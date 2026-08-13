"""Công thức nguyên vật liệu theo dịch bia (xem models/formula.py cho bối cảnh thiết kế).

Nhiều công thức/dịch bia có thể cùng is_active=True — kích hoạt 1 công thức KHÔNG còn tự
ngừng hiệu lực công thức khác của cùng dịch bia (khác quy tắc cũ trước đây). Người lập Lệnh
nấu tự chọn dùng công thức nào (formula_id) cho mỗi lệnh nhỏ — xem
services/brew_order.py::build_lines_from_bom."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import utcnow
from ..errors import DomainError, NotFoundError
from ..models.formula import Formula, FormulaActivationLog
from ..models.master import Material, MaterialAltGroup, Product
from ..security import User, require_perm

_MANAGE_PERM = "recipe.author"  # 1 quyền dùng chung cho mọi thao tác — "người quản lý công thức"


def _validate_materials(db: Session, materials: list) -> None:
    if not materials:
        raise DomainError("Công thức phải có ít nhất 1 dòng nguyên vật liệu.")
    # Mỗi dòng khai ĐÚNG 1 trong material_code (vật tư cụ thể) HOẶC alt_group_code (nhóm vật
    # tư thay thế, VD "Malt Úc" gồm rời/bao — xem models/master.py::MaterialAltGroup).
    for m in materials:
        material_code, alt_group_code = m.get("material_code"), m.get("alt_group_code")
        if bool(material_code) == bool(alt_group_code):
            raise DomainError("Mỗi dòng NVL phải khai đúng 1 trong Mã vật tư hoặc Nhóm vật tư thay thế.")
        if not (m.get("qty") or 0) > 0:
            raise DomainError(f"NVL '{material_code or alt_group_code}': số lượng phải > 0.")

    codes = {m["material_code"] for m in materials if m.get("material_code")}
    if codes:
        found_materials = {mat.code: mat for mat in
                            db.execute(select(Material).where(Material.code.in_(codes))).scalars().all()}
        missing = codes - found_materials.keys()
        if missing:
            raise DomainError(f"Mã NVL không tồn tại: {', '.join(sorted(missing))}.")
        # Dòng khai theo mã cụ thể luôn dùng ĐÚNG đơn vị chính đã đăng ký ở Danh mục Vật tư —
        # không cho tự nhập uom khác (mirror quy tắc dòng theo nhóm bên dưới).
        for m in materials:
            code = m.get("material_code")
            if code:
                m["uom"] = found_materials[code].uom

    group_codes = {m["alt_group_code"] for m in materials if m.get("alt_group_code")}
    if group_codes:
        groups = db.execute(select(MaterialAltGroup).where(MaterialAltGroup.code.in_(group_codes))).scalars().all()
        found_groups = {g.code: g for g in groups}
        missing_groups = group_codes - found_groups.keys()
        if missing_groups:
            raise DomainError(f"Nhóm vật tư thay thế không tồn tại: {', '.join(sorted(missing_groups))}.")
        for code, g in found_groups.items():
            if not g.active:
                raise DomainError(f"Nhóm vật tư thay thế '{code}' đã ngừng hoạt động.")
            if not g.member_material_ids:
                raise DomainError(f"Nhóm vật tư thay thế '{code}' chưa có vật tư thành viên nào.")
        # Dòng khai theo nhóm luôn dùng ĐÚNG đơn vị đã đăng ký của nhóm (MaterialAltGroup.unit) —
        # không cho tự nhập uom khác, để _line_stock quy đổi tồn từng thành viên về đúng 1 đơn vị
        # trước khi cộng dồn (xem services/brew_order.py::_convert_member_qty).
        for m in materials:
            group_code = m.get("alt_group_code")
            if group_code:
                m["uom"] = found_groups[group_code].unit


def create_formula(db: Session, payload: dict, user: User) -> Formula:
    require_perm(user, _MANAGE_PERM)
    if db.execute(select(Formula.formula_id).where(Formula.code == payload["code"])).first():
        raise DomainError(f"Mã công thức '{payload['code']}' đã tồn tại.")
    if not db.get(Product, payload["product_id"]):
        raise DomainError("Loại dịch bia không tồn tại.")
    materials = [m.model_dump() if hasattr(m, "model_dump") else dict(m) for m in payload.get("materials", [])]
    _validate_materials(db, materials)
    f = Formula(code=payload["code"], product_id=payload["product_id"], note=payload.get("note"),
                base_qty=payload.get("base_qty", 0.0), base_uom=payload.get("base_uom", "L"),
                materials=materials, created_by=user.username)
    db.add(f)
    db.flush()
    record_audit(db, entity_type="formula", entity_id=f.formula_id, action="create", actor=user,
                 after={"code": f.code, "product_id": f.product_id, "materials": materials})
    db.commit()
    return f


def update_formula(db: Session, formula_id: str, payload: dict, user: User) -> Formula:
    require_perm(user, _MANAGE_PERM)
    f = db.get(Formula, formula_id)
    if not f:
        raise NotFoundError("Công thức không tồn tại.")
    if f.locked:
        raise DomainError("Công thức đã bị khóa — không thể sửa.")
    before = {"code": f.code, "note": f.note, "base_qty": f.base_qty, "base_uom": f.base_uom,
              "materials": f.materials}
    new_code = payload.get("code", f.code)
    if new_code != f.code and db.execute(
            select(Formula.formula_id).where(Formula.code == new_code, Formula.formula_id != formula_id)).first():
        raise DomainError(f"Mã công thức '{new_code}' đã tồn tại.")
    materials = [m.model_dump() if hasattr(m, "model_dump") else dict(m) for m in payload.get("materials", f.materials)]
    _validate_materials(db, materials)
    f.code, f.note = new_code, payload.get("note", f.note)
    f.base_qty = payload.get("base_qty", f.base_qty)
    f.base_uom = payload.get("base_uom", f.base_uom)
    f.materials = materials
    record_audit(db, entity_type="formula", entity_id=f.formula_id, action="update", actor=user,
                 before=before, after={"code": f.code, "note": f.note, "base_qty": f.base_qty,
                                       "base_uom": f.base_uom, "materials": materials})
    db.commit()
    return f


def list_formulas(db: Session, product_id: str | None = None) -> list[Formula]:
    q = select(Formula)
    if product_id:
        q = q.where(Formula.product_id == product_id)
    return db.execute(q.order_by(Formula.created_at.desc())).scalars().all()


def get_formula(db: Session, formula_id: str) -> Formula:
    f = db.get(Formula, formula_id)
    if not f:
        raise NotFoundError("Công thức không tồn tại.")
    return f


def activate_formula(db: Session, formula_id: str, user: User) -> Formula:
    require_perm(user, _MANAGE_PERM)
    f = get_formula(db, formula_id)
    if f.is_active:
        raise DomainError("Công thức này đang hiệu lực rồi.")
    now = utcnow()
    f.is_active = True
    db.add(FormulaActivationLog(formula_id=f.formula_id, product_id=f.product_id, action="activate",
                                 note="Kích hoạt", changed_by=user.username, changed_at=now))
    record_audit(db, entity_type="formula", entity_id=f.formula_id, action="activate", actor=user,
                 after={"code": f.code})
    db.commit()
    return f


def deactivate_formula(db: Session, formula_id: str, user: User) -> Formula:
    require_perm(user, _MANAGE_PERM)
    f = get_formula(db, formula_id)
    if not f.is_active:
        raise DomainError("Công thức này chưa hiệu lực.")
    f.is_active = False
    db.add(FormulaActivationLog(formula_id=f.formula_id, product_id=f.product_id, action="deactivate",
                                 note="Ngừng hiệu lực thủ công (không thay thế)",
                                 changed_by=user.username, changed_at=utcnow()))
    record_audit(db, entity_type="formula", entity_id=f.formula_id, action="deactivate", actor=user,
                 after={"code": f.code})
    db.commit()
    return f


def lock_formula(db: Session, formula_id: str, user: User) -> Formula:
    require_perm(user, _MANAGE_PERM)
    f = get_formula(db, formula_id)
    if f.locked:
        raise DomainError("Công thức này đã bị khóa.")
    f.locked, f.locked_by, f.locked_at = True, user.username, utcnow()
    record_audit(db, entity_type="formula", entity_id=f.formula_id, action="lock", actor=user)
    db.commit()
    return f


def unlock_formula(db: Session, formula_id: str, user: User) -> Formula:
    require_perm(user, _MANAGE_PERM)
    f = get_formula(db, formula_id)
    if not f.locked:
        raise DomainError("Công thức này chưa bị khóa.")
    f.locked, f.locked_by, f.locked_at = False, None, None
    record_audit(db, entity_type="formula", entity_id=f.formula_id, action="unlock", actor=user)
    db.commit()
    return f


def delete_formula(db: Session, formula_id: str, user: User) -> None:
    require_perm(user, _MANAGE_PERM)
    f = get_formula(db, formula_id)
    if f.is_active:
        raise DomainError("Công thức đang hiệu lực — phải kích hoạt công thức khác thay thế trước khi xóa.")
    if f.locked:
        raise DomainError("Công thức đã bị khóa — không thể xóa.")
    record_audit(db, entity_type="formula", entity_id=f.formula_id, action="delete", actor=user,
                 before={"code": f.code, "product_id": f.product_id})
    # MSSQL enforce FK: xóa lịch sử kích hoạt (con) trước khi xóa formula (cha) — SQLite bỏ qua
    # FK nên chạy được, MSSQL thì chặn (DEPLOY-CONTRACT §E).
    for log in db.execute(select(FormulaActivationLog).where(
            FormulaActivationLog.formula_id == formula_id)).scalars().all():
        db.delete(log)
    db.flush()
    db.delete(f)
    db.commit()


def list_activation_log(db: Session, product_id: str) -> list[FormulaActivationLog]:
    return db.execute(select(FormulaActivationLog).where(
        FormulaActivationLog.product_id == product_id
    ).order_by(FormulaActivationLog.changed_at.desc())).scalars().all()
