"""Tổng hợp số liệu cho Tổng quan (dashboard): lệnh nấu/lọc, mẻ nấu/lọc/chiết (thực thi
thật, không phải trạng thái ERP). Sản lượng chiết lon theo ngày+ca hiển thị trên
dashboard lấy trực tiếp từ báo cáo SCADA thật (services/filling_external.py) — không
tính lại ở đây."""
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import false, select, true
from sqlalchemy.orm import Session

from ..common import DeviationState, LotStatus, QualityStatus, ResultStatus, utcnow
from ..models.batches import BatchExecution
from ..models.batch_pipeline import (
    BatchFilterLot,
    BatchFilterLotBatch,
    BatchFilterLotBatchDraw,
    BatchFilterLotSource,
    BatchPackLot,
    BatchTank,
)
from ..models.lines import ProductionLine
from ..models.master import BeerType, FinishedProduct, Material, Product
from ..models.materials import MaterialLot
from ..models.quality import Deviation, QualityResult
from ..models.quality_ext import CAPA, QCParameter
from . import batch_pipeline as batch_pipeline_svc
from . import brew_order as brew_order_svc
from . import quality as quality_svc
from .filter_yield_report import LABEL as _YIELD_LABEL
from .filter_yield_report import classify_yield_l

# UI luôn hiển thị giờ theo múi VN (frontend fmt() dùng toLocaleString mặc định trình
# duyệt, Asia/Ho_Chi_Minh = UTC+7) — quy đổi trước khi lấy .date() để "hôm nay" ở dashboard
# khớp với ngày người dùng nhìn thấy trên các bảng khác, tránh lệch ngày quanh mốc
# 17h-24h UTC (0h-7h giờ VN).
VN_OFFSET = timedelta(hours=7)


def _local_date(dt):
    return (dt + VN_OFFSET).date() if dt else None


def _order_counts(items: list, complete_key: str, executed_key: str) -> dict:
    total = len(items)
    complete = sum(1 for i in items if i[complete_key])
    executing = sum(1 for i in items if not i[complete_key] and i[executed_key])
    return {"total": total, "hoan_thanh": complete, "dang_thuc_hien": executing,
            "chua_thuc_hien": total - complete - executing}


def _batch_counts(rows: list, ended_attr: str = "ended_at") -> dict:
    """`ended_attr` cho phép mirror mốc "đã kết thúc" khác tên tuỳ model (BatchExecution dùng
    `end_at`, BatchFilterLotBatch dùng `ended_at`, BatchPackLot không có mốc kết thúc riêng nên
    dùng tạm `approved_at` — chỉ có giá trị khi KCS đã duyệt, cùng ý nghĩa "coi như xong việc",
    xem production_summary)."""
    total = len(rows)
    today = _local_date(utcnow())
    ended = lambda r: getattr(r, ended_attr, None)
    done = sum(1 for r in rows if ended(r) is not None)
    done_today = sum(1 for r in rows if ended(r) is not None and _local_date(ended(r)) == today)
    return {"total": total, "dang_thuc_hien": total - done, "hoan_thanh": done, "hoan_thanh_hom_nay": done_today}


def _batch_tank_len_men_counts(db: Session) -> dict:
    """"Tank đang lên men" trên Dashboard — CHỈ tính tank còn ĐÚNG NGHĨA đang lên men (status
    "len_men" hoặc "cho_loc", xem services/batch_pipeline.py::_tank_status) — KHÁC
    available_tank_lines (dùng cho picker chọn tank gộp mẻ mới, "chiếm dụng" ở đó = còn tồn
    khác 0 bất kể đã lọc hay chưa, mục đích khác hẳn: không cho dùng lại tank chưa dọn sạch).
    Tank đã "loc_1_phan"/"da_loc_het"/"am" (đã bị rút dịch, dù còn tồn dở) đã CHUYỂN sang công
    đoạn Lọc rồi, không còn tính là "đang lên men" nữa (yêu cầu người dùng 2026-09-02: "tank
    đang lọc mà lại vẫn hiển thị đang lên men"). `dang_loc` (yêu cầu người dùng 2026-09-02: ghi
    chú thêm "số tank đang lọc") đếm riêng tank "loc_1_phan" (đang rút dịch dở dang) — KHÁC
    "trống" thật sự (đã rút hết/am, hoặc chưa từng gộp mẻ nào). `dang_nap` đếm tank status
    "dang_nau" (ÍT NHẤT 1 mẻ đã gộp vào THẬT SỰ bắt đầu nấu — running/held/completed/closed —
    nhưng CHƯA kết thúc hết cả tank, xem services/batch_pipeline.py::_tank_status dòng
    "dang_nau") — TRƯỚC ĐÂY hardcode = 0 dựa trên tiền đề sai (tưởng không có trạng thái "đang
    nạp dở dang" nào), khiến tank đang thật sự bị chiếm dụng bị đếm nhầm vào "trống" (audit
    2026-09-06, người dùng phát hiện qua dashboard thật). `dat_cho` (yêu cầu người dùng
    2026-09-06: "nếu 1 trong các mẻ sản xuất nấu ít nhất là running/Completed/closed thì được
    coi là đang điền dịch, nếu không đều ở trạng thái Planned") đếm riêng tank ĐÃ gộp mẻ nhưng
    TẤT CẢ mẻ còn "planned"/"ready" (chưa mẻ nào thật sự chạy) — tank đã bị "đặt chỗ" (không cho
    mẻ khác gộp vào nữa, xem _tank_lm_occupied) nhưng CHƯA có dịch nào chảy vào, khác cả "đang
    điền dịch" lẫn "trống" thật sự."""
    lines = db.execute(select(ProductionLine).where(
        ProductionLine.kind == "tank", ProductionLine.active == true())).scalars().all()
    tanks_by_code: dict[str, str] = {}
    for t in batch_pipeline_svc.list_tanks_out(db):
        if t["tank_lm"]:
            tanks_by_code[t["tank_lm"]] = t["status"]
    total = len(lines)
    dang_su_dung = sum(1 for l in lines if tanks_by_code.get(l.code) in ("len_men", "cho_loc"))
    dang_loc = sum(1 for l in lines if tanks_by_code.get(l.code) == "loc_1_phan")
    dang_nap = sum(1 for l in lines if tanks_by_code.get(l.code) == "dang_nau")
    dat_cho = sum(1 for l in lines if tanks_by_code.get(l.code) == "planned")
    return {"total": total, "dang_su_dung": dang_su_dung, "dang_loc": dang_loc, "dang_nap": dang_nap,
            "dat_cho": dat_cho, "trong": total - dang_su_dung - dang_loc - dang_nap - dat_cho}


