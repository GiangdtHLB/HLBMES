"""Bao bì tuần hoàn: khai báo loại (vỏ chai/két-gông/keg) + biến động tồn/lưu hành.

Biến động: nhap (nhập kho) · xuat (xuất theo hàng → ra lưu hành) · thu_hoi (thu vỏ về kho)
· loai_bo (vỏ hỏng) · kiem_ke (đặt lại tồn theo kiểm kê).
"""

from sqlalchemy import select, true
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import new_id, utcnow
from ..errors import DomainError, NotFoundError
from ..models.brewing import BottleMaterialUsage, BottleRecord
from ..models.master import Material, MaterialGroup
from ..models.materials import MaterialLot
from ..models.packaging import PackagingMove, PackagingType
from ..security import User, require_perm

CATEGORIES = {"vo_chai": "Vỏ chai", "ket_gong": "Két/Gông", "keg": "Keg inox"}
MOVES = {"nhap": "Nhập kho", "xuat": "Xuất (ra lưu hành)", "thu_hoi": "Thu hồi vỏ",
         "loai_bo": "Loại bỏ (hỏng)", "kiem_ke": "Kiểm kê (đặt lại tồn)"}


def list_types(db: Session) -> list:
    rows = db.execute(select(PackagingType).order_by(PackagingType.category, PackagingType.code)).scalars().all()
    return [{"pkg_id": p.pkg_id, "code": p.code, "name": p.name, "category": p.category,
             "category_label": CATEGORIES.get(p.category, p.category), "material": p.material,
             "volume_l": p.volume_l, "deposit": p.deposit, "on_hand": p.on_hand,
             "in_circulation": p.in_circulation, "total": p.on_hand + p.in_circulation,
             "active": p.active} for p in rows]


def summary(db: Session) -> dict:
    rows = db.execute(select(PackagingType)).scalars().all()
    by_cat = {}
    for p in rows:
        c = by_cat.setdefault(p.category, {"category": p.category, "label": CATEGORIES.get(p.category, p.category),
                                           "types": 0, "on_hand": 0.0, "in_circulation": 0.0})
        c["types"] += 1
        c["on_hand"] += p.on_hand
        c["in_circulation"] += p.in_circulation
    return {"by_category": list(by_cat.values()),
            "total_on_hand": sum(p.on_hand for p in rows),
            "total_in_circulation": sum(p.in_circulation for p in rows)}


def create_type(db: Session, payload: dict, user: User) -> PackagingType:
    require_perm(user, "master.manage")
    if payload.get("category") not in CATEGORIES:
        raise DomainError(f"Loại bao bì không hợp lệ: {payload.get('category')} (cho phép: {', '.join(CATEGORIES)}).")
    if db.execute(select(PackagingType).where(PackagingType.code == payload["code"])).scalar_one_or_none():
        raise DomainError(f"Mã bao bì '{payload['code']}' đã tồn tại.")
    p = PackagingType(pkg_id=new_id(), code=payload["code"], name=payload["name"],
                      category=payload["category"], material=payload.get("material"),
                      volume_l=payload.get("volume_l"), deposit=payload.get("deposit", 0.0) or 0.0,
                      on_hand=payload.get("on_hand", 0.0) or 0.0,
                      in_circulation=payload.get("in_circulation", 0.0) or 0.0)
    db.add(p)
    record_audit(db, entity_type="packaging", entity_id=p.pkg_id, action="create", actor=user,
                 after={"code": p.code, "category": p.category})
    db.commit()
    db.refresh(p)
    return p


