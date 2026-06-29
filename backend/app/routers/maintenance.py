"""Bảo trì thiết bị & Kiểm định hiệu chuẩn."""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import new_id, utcnow
from ..database import get_db
from ..errors import NotFoundError
from ..models.maintenance import (
    Calibration,
    Equipment,
    Incident,
    MaintenancePlan,
    SparePart,
)
from ..schemas import (
    CalibrationIn,
    EquipmentIn,
    IncidentIn,
    MaintenancePlanIn,
    SparePartIn,
)
from ..security import User, get_current_user, require_perm

router = APIRouter(prefix="/api/maint", tags=["maintenance"],
                   dependencies=[Depends(get_current_user)])


# ---- Danh mục thiết bị / phụ tùng ----
@router.get("/equipment")
def list_equipment(db: Session = Depends(get_db)):
    return db.execute(select(Equipment).order_by(Equipment.code)).scalars().all()


@router.post("/equipment", status_code=201)
def create_equipment(payload: EquipmentIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "maintenance.manage")
    e = Equipment(equipment_id=new_id(), **payload.model_dump())
    db.add(e); db.commit(); db.refresh(e)
    return e


@router.get("/parts")
def list_parts(db: Session = Depends(get_db)):
    parts = db.execute(select(SparePart).order_by(SparePart.code)).scalars().all()
    return [{"part_id": p.part_id, "code": p.code, "name": p.name, "uom": p.uom,
             "stock": p.stock, "stock_min": p.stock_min, "below_min": p.stock < p.stock_min}
            for p in parts]


@router.post("/parts", status_code=201)
def create_part(payload: SparePartIn, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    require_perm(user, "maintenance.manage")
    p = SparePart(part_id=new_id(), **payload.model_dump())
    db.add(p); db.commit(); db.refresh(p)
    return p


# ---- Sự cố (Incident) ----
@router.get("/incidents")
def list_incidents(status: str = None, db: Session = Depends(get_db)):
    stmt = select(Incident).order_by(Incident.reported_at.desc())
    if status:
        stmt = stmt.where(Incident.status == status)
    return db.execute(stmt).scalars().all()


@router.post("/incidents", status_code=201)
def add_incident(payload: IncidentIn, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    require_perm(user, "maintenance.manage")
    inc = Incident(incident_id=new_id(), incident_code=f"SC-{utcnow():%Y%m%d}-{new_id()[:5].upper()}",
                   reported_by=user.username, **payload.model_dump())
    db.add(inc)
    if inc.equipment_id:
        eq = db.get(Equipment, inc.equipment_id)
        if eq and inc.severity in ("major", "critical"):
            eq.status = "broken"
    record_audit(db, entity_type="incident", entity_id=inc.incident_id, action="open",
                 actor=user, after={"code": inc.incident_code, "title": inc.title})
    db.commit(); db.refresh(inc)
    return inc


@router.post("/incidents/{incident_id}/resolve")
def resolve_incident(incident_id: str, resolution: str = "", downtime_min: float = 0,
                     db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "maintenance.manage")
    inc = db.get(Incident, incident_id)
    if not inc:
        raise NotFoundError("Sự cố không tồn tại.")
    inc.status = "resolved"
    inc.resolution = resolution
    inc.downtime_min = downtime_min
    inc.resolved_at = utcnow()
    if inc.equipment_id:
        eq = db.get(Equipment, inc.equipment_id)
        if eq:
            eq.status = "running"
    record_audit(db, entity_type="incident", entity_id=inc.incident_id, action="resolve",
                 actor=user, after={"downtime_min": downtime_min})
    db.commit(); db.refresh(inc)
    return inc


# ---- Kế hoạch bảo trì ----
@router.get("/plans")
def list_plans(plan_type: str = None, db: Session = Depends(get_db)):
    plans = db.execute(select(MaintenancePlan).order_by(MaintenancePlan.scheduled_date)).scalars().all()
    today = date.today()
    out = []
    for p in plans:
        if plan_type and p.plan_type != plan_type:
            continue
        status = p.status
        if status == "planned" and p.scheduled_date < today:
            status = "overdue"
        eq = db.get(Equipment, p.equipment_id)
        out.append({"plan_id": p.plan_id, "equipment": eq.code if eq else p.equipment_id,
                    "plan_type": p.plan_type, "scheduled_date": p.scheduled_date,
                    "status": status, "note": p.note})
    return out


@router.post("/plans", status_code=201)
def create_plan(payload: MaintenancePlanIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "maintenance.manage")
    p = MaintenancePlan(plan_id=new_id(), **payload.model_dump())
    db.add(p); db.commit(); db.refresh(p)
    return p


@router.post("/plans/{plan_id}/done")
def complete_plan(plan_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "maintenance.manage")
    p = db.get(MaintenancePlan, plan_id)
    if not p:
        raise NotFoundError("Kế hoạch không tồn tại.")
    p.status = "done"; p.done_at = utcnow()
    db.commit(); db.refresh(p)
    return p


# ---- Kiểm định / hiệu chuẩn ----
@router.get("/calibrations")
def list_calibrations(calib_type: str = None, db: Session = Depends(get_db)):
    from ..services import derived
    return derived.calibrations(db, calib_type)


@router.post("/calibrations", status_code=201)
def create_calibration(payload: CalibrationIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "calibration.manage")
    c = Calibration(calib_id=new_id(), **payload.model_dump())
    db.add(c); db.commit(); db.refresh(c)
    return c