def production_summary(db: Session) -> dict:
    """Lệnh & mẻ sản xuất (yêu cầu người dùng 2026-09-02: toàn bộ 6 thẻ đổi sang lấy dữ liệu từ
    pipeline "Mẻ sản xuất" MỚI, không còn từ module Nấu-Lọc-Chiết cũ — TRỪ "Lệnh nấu" (BrewOrder)
    vốn đã là lớp ERP DÙNG CHUNG cho cả 2 pipeline (WorkOrder/BatchExecution mới VÀ BrewRecord/
    BrewBatch cũ đều có thể tạo dưới 1 BrewOrder), không phải "dữ liệu module cũ" cần thay).
    "Mẻ nấu"/"Mẻ lọc"/"Mẻ chiết" đều hiện TỔNG SỐ (cộng dồn cả lịch sử, không chỉ phần đang làm
    dở — yêu cầu người dùng 2026-09-02: "hiển thị tất cả số lượng ra, bên dưới có ghi chú rồi"),
    kèm ghi chú hoàn thành/đang thực hiện/chưa thực hiện ngay dưới số tổng (xem _batch_counts).
    Riêng "Tank đang lên men" (_batch_tank_len_men_counts) vẫn CHỈ tính tank còn đúng nghĩa đang
    lên men — khác hẳn ý nghĩa "tổng số mẻ", vì 1 tank vật lý chỉ có thể ở ĐÚNG 1 trạng thái tại
    1 thời điểm (không có "lịch sử" để cộng dồn như mẻ nấu/lọc/chiết)."""
    brew_orders = brew_order_svc.list_orders(db)
    filter_orders = batch_pipeline_svc.list_filter_orders(db)
    batches = db.execute(select(BatchExecution)).scalars().all()
    filter_lot_batches = db.execute(select(BatchFilterLotBatch)).scalars().all()
    pack_lots = db.execute(select(BatchPackLot)).scalars().all()
    return {
        "lenh_nau": _order_counts(brew_orders, "is_complete", "is_executed"),
        "lenh_loc": _order_counts(
            [{"is_complete": o["is_complete"], "is_executed": o["status"] != "planned"} for o in filter_orders],
            "is_complete", "is_executed"),
        "me_nau": _batch_counts(batches, ended_attr="end_at"),
        "me_loc": _batch_counts(filter_lot_batches, ended_attr="ended_at"),
        "me_chiet": _batch_counts(pack_lots, ended_attr="approved_at"),
        "tank_len_men": _batch_tank_len_men_counts(db),
    }


# Nhãn hiển thị + thuộc tính chứa mã người-đọc-được cho từng loại phạm vi (scope_type) mà
# Deviation/QualityResult dùng — mirror app.js::holdScopeLabel (VIEWS.quality Hold/Release)
# để "Lô/Phạm vi" trên Dashboard hiện đúng mã thay vì UUID scope_id thô.
_SCOPE_MODELS = {"lot": MaterialLot, "batch": BatchExecution}
_SCOPE_CODE_ATTR = {"lot": "lot_code", "batch": "batch_code"}
_SCOPE_LABEL_PREFIX = {"lot": "Lô NVL", "batch": "Mẻ SX"}
_SCOPE_ID_ATTR: dict[str, str] = {}


def _scope_code(db: Session, scope_type: str, scope_id: str) -> str | None:
    model = _SCOPE_MODELS.get(scope_type)
    obj = db.get(model, scope_id) if model else None
    return getattr(obj, _SCOPE_CODE_ATTR[scope_type], None) if obj else None


def _scope_label(scope_type: str, scope_code: str | None, scope_id: str) -> str:
    return f"{_SCOPE_LABEL_PREFIX.get(scope_type, scope_type)} {scope_code or scope_id}"


# Dành cho scope_type có "lô cha" (chỉ có nghĩa với scope="lot" hiện tại không cần) — thay cho
# cột "Vật tư"/"SL" trên Dashboard vốn luôn rỗng với các scope_type không phải "lot". Không còn
# scope_type nào cần nhãn lô cha kể từ khi module Nấu-Lọc-Chiết cũ (brew_batch/filter/bottle)
# bị xóa — giữ lại hàm (no-op) làm điểm mở rộng nếu sau này cần cho scope_type mới.
def _parent_label(db: Session, scope_type: str, obj) -> str | None:
    return None


