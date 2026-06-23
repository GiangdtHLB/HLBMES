"""Bộ nhớ hội thoại AI (P2 — nền tảng AI agent).

Trước đây lịch sử chat chỉ giữ ở client (mất khi tải lại / đổi máy). Lưu phía server:
- AiConversation: một phiên hội thoại của một người dùng.
- AiMessage: từng lượt (user/assistant) trong hội thoại, kèm tool đã dùng + token.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..common import new_id, utcnow
from ..database import Base


class AiConversation(Base):
    __tablename__ = "ai_conversation"

    conv_id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String, index=True)   # chủ sở hữu hội thoại
    title: Mapped[str] = mapped_column(String, default="Hội thoại mới")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AiMessage(Base):
    __tablename__ = "ai_message"

    msg_id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    conv_id: Mapped[str] = mapped_column(ForeignKey("ai_conversation.conv_id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)        # thứ tự trong hội thoại
    role: Mapped[str] = mapped_column(String)                   # user | assistant
    content: Mapped[str] = mapped_column(Text)
    tools_used: Mapped[Optional[str]] = mapped_column(String, nullable=True)   # csv
    mode: Mapped[Optional[str]] = mapped_column(String, nullable=True)         # claude:* | local
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
