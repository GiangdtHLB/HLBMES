"""Báo cáo thống kê QC (Nhóm C, port từ phần mềm QLSX cũ dma.biahalong.com:88 › Báo cáo sản
xuất), yêu cầu người dùng 2026-11-05:
- qc_min_max_avg(): KCS Thống kê Min-Max-AVG — theo từng chỉ tiêu (parameter), thống kê giá trị
  (bỏ qua pass/fail), lọc theo công đoạn (scope_type)/khoảng ngày tùy chọn.
- qc_analysis_count(): KCS đếm số lần phân tích — theo từng chỉ tiêu (tổng số lần + breakdown
  Đạt/Không đạt/Chờ duyệt) VÀ theo từng ngày (tổng số lần phân tích/ngày, xem xu hướng khối
  lượng công việc KCS) — đếm TẤT CẢ QualityResult khớp bộ lọc, không chỉ các dòng có `value`
  (khác qc_min_max_avg, vốn chỉ thống kê được giá trị số).
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.quality import QualityResult
from . import qc_catalog


def _apply_filters(stmt, scope_type: str = None, date_from: datetime = None, date_to: datetime = None):
    if scope_type:
        stmt = stmt.where(QualityResult.scope_type == scope_type)
    if date_from:
        stmt = stmt.where(QualityResult.recorded_at >= date_from)
    if date_to:
        stmt = stmt.where(QualityResult.recorded_at <= date_to)
    return stmt


def qc_min_max_avg(db: Session, scope_type: str = None, date_from: datetime = None,
                   date_to: datetime = None) -> dict:
    """KCS Thống kê Min-Max-AVG — chỉ xét các dòng có `value` (chỉ tiêu dạng số); chỉ tiêu
    pass_fail/text không có ý nghĩa Min/Max/AVG nên bị bỏ qua tự nhiên (value luôn có ở đây theo
    quy ước ghi nhận, nhưng về mặt thống kê min/max/avg của 0/1 không có giá trị đọc hiểu).

    `parameter` (tên trả về) là MÃ THẬT lưu trong QualityResult.parameter (dữ liệu QC cũ lưu mã,
    VD "2515", không phải tên) — tra thêm `parameter_name`/`unit` qua QCParameter.code (yêu cầu
    người dùng 2026-11-05: "hiển thị cả tên chỉ tiêu, đơn vị") — xem
    qc_catalog.resolve_parameter_display(). Không khớp được thì parameter_name = mã, unit = None
    (fallback QualityResult.unit của chính dòng, vì catalog đáng tin hơn nhưng không phải lúc nào
    cũng có)."""
    stmt = _apply_filters(select(QualityResult).where(QualityResult.value.isnot(None)),
                          scope_type, date_from, date_to)
    rows = db.execute(stmt).scalars().all()
    by_param: dict[str, dict] = {}
    for r in rows:
        p = by_param.setdefault(r.parameter, {"parameter": r.parameter, "row_unit": r.unit,
                                              "values": []})
        p["values"].append(r.value)
        if not p["row_unit"] and r.unit:
            p["row_unit"] = r.unit
    resolved = qc_catalog.resolve_parameter_display(db, by_param.keys())
    items = []
    for p, d in by_param.items():
        vals = d["values"]
        items.append({"parameter": p, "parameter_name": resolved[p]["name"],
                      "unit": resolved[p]["unit"] or d["row_unit"], "n": len(vals),
                      "min": round(min(vals), 4), "max": round(max(vals), 4),
                      "avg": round(sum(vals) / len(vals), 4)})
    items.sort(key=lambda i: i["parameter_name"])
    return {"scope_type": scope_type, "items": items}


def qc_analysis_count(db: Session, scope_type: str = None, date_from: datetime = None,
                      date_to: datetime = None) -> dict:
    """KCS đếm số lần phân tích — đếm TẤT CẢ QualityResult (không lọc theo có `value` hay
    không, khác qc_min_max_avg) khớp bộ lọc, nhóm theo chỉ tiêu (kèm breakdown Đạt/Không đạt/
    Chờ duyệt/Không hợp lệ) và theo ngày (tổng số lần phân tích/ngày, trục thời gian).

    `parameter`/`parameter_name`/`unit`: xem docstring qc_min_max_avg() — cùng cơ chế tra tên/ĐVT
    qua QCParameter.code (yêu cầu người dùng 2026-11-05: "hiển thị cả tên chỉ tiêu, đơn vị")."""
    stmt = _apply_filters(select(QualityResult), scope_type, date_from, date_to)
    rows = db.execute(stmt).scalars().all()
    by_param: dict[str, dict] = {}
    by_day: dict[str, int] = {}
    for r in rows:
        p = by_param.setdefault(r.parameter, {"parameter": r.parameter, "row_unit": r.unit,
                                              "total": 0, "pass": 0, "fail": 0, "pending": 0, "invalid": 0})
        p["total"] += 1
        p[r.status] = p.get(r.status, 0) + 1
        if not p["row_unit"] and r.unit:
            p["row_unit"] = r.unit
        if r.recorded_at:
            day = r.recorded_at.date().isoformat()
            by_day[day] = by_day.get(day, 0) + 1
    resolved = qc_catalog.resolve_parameter_display(db, by_param.keys())
    by_parameter = sorted(
        ({**{k: v for k, v in p.items() if k != "row_unit"},
          "parameter_name": resolved[p["parameter"]]["name"],
          "unit": resolved[p["parameter"]]["unit"] or p["row_unit"]} for p in by_param.values()),
        key=lambda i: i["parameter_name"])
    by_day_items = [{"date": d, "count": c} for d, c in sorted(by_day.items())]
    return {"scope_type": scope_type, "total": len(rows),
            "by_parameter": by_parameter, "by_day": by_day_items}
