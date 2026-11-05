"""Báo cáo sản lượng Nấu/Lọc/Chiết theo kỳ (tháng/ngày+lũy kế) — port từ phần mềm QLSX cũ
(dma.biahalong.com:88 › Báo cáo sản xuất), yêu cầu người dùng 2026-11-05: "xem mục báo cáo sản
xuất của phần mềm cũ, tạo cho tôi các báo cáo như vậy, bỏ qua hồ sơ điện tử".

3 báo cáo trong file này (Nhóm A — đã thống nhất phạm vi, bỏ Nhóm E/F):
- pack_output_by_category(): BC sản lượng chiết theo tháng, nhóm theo Loại bia (category) hoặc
  theo từng SKU (group_by="sku", yêu cầu người dùng 2026-11-05), kèm % hiệu suất thu hồi (chiết
  ra / dịch đưa vào chiết).
- pack_output_cumulative(): BC sản lượng chiết lũy kế — 1 ngày cụ thể, kèm lũy kế tuần/tháng/năm
  song song, theo từng SKU (FinishedProduct).
- brew_volume_by_product(): BC sản lượng nấu theo tháng, nhóm theo Dịch bia (Product), kèm tổng
  cộng theo từng dịch bia — mirror "V dịch"/"V tồn" của báo cáo cũ (V tồn lấy từ BatchTank.on_hand
  của tank mà mẻ đó đã gộp vào — xem ghi chú trong hàm, đây là số liệu CẤP TANK chứ không tách
  được riêng cho từng mẻ nếu 1 tank gộp nhiều mẻ).
"""

import calendar
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..common import execute_in_chunks
from ..errors import DomainError
from ..models.batches import BatchExecution
from ..models.batch_pipeline import (
    BatchFilterLot,
    BatchPackLot,
    BatchTank,
    BatchTankLink,
)
from ..models.master import FinishedProduct, Product

L_PER_HL = 100.0

# Nhãn hiển thị cho category (free-text trên FinishedProduct/BatchFilterLot — mirror
# CATEGORIES ở services/packaging.py cho phần bao bì, nhưng đây là category CỦA BIA, khác tập
# giá trị, nên không dùng chung).
_CATEGORY_LABEL_FALLBACK = "Chưa phân loại"


def _month_bounds_utc(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    days = calendar.monthrange(year, month)[1]
    end = datetime(year, month, days, 23, 59, 59, tzinfo=timezone.utc)
    return start, end


# Mốc 00:00 giờ VN quy đổi UTC (mirror dashboard.py::_vn_day_start_utc) — dùng cho báo cáo
# NGÀY (lũy kế) vì sai lệch 7 tiếng UTC/VN ảnh hưởng rõ ràng tới "hôm nay" ở biên 17h-24h UTC,
# khác báo cáo THÁNG (ảnh hưởng không đáng kể, dùng mốc UTC lịch cho đơn giản, mirror
# oee_waterfall.py::_month_bounds).
_VN_OFFSET = timedelta(hours=7)


def _vn_day_bounds_utc(d: date) -> tuple[datetime, datetime]:
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) - _VN_OFFSET
    return start, start + timedelta(days=1) - timedelta(seconds=1)


