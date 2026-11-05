"""BC hiệu suất chi tiết theo tháng (Nhóm D, port từ phần mềm QLSX cũ dma.biahalong.com:88 ›
Báo cáo sản xuất), yêu cầu người dùng 2026-11-05.

Khác `services/yield_calc.py::yield_report()` (CHỈ xem được hiệu suất của 1 mẻ cụ thể) —
`monthly_yield_detail()` gộp TẤT CẢ `BatchYieldActual` ghi nhận trong 1 tháng (theo `recorded_at`
của chính dòng yield, không phải ngày nấu mẻ) thành 1 báo cáo: chi tiết từng dòng (1 mẻ × 1 công
đoạn) kèm tổng hợp theo công đoạn (số mẻ, hiệu suất TB thực tế so kỳ vọng, số mẻ dưới kỳ vọng).
"""

import calendar
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..common import execute_in_chunks
from ..models.batch_pipeline import BatchPackLot
from ..models.batches import BatchExecution
from ..models.master import Product
from ..models.recipe_ext import BatchYieldActual
from . import production_reports
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


def overall_yield_and_norms_report(db: Session, year: int, month: int) -> dict:
    """BC hiệu suất tổng + định mức dịch + định mức năng lượng — báo cáo thứ 2 của Nhóm D.

    - Hiệu suất tổng: hiệu suất thu hồi CẢ NHÀ MÁY trong tháng (output chiết / input cấp chiết),
      lấy lại `production_reports.pack_output_by_category()["total"]` — KHÔNG tính lại, tránh 2
      nơi có thể lệch công thức.
    - Định mức dịch: theo TỪNG dịch bia (Product.v_dich_norm_hl, hl/mẻ) — so V dịch TB thực tế/mẻ
      trong tháng (từ BatchExecution.actual_qty, mirror brew_volume_by_product nhưng nhóm theo
      product_id để join định mức chính xác, KHÔNG nhóm theo tên như brew_volume_by_product).
    - Định mức năng lượng: định mức khai theo TỪNG dịch bia (kWh/hl thành phẩm), nhưng đồng hồ
      điện chỉ đo được TOÀN NHÀ MÁY (không tách riêng theo dịch bia) — nên so 1 con số BÌNH QUÂN
      GIA QUYỀN theo sản lượng (Σ norm_i × output_i / Σ output_i) với kWh/hl thực tế TOÀN NHÀ MÁY
      (tổng điện tiêu thụ / TỔNG sản lượng chiết ra trong tháng — mẫu số này KHÁC
      overall["output_l"] phía trên: lấy TẤT CẢ BatchPackLot có pack_date trong tháng, không chỉ
      lô lọc đã chiết HẾT, vì điện tiêu thụ cả nhà máy phải chia cho TOÀN BỘ sản lượng ra trong
      tháng mới có ý nghĩa — dùng nhầm overall["output_l"] (tập con hẹp) từng cho kWh/hl vô lý).
      Nguồn điện là CSDL ngoài (SQL Server thật qua services/energy_external.py) — có thể không
      kết nối được, báo cáo vẫn trả về phần hiệu suất + định mức dịch bình thường, phần năng
      lượng để None kèm lỗi.
    """
    start, end = _month_bounds_utc(year, month)
    pack_rpt = production_reports.pack_output_by_category(db, year, month)
    overall = pack_rpt["total"]

    batches = db.execute(select(BatchExecution).where(
        BatchExecution.start_at >= start, BatchExecution.start_at <= end
    )).scalars().all()
    product_ids = {b.product_id for b in batches if b.product_id}
    products_by_id = {p.product_id: p for p in execute_in_chunks(
        db, lambda chunk: select(Product).where(Product.product_id.in_(chunk)),
        product_ids, scalars=True)}

    by_product: dict[str, dict] = {}
    for b in batches:
        prod = products_by_id.get(b.product_id)
        if not prod:
            continue
        s = by_product.setdefault(prod.product_id, {
            "product_name": prod.name, "v_dich_norm_hl": prod.v_dich_norm_hl,
            "energy_norm_kwh_per_hl": prod.energy_norm_kwh_per_hl,
            "batch_count": 0, "v_dich_sum": 0.0,
        })
        s["batch_count"] += 1
        s["v_dich_sum"] += (b.actual_qty or 0.0)

    v_dich_items = []
    norm_weighted_sum, norm_weight_total = 0.0, 0.0
    for s in by_product.values():
        avg_per_batch_hl = (s["v_dich_sum"] / s["batch_count"] / 100.0) if s["batch_count"] else None
        pct_of_norm = (round(avg_per_batch_hl / s["v_dich_norm_hl"] * 100, 2)
                      if avg_per_batch_hl is not None and s["v_dich_norm_hl"] else None)
        v_dich_items.append({
            "product_name": s["product_name"], "batch_count": s["batch_count"],
            "avg_v_dich_per_batch_hl": round(avg_per_batch_hl, 2) if avg_per_batch_hl is not None else None,
            "v_dich_norm_hl": s["v_dich_norm_hl"], "pct_of_norm": pct_of_norm,
        })
        if s["energy_norm_kwh_per_hl"] is not None:
            norm_weighted_sum += s["energy_norm_kwh_per_hl"] * s["v_dich_sum"]
            norm_weight_total += s["v_dich_sum"]
    v_dich_items.sort(key=lambda i: i["product_name"] or "")
    energy_norm_weighted = round(norm_weighted_sum / norm_weight_total, 4) if norm_weight_total > 1e-9 else None

    energy = {"actual_kwh": None, "actual_kwh_per_hl": None, "norm_kwh_per_hl": energy_norm_weighted,
             "pct_of_norm": None, "error": None}
    # Mẫu số dùng TỔNG sản lượng chiết ra trong tháng (mọi lô thành phẩm có pack_date rơi vào
    # tháng, BẤT KỂ lô lọc nguồn đã rút hết hay chưa) — KHÔNG dùng overall["output_l"]
    # (pack_output_by_category CHỈ tính lô lọc ĐÃ CHIẾT HẾT trong tháng, một tập con hẹp hơn
    # nhiều — dùng nhầm số đó làm mẫu số từng cho ra kWh/hl vô nghĩa, vì điện tiêu thụ CẢ NHÀ MÁY
    # chia cho 1 phần nhỏ sản lượng).
    total_output_l_month = db.execute(select(func.sum(BatchPackLot.qty)).where(
        BatchPackLot.pack_date >= start, BatchPackLot.pack_date <= end)).scalar() or 0.0
    output_hl = total_output_l_month / 100.0
    try:
        from . import energy_external
        elec = energy_external.electricity_report(db, start, end)
        energy["actual_kwh"] = elec["total_station"]
        if output_hl > 1e-9:
            energy["actual_kwh_per_hl"] = round(elec["total_station"] / output_hl, 4)
            if energy_norm_weighted:
                energy["pct_of_norm"] = round(energy["actual_kwh_per_hl"] / energy_norm_weighted * 100, 2)
    except Exception as e:  # CSDL điện ngoài có thể không kết nối được — không chặn cả báo cáo
        energy["error"] = str(e)

    return {"year": year, "month": month, "overall_yield": overall,
            "v_dich_by_product": v_dich_items, "energy": energy}
