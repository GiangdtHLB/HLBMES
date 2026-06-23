"""Truy vấn dẫn xuất dùng chung (cảnh báo brewing/QC, kiểm định, năng lượng).

Tách khỏi router để cả router lẫn ai_tools cùng gọi service — tránh service
import ngược lên router (vòng phụ thuộc, khó test). Hàm thuần (db, **params)->dict/list.
"""

from datetime import date

from sqlalchemy import extract, select
from sqlalchemy.orm import Session

from ..common import utcnow
from ..models.batches import BatchExecution
from ..models.brewing import BottleRecord, BrewRecord, FilterRecord
from ..models.energy import EnergyGroup, EnergyReading
from ..models.maintenance import Calibration, Equipment
from ..models.metrics import ProcessReading
from ..models.quality import QualityResult


def brewing_alerts(db: Session, month: int = None, year: int = None) -> dict:
    now = utcnow()
    month = month or now.month
    year = year or now.year
    out = []
    brews = db.execute(select(BrewRecord).where(
        extract("month", BrewRecord.brew_date) == month,
        extract("year", BrewRecord.brew_date) == year)).scalars().all()
    for b in brews:
        if b.original_extract is None:
            out.append(f"Mã thông tin nấu = {b.brew_code} Tên chỉ tiêu: Độ hòa tan nguyên thủy không được để trống")
        if b.plato is None:
            out.append(f"Mã thông tin nấu = {b.brew_code} Tên chỉ tiêu: Plato không được để trống")
    bottles = db.execute(select(BottleRecord).where(
        extract("month", BottleRecord.bottle_date) == month,
        extract("year", BottleRecord.bottle_date) == year)).scalars().all()
    for bo in bottles:
        if bo.v_cap_chiet_hl > 0 and (bo.ca1 + bo.ca2 + bo.ca3) <= 0:
            out.append(f"Mã thông tin chiết = {bo.bottle_code} Nhập sản lượng không đúng")
    filters = db.execute(select(FilterRecord).where(
        extract("month", FilterRecord.filter_date) == month,
        extract("year", FilterRecord.filter_date) == year)).scalars().all()
    for fl in filters:
        if fl.filter_type != "ve_bbt_phoi" and not fl.has_indicators:
            out.append(f"Mã thông tin lọc = {fl.filter_code} Chưa nhập chỉ tiêu lọc")
    return {"month": month, "year": year, "count": len(out), "alerts": out}


def process_quality_alerts(db: Session) -> dict:
    """QC FAIL + reading vượt giới hạn QC trong recipe snapshot."""
    alerts = []
    batches = db.execute(select(BatchExecution)).scalars().all()
    for b in batches:
        fails = db.execute(select(QualityResult).where(
            QualityResult.scope_type == "batch", QualityResult.scope_id == b.batch_id,
            QualityResult.status == "fail")).scalars().all()
        for f in fails:
            alerts.append({"severity": "high", "batch": b.batch_code, "type": "QC FAIL",
                           "detail": f"{f.parameter} = {f.value} {f.unit or ''} ngoài [{f.lower_limit}, {f.upper_limit}]"})
        checks = {c.get("parameter"): c for c in (b.recipe_snapshot or {}).get("quality_checks", [])}
        readings = db.execute(select(ProcessReading).where(ProcessReading.batch_id == b.batch_id)).scalars().all()
        seen = set()
        for r in readings:
            chk = checks.get(r.parameter)
            if not chk:
                continue
            lo, hi = chk.get("lower"), chk.get("upper")
            if (lo is not None and r.value < lo) or (hi is not None and r.value > hi):
                key = (b.batch_id, r.parameter)
                if key not in seen:
                    seen.add(key)
                    alerts.append({"severity": "medium", "batch": b.batch_code, "type": "Reading out-of-range",
                                   "detail": f"{r.parameter} = {r.value} {r.unit or ''} ngoài [{lo}, {hi}]"})
    return {"count": len(alerts), "alerts": alerts}


def calibrations(db: Session, calib_type: str = None) -> list:
    items = db.execute(select(Calibration).order_by(Calibration.due_date)).scalars().all()
    today = date.today()
    out = []
    for c in items:
        if calib_type and c.calib_type != calib_type:
            continue
        days = (c.due_date - today).days
        status = "overdue" if days < 0 else ("due" if days <= 30 else "valid")
        eq = db.get(Equipment, c.equipment_id) if c.equipment_id else None
        out.append({"calib_id": c.calib_id, "name": c.name, "calib_type": c.calib_type,
                    "equipment": eq.code if eq else None, "last_date": c.last_date,
                    "due_date": c.due_date, "days_left": days, "result": c.result, "status": status})
    return out


def energy_monthly(db: Session, year: int = None) -> list:
    rows = db.execute(select(EnergyReading)).scalars().all()
    groups = {g.group_id: g for g in db.execute(select(EnergyGroup)).scalars().all()}
    agg = {}
    for r in rows:
        if year and r.day.year != year:
            continue
        ym = f"{r.day.year}-{r.day.month:02d}"
        agg.setdefault((ym, r.group_id), 0.0)
        agg[(ym, r.group_id)] += r.value
    out = []
    for (ym, gid), v in agg.items():
        g = groups.get(gid)
        out.append({"month": ym, "group_id": gid, "group": g.name if g else gid,
                    "unit": g.unit if g else "", "value": round(v, 3)})
    return sorted(out, key=lambda x: (x["month"], x["group"]))