def qc_attention_alerts(db: Session) -> dict:
    """Cảnh báo QC cho Dashboard: gộp lô đang giữ (MaterialLot.status=on_hold) và mọi scope
    đang có deviation MỞ (state != closed) thành 1 danh sách duy nhất — 1 lô vừa hold vừa có
    deviation mở chỉ xuất hiện 1 dòng (key theo scope_type:scope_id), kèm số chỉ tiêu QC đang
    FAIL (giá trị mới nhất/chỉ tiêu, dùng chung logic với _assert_releasable) để biết mức độ
    nghiêm trọng. Không còn gộp CAPA/hiệu chuẩn — 2 loại đó đã có trang riêng (QC Lab, Bảo
    trì/Kiểm định), không thuộc phạm vi "chất lượng lô hàng đang xử lý"."""
    mat_by_id = {m.material_id: m for m in db.execute(select(Material)).scalars().all()}
    items: dict[str, dict] = {}

    hold_lots = db.execute(select(MaterialLot).where(
        MaterialLot.status == LotStatus.ON_HOLD.value, MaterialLot.quantity > 0)).scalars().all()
    for l in hold_lots:
        key = f"lot:{l.lot_id}"
        items[key] = {"scope_type": "lot", "scope_id": l.lot_id, "lot_code": l.lot_code,
                      "scope_code": l.lot_code, "scope_label": _scope_label("lot", l.lot_code, l.lot_id),
                      "material_code": mat_by_id[l.material_id].code if l.material_id in mat_by_id else None,
                      "material_name": mat_by_id[l.material_id].name if l.material_id in mat_by_id else None,
                      "quantity": l.quantity, "uom": l.uom, "parent_label": None, "reasons": ["on_hold"],
                      "deviation_count": 0, "opened_at": None}

    # Mẻ/lô công đoạn bị hold trực tiếp qua quality_status (services/quality.py::
    # set_hold/_cascade_hold_siblings) — không có deviation mở kèm theo thì trước đây KHÔNG bao
    # giờ lộ ra ở đây (chỉ suy luận "on_hold" gián tiếp qua deviation trùng scope), khiến
    # Dashboard "Hold/Release" bỏ sót các hold loại này dù Lịch sử Hold/Release đã ghi nhận
    # đúng. _SCOPE_ID_ATTR hiện rỗng (module Nấu-Lọc-Chiết cũ — scope duy nhất từng cần vòng
    # lặp này — đã bị xóa) nên vòng lặp dưới đây không còn chạy; giữ lại làm điểm mở rộng nếu
    # sau này pipeline "Mẻ sản xuất" cần liệt kê hold trực tiếp tương tự.
    for scope_type, attr in _SCOPE_ID_ATTR.items():
        model = _SCOPE_MODELS[scope_type]
        rows = db.execute(select(model).where(
            model.quality_status == QualityStatus.ON_HOLD.value)).scalars().all()
        for obj in rows:
            scope_id = getattr(obj, attr)
            key = f"{scope_type}:{scope_id}"
            if key not in items:
                code = _scope_code(db, scope_type, scope_id)
                items[key] = {"scope_type": scope_type, "scope_id": scope_id, "lot_code": None,
                              "scope_code": code, "scope_label": _scope_label(scope_type, code, scope_id),
                              "material_code": None, "quantity": None, "uom": None,
                              "parent_label": _parent_label(db, scope_type, obj),
                              "reasons": [], "deviation_count": 0, "opened_at": None}
            if "on_hold" not in items[key]["reasons"]:
                items[key]["reasons"].append("on_hold")

    open_devs = db.execute(select(Deviation).where(
        Deviation.state != DeviationState.CLOSED.value)).scalars().all()
    dev_counts: dict[str, int] = {}
    dev_earliest: dict[str, object] = {}
    for d in open_devs:
        key = f"{d.scope_type}:{d.scope_id}"
        dev_counts[key] = dev_counts.get(key, 0) + 1
        if key not in dev_earliest or d.opened_at < dev_earliest[key]:
            dev_earliest[key] = d.opened_at
        if key not in items:
            lot = db.get(MaterialLot, d.scope_id) if d.scope_type == "lot" else None
            model = _SCOPE_MODELS.get(d.scope_type)
            obj = lot or (db.get(model, d.scope_id) if model else None)
            code = lot.lot_code if lot else _scope_code(db, d.scope_type, d.scope_id)
            items[key] = {"scope_type": d.scope_type, "scope_id": d.scope_id,
                          "lot_code": lot.lot_code if lot else None,
                          "scope_code": code, "scope_label": _scope_label(d.scope_type, code, d.scope_id),
                          "material_code": (mat_by_id[lot.material_id].code
                                           if lot and lot.material_id in mat_by_id else None),
                          "material_name": (mat_by_id[lot.material_id].name
                                           if lot and lot.material_id in mat_by_id else None),
                          "quantity": lot.quantity if lot else None, "uom": lot.uom if lot else None,
                          "parent_label": _parent_label(db, d.scope_type, obj) if obj and d.scope_type != "lot" else None,
                          "reasons": [], "deviation_count": 0, "opened_at": None}
        items[key]["reasons"].append("deviation")
        items[key]["deviation_count"] = dev_counts[key]
        items[key]["opened_at"] = dev_earliest[key]

    # Lô NVL đã được duyệt (RELEASED) dù còn chỉ tiêu FAIL — từ 2026-08-01 duyệt NVL không còn
    # bị chặn bởi FAIL (xem quality.py::_assert_releasable) nên các lô này rời khỏi on_hold, và
    # NVL không dùng luồng deviation (xem comment ở _assert_releasable) nên cũng không có Deviation
    # mở kèm theo — 2 khối trên vì vậy bỏ sót các lô này dù vẫn còn chỉ tiêu FAIL cần chú ý.
    fail_lot_ids = db.execute(
        select(QualityResult.scope_id).where(QualityResult.scope_type == "lot").distinct()
    ).scalars().all()
    for lot_id in fail_lot_ids:
        key = f"lot:{lot_id}"
        if key in items:
            continue
        lot = db.get(MaterialLot, lot_id)
        if not lot or lot.quantity <= 0:
            continue
        latest_by_param = quality_svc.latest_results_by_param(db, "lot", lot_id)
        if not any(r.status == ResultStatus.FAIL.value for r in latest_by_param.values()):
            continue
        items[key] = {"scope_type": "lot", "scope_id": lot_id, "lot_code": lot.lot_code,
                      "scope_code": lot.lot_code, "scope_label": _scope_label("lot", lot.lot_code, lot_id),
                      "material_code": mat_by_id[lot.material_id].code if lot.material_id in mat_by_id else None,
                      "material_name": mat_by_id[lot.material_id].name if lot.material_id in mat_by_id else None,
                      "quantity": lot.quantity, "uom": lot.uom, "parent_label": None,
                      "reasons": ["qc_fail"], "deviation_count": 0, "opened_at": None}

    param_name_by_code = {p.code: p.name for p in db.execute(select(QCParameter)).scalars().all()}
    for key, item in items.items():
        scope_type, scope_id = key.split(":", 1)
        latest_by_param = quality_svc.latest_results_by_param(db, scope_type, scope_id)
        fail_results = [r for r in latest_by_param.values() if r.status == ResultStatus.FAIL.value]
        item["fail_param_count"] = len(fail_results)
        # Tên chỉ tiêu đang fail (không chỉ đếm số lượng) — để Dashboard hiện ngay "Độ đục,
        # Plato" thay vì phải bấm vào mới biết cụ thể chỉ tiêu nào đang fail.
        item["fail_params"] = [param_name_by_code.get(r.parameter, r.parameter) for r in fail_results]

    out = sorted(items.values(), key=lambda i: (i["opened_at"] is None, i["opened_at"]))
    return {"items": out, "total": len(out)}


