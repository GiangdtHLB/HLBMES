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
             "capacity": l.capacity, "used": counts.get(l.loc_id, 0)} for l in locs]


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
                    "total_units": sum(c.units for c in cases), "status": p.status,
                    "location": loc.code if loc else None,
                    "cases": [{"case_code": c.case_code, "units": c.units} for c in cases]})
    return out


def build_pallet(db: Session, payload: dict, user: User) -> Pallet:
    require_perm(user, "warehouse.receive")
    n = int(payload.get("case_count", 0) or 0)
    upc = int(payload.get("units_per_case", 24) or 24)
    if n <= 0:
        raise DomainError("Số case phải > 0.")
    stamp = f"{utcnow():%y%m%d}-{new_id()[:4].upper()}"
    pallet = Pallet(pallet_id=new_id(), pallet_code=f"PLT-{stamp}",
                    product=payload.get("product"), lot_code=payload.get("lot_code"),
                    case_count=n, units_per_case=upc, status="building",
                    created_by=user.username, created_at=utcnow())
    db.add(pallet)
    db.flush()
    for i in range(1, n + 1):
        db.add(Case(case_id=new_id(), case_code=f"CS-{stamp}-{i:03d}", pallet_id=pallet.pallet_id,
                    product=payload.get("product"), units=upc, lot_code=payload.get("lot_code")))
    record_audit(db, entity_type="pallet", entity_id=pallet.pallet_id, action="build", actor=user,
                 after={"pallet_code": pallet.pallet_code, "cases": n, "units": n * upc})
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


def resolve(db: Session, code: str) -> dict:
    """Phân giải barcode pallet/case (cho kiosk/đầu đọc)."""
    p = db.execute(select(Pallet).where(Pallet.pallet_code == code)).scalar_one_or_none()
    if p:
        loc = db.get(WmsLocation, p.location_id) if p.location_id else None
        return {"type": "pallet", "pallet_code": p.pallet_code, "product": p.product,
                "lot_code": p.lot_code, "case_count": p.case_count, "status": p.status,
                "location": loc.code if loc else None}
    c = db.execute(select(Case).where(Case.case_code == code)).scalar_one_or_none()
    if c:
        pal = db.get(Pallet, c.pallet_id)
        return {"type": "case", "case_code": c.case_code, "product": c.product,
                "units": c.units, "lot_code": c.lot_code,
                "pallet_code": pal.pallet_code if pal else None}
    return {"type": "unknown", "code": code}
