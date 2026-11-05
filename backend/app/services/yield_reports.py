"""BC hiệu suất chi tiết theo tháng (Nhóm D, port từ phần mềm QLSX cũ dma.biahalong.com:88 ›
Báo cáo sản xuất), yêu cầu người dùng 2026-11-05.

Khác `services/yield_calc.py::yield_report()` (CHỈ xem được hiệu suất của 1 mẻ cụ thể) —
`monthly_yield_detail()` gộp TẤT CẢ `BatchYieldActual` ghi nhận trong 1 tháng (theo `recorded_at`
của chính dòng yield, không phải ngày nấu mẻ) thành 1 báo cáo: chi tiết từng dòng (1 mẻ × 1 công
đoạn) kèm tổng hợp theo công đoạn (số mẻ, hiệu suất TB thực tế so kỳ vọng, số mẻ dưới kỳ vọng).
"""

import calendar
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..common import execute_in_chunks
from ..models.batches import BatchExecution
from ..models.recipe_ext import BatchYieldActual
from .yield_calc import step_yield


def _month_bounds_utc(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    days = calendar.monthrange(year, month)[1]
    end = datetime(year, month, days, 23, 59, 59, tzinfo=timezone.utc)
    return start, end


_STEP_LABEL = {"nau": "Nấu", "len_men": "Lên men", "loc": "Lọc", "chiet": "Chiết"}


def monthly_yield_detail(db: Session, year: int, month: int) -> dict:
    start, end = _month_bounds_utc(year, month)
    rows = db.execute(select(BatchYieldActual).where(
        BatchYieldActual.recorded_at >= start, BatchYieldActual.recorded_at <= end
    ).order_by(BatchYieldActual.step_no, BatchYieldActual.recorded_at)).scalars().all()
    batch_ids = {r.batch_id for r in rows}
    batches_by_id = {b.batch_id: b for b in execute_in_chunks(
        db, lambda chunk: select(BatchExecution).where(BatchExecution.batch_id.in_(chunk)),
        batch_ids, scalars=True)}

    items = []
    by_step: dict[str, dict] = {}
    for r in rows:
        b = batches_by_id.get(r.batch_id)
        pct = step_yield(r.input_qty, r.output_qty)
        below = r.expected_pct is not None and pct < r.expected_pct
        items.append({
            "batch_code": b.batch_code if b else None, "step_key": r.step_key,
            "step_label": _STEP_LABEL.get(r.step_key, r.step_key),
            "input_qty": r.input_qty, "output_qty": r.output_qty, "uom": r.uom,
            "step_pct": pct, "expected_pct": r.expected_pct, "below_expected": below,
            "recorded_at": r.recorded_at, "recorded_by": r.recorded_by,
        })
        s = by_step.setdefault(r.step_key, {
            "step_key": r.step_key, "step_label": _STEP_LABEL.get(r.step_key, r.step_key),
            "n": 0, "pct_sum": 0.0, "expected_sum": 0.0, "expected_n": 0, "below_count": 0,
        })
        s["n"] += 1
        s["pct_sum"] += pct
        if r.expected_pct is not None:
            s["expected_sum"] += r.expected_pct
            s["expected_n"] += 1
        if below:
            s["below_count"] += 1

    summary = []
    for key, s in by_step.items():
        summary.append({
            "step_key": key, "step_label": s["step_label"], "n": s["n"],
            "avg_pct": round(s["pct_sum"] / s["n"], 2) if s["n"] else None,
            "avg_expected_pct": round(s["expected_sum"] / s["expected_n"], 2) if s["expected_n"] else None,
            "below_expected_count": s["below_count"],
        })
    step_order = {"nau": 1, "len_men": 2, "loc": 3, "chiet": 4}
    summary.sort(key=lambda s: step_order.get(s["step_key"], 99))
    items.sort(key=lambda i: (step_order.get(i["step_key"], 99), i["recorded_at"]))
    return {"year": year, "month": month, "summary": summary, "items": items}
