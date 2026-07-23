"""WMS thành phẩm: vị trí + đơn vị tồn kho (vỉ/keg, độc lập — không pallet/case),
putaway/ship theo vị trí, tồn theo vị trí, phân giải barcode (cho đầu đọc cầm tay / kiosk)."""

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import Role, new_id, utcnow
from ..errors import DomainError, NotFoundError
from ..models.audit import AuditLog
from ..models.brewing import BottleRecord
from ..models.master import FinishedProduct
from ..models.materials import GenealogyEdge
from ..models.wms import FinishedGoodsUnit, NearExpiryEntry, Shipment, ShipToLocation, Vehicle, WmsLocation
from ..security import User, require_perm, require_role
from . import genealogy


def create_location(db: Session, payload: dict) -> WmsLocation:
    loc = WmsLocation(loc_id=new_id(), **payload)
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return loc


def update_location(db: Session, loc_id: str, payload: dict) -> WmsLocation:
    loc = db.get(WmsLocation, loc_id)
    if not loc:
        raise NotFoundError("Vị trí không tồn tại.")
    for k, v in payload.items():
        if v is not None:
            setattr(loc, k, v)
    db.commit()
    db.refresh(loc)
    return loc


def delete_location(db: Session, loc_id: str) -> None:
    loc = db.get(WmsLocation, loc_id)
    if not loc:
        raise NotFoundError("Vị trí không tồn tại.")
    used = db.execute(select(func.count(FinishedGoodsUnit.unit_id)).where(
        FinishedGoodsUnit.location_id == loc_id, FinishedGoodsUnit.status == "stored")).scalar() or 0
    if used:
        raise DomainError(f"Vị trí {loc.code} đang chứa {used} vỉ/keg — không thể xóa.")
    db.delete(loc)
    db.commit()


def list_locations(db: Session) -> list:
    locs = db.execute(select(WmsLocation).order_by(WmsLocation.code)).scalars().all()
    counts = dict(db.execute(
        select(FinishedGoodsUnit.location_id, func.count(FinishedGoodsUnit.unit_id))
        .where(FinishedGoodsUnit.status == "stored").group_by(FinishedGoodsUnit.location_id)).all())
    return [{"loc_id": l.loc_id, "code": l.code, "name": l.name, "zone": l.zone, "kind": l.kind,
             "capacity": l.capacity, "active": l.active, "used": counts.get(l.loc_id, 0)} for l in locs]


def create_ship_to(db: Session, payload: dict) -> ShipToLocation:
    st = ShipToLocation(ship_to_id=new_id(), **payload)
    db.add(st)
    db.commit()
    db.refresh(st)
    return st


def update_ship_to(db: Session, ship_to_id: str, payload: dict) -> ShipToLocation:
    st = db.get(ShipToLocation, ship_to_id)
    if not st:
        raise NotFoundError("Nơi xuất đến không tồn tại.")
    for k, v in payload.items():
        if v is not None:
            setattr(st, k, v)
    db.commit()
    db.refresh(st)
    return st


def delete_ship_to(db: Session, ship_to_id: str) -> None:
    """Chặn xóa nếu đã có phiếu xuất kho nào TỪNG dùng nơi này — khác delete_location (chặn
    theo đang chứa), ở đây phải chặn theo lịch sử vì đây là dữ liệu truy xuất/thu hồi, không
    được để genealogy edge/Shipment trỏ tới bản ghi đã bị xóa."""
    st = db.get(ShipToLocation, ship_to_id)
    if not st:
        raise NotFoundError("Nơi xuất đến không tồn tại.")
    used = db.execute(select(func.count(Shipment.shipment_id)).where(
        Shipment.ship_to_id == ship_to_id)).scalar() or 0
    if used:
        raise DomainError(f"Đã có {used} phiếu xuất kho từng dùng {st.code} — không thể xóa (ảnh hưởng truy xuất/thu hồi).")
    db.delete(st)
    db.commit()


def list_ship_to(db: Session) -> list:
    rows = db.execute(select(ShipToLocation).order_by(ShipToLocation.code)).scalars().all()
    return [{"ship_to_id": s.ship_to_id, "code": s.code, "name": s.name, "kind": s.kind,
             "address": s.address, "contact": s.contact, "active": s.active} for s in rows]


def create_vehicle(db: Session, payload: dict) -> Vehicle:
    if db.execute(select(Vehicle).where(Vehicle.plate == payload["plate"])).scalar_one_or_none():
        raise DomainError(f"Biển số '{payload['plate']}' đã tồn tại.")
    v = Vehicle(vehicle_id=new_id(), **payload)
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


def update_vehicle(db: Session, vehicle_id: str, payload: dict) -> Vehicle:
    v = db.get(Vehicle, vehicle_id)
    if not v:
        raise NotFoundError("Xe không tồn tại.")
    for k, val in payload.items():
        if val is not None:
            setattr(v, k, val)
    db.commit()
    db.refresh(v)
    return v


def delete_vehicle(db: Session, vehicle_id: str) -> None:
    v = db.get(Vehicle, vehicle_id)
    if not v:
        raise NotFoundError("Xe không tồn tại.")
    db.delete(v)
    db.commit()


def list_vehicles(db: Session) -> list:
    rows = db.execute(select(Vehicle).order_by(Vehicle.plate)).scalars().all()
    return [{"vehicle_id": v.vehicle_id, "plate": v.plate, "driver_name": v.driver_name,
             "driver_short_name": v.driver_short_name, "capacity_kg": v.capacity_kg,
             "pallet_capacity": v.pallet_capacity, "phone": v.phone, "team": v.team,
             "active": v.active} for v in rows]


def summary(db: Session) -> dict:
    """Tổng hợp toàn kho: số vị trí + sức chứa, tổng vỉ/keg theo trạng thái/loại — dùng
    COUNT/GROUP BY ở SQL, KHÔNG load từng dòng vào Python (kho có thể có hàng trăm ngàn
    đơn vị — load hết ra rồi đếm bằng vòng lặp từng chậm tới hàng phút khi 1 lô lớn)."""
    locs = db.execute(select(WmsLocation)).scalars().all()
    capacity = sum(l.capacity for l in locs)
    units_total = db.execute(select(func.count(FinishedGoodsUnit.unit_id))).scalar_one()
    by_status = dict(db.execute(select(FinishedGoodsUnit.status, func.count(FinishedGoodsUnit.unit_id))
                                .group_by(FinishedGoodsUnit.status)).all())
    by_type = dict(db.execute(select(FinishedGoodsUnit.unit_type, func.count(FinishedGoodsUnit.unit_id))
                              .group_by(FinishedGoodsUnit.unit_type)).all())
    units_stored = by_status.get("stored", 0)
    return {"locations": len(locs), "capacity_units": capacity,
            "units_total": units_total, "units_stored": units_stored,
            "fill_pct": round(units_stored / capacity * 100, 1) if capacity else 0.0,
            "by_status": by_status, "by_type": by_type}


def list_units(db: Session, status: str = None, unit_type: str = None,
               product_name: str = None, lot_code: str = None) -> list:
    """`product_name`/`lot_code` giới hạn về 1 lô cụ thể — BẮT BUỘC dùng khi cần liệt kê
    từng đơn vị (VD trước khi xóa cả lô), vì không lọc có thể trả về hàng trăm ngàn dòng
    (xem list_lot_summaries cho hiển thị tổng hợp không cần liệt kê từng dòng)."""
    stmt = select(FinishedGoodsUnit).order_by(FinishedGoodsUnit.created_at)
    if status:
        stmt = stmt.where(FinishedGoodsUnit.status == status)
    if unit_type:
        stmt = stmt.where(FinishedGoodsUnit.unit_type == unit_type)
    if product_name:
        stmt = stmt.where(FinishedGoodsUnit.product_name == product_name)
    if lot_code:
        stmt = stmt.where(FinishedGoodsUnit.lot_code == lot_code)
    out = []
    loc_by = {l.loc_id: l for l in db.execute(select(WmsLocation)).scalars().all()}
    ship_to_by = {s.ship_to_id: s for s in db.execute(select(ShipToLocation)).scalars().all()}
    bottle_codes_by_lot: dict[str, list] = {}
    for lot_no, bottle_code in db.execute(select(BottleRecord.lot_no, BottleRecord.bottle_code)
                                          .where(BottleRecord.lot_no.isnot(None))).all():
        bottle_codes_by_lot.setdefault(lot_no, []).append(bottle_code)
    for u in db.execute(stmt).scalars().all():
        loc = loc_by.get(u.location_id)
        ship_to = ship_to_by.get(u.ship_to_id)
        # bottle_code: mã chiết đã sinh ra lô này — chỉ để hiển thị tham khảo (VD Kho TP), KHÔNG
        # dùng để gom nhóm/FIFO (vẫn theo lot_code = số lô bia, xem list_lot_summaries).
        out.append({"unit_id": u.unit_id, "unit_code": u.unit_code, "unit_type": u.unit_type,
                    "finished_product_id": u.finished_product_id, "product": u.product_name,
                    "lot_code": u.lot_code, "bottle_codes": bottle_codes_by_lot.get(u.lot_code, []),
                    "quantity": u.quantity, "status": u.status,
                    "location": loc.code if loc else None,
                    "created_at": u.created_at, "shipped_at": u.shipped_at,
                    "ship_to_code": ship_to.code if ship_to else None,
                    "ship_to_name": ship_to.name if ship_to else None})
    return out


