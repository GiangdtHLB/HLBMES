"""Lớp AI: trợ lý chat + AI vận hành (advisory) + manifest tool cho agent."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import LLM_MODEL
from ..database import get_db
from ..security import User, get_current_user
from ..services import ai, ai_tools

router = APIRouter(prefix="/api/ai", tags=["ai"])


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list = Field(default_factory=list, max_length=20)


@router.get("/status")
def status():
    return {"llm_available": ai.llm_available(), "model": LLM_MODEL,
            "advisory_only": True, "tools": list(ai_tools.TOOLS.keys())}


@router.post("/chat")
def chat(payload: ChatIn, db: Session = Depends(get_db),
         user: User = Depends(get_current_user)):
    return ai.chat(db, payload.message, payload.history)


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
