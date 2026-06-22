"""Recipes + versions (workflow, SoD)."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..common import new_id
from ..database import get_db
from ..errors import NotFoundError
from ..models.recipes import Recipe, RecipeVersion
from ..schemas import (
    RecipeIn,
    RecipeOut,
    RecipeVersionIn,
    RecipeVersionOut,
    TransitionIn,
)
from ..security import User, get_current_user, require_perm
from ..services import recipes as svc

router = APIRouter(prefix="/api/recipes", tags=["recipes"])


@router.get("", response_model=list[RecipeOut])
def list_recipes(db: Session = Depends(get_db)):
    return db.execute(select(Recipe).order_by(Recipe.code)).scalars().all()


@router.post("", response_model=RecipeOut, status_code=201)
def create_recipe(payload: RecipeIn, db: Session = Depends(get_db)):
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
