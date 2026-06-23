"""Lập lịch sản xuất (tank/CIP/maintenance/material) + Gantt (P3-2)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import AutoScheduleIn
from ..security import User, get_current_user, require_perm
from ..services import scheduler as svc

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


@router.get("")
def board(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.board(db)


@router.get("/conflicts")
def conflicts(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.conflicts(db)


@router.post("/auto")
def auto(payload: AutoScheduleIn, db: Session = Depends(get_db),
         user: User = Depends(get_current_user)):
    require_perm(user, "wo.dispatch")
    return svc.auto_schedule(db, user, payload.days, payload.prod_hours, payload.cip_hours)
