"""Quality results, hold/release, deviations."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.quality import Deviation, QualityResult
from ..schemas import (
    DeviationIn,
    DeviationOut,
    DeviationTransitionIn,
    HoldIn,
    ResultIn,
    ResultOut,
)
from ..security import User, get_current_user, require_perm
from ..services import quality as svc

router = APIRouter(prefix="/api/quality", tags=["quality"])


@router.get("/results", response_model=list[ResultOut])
def list_results(scope_id: str = None, db: Session = Depends(get_db)):
    stmt = select(QualityResult).order_by(QualityResult.recorded_at.desc())
    if scope_id:
        stmt = stmt.where(QualityResult.scope_id == scope_id)
    return db.execute(stmt).scalars().all()


@router.post("/results", response_model=ResultOut, status_code=201)
def record_result(payload: ResultIn, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    return svc.record_result(db, payload.model_dump(), user)


@router.post("/hold")
def set_hold(payload: HoldIn, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    if not payload.on_hold:
        require_perm(user, "quality.release")
    return svc.set_hold(db, payload.scope_type, payload.scope_id, payload.on_hold,
                        user, payload.reason)


@router.get("/deviations", response_model=list[DeviationOut])
def list_deviations(db: Session = Depends(get_db)):
    return db.execute(select(Deviation).order_by(Deviation.opened_at.desc())).scalars().all()


@router.post("/deviations", response_model=DeviationOut, status_code=201)
def open_deviation(payload: DeviationIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    require_perm(user, "quality.deviation")
    return svc.open_deviation(db, payload.model_dump(), user)


@router.post("/deviations/{deviation_id}/transition", response_model=DeviationOut)
def transition_deviation(deviation_id: str, payload: DeviationTransitionIn,
                         db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.transition_deviation(db, deviation_id, payload.target, user,
                                    payload.model_dump())