def _batch_filter_lot_yield_items(db: Session, date_from, date_to, low_l: float, high_l: float) -> list[dict]:
    """Mirror filter_yield_report.filter_line_yield_report (module Nấu-Lọc-Chiết cũ, theo
    FilterOrderTank) nhưng cho pipeline "Mẻ sản xuất" mới — BatchFilterLotBatch (1 mẻ lọc/lần
    chạy máy) tự là đơn vị atomic trong PHẠM VI 1 lô lọc (không bị tách ghi nhận qua nhiều
    FilterRecord như module cũ). NHƯNG 1 mẻ nấu lớn có thể phải lọc qua NHIỀU lô lọc/tank khác
    nhau mới hết (mỗi lô lọc tự gõ trùng "Mẻ lọc số" — batch_seq_no — để đánh dấu cùng 1 mẻ) —
    "V lọc" thật của mẻ đó là TỔNG của mọi lô lọc cùng batch_seq_no, CỘNG DỒN bất kể khác lô
    lọc/lệnh lọc/tank nguồn (yêu cầu người dùng 2026-09-30, ví dụ thực tế: mẻ 42 tách ra 4 lô lọc
    T11.1378/T12.1376/T1.1375/T2.1374, tổng thật = 113.200 lít chứ không phải 4 dòng riêng lẻ
    20.900/32.500/20.000/39.800). batch_seq_no rỗng (không gõ) không nhóm được với gì -> giữ
    riêng theo từng batch_link_id như cũ.

    Vì 1 nhóm có thể có phần tử kết thúc ở NHIỀU thời điểm khác nhau, lọc theo kỳ [date_from,
    date_to) dựa trên `ended_at` CUỐI CÙNG của nhóm (mẻ chỉ tính "xong" khi phần cuối cùng xong)
    — nên phải nạp TOÀN BỘ batch đã kết thúc (không lọc theo kỳ ngay từ đầu) để không bỏ sót
    phần tử cùng nhóm kết thúc trước `date_from`.

    "Mẻ cuối" (is_final_batch, mẻ vét) chỉ loại nhóm khỏi phân loại khi MỌI phần tử trong nhóm
    đều là mẻ vét — nếu nhóm có ít nhất 1 phần KHÔNG vét, tổng cả nhóm là sản lượng thật của cả
    mẻ (không còn là "vét" nữa) nên vẫn phân loại bình thường theo tổng."""
    all_batches = db.execute(
        select(BatchFilterLotBatch).where(BatchFilterLotBatch.ended_at.is_not(None))
    ).scalars().all()
    batch_ids = [b.batch_link_id for b in all_batches]
    draws = db.execute(select(BatchFilterLotBatchDraw).where(
        BatchFilterLotBatchDraw.batch_link_id.in_(batch_ids))).scalars().all() if batch_ids else []
    draw_hl_by_batch: dict[str, float] = {}
    for d in draws:
        draw_hl_by_batch[d.batch_link_id] = draw_hl_by_batch.get(d.batch_link_id, 0.0) + (d.dich_nha_hl or 0.0)
    filter_lot_ids = {b.filter_lot_id for b in all_batches}
    filter_lots_by_id = {fl.filter_lot_id: fl for fl in db.execute(
        select(BatchFilterLot).where(BatchFilterLot.filter_lot_id.in_(filter_lot_ids))).scalars().all()} if filter_lot_ids else {}
    from ..models.master import BeerType
    beer_type_ids = {fl.beer_type_id for fl in filter_lots_by_id.values() if fl.beer_type_id}
    beer_types_by_id = {bt.beer_type_id: bt for bt in db.execute(
        select(BeerType).where(BeerType.beer_type_id.in_(beer_type_ids))).scalars().all()} if beer_type_ids else {}

    groups: dict[tuple, list[BatchFilterLotBatch]] = {}
    for b in all_batches:
        key = ("seq", b.batch_seq_no) if b.batch_seq_no else ("solo", b.batch_link_id)
        groups.setdefault(key, []).append(b)

    items = []
    for members in groups.values():
        last_ended = max(m.ended_at for m in members)
        if not (date_from <= last_ended < date_to):
            continue
        v_dich_l = sum(draw_hl_by_batch.get(m.batch_link_id, 0.0) for m in members) * 100
        v_daw_l = sum((m.nuoc_bai_khi_hl or 0.0) for m in members) * 100
        v_l = v_dich_l + v_daw_l
        # "Mẻ cuối" (mẻ vét) của cả NHÓM: CHỈ CẦN 1 lô lọc/mẻ con trong nhóm được đánh dấu là đủ
        # (OR, không phải AND như trước) — yêu cầu người dùng 2026-10-02: "nếu 1 trong các lô lọc
        # của mẻ lọc đó có tích mẻ cuối, thì cả mẻ lọc đó được coi là mẻ cuối". Phân loại
        # Thấp/Bình thường/Cao giờ LUÔN tính theo ngưỡng thật (không còn "cuoi" đè lên, loại khỏi
        # so sánh như trước) — mẻ cuối hay không vẫn so với ngưỡng bình thường để tô màu đỏ/xanh
        # trên "BC hệ lọc" (yêu cầu người dùng: "so sánh với cài đặt này, nếu ở mức thấp thì sẽ
        # màu đỏ, ở mức cao thì sẽ màu xanh, còn nếu mức bình thường thì màu bình thường"). Dashboard
        # "Sản lượng lọc thấp" (low_yield_filter_alerts) tự loại riêng is_final=True khỏi cảnh báo
        # (mẻ vét thấp là chuyện bình thường, không phải cảnh báo hiệu suất).
        is_final = any(m.is_final_batch for m in members)
        cls = classify_yield_l(v_l, low_l, high_l)
        lot_codes = sorted({filter_lots_by_id[m.filter_lot_id].filter_lot_code
                            for m in members if filter_lots_by_id.get(m.filter_lot_id)})
        fl0 = next((filter_lots_by_id.get(m.filter_lot_id) for m in members
                   if filter_lots_by_id.get(m.filter_lot_id)), None)
        bt0 = beer_types_by_id.get(fl0.beer_type_id) if fl0 and fl0.beer_type_id else None
        items.append({
            "batch_link_id": members[0].batch_link_id if len(members) == 1 else None,
            "batch_link_ids": [m.batch_link_id for m in members],
            "batch_seq_no": members[0].batch_seq_no,
            "filter_lot_id": fl0.filter_lot_id if fl0 else None,
            "filter_lot_code": ", ".join(lot_codes) if lot_codes else None,
            "lot_count": len(members),
            "beer_type": bt0.name if bt0 else None,
            "ended_at": last_ended.isoformat() if last_ended else None,
            "v_dich_l": round(v_dich_l, 1), "v_daw_l": round(v_daw_l, 1),
            "v_l": round(v_l, 1), "classification": cls, "classification_label": _YIELD_LABEL[cls],
            "is_final": is_final,
        })
    return items


