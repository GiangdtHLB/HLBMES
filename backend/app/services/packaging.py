"""Bao bì tuần hoàn: khai báo loại (vỏ chai/két-gông/keg) + biến động tồn/lưu hành.

Biến động: nhap (nhập kho) · xuat (xuất theo hàng → ra lưu hành) · thu_hoi (thu vỏ về kho)
· loai_bo (vỏ hỏng) · kiem_ke (đặt lại tồn theo kiểm kê).
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import new_id, utcnow
from ..errors import DomainError, NotFoundError
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


def list_moves(db: Session, pkg_id: str = None) -> list:
    stmt = select(PackagingMove).order_by(PackagingMove.ts.desc()).limit(100)
    if pkg_id:
        stmt = stmt.where(PackagingMove.pkg_id == pkg_id)
    return [{"kind": m.kind, "kind_label": MOVES.get(m.kind, m.kind), "qty": m.qty,
             "ref": m.ref, "note": m.note, "by": m.by, "ts": m.ts, "pkg_id": m.pkg_id}
            for m in db.execute(stmt).scalars().all()]
