"""Cấp phát nguyên liệu (dispense) + backflush (tài liệu §7.4, §7.6).

- dispense: cấp liệu cho mẻ theo lô cụ thể HOẶC tự chọn lô theo FEFO (hết hạn trước
  xuất trước), tái dùng batches.consume_lot (trừ tồn + genealogy + chặn vượt định mức),
  bổ sung: chặn lô hết hạn, tách nhu cầu qua nhiều lô.
- backflush: tự khấu trừ NVL theo định mức BOM × tỉ lệ sản lượng đã sản xuất, trừ phần
  đã tiêu thụ trước đó (tránh trừ trùng), tự chọn lô FEFO.
"""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import LotStatus, Role, new_id, utcnow
from ..errors import DomainError, NotFoundError
from ..models.batches import BatchExecution
from ..models.master import Material
from ..models.materials import MaterialLot
from ..models.materials_ext import Dispense, DispenseLine
from ..security import User, require_role
from . import batches as batch_svc
from . import bom


def _is_expired(lot: MaterialLot) -> bool:
    if not lot.expiry:
        return False
    exp = lot.expiry
    now = utcnow()
    if exp.tzinfo is None:
        now = now.replace(tzinfo=None)
    return exp < now


def _fefo_lots(db: Session, material_code: str) -> list:
    """Các lô available của một material_code, sắp theo FEFO (hết hạn trước) rồi FIFO."""
    mat = db.execute(select(Material).where(Material.code == material_code)).scalar_one_or_none()
    if not mat:
        return []
    lots = db.execute(select(MaterialLot).where(
        MaterialLot.material_id == mat.material_id,
        MaterialLot.status == LotStatus.AVAILABLE.value,
        MaterialLot.quantity > 0)).scalars().all()
    lots = [l for l in lots if not _is_expired(l)]
    # expiry None → cuối hàng đợi (giá trị lớn); cùng expiry → FIFO theo created_at
    far = utcnow().replace(tzinfo=None) + timedelta(days=36500)

    def key(l):
        e = l.expiry
        if e is None:
            e = far
        elif e.tzinfo is not None:
            e = e.replace(tzinfo=None)
        c = l.created_at
        if c is not None and c.tzinfo is not None:
            c = c.replace(tzinfo=None)
        return (e, c)
    return sorted(lots, key=key)


def _consume_qty(db: Session, batch: BatchExecution, material_code: str, qty: float,
                 user: User, allow_over: bool, picked_lot_id: str = None) -> list:
    """Tiêu thụ `qty` của material_code: nếu chỉ định lot thì dùng lot đó, ngược lại
    tự chọn FEFO, tách qua nhiều lô khi cần. Trả về list dòng đã cấp."""
    lines = []
    remaining = round(qty, 6)
    if picked_lot_id:
        lot = db.get(MaterialLot, picked_lot_id)
        if not lot:
            raise NotFoundError("Lô vật tư không tồn tại.")
        if _is_expired(lot):
            raise DomainError(f"Lô {lot.lot_code} đã HẾT HẠN — không được cấp.")
        take = min(remaining, lot.quantity)
        batch_svc.consume_lot(db, batch.batch_id, lot.lot_id, take, user, allow_over)
        lines.append({"material_code": material_code, "lot_id": lot.lot_id,
                      "lot_code": lot.lot_code, "quantity": take, "uom": lot.uom})
        remaining = round(remaining - take, 6)
    else:
        for lot in _fefo_lots(db, material_code):
            if remaining <= 1e-9:
                break
            take = min(remaining, lot.quantity)
            if take <= 0:
                continue
            batch_svc.consume_lot(db, batch.batch_id, lot.lot_id, take, user, allow_over)
            lines.append({"material_code": material_code, "lot_id": lot.lot_id,
                          "lot_code": lot.lot_code, "quantity": take, "uom": lot.uom})
            remaining = round(remaining - take, 6)
    if remaining > 1e-6:
        raise DomainError(
            f"Không đủ lô khả dụng (còn hạn) cho {material_code}: thiếu {round(remaining,3)}.")
    return lines


