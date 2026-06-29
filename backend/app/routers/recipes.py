"""Recipes + versions (workflow, SoD)."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..common import new_id
from ..database import get_db
from ..errors import NotFoundError
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
    r = Recipe(recipe_id=new_id(), **payload.model_dump())
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


@router.get("/{recipe_id}/versions", response_model=list[RecipeVersionOut])
def list_versions(recipe_id: str, db: Session = Depends(get_db)):
    return db.execute(
        select(RecipeVersion).where(RecipeVersion.recipe_id == recipe_id)
        .order_by(RecipeVersion.version_no)
    ).scalars().all()


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
