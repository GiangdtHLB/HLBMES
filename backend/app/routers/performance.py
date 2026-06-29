"""OEE đóng gói (tài liệu §7.7)."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..common import Role, new_id, utcnow
from ..database import get_db
from ..models.metrics import OEERecord
from ..schemas import OEEIn, OEEOut
from ..security import User, get_current_user, require_role
from ..services.performance import compute_oee

router = APIRouter(prefix="/api/oee", tags=["performance"],
                   dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[OEEOut])
def list_oee(line: str = None, db: Session = Depends(get_db)):
    stmt = select(OEERecord)
    if line:
        stmt = stmt.where(OEERecord.line == line)
    recs = db.execute(stmt.order_by(OEERecord.shift_date.desc())).scalars().all()
    return [compute_oee(r) for r in recs]


@router.post("", response_model=OEEOut, status_code=201)
def create_oee(payload: OEEIn, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    require_role(user, Role.SUPERVISOR, Role.OPERATOR)
    rec = OEERecord(
        oee_id=new_id(),
        line=payload.line,
        shift=payload.shift,
        shift_date=payload.shift_date or utcnow(),
        planned_time_min=payload.planned_time_min,
        downtime_min=payload.downtime_min,
        ideal_rate_per_min=payload.ideal_rate_per_min,
        total_count=payload.total_count,
        good_count=payload.good_count,
        downtime_reasons=payload.downtime_reasons,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return compute_oee(rec)