def pack_output_by_category(db: Session, year: int, month: int, group_by: str = "category") -> dict:
    """BC sản lượng chiết theo tháng, nhóm theo Loại bia (category kế thừa từ BatchFilterLot
    nguồn — mirror qc_catalog.py ghi chú "BatchPackLot không tự lưu category, kế thừa từ
    BatchFilterLot nguồn") hoặc theo từng SKU (FinishedProduct) — yêu cầu người dùng 2026-11-05
    "báo cáo theo từng SKU" — `group_by="sku"`.

    Hiệu suất thu hồi % tính theo CẢ VÒNG ĐỜI 1 lô lọc (volume_hl = v_dich_hl + nuoc_bai_khi_hl
    đưa vào ↔ tổng lít MỌI lô thành phẩm đã tách ra từ lô đó — dùng volume_hl chứ KHÔNG phải
    v_dich_hl riêng, vì nước bài khí pha loãng vào cũng được đóng chai/lon cùng dịch, xác nhận
    bằng dữ liệu thật: 1 lô lọc volume_hl=21 → đúng 2100 lít chiết ra = 100% khớp), KHÔNG tính
    riêng theo lượt chiết trong tháng — vì
    split_filter_lot_to_pack_lot() trừ on_hand đúng 1:1 theo `qty` (xem L_PER_HL ở đó, không có
    hao hụt ghi nhận riêng ở BƯỚC tách), nên hao hụt thật chỉ lộ ra khi so TOÀN BỘ input của lô
    lọc với TOÀN BỘ output cộng dồn của nó — so riêng theo từng lượt/từng tháng sẽ cho % vô nghĩa
    (lô lọc tách rải qua nhiều tháng, mỗi tháng chỉ thấy 1 phần output so với 100% input). Mỗi lô
    lọc được xếp vào ĐÚNG 1 tháng — tháng của lượt tách CUỐI CÙNG (coi như lô đã "chiết xong" khi
    đó) — để không đếm trùng input giữa các tháng.

    Khi group_by="sku": 1 lô lọc có thể tách ra NHIỀU SKU khác nhau (không có input riêng từng
    SKU) — input_hl của lô lọc được PHÂN BỔ cho từng SKU theo tỷ trọng output (lít) của SKU đó
    trong tổng output của lô, nên yield_pct theo SKU là ƯỚC TÍNH (giả định hao hụt rải đều theo
    tỷ lệ, không lệch theo SKU) — tổng input_hl/output_l cộng lại giữa các SKU vẫn khớp đúng
    tổng theo category (không có input nào bị đếm trùng/thiếu khi đổi cách nhóm)."""
    if group_by not in ("category", "sku"):
        raise DomainError(f"group_by không hợp lệ: {group_by!r}")
    start, end = _month_bounds_utc(year, month)
    all_pack_lots = db.execute(select(BatchPackLot).where(
        BatchPackLot.finished_product_id.is_not(None) | BatchPackLot.filter_lot_id.is_not(None)
    )).scalars().all()
    by_filter_lot: dict[str, list] = {}
    for p in all_pack_lots:
        if p.filter_lot_id:
            by_filter_lot.setdefault(p.filter_lot_id, []).append(p)
    all_filter_lots_by_id = {fl.filter_lot_id: fl for fl in execute_in_chunks(
        db, lambda chunk: select(BatchFilterLot).where(BatchFilterLot.filter_lot_id.in_(chunk)),
        set(by_filter_lot), scalars=True)}
    # Chỉ giữ lô lọc ĐÃ CHIẾT HẾT (on_hand ≈ 0) có lượt tách CUỐI CÙNG rơi vào đúng tháng đang
    # xem — lô còn dở (chưa rút hết, sẽ còn tách tiếp ở tháng sau) CHƯA tính vào tháng này, nếu
    # không input (v_dich_hl cả lô) sẽ bị gán hết vào tháng mới có 1 phần output đầu tiên, trong
    # khi phần output còn lại (tháng sau) không được cộng bù → hiệu suất tính sai be bét (lô vẫn
    # "đang chiết dở" vào thời điểm chạy báo cáo cho tháng trước đó sẽ không bao giờ lọt vào đâu).
    filter_lot_ids_in_month = {
        fid for fid, lots in by_filter_lot.items()
        if (fl := all_filter_lots_by_id.get(fid)) is not None and fl.on_hand <= 1e-6
        and start <= max(p.pack_date for p in lots) <= end
    }
    filter_lots_by_id = all_filter_lots_by_id
    pack_lots_in_month_scope = [p for fid in filter_lot_ids_in_month for p in by_filter_lot[fid]]
    finished_product_ids = {p.finished_product_id for p in pack_lots_in_month_scope if p.finished_product_id}
    fp_by_id = {f.finished_product_id: f for f in execute_in_chunks(
        db, lambda chunk: select(FinishedProduct).where(FinishedProduct.finished_product_id.in_(chunk)),
        finished_product_ids, scalars=True)}

    by_key: dict[str, dict] = {}
    for fid in filter_lot_ids_in_month:
        fl = filter_lots_by_id.get(fid)
        lots = by_filter_lot[fid]
        fl_input_hl = (fl.volume_hl or 0.0) if fl else 0.0
        if group_by == "sku":
            total_output_fl = sum(p.qty or 0.0 for p in lots)
            for p in lots:
                fp = fp_by_id.get(p.finished_product_id)
                key = p.finished_product_id or "_khac"
                c = by_key.setdefault(key, {
                    "finished_product_code": fp.code if fp else None,
                    "finished_product_name": fp.name if fp else "(Chưa gán SKU)",
                    "output_l": 0.0, "case_count": 0.0, "input_hl": 0.0, "filter_lot_ids": set()})
                share = (p.qty or 0.0) / total_output_fl if total_output_fl > 1e-9 else 0.0
                c["input_hl"] += fl_input_hl * share
                c["filter_lot_ids"].add(fid)
                c["output_l"] += p.qty or 0.0
                if fp and fp.pack_size and fp.unit_volume_l:
                    c["case_count"] += (p.qty or 0.0) / (fp.pack_size * fp.unit_volume_l)
        else:
            cat = (fl.category if fl else None) or _CATEGORY_LABEL_FALLBACK
            c = by_key.setdefault(cat, {"category": cat, "output_l": 0.0, "case_count": 0.0,
                                        "input_hl": 0.0, "filter_batch_count": 0})
            c["input_hl"] += fl_input_hl
            c["filter_batch_count"] += 1
            for p in lots:
                c["output_l"] += p.qty or 0.0
                fp = fp_by_id.get(p.finished_product_id)
                if fp and fp.pack_size and fp.unit_volume_l:
                    c["case_count"] += (p.qty or 0.0) / (fp.pack_size * fp.unit_volume_l)

    items = []
    if group_by == "sku":
        for c in by_key.values():
            input_l = c["input_hl"] * L_PER_HL
            items.append({
                "finished_product_code": c["finished_product_code"],
                "finished_product_name": c["finished_product_name"],
                "filter_batch_count": len(c["filter_lot_ids"]),
                "input_hl": round(c["input_hl"], 2), "output_l": round(c["output_l"], 1),
                "case_count": round(c["case_count"]) if c["case_count"] else None,
                "yield_pct": round(c["output_l"] / input_l * 100, 2) if input_l > 1e-6 else None,
            })
        items.sort(key=lambda i: i["finished_product_code"] or "")
    else:
        for cat in sorted(by_key):
            c = by_key[cat]
            input_l = c["input_hl"] * L_PER_HL
            items.append({
                "category": cat, "filter_batch_count": c["filter_batch_count"],
                "input_hl": round(c["input_hl"], 2), "output_l": round(c["output_l"], 1),
                "case_count": round(c["case_count"]) if c["case_count"] else None,
                "yield_pct": round(c["output_l"] / input_l * 100, 2) if input_l > 1e-6 else None,
            })
    total_output = sum(i["output_l"] for i in items)
    total_input_hl = sum(i["input_hl"] for i in items)
    return {"year": year, "month": month, "group_by": group_by, "items": items,
            "total": {"output_l": round(total_output, 1), "input_hl": round(total_input_hl, 2),
                      "yield_pct": round(total_output / (total_input_hl * L_PER_HL) * 100, 2)
                      if total_input_hl > 1e-6 else None}}