def _create_units(db: Session, payload: dict, created_by: str, actor: User) -> list[FinishedGoodsUnit]:
    """Sinh N dòng vỉ/keg — không kiểm tra quyền, dùng nội bộ (vd approve_bottle tự động
    nhập kho thành phẩm sau khi KCS duyệt chiết, không đi qua quyền warehouse.receive).
    n = ceil(total / pack_size); dòng cuối lấy phần dư (có thể lẻ), các dòng trước đủ
    pack_size."""
    total = float(payload.get("total", 0) or 0)
    pack_size = int(payload.get("pack_size", 1) or 1)
    unit_type = payload.get("unit_type") or "vi"
    if total <= 0:
        raise DomainError("Tổng số lượng phải > 0.")
    n = max(1, -(-round(total) // pack_size))
    prefix = "KEG" if unit_type == "keg" else "VI"
    stamp = f"{utcnow():%y%m%d}-{new_id()[:4].upper()}"
    remaining = total
    created = []
    for i in range(1, n + 1):
        qty = pack_size if i < n else remaining - pack_size * (n - 1)
        u = FinishedGoodsUnit(unit_id=new_id(), unit_code=f"{prefix}-{stamp}-{i:04d}", unit_type=unit_type,
                              finished_product_id=payload.get("finished_product_id"),
                              product_name=payload.get("product_name"), lot_code=payload.get("lot_code"),
                              quantity=qty, status="stored", created_by=created_by, created_at=utcnow())
        db.add(u)
        created.append(u)
    db.flush()
    record_audit(db, entity_type="finished_goods_unit", entity_id=created[0].unit_id, action="build", actor=actor,
                 after={"count": n, "unit_type": unit_type, "total": total, "lot_code": payload.get("lot_code")},
                 reason=payload.get("reason"))
    db.commit()
    for u in created:
        db.refresh(u)
    return created


def build_units(db: Session, payload: dict, user: User) -> list[FinishedGoodsUnit]:
    require_perm(user, "warehouse.receive")
    return _create_units(db, payload, user.username, user)


# ---- Nhập bia cận date: tự nhận lô chiết theo ngày giờ khai báo + lịch sử riêng ----

def find_bottle_for_datetime(db: Session, declared_at) -> list[dict]:
    """Tìm (các) lô chiết mà khoảng thời gian thực hiện (bottle_date .. ended_at, hoặc chỉ
    bottle_date nếu chưa "Kết thúc") chứa thời điểm khai báo — dùng để tự nhận lô chiết/lô
    trong kho thành phẩm khi khai báo "Nhập bia cận date". Chỉ xét mẻ chiết đã duyệt KCS
    (approved=True) vì chỉ mẻ đã duyệt mới thực sự có lô trong kho thành phẩm."""
    candidates = db.execute(select(BottleRecord).where(
        BottleRecord.approved == True, BottleRecord.bottle_date <= declared_at,  # noqa: E712
        or_(BottleRecord.ended_at.is_(None), BottleRecord.ended_at >= declared_at),
    ).order_by(BottleRecord.bottle_date.desc())).scalars().all()
    out = []
    for b in candidates:
        fp = db.get(FinishedProduct, b.finished_product_id) if b.finished_product_id else None
        out.append({"bottle_id": b.bottle_id, "bottle_code": b.bottle_code,
                    "product_name": fp.code if fp else b.beer_type, "lot_code": b.lot_no or b.bottle_code,
                    "finished_product_id": b.finished_product_id,
                    "unit_type": fp.unit_type if fp else "vi", "pack_size": fp.pack_size if fp else 24,
                    "bottle_date": b.bottle_date, "ended_at": b.ended_at})
    return out


def create_near_expiry_entry(db: Session, bottle_id: str, quantity: int, declared_at, user: User,
                             note: str = None) -> dict:
    """Khai báo "Nhập bia cận date": tăng tồn kho thành phẩm công ty (tạo vỉ/keg mới, tương
    tự Nhập kho thủ công) nhưng đánh dấu is_near_expiry=True + ghi 1 dòng lịch sử riêng
    (NearExpiryEntry, direction="in") tách biệt khỏi lịch sử nhập kho thông thường."""
    require_perm(user, "warehouse.receive")
    b = db.get(BottleRecord, bottle_id)
    if not b:
        raise NotFoundError("Không tìm thấy lô chiết tương ứng.")
    if quantity <= 0:
        raise DomainError("Số lượng phải > 0.")
    fp = db.get(FinishedProduct, b.finished_product_id) if b.finished_product_id else None
    unit_type = fp.unit_type if fp else "vi"
    pack_size = fp.pack_size if fp else 24
    product_name = fp.code if fp else b.beer_type
    lot_code = b.lot_no or b.bottle_code
    units = _create_units(db, {
        "finished_product_id": b.finished_product_id, "product_name": product_name,
        "lot_code": lot_code, "total": quantity * pack_size, "pack_size": pack_size, "unit_type": unit_type,
    }, created_by=user.username, actor=user)
    for u in units:
        u.is_near_expiry = True
        genealogy.add_edge(db, from_type="bottle", from_id=bottle_id, to_type="finished_goods_unit",
                           to_id=u.unit_id, relation="nhập bia cận date", quantity=u.quantity, uom=u.unit_type)
    entry = NearExpiryEntry(entry_id=new_id(), direction="in", product_name=product_name, lot_code=lot_code,
                            unit_type=unit_type, quantity=len(units), declared_at=declared_at,
                            bottle_id=bottle_id, note=note, created_by=user.username, created_at=utcnow(),
                            unit_codes=",".join(u.unit_code for u in units))
    db.add(entry)
    record_audit(db, entity_type="near_expiry_entry", entity_id=entry.entry_id, action="create", actor=user,
                after={"bottle_code": b.bottle_code, "lot_code": lot_code, "count": len(units)})
    db.commit()
    return {"entry_id": entry.entry_id, "bottle_code": b.bottle_code, "product_name": product_name,
            "lot_code": lot_code, "unit_type": unit_type, "count": len(units),
            "unit_codes": [u.unit_code for u in units]}


def list_near_expiry_entries(db: Session) -> list[dict]:
    entries = db.execute(select(NearExpiryEntry).order_by(NearExpiryEntry.created_at.desc())).scalars().all()
    out = []
    for e in entries:
        shipment = db.get(Shipment, e.shipment_id) if e.shipment_id else None
        out.append({"entry_id": e.entry_id, "direction": e.direction, "product_name": e.product_name,
                    "lot_code": e.lot_code, "unit_type": e.unit_type, "quantity": e.quantity,
                    "declared_at": e.declared_at, "shipment_code": shipment.shipment_code if shipment else None,
                    "note": e.note, "created_by": e.created_by, "created_at": e.created_at,
                    "reversed": e.reversed,
                    "can_undo": e.direction == "in" and not e.reversed and bool(e.unit_codes)})
    return out


def undo_near_expiry_entry(db: Session, entry_id: str, user: User) -> dict:
    """Hoàn tác 1 bản khai "Nhập bia cận date" (direction="in"): xoá đúng các vỉ/keg do lần
    khai báo đó tạo ra (theo unit_codes đã lưu lúc tạo) + gỡ cạnh genealogy liên quan, miễn
    là các đơn vị đó vẫn còn "stored" (chưa xuất/phân rã/điều chuyển đi nơi khác — phân rã và
    điều chuyển không đổi status nhưng phân rã xoá hẳn dòng gốc nên sẽ tự nhiên bị chặn ở
    bước kiểm unit_codes vẫn còn đủ dưới đây)."""
    require_perm(user, "warehouse.receive")
    entry = db.get(NearExpiryEntry, entry_id)
    if not entry:
        raise NotFoundError("Không tìm thấy bản khai.")
    if entry.direction != "in":
        raise DomainError("Chỉ có thể hoàn tác bản khai \"Nhập bia cận date\" (không áp dụng cho dòng tự động khi xuất kho).")
    if entry.reversed:
        raise DomainError("Bản khai này đã được hoàn tác trước đó.")
    if not entry.unit_codes:
        raise DomainError("Bản khai này không có dữ liệu vỉ/keg để hoàn tác (được tạo trước khi có tính năng này).")
    unit_codes = entry.unit_codes.split(",")
    units = db.execute(select(FinishedGoodsUnit).where(
        FinishedGoodsUnit.unit_code.in_(unit_codes))).scalars().all()
    if len(units) != len(unit_codes):
        raise DomainError("Một số vỉ/keg của bản khai này đã bị xoá/phân rã ở nơi khác, không thể hoàn tác.")
    not_stored = [u.unit_code for u in units if u.status != "stored"]
    if not_stored:
        raise DomainError(f"Vỉ/keg đã xuất hoặc không còn trong kho ({', '.join(not_stored)}), không thể hoàn tác.")
    unit_ids = [u.unit_id for u in units]
    edges = db.execute(select(GenealogyEdge).where(
        GenealogyEdge.from_type == "bottle", GenealogyEdge.from_id == entry.bottle_id,
        GenealogyEdge.to_type == "finished_goods_unit", GenealogyEdge.to_id.in_(unit_ids))).scalars().all()
    for e in edges:
        db.delete(e)
    for u in units:
        db.delete(u)
    entry.reversed = True
    record_audit(db, entity_type="near_expiry_entry", entity_id=entry.entry_id, action="undo", actor=user,
                before={"count": len(units)}, after={"reversed": True})
    db.commit()
    return {"entry_id": entry.entry_id, "removed": len(units)}


def adjust_bottle_finish_stock(db: Session, *, finished_product_id: str | None, product_name: str,
                               lot_code: str, unit_type: str, pack_size: int, delta_total: float,
                               bottle_id: str, actor: User) -> dict:
    """Điều chỉnh tồn kho thành phẩm khi Ca 1/2/3 của 1 mẻ chiết ĐÃ DUYỆT bị sửa lại (gọi lại
    finish_bottle sau approve_bottle) — trước đây approve_bottle chỉ nhập kho ĐÚNG 1 LẦN lúc
    duyệt, sửa Ca sau đó không cập nhật lại số vỉ/keg đã tạo, khiến tồn kho lệch khỏi sản
    lượng hiển thị (bug thực tế — xem finish_bottle). delta>0: tạo thêm vỉ/keg mới (mirror
    approve_bottle/_create_units). delta<0: bớt từ các đơn vị "stored" MỚI TẠO TRƯỚC (LIFO —
    ưu tiên hoàn tác đúng phần vừa cộng dư do sửa số, không đụng hàng cũ hơn đã có sẵn từ
    trước khi sửa). Chặn nếu tồn "stored" không đủ để bớt (nghĩa là 1 phần đã xuất/điều
    chuyển đi nơi khác) — không tự ý xóa hàng đã rời kho."""
    if delta_total == 0:
        return {"created": 0, "removed": 0}
    if delta_total > 0:
        units = _create_units(db, {
            "finished_product_id": finished_product_id, "product_name": product_name,
            "lot_code": lot_code, "total": delta_total, "pack_size": pack_size, "unit_type": unit_type,
        }, created_by=actor.username, actor=actor)
        for u in units:
            genealogy.add_edge(db, from_type="bottle", from_id=bottle_id, to_type="finished_goods_unit",
                               to_id=u.unit_id, relation="nhập kho (sửa SL)", quantity=u.quantity, uom=u.unit_type)
        record_audit(db, entity_type="finished_goods_unit", entity_id=units[0].unit_id, action="adjust_bottle_finish",
                     actor=actor, before={"bottle_id": bottle_id, "delta": delta_total},
                     after={"created": len(units)})
        db.commit()
        return {"created": len(units), "removed": 0}

    need = -delta_total
    candidates = db.execute(select(FinishedGoodsUnit).where(
        FinishedGoodsUnit.product_name == product_name, FinishedGoodsUnit.lot_code == lot_code,
        FinishedGoodsUnit.unit_type == unit_type, FinishedGoodsUnit.status == "stored",
    ).order_by(FinishedGoodsUnit.created_at.desc())).scalars().all()
    available = sum(u.quantity for u in candidates)
    if available < need:
        raise DomainError(
            f"Không thể tự động giảm tồn kho theo Ca mới — chỉ còn {available:g} {unit_type} đang ở trạng "
            f"thái tồn kho trong khi cần giảm {need:g} (phần còn lại có thể đã xuất/điều chuyển đi nơi khác). "
            "Hãy xử lý điều chỉnh tồn kho thủ công.")
    removed_ids = []
    remaining = need
    for u in candidates:
        if remaining <= 0:
            break
        if u.quantity <= remaining:
            remaining -= u.quantity
            removed_ids.append(u.unit_id)
            db.delete(u)
        else:
            u.quantity -= remaining
            remaining = 0
    # Chia nhỏ IN(...) theo lô 500 id — SQLite giới hạn số biến/câu lệnh (~999), số lượng đơn
    # vị cần xóa có thể lên tới hàng chục nghìn dòng nếu Ca bị sửa giảm rất nhiều.
    for i in range(0, len(removed_ids), 500):
        chunk = removed_ids[i:i + 500]
        edges = db.execute(select(GenealogyEdge).where(
            GenealogyEdge.to_type == "finished_goods_unit", GenealogyEdge.to_id.in_(chunk))).scalars().all()
        for e in edges:
            db.delete(e)
    record_audit(db, entity_type="finished_goods_unit", entity_id=bottle_id, action="adjust_bottle_finish",
                 actor=actor, before={"bottle_id": bottle_id, "delta": delta_total},
                 after={"removed_units": len(removed_ids), "removed_qty": need})
    db.commit()
    return {"created": 0, "removed": len(removed_ids)}


def _capacity_ok(db: Session, loc: WmsLocation, exclude_unit: str = None) -> bool:
    used = db.execute(select(func.count(FinishedGoodsUnit.unit_id)).where(
        FinishedGoodsUnit.location_id == loc.loc_id, FinishedGoodsUnit.status == "stored",
        FinishedGoodsUnit.unit_id != (exclude_unit or ""))).scalar() or 0
    return used < loc.capacity


def putaway(db: Session, unit_id: str, loc_id: str, user: User) -> dict:
    require_perm(user, "warehouse.issue")
    u = db.get(FinishedGoodsUnit, unit_id)
    if not u:
        raise NotFoundError("Vỉ/keg không tồn tại.")
    if u.status != "stored":
        raise DomainError(f"{u.unit_code} không ở trạng thái tồn kho (đã xuất/đã phân rã) — không thể cất.")
    loc = db.get(WmsLocation, loc_id)
    if not loc:
        raise NotFoundError("Vị trí không tồn tại.")
    if not _capacity_ok(db, loc, exclude_unit=unit_id):
        raise DomainError(f"Vị trí {loc.code} đã đầy (sức chứa {loc.capacity}).")
    before = {"location": u.location_id, "status": u.status}
    u.location_id = loc.loc_id
    u.status = "stored"
    record_audit(db, entity_type="finished_goods_unit", entity_id=unit_id, action="putaway", actor=user,
                 before=before, after={"location": loc.code})
    db.commit()
    return {"unit_code": u.unit_code, "location": loc.code, "status": u.status}


def transfer_units(db: Session, unit_ids: list, to_loc_id: str, user: User) -> dict:
    """Điều chuyển nội bộ: đổi vị trí hàng loạt cho các vỉ/keg/lon đang tồn kho —
    vị trí nguồn giảm, vị trí đích tăng (không đổi tổng tồn toàn kho)."""
    require_perm(user, "warehouse.issue")
    if not unit_ids:
        raise DomainError("Phải chọn ít nhất 1 đơn vị để điều chuyển.")
    to_loc = db.get(WmsLocation, to_loc_id)
    if not to_loc:
        raise NotFoundError("Vị trí đích không tồn tại.")

    units = []
    for unit_id in unit_ids:
        u = db.get(FinishedGoodsUnit, unit_id)
        if not u:
            raise NotFoundError("Vỉ/keg/lon không tồn tại.")
        if u.status != "stored":
            raise DomainError(f"{u.unit_code} không ở trạng thái tồn kho (đã xuất/đã phân rã) — không thể điều chuyển.")
        units.append(u)

    moving_in = [u for u in units if u.location_id != to_loc_id]
    if moving_in:
        used_at_dest = db.execute(select(func.count(FinishedGoodsUnit.unit_id)).where(
            FinishedGoodsUnit.location_id == to_loc_id, FinishedGoodsUnit.status == "stored")).scalar() or 0
        if used_at_dest + len(moving_in) > to_loc.capacity:
            raise DomainError(f"Vị trí {to_loc.code} không đủ sức chứa (sức chứa {to_loc.capacity}, "
                              f"hiện có {used_at_dest}, cần thêm {len(moving_in)}).")

    loc_by = {l.loc_id: l for l in db.execute(select(WmsLocation)).scalars().all()}
    from_codes = [loc_by[u.location_id].code if u.location_id in loc_by else None for u in units]
    unit_codes = [u.unit_code for u in units]
    for u in units:
        u.location_id = to_loc_id
    record_audit(db, entity_type="finished_goods_unit", entity_id=new_id(), action="transfer", actor=user,
                 before={"unit_codes": unit_codes, "from_locations": from_codes},
                 after={"unit_codes": unit_codes, "to_location": to_loc.code})
    db.commit()
    return {"moved": len(units), "to_location": to_loc.code, "unit_codes": unit_codes}


def _decompose_one_vi(db: Session, u: FinishedGoodsUnit, actor_username: str) -> list:
    """Sinh các lon lẻ từ 1 vỉ (nội bộ, không audit/không commit — gọi trong 1 transaction
    lớn hơn của decompose_unit/decompose_batch). Lon kế thừa created_at của vỉ gốc để FIFO
    tính đúng theo tuổi bia thật. Đánh dấu vỉ gốc status="decomposed" (không xóa, giữ để
    truy vết genealogy/audit, loại khỏi mọi truy vấn tồn khả dụng)."""
    count = max(1, round(u.quantity))
    stamp = f"{utcnow():%y%m%d}-{new_id()[:4].upper()}"
    lon_units = []
    for i in range(1, count + 1):
        lon = FinishedGoodsUnit(unit_id=new_id(), unit_code=f"LON-{stamp}-{i:04d}", unit_type="lon",
                                finished_product_id=u.finished_product_id, product_name=u.product_name,
                                lot_code=u.lot_code, quantity=1, status="stored", location_id=u.location_id,
                                created_by=actor_username, created_at=u.created_at)
        db.add(lon)
        lon_units.append(lon)
    db.flush()
    u.status = "decomposed"
    for lon in lon_units:
        genealogy.add_edge(db, from_type="finished_goods_unit", from_id=u.unit_id,
                           to_type="finished_goods_unit", to_id=lon.unit_id, relation="phân rã",
                           quantity=1, uom="lon")
    return lon_units


def decompose_unit(db: Session, unit_id: str, user: User) -> dict:
    """Phân rã 1 vỉ cụ thể (theo unit_id) thành các lon lẻ."""
    require_perm(user, "warehouse.issue")
    u = db.get(FinishedGoodsUnit, unit_id)
    if not u:
        raise NotFoundError("Vỉ không tồn tại.")
    if u.unit_type != "vi":
        raise DomainError("Chỉ có thể phân rã đơn vị loại vỉ.")
    if u.status != "stored":
        raise DomainError("Chỉ phân rã được vỉ đang tồn kho (chưa xuất/chưa phân rã).")

    lon_units = _decompose_one_vi(db, u, user.username)
    record_audit(db, entity_type="finished_goods_unit", entity_id=u.unit_id, action="decompose", actor=user,
                 before={"unit_code": u.unit_code, "quantity": u.quantity,
                         "product_name": u.product_name, "lot_code": u.lot_code},
                 after={"lon_codes": [l.unit_code for l in lon_units], "count": len(lon_units)})
    db.commit()
    return {"source_unit_code": u.unit_code, "count": len(lon_units),
            "lon_unit_codes": [l.unit_code for l in lon_units]}


def decompose_batch(db: Session, product_name: str, lot_code: str, count: int, user: User) -> dict:
    """Phân rã N vỉ (cũ nhất trước — FIFO) của 1 sản phẩm/lô thành lon — dùng cho kho có
    hàng trăm ngàn vỉ, không yêu cầu chọn từng vỉ một. Nếu tồn ít hơn N, phân rã hết số
    hiện có (trả về đúng số đã xử lý để frontend báo nếu thiếu)."""
    require_perm(user, "warehouse.issue")
    if count <= 0:
        raise DomainError("Số vỉ cần phân rã phải > 0.")
    candidates = db.execute(select(FinishedGoodsUnit).where(
        FinishedGoodsUnit.product_name == product_name, FinishedGoodsUnit.lot_code == lot_code,
        FinishedGoodsUnit.unit_type == "vi", FinishedGoodsUnit.status == "stored"
    ).order_by(FinishedGoodsUnit.created_at).limit(count)).scalars().all()
    if not candidates:
        raise DomainError("Không còn vỉ nào tồn kho cho sản phẩm/lô này.")

    source_unit_ids = [u.unit_id for u in candidates]
    lon_unit_ids = []
    for u in candidates:
        lon_unit_ids += [lon.unit_id for lon in _decompose_one_vi(db, u, user.username)]

    entry = record_audit(db, entity_type="finished_goods_unit", entity_id=new_id(), action="decompose_batch", actor=user,
                         before={"product_name": product_name, "lot_code": lot_code, "requested": count},
                         after={"vi_decomposed": len(candidates), "lon_created": len(lon_unit_ids),
                                "source_unit_ids": source_unit_ids, "lon_unit_ids": lon_unit_ids})
    db.commit()
    return {"vi_decomposed": len(candidates), "lon_created": len(lon_unit_ids), "requested": count,
            "audit_id": entry.audit_id}


def undo_decompose_batch(db: Session, audit_id: str, user: User) -> dict:
    """Hoàn tác 1 lượt phân rã hàng loạt (decompose_batch) — CHỈ khi toàn bộ lon sinh ra từ
    lượt đó chưa xuất kho (status vẫn "stored", chưa gắn Shipment nào — "chưa xuất sử dụng").
    Không sửa/xóa bản ghi audit gốc (chuỗi hash audit bất biến, §10.3) — xóa các lon đã sinh
    + trả vỉ nguồn về "stored", rồi ghi 1 audit MỚI action="undo_decompose_batch" tham chiếu
    lại audit_id gốc (dùng để phát hiện & chặn hoàn tác 2 lần cho cùng 1 lượt)."""
    require_perm(user, "warehouse.issue")
    entry = db.get(AuditLog, audit_id)
    if not entry or entry.entity_type != "finished_goods_unit" or entry.action != "decompose_batch":
        raise NotFoundError("Không tìm thấy lượt phân rã này.")

    prior_undos = db.execute(select(AuditLog).where(
        AuditLog.entity_type == "finished_goods_unit", AuditLog.action == "undo_decompose_batch")).scalars().all()
    if any((u.before or {}).get("decompose_audit_id") == audit_id for u in prior_undos):
        raise DomainError("Lượt phân rã này đã được hoàn tác trước đó.")

    source_unit_ids = (entry.after or {}).get("source_unit_ids") or []
    lon_unit_ids = (entry.after or {}).get("lon_unit_ids") or []
    if not source_unit_ids or not lon_unit_ids:
        raise DomainError("Lượt phân rã này thực hiện trước khi hỗ trợ hoàn tác — không thể hoàn tác.")

    lons = db.execute(select(FinishedGoodsUnit).where(FinishedGoodsUnit.unit_id.in_(lon_unit_ids))).scalars().all()
    if any(l.status != "stored" for l in lons):
        raise DomainError("Đã có lon xuất kho/sử dụng từ lượt phân rã này — không thể hoàn tác.")

    sources = db.execute(select(FinishedGoodsUnit).where(FinishedGoodsUnit.unit_id.in_(source_unit_ids))).scalars().all()
    edges = db.execute(select(GenealogyEdge).where(
        GenealogyEdge.from_type == "finished_goods_unit", GenealogyEdge.from_id.in_(source_unit_ids),
        GenealogyEdge.to_type == "finished_goods_unit", GenealogyEdge.to_id.in_(lon_unit_ids))).scalars().all()
    for e in edges:
        db.delete(e)
    for l in lons:
        db.delete(l)
    for s in sources:
        s.status = "stored"

    record_audit(db, entity_type="finished_goods_unit", entity_id=entry.entity_id, action="undo_decompose_batch",
                 actor=user, before={"decompose_audit_id": audit_id,
                                     "product_name": (entry.before or {}).get("product_name"),
                                     "lot_code": (entry.before or {}).get("lot_code")},
                 after={"vi_restored": len(sources), "lon_removed": len(lons)})
    db.commit()
    return {"vi_restored": len(sources), "lon_removed": len(lons)}


def free_issue_batch(db: Session, product_name: str, lot_code: str | None, unit_type: str,
                     count: int, reason: str, user: User) -> dict:
    """Xuất tự do (không qua Shipment) N vỉ/keg/lon CŨ NHẤT (FIFO) của 1 sản phẩm/lô — dùng
    cho hao hụt nội bộ/hủy hàng/kiểm tra chất lượng, KHÔNG phải bán hàng thật (đã có Xuất
    kho/Shipment riêng cho việc đó). Chỉ admin, bắt buộc nêu lý do (mirror return_to_supplier)
    — mirror decompose_batch nhưng đánh dấu status="issued_free" (loại khỏi tồn khả dụng, xem
    list_lot_summaries lọc status="stored") thay vì tạo dòng con; hoàn tác được như
    undo_decompose_batch (xem undo_free_issue_batch)."""
    require_role(user, Role.ADMIN)
    if not reason or not reason.strip():
        raise DomainError("Phải nhập lý do xuất tự do.")
    if count <= 0:
        raise DomainError("Số lượng xuất phải > 0.")
    candidates = db.execute(select(FinishedGoodsUnit).where(
        FinishedGoodsUnit.product_name == product_name, FinishedGoodsUnit.lot_code == lot_code,
        FinishedGoodsUnit.unit_type == unit_type, FinishedGoodsUnit.status == "stored"
    ).order_by(FinishedGoodsUnit.created_at).limit(count)).scalars().all()
    if not candidates:
        raise DomainError("Không còn đơn vị nào tồn kho cho sản phẩm/lô này.")

    for u in candidates:
        u.status = "issued_free"
    unit_ids = [u.unit_id for u in candidates]

    entry = record_audit(db, entity_type="finished_goods_unit", entity_id=new_id(), action="free_issue_batch",
                         actor=user, before={"product_name": product_name, "lot_code": lot_code,
                                             "unit_type": unit_type, "requested": count},
                         after={"issued": len(candidates), "unit_ids": unit_ids,
                                "unit_codes": [u.unit_code for u in candidates]},
                         reason=reason)
    db.commit()
    return {"issued": len(candidates), "requested": count, "audit_id": entry.audit_id}


def undo_free_issue_batch(db: Session, audit_id: str, user: User) -> dict:
    """Hoàn tác 1 lượt xuất tự do (free_issue_batch) — CHỈ khi toàn bộ đơn vị của lượt đó
    vẫn còn status="issued_free" (chưa bị thao tác gì khác từ lúc xuất). Mirror
    undo_decompose_batch: không sửa/xóa audit gốc, trả các đơn vị về "stored" rồi ghi 1
    audit mới tham chiếu lại audit_id gốc (chặn hoàn tác 2 lần)."""
    require_role(user, Role.ADMIN)
    entry = db.get(AuditLog, audit_id)
    if not entry or entry.entity_type != "finished_goods_unit" or entry.action != "free_issue_batch":
        raise NotFoundError("Không tìm thấy lượt xuất tự do này.")

    prior_undos = db.execute(select(AuditLog).where(
        AuditLog.entity_type == "finished_goods_unit", AuditLog.action == "undo_free_issue_batch")).scalars().all()
    if any((u.before or {}).get("free_issue_audit_id") == audit_id for u in prior_undos):
        raise DomainError("Lượt xuất tự do này đã được hoàn tác trước đó.")

    unit_ids = (entry.after or {}).get("unit_ids") or []
    if not unit_ids:
        raise DomainError("Lượt xuất tự do này không có dữ liệu để hoàn tác.")
    units = db.execute(select(FinishedGoodsUnit).where(FinishedGoodsUnit.unit_id.in_(unit_ids))).scalars().all()
    if any(u.status != "issued_free" for u in units):
        raise DomainError("Có đơn vị đã thay đổi trạng thái sau khi xuất — không thể hoàn tác.")

    for u in units:
        u.status = "stored"
    record_audit(db, entity_type="finished_goods_unit", entity_id=entry.entity_id, action="undo_free_issue_batch",
                 actor=user, before={"free_issue_audit_id": audit_id,
                                     "product_name": (entry.before or {}).get("product_name"),
                                     "lot_code": (entry.before or {}).get("lot_code")},
                 after={"restored": len(units)})
    db.commit()
    return {"restored": len(units)}


def list_free_issues(db: Session, limit: int = 200) -> list[dict]:
    """Lịch sử xuất tự do (kho thành phẩm) — mỗi lượt free_issue_batch kèm cờ đã hoàn tác
    hay chưa (tra theo undo_free_issue_batch tham chiếu lại)."""
    entries = db.execute(select(AuditLog).where(
        AuditLog.entity_type == "finished_goods_unit",
        AuditLog.action.in_(["free_issue_batch", "undo_free_issue_batch"])
    ).order_by(AuditLog.ts.desc()).limit(limit * 2)).scalars().all()
    undone_ids = {(e.before or {}).get("free_issue_audit_id") for e in entries
                  if e.action == "undo_free_issue_batch"}
    rows = []
    for e in entries:
        if e.action != "free_issue_batch":
            continue
        rows.append({"audit_id": e.audit_id, "ts": e.ts, "actor": e.actor,
                    "product_name": (e.before or {}).get("product_name"),
                    "lot_code": (e.before or {}).get("lot_code"),
                    "unit_type": (e.before or {}).get("unit_type"),
                    "requested": (e.before or {}).get("requested"),
                    "issued": (e.after or {}).get("issued"),
                    "reason": e.reason, "undone": e.audit_id in undone_ids})
    return rows[:limit]


def list_lot_summaries(db: Session) -> list:
    """Tổng hợp tồn kho theo (sản phẩm, lô) — mỗi dòng gộp số lượng vỉ/keg/lon, dùng cho
    picker Xuất kho (không liệt kê từng đơn vị — kho có thể có hàng trăm ngàn vỉ).
    has_lon: lô này đã từng phân rã ra lon lẻ (còn tồn) hay chưa — dùng cho bộ lọc.
    {type}_fifo_ok: lô này có phải lô CŨ NHẤT còn tồn của (sản phẩm, loại đơn vị) này
    không — để người dùng thấy ngay có nên chọn lô này trước hay không, đúng thứ tự FIFO
    mà create_shipment vẫn áp dụng khi tự chọn đơn vị.
    bottle_codes: mã chiết (BottleRecord.bottle_code) đã sinh ra lot_code này — tra qua
    BottleRecord.lot_no == lot_code (thường 1:1, nhưng liệt kê hết phòng khi trùng số lô bia
    thủ công) — chỉ để hiển thị tham khảo, KHÔNG dùng để gom nhóm/FIFO (vẫn theo lot_code).
    {type}_locations: danh sách [{"code","name","count"}] các vị trí kho đang giữ loại đơn vị
    đó của lô này (1 lô/loại vẫn có thể nằm rải rác nhiều vị trí) — "(chưa cất vị trí)" tính
    riêng qua {type}_unplaced, không lẫn vào đây."""
    rows = db.execute(select(FinishedGoodsUnit.product_name, FinishedGoodsUnit.lot_code,
                             FinishedGoodsUnit.unit_type, FinishedGoodsUnit.location_id,
                             func.count(FinishedGoodsUnit.unit_id),
                             func.sum(FinishedGoodsUnit.quantity), func.min(FinishedGoodsUnit.created_at))
                      .where(FinishedGoodsUnit.status == "stored")
                      .group_by(FinishedGoodsUnit.product_name, FinishedGoodsUnit.lot_code,
                               FinishedGoodsUnit.unit_type, FinishedGoodsUnit.location_id)).all()
    bottle_codes_by_lot: dict[str, list] = {}
    for lot_no, bottle_code in db.execute(select(BottleRecord.lot_no, BottleRecord.bottle_code)
                                          .where(BottleRecord.lot_no.isnot(None))).all():
        bottle_codes_by_lot.setdefault(lot_no, []).append(bottle_code)
    loc_meta_by_id = {l.loc_id: (l.code, l.name) for l in db.execute(select(WmsLocation)).scalars().all()}
    grouped: dict[tuple, dict] = {}
    oldest_by_type: dict[tuple, object] = {}
    loc_counts: dict[tuple, dict] = {}  # (product_name, lot_code, unit_type) -> {loc_id: count}
    for product_name, lot_code, unit_type, location_id, count, qty, oldest_at in rows:
        key = (product_name, lot_code)
        g = grouped.setdefault(key, {"product_name": product_name, "lot_code": lot_code,
                                     "bottle_codes": bottle_codes_by_lot.get(lot_code, []),
                                     "vi_count": 0, "vi_qty": 0.0, "vi_unplaced": 0,
                                     "keg_count": 0, "keg_qty": 0.0, "keg_unplaced": 0,
                                     "lon_count": 0, "lon_qty": 0.0, "lon_unplaced": 0})
        if f"{unit_type}_count" in g:
            g[f"{unit_type}_count"] += count
            g[f"{unit_type}_qty"] += qty or 0
            if location_id is None:
                g[f"{unit_type}_unplaced"] += count
            else:
                lc = loc_counts.setdefault((product_name, lot_code, unit_type), {})
                lc[location_id] = lc.get(location_id, 0) + count
            prev_oldest = g.get(f"{unit_type}_oldest_at")
            if prev_oldest is None or (oldest_at and oldest_at < prev_oldest):
                g[f"{unit_type}_oldest_at"] = oldest_at
        type_key = (product_name, unit_type)
        if type_key not in oldest_by_type or (oldest_at and oldest_at < oldest_by_type[type_key]):
            oldest_by_type[type_key] = oldest_at
    for g in grouped.values():
        g["has_lon"] = g["lon_count"] > 0
        for t in ("vi", "keg", "lon"):
            oldest_at = g.pop(f"{t}_oldest_at", None)
            if g[f"{t}_count"] > 0:
                g[f"{t}_fifo_ok"] = oldest_at == oldest_by_type.get((g["product_name"], t))
                g[f"{t}_oldest_at"] = oldest_at.isoformat() if oldest_at else None
            else:
                g[f"{t}_fifo_ok"] = None
                g[f"{t}_oldest_at"] = None
            lc = loc_counts.get((g["product_name"], g["lot_code"], t), {})
            g[f"{t}_locations"] = sorted(({"code": loc_meta_by_id.get(loc_id, (loc_id, None))[0],
                                           "name": loc_meta_by_id.get(loc_id, (loc_id, None))[1],
                                           "count": cnt} for loc_id, cnt in lc.items()),
                                         key=lambda x: -x["count"])
    return sorted(grouped.values(), key=lambda g: (g["product_name"] or "", g["lot_code"] or ""))


# Ngưỡng mặc định (số ngày tồn kho kể từ đơn vị nhập sớm nhất trong nhóm) để tô màu cảnh báo ở
# báo cáo tồn kho theo tuổi — khối kinh doanh dùng để biết lô nào cần đẩy bán gấp. Có thể chỉnh
# qua Cài đặt vận hành (OpsSetting.aging_*_days), xem lot_aging_report().
AGING_BUCKETS = [(90, "critical"), (60, "warning"), (30, "caution")]


def lot_aging_report(db: Session, caution_days: float = 30.0, warning_days: float = 60.0,
                     critical_days: float = 90.0) -> list[dict]:
    """Báo cáo tồn kho thành phẩm theo TUỔI LÔ — mỗi dòng 1 (sản phẩm, lô, loại đơn vị) còn
    tồn kho ("stored"), kèm ngày nhập sớm nhất, số ngày đã tồn và vị trí kho — để khối kinh
    doanh biết lô nào tồn lâu cần đẩy nhanh tiến độ bán hàng. Gộp qua SQL GROUP BY (không tải
    từng đơn vị — 1 lô có thể có hàng trăm nghìn vỉ, xem list_lot_summaries). Ngưỡng cảnh báo
    (caution/warning/critical) lấy từ Cài đặt vận hành, mặc định 30/60/90 ngày."""
    buckets = [(critical_days, "critical"), (warning_days, "warning"), (caution_days, "caution")]
    rows = db.execute(select(FinishedGoodsUnit.product_name, FinishedGoodsUnit.lot_code,
                             FinishedGoodsUnit.unit_type, FinishedGoodsUnit.location_id,
                             func.count(FinishedGoodsUnit.unit_id),
                             func.sum(FinishedGoodsUnit.quantity), func.min(FinishedGoodsUnit.created_at))
                      .where(FinishedGoodsUnit.status == "stored")
                      .group_by(FinishedGoodsUnit.product_name, FinishedGoodsUnit.lot_code,
                               FinishedGoodsUnit.unit_type, FinishedGoodsUnit.location_id)).all()
    loc_code_by_id = {l.loc_id: l.code for l in db.execute(select(WmsLocation)).scalars().all()}
    # FinishedGoodsUnit.product_name thực ra lưu MÃ SKU (vd "FLGN200"), không phải tên hiển thị —
    # tra thêm bảng finished_product để lấy đúng tên tiếng Việt (vd "Bia tươi Legend 20L") cho
    # báo cáo/Dashboard hiển thị, không đổi tên cột product_name (đã dùng khắp module này làm khoá).
    fp_name_by_code = {fp.code: fp.name for fp in db.execute(select(FinishedProduct)).scalars().all()}
    now = utcnow()
    grouped: dict[tuple, dict] = {}
    for product_name, lot_code, unit_type, location_id, count, qty, oldest_at in rows:
        key = (product_name, lot_code, unit_type)
        g = grouped.setdefault(key, {"product_name": product_name,
                                     "product_display_name": fp_name_by_code.get(product_name, product_name),
                                     "lot_code": lot_code,
                                     "unit_type": unit_type, "count": 0, "quantity": 0.0,
                                     "oldest_at": None, "locations": [], "unplaced": 0})
        g["count"] += count
        g["quantity"] += qty or 0
        if location_id is None:
            g["unplaced"] += count
        else:
            g["locations"].append({"code": loc_code_by_id.get(location_id), "count": count})
        if g["oldest_at"] is None or (oldest_at and oldest_at < g["oldest_at"]):
            g["oldest_at"] = oldest_at
    out = []
    for g in grouped.values():
        oldest_at = g.pop("oldest_at")
        # Dùng total_seconds()/86400 (số thực) thay vì .days (làm tròn xuống số nguyên) — ngưỡng
        # cảnh báo cho phép nhập số thực (VD 0.2 ngày ~ 4.8 giờ) nên tuổi lô cũng phải giữ phần lẻ,
        # nếu không mọi lô mới nhập trong vòng chưa đủ 24h đều ra age_days=0, không bao giờ vượt
        # ngưỡng < 1 ngày.
        age_days = round((now - oldest_at).total_seconds() / 86400, 2) if oldest_at else None
        bucket = next((b for days, b in buckets if age_days is not None and age_days >= days), "ok")
        out.append({**g, "received_at": oldest_at.isoformat() if oldest_at else None,
                    "age_days": age_days, "age_bucket": bucket})
    return sorted(out, key=lambda g: -(g["age_days"] or 0))


def list_lot_summaries_by_location(db: Session, loc_id: str) -> list:
    """Tổng hợp tồn "stored" theo (sản phẩm, lô, loại đơn vị) tại RIÊNG 1 vị trí kho — dùng
    cho picker Điều chuyển nội bộ (chọn vị trí nguồn rồi xem có gì để chuyển), tính bằng
    GROUP BY ở SQL thay vì tải hết đơn vị toàn kho về rồi lọc/gộp bằng Python (kho có thể có
    hàng trăm ngàn đơn vị)."""
    rows = db.execute(select(FinishedGoodsUnit.product_name, FinishedGoodsUnit.lot_code,
                             FinishedGoodsUnit.unit_type, func.count(FinishedGoodsUnit.unit_id))
                      .where(FinishedGoodsUnit.status == "stored", FinishedGoodsUnit.location_id == loc_id)
                      .group_by(FinishedGoodsUnit.product_name, FinishedGoodsUnit.lot_code,
                               FinishedGoodsUnit.unit_type)).all()
    return [{"product_name": product_name, "lot_code": lot_code, "unit_type": unit_type, "count": count}
            for product_name, lot_code, unit_type, count in rows]


def delete_units_by_criteria(db: Session, product_name: str, lot_code: str | None, unit_type: str,
                             user: User) -> dict:
    """Xóa CẢ LÔ vỉ/keg theo (sản phẩm, lô, loại) thay vì theo danh sách unit_id — tránh phải
    tải/gửi hàng trăm ngàn unit_id qua mạng (xem delete_units cho trường hợp chọn từng đơn
    vị cụ thể). CHỈ xóa các dòng đang "stored" (đã xuất/phân rã thì lô này không còn khớp
    tiêu chí lọc status='stored' nên tự động không bị đụng tới — không cần kiểm tra riêng
    từng dòng như delete_units)."""
    require_perm(user, "warehouse.issue")
    ids = [row[0] for row in db.execute(select(FinishedGoodsUnit.unit_id).where(
        FinishedGoodsUnit.product_name == product_name, FinishedGoodsUnit.lot_code == lot_code,
        FinishedGoodsUnit.unit_type == unit_type, FinishedGoodsUnit.status == "stored")).all()]
    if not ids:
        raise DomainError("Không tìm thấy vỉ/keg nào khớp lô này để xóa.")
    bottles_reset = set()
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        edges = db.execute(select(GenealogyEdge).where(or_(
            and_(GenealogyEdge.to_type == "finished_goods_unit", GenealogyEdge.to_id.in_(chunk)),
            and_(GenealogyEdge.from_type == "finished_goods_unit", GenealogyEdge.from_id.in_(chunk))))).scalars().all()
        for e in edges:
            if e.to_type == "finished_goods_unit" and e.to_id in chunk and e.from_type == "bottle":
                bottle = db.get(BottleRecord, e.from_id)
                if bottle:
                    bottle.approved = False
                    bottle.stocked = False
                    bottles_reset.add(bottle.bottle_code)
            db.delete(e)
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        db.execute(delete(FinishedGoodsUnit).where(FinishedGoodsUnit.unit_id.in_(chunk)))
    record_audit(db, entity_type="finished_goods_unit", entity_id=ids[0], action="delete_by_lot", actor=user,
                 before={"product_name": product_name, "lot_code": lot_code, "unit_type": unit_type},
                 after={"deleted": len(ids), "bottles_reset": sorted(bottles_reset)})
    db.commit()
    return {"deleted": len(ids), "bottles_reset": sorted(bottles_reset)}


def _next_shipment_code(db: Session, year: int) -> str:
    """Số phiếu xuất kho theo đúng mẫu biên bản bàn giao hàng hóa giấy: {số:03d}/{năm}/BBBG-BHL.
    Dựa trên SỐ LỚN NHẤT đã dùng cho năm đó (không phải COUNT) — xóa 1 phiếu ở giữa vẫn phải
    tiếp tục tăng từ số cao nhất, không cấp lại trùng số đã xóa (cùng cách với LoadSlip.slip_code
    ở services/load_slip.py::_next_slip_code, nhưng đây là dãy số RIÊNG cho Shipment)."""
    suffix = f"/{year}/BBBG-BHL"
    existing = db.execute(select(Shipment.shipment_code)
                         .where(Shipment.shipment_code.like(f"%{suffix}"))).scalars().all()
    max_seq = 0
    for code in existing:
        try:
            max_seq = max(max_seq, int(code.split("/")[0]))
        except (ValueError, IndexError):
            pass
    return f"{max_seq + 1:03d}{suffix}"


def create_shipment(db: Session, ship_to_id: str, lines: list, user: User, header: dict | None = None) -> dict:
    """Xuất kho — mỗi dòng chọn (sản phẩm, lô, loại đơn vị, số lượng); hệ thống tự chọn
    đúng số vỉ/keg/lon cũ nhất (FIFO) trong lô đó, không cần liệt kê/chọn từng đơn vị (kho
    có thể có hàng trăm ngàn vỉ). Không đủ tồn cho 1 dòng thì báo lỗi rõ ràng (không xuất
    thiếu âm thầm). FIFO check: nếu unit được chọn trong khi còn unit CÙNG SẢN PHẨM cũ hơn
    (created_at sớm hơn) mà KHÔNG nằm trong danh sách đang xuất, coi là vi phạm FIFO."""
    require_perm(user, "warehouse.issue")
    if not ship_to_id:
        raise DomainError("Phải chọn nơi xuất đến.")
    ship_to = db.get(ShipToLocation, ship_to_id)
    if not ship_to:
        raise NotFoundError("Nơi xuất đến không tồn tại.")
    if not lines:
        raise DomainError("Phải chọn ít nhất 1 dòng sản phẩm để xuất.")

    units = []
    picked_so_far = set()
    for line in lines:
        product_name = line.get("product_name")
        unit_type = line.get("unit_type")
        lot_code = line.get("lot_code")
        qty = int(line.get("quantity") or 0)
        near_expiry_only = bool(line.get("near_expiry_only"))
        if not product_name or not unit_type:
            raise DomainError("Mỗi dòng phải có sản phẩm và loại đơn vị.")
        if qty <= 0:
            raise DomainError(f"Số lượng cần xuất cho {product_name} phải > 0.")
        stmt = select(FinishedGoodsUnit).where(
            FinishedGoodsUnit.product_name == product_name, FinishedGoodsUnit.unit_type == unit_type,
            FinishedGoodsUnit.status == "stored")
        if lot_code:
            stmt = stmt.where(FinishedGoodsUnit.lot_code == lot_code)
        if near_expiry_only:
            stmt = stmt.where(FinishedGoodsUnit.is_near_expiry == True)  # noqa: E712
        if picked_so_far:
            stmt = stmt.where(FinishedGoodsUnit.unit_id.notin_(picked_so_far))
        stmt = stmt.order_by(FinishedGoodsUnit.created_at).limit(qty)
        candidates = db.execute(stmt).scalars().all()
        if len(candidates) < qty:
            near_expiry_note = " (bia cận date)" if near_expiry_only else ""
            raise DomainError(f"{product_name} {lot_code or ''}{near_expiry_note}: chỉ còn {len(candidates)} "
                              f"đơn vị tồn kho, không đủ {qty} yêu cầu.")
        units.extend(candidates)
        picked_so_far.update(u.unit_id for u in candidates)

    picked_ids = picked_so_far
    fifo_ok = True
    for u in units:
        if not u.product_name:
            continue
        older = db.execute(select(FinishedGoodsUnit).where(
            FinishedGoodsUnit.product_name == u.product_name, FinishedGoodsUnit.status == "stored",
            FinishedGoodsUnit.unit_id != u.unit_id, FinishedGoodsUnit.created_at < u.created_at)).scalars().all()
        if any(o.unit_id not in picked_ids for o in older):
            fifo_ok = False
            break

    # Xuất tại kho = vị trí hiện đang lưu các vỉ/keg được chọn — tự suy ra từ location_id
    # của chính các đơn vị này (TRƯỚC khi bị xóa ở vòng lặp dưới), không cho nhập tay nữa vì
    # dễ sai/không khớp thực tế. Nhiều vị trí khác nhau thì liệt kê cách nhau dấu phẩy.
    loc_ids = {u.location_id for u in units if u.location_id}
    locs = db.execute(select(WmsLocation).where(WmsLocation.loc_id.in_(loc_ids))).scalars().all() if loc_ids else []
    from_location = ", ".join(sorted({l.code for l in locs})) or None

    header = header or {}
    shipment = Shipment(shipment_id=new_id(), shipment_code=_next_shipment_code(db, utcnow().year),
                        ship_to_id=ship_to_id, created_by=user.username, created_at=utcnow(),
                        fifo_ok=fifo_ok, note=header.get("note"),
                        recipient_name=header.get("recipient_name"), recipient_dept=header.get("recipient_dept"),
                        driver_name=header.get("driver_name"), vehicle_plate=header.get("vehicle_plate"),
                        from_location=from_location, delivery_place=header.get("delivery_place"),
                        shipment_type=header.get("shipment_type") or "normal")
    db.add(shipment)
    db.flush()

    out_lines = []
    near_expiry_groups: dict[tuple, int] = {}
    for u in units:
        u.status = "shipped"
        u.location_id = None
        u.shipped_at = utcnow()
        u.shipment_id = shipment.shipment_id
        u.ship_to_id = ship_to_id
        genealogy.add_edge(db, from_type="finished_goods_unit", from_id=u.unit_id, to_type="ship_to",
                           to_id=ship_to_id, relation="xuất kho", quantity=u.quantity, uom=u.unit_type)
        out_lines.append({"unit_code": u.unit_code, "product": u.product_name, "lot_code": u.lot_code})
        if u.is_near_expiry:
            key = (u.product_name, u.lot_code, u.unit_type)
            near_expiry_groups[key] = near_expiry_groups.get(key, 0) + 1

    # Xuất kho có bao gồm bia cận date — tự động ghi thêm dòng "xuất" vào lịch sử riêng
    # (tách khỏi lịch sử xuất kho thông thường) để tra cứu vòng đời bia cận date đầy đủ.
    for (product_name, lot_code, unit_type), count in near_expiry_groups.items():
        db.add(NearExpiryEntry(entry_id=new_id(), direction="out", product_name=product_name, lot_code=lot_code,
                               unit_type=unit_type, quantity=count, shipment_id=shipment.shipment_id,
                               created_by=user.username, created_at=utcnow()))

    record_audit(db, entity_type="shipment", entity_id=shipment.shipment_id, action="create", actor=user,
                 after={"shipment_code": shipment.shipment_code, "ship_to": ship_to.code,
                        "units": out_lines, "fifo_ok": fifo_ok})
    db.commit()
    return {"shipment_id": shipment.shipment_id, "shipment_code": shipment.shipment_code,
            "ship_to_code": ship_to.code, "fifo_ok": fifo_ok, "units": out_lines}


def list_shipments(db: Session) -> list:
    ships = db.execute(select(Shipment).order_by(Shipment.created_at.desc())).scalars().all()
    ship_to_by = {s.ship_to_id: s for s in db.execute(select(ShipToLocation)).scalars().all()}
    out = []
    for s in ships:
        units = db.execute(select(FinishedGoodsUnit).where(
            FinishedGoodsUnit.shipment_id == s.shipment_id)).scalars().all()
        # Gom nhóm theo (product, lot_code, unit_type) để in phiếu — thay cho bảng dòng riêng.
        grouped: dict[tuple, dict] = {}
        for u in units:
            key = (u.product_name, u.lot_code, u.unit_type)
            g = grouped.setdefault(key, {"product": u.product_name, "lot_code": u.lot_code,
                                         "unit_type": u.unit_type, "count": 0, "quantity": 0.0})
            g["count"] += 1
            g["quantity"] += u.quantity
        ship_to = ship_to_by.get(s.ship_to_id)
        out.append({"shipment_id": s.shipment_id, "shipment_code": s.shipment_code,
                    "ship_to_code": ship_to.code if ship_to else None,
                    "ship_to_name": ship_to.name if ship_to else None,
                    "ship_to_address": ship_to.address if ship_to else None,
                    "created_by": s.created_by, "created_at": s.created_at, "fifo_ok": s.fifo_ok,
                    "shipment_type": s.shipment_type,
                    "note": s.note, "recipient_name": s.recipient_name, "recipient_dept": s.recipient_dept,
                    "driver_name": s.driver_name, "vehicle_plate": s.vehicle_plate,
                    "from_location": s.from_location, "delivery_place": s.delivery_place,
                    "unit_count": len(units), "lines": list(grouped.values())})
    return out


def undo_shipment(db: Session, shipment_id: str, user: User) -> dict:
    """Hoàn tác 1 phiếu xuất kho — trả các vỉ/keg/lon đã xuất về "stored" (gỡ khỏi phiếu/nơi
    xuất đến). Không giữ lại location_id gốc (đã bị xóa lúc xuất) — hàng về kho coi như chưa
    xếp vị trí, xếp lại thủ công (Điều chuyển) nếu cần. Không xóa phiếu (giữ làm lịch sử) —
    idempotent tự nhiên: sau khi hoàn tác, truy vấn theo shipment_id không còn ra unit nào
    nên gọi lại sẽ báo lỗi thay vì hoàn tác lần 2."""
    require_perm(user, "warehouse.issue")
    shipment = db.get(Shipment, shipment_id)
    if not shipment:
        raise NotFoundError("Phiếu xuất kho không tồn tại.")
    units = db.execute(select(FinishedGoodsUnit).where(
        FinishedGoodsUnit.shipment_id == shipment_id)).scalars().all()
    if not units:
        raise DomainError("Phiếu này không còn đơn vị nào để hoàn tác (có thể đã hoàn tác trước đó).")
    unit_ids = [u.unit_id for u in units]
    for u in units:
        u.status = "stored"
        u.shipped_at = None
        u.shipment_id = None
        u.ship_to_id = None
    edges = db.execute(select(GenealogyEdge).where(
        GenealogyEdge.from_type == "finished_goods_unit", GenealogyEdge.from_id.in_(unit_ids),
        GenealogyEdge.to_type == "ship_to", GenealogyEdge.to_id == shipment.ship_to_id)).scalars().all()
    for e in edges:
        db.delete(e)
    record_audit(db, entity_type="shipment", entity_id=shipment_id, action="undo", actor=user,
                 before={"unit_count": len(units)}, after={"restored": len(units)})
    db.commit()
    return {"shipment_id": shipment_id, "restored": len(units)}


def delete_unit(db: Session, unit_id: str, user: User) -> None:
    """Xóa 1 vỉ/keg — chỉ khi CHƯA xuất kho (status != "shipped"), vì hàng đã xuất là đã ra
    khỏi nhà máy trong thực tế, xóa bản ghi sẽ làm sai lệch hồ sơ/không khớp thực tế. Xóa
    xong phải "mở khóa" lại bản ghi Chiết nguồn (approved/stocked -> False, xem
    routers/brewing.py::approve_bottle) để người dùng có thể sửa/xóa lại chiết nếu cần —
    đúng quy tắc "muốn xóa bước trước thì bước sau phải được xóa trước"."""
    require_perm(user, "warehouse.issue")
    u = db.get(FinishedGoodsUnit, unit_id)
    if not u:
        raise NotFoundError("Vỉ/keg không tồn tại.")
    if u.status == "shipped":
        raise DomainError("Đã xuất kho — không thể xóa.")
    if u.status == "decomposed":
        raise DomainError("Đã phân rã thành lon — không thể xóa (còn lon con phụ thuộc).")
    for e in db.execute(select(GenealogyEdge).where(or_(
            and_(GenealogyEdge.to_type == "finished_goods_unit", GenealogyEdge.to_id == unit_id),
            and_(GenealogyEdge.from_type == "finished_goods_unit", GenealogyEdge.from_id == unit_id)))).scalars().all():
        if e.to_type == "finished_goods_unit" and e.to_id == unit_id and e.from_type == "bottle":
            bottle = db.get(BottleRecord, e.from_id)
            if bottle:
                bottle.approved = False
                bottle.stocked = False
        db.delete(e)
    record_audit(db, entity_type="finished_goods_unit", entity_id=unit_id, action="delete", actor=user,
                 before={"unit_code": u.unit_code, "status": u.status})
    db.delete(u)
    db.commit()


def delete_units(db: Session, unit_ids: list[str], user: User) -> dict:
    """Xóa CẢ LÔ vỉ/keg cùng lúc (VD xóa nguyên lần nhập kho tự động sau khi duyệt chiết) —
    mirror delete_unit nhưng gộp nhiều dòng, validate HẾT trước khi xóa dòng nào (không xóa
    dở dang nếu 1 dòng ở giữa bị chặn). Cùng logic "mở khóa" lại Chiết nguồn — xem
    delete_unit."""
    require_perm(user, "warehouse.issue")
    if not unit_ids:
        raise DomainError("Chưa chọn vỉ/keg nào để xóa.")
    units = []
    for unit_id in unit_ids:
        u = db.get(FinishedGoodsUnit, unit_id)
        if not u:
            raise NotFoundError("Vỉ/keg không tồn tại.")
        if u.status == "shipped":
            raise DomainError(f"{u.unit_code} đã xuất kho — không thể xóa.")
        if u.status == "decomposed":
            raise DomainError(f"{u.unit_code} đã phân rã thành lon — không thể xóa (còn lon con phụ thuộc).")
        units.append(u)
    bottles_reset = set()
    for u in units:
        for e in db.execute(select(GenealogyEdge).where(or_(
                and_(GenealogyEdge.to_type == "finished_goods_unit", GenealogyEdge.to_id == u.unit_id),
                and_(GenealogyEdge.from_type == "finished_goods_unit", GenealogyEdge.from_id == u.unit_id)))).scalars().all():
            if e.to_type == "finished_goods_unit" and e.to_id == u.unit_id and e.from_type == "bottle":
                bottle = db.get(BottleRecord, e.from_id)
                if bottle:
                    bottle.approved = False
                    bottle.stocked = False
                    bottles_reset.add(bottle.bottle_code)
            db.delete(e)
        record_audit(db, entity_type="finished_goods_unit", entity_id=u.unit_id, action="delete", actor=user,
                     before={"unit_code": u.unit_code, "status": u.status})
        db.delete(u)
    db.commit()
    return {"deleted": len(units), "bottles_reset": sorted(bottles_reset)}


def resolve(db: Session, code: str) -> dict:
    """Phân giải barcode (cho kiosk/đầu đọc) — mã vạch/QR in theo LÔ (không in riêng từng
    vỉ), nên trước tiên tra theo lot_code (tổng hợp số lượng theo trạng thái/loại); chỉ
    còn tra theo unit_code (mã nội bộ từng dòng) để tương thích các tem cũ đã in trước đây."""
    lot_units = db.execute(select(FinishedGoodsUnit).where(FinishedGoodsUnit.lot_code == code)).scalars().all()
    if lot_units:
        by_status = {}
        by_type = {}
        for u in lot_units:
            by_status[u.status] = by_status.get(u.status, 0) + 1
            by_type[u.unit_type] = by_type.get(u.unit_type, 0) + 1
        return {"type": "lot", "lot_code": code, "product": lot_units[0].product_name,
                "unit_count": len(lot_units), "by_status": by_status, "by_type": by_type}
    u = db.execute(select(FinishedGoodsUnit).where(FinishedGoodsUnit.unit_code == code)).scalar_one_or_none()
    if u:
        loc = db.get(WmsLocation, u.location_id) if u.location_id else None
        return {"type": "finished_goods_unit", "unit_code": u.unit_code, "unit_type": u.unit_type,
                "product": u.product_name, "lot_code": u.lot_code, "quantity": u.quantity,
                "status": u.status, "location": loc.code if loc else None}
    return {"type": "unknown", "code": code}


def relocate_batch(db: Session, product_name: str, lot_code: str, unit_type: str,
                   from_loc_id: str | None, to_loc_id: str, count: int, user: User) -> dict:
    """Gán/chuyển vị trí cho N đơn vị (cũ nhất trước) của 1 sản phẩm/lô/loại — dùng cho
    "Cất" hàng loạt (from_loc_id=None: đơn vị chưa có vị trí) hoặc điều chuyển hàng loạt
    theo số lượng thay vì phải chọn từng đơn vị (phù hợp kho có hàng trăm ngàn vỉ)."""
    require_perm(user, "warehouse.issue")
    if count <= 0:
        raise DomainError("Số lượng phải > 0.")
    to_loc = db.get(WmsLocation, to_loc_id)
    if not to_loc:
        raise NotFoundError("Vị trí đích không tồn tại.")

    where_loc = FinishedGoodsUnit.location_id.is_(None) if not from_loc_id else FinishedGoodsUnit.location_id == from_loc_id
    candidates = db.execute(select(FinishedGoodsUnit).where(
        FinishedGoodsUnit.product_name == product_name, FinishedGoodsUnit.lot_code == lot_code,
        FinishedGoodsUnit.unit_type == unit_type, FinishedGoodsUnit.status == "stored", where_loc
    ).order_by(FinishedGoodsUnit.created_at).limit(count)).scalars().all()
    if not candidates:
        raise DomainError("Không còn đơn vị nào phù hợp để xử lý.")

    moving_in = [u for u in candidates if u.location_id != to_loc_id]
    if moving_in:
        used_at_dest = db.execute(select(func.count(FinishedGoodsUnit.unit_id)).where(
            FinishedGoodsUnit.location_id == to_loc_id, FinishedGoodsUnit.status == "stored")).scalar() or 0
        if used_at_dest + len(moving_in) > to_loc.capacity:
            raise DomainError(f"Vị trí {to_loc.code} không đủ sức chứa (sức chứa {to_loc.capacity}, "
                              f"hiện có {used_at_dest}, cần thêm {len(moving_in)}).")

    from_loc = db.get(WmsLocation, from_loc_id) if from_loc_id else None
    for u in candidates:
        u.location_id = to_loc_id
    record_audit(db, entity_type="finished_goods_unit", entity_id=new_id(), action="relocate_batch", actor=user,
                 before={"product_name": product_name, "lot_code": lot_code, "unit_type": unit_type, "requested": count,
                         "from_location": from_loc.code if from_loc else None},
                 after={"moved": len(candidates), "to_location": to_loc.code})
    db.commit()
    return {"moved": len(candidates), "to_location": to_loc.code, "requested": count}
