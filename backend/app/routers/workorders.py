"""Lệnh sản xuất (Work Order) & điều độ."""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.workorder import WorkOrder
from ..errors import NotFoundError
from ..schemas import WorkOrderIn, WoDispatchIn, TransitionIn
from ..security import User, get_current_user
from ..services import workorders as svc

router = APIRouter(prefix="/api/workorders", tags=["workorders"])


@router.get("")
def list_board(date_from: date = None, date_to: date = None, line: str = None,
               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.board(db, date_from, date_to, line)


@router.get("/{wo_id}")
def get_wo(wo_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    wo = db.get(WorkOrder, wo_id)
    if not wo:
        raise NotFoundError("Lệnh sản xuất không tồn tại.")
    return {**{c.name: getattr(wo, c.name) for c in wo.__table__.columns},
            "rollup": svc.rollup(db, wo)}


@router.post("", status_code=201)
def create_wo(payload: WorkOrderIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    wo = svc.create_wo(db, payload.model_dump(), user)
    return {"wo_id": wo.wo_id, "wo_code": wo.wo_code, "status": wo.status}


@router.post("/{wo_id}/transition")
def transition(wo_id: str, payload: TransitionIn, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    wo = svc.transition(db, wo_id, payload.target, user, payload.reason)
    return {"wo_id": wo.wo_id, "status": wo.status}


@router.post("/{wo_id}/dispatch")
def dispatch(wo_id: str, payload: WoDispatchIn, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    return svc.dispatch(db, wo_id, user, payload.recipe_version_id, payload.batch_code,
                        payload.planned_qty, payload.allow_shortage)