def filter_production_report(db: Session, days: int = 3650) -> list[dict]:
    """Báo cáo hệ lọc (tab Báo cáo) — mỗi dòng = 1 MẺ LỌC, nhóm theo `batch_seq_no` qua NHIỀU lô
    lọc nếu có (reuse _batch_filter_lot_yield_items — yêu cầu người dùng 2026-10-01: "Tính theo
    mẻ lọc, ví dụ mẻ lọc 1 xuất hiện tại 2-3-4 lô lọc thì phải cộng dồn vào"). Mỗi dòng kèm:
    - `is_blend`: suy từ SỐ TANK LÊN MEN NGUỒN phân biệt của cả nhóm (> 1 = phối) — KHÔNG dùng
      BatchFilterOrder.blend_mode vì 1 mẻ lọc có thể gộp nhiều lô lọc thuộc nhiều lệnh lọc khác
      nhau, blend_mode của 1 lệnh đơn lẻ không còn đại diện đúng cho cả nhóm.
    - `is_final`: true khi ÍT NHẤT 1 lô lọc/mẻ con trong nhóm là "mẻ cuối" (mẻ vét,
      `BatchFilterLotBatch.is_final_batch`) — OR, không phải AND (yêu cầu người dùng 2026-10-02:
      "nếu 1 trong các lô lọc của mẻ lọc đó có tích mẻ cuối, thì cả mẻ lọc đó được coi là mẻ
      cuối").
    - `classification`/`classification_label`: Thấp/Bình thường/Cao theo ngưỡng thật
      (OpsSetting.filter_line_yield_low_l/high_l) — LUÔN tính, kể cả khi `is_final` — mẻ cuối
      không còn bị loại khỏi so sánh ở báo cáo này (khác `low_yield_filter_alerts`, nơi mẻ cuối
      vẫn bị loại khỏi cảnh báo "thấp" vì mẻ vét thấp là chuyện bình thường) — dùng để tô màu đỏ/
      xanh cột "Sản lượng lọc" (yêu cầu người dùng 2026-10-02).
    - `tanks`: tank lên men nguồn, mỗi tank kèm `tank_id`/`tank_lm`/`product_name` (Dịch bia CỦA
      RIÊNG tank đó, VD "B25" + "Sapphire 14oP") — frontend ghép thành nhãn "B25 — Sapphire 14oP"
      và dùng `tank_id` để bấm "truy ngược" xem lại chỉ tiêu CT chính/phụ (chỉ tiêu chất lượng
      TRƯỚC LỌC). Không còn cột "Dịch bia" riêng cho cả nhóm — gắn thẳng vào từng tank (yêu cầu
      người dùng 2026-10-02: "bỏ cột dịch bia, tại cột tank lên men, thêm loại dịch bia vào").
    - `bbt_list`: tank thành phẩm (BBT) đích, mỗi tank kèm `to_bbt`/`beer_type_name` (Loại bia CỦA
      RIÊNG lô lọc đổ vào tank đó) + `filter_lot_id` — frontend ghép thành nhãn "T01 — Sapphire"
      và dùng `filter_lot_id` để bấm xem "Chỉ tiêu Lọc" của lô lọc đó ngay tại báo cáo (yêu cầu
      người dùng 2026-10-02: "Tank thành phẩm cũng tương tự ... bổ sung thêm chỉ tiêu tank thành
      phẩm xem luôn ở màn hình này khi bấm vào").
    - `ended_at`: "Ngày lọc" = mốc kết thúc CUỐI CÙNG của cả nhóm (mirror hàm nguồn).
    - `v_l`: sản lượng lọc (lít), cộng dồn cả nhóm.
    - `beer_type_name`: gộp ĐỦ Loại bia đã gán thẳng trên TỪNG BatchFilterLot của cả nhóm (không
      chỉ 1 lô đại diện) — nếu KHÔNG lô nào trong nhóm có beer_type_id (dữ liệu cũ/thiếu) thì SUY
      từ Product.beer_type_id của tank nguồn thay vì bỏ trống (yêu cầu người dùng 2026-10-01:
      "chưa thấy dịch bia nào").
    Chỉ gồm mẻ lọc ĐÃ KẾT THÚC (mirror _batch_filter_lot_yield_items — "ngày lọc" vô nghĩa với mẻ
    chưa xong). `days` tính SERVER-SIDE từ utcnow() (mirror material_norm?days=N) — tránh nhận
    date_from/date_to thô từ client: _batch_filter_lot_yield_items so sánh datetime NGAY TRONG
    PYTHON (không phải ở tầng SQL), nên 1 datetime client gửi lên THIẾU tzinfo (naive) sẽ vỡ
    TypeError khi so với `ended_at` tz-aware đọc từ CSDL — 2026-10-01, audit báo cáo "Hệ lọc".
    Prefetch hàng loạt theo ID, không query trong vòng lặp."""
    from . import ops_setting as ops_setting_svc
    settings = ops_setting_svc.get_settings(db)
    date_to = utcnow()
    date_from = date_to - timedelta(days=days)
    base_items = _batch_filter_lot_yield_items(
        db, date_from, date_to, settings.filter_line_yield_low_l, settings.filter_line_yield_high_l)
    if not base_items:
        return []
    all_batch_ids = {bid for it in base_items for bid in it["batch_link_ids"]}
    batches_by_id = {b.batch_link_id: b for b in db.execute(
        select(BatchFilterLotBatch).where(BatchFilterLotBatch.batch_link_id.in_(all_batch_ids))).scalars().all()}
    filter_lot_ids = {b.filter_lot_id for b in batches_by_id.values()}
    filter_lots_by_id = {fl.filter_lot_id: fl for fl in db.execute(
        select(BatchFilterLot).where(BatchFilterLot.filter_lot_id.in_(filter_lot_ids))).scalars().all()}
    sources = db.execute(select(BatchFilterLotSource).where(
        BatchFilterLotSource.filter_lot_id.in_(filter_lot_ids))).scalars().all()
    sources_by_lot: dict[str, list] = {}
    for s in sources:
        sources_by_lot.setdefault(s.filter_lot_id, []).append(s)
    tank_ids = {s.source_tank_id for s in sources if s.source_type == "tank" and s.source_tank_id}
    tanks_by_id = {t.tank_id: t for t in db.execute(
        select(BatchTank).where(BatchTank.tank_id.in_(tank_ids))).scalars().all()} if tank_ids else {}
    # Dịch bia (Product) của tank nguồn — cũng dùng làm DỰ PHÒNG suy ra "Loại bia" khi bản thân
    # BatchFilterLot chưa gán beer_type_id (dữ liệu cũ/thiếu sót) — yêu cầu người dùng 2026-10-01:
    # "chưa thấy dịch bia nào".
    product_ids = {t.product_id for t in tanks_by_id.values() if t.product_id}
    products_by_id = {p.product_id: p for p in db.execute(
        select(Product).where(Product.product_id.in_(product_ids))).scalars().all()} if product_ids else {}
    fallback_beer_type_ids = {p.beer_type_id for p in products_by_id.values() if p.beer_type_id}
    # explicit_beer_type_ids: beer_type_id gán THẲNG trên TỪNG BatchFilterLot của cả nhóm (không
    # chỉ 1 lô đại diện như `it["beer_type"]` của _batch_filter_lot_yield_items) — cần để hiện
    # ĐỦ khi 1 mẻ lọc Phối gộp nhiều lô lọc có Loại bia khác nhau (xem giải thích ở dưới).
    explicit_beer_type_ids = {fl.beer_type_id for fl in filter_lots_by_id.values() if fl.beer_type_id}
    beer_types_by_id = {bt.beer_type_id: bt for bt in db.execute(
        select(BeerType).where(BeerType.beer_type_id.in_(fallback_beer_type_ids | explicit_beer_type_ids)))
        .scalars().all()} if (fallback_beer_type_ids or explicit_beer_type_ids) else {}

    rows = []
    for it in base_items:
        member_lot_ids = {batches_by_id[bid].filter_lot_id for bid in it["batch_link_ids"] if bid in batches_by_id}
        # tanks_in_group: tank nguồn (Lên men) kèm ĐÚNG Dịch bia của riêng tank đó — gắn thẳng
        # vào nhãn (VD "B25 — Sapphire 14oP") thay vì tách riêng 1 cột "Dịch bia" chung cho cả
        # nhóm (yêu cầu người dùng 2026-10-02: "bỏ cột dịch bia, ... thêm loại dịch bia vào" cột
        # Tank lên men). bbt_by_code: tank thành phẩm kèm ĐÚNG Loại bia của riêng lô lọc đổ vào
        # tank đó (không phải Loại bia gộp cả nhóm) + filter_lot_id để bấm xem "Chỉ tiêu Lọc"
        # ngay tại đây (yêu cầu: "Tank thành phẩm cũng tương tự ... bổ sung thêm chỉ tiêu tank
        # thành phẩm xem luôn ở màn hình này khi bấm vào").
        tanks_in_group: dict[str, dict] = {}
        bbt_by_code: dict[str, dict] = {}
        explicit_beer_type_names = set()
        fallback_beer_type_names = set()
        for lot_id in member_lot_ids:
            fl = filter_lots_by_id.get(lot_id)
            fl_explicit = set()
            if fl and fl.beer_type_id:
                bt = beer_types_by_id.get(fl.beer_type_id)
                if bt:
                    fl_explicit.add(bt.name)
                    explicit_beer_type_names.add(bt.name)
            fl_fallback = set()
            for s in sources_by_lot.get(lot_id, []):
                if s.source_type == "tank":
                    t = tanks_by_id.get(s.source_tank_id)
                    if t:
                        product = products_by_id.get(t.product_id)
                        tanks_in_group[t.tank_id] = {"tank_lm": t.tank_lm or t.tank_code,
                                                     "product_name": product.name if product else None}
                        if product and product.beer_type_id:
                            bt = beer_types_by_id.get(product.beer_type_id)
                            if bt:
                                fl_fallback.add(bt.name)
                                fallback_beer_type_names.add(bt.name)
            if fl and fl.to_bbt and fl.to_bbt not in bbt_by_code:
                fl_beer_type_name = ", ".join(sorted(fl_explicit)) or ", ".join(sorted(fl_fallback)) or None
                bbt_by_code[fl.to_bbt] = {"to_bbt": fl.to_bbt, "beer_type_name": fl_beer_type_name,
                                          "filter_lot_id": fl.filter_lot_id}
        # Mẻ lọc Phối có thể gộp nhiều lô lọc gán Loại bia KHÁC nhau (VD lọc chung Sapphire +
        # Legend) — trước đây chỉ lấy `it["beer_type"]` của 1 lô ĐẠI DIỆN (fl0 — xem
        # _batch_filter_lot_yield_items), bỏ sót Loại bia của các lô còn lại trong nhóm (yêu cầu
        # người dùng 2026-10-01: "nếu phối thì hiện ra cả 2 loại dịch"). Giờ gộp ĐỦ mọi Loại bia
        # đã gán thẳng trên TỪNG lô của cả nhóm; chỉ dùng tới fallback (suy từ Product của tank
        # nguồn) khi KHÔNG lô nào trong nhóm có beer_type_id.
        beer_type_name = ", ".join(sorted(explicit_beer_type_names)) or ", ".join(sorted(fallback_beer_type_names)) or None
        rows.append({
            "batch_seq_no": it["batch_seq_no"], "lot_count": it["lot_count"],
            "filter_lot_code": it["filter_lot_code"], "filter_lot_id": it["filter_lot_id"],
            "ended_at": it["ended_at"], "v_l": it["v_l"],
            "beer_type_name": beer_type_name,
            "is_blend": len(tanks_in_group) > 1,
            "is_final": it["is_final"],
            "classification": it["classification"], "classification_label": it["classification_label"],
            "tanks": [{"tank_id": tid, "tank_lm": v["tank_lm"], "product_name": v["product_name"]}
                     for tid, v in sorted(tanks_in_group.items(), key=lambda x: x[1]["tank_lm"] or "")],
            "bbt_list": [bbt_by_code[code] for code in sorted(bbt_by_code)],
        })
    rows.sort(key=lambda r: r["ended_at"] or "", reverse=True)
    return rows


