"""ISA-88 procedural: xem thủ tục recipe + thực thi phase theo mẻ (§7.2)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import PhaseStartIn, PhaseTransitionIn
from ..security import User, get_current_user, require_perm
from ..services import isa88 as svc

router = APIRouter(prefix="/api/isa88", tags=["isa88"])


@router.get("/recipe/{version_id}")
def recipe_procedure(version_id: str, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    return svc.recipe_procedure(db, version_id)


@router.get("/batch/{batch_id}")
def batch_status(batch_id: str, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    return svc.status(db, batch_id)


@router.post("/batch/{batch_id}/start")
def start_phase(batch_id: str, payload: PhaseStartIn, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    require_perm(user, "batch.execute")
    return svc.start_phase(db, batch_id, payload.up, payload.op, payload.phase, user)


@router.post("/phase/{run_id}/transition")
def transition_phase(run_id: str, payload: PhaseTransitionIn, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    require_perm(user, "batch.execute")
    return svc.transition_phase(db, run_id, payload.target, user, payload.values)