def dispense(db: Session, batch_id: str, lines_in: list, user: User, note: str = None) -> dict:
    """Cấp liệu cho mẻ. lines_in = [{material_code, quantity, lot_id?}]."""
    require_role(user, Role.OPERATOR, Role.SUPERVISOR, Role.ENGINEER)
    batch = db.get(BatchExecution, batch_id)
    if not batch:
        raise NotFoundError("Batch không tồn tại.")
    if not lines_in:
        raise DomainError("Phiếu cấp liệu rỗng.")
    disp = Dispense(dispense_id=new_id(),
                    dispense_code=f"DISP-{utcnow():%Y%m%d}-{new_id()[:5].upper()}",
                    batch_id=batch_id, mode="dispense", status="issued",
                    note=note, created_by=user.username, created_at=utcnow())
    db.add(disp)
    db.flush()
    all_lines = []
    for ln in lines_in:
        code = ln.get("material_code")
        qty = float(ln.get("quantity") or 0)
        if not code or qty <= 0:
            continue
        rows = _consume_qty(db, batch, code, qty, user,
                            allow_over=bool(ln.get("allow_over")), picked_lot_id=ln.get("lot_id"))
        for r in rows:
            db.add(DispenseLine(line_id=new_id(), dispense_id=disp.dispense_id, **r))
            all_lines.append(r)
    record_audit(db, entity_type="batch", entity_id=batch_id, action="dispense", actor=user,
                 after={"dispense_code": disp.dispense_code, "lines": len(all_lines)})
    db.commit()
    return {"dispense_code": disp.dispense_code, "lines": all_lines,
            "bom": bom.compare_batch(db, batch)}


def backflush(db: Session, batch_id: str, produced_qty: float, user: User) -> dict:
    """Tự khấu trừ NVL theo định mức BOM cho `produced_qty` đã sản xuất.

    standard(material) = qty_BOM × (produced_qty / base_qty). Trừ phần đã consume trước đó."""
    require_role(user, Role.OPERATOR, Role.SUPERVISOR, Role.ENGINEER)
    batch = db.get(BatchExecution, batch_id)
    if not batch:
        raise NotFoundError("Batch không tồn tại.")
    snap = batch.recipe_snapshot or {}
    base = snap.get("base_qty") or 0
    if not base:
        raise DomainError("Recipe snapshot thiếu base_qty — không backflush được.")
    factor = produced_qty / base
    already = bom.actual_consumed(db, batch_id)
    disp = Dispense(dispense_id=new_id(),
                    dispense_code=f"BKF-{utcnow():%Y%m%d}-{new_id()[:5].upper()}",
                    batch_id=batch_id, mode="backflush", status="issued",
                    note=f"Backflush cho {produced_qty} {batch.uom}",
                    created_by=user.username, created_at=utcnow())
    db.add(disp)
    db.flush()
    all_lines, skipped = [], []
    # Gộp định mức theo material_code
    req_by, uom_by = {}, {}
    for m in (snap.get("materials") or []):
        code = m.get("material_code")
        req_by[code] = req_by.get(code, 0.0) + (m.get("qty", 0) or 0) * factor
        uom_by.setdefault(code, m.get("uom"))
    for code, std in req_by.items():
        need = round(std - already.get(code, 0.0), 3)
        if need <= 1e-6:
            continue
        try:
            # Backflush vẫn TÔN TRỌNG trần định mức BOM (không tự ý vượt); nếu vượt
            # sẽ rơi vào DomainError → ghi vào 'skipped' để người dùng xử lý thủ công.
            rows = _consume_qty(db, batch, code, need, user, allow_over=False)
            for r in rows:
                db.add(DispenseLine(line_id=new_id(), dispense_id=disp.dispense_id, **r))
                all_lines.append(r)
        except DomainError as e:
            skipped.append({"material_code": code, "need": need, "error": str(e)})
    record_audit(db, entity_type="batch", entity_id=batch_id, action="backflush", actor=user,
                 after={"dispense_code": disp.dispense_code, "produced_qty": produced_qty,
                        "lines": len(all_lines)})
    db.commit()
    return {"dispense_code": disp.dispense_code, "factor": round(factor, 4),
            "lines": all_lines, "skipped": skipped, "bom": bom.compare_batch(db, batch)}


def list_dispenses(db: Session, batch_id: str = None) -> list:
    stmt = select(Dispense).order_by(Dispense.created_at.desc())
    if batch_id:
        stmt = stmt.where(Dispense.batch_id == batch_id)
    out = []
    for d in db.execute(stmt).scalars().all():
        lines = db.execute(select(DispenseLine).where(
            DispenseLine.dispense_id == d.dispense_id)).scalars().all()
        out.append({"dispense_code": d.dispense_code, "batch_id": d.batch_id, "mode": d.mode,
                    "status": d.status, "note": d.note, "created_by": d.created_by,
                    "created_at": d.created_at,
                    "lines": [{"material_code": l.material_code, "lot_code": l.lot_code,
                               "quantity": l.quantity, "uom": l.uom} for l in lines]})
    return out
