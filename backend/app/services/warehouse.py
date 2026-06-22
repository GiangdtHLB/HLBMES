"""Nghiệp vụ kho: nhập/xuất/hoàn/sang ngang + tồn/thẻ kho/hạn dùng/báo cáo."""

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import LotStatus, Role, new_id, utcnow
from ..errors import DomainError, NotFoundError
from ..models.master import Material
from ..models.materials import MaterialLot
from ..models.warehouse import StockMovement
from ..security import User, require_role


def _move(db, mtype, lot, quantity, user, **kw):
    mv = StockMovement(movement_id=new_id(), movement_type=mtype,
                       material_id=lot.material_id, lot_id=lot.lot_id, lot_code=lot.lot_code,
                       quantity=quantity, uom=lot.uom, actor=user.username, ts=utcnow(), **kw)
    db.add(mv)
    return mv


def receive(db: Session, payload: dict, user: User) -> dict:
    """Nhập kho: tạo lô mới hoặc cộng vào lô hiện có."""
    require_role(user, Role.OPERATOR, Role.SUPERVISOR)
    lot_code = payload["lot_code"]
    qty = float(payload["quantity"])
    if qty <= 0:
        raise DomainError("Số lượng nhập phải > 0.")
    lot = db.execute(select(MaterialLot).where(MaterialLot.lot_code == lot_code)).scalar_one_or_none()
    if lot:
        lot.quantity += qty
        if lot.status == LotStatus.CONSUMED.value:
            lot.status = LotStatus.AVAILABLE.value
    else:
        expiry = payload.get("expiry")
        lot = MaterialLot(lot_id=new_id(), lot_code=lot_code, material_id=payload.get("material_id"),
                          lot_type=payload.get("lot_type", "material"), supplier_lot=payload.get("supplier_lot"),
                          quantity=qty, uom=payload.get("uom", "kg"), status=LotStatus.AVAILABLE.value,
                          expiry=datetime.fromisoformat(expiry) if isinstance(expiry, str) else expiry,
                          location=payload.get("location", "Kho chính"))
        db.add(lot)
        db.flush()
    _move(db, "receipt", lot, qty, user, location_to=lot.location,
          reason=payload.get("reason"), ref_doc=payload.get("ref_doc"))
    record_audit(db, entity_type="lot", entity_id=lot.lot_id, action="receipt", actor=user,
                 after={"lot_code": lot_code, "quantity": qty})
    db.commit()
    return {"lot_id": lot.lot_id, "lot_code": lot.lot_code, "on_hand": lot.quantity, "uom": lot.uom}


def return_stock(db: Session, lot_id: str, quantity: float, user: User, reason: str = None) -> dict:
    """Nhập hoàn kho: trả vật tư chưa dùng về lô."""
    require_role(user, Role.OPERATOR, Role.SUPERVISOR)
    lot = _lot(db, lot_id)
    if quantity <= 0:
        raise DomainError("Số lượng hoàn phải > 0.")
    lot.quantity += quantity
    if lot.status == LotStatus.CONSUMED.value:
        lot.status = LotStatus.AVAILABLE.value
    _move(db, "return", lot, quantity, user, location_to=lot.location, reason=reason)
    record_audit(db, entity_type="lot", entity_id=lot.lot_id, action="return", actor=user,
                 after={"quantity": quantity})
    db.commit()
    return {"lot_id": lot.lot_id, "on_hand": lot.quantity}


def issue(db: Session, lot_id: str, quantity: float, user: User, mode: str = "tu_do",
          reason: str = None, ref_doc: str = None) -> dict:
    """Xuất kho (theo đề nghị / tự do)."""
    require_role(user, Role.OPERATOR, Role.SUPERVISOR)
    lot = _lot(db, lot_id)
    if lot.status == LotStatus.ON_HOLD.value:
        raise DomainError(f"Lô {lot.lot_code} đang HOLD, không được xuất.")
    if quantity <= 0 or quantity > lot.quantity:
        raise DomainError(f"Số lượng xuất không hợp lệ (tồn {lot.quantity} {lot.uom}).")
    lot.quantity -= quantity
    if lot.quantity == 0:
        lot.status = LotStatus.CONSUMED.value
    _move(db, "issue", lot, quantity, user, location_from=lot.location, mode=mode,
          reason=reason, ref_doc=ref_doc)
    record_audit(db, entity_type="lot", entity_id=lot.lot_id, action="issue", actor=user,
                 after={"quantity": quantity, "mode": mode})
    db.commit()
    return {"lot_id": lot.lot_id, "on_hand": lot.quantity}


