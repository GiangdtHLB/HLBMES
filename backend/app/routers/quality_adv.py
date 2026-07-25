"""Quality hardcore: SPC control chart, CAPA, COA, LIMS-lite (§7.5)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import (
    CapaIn,
    CapaTransitionIn,
    QcGroupCopyItemsIn,
    QcGroupIn,
    QcGroupItemIn,
    QcGroupOut,
    QcParameterIn,
    QcParameterOut,
    SampleIn,
    SampleTransitionIn,
    StageQcGroupIn,
)
from ..security import User, get_current_user
from ..services import qc_catalog, quality_adv as svc

router = APIRouter(prefix="/api/qc", tags=["quality-adv"])


# ---- SPC / danh mục chỉ tiêu ----
@router.get("/parameters")
def qc_parameters(active_only: bool = True, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    return svc.list_qc_parameters(db, active_only)


@router.post("/parameters", response_model=QcParameterOut, status_code=201)
def create_qc_parameter(payload: QcParameterIn, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    return svc.create_qc_parameter(db, payload.model_dump(), user)


@router.put("/parameters/{param_id}", response_model=QcParameterOut)
def update_qc_parameter(param_id: str, payload: QcParameterIn, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    return svc.update_qc_parameter(db, param_id, payload.model_dump(), user)


# ---- Nhóm chỉ tiêu chất lượng NVL ----
@router.get("/groups", response_model=list[QcGroupOut])
def list_qc_groups(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return qc_catalog.list_groups(db)


@router.post("/groups", response_model=QcGroupOut, status_code=201)
def create_qc_group(payload: QcGroupIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    return qc_catalog.create_group(db, payload.model_dump(), user)


@router.put("/groups/{group_id}", response_model=QcGroupOut)
def update_qc_group(group_id: str, payload: QcGroupIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    return qc_catalog.update_group(db, group_id, payload.model_dump(), user)


@router.delete("/groups/{group_id}", status_code=204)
def delete_qc_group(group_id: str, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    qc_catalog.delete_group(db, group_id, user)


@router.get("/groups/{group_id}/items")
def list_qc_group_items(group_id: str, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    return qc_catalog.list_items(db, group_id)


@router.post("/groups/{group_id}/items", status_code=201)
def add_qc_group_item(group_id: str, payload: QcGroupItemIn, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    return qc_catalog.add_item(db, group_id, payload.model_dump(), user)


@router.put("/groups/{group_id}/items/{item_id}")
def update_qc_group_item(group_id: str, item_id: str, payload: QcGroupItemIn,
                         db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return qc_catalog.update_item(db, item_id, payload.model_dump(), user)


@router.delete("/groups/{group_id}/items/{item_id}", status_code=204)
def delete_qc_group_item(group_id: str, item_id: str, db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    qc_catalog.delete_item(db, item_id, user)


@router.post("/groups/{group_id}/items/copy")
def copy_qc_group_items(group_id: str, payload: QcGroupCopyItemsIn, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    return qc_catalog.copy_items(db, group_id, payload.source_group_id, user)


# ---- Gán nhóm chỉ tiêu cho công đoạn sản xuất (mẻ nấu/lên men/lọc/chiết) ----
@router.get("/stage-groups")
def list_stage_qc_groups(stage: str = None, db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    return qc_catalog.list_stage_groups(db, stage)


@router.post("/stage-groups", status_code=201)
def link_stage_qc_group(payload: StageQcGroupIn, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    return qc_catalog.link_stage_group(db, payload.model_dump(), user)


@router.put("/stage-groups/{link_id}")
def update_stage_qc_group(link_id: str, payload: StageQcGroupIn, db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    return qc_catalog.update_stage_group(db, link_id, payload.model_dump(), user)


@router.delete("/stage-groups/{link_id}", status_code=204)
def unlink_stage_qc_group(link_id: str, db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    qc_catalog.unlink_stage_group(db, link_id, user)


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
