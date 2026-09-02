"""Danh mục "Tham số quy trình" (setpoint công nghệ) — mirror đúng cấu trúc endpoint của
routers/quality_adv.py (danh mục chỉ tiêu chất lượng), xem services/param_catalog.py."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import (
    ProcessParameterGroupCopyItemsIn,
    ProcessParameterGroupIn,
    ProcessParameterGroupItemIn,
    ProcessParameterGroupOut,
    ProcessParameterIn,
    ProcessParameterOut,
)
from ..security import User, get_current_user
from ..services import param_catalog as svc

router = APIRouter(prefix="/api/process-params", tags=["process-params"])


# ---- Tham số ----
@router.get("/parameters")
def list_parameters(active_only: bool = True, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    return svc.list_parameters(db, active_only)


@router.post("/parameters", response_model=ProcessParameterOut, status_code=201)
def create_parameter(payload: ProcessParameterIn, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    return svc.create_parameter(db, payload.model_dump(), user)


@router.put("/parameters/{param_id}", response_model=ProcessParameterOut)
def update_parameter(param_id: str, payload: ProcessParameterIn, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    return svc.update_parameter(db, param_id, payload.model_dump(), user)


@router.delete("/parameters/{param_id}", status_code=204)
def delete_parameter(param_id: str, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    svc.delete_parameter(db, param_id, user)


# ---- Nhóm tham số ----
@router.get("/groups", response_model=list[ProcessParameterGroupOut])
def list_groups(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.list_groups(db)


@router.post("/groups", response_model=ProcessParameterGroupOut, status_code=201)
def create_group(payload: ProcessParameterGroupIn, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    return svc.create_group(db, payload.model_dump(), user)


@router.put("/groups/{group_id}", response_model=ProcessParameterGroupOut)
def update_group(group_id: str, payload: ProcessParameterGroupIn, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    return svc.update_group(db, group_id, payload.model_dump(), user)


@router.delete("/groups/{group_id}", status_code=204)
def delete_group(group_id: str, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    svc.delete_group(db, group_id, user)


@router.get("/groups/{group_id}/items")
def list_group_items(group_id: str, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    return svc.list_items(db, group_id)


@router.post("/groups/{group_id}/items", status_code=201)
def add_group_item(group_id: str, payload: ProcessParameterGroupItemIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    return svc.add_item(db, group_id, payload.model_dump(), user)


@router.put("/groups/{group_id}/items/{item_id}")
def update_group_item(group_id: str, item_id: str, payload: ProcessParameterGroupItemIn,
                      db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.update_item(db, item_id, payload.model_dump(), user)


@router.delete("/groups/{group_id}/items/{item_id}", status_code=204)
def delete_group_item(group_id: str, item_id: str, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    svc.delete_item(db, item_id, user)


@router.post("/groups/{group_id}/items/copy")
def copy_group_items(group_id: str, payload: ProcessParameterGroupCopyItemsIn, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    return svc.copy_items(db, group_id, payload.source_group_id, user)
