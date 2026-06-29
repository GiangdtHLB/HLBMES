"""Năng lượng hàng ngày/tháng + danh mục."""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..common import new_id
from ..database import get_db
from ..models.energy import EnergyArea, EnergyGroup, EnergyReading
from ..schemas import (
    EnergyAreaIn,
    EnergyGroupIn,
    EnergyReadingIn,
)
from ..security import User, get_current_user, require_perm

router = APIRouter(prefix="/api/energy", tags=["energy"],
                   dependencies=[Depends(get_current_user)])


# ---- Danh mục ----
@router.get("/groups")
def list_groups(db: Session = Depends(get_db)):
    return db.execute(select(EnergyGroup).order_by(EnergyGroup.code)).scalars().all()


@router.post("/groups", status_code=201)
def create_group(payload: EnergyGroupIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "energy.update")
    g = EnergyGroup(group_id=new_id(), **payload.model_dump())
    db.add(g)
    db.commit()
    db.refresh(g)
    return g


@router.get("/areas")
def list_areas(db: Session = Depends(get_db)):
    return db.execute(select(EnergyArea).order_by(EnergyArea.code)).scalars().all()


@router.post("/areas", status_code=201)
def create_area(payload: EnergyAreaIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "energy.update")
    a = EnergyArea(area_id=new_id(), **payload.model_dump())
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


# ---- Cập nhật reading ngày (upsert) ----
@router.post("/readings", status_code=201)
def upsert_reading(payload: EnergyReadingIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    require_perm(user, "energy.update")
    d = payload.day or date.today()
    existing = db.execute(
        select(EnergyReading).where(EnergyReading.day == d, EnergyReading.group_id == payload.group_id,
                                    EnergyReading.area_id == payload.area_id)
    ).scalar_one_or_none()
    if existing:
        existing.value = payload.value
        existing.note = payload.note
        r = existing
    else:
        r = EnergyReading(reading_id=new_id(), day=d, group_id=payload.group_id,
                          area_id=payload.area_id, value=payload.value, note=payload.note)
        db.add(r)
    db.commit()
    db.refresh(r)
    return r


# ---- Biểu đồ/đọc theo ngày ----
@router.get("/daily")
def daily(group_id: str = None, days: int = 30, db: Session = Depends(get_db)):
    stmt = select(EnergyReading).order_by(EnergyReading.day)
    if group_id:
        stmt = stmt.where(EnergyReading.group_id == group_id)
    rows = db.execute(stmt).scalars().all()
    # gộp theo ngày (cộng các khu)
    agg = {}
    for r in rows:
        key = (r.day.isoformat(), r.group_id)
        agg[key] = agg.get(key, 0.0) + r.value
    out = [{"day": k[0], "group_id": k[1], "value": round(v, 3)} for k, v in agg.items()]
    return sorted(out, key=lambda x: x["day"])


# ---- Tổng hợp tháng ----
@router.get("/monthly")
def monthly(year: int = None, db: Session = Depends(get_db)):
    from ..services import derived
    return derived.energy_monthly(db, year)
