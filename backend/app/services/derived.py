"""Truy vấn dẫn xuất dùng chung (cảnh báo QC, kiểm định, năng lượng).

Tách khỏi router để cả router lẫn ai_tools cùng gọi service — tránh service
import ngược lên router (vòng phụ thuộc, khó test). Hàm thuần (db, **params)->dict/list.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.batches import BatchExecution
from ..models.energy import EnergyArea, EnergyGroup, EnergyReading
from ..models.maintenance import Calibration, Equipment
from ..models.metrics import ProcessReading
from ..models.quality import QualityResult


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


def energy_report(db: Session, date_from: date, date_to: date, group_by: str = "day",
                  area_id: str | None = None) -> dict:
    """Báo cáo năng lượng theo khoảng ngày — tổng theo nhóm (điện/nước/hơi...), chuỗi
    theo kỳ (ngày/tháng), và phân theo khu vực (area_id=None/"all" => gộp mọi khu, có
    breakdown theo khu cho biểu đồ tròn/bảng; truyền area_id cụ thể => chỉ khu đó, không
    breakdown). Đây là dữ liệu nội bộ MES (EnergyReading) — CHƯA nối với kết nối SQL
    ngoài đã khai báo ở Tích hợp (xem SqlConnection.purpose="energy"); sẽ nối sau khi có
    tên bảng/cột cụ thể bên hệ SCADA/WinCC."""
    groups = {g.group_id: g for g in db.execute(select(EnergyGroup)).scalars().all()}
    areas = {a.area_id: a for a in db.execute(select(EnergyArea)).scalars().all()}

    stmt = select(EnergyReading).where(EnergyReading.day >= date_from, EnergyReading.day <= date_to)
    if area_id and area_id != "all":
        stmt = stmt.where(EnergyReading.area_id == area_id)
    rows = db.execute(stmt).scalars().all()

    def period_key(d):
        return f"{d.year}-{d.month:02d}" if group_by == "month" else d.isoformat()

    def area_name(area_key):
        if area_key == "_none":
            return "Toàn nhà máy"
        a = areas.get(area_key)
        return a.name if a else area_key

    totals: dict = {}
    series_agg: dict = {}
    series_by_area_agg: dict = {}
    by_area_agg: dict = {}

    for r in rows:
        totals[r.group_id] = totals.get(r.group_id, 0.0) + r.value
        p = period_key(r.day)
        series_agg[(p, r.group_id)] = series_agg.get((p, r.group_id), 0.0) + r.value
        area_key = r.area_id or "_none"
        k2 = (p, r.group_id, area_key)
        series_by_area_agg[k2] = series_by_area_agg.get(k2, 0.0) + r.value
        k3 = (r.group_id, area_key)
        by_area_agg[k3] = by_area_agg.get(k3, 0.0) + r.value

    series = sorted(
        [{"period": p, "group_id": gid, "value": round(v, 3)} for (p, gid), v in series_agg.items()],
        key=lambda x: (x["period"], x["group_id"]))
    series_by_area = sorted(
        [{"period": p, "group_id": gid, "area_id": ak, "area_name": area_name(ak), "value": round(v, 3)}
         for (p, gid, ak), v in series_by_area_agg.items()],
        key=lambda x: (x["period"], x["group_id"], x["area_name"]))
    by_area = sorted(
        [{"group_id": gid, "area_id": ak, "area_name": area_name(ak), "value": round(v, 3)}
         for (gid, ak), v in by_area_agg.items()],
        key=lambda x: (x["group_id"], x["area_name"]))

    return {
        "date_from": date_from.isoformat(), "date_to": date_to.isoformat(), "group_by": group_by,
        "groups": [{"group_id": g.group_id, "code": g.code, "name": g.name, "unit": g.unit}
                  for g in groups.values()],
        "totals": {gid: round(v, 3) for gid, v in totals.items()},
        "series": series, "series_by_area": series_by_area, "by_area": by_area,
    }