def pack_output_cumulative(db: Session, as_of_date: date) -> dict:
    """BC sản lượng chiết lũy kế — 1 ngày cụ thể kèm lũy kế tuần (từ Thứ 2 ISO)/tháng/năm, theo
    từng SKU (FinishedProduct) — mirror "BC sản lượng chiết lũy kế" của phần mềm cũ (ngày/tuần/
    tháng/năm hiện song song cùng 1 bảng)."""
    day_start, day_end = _vn_day_bounds_utc(as_of_date)
    iso_year, iso_week, _ = as_of_date.isocalendar()
    week_start_date = date.fromisocalendar(iso_year, iso_week, 1)
    week_start, _ = _vn_day_bounds_utc(week_start_date)
    month_start, _ = _vn_day_bounds_utc(date(as_of_date.year, as_of_date.month, 1))
    year_start, _ = _vn_day_bounds_utc(date(as_of_date.year, 1, 1))

    windows = {"day": (day_start, day_end), "week": (week_start, day_end),
              "month": (month_start, day_end), "year": (year_start, day_end)}
    pack_lots = db.execute(select(BatchPackLot).where(
        BatchPackLot.pack_date >= year_start, BatchPackLot.pack_date <= day_end,
        BatchPackLot.finished_product_id.is_not(None))).scalars().all()
    fp_ids = {p.finished_product_id for p in pack_lots}
    fps = execute_in_chunks(db, lambda chunk: select(FinishedProduct).where(
        FinishedProduct.finished_product_id.in_(chunk)), fp_ids, scalars=True)
    fp_by_id = {f.finished_product_id: f for f in fps}

    out_by_fp: dict[str, dict] = {fid: {"day": 0.0, "week": 0.0, "month": 0.0, "year": 0.0}
                                  for fid in fp_ids}
    for p in pack_lots:
        acc = out_by_fp.get(p.finished_product_id)
        if acc is None:
            continue
        for win_name, (w_start, w_end) in windows.items():
            if w_start <= p.pack_date <= w_end:
                acc[win_name] += p.qty or 0.0

    def _case(fp, liters):
        if fp and fp.pack_size and fp.unit_volume_l:
            return round(liters / (fp.pack_size * fp.unit_volume_l))
        return None

    items = []
    for fid, acc in out_by_fp.items():
        fp = fp_by_id.get(fid)
        if not fp:
            continue
        items.append({
            "finished_product_code": fp.code, "finished_product_name": fp.name,
            "category": fp.category,
            "day": {"case": _case(fp, acc["day"]), "l": round(acc["day"], 1)},
            "week": {"case": _case(fp, acc["week"]), "l": round(acc["week"], 1)},
            "month": {"case": _case(fp, acc["month"]), "l": round(acc["month"], 1)},
            "year": {"case": _case(fp, acc["year"]), "l": round(acc["year"], 1)},
        })
    items.sort(key=lambda i: i["finished_product_code"] or "")
    return {"as_of": as_of_date.isoformat(), "items": items}


