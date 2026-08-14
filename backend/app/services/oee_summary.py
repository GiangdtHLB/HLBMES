"""Dashboard "Summary" OEE — tổng hợp xu hướng OPI theo tháng/quý/tuần (rolling 13 tuần) +
Pareto tổn thất theo tháng vừa qua / quý hiện tại, mirror đúng bố cục sheet Summary của file vận
hành thật "OPI - CAN L3 (KHS 30K).xlsx" (16 biểu đồ), nhưng lấy target từ chính
`OeeReasonCatalog.target_pct` đang sống trong hệ thống — không hardcode lại số target cũ trong
file Excel gốc, để nhất quán với tab Dashboard OPI hiện có.
"""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..common import utcnow
from ..models.oee_ext import DowntimeEvent, OeeReasonCatalog
from . import oee_waterfall as wf


def _opi_point(db: Session, line_code: str, label: str, start, end, elapsed_days: int, meta: dict) -> dict:
    s = wf._opi_summary_bounds(db, line_code, start, end, elapsed_days, meta)
    by_cat = {c["category"]: c for c in s["by_category"]}
    unplanned_pct = by_cat["thieu_vat_tu"]["actual_pct"] + by_cat["breakdown"]["actual_pct"] + by_cat["dung_lat_nhat"]["actual_pct"]
    return {
        "label": label, "opi": s["opi"], "opi_target": s["opi_target"],
        "opi_nona": s["opi_nona"], "opi_nona_target": s["opi_nona_target"],
        "efficiency": s["efficiency"], "efficiency_target": s["efficiency_target"],
        "planned_pct": by_cat["ke_hoach"]["actual_pct"], "planned_target": by_cat["ke_hoach"]["target_pct"],
        "unplanned_pct": round(unplanned_pct, 4),
        "changeover_pct": by_cat["chuyen_may"]["actual_pct"], "changeover_target": by_cat["chuyen_may"]["target_pct"],
        "breakdown_pct": by_cat["breakdown"]["actual_pct"], "breakdown_target": by_cat["breakdown"]["target_pct"],
        "ms_sl_pct": by_cat["dung_lat_nhat"]["actual_pct"], "ms_sl_target": by_cat["dung_lat_nhat"]["target_pct"],
        "by_category": s["by_category"],
    }


def monthly_trend(db: Session, line_code: str, year: int) -> list:
    return [_opi_point(db, line_code, f"T{m}", *wf._month_bounds(year, m), {"year": year, "month": m})
            for m in range(1, 13)]


def quarterly_trend(db: Session, line_code: str, year: int) -> list:
    return [_opi_point(db, line_code, f"Q{q}", *wf._quarter_bounds(year, q), {"year": year, "quarter": q})
            for q in range(1, 5)]


def weekly_trend(db: Session, line_code: str) -> list:
    """13 tuần ISO gần nhất tính tới tuần hiện tại (kể cả tuần hiện tại), mirror cửa sổ trượt
    D47:P47 của sheet Summary."""
    cur_year, cur_week, _ = utcnow().isocalendar()
    points = []
    for i in range(12, -1, -1):
        wk = cur_week - i
        yr = cur_year
        while wk < 1:
            yr -= 1
            wk += date(yr, 12, 28).isocalendar()[1]  # số tuần ISO thực của năm trước (52 hoặc 53)
        points.append(_opi_point(db, line_code, f"W{wk}", *wf._week_bounds(yr, wk), {"iso_year": yr, "iso_week": wk}))
    return points


def category_breakdown(db: Session, line_code: str, start, end, reason_group: str, by_machine_position: bool = False) -> list:
    """Pareto phút dừng theo lý do con (hoặc theo vị trí máy nếu category=breakdown), sắp giảm dần."""
    if by_machine_position:
        q = (
            select(OeeReasonCatalog.machine_position.label("label"),
                   func.sum(DowntimeEvent.minutes).label("minutes"),
                   func.count(DowntimeEvent.event_id).label("count"))
            .join(OeeReasonCatalog, DowntimeEvent.reason_catalog_id == OeeReasonCatalog.reason_id)
            .where(DowntimeEvent.line == line_code, DowntimeEvent.reason_group == reason_group,
                   DowntimeEvent.shift_date >= start, DowntimeEvent.shift_date <= end)
            .group_by(OeeReasonCatalog.machine_position)
        )
    else:
        q = (
            select(DowntimeEvent.reason_label.label("label"),
                   func.sum(DowntimeEvent.minutes).label("minutes"),
                   func.count(DowntimeEvent.event_id).label("count"))
            .where(DowntimeEvent.line == line_code, DowntimeEvent.reason_group == reason_group,
                   DowntimeEvent.shift_date >= start, DowntimeEvent.shift_date <= end)
            .group_by(DowntimeEvent.reason_label)
        )
    items = [{"label": r.label or "(khác)", "minutes": round(float(r.minutes or 0), 1), "count": int(r.count or 0)}
             for r in db.execute(q).all()]
    items.sort(key=lambda x: -x["minutes"])
    return items


def period_breakdowns(db: Session, line_code: str, start, end) -> dict:
    return {
        "planned_downtime": category_breakdown(db, line_code, start, end, "ke_hoach"),
        "breakdown": category_breakdown(db, line_code, start, end, "breakdown", by_machine_position=True),
        "minor_stop": category_breakdown(db, line_code, start, end, "dung_lat_nhat"),
    }


def summary_dashboard(db: Session, line_code: str, year: int, month: int) -> dict:
    quarter = (month - 1) // 3 + 1
    lm_start, lm_end, _ = wf._month_bounds(year, month)
    q_start, q_end, _ = wf._quarter_bounds(year, quarter)
    return {
        "line_code": line_code, "year": year, "month": month, "quarter": quarter,
        "monthly": monthly_trend(db, line_code, year),
        "quarterly": quarterly_trend(db, line_code, year),
        "weekly": weekly_trend(db, line_code),
        "last_month_breakdowns": period_breakdowns(db, line_code, lm_start, lm_end),
        "this_quarter_breakdowns": period_breakdowns(db, line_code, q_start, q_end),
    }