def move(db: Session, pkg_id: str, kind: str, qty: float, user: User,
         ref: str = None, note: str = None) -> dict:
    require_perm(user, "warehouse.issue")
    if kind not in MOVES:
        raise DomainError(f"Loại biến động không hợp lệ: {kind}.")
    p = db.get(PackagingType, pkg_id)
    if not p:
        raise NotFoundError("Loại bao bì không tồn tại.")
    qty = float(qty or 0)
    if kind == "kiem_ke":
        if qty < 0:
            raise DomainError("Số lượng kiểm kê không được âm.")
    elif qty <= 0:
        raise DomainError("Số lượng phải > 0.")
    before = {"on_hand": p.on_hand, "in_circulation": p.in_circulation}
    if kind == "nhap":
        p.on_hand += qty
    elif kind == "xuat":
        if p.on_hand < qty:
            raise DomainError(f"Tồn kho không đủ để xuất (tồn {p.on_hand}).")
        p.on_hand -= qty
        p.in_circulation += qty
    elif kind == "thu_hoi":
        if p.in_circulation < qty:
            raise DomainError(f"Lượng đang lưu hành không đủ để thu hồi (đang lưu hành {p.in_circulation}).")
        p.in_circulation -= qty
        p.on_hand += qty
    elif kind == "loai_bo":
        if p.on_hand < qty:
            raise DomainError(f"Tồn kho không đủ để loại bỏ (tồn {p.on_hand}).")
        p.on_hand -= qty
    elif kind == "kiem_ke":
        p.on_hand = qty
    db.add(PackagingMove(move_id=new_id(), pkg_id=pkg_id, kind=kind, qty=qty,
                         ref=ref, note=note, by=user.username, ts=utcnow()))
    record_audit(db, entity_type="packaging", entity_id=pkg_id, action=f"move:{kind}", actor=user,
                 before=before, after={"on_hand": p.on_hand, "in_circulation": p.in_circulation,
                                       "qty": qty}, reason=note)
    db.commit()
    return {"pkg_id": pkg_id, "kind": kind, "on_hand": p.on_hand, "in_circulation": p.in_circulation}


def lot_report(db: Session) -> list[dict]:
    """Báo cáo bao bì TIÊU HAO (nắp, thùng carton, tem nhãn...) theo lô — lấy trực tiếp từ
    Kho NVL (Material/MaterialLot), không khai báo tay như packaging_type. Vật tư thuộc 1
    Nhóm vật tư đã đánh dấu is_packaging tự động lọt vào đây; nhập kho qua Nhập kho NVL bình
    thường, xuất dùng cho mẻ chiết qua nút NVL trên dòng Chiết (BottleMaterialUsage) —
    KHÔNG áp dụng cho vỏ chai/két/keg tuần hoàn (vẫn dùng packaging_type/packaging_move)."""
    packaging_group_codes = [g.code for g in db.execute(
        select(MaterialGroup).where(MaterialGroup.is_packaging == true())).scalars().all()]
    if not packaging_group_codes:
        return []
    materials = db.execute(select(Material).where(Material.category.in_(packaging_group_codes))).scalars().all()
    material_by_id = {m.material_id: m for m in materials}
    if not material_by_id:
        return []
    lots = db.execute(select(MaterialLot).where(MaterialLot.material_id.in_(material_by_id))
                      .order_by(MaterialLot.created_at.desc())).scalars().all()
    lot_ids = [l.lot_id for l in lots]
    usages = db.execute(select(BottleMaterialUsage).where(
        BottleMaterialUsage.lot_id.in_(lot_ids))).scalars().all() if lot_ids else []
    bottle_by_id = {b.bottle_id: b for b in db.execute(select(BottleRecord).where(
        BottleRecord.bottle_id.in_({u.bottle_id for u in usages}))).scalars().all()} if usages else {}
    usages_by_lot: dict[str, list] = {}
    for u in usages:
        b = bottle_by_id.get(u.bottle_id)
        usages_by_lot.setdefault(u.lot_id, []).append({
            "bottle_id": u.bottle_id, "bottle_code": b.bottle_code if b else None,
            "quantity": u.quantity, "uom": u.uom, "used_at": u.created_at,
        })
    out = []
    for l in lots:
        m = material_by_id.get(l.material_id)
        lot_usages = usages_by_lot.get(l.lot_id, [])
        out.append({
            "lot_id": l.lot_id, "lot_code": l.lot_code, "material_id": l.material_id,
            "material_code": m.code if m else None, "material_name": m.name if m else None,
            "quantity": l.quantity, "uom": l.uom, "status": l.status, "location": l.location,
            "received_at": l.created_at,
            "last_issued_at": max((u["used_at"] for u in lot_usages), default=None),
            "usages": lot_usages,
        })
    return out


def list_moves(db: Session, pkg_id: str = None) -> list:
    stmt = select(PackagingMove).order_by(PackagingMove.ts.desc()).limit(100)
    if pkg_id:
        stmt = stmt.where(PackagingMove.pkg_id == pkg_id)
    return [{"kind": m.kind, "kind_label": MOVES.get(m.kind, m.kind), "qty": m.qty,
             "ref": m.ref, "note": m.note, "by": m.by, "ts": m.ts, "pkg_id": m.pkg_id}
            for m in db.execute(stmt).scalars().all()]
