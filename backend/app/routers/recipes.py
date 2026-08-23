"""Recipes + versions (workflow, SoD)."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..common import new_id
from ..database import get_db
from ..errors import DomainError, NotFoundError
from ..models.recipes import Recipe, RecipeVersion
from ..schemas import (
    ChangeApproveIn,
    RecipeIn,
    RecipeOut,
    RecipeVersionIn,
    RecipeVersionOut,
    TransitionIn,
)
from ..security import User, get_current_user, require_perm
from ..services import master_data
from ..services import recipes as svc

router = APIRouter(prefix="/api/recipes", tags=["recipes"],
                   dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[RecipeOut])
def list_recipes(db: Session = Depends(get_db)):
    return db.execute(select(Recipe).order_by(Recipe.code)).scalars().all()


@router.post("", response_model=RecipeOut, status_code=201)
def create_recipe(payload: RecipeIn, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    require_perm(user, "recipe.author")
    if db.execute(select(Recipe).where(Recipe.beer_type_id == payload.beer_type_id)).scalar_one_or_none():
        raise DomainError("Loại bia này đã có công thức — mỗi loại bia chỉ được 1 công thức "
                           "(tạo version mới trong công thức đã có, chọn đúng dịch bia, thay vì "
                           "tạo công thức khác).")
    r = Recipe(recipe_id=new_id(), **payload.model_dump())
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


@router.delete("/{recipe_id}", status_code=204)
def delete_recipe(recipe_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    master_data.delete_recipe(db, recipe_id, user)


@router.get("/{recipe_id}/versions", response_model=list[RecipeVersionOut])
def list_versions(recipe_id: str, db: Session = Depends(get_db)):
    versions = db.execute(
        select(RecipeVersion).where(RecipeVersion.recipe_id == recipe_id)
        .order_by(RecipeVersion.version_no)
    ).scalars().all()
    used_ids = master_data.used_recipe_version_ids(db, [v.version_id for v in versions])
    for v in versions:
        v.is_used = v.version_id in used_ids
    return versions


@router.post("/{recipe_id}/versions", response_model=RecipeVersionOut, status_code=201)
def create_version(recipe_id: str, payload: RecipeVersionIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    require_perm(user, "recipe.author")
    return svc.create_version(db, recipe_id, payload.model_dump(), user)


@router.put("/versions/{version_id}", response_model=RecipeVersionOut)
def update_version(version_id: str, payload: RecipeVersionIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    require_perm(user, "recipe.author")
    return svc.update_draft(db, version_id, payload.model_dump(), user)


@router.post("/versions/{version_id}/transition", response_model=RecipeVersionOut)
def transition_version(version_id: str, payload: TransitionIn, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    require_perm(user, "recipe.approve")
    return svc.transition(db, version_id, payload.target, user, payload.reason)


@router.get("/versions/{version_id}", response_model=RecipeVersionOut)
def get_version(version_id: str, db: Session = Depends(get_db)):
    rv = db.get(RecipeVersion, version_id)
    if not rv:
        raise NotFoundError("Recipe version không tồn tại.")
    return rv


@router.delete("/versions/{version_id}", status_code=204)
def delete_version(version_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    master_data.delete_recipe_version(db, version_id, user)


# ---- Change-control (e-signature) + diff + danh sách thay đổi ----
@router.post("/versions/{version_id}/change-approve")
def change_approve(version_id: str, payload: ChangeApproveIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """Duyệt thay đổi công thức bằng chữ ký điện tử (re-auth + lý do bắt buộc)."""
    require_perm(user, "recipe.approve")
    return svc.approve_with_signature(db, version_id, user, payload.password, payload.change_reason)


@router.get("/diff")
def diff(va: str, vb: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """So sánh 2 recipe version (va=cũ, vb=mới)."""
    return svc.diff_versions(db, va, vb)


@router.get("/changes")
def list_changes(recipe_id: str = None, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    from ..models.recipe_ext import RecipeChange
    stmt = select(RecipeChange).order_by(RecipeChange.created_at.desc())
    if recipe_id:
        stmt = stmt.where(RecipeChange.recipe_id == recipe_id)
    rows = db.execute(stmt).scalars().all()
    return [{"change_code": c.change_code, "recipe_id": c.recipe_id, "version_id": c.version_id,
             "from_version_id": c.from_version_id, "reason": c.reason, "state": c.state,
             "requested_by": c.requested_by, "approved_by": c.approved_by,
             "approved_at": c.approved_at, "diff": c.diff} for c in rows]
