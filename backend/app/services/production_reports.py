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
import re
import statistics
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
from ..models.lines import ProductionLine
from ..models.master import FinishedProduct, Product
from . import batch_pipeline as batch_pipeline_svc

L_PER_HL = 100.0
_MIN_DT = datetime(1970, 1, 1, tzinfo=timezone.utc)
_TANK_NAME_RE = re.compile(r"^([A-Za-z]+)(\d+)(.*)$")

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
    cộng theo dịch bia + TỔNG CỘNG CHUNG (mọi dịch bia gộp lại — yêu cầu người dùng 2026-11-11:
    "Tính thêm tổng số mẻ/tháng, số lượng dịch/tháng"). "V tồn" lấy từ BatchTank.on_hand của tank
    mẻ đó đã gộp vào — LƯU Ý: đây là số tồn CẤP TANK (nhiều mẻ gộp 1 tank sẽ cùng hiện 1 số tồn
    như nhau), không tách được riêng cho từng mẻ, mirror đúng giới hạn dữ liệu đã xác nhận khi
    khảo sát báo cáo cũ."""
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
    total_batch_count = sum(s["batch_count"] for s in subtotal_by_product.values())
    total_v_dich = round(sum(s["v_dich"] for s in subtotal_by_product.values()), 2)
    return {"year": year, "month": month, "items": rows,
            "subtotals": sorted(subtotal_by_product.values(), key=lambda s: s["product_name"]),
            "total": {"batch_count": total_batch_count, "v_dich": total_v_dich}}


def _tank_name_sort_key(tank_lm: str) -> tuple:
    """Sắp xếp tự nhiên theo tên tank (B01..B31 theo đúng thứ tự SỐ, không phải chuỗi — rồi tới
    các tank chữ khác như T05-LM/T06-LM) — mirror cách đã làm ở file Excel báo cáo tank lên men
    (yêu cầu người dùng 2026-11-12: "sắp xếp tank theo thứ tự cho tôi")."""
    m = _TANK_NAME_RE.match(tank_lm or "")
    if m:
        prefix, num, rest = m.groups()
        return (prefix, int(num), rest)
    return (tank_lm or "", 0, "")


def tank_rotation_report(db: Session, date_from_str: str = None, date_to_str: str = None) -> dict:
    """BC "Tank lên men" (quay vòng) — yêu cầu người dùng 2026-11-12: "Làm cho tôi 1 báo cáo về
    tank lên men như file excel bạn làm, tank lên men thể hiện cả dung tích nhé", tiếp nối hội
    thoại tính tay trước đó (xem services/dashboard.py::VN_OFFSET note, batch_pipeline.py::
    WHIRLPOOL_TRANSFER_MINUTES — "Ngày vào dịch" đã trừ 78 phút đúng công thức mới).

    Tái dùng batch_pipeline_svc.list_tanks_out() (ĐÃ tính đúng vao_dich_start/vao_dich_end qua
    _tank_out(), không tính lại) — đây là TOÀN BỘ lịch sử BatchTank (mọi năm, mọi lượt vào dịch
    của mọi tank vật lý), không chỉ tank đang hoạt động.

    - "current": 1 dòng/tank vật lý (tank_lm) — lượt vào dịch GẦN NHẤT (= tank "hiện có", mirror
      file Excel sheet "Danh sách tank"), kèm Dung tích (ProductionLine.volume, Danh mục "Tank
      lên men", kind="tank") + Dung tích khả dụng (volume * usable_pct/100, mirror
      batch_pipeline.usable_capacity_for_code) + "last_cycle_days" (số ngày quay vòng LẦN GẦN
      NHẤT dẫn tới lượt vào dịch này — None nếu đây là lượt đầu tiên của tank trong lịch sử).
    - "history": TOÀN BỘ lượt vào dịch (mọi tank, mọi năm), mỗi dòng kèm "turnover_days" (số
      ngày tới lượt vào dịch KẾ TIẾP của CÙNG tank — None nếu là lượt mới nhất, chưa có lượt sau).
    - "tank_summaries": 1 dòng/tank — số lượt vào dịch, số lần quay vòng ĐÃ HOÀN CHỈNH (= số lượt
      - 1, trừ phi tank mới chỉ có 1 lượt), TB/nhỏ nhất/lớn nhất mỗi lần, kèm danh sách đủ các
      lần (để FE tự ghép chuỗi hiển thị như cột "Chi tiết từng lần" ở file Excel).
    - "cycles": 1 dòng/LẦN QUAY VÒNG (không phải 1 dòng/lượt vào dịch) — từ lượt này sang lượt kế
      tiếp của cùng tank, kèm số ngày.
    - "summary": thống kê toàn nhà máy (số lượt quay vòng, TB/trung vị/nhỏ nhất/lớn nhất) — None
      nếu chưa có lượt quay vòng hoàn chỉnh nào.

    `date_from_str`/`date_to_str` ("yyyy-mm-dd", hiểu là ngày giờ VN, TRỌN ngày date_to_str — mốc
    loại trừ = đầu ngày VN kế tiếp, mirror dashboard.py::filter_production_report) — LỌC theo
    "Ngày vào dịch" (vao_dich_start) — yêu cầu người dùng 2026-11-12: "Thêm lọc cho tank lên men
    từ ngày đến ngày". Quan trọng: turnover_days/last_cycle_days vẫn tính trên TOÀN BỘ chuỗi lịch
    sử THẬT (không lọc trước khi tính) — lọc CHỈ áp dụng vào bước cuối (chọn hiện dòng/lần quay
    vòng nào), để khoảng cách quay vòng luôn đúng dù lượt "kế tiếp" nằm NGOÀI kỳ đã chọn.
    - "current": với mỗi tank, chỉ xét các lượt vào dịch RƠI TRONG KỲ — lấy lượt MỚI NHẤT trong
      số đó làm "hiện có theo kỳ" (tank không có lượt nào trong kỳ thì KHÔNG xuất hiện).
    - "history": chỉ các lượt có vao_dich_start rơi trong kỳ.
    - "cycles": chỉ các lần quay vòng mà lượt BẮT ĐẦU (from) rơi trong kỳ.
    - "tank_summaries": tính lại TB/nhỏ nhất/lớn nhất CHỈ trên các lần quay vòng đã lọc ở trên."""
    all_tanks = batch_pipeline_svc.list_tanks_out(db)
    capacities = {
        l.code: {"volume": l.volume, "volume_uom": l.volume_uom, "usable_pct": l.usable_pct}
        for l in db.execute(select(ProductionLine).where(ProductionLine.kind == "tank")).scalars().all()
    }

    window_start = window_end = None
    if date_from_str and date_to_str:
        window_start = _vn_day_bounds_utc(date.fromisoformat(date_from_str))[0]
        window_end = _vn_day_bounds_utc(date.fromisoformat(date_to_str) + timedelta(days=1))[0]

    def _in_window(dt) -> bool:
        if window_start is None:
            return True
        return dt is not None and window_start <= dt < window_end

    # Nhóm theo tank_lm (tên tank vật lý, free-text) để tính quay vòng — NHƯNG tank_lm có thể bỏ
    # trống (NULL, không gán tank vật lý lúc tạo) — nếu gộp chung mọi dòng NULL vào 1 "nhóm" sẽ
    # tính nhầm quay vòng giữa các tank KHÁC NHAU chỉ vì cùng thiếu tên (bug phát hiện khi test
    # trên dev DB thật 2026-11-12: 1 dòng tank_lm=None lẫn vào nhóm khác). Mỗi dòng tank_lm=None
    # tự đứng 1 nhóm riêng (dùng tank_id làm khoá nhóm, KHÔNG hiện ra ngoài) — vẫn hiện đủ trong
    # "current"/"history", chỉ không tính được quay vòng (occurrences=1, đúng bản chất — không có
    # tên tank vật lý để biết nó có "quay lại" tank nào hay không).
    by_tank: dict[str, list[dict]] = {}
    for t in all_tanks:
        group_key = t["tank_lm"] if t["tank_lm"] else f"\0{t['tank_id']}"
        by_tank.setdefault(group_key, []).append(t)
    for arr in by_tank.values():
        arr.sort(key=lambda t: t["vao_dich_start"] or _MIN_DT)
        for i, t in enumerate(arr):
            if i + 1 < len(arr) and arr[i + 1]["vao_dich_start"] and t["vao_dich_start"]:
                delta_days = (arr[i + 1]["vao_dich_start"] - t["vao_dich_start"]).total_seconds() / 86400
                t["turnover_days"] = round(delta_days, 2)
            else:
                t["turnover_days"] = None
        for i, t in enumerate(arr):
            t["last_cycle_days"] = arr[i - 1]["turnover_days"] if i > 0 else None

    current_rows = []
    tank_summaries = []
    cycles = []
    for group_key in sorted(by_tank, key=_tank_name_sort_key):
        arr = by_tank[group_key]
        tank_lm = arr[0]["tank_lm"]   # hiện tên THẬT (có thể None) — group_key chỉ dùng nội bộ
        arr_in_window = [t for t in arr if _in_window(t["vao_dich_start"])]
        if not arr_in_window:
            continue   # tank nay khong co luot vao dich nao roi vao ky da chon -> bo qua het
        cap = capacities.get(tank_lm)
        usable_cap = None
        if cap and cap["volume"] is not None and cap["usable_pct"] is not None:
            usable_cap = round(cap["volume"] * cap["usable_pct"] / 100, 1)
        cur = arr_in_window[-1]   # "hiện có" THEO ĐÚNG kỳ đã chọn (không phải luôn là lượt mới nhất toàn thời gian)
        current_rows.append({
            "tank_lm": tank_lm,
            "capacity_hl": cap["volume"] if cap else None,
            "capacity_usable_hl": usable_cap,
            "capacity_usable_pct": cap["usable_pct"] if cap else None,
            "tank_code": cur["tank_code"], "tank_year": cur["tank_year"],
            "product_name": cur["product_name"], "beer_type_name": cur["beer_type_name"],
            "status": cur["status"], "status_label": cur["status_label"],
            "on_hand": cur["on_hand"], "volume_hl": cur["volume_hl"],
            "vao_dich_start": cur["vao_dich_start"], "vao_dich_end": cur["vao_dich_end"],
            "days_elapsed": cur["days_elapsed"], "ready_date": cur["ready_date"],
            "last_cycle_days": cur["last_cycle_days"],
            "quality_status": cur["quality_status"],
            "has_len_men_chinh_result": cur["has_len_men_chinh_result"],
            "has_len_men_phu_result": cur["has_len_men_phu_result"],
            "qc_fail_count": cur["qc_fail_count"],
        })
        tank_cycles = [t["turnover_days"] for t in arr_in_window if t["turnover_days"] is not None]
        tank_summaries.append({
            "tank_lm": tank_lm, "occurrences": len(arr_in_window), "cycle_count": len(tank_cycles),
            "avg_days": round(sum(tank_cycles) / len(tank_cycles), 2) if tank_cycles else None,
            "min_days": min(tank_cycles) if tank_cycles else None,
            "max_days": max(tank_cycles) if tank_cycles else None,
            "cycles": tank_cycles,
        })
        cycle_no = 0
        for t in arr_in_window:
            if t["turnover_days"] is None:
                continue
            cycle_no += 1
            nxt = arr[arr.index(t) + 1]   # mẻ "kế tiếp" trong CHUỖI ĐẦY ĐỦ — có thể nằm NGOÀI kỳ
            cycles.append({
                "tank_lm": tank_lm, "cycle_no": cycle_no,
                "from_tank_code": t["tank_code"], "from_vao_dich": t["vao_dich_start"],
                "to_tank_code": nxt["tank_code"], "to_vao_dich": nxt["vao_dich_start"],
                "days": t["turnover_days"],
            })

    history_rows = sorted(
        [t for t in all_tanks if _in_window(t["vao_dich_start"])],
        key=lambda t: t["vao_dich_start"] or _MIN_DT, reverse=True)

    all_cycle_days = [c["days"] for c in cycles]
    summary = None
    if all_cycle_days:
        summary = {
            "count": len(all_cycle_days),
            "avg": round(sum(all_cycle_days) / len(all_cycle_days), 2),
            "median": round(statistics.median(all_cycle_days), 2),
            "min": min(all_cycle_days), "max": max(all_cycle_days),
        }

    return {
        "current": current_rows, "history": history_rows,
        "tank_summaries": tank_summaries, "cycles": cycles, "summary": summary,
    }