def _fmt_vn_dt(iso_str: Optional[str]) -> str:
    """ISO UTC (từ filter_production_report) -> chuỗi hiển thị giờ Việt Nam (UTC+7, cố định —
    không có nhà máy nào ở múi giờ khác) dạng dd/mm/yyyy HH:MM, mirror fmt() ở frontend (vốn tự
    quy đổi theo giờ trình duyệt — ở đây quy đổi tay vì file Excel xuất ra không chạy JS)."""
    if not iso_str:
        return ""
    return (datetime.fromisoformat(iso_str) + VN_OFFSET).strftime("%d/%m/%Y %H:%M")


def export_filter_production_xlsx(db: Session, days: int = 3650) -> bytes:
    """Xuất báo cáo hệ lọc (filter_production_report) ra file .xlsx thật — mirror
    import_mapping.py::export_report (cùng dùng openpyxl, đã là dependency sẵn có, không cần
    thêm thư viện) — yêu cầu người dùng 2026-10-01: "thêm mục xuất ra file excel"."""
    from openpyxl import Workbook
    from openpyxl.styles import PatternFill
    import io

    rows = filter_production_report(db, days)
    wb = Workbook()
    ws = wb.active
    ws.title = "Hệ lọc"
    headers = ["Mẻ lọc số", "Lô lọc", "Kiểu", "Mẻ cuối", "Tank lên men", "Tank thành phẩm",
              "Ngày lọc", "Sản lượng lọc (lít)", "Loại bia"]
    ws.append(headers)
    # Tô màu cột "Sản lượng lọc" theo đúng phân loại Thấp/Cao (mirror màu đỏ/xanh trên web) — kể
    # cả dòng "Mẻ cuối" cũng tô theo phân loại thật, không loại trừ (yêu cầu người dùng 2026-10-02).
    fill_by_cls = {"thap": PatternFill("solid", fgColor="FFC7CE"), "cao": PatternFill("solid", fgColor="C6EFCE")}
    v_l_col = headers.index("Sản lượng lọc (lít)") + 1
    # Mỗi tank/BBT kèm thẳng Dịch bia/Loại bia của riêng nó (VD "B25 - Sapphire 14oP") — bỏ cột
    # "Dịch bia" chung cho cả nhóm (yêu cầu người dùng 2026-10-02: "bỏ cột dịch bia ... thêm loại
    # dịch bia vào" cột Tank lên men/Tank thành phẩm).
    tank_label = lambda t: f'{t["tank_lm"]} - {t["product_name"]}' if t["product_name"] else t["tank_lm"]
    bbt_label = lambda b: f'{b["to_bbt"]} - {b["beer_type_name"]}' if b["beer_type_name"] else b["to_bbt"]
    for r in rows:
        ws.append([
            r["batch_seq_no"] or "", r["filter_lot_code"] or "",
            "Phối" if r["is_blend"] else "Không phối",
            "Mẻ cuối" if r["is_final"] else "",
            ", ".join(tank_label(t) for t in r["tanks"] if t["tank_lm"]),
            ", ".join(bbt_label(b) for b in r["bbt_list"]), _fmt_vn_dt(r["ended_at"]), r["v_l"],
            r["beer_type_name"] or "",
        ])
        fill = fill_by_cls.get(r["classification"])
        if fill:
            ws.cell(row=ws.max_row, column=v_l_col).fill = fill
    for col_idx in range(1, len(headers) + 1):
        ws.column_dimensions[chr(64 + col_idx)].width = 18
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def low_yield_filter_alerts(db: Session, days: int = 5, limit: int = 5) -> dict:
    """Cảnh báo sản lượng lọc thấp cho Dashboard — pipeline "Mẻ sản xuất" mới (yêu cầu người
    dùng 2026-09-02: đổi nguồn từ module Nấu-Lọc-Chiết cũ sang BatchFilterLotBatch, tính toán
    tương tự y hệt cách cũ — xem _batch_filter_lot_yield_items). Trong N ngày gần nhất (mặc
    định 5, tính theo `ended_at` — thời điểm kết thúc mẻ lọc), chỉ giữ classification="thap" VÀ
    is_final=False (mẻ cuối/mẻ vét vốn dĩ thấp — không phải cảnh báo hiệu suất thật, xem
    _batch_filter_lot_yield_items), sắp theo V lọc thấp nhất lên trước (mẻ hụt sản lượng nặng
    nhất đáng chú ý nhất), giới hạn top N dòng — mirror qc_attention_alerts (widget cảnh báo gọn
    trên Dashboard)."""
    from . import ops_setting as ops_setting_svc
    settings = ops_setting_svc.get_settings(db)
    date_to = utcnow()
    date_from = date_to - timedelta(days=days)
    all_items = _batch_filter_lot_yield_items(
        db, date_from, date_to, settings.filter_line_yield_low_l, settings.filter_line_yield_high_l)
    low_items = sorted((it for it in all_items if it["classification"] == "thap" and not it["is_final"]),
                       key=lambda it: it["v_l"])
    return {"items": low_items[:limit], "total": len(low_items),
            "date_from": date_from.isoformat(), "date_to": date_to.isoformat(),
            "low_l": settings.filter_line_yield_low_l}


