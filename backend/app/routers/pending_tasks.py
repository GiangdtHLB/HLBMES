"""Việc cần làm — API cho chuông thông báo, xem services/pending_tasks.py."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..security import User, get_current_user
from ..services import pending_tasks as svc

router = APIRouter(prefix="/api/pending-tasks", tags=["pending-tasks"])


@router.get("")
def get_pending_tasks(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    items = svc.get_pending_tasks(db, user)
    return {"total": sum(i["count"] for i in items), "items": items}
