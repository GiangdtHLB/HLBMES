"""Quy tắc recipe/version (tài liệu §7.2): workflow trạng thái, SoD giữa
người soạn và người duyệt, không cho sửa version đã rời draft."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import RECIPE_TRANSITIONS, Role, RecipeState, new_id, utcnow
from ..errors import DomainError, NotFoundError
from ..models.recipes import Recipe, RecipeVersion
from ..security import User, enforce_sod, require_role


def create_version(db: Session, recipe_id: str, payload: dict, user: User) -> RecipeVersion:
    require_role(user, Role.ENGINEER)
    recipe = db.get(Recipe, recipe_id)
    if not recipe:
        raise NotFoundError("Recipe không tồn tại.")
    last = db.execute(
        select(RecipeVersion).where(RecipeVersion.recipe_id == recipe_id)
        .order_by(RecipeVersion.version_no.desc())
    ).scalars().first()
    next_no = (last.version_no + 1) if last else 1
    rv = RecipeVersion(
        version_id=new_id(),
        recipe_id=recipe_id,
        version_no=next_no,
        state=RecipeState.DRAFT.value,
        base_qty=payload.get("base_qty", 0.0) or 0.0,
        base_uom=payload.get("base_uom", "L"),
        parameters=payload.get("parameters", []),
        materials=payload.get("materials", []),
        quality_checks=payload.get("quality_checks", []),
        created_by=user.username,
        created_at=utcnow(),
    )
    db.add(rv)
    record_audit(db, entity_type="recipe_version", entity_id=rv.version_id,
                 action="create", actor=user, after={"version_no": next_no})
    db.commit()
    db.refresh(rv)
    return rv


def update_draft(db: Session, version_id: str, payload: dict, user: User) -> RecipeVersion:
    require_role(user, Role.ENGINEER)
    rv = db.get(RecipeVersion, version_id)
    if not rv:
        raise NotFoundError("Recipe version không tồn tại.")
    if rv.state != RecipeState.DRAFT.value:
        # Không cho phép chỉnh version đã rời draft (tài liệu §7.2).
        raise DomainError("Chỉ được sửa recipe version ở trạng thái draft.")
    before = {"parameters": rv.parameters, "materials": rv.materials, "quality_checks": rv.quality_checks}
    rv.base_qty = payload.get("base_qty", rv.base_qty) or 0.0
    rv.base_uom = payload.get("base_uom", rv.base_uom)
    rv.parameters = payload.get("parameters", rv.parameters)
    rv.materials = payload.get("materials", rv.materials)
    rv.quality_checks = payload.get("quality_checks", rv.quality_checks)
    record_audit(db, entity_type="recipe_version", entity_id=rv.version_id,
                 action="update_draft", actor=user, before=before,
                 after={"parameters": rv.parameters, "materials": rv.materials})
    db.commit()
    db.refresh(rv)
    return rv


def transition(db: Session, version_id: str, target: str, user: User, reason: str = None) -> RecipeVersion:
    rv = db.get(RecipeVersion, version_id)
    if not rv:
        raise NotFoundError("Recipe version không tồn tại.")
    try:
        target_state = RecipeState(target)
    except ValueError:
        raise DomainError(f"Trạng thái không hợp lệ: {target}")

    current = RecipeState(rv.state)
    if target_state not in RECIPE_TRANSITIONS[current]:
        raise DomainError(f"Không thể chuyển recipe từ {current.value} sang {target}.")

    # Duyệt (approved) yêu cầu vai trò ENGINEER/QA và SoD với người soạn.
    if target_state == RecipeState.APPROVED:
        require_role(user, Role.ENGINEER, Role.QA)
        enforce_sod(rv.created_by, user, "duyệt recipe")
        rv.approved_by = user.username
        rv.approved_at = utcnow()
    elif target_state == RecipeState.EFFECTIVE:
        require_role(user, Role.ENGINEER, Role.QA)

    before = {"state": rv.state}
    rv.state = target_state.value
    record_audit(db, entity_type="recipe_version", entity_id=rv.version_id,
                 action=f"transition:{target}", actor=user, before=before,
                 after={"state": rv.state}, reason=reason)
    db.commit()
    db.refresh(rv)
    return rv
