"""Công thức nguyên vật liệu theo dịch bia (xem models/formula.py cho bối cảnh thiết kế).

Quy tắc cốt lõi: CHỈ ĐÚNG 1 formula/product được is_active=True tại 1 thời điểm — đảm bảo
ở đây (activate_formula), KHÔNG dựa vào DB constraint. services/brew_order.py::_effective_bom
tin tưởng bất biến này để chọn công thức hiệu lực mà không cần ORDER BY."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import utcnow
from ..errors import DomainError, NotFoundError
from ..models.formula import Formula, FormulaActivationLog
from ..models.master import Material, Product
from ..security import User, require_perm

_MANAGE_PERM = "recipe.author"  # 1 quyền dùng chung cho mọi thao tác — "người quản lý công thức"


def _validate_materials(db: Session, materials: list) -> None:
    if not materials:
        raise DomainError("Công thức phải có ít nhất 1 dòng nguyên vật liệu.")
    codes = {m.get("material_code") for m in materials}
    found = {c for c, in db.execute(select(Material.code).where(Material.code.in_(codes))).all()}
    missing = codes - found
    if missing:
        raise DomainError(f"Mã NVL không tồn tại: {', '.join(sorted(missing))}.")
    for m in materials:
        if not (m.get("qty") or 0) > 0:
            raise DomainError(f"NVL '{m.get('material_code')}': số lượng phải > 0.")


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
    prev = db.execute(select(Formula).where(
        Formula.product_id == f.product_id, Formula.is_active == True, Formula.formula_id != formula_id  # noqa: E712
    )).scalars().first()
    if prev:
        prev.is_active = False
        db.add(FormulaActivationLog(formula_id=prev.formula_id, product_id=prev.product_id, action="deactivate",
                                     note=f"Tự động ngừng hiệu lực (do {f.code} được kích hoạt)",
                                     changed_by=user.username, changed_at=now))
    f.is_active = True
    db.add(FormulaActivationLog(formula_id=f.formula_id, product_id=f.product_id, action="activate",
                                 note=(f"Kích hoạt (thay thế {prev.code})" if prev else "Kích hoạt lần đầu"),
                                 changed_by=user.username, changed_at=now))
    record_audit(db, entity_type="formula", entity_id=f.formula_id, action="activate", actor=user,
                 before={"prev_active_formula": prev.code if prev else None}, after={"code": f.code})
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
    db.delete(f)
    db.commit()


def list_activation_log(db: Session, product_id: str) -> list[FormulaActivationLog]:
    return db.execute(select(FormulaActivationLog).where(
        FormulaActivationLog.product_id == product_id
    ).order_by(FormulaActivationLog.changed_at.desc())).scalars().all()