def overdue_action_alerts(db: Session) -> dict:
    """Cảnh báo Deviation/CAPA quá hạn xử lý cho Dashboard: gộp Deviation và CAPA đang mở
    (state != closed) có `due_date` đã qua thành 1 danh sách, sắp theo số ngày quá hạn giảm dần
    (nặng nhất lên đầu) — mirror qc_attention_alerts/low_yield_filter_alerts (widget cảnh báo
    gọn trên Dashboard). Deviation/CAPA chưa đặt due_date hoặc chưa quá hạn không xuất hiện."""
    today = _local_date(utcnow())
    items = []

    devs = db.execute(select(Deviation).where(
        Deviation.due_date.isnot(None), Deviation.state != DeviationState.CLOSED.value
    )).scalars().all()
    for d in devs:
        due = d.due_date.date() if hasattr(d.due_date, "date") else d.due_date
        if due >= today:
            continue
        items.append({
            "kind": "deviation", "code": d.deviation_code, "title": d.reason,
            "severity": d.severity, "state": d.state, "due_date": d.due_date,
            "days_overdue": (today - due).days, "opened_by": d.opened_by,
        })

    capas = db.execute(select(CAPA).where(
        CAPA.due_date.isnot(None), CAPA.state != "closed"
    )).scalars().all()
    for c in capas:
        due = c.due_date.date() if hasattr(c.due_date, "date") else c.due_date
        if due >= today:
            continue
        items.append({
            "kind": "capa", "code": c.capa_code, "title": c.title,
            "severity": c.severity, "state": c.state, "due_date": c.due_date,
            "days_overdue": (today - due).days, "opened_by": c.opened_by,
        })

    items.sort(key=lambda it: it["days_overdue"], reverse=True)
    return {"items": items, "total": len(items)}