def transfer(db: Session, lot_id: str, quantity: float, location_to: str, user: User,
             reason: str = None) -> dict:
    """Xuất sang ngang: chuyển vị trí (không đổi tổng tồn)."""
    require_role(user, Role.OPERATOR, Role.SUPERVISOR)
    lot = _lot(db, lot_id)
    loc_from = lot.location
    lot.location = location_to
    _move(db, "transfer", lot, quantity, user, location_from=loc_from, location_to=location_to,
          mode="sang_ngang", reason=reason)
    record_audit(db, entity_type="lot", entity_id=lot.lot_id, action="transfer", actor=user,
                 after={"from": loc_from, "to": location_to})
    db.commit()
    return {"lot_id": lot.lot_id, "location": lot.location}


def stock_on_hand(db: Session) -> list[dict]:
    """Xem tồn kho: tổng tồn theo vật tư."""
    rows = db.execute(
        select(MaterialLot.material_id, func.sum(MaterialLot.quantity), MaterialLot.uom)
        .where(MaterialLot.material_id.isnot(None))
        .group_by(MaterialLot.material_id, MaterialLot.uom)
    ).all()
    out = []
    for material_id, total, uom in rows:
        mat = db.get(Material, material_id)
        out.append({"material_id": material_id, "material_code": mat.code if mat else material_id,
                    "material_name": mat.name if mat else "", "on_hand": round(total or 0, 3),
                    "uom": uom, "category": mat.category if mat else None})
    return sorted(out, key=lambda x: x["material_code"])


def stock_card(db: Session, material_id: str = None, lot_id: str = None) -> list[dict]:
    """Thẻ kho: ledger có số dư luỹ kế."""
    stmt = select(StockMovement)
    if lot_id:
        stmt = stmt.where(StockMovement.lot_id == lot_id)
    elif material_id:
        stmt = stmt.where(StockMovement.material_id == material_id)
    movements = db.execute(stmt.order_by(StockMovement.ts)).scalars().all()
    bal = 0.0
    out = []
    for m in movements:
        sign = 1 if m.movement_type in ("receipt", "return") else (-1 if m.movement_type == "issue" else 0)
        bal += sign * m.quantity
        out.append({"ts": m.ts, "type": m.movement_type, "lot_code": m.lot_code,
                    "in": m.quantity if sign > 0 else 0, "out": m.quantity if sign < 0 else 0,
                    "balance": round(bal, 3), "uom": m.uom, "mode": m.mode,
                    "reason": m.reason, "actor": m.actor})
    return out


def expiry_report(db: Session, warn_days: int = 30) -> list[dict]:
    """Xem hạn sử dụng: phân loại ok / sắp hết hạn / hết hạn."""
    now = utcnow()
    lots = db.execute(
        select(MaterialLot).where(MaterialLot.expiry.isnot(None), MaterialLot.quantity > 0)
        .order_by(MaterialLot.expiry)
    ).scalars().all()
    out = []
    for lot in lots:
        exp = lot.expiry
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=now.tzinfo)
        days = (exp - now).days
        status = "expired" if days < 0 else ("near" if days <= warn_days else "ok")
        out.append({"lot_code": lot.lot_code, "quantity": lot.quantity, "uom": lot.uom,
                    "expiry": lot.expiry, "days_left": days, "status": status, "location": lot.location})
    return out


def inventory_report(db: Session, days: int = 30) -> list[dict]:
    """BC nhập-xuất-tồn trong kỳ: tổng nhập, tổng xuất, tồn hiện tại theo vật tư."""
    since = utcnow() - timedelta(days=days)
    on_hand = {r["material_id"]: r for r in stock_on_hand(db)}
    moves = db.execute(select(StockMovement).where(StockMovement.ts >= since)).scalars().all()
    agg = {}
    for m in moves:
        a = agg.setdefault(m.material_id, {"receipt": 0.0, "issue": 0.0, "return": 0.0})
        if m.movement_type in a:
            a[m.movement_type] += m.quantity
    out = []
    for mid, oh in on_hand.items():
        a = agg.get(mid, {"receipt": 0.0, "issue": 0.0, "return": 0.0})
        out.append({**oh, "received": round(a["receipt"] + a["return"], 3),
                    "issued": round(a["issue"], 3)})
    return out


def _lot(db, lot_id):
    lot = db.get(MaterialLot, lot_id)
    if not lot:
        raise NotFoundError("Lô không tồn tại.")
    return lot
