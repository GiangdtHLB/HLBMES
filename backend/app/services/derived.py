"""Truy vấn dẫn xuất dùng chung (cảnh báo brewing/QC, kiểm định, năng lượng).

Tách khỏi router để cả router lẫn ai_tools cùng gọi service — tránh service
import ngược lên router (vòng phụ thuộc, khó test). Hàm thuần (db, **params)->dict/list.
"""

from datetime import date

from sqlalchemy import extract, select
from sqlalchemy.orm import Session

from ..common import utcnow
from ..models.batches import BatchExecution
from ..models.brewing import BottleRecord, FermentRecord, FilterRecord
from ..models.energy import EnergyArea, EnergyGroup, EnergyReading
from ..models.maintenance import Calibration, Equipment
from ..models.metrics import ProcessReading
from ..models.quality import QualityResult


def ferment_status(r: FermentRecord) -> str:
    """Trạng thái lên men suy ra từ dữ liệu thật, không dùng cột status tĩnh:
    - `kt_date` rỗng (chưa nạp đầy tank — còn mẻ nào của mã nấu nạp vào tank này chưa bấm
      "Kết thúc", xem routers/brewing.py::_sync_ferment_kt_date) → "đang nấu", CHƯA thật sự
      lên men dù đã có dịch trong tank.
    - Từ lúc `kt_date` có giá trị (mẻ cuối đã kết thúc) mới xét theo tồn CCT thật
      (on_hand_cct): chưa lọc gì (đang lên men) / đã lọc một phần / đã lọc hết (về 0)."""
    if r.kt_date is None:
        return "dang_nau"
    if r.on_hand_cct <= 1e-6:
        return "da_loc_het"
    if r.on_hand_cct < r.volume_hl - 1e-6:
        return "loc_mot_phan"
    return "len_men"


def filter_status(r: FilterRecord) -> str:
    """Trạng thái lọc suy ra từ tồn BBT thật (on_hand_bbt), không dùng cột status tĩnh:
    chưa chiết chút nào / đang chiết (chưa hết) / đã chiết hết (on_hand_bbt về 0). ended_at
    (toàn bản ghi) chỉ có khi TẤT CẢ tank của bản ghi đã bấm "Kết thúc" (xem
    routers/brewing.py::_sync_filter_aggregate) — trong lúc đó phải coi là "đang lọc", KHÔNG
    phải "chờ chiết" (dễ hiểu nhầm là đã lọc xong, chỉ còn chờ đem đi chiết). Sau khi lọc xong
    nhưng CHƯA được KCS duyệt (qc_approved) phải coi là "chờ duyệt" — chưa cho phép chiết (xem
    filter_order_svc.available_bbt_tanks gate any_qc_approved) nên không được hiện "chờ chiết"
    (dễ hiểu nhầm là đã sẵn sàng đem đi chiết)."""
    if r.ended_at is None:
        return "dang_loc"
    if not r.qc_approved:
        return "cho_duyet"
    if r.v_beer_hl <= 1e-6:
        return "cho_chiet"
    if r.on_hand_bbt <= 1e-6:
        return "da_chiet_het"
    if r.on_hand_bbt < r.v_beer_hl - 1e-6:
        return "chiet_1_phan"
    return "cho_chiet"


def brewing_alerts(db: Session, month: int = None, year: int = None) -> dict:
    now = utcnow()
    month = month or now.month
    year = year or now.year
    out = []
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
