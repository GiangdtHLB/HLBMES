"""Năng lượng hàng ngày/tháng + danh mục."""

from datetime import date, datetime, timedelta

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


# ---- Báo cáo theo khoảng ngày (tổng/chuỗi/phân theo khu) ----
@router.get("/report")
def report(date_from: date = None, date_to: date = None, group_by: str = "day",
          area_id: str = None, db: Session = Depends(get_db)):
    from ..services import derived
    today = date.today()
    d_from = date_from or (today - timedelta(days=30))
    d_to = date_to or today
    return derived.energy_report(db, d_from, d_to, group_by, area_id)


# ---- Báo cáo điện (AED) thật từ CSDL SCADA ngoài (SqlConnection.purpose theo nhà máy —
# xem services/energy_external.py::SITE_PURPOSE) ----
@router.get("/external-sites")
def external_sites():
    """Kèm theo `purpose` (token gán ở SqlConnection.purpose — Tích hợp › Kết nối CSDL) để
    frontend dựng đúng checkbox "Dùng cho" theo từng nhà máy, tránh gõ tay/nhầm giữa các site."""
    from ..services import energy_external
    return [{"site": k, "label": v, "purpose": energy_external.SITE_PURPOSE[k]}
            for k, v in energy_external.SITE_LABELS.items()]


@router.get("/external-bounds")
def external_bounds(site: str = "hl", db: Session = Depends(get_db)):
    from ..services import energy_external
    return energy_external.data_bounds(db, site)


@router.get("/external-report")
def external_report(date_from: datetime = None, date_to: datetime = None, group_by: str = "day",
                    site: str = "hl", db: Session = Depends(get_db)):
    from ..services import energy_external
    if not date_from or not date_to:
        bounds = energy_external.data_bounds(db, site)
        date_to = date_to or (datetime.fromisoformat(bounds["max_date"]) + timedelta(hours=23, minutes=59, seconds=59))
        date_from = date_from or (date_to - timedelta(days=30))
    return energy_external.electricity_report(db, date_from, date_to, group_by, site)


# ---- Điện tiêu thụ theo ca (Ca1/Ca2/Ca3) ----
@router.get("/external-ca-report")
def external_ca_report(date_from: datetime = None, date_to: datetime = None,
                       site: str = "hl", db: Session = Depends(get_db)):
    from ..services import energy_external
    if not date_from or not date_to:
        # Mặc định: ngày hôm qua (hôm nay chưa qua hết ca 3) — Ca 1 (06h) hôm qua tới Ca 3 (06h hôm nay).
        ref_day = datetime.combine(date.today() - timedelta(days=1), datetime.min.time())
        date_from = date_from or ref_day.replace(hour=6)
        date_to = date_to or (date_from + timedelta(hours=24))
    return energy_external.electricity_ca_report(db, date_from, date_to, site)
