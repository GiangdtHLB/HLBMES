"""WMS thành phẩm: build pallet (gồm case), putaway/move/ship theo vị trí, tồn theo
vị trí, phân giải barcode pallet/case (cho đầu đọc cầm tay / kiosk)."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import new_id, utcnow
from ..errors import DomainError, NotFoundError
from ..models.wms import Case, Pallet, WmsLocation
from ..security import User, require_perm


def list_locations(db: Session) -> list:
    locs = db.execute(select(WmsLocation).order_by(WmsLocation.code)).scalars().all()
    counts = dict(db.execute(
        select(Pallet.location_id, func.count(Pallet.pallet_id))
        .where(Pallet.status == "stored").group_by(Pallet.location_id)).all())
    return [{"loc_id": l.loc_id, "code": l.code, "name": l.name, "zone": l.zone, "kind": l.kind,
             "capacity": l.capacity, "active": l.active, "used": counts.get(l.loc_id, 0)} for l in locs]


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
    used = db.execute(select(func.count(Pallet.pallet_id)).where(
        Pallet.location_id == loc_id, Pallet.status == "stored")).scalar() or 0
    if used:
        raise DomainError(f"Vị trí {loc.code} đang chứa {used} pallet — không thể xóa.")
    db.delete(loc)
    db.commit()


def summary(db: Session) -> dict:
    """Tổng hợp toàn kho: số vị trí + sức chứa, tổng pallet (theo trạng thái), case/units."""
    locs = db.execute(select(WmsLocation)).scalars().all()
    capacity = sum(l.capacity for l in locs)
    pallets = db.execute(select(Pallet)).scalars().all()
    stored = [p for p in pallets if p.status == "stored"]
    cases = db.execute(select(func.count(Case.case_id))).scalar() or 0
    units = db.execute(select(func.coalesce(func.sum(Case.units), 0))).scalar() or 0
    by_status = {}
    for p in pallets:
        by_status[p.status] = by_status.get(p.status, 0) + 1
    return {"locations": len(locs), "capacity_pallets": capacity,
            "pallets_total": len(pallets), "pallets_stored": len(stored),
            "fill_pct": round(len(stored) / capacity * 100, 1) if capacity else 0.0,
            "by_status": by_status, "cases": cases, "units": int(units)}


def list_pallets(db: Session, status: str = None) -> list:
    stmt = select(Pallet).order_by(Pallet.created_at.desc())
    if status:
        stmt = stmt.where(Pallet.status == status)
    out = []
    loc_by = {l.loc_id: l for l in db.execute(select(WmsLocation)).scalars().all()}
    for p in db.execute(stmt).scalars().all():
        loc = loc_by.get(p.location_id)
        cases = db.execute(select(Case).where(Case.pallet_id == p.pallet_id)).scalars().all()
        out.append({"pallet_id": p.pallet_id, "pallet_code": p.pallet_code, "product": p.product,
                    "lot_code": p.lot_code, "case_count": p.case_count, "units_per_case": p.units_per_case,
                    "total_units": sum(c.units for c in cases), "status": p.status, "source": p.source,
                    "location": loc.code if loc else None,
                    "cases": [{"case_code": c.case_code, "units": c.units} for c in cases]})
    return out


def list_lots(db: Session) -> list:
    """Tổng hợp theo Lô TP (lot_code) — nhiều pallet (mỗi pallet 1 mã SSCC riêng theo chuẩn GS1)
    có thể cùng chung 1 lot_code (1 lô sản xuất). Dùng để chọn CẢ LÔ xuất 1 lần thay vì từng
    pallet (yêu cầu người dùng 2026-09-20: "có thể cho chọn cả lô để xuất... báo lô đó có tổng
    bao nhiêu pallet, tổng bao nhiêu vỉ"). Chỉ liệt kê lô CÒN pallet chưa xuất — lô đã xuất hết
    không còn gì để chọn xuất tiếp."""
    pallets = db.execute(select(Pallet).where(
        Pallet.lot_code.isnot(None), Pallet.status != "shipped")).scalars().all()
    by_lot: dict[str, list[Pallet]] = {}
    for p in pallets:
        by_lot.setdefault(p.lot_code, []).append(p)
    cases_by_pallet: dict[str, float] = dict(db.execute(
        select(Case.pallet_id, func.coalesce(func.sum(Case.units), 0)).group_by(Case.pallet_id)).all())
    out = []
    for lot_code, plist in by_lot.items():
        total_units = sum(cases_by_pallet.get(p.pallet_id, 0) for p in plist)
        by_status: dict[str, int] = {}
        for p in plist:
            by_status[p.status] = by_status.get(p.status, 0) + 1
        out.append({"lot_code": lot_code, "product": plist[0].product,
                    "pallet_count": len(plist), "total_units": int(total_units), "by_status": by_status})
    return sorted(out, key=lambda x: x["lot_code"])


def build_pallet(db: Session, payload: dict, user: User) -> Pallet:
    require_perm(user, "warehouse.receive")
    return _build_pallet(db, payload, user, source="manual")


def _build_pallet(db: Session, payload: dict, user: User, source: str = "manual") -> Pallet:
    """Lõi tạo pallet, KHÔNG check quyền — dùng chung cho build_pallet() (thao tác tay, tự
    check warehouse.receive) và release_pack_lot_to_wms() (services/batch_pipeline.py, đã tự
    check production.release_to_wms — không bắt người duyệt nhập kho từ Mẻ sản xuất phải có
    thêm quyền warehouse.receive).

    `source` chỉ để đánh dấu hiển thị/kiểm toán — "manual" (thủ kho tự đóng pallot, KHÔNG qua
    duyệt KCS/Giám đốc SX, không link genealogy về lô chiết) hay "production" (đã qua đủ 2 bước
    duyệt qua release_pack_lot_to_wms). KHÔNG dùng để chặn quyền — người dùng đã xác nhận giữ
    nguyên khả năng đóng pallet thủ công (audit rủi ro 2026-09-15), chỉ cần phân biệt rõ khi
    xem danh sách/kiểm toán."""
    n = int(payload.get("case_count", 0) or 0)
    upc = int(payload.get("units_per_case", 24) or 24)
    if n <= 0:
        raise DomainError("Số case phải > 0.")
    stamp = f"{utcnow():%y%m%d}-{new_id()[:4].upper()}"
    pallet = Pallet(pallet_id=new_id(), pallet_code=f"PLT-{stamp}",
                    product=payload.get("product"), lot_code=payload.get("lot_code"),
                    case_count=n, units_per_case=upc, status="building", source=source,
                    created_by=user.username, created_at=utcnow())
    db.add(pallet)
    db.flush()
    for i in range(1, n + 1):
        db.add(Case(case_id=new_id(), case_code=f"CS-{stamp}-{i:03d}", pallet_id=pallet.pallet_id,
                    product=payload.get("product"), units=upc, lot_code=payload.get("lot_code")))
    record_audit(db, entity_type="pallet", entity_id=pallet.pallet_id, action="build", actor=user,
                 after={"pallet_code": pallet.pallet_code, "cases": n, "units": n * upc, "source": source})
    db.commit()
    db.refresh(pallet)
    return pallet


def _capacity_ok(db: Session, loc: WmsLocation, exclude_pallet: str = None) -> bool:
    used = db.execute(select(func.count(Pallet.pallet_id)).where(
        Pallet.location_id == loc.loc_id, Pallet.status == "stored",
        Pallet.pallet_id != (exclude_pallet or ""))).scalar() or 0
    return used < loc.capacity


def putaway(db: Session, pallet_id: str, loc_id: str, user: User) -> dict:
    require_perm(user, "warehouse.issue")
    p = db.get(Pallet, pallet_id)
    if not p:
        raise NotFoundError("Pallet không tồn tại.")
    if p.status == "shipped":
        raise DomainError("Pallet đã xuất — không thể cất.")
    loc = db.get(WmsLocation, loc_id)
    if not loc:
        raise NotFoundError("Vị trí không tồn tại.")
    if not _capacity_ok(db, loc, exclude_pallet=pallet_id):
        raise DomainError(f"Vị trí {loc.code} đã đầy (sức chứa {loc.capacity} pallet).")
    before = {"location": p.location_id, "status": p.status}
    p.location_id = loc.loc_id
    p.status = "stored"
    record_audit(db, entity_type="pallet", entity_id=pallet_id, action="putaway", actor=user,
                 before=before, after={"location": loc.code})
    db.commit()
    return {"pallet_code": p.pallet_code, "location": loc.code, "status": p.status}


def ship(db: Session, pallet_id: str, user: User) -> dict:
    require_perm(user, "warehouse.issue")
    p = db.get(Pallet, pallet_id)
    if not p:
        raise NotFoundError("Pallet không tồn tại.")
    p.status = "shipped"
    p.location_id = None
    record_audit(db, entity_type="pallet", entity_id=pallet_id, action="ship", actor=user,
                 after={"pallet_code": p.pallet_code})
    db.commit()
    return {"pallet_code": p.pallet_code, "status": "shipped"}


def ship_lot(db: Session, lot_code: str, user: User) -> dict:
    """Xuất TOÀN BỘ pallet còn lại của 1 Lô TP (lot_code) trong 1 lần, thay vì phải xuất từng
    pallet lẻ (yêu cầu người dùng 2026-09-20 — nhiều pallet cùng lô là bình thường theo chuẩn
    GS1: SSCC riêng từng pallet, Batch/Lot Number chung cả lô). Lặp gọi ship() cho từng pallet —
    giữ nguyên đúng 1 bản ghi audit/pallet như xuất tay từng cái."""
    require_perm(user, "warehouse.issue")
    pallets = db.execute(select(Pallet).where(
        Pallet.lot_code == lot_code, Pallet.status != "shipped")).scalars().all()
    if not pallets:
        raise NotFoundError(f"Không có pallet nào của lô '{lot_code}' để xuất (có thể đã xuất hết).")
    cases_by_pallet: dict[str, float] = dict(db.execute(
        select(Case.pallet_id, func.coalesce(func.sum(Case.units), 0))
        .where(Case.pallet_id.in_([p.pallet_id for p in pallets])).group_by(Case.pallet_id)).all())
    total_units = int(sum(cases_by_pallet.get(p.pallet_id, 0) for p in pallets))
    results = [ship(db, p.pallet_id, user) for p in pallets]
    return {"lot_code": lot_code, "pallet_count": len(results),
            "pallet_codes": [r["pallet_code"] for r in results], "total_units": total_units}


def resolve(db: Session, code: str) -> dict:
    """Phân giải barcode pallet/case (cho kiosk/đầu đọc)."""
    p = db.execute(select(Pallet).where(Pallet.pallet_code == code)).scalar_one_or_none()
    if p:
        loc = db.get(WmsLocation, p.location_id) if p.location_id else None
        return {"type": "pallet", "pallet_code": p.pallet_code, "product": p.product,
                "lot_code": p.lot_code, "case_count": p.case_count, "status": p.status,
                "source": p.source, "location": loc.code if loc else None}
    c = db.execute(select(Case).where(Case.case_code == code)).scalar_one_or_none()
    if c:
        pal = db.get(Pallet, c.pallet_id)
        return {"type": "case", "case_code": c.case_code, "product": c.product,
                "units": c.units, "lot_code": c.lot_code,
                "pallet_code": pal.pallet_code if pal else None}
    return {"type": "unknown", "code": code}