def brew_volume_by_product(db: Session, year: int, month: int) -> dict:
    """BC sản lượng nấu theo tháng, nhóm theo Dịch bia (Product) — mỗi dòng 1 mẻ nấu, kèm tổng
    cộng theo dịch bia. "V tồn" lấy từ BatchTank.on_hand của tank mẻ đó đã gộp vào — LƯU Ý: đây
    là số tồn CẤP TANK (nhiều mẻ gộp 1 tank sẽ cùng hiện 1 số tồn như nhau), không tách được
    riêng cho từng mẻ, mirror đúng giới hạn dữ liệu đã xác nhận khi khảo sát báo cáo cũ."""
    start, end = _month_bounds_utc(year, month)
    batches = db.execute(select(BatchExecution).where(
        BatchExecution.start_at >= start, BatchExecution.start_at <= end
    ).order_by(BatchExecution.start_at)).scalars().all()
    batch_ids = [b.batch_id for b in batches]
    links = execute_in_chunks(db, lambda chunk: select(BatchTankLink).where(
        BatchTankLink.batch_id.in_(chunk)), batch_ids, scalars=True)
    tank_id_by_batch: dict[str, str] = {}
    for l in links:
        tank_id_by_batch.setdefault(l.batch_id, l.tank_id)   # 1 mẻ chỉ gộp vào đúng 1 tank
    tank_ids = set(tank_id_by_batch.values())
    tanks_by_id = {t.tank_id: t for t in execute_in_chunks(
        db, lambda chunk: select(BatchTank).where(BatchTank.tank_id.in_(chunk)), tank_ids, scalars=True)}
    product_ids = {b.product_id for b in batches if b.product_id}
    products_by_id = {p.product_id: p for p in execute_in_chunks(
        db, lambda chunk: select(Product).where(Product.product_id.in_(chunk)), product_ids, scalars=True)}

    rows = []
    subtotal_by_product: dict[str, dict] = {}
    for b in batches:
        prod = products_by_id.get(b.product_id)
        prod_code = prod.code if prod else None
        prod_name = prod.name if prod else "(chưa gán dịch bia)"
        tank = tanks_by_id.get(tank_id_by_batch.get(b.batch_id))
        rows.append({
            "batch_code": b.batch_code, "start_at": b.start_at, "end_at": b.end_at,
            "product_code": prod_code, "product_name": prod_name,
            "tank_code": tank.tank_code if tank else None,
            "v_dich": b.actual_qty, "v_ton": tank.on_hand if tank else None, "uom": b.uom,
        })
        s = subtotal_by_product.setdefault(prod_name, {"product_name": prod_name, "v_dich": 0.0, "batch_count": 0})
        s["v_dich"] += b.actual_qty or 0.0
        s["batch_count"] += 1
    for s in subtotal_by_product.values():
        s["v_dich"] = round(s["v_dich"], 2)
    return {"year": year, "month": month, "items": rows,
            "subtotals": sorted(subtotal_by_product.values(), key=lambda s: s["product_name"])}
