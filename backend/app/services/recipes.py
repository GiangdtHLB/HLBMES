"""Quy tắc recipe/version (tài liệu §7.2): workflow trạng thái, SoD giữa
người soạn và người duyệt, không cho sửa version đã rời draft."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import RECIPE_TRANSITIONS, Role, RecipeState, new_id, utcnow
from ..errors import DomainError, NotFoundError, PermissionError_
from ..models.recipes import Recipe, RecipeVersion
from ..models.recipe_ext import RecipeChange
from ..models.signature import Signature
from ..security import User, enforce_sod, require_role, verify_password


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
        yield_steps=payload.get("yield_steps", []),
        procedure=payload.get("procedure", []),
        change_reason=payload.get("change_reason"),
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
    rv.yield_steps = payload.get("yield_steps", rv.yield_steps)
    rv.procedure = payload.get("procedure", rv.procedure)
    if payload.get("change_reason") is not None:
        rv.change_reason = payload.get("change_reason")
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

    # Tạm ngưng / ngừng dùng: BẮT BUỘC nêu lý do (truy vết audit).
    if target_state in (RecipeState.SUSPENDED, RecipeState.OBSOLETE) and not (reason or "").strip():
        raise DomainError("Phải nêu lý do khi tạm ngưng/ngừng dùng công thức.")

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


# ---------------------------------------------------------------------------
# Change-control: duyệt thay đổi công thức có CHỮ KÝ ĐIỆN TỬ (re-auth) + diff.
# ---------------------------------------------------------------------------

def _latest_effective(db: Session, recipe_id: str, exclude_id: str = None):
    rows = db.execute(select(RecipeVersion).where(
        RecipeVersion.recipe_id == recipe_id,
        RecipeVersion.state.in_(["effective", "obsolete"])
    ).order_by(RecipeVersion.version_no.desc())).scalars().all()
    for r in rows:
        if r.version_id != exclude_id:
            return r
    return None


def diff_versions(db: Session, va_id: str, vb_id: str) -> dict:
    """So sánh 2 recipe version: base_qty, parameters, materials, yield_steps."""
    a = db.get(RecipeVersion, va_id)
    b = db.get(RecipeVersion, vb_id)
    if not a or not b:
        raise NotFoundError("Recipe version không tồn tại.")

    def _mat_map(rv):
        return {m.get("material_code"): m for m in (rv.materials or [])}

    def _param_map(rv):
        return {p.get("name"): p for p in (rv.parameters or [])}

    am, bm = _mat_map(a), _mat_map(b)
    mat_changes = []
    for code in sorted(set(am) | set(bm)):
        oa, ob = am.get(code), bm.get(code)
        if oa is None:                       # có ở b, không có ở a → thêm mới
            mat_changes.append({"material_code": code, "type": "added",
                                "new_qty": ob.get("qty"), "new_tol": ob.get("tol_pct")})
        elif ob is None:                     # có ở a, không có ở b → bỏ
            mat_changes.append({"material_code": code, "type": "removed",
                                "old_qty": oa.get("qty"), "old_tol": oa.get("tol_pct")})
        else:
            qa, qb = oa.get("qty"), ob.get("qty")
            if qa != qb or oa.get("tol_pct") != ob.get("tol_pct"):
                mat_changes.append({"material_code": code, "type": "changed",
                                    "old_qty": qa, "new_qty": qb,
                                    "old_tol": oa.get("tol_pct"), "new_tol": ob.get("tol_pct")})
    ap, bp = _param_map(a), _param_map(b)
    param_changes = []
    for name in sorted(set(ap) | set(bp)):
        oa, ob = ap.get(name), bp.get(name)
        if oa != ob:
            param_changes.append({"name": name, "old": oa, "new": ob})
    return {
        "from": {"version_id": a.version_id, "version_no": a.version_no, "state": a.state},
        "to": {"version_id": b.version_id, "version_no": b.version_no, "state": b.state},
        "base_qty": {"old": a.base_qty, "new": b.base_qty} if a.base_qty != b.base_qty else None,
        "materials": mat_changes,
        "parameters": param_changes,
        "yield_steps": {"old": a.yield_steps, "new": b.yield_steps} if a.yield_steps != b.yield_steps else None,
    }


def approve_with_signature(db: Session, version_id: str, user: User, password: str,
                           change_reason: str) -> dict:
    """Duyệt công thức (review→approved) bằng CHỮ KÝ ĐIỆN TỬ: re-auth mật khẩu +
    bắt buộc lý do thay đổi + SoD + lưu RecipeChange (kèm diff vs version effective trước)."""
    require_role(user, Role.ENGINEER, Role.QA)
    rv = db.get(RecipeVersion, version_id)
    if not rv:
        raise NotFoundError("Recipe version không tồn tại.")
    if rv.state != RecipeState.REVIEW.value:
        raise DomainError("Chỉ ký duyệt version đang ở trạng thái 'review'.")
    enforce_sod(rv.created_by, user, "duyệt công thức")
    if not (change_reason or "").strip():
        raise DomainError("Phải nêu lý do thay đổi (change control).")
    # Re-authentication cho chữ ký điện tử (21 CFR Part 11).
    from ..models.auth import User as UserModel
    u = db.execute(select(UserModel).where(UserModel.username == user.username)).scalar_one_or_none()
    if not u or not verify_password(password or "", u.password_hash):
        raise PermissionError_("Xác thực lại thất bại: mật khẩu không đúng (yêu cầu cho chữ ký điện tử).")

    baseline = _latest_effective(db, rv.recipe_id, exclude_id=rv.version_id)
    diff = diff_versions(db, baseline.version_id, rv.version_id) if baseline else {
        "to": {"version_no": rv.version_no}, "note": "Version đầu tiên (không có baseline)."}

    rv.state = RecipeState.APPROVED.value
    rv.approved_by = user.username
    rv.approved_at = utcnow()
    rv.change_reason = change_reason

    change = RecipeChange(
        change_id=new_id(), change_code=f"CHG-{utcnow():%Y%m%d}-{new_id()[:5].upper()}",
        recipe_id=rv.recipe_id, version_id=rv.version_id,
        from_version_id=baseline.version_id if baseline else None,
        reason=change_reason, diff=diff, state="approved",
        requested_by=rv.created_by, approved_by=user.username, approved_at=utcnow())
    db.add(change)
    # Gắn nội dung đã ký vào chữ ký (signature/record linking, 21 CFR §11.70): hash
    # bao trùm phần thực chất của version → phát hiện nếu nội dung bị đổi sau khi ký.
    import hashlib
    import json
    signed_content = {
        "version_id": rv.version_id, "version_no": rv.version_no,
        "base_qty": rv.base_qty, "base_uom": rv.base_uom,
        "parameters": rv.parameters, "materials": rv.materials,
        "quality_checks": rv.quality_checks, "yield_steps": rv.yield_steps,
        "procedure": getattr(rv, "procedure", None),
    }
    content_hash = hashlib.sha256(
        json.dumps(signed_content, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()
    db.add(Signature(sig_id=new_id(), scope_type="recipe_version", scope_id=rv.version_id,
                     meaning="Phê duyệt thay đổi công thức", signed_by=user.username,
                     role=user.role, reason=change_reason,
                     content_hash=content_hash, signed_at=utcnow()))
    record_audit(db, entity_type="recipe_version", entity_id=rv.version_id,
                 action="change_control:approved", actor=user,
                 before={"state": "review"}, after={"state": rv.state, "change": change.change_code},
                 reason=change_reason)
    db.commit()
    db.refresh(rv)
    return {"version_id": rv.version_id, "state": rv.state, "change_code": change.change_code,
            "diff": diff}
