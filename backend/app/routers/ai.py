"""Lớp AI: trợ lý chat + AI vận hành (advisory) + manifest tool cho agent."""

from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import LLM_MODEL
from ..database import get_db
from ..security import User, get_current_user
from ..services import ai, ai_tools, conversations

router = APIRouter(prefix="/api/ai", tags=["ai"])


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list = Field(default_factory=list, max_length=20)   # giữ tương thích client cũ
    conversation_id: Optional[str] = None


@router.get("/status")
def status():
    return {"llm_available": ai.llm_available(), "model": LLM_MODEL,
            "advisory_only": True, "tools": list(ai_tools.TOOLS.keys())}


@router.post("/chat")
def chat(payload: ChatIn, db: Session = Depends(get_db),
         user: User = Depends(get_current_user)):
    """Chat có bộ nhớ: lưu/nạp lịch sử theo conversation_id (phía server)."""
    return conversations.chat_with_memory(db, user, payload.message, payload.conversation_id)


@router.post("/chat/stream")
def chat_stream(payload: ChatIn, user: User = Depends(get_current_user)):
    """Chat streaming (SSE): token hiện dần + sự kiện tool, vẫn lưu ConversationMemory.

    Tiêu thụ bằng fetch() + ReadableStream (hỗ trợ gửi header Authorization)."""
    gen = conversations.stream_chat_with_memory(user, payload.message, payload.conversation_id)
    return StreamingResponse(gen, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/conversations")
def list_conversations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return conversations.list_conversations(db, user.username)


@router.get("/conversations/{conv_id}")
def get_conversation(conv_id: str, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    return conversations.get_messages(db, conv_id, user.username)


@router.delete("/conversations/{conv_id}")
def delete_conversation(conv_id: str, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    return conversations.delete_conversation(db, conv_id, user.username)


@router.get("/insights")
def insights(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """AI vận hành: cảnh báo & đề xuất tư vấn (human-in-the-loop)."""
    return ai.operational_insights(db)


@router.get("/tools")
def tools_manifest(user: User = Depends(get_current_user)):
    """Manifest tool cho AI agent / MCP tương lai khám phá năng lực MES."""
    return {
        "name": "mes-brewery-tools",
        "description": "Read-only MES tools cho nhà máy bia (advisory).",
        "advisory_only": True,
        "tools": [{"name": n, "description": t["description"],
                   "input_schema": t["input_schema"],
                   "endpoint": "/api/ai/chat (gọi gián tiếp qua trợ lý) hoặc dùng /api/v1"}
                  for n, t in ai_tools.TOOLS.items()],
    }
