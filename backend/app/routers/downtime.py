"""Downtime: reason-tree, ghi sự kiện dừng, Pareto, 6 big losses, MTBF/MTTR (§7.7)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import DowntimeIn
from ..security import User, get_current_user
from ..services import downtime as svc

router = APIRouter(prefix="/api/downtime", tags=["downtime"])


@router.get("/reason-tree")
def reason_tree(user: User = Depends(get_current_user)):
    return svc.reason_tree()


@router.get("")
def list_events(line: str = None, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    return svc.list_events(db, line)


@router.post("", status_code=201)
def record(payload: DowntimeIn, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    ev = svc.record_downtime(db, payload.model_dump(), user)
    return {"event_id": ev.event_id, "line": ev.line, "minutes": ev.minutes,
            "reason_label": ev.reason_label, "loss_category": ev.loss_category}


@router.get("/pareto")
def pareto(line: str = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.pareto(db, line)


@router.get("/big-losses")
def big_losses(line: str = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.big_losses(db, line)


@router.get("/mtbf")
def mtbf(days: int = 30, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.mtbf_mttr(db, days)
