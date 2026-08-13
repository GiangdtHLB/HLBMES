"""RCFA (Root Cause Failure Analysis) + 5 Whys cho sự cố dừng máy — mirror sheet RCFA/5Whys
của file "OPI - CAN L3 (KHS 30K).xlsx"."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import OeeRcfaIn, OeeRcfaRecheckIn
from ..security import User, get_current_user
from ..services import oee_rcfa as svc

router = APIRouter(prefix="/api/rcfa", tags=["oee-rcfa"])


@router.get("")
def list_rcfa(line_code: str = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.list_rcfa(db, line_code)


@router.post("", status_code=201)
def create_rcfa(payload: OeeRcfaIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rec = svc.create_rcfa(db, payload.model_dump(), user)
    return {"rcfa_id": rec.rcfa_id, "rcfa_no": rec.rcfa_no}


@router.get("/{rcfa_id}")
def get_rcfa(rcfa_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rec = svc.get_rcfa(db, rcfa_id)
    return {"rcfa_id": rec.rcfa_id, "rcfa_no": rec.rcfa_no, "line_code": rec.line_code,
            "machine": rec.machine, "part": rec.part, "stop_at": rec.stop_at,
            "duration_min": rec.duration_min, "failure_function": rec.failure_function,
            "prior_signs": rec.prior_signs, "technician": rec.technician, "repair_min": rec.repair_min,
            "wait_min": rec.wait_min, "description": rec.description, "replaced_parts": rec.replaced_parts,
            "working_principle": rec.working_principle, "failure_mechanism": rec.failure_mechanism,
            "analyst": rec.analyst, "factor": rec.factor, "five_whys": rec.five_whys,
            "category_4m1e": rec.category_4m1e, "corrective_action": rec.corrective_action,
            "preventive_action": rec.preventive_action, "executor": rec.executor,
            "complete_date": rec.complete_date, "checker": rec.checker,
            "recheck_schedule": rec.recheck_schedule}


@router.put("/{rcfa_id}")
def update_rcfa(rcfa_id: str, payload: OeeRcfaIn, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    rec = svc.update_rcfa(db, rcfa_id, payload.model_dump(exclude_unset=True), user)
    return {"rcfa_id": rec.rcfa_id}


@router.put("/{rcfa_id}/recheck")
def update_recheck(rcfa_id: str, payload: OeeRcfaRecheckIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    rec = svc.update_recheck(db, rcfa_id, payload.week_offset, payload.checked, payload.note, user)
    return {"rcfa_id": rec.rcfa_id, "recheck_schedule": rec.recheck_schedule}