def bottled_not_approved_report(db: Session) -> dict:
    """Báo cáo "Đã chiết nhưng chưa duyệt" — pipeline "Mẻ sản xuất" mới (yêu cầu người dùng
    2026-09-02: đổi nguồn từ BottleRecord (module cũ) sang BatchPackLot). BatchPackLot.approved
    giữ ĐÚNG vai trò như BottleRecord.approved (KCS duyệt chỉ tiêu — mirror approve_pack_lot,
    tách biệt với release_pack_lot_to_wms/"Duyệt nhập kho" là bước RIÊNG của Giám đốc SX) —
    không có mốc "ended_at" riêng như BottleRecord nên dùng `created_at` (thời điểm ghi nhận đã
    chiết) làm mốc "đang chờ từ khi nào", trước đây không có báo cáo/bộ lọc riêng cho khoảng
    trống này nên dễ bị bỏ sót, hàng chiết xong nằm chờ vô thời hạn mà không ai để ý."""
    from ..models.master import BeerType
    rows = db.execute(select(BatchPackLot).where(
        BatchPackLot.approved == false()
    ).order_by(BatchPackLot.created_at)).scalars().all()
    products = {p.finished_product_id: p for p in db.execute(select(FinishedProduct)).scalars().all()}
    filter_lot_ids = {p.filter_lot_id for p in rows}
    filter_lots_by_id = {fl.filter_lot_id: fl for fl in db.execute(
        select(BatchFilterLot).where(BatchFilterLot.filter_lot_id.in_(filter_lot_ids))).scalars().all()} if filter_lot_ids else {}
    beer_type_ids = {fl.beer_type_id for fl in filter_lots_by_id.values() if fl.beer_type_id}
    beer_types_by_id = {bt.beer_type_id: bt for bt in db.execute(
        select(BeerType).where(BeerType.beer_type_id.in_(beer_type_ids))).scalars().all()} if beer_type_ids else {}
    now = utcnow()
    items = []
    for p in rows:
        fp = products.get(p.finished_product_id)
        fl = filter_lots_by_id.get(p.filter_lot_id)
        bt = beer_types_by_id.get(fl.beer_type_id) if fl and fl.beer_type_id else None
        items.append({
            "pack_lot_id": p.pack_lot_id, "pack_lot_code": p.pack_lot_code, "beer_type": bt.name if bt else None,
            "finished_product_code": fp.code if fp else None, "finished_product_name": fp.name if fp else None,
            "from_bbt": p.from_bbt, "created_at": p.created_at,
            "hours_waiting": round((now - p.created_at).total_seconds() / 3600, 1),
            "qty": p.qty, "ca1_qty": p.ca1_qty, "ca2_qty": p.ca2_qty, "ca3_qty": p.ca3_qty,
        })
    return {"items": items, "total": len(items)}
