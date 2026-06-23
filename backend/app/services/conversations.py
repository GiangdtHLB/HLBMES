"""Bộ nhớ hội thoại AI phía server (P2).

Lưu hội thoại + từng lượt vào DB để lịch sử bền vững (không mất khi tải lại/đổi máy)
và làm nền cho AI agent. Chat luôn gắn với một AiConversation của người dùng.
"""

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..common import new_id, utcnow
from ..database import SessionLocal
from ..errors import NotFoundError, PermissionError_
from ..logging_config import get_logger
from ..models.ai_memory import AiConversation, AiMessage
from ..security import User
from . import ai

log = get_logger("mes.ai")
_HISTORY_TURNS = 8   # số lượt gần nhất nạp làm ngữ cảnh cho LLM


def list_conversations(db: Session, username: str) -> list:
    rows = db.execute(select(AiConversation).where(AiConversation.username == username)
                      .order_by(AiConversation.updated_at.desc())).scalars().all()
    out = []
    for c in rows:
        n = db.execute(select(func.count(AiMessage.msg_id)).where(
            AiMessage.conv_id == c.conv_id)).scalar() or 0
        out.append({"conv_id": c.conv_id, "title": c.title, "messages": n,
                    "created_at": c.created_at, "updated_at": c.updated_at})
    return out


def _owned(db: Session, conv_id: str, username: str) -> AiConversation:
    c = db.get(AiConversation, conv_id)
    if not c:
        raise NotFoundError("Hội thoại không tồn tại.")
    if c.username != username:
        raise PermissionError_("Không có quyền truy cập hội thoại của người khác.")
    return c


def get_messages(db: Session, conv_id: str, username: str) -> dict:
    c = _owned(db, conv_id, username)
    msgs = db.execute(select(AiMessage).where(AiMessage.conv_id == conv_id)
                      .order_by(AiMessage.seq)).scalars().all()
    return {"conv_id": c.conv_id, "title": c.title,
            "messages": [{"role": m.role, "content": m.content, "tools_used": m.tools_used,
                          "mode": m.mode, "created_at": m.created_at} for m in msgs]}


def delete_conversation(db: Session, conv_id: str, username: str) -> dict:
    c = _owned(db, conv_id, username)
    db.execute(AiMessage.__table__.delete().where(AiMessage.conv_id == conv_id))
    db.delete(c)
    db.commit()
    return {"deleted": True, "conv_id": conv_id}


def _append(db: Session, conv_id: str, role: str, content: str,
            tools: list = None, mode: str = None) -> None:
    seq = (db.execute(select(func.max(AiMessage.seq)).where(
        AiMessage.conv_id == conv_id)).scalar() or 0) + 1
    db.add(AiMessage(msg_id=new_id(), conv_id=conv_id, seq=seq, role=role, content=content,
                     tools_used=",".join(tools) if tools else None, mode=mode))


def chat_with_memory(db: Session, user: User, message: str, conversation_id: str = None) -> dict:
    """Tạo/nối hội thoại: nạp lịch sử từ DB làm ngữ cảnh, gọi AI, lưu cả 2 lượt."""
    if conversation_id:
        conv = _owned(db, conversation_id, user.username)
    else:
        title = (message or "Hội thoại mới").strip()[:60]
        conv = AiConversation(conv_id=new_id(), username=user.username, title=title,
                              created_at=utcnow(), updated_at=utcnow())
        db.add(conv)
        db.flush()

    prior = db.execute(select(AiMessage).where(AiMessage.conv_id == conv.conv_id)
                       .order_by(AiMessage.seq)).scalars().all()
    history = [{"role": m.role, "content": m.content} for m in prior][-_HISTORY_TURNS:]

    result = ai.chat(db, message, history)   # engine luật hoặc Claude (đã có sẵn)

    _append(db, conv.conv_id, "user", message)
    _append(db, conv.conv_id, "assistant", result.get("answer", ""),
            tools=result.get("tools_used"), mode=result.get("mode"))
    conv.updated_at = utcnow()
    db.commit()
    return {**result, "conversation_id": conv.conv_id, "title": conv.title}


def _sse(obj: dict) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


def stream_chat_with_memory(user: User, message: str, conversation_id: str = None):
    """Generator SSE: tạo/nối hội thoại, stream token từ AI, lưu cả 2 lượt khi xong.

    Tự mở SessionLocal riêng (an toàn cho StreamingResponse — không phụ thuộc get_db
    đóng sớm). Phát: meta → delta*/tool* → done (hoặc error)."""
    db = SessionLocal()
    try:
        if conversation_id:
            conv = _owned(db, conversation_id, user.username)
        else:
            title = (message or "Hội thoại mới").strip()[:60]
            conv = AiConversation(conv_id=new_id(), username=user.username, title=title,
                                  created_at=utcnow(), updated_at=utcnow())
            db.add(conv)
            db.flush()
        prior = db.execute(select(AiMessage).where(AiMessage.conv_id == conv.conv_id)
                           .order_by(AiMessage.seq)).scalars().all()
        history = [{"role": m.role, "content": m.content} for m in prior][-_HISTORY_TURNS:]

        yield _sse({"type": "meta", "conversation_id": conv.conv_id, "title": conv.title})
        parts, tools, mode = [], [], None
        for ev in ai.stream_chat(db, message, history):
            if ev["type"] == "delta":
                parts.append(ev["text"])
                yield _sse(ev)
            elif ev["type"] == "tool":
                tools.append(ev["name"])
                yield _sse(ev)
            elif ev["type"] == "final":
                mode = ev.get("mode")
                if ev.get("tools_used"):
                    tools = ev["tools_used"]
        answer = "".join(parts).strip() or "(không có nội dung)"
        _append(db, conv.conv_id, "user", message)
        _append(db, conv.conv_id, "assistant", answer, tools=tools, mode=mode)
        conv.updated_at = utcnow()
        db.commit()
        yield _sse({"type": "done", "conversation_id": conv.conv_id, "title": conv.title,
                    "answer": answer, "tools_used": tools, "mode": mode})
    except Exception as e:  # noqa: BLE001
        log.warning("stream_chat lỗi: %s", e, exc_info=True)
        yield _sse({"type": "error", "detail": str(e)})
    finally:
        db.close()
