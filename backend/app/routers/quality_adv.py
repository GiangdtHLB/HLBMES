"""Quality hardcore: SPC control chart, CAPA, COA, LIMS-lite (§7.5)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import CapaIn, CapaTransitionIn, SampleIn, SampleTransitionIn
from ..security import User, get_current_user, require_perm
from ..services import quality_adv as svc

router = APIRouter(prefix="/api/qc", tags=["quality-adv"])


# ---- SPC ----
@router.get("/parameters")
def qc_parameters(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.list_qc_parameters(db)


@router.get("/spc")
def spc(parameter: str, scope_type: str = None, db: Session = Depends(get_db),
        user: User = Depends(get_current_user)):
    return svc.spc_chart(db, parameter, scope_type)


# ---- CAPA ----
@router.get("/capa")
def list_capa(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.list_capa(db)


@router.post("/capa", status_code=201)
def open_capa(payload: CapaIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = svc.open_capa(db, payload.model_dump(), user)
    return {"capa_code": c.capa_code, "capa_id": c.capa_id, "state": c.state}


@router.post("/capa/{capa_id}/transition")
def transition_capa(capa_id: str, payload: CapaTransitionIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    c = svc.transition_capa(db, capa_id, payload.target, user, payload.model_dump())
    return {"capa_code": c.capa_code, "state": c.state}


# ---- COA ----
@router.get("/coa/{batch_id}")
def coa(batch_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.coa(db, batch_id)


# ---- LIMS-lite ----
@router.get("/samples")
def list_samples(scope_id: str = None, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    return svc.list_samples(db, scope_id)


@router.post("/samples", status_code=201)
def register_sample(payload: SampleIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    s = svc.register_sample(db, payload.model_dump(), user)
    return {"sample_code": s.sample_code, "sample_id": s.sample_id, "status": s.status}


@router.post("/samples/{sample_id}/transition")
def transition_sample(sample_id: str, payload: SampleTransitionIn, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    s = svc.transition_sample(db, sample_id, payload.target, user)
    return {"sample_code": s.sample_code, "status": s.status}
