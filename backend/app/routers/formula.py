"""Công thức nguyên vật liệu mới theo dịch bia — xem models/formula.py + services/formula.py.
Thay thế /api/recipes (Recipe/RecipeVersion) cho màn hình Công thức đang dùng thực tế;
/api/recipes vẫn giữ nguyên cho Công thức+ (nav-unused) — không đụng."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import FormulaActivationLogOut, FormulaIn, FormulaOut
from ..security import User, get_current_user
from ..services import formula as svc

router = APIRouter(prefix="/api/formulas", tags=["formulas"],
                   dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[FormulaOut])
def list_formulas(product_id: str = None, db: Session = Depends(get_db)):
    return svc.list_formulas(db, product_id)


@router.get("/activation-log", response_model=list[FormulaActivationLogOut])
def list_activation_log(product_id: str, db: Session = Depends(get_db)):
    return svc.list_activation_log(db, product_id)


@router.get("/{formula_id}", response_model=FormulaOut)
def get_formula(formula_id: str, db: Session = Depends(get_db)):
    return svc.get_formula(db, formula_id)


@router.post("", response_model=FormulaOut, status_code=201)
def create_formula(payload: FormulaIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    return svc.create_formula(db, payload.model_dump(), user)


@router.put("/{formula_id}", response_model=FormulaOut)
def update_formula(formula_id: str, payload: FormulaIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    return svc.update_formula(db, formula_id, payload.model_dump(), user)


@router.post("/{formula_id}/activate", response_model=FormulaOut)
def activate_formula(formula_id: str, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    return svc.activate_formula(db, formula_id, user)


@router.post("/{formula_id}/deactivate", response_model=FormulaOut)
def deactivate_formula(formula_id: str, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    return svc.deactivate_formula(db, formula_id, user)


@router.post("/{formula_id}/lock", response_model=FormulaOut)
def lock_formula(formula_id: str, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    return svc.lock_formula(db, formula_id, user)


@router.post("/{formula_id}/unlock", response_model=FormulaOut)
def unlock_formula(formula_id: str, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    return svc.unlock_formula(db, formula_id, user)


@router.delete("/{formula_id}", status_code=204)
def delete_formula(formula_id: str, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    svc.delete_formula(db, formula_id, user)
