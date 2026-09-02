"""Quy tắc recipe/version (tài liệu §7.2): workflow trạng thái, SoD giữa
người soạn và người duyệt, không cho sửa version đã rời draft."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import RECIPE_TRANSITIONS, Role, RecipeState, new_id, utcnow
from ..errors import DomainError, NotFoundError, PermissionError_
from ..models.master import Product
from ..models.quality_ext import ProcessParameter, QCParameter
from ..models.recipes import Recipe, RecipeVersion, RecipeVersionParamItem, RecipeVersionQcItem
from ..models.recipe_ext import RecipeChange
from ..models.signature import Signature
from ..security import User, enforce_sod, require_role, verify_password


# ---- Chọn chỉ tiêu/tham số từ Danh mục cho 1 RecipeVersion ----
# `quality_checks`/`parameters` (JSON phẳng, cột cũ trên RecipeVersion) vẫn được TỰ TÍNH/ghi đè
# từ 2 hàm dưới đây mỗi lần lưu (giữ nguyên shape cũ) — để services/batches.py, quality_adv.py::
# coa, services/derived.py (đang đọc thẳng 2 cột JSON này) không cần sửa gì. `param_id` được
# nhét thêm vào bản ghi phẳng (field mới, không phá vỡ shape cũ) để diff_versions/UI có thể nối
# ngược lại danh mục khi cần.

def _resolve_qc_items(db: Session, items: list) -> tuple[list[dict], list[dict]]:
    """items: [{param_id, seq, mandatory, target_override, usl_override, lsl_override}] (chọn từ
    Danh mục chỉ tiêu QCParameter) → (rows để lưu RecipeVersionQcItem, quality_checks JSON phẳng
    — override-hoặc-mặc-định mirror qc_catalog.py::_item_out/required_params_for_material)."""
    rows, flat = [], []
    for it in items:
        param = db.get(QCParameter, it["param_id"])
        if not param:
            raise NotFoundError(f"Chỉ tiêu '{it['param_id']}' không tồn tại.")
        mandatory = it.get("mandatory", True)
        lsl = it.get("lsl_override") if it.get("lsl_override") is not None else param.lsl
        usl = it.get("usl_override") if it.get("usl_override") is not None else param.usl
        rows.append({"param_id": param.param_id, "seq": it.get("seq", 0), "mandatory": mandatory,
                    "target_override": it.get("target_override"),
                    "usl_override": it.get("usl_override"), "lsl_override": it.get("lsl_override")})
        flat.append({"param_id": param.param_id, "parameter": param.name, "method": param.method,
                    "unit": param.unit, "mandatory": mandatory, "lower": lsl, "upper": usl})
    return rows, flat


def _resolve_param_items(db: Session, items: list) -> tuple[list[dict], list[dict]]:
    """items: [{param_id, seq, mandatory, phase_override, target_override, usl_override,
    lsl_override}] (chọn từ Danh mục tham số ProcessParameter) → (rows để lưu
    RecipeVersionParamItem, parameters JSON phẳng)."""
    rows, flat = [], []
    for it in items:
        param = db.get(ProcessParameter, it["param_id"])
        if not param:
            raise NotFoundError(f"Tham số '{it['param_id']}' không tồn tại.")
        phase = it.get("phase_override") or param.phase
        target = it.get("target_override") if it.get("target_override") is not None else param.target
        lsl = it.get("lsl_override") if it.get("lsl_override") is not None else param.lsl
        usl = it.get("usl_override") if it.get("usl_override") is not None else param.usl
        rows.append({"param_id": param.param_id, "seq": it.get("seq", 0),
                    "mandatory": it.get("mandatory", True), "phase_override": it.get("phase_override"),
                    "target_override": it.get("target_override"),
                    "usl_override": it.get("usl_override"), "lsl_override": it.get("lsl_override")})
        flat.append({"param_id": param.param_id, "name": param.name, "unit": param.unit,
                    "phase": phase, "target": target, "lower": lsl, "upper": usl})
    return rows, flat


def _replace_qc_items(db: Session, version_id: str, rows: list) -> None:
    for old in db.execute(select(RecipeVersionQcItem).where(
            RecipeVersionQcItem.version_id == version_id)).scalars().all():
        db.delete(old)
    for r in rows:
        db.add(RecipeVersionQcItem(link_id=new_id(), version_id=version_id, **r))


def _replace_param_items(db: Session, version_id: str, rows: list) -> None:
    for old in db.execute(select(RecipeVersionParamItem).where(
            RecipeVersionParamItem.version_id == version_id)).scalars().all():
        db.delete(old)
    for r in rows:
        db.add(RecipeVersionParamItem(link_id=new_id(), version_id=version_id, **r))


def list_qc_items(db: Session, version_id: str) -> list[dict]:
    items = db.execute(select(RecipeVersionQcItem).where(
        RecipeVersionQcItem.version_id == version_id).order_by(RecipeVersionQcItem.seq)).scalars().all()
    out = []
    for it in items:
        param = db.get(QCParameter, it.param_id)
        out.append({"link_id": it.link_id, "version_id": it.version_id, "param_id": it.param_id,
                    "seq": it.seq, "mandatory": it.mandatory, "target_override": it.target_override,
                    "usl_override": it.usl_override, "lsl_override": it.lsl_override,
                    "param_code": param.code if param else None, "param_name": param.name if param else None,
                    "param_unit": param.unit if param else None})
    return out


def list_param_items(db: Session, version_id: str) -> list[dict]:
    items = db.execute(select(RecipeVersionParamItem).where(
        RecipeVersionParamItem.version_id == version_id).order_by(RecipeVersionParamItem.seq)).scalars().all()
    out = []
    for it in items:
        param = db.get(ProcessParameter, it.param_id)
        out.append({"link_id": it.link_id, "version_id": it.version_id, "param_id": it.param_id,
                    "seq": it.seq, "mandatory": it.mandatory, "phase_override": it.phase_override,
                    "target_override": it.target_override,
                    "usl_override": it.usl_override, "lsl_override": it.lsl_override,
                    "param_code": param.code if param else None, "param_name": param.name if param else None,
                    "param_unit": param.unit if param else None})
    return out


def _resolve_version_product(db: Session, recipe: Recipe, product_id: str) -> Product:
    """1 version chỉ được gắn Product thuộc ĐÚNG Loại bia (beer_type_id) của Recipe cha — mỗi
    Recipe giờ đại diện 1 Loại bia (VD Sapphire), còn từng version mới ứng với 1 dịch bia cụ thể
    (VD SAPPHIRE-13OP/14OP), xem models/recipes.py."""
    if not product_id:
        raise DomainError("Chọn Dịch bia cho version này.")
    product = db.get(Product, product_id)
    if not product:
        raise DomainError("Dịch bia đã chọn không tồn tại.")
    if product.beer_type_id != recipe.beer_type_id:
        raise DomainError(f"Dịch bia '{product.code}' không thuộc Loại bia của công thức này.")
    return product


def create_version(db: Session, recipe_id: str, payload: dict, user: User) -> RecipeVersion:
    require_role(user, Role.ENGINEER)
    recipe = db.get(Recipe, recipe_id)
    if not recipe:
        raise NotFoundError("Recipe không tồn tại.")
    _resolve_version_product(db, recipe, payload.get("product_id"))
    last = db.execute(
        select(RecipeVersion).where(RecipeVersion.recipe_id == recipe_id)
        .order_by(RecipeVersion.version_no.desc())
    ).scalars().first()
    next_no = (last.version_no + 1) if last else 1
    # qc_items/param_items (chọn từ Danh mục) — nếu có, resolve rồi GHI ĐÈ quality_checks/
    # parameters (JSON phẳng cũ) bằng bản đã resolve; không có thì giữ nguyên hành vi cũ (nhận
    # thẳng quality_checks/parameters tự do, tương thích ngược).
    qc_rows, param_rows = None, None
    quality_checks, parameters = payload.get("quality_checks", []), payload.get("parameters", [])
    if payload.get("qc_items") is not None:
        qc_rows, quality_checks = _resolve_qc_items(db, payload["qc_items"])
    if payload.get("param_items") is not None:
        param_rows, parameters = _resolve_param_items(db, payload["param_items"])
    rv = RecipeVersion(
        version_id=new_id(),
        recipe_id=recipe_id,
        product_id=payload.get("product_id"),
        version_no=next_no,
        state=RecipeState.DRAFT.value,
        base_qty=payload.get("base_qty", 0.0) or 0.0,
        base_uom=payload.get("base_uom", "L"),
        parameters=parameters,
        materials=payload.get("materials", []),
        quality_checks=quality_checks,
        yield_steps=payload.get("yield_steps", []),
        procedure=payload.get("procedure", []),
        change_reason=payload.get("change_reason"),
        created_by=user.username,
        created_at=utcnow(),
    )
    db.add(rv)
    db.flush()
    if qc_rows is not None:
        _replace_qc_items(db, rv.version_id, qc_rows)
    if param_rows is not None:
        _replace_param_items(db, rv.version_id, param_rows)
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
    if rv.state != RecipeState.DRAFT.value and user.role != Role.ADMIN.value:
        # Không cho phép chỉnh version đã rời draft (tài liệu §7.2).
        # TẠM THỜI: admin được phép sửa version ở bất kỳ trạng thái nào (theo yêu cầu người
        # dùng) — bỏ điều kiện "and user.role != Role.ADMIN.value" ở trên khi không cần nữa.
        raise DomainError("Chỉ được sửa recipe version ở trạng thái draft.")
    recipe = db.get(Recipe, rv.recipe_id)
    rv.product_id = _resolve_version_product(db, recipe, payload.get("product_id", rv.product_id)).product_id
    before = {"parameters": rv.parameters, "materials": rv.materials, "quality_checks": rv.quality_checks}
    rv.base_qty = payload.get("base_qty", rv.base_qty) or 0.0
    rv.base_uom = payload.get("base_uom", rv.base_uom)
    rv.materials = payload.get("materials", rv.materials)
    if payload.get("qc_items") is not None:
        qc_rows, rv.quality_checks = _resolve_qc_items(db, payload["qc_items"])
        _replace_qc_items(db, rv.version_id, qc_rows)
    else:
        rv.quality_checks = payload.get("quality_checks", rv.quality_checks)
    if payload.get("param_items") is not None:
        param_rows, rv.parameters = _resolve_param_items(db, payload["param_items"])
        _replace_param_items(db, rv.version_id, param_rows)
    else:
        rv.parameters = payload.get("parameters", rv.parameters)
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
        # Dòng khai theo Nhóm vật tư thay thế không có material_code — key theo alt_group_code
        # để không đụng độ/mất dòng khi so sánh 2 version (xem build_lines_from_recipe_version).
        return {m.get("material_code") or m.get("alt_group_code"): m for m in (rv.materials or [])}

    def _param_map(rv):
        # Ưu tiên khoá theo param_id (tham số chọn từ Danh mục) — fallback "name" cho version cũ
        # chưa có catalog ref (gõ tay tự do, không có param_id).
        return {p.get("param_id") or p.get("name"): p for p in (rv.parameters or [])}

    am, bm = _mat_map(a), _mat_map(b)
    mat_changes = []
    for code in sorted(set(am) | set(bm)):
        oa, ob = am.get(code), bm.get(code)
        if oa is None:                       # có ở b, không có ở a → thêm mới
            mat_changes.append({"material_code": code, "type": "added",
                                "new_qty": ob.get("qty"), "new_tol": ob.get("tol_pct"),
                                "new_member_qty": ob.get("member_qty")})
        elif ob is None:                     # có ở a, không có ở b → bỏ
            mat_changes.append({"material_code": code, "type": "removed",
                                "old_qty": oa.get("qty"), "old_tol": oa.get("tol_pct"),
                                "old_member_qty": oa.get("member_qty")})
        else:
            qa, qb = oa.get("qty"), ob.get("qty")
            # member_qty (định mức riêng từng thành viên Nhóm vật tư thay thế) so sánh riêng —
            # dòng khai kiểu này không có "qty" chung nên qa==qb==None không có nghĩa là
            # KHÔNG đổi, phải so cả member_qty mới không bỏ sót thay đổi định mức từng mã.
            mqa, mqb = oa.get("member_qty"), ob.get("member_qty")
            if qa != qb or mqa != mqb or oa.get("tol_pct") != ob.get("tol_pct"):
                mat_changes.append({"material_code": code, "type": "changed",
                                    "old_qty": qa, "new_qty": qb,
                                    "old_member_qty": mqa, "new_member_qty": mqb,
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
