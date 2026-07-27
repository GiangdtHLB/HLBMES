"""CIP (vệ sinh thiết bị) — danh mục loại biểu mẫu/thiết bị, khai báo + nghiệm thu, và
gắn tay với mẻ/lô sản xuất."""

from fastapi import APIRouter, Depends

from ..database import get_db
from ..schemas import (
    CipApproveIn,
    CipEquipmentIn,
    CipEquipmentOut,
    CipFormTypeIn,
    CipFormTypeOut,
    CipLinkIn,
    CipRecordIn,
    CipRecordOut,
)
from ..security import User, get_current_user
from ..services import cip as svc
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/cip", tags=["cip"])


# ---- Danh mục loại biểu mẫu ----

@router.get("/form-types", response_model=list[CipFormTypeOut])
def list_form_types(area: str = None, active_only: bool = True, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    return svc.list_form_types(db, area=area, active_only=active_only)


@router.post("/form-types", response_model=CipFormTypeOut, status_code=201)
def create_form_type(payload: CipFormTypeIn, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    return svc.create_form_type(db, payload.model_dump(), user)


@router.put("/form-types/{form_type_id}", response_model=CipFormTypeOut)
def update_form_type(form_type_id: str, payload: CipFormTypeIn, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    return svc.update_form_type(db, form_type_id, payload.model_dump(), user)


@router.delete("/form-types/{form_type_id}", status_code=204)
def delete_form_type(form_type_id: str, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    svc.delete_form_type(db, form_type_id, user)


# ---- Danh mục thiết bị ----

@router.get("/equipment", response_model=list[CipEquipmentOut])
def list_equipment(area: str = None, active_only: bool = True, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    return svc.list_equipment(db, area=area, active_only=active_only)


@router.post("/equipment", response_model=CipEquipmentOut, status_code=201)
def create_equipment(payload: CipEquipmentIn, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    return svc.create_equipment(db, payload.model_dump(), user)


@router.put("/equipment/{equipment_id}", response_model=CipEquipmentOut)
def update_equipment(equipment_id: str, payload: CipEquipmentIn, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    return svc.update_equipment(db, equipment_id, payload.model_dump(), user)


@router.delete("/equipment/{equipment_id}", status_code=204)
def delete_equipment(equipment_id: str, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    svc.delete_equipment(db, equipment_id, user)


# ---- Bản ghi CIP ----

@router.get("/records")
def list_records(equipment_id: str = None, form_type_id: str = None, area: str = None,
                 result: str = None, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    return svc.list_records(db, equipment_id=equipment_id, form_type_id=form_type_id,
                            area=area, result=result)


@router.post("/records", response_model=CipRecordOut, status_code=201)
def create_record(payload: CipRecordIn, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    return svc.create_record(db, payload.model_dump(), user)


@router.get("/records/{cip_id}", response_model=CipRecordOut)
def get_record(cip_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.get_record(db, cip_id)


@router.put("/records/{cip_id}", response_model=CipRecordOut)
def update_record(cip_id: str, payload: CipRecordIn, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    return svc.update_record(db, cip_id, payload.model_dump(), user)


@router.post("/records/{cip_id}/approve", response_model=CipRecordOut)
def approve_record(cip_id: str, payload: CipApproveIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    return svc.approve_record(db, cip_id, payload.model_dump(), user)


# ---- Gợi ý + gắn tay với mẻ/lô sản xuất ----

@router.get("/suggest")
def suggest_for_scope(scope_type: str, scope_id: str, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    return svc.suggest_for_scope(db, scope_type, scope_id)


@router.get("/links")
def links_for(scope_type: str, scope_id: str, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    return svc.links_for(db, scope_type, scope_id)


@router.post("/links", status_code=201)
def link_records(payload: CipLinkIn, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    created = svc.link_records(db, payload.scope_type, payload.scope_id, payload.cip_ids, user)
    return {"linked": len(created)}


@router.delete("/links/{link_id}", status_code=204)
def unlink(link_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    svc.unlink(db, link_id, user)
