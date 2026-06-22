"""Lớp AI: trợ lý chat + AI vận hành (advisory) + manifest tool cho agent."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import LLM_MODEL
from ..database import get_db
from ..services import ai, ai_tools

router = APIRouter(prefix="/api/ai", tags=["ai"])


class ChatIn(BaseModel):
    message: str
    history: list = []


@router.get("/status")
def status():
    return {"llm_available": ai.llm_available(), "model": LLM_MODEL,
            "advisory_only": True, "tools": list(ai_tools.TOOLS.keys())}


@router.post("/chat")
def chat(payload: ChatIn, db: Session = Depends(get_db)):
    return ai.chat(db, payload.message, payload.history)


@router.get("/insights")
def insights(db: Session = Depends(get_db)):
    """AI vận hành: cảnh báo & đề xuất tư vấn (human-in-the-loop)."""
    return ai.operational_insights(db)


@router.get("/tools")
def tools_manifest():
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
