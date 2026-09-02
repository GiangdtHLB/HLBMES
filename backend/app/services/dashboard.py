"""Tổng hợp số liệu cho Tổng quan (dashboard): lệnh nấu/lọc, mẻ nấu/lọc/chiết (thực thi
thật, không phải trạng thái ERP). Sản lượng chiết lon/keg theo ngày+ca hiển thị trên
dashboard lấy trực tiếp từ báo cáo SCADA thật (services/filling_external.py,
keg_external.py) — không tính lại ở đây."""
from datetime import timedelta

from sqlalchemy import false, select, true
from sqlalchemy.orm import Session

from ..common import DeviationState, LotStatus, QualityStatus, ResultStatus, utcnow
from ..models.batches import BatchExecution
from ..models.batch_pipeline import BatchFilterLot, BatchFilterLotBatch, BatchFilterLotBatchDraw, BatchPackLot
from ..models.brewing import BottleRecord, BrewBatch, BrewRecord, FermentRecord, FilterOrder, FilterRecord
from ..models.lines import ProductionLine
from ..models.master import FinishedProduct, Material
from ..models.materials import MaterialLot
from ..models.quality import Deviation, QualityResult
from ..models.quality_ext import CAPA, QCParameter
from . import batch_pipeline as batch_pipeline_svc
from . import brew_order as brew_order_svc
from . import derived
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


def _ferment_tank_rows(db: Session) -> tuple:
    """Danh sách tank lên men (CCT) đã khai báo (Danh mục "Tank lên men", ProductionLine.kind
    == "tank") + tập mã tank đang thật sự bị chiếm dụng. Một tank được coi là "đang lên men"
    nếu có ÍT NHẤT 1 FermentRecord ứng với tank đó chưa lọc hết (derived.ferment_status !=
    "da_loc_het") — tank có toàn bộ lô đã lọc hết coi như trống, sẵn sàng nhận lô mới. Dùng
    chung bởi _tank_len_men_counts (đếm tổng hợp) và available_ferment_tanks (từng tank)."""
    tanks = db.execute(select(ProductionLine).where(
        ProductionLine.kind == "tank", ProductionLine.active == true())).scalars().all()
    ferments = db.execute(select(FermentRecord)).scalars().all()
    occupied = {f.tank_lm: f for f in ferments if derived.ferment_status(f) != "da_loc_het"}
    occupied_codes = set(occupied.keys())
    return tanks, occupied_codes, occupied


def _tank_len_men_counts(db: Session) -> dict:
    # "Đang lên men" CHỈ tính tank đã nạp ĐẦY dịch VÀ đã kết thúc nấu (FermentRecord.kt_date
    # đã có — tự tính bằng giờ kết thúc mẻ CUỐI của (các) mã nấu chuyển sang tank đó, xem
    # routers/brewing.py::_sync_ferment_kt_date) — tách riêng khỏi tank ĐANG NẠP dịch (đã gán
    # tank nhưng mã nấu chuyển sang chưa kết thúc/chưa đầy tank, kt_date còn trống).
    tanks, occupied_codes, occupied = _ferment_tank_rows(db)
    total = len(tanks)
    dang_su_dung = sum(1 for t in tanks if t.code in occupied_codes and occupied[t.code].kt_date is not None)
    dang_nap = sum(1 for t in tanks if t.code in occupied_codes and occupied[t.code].kt_date is None)
    return {"total": total, "dang_su_dung": dang_su_dung, "dang_nap": dang_nap,
            "trong": total - dang_su_dung - dang_nap}


def available_ferment_tanks(db: Session) -> list:
    """Từng tank lên men (CCT) kèm cờ đang chiếm dụng hay không — dùng cho picker "Tank lên
    men" khi tạo mã nấu (tab Nấu), lọc chỉ hiện tank "trống" thay vì liệt kê mọi tank trong
    Danh mục không phân biệt (xem routers/brewing.py::list_available_ferment_tanks)."""
    tanks, occupied_codes, _ = _ferment_tank_rows(db)
    return [{"code": t.code, "name": t.name, "occupied": t.code in occupied_codes}
            for t in sorted(tanks, key=lambda t: t.code)]


def _batch_tank_len_men_counts(db: Session) -> dict:
    """"Tank đang lên men" trên Dashboard — CHỈ tính tank còn ĐÚNG NGHĨA đang lên men (status
    "len_men" hoặc "cho_loc", xem services/batch_pipeline.py::_tank_status) — KHÁC
    available_tank_lines (dùng cho picker chọn tank gộp mẻ mới, "chiếm dụng" ở đó = còn tồn
    khác 0 bất kể đã lọc hay chưa, mục đích khác hẳn: không cho dùng lại tank chưa dọn sạch).
    Tank đã "loc_1_phan"/"da_loc_het"/"am" (đã bị rút dịch, dù còn tồn dở) đã CHUYỂN sang công
    đoạn Lọc rồi, không còn tính là "đang lên men" nữa (yêu cầu người dùng 2026-09-02: "tank
    đang lọc mà lại vẫn hiển thị đang lên men"). `dang_loc` (yêu cầu người dùng 2026-09-02: ghi
    chú thêm "số tank đang lọc") đếm riêng tank "loc_1_phan" (đang rút dịch dở dang) — KHÁC
    "trống" thật sự (đã rút hết/am, hoặc chưa từng gộp mẻ nào). `dang_nap` giữ nguyên = 0 (không
    có trạng thái "đang nạp dở dang" trong dữ liệu — merge_batches_into_tank ghi on_hand ĐỦ ngay
    khi gộp mẻ, không có bước tăng dần để tính riêng, theo lựa chọn người dùng 2026-09-02)."""
    lines = db.execute(select(ProductionLine).where(
        ProductionLine.kind == "tank", ProductionLine.active == true())).scalars().all()
    tanks_by_code: dict[str, str] = {}
    for t in batch_pipeline_svc.list_tanks_out(db):
        if t["tank_lm"]:
            tanks_by_code[t["tank_lm"]] = t["status"]
    total = len(lines)
    dang_su_dung = sum(1 for l in lines if tanks_by_code.get(l.code) in ("len_men", "cho_loc"))
    dang_loc = sum(1 for l in lines if tanks_by_code.get(l.code) == "loc_1_phan")
    return {"total": total, "dang_su_dung": dang_su_dung, "dang_loc": dang_loc, "dang_nap": 0,
            "trong": total - dang_su_dung - dang_loc}


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
# để "Lô/Phạm vi" trên Dashboard hiện đúng mã (VD "Mẻ lọc FL-20601") thay vì UUID scope_id thô.
_SCOPE_MODELS = {"lot": MaterialLot, "batch": BatchExecution, "brew_batch": BrewBatch,
                 "ferment": FermentRecord, "filter": FilterRecord, "bottle": BottleRecord}
_SCOPE_CODE_ATTR = {"lot": "lot_code", "batch": "batch_code", "brew_batch": "batch_code",
                    "ferment": "lm_code", "filter": "filter_code", "bottle": "bottle_code"}
_SCOPE_LABEL_PREFIX = {"lot": "Lô NVL", "batch": "Mẻ SX", "brew_batch": "Mẻ nấu",
                       "ferment": "Lô LM", "filter": "Mẻ lọc", "bottle": "Mã chiết"}
_SCOPE_ID_ATTR = {"brew_batch": "batch_id", "ferment": "ferment_id",
                  "filter": "filter_id", "bottle": "bottle_id"}


def _scope_code(db: Session, scope_type: str, scope_id: str) -> str | None:
    model = _SCOPE_MODELS.get(scope_type)
    obj = db.get(model, scope_id) if model else None
    return getattr(obj, _SCOPE_CODE_ATTR[scope_type], None) if obj else None


def _scope_label(scope_type: str, scope_code: str | None, scope_id: str) -> str:
    return f"{_SCOPE_LABEL_PREFIX.get(scope_type, scope_type)} {scope_code or scope_id}"


# mẻ nấu/mẻ lọc/mã chiết chỉ có nghĩa khi biết chúng thuộc lô nấu/lô lọc/mẻ lọc nguồn nào —
# dùng FK sẵn có (không query thêm ngoài 1 db.get) để trả ra nhãn lô cha, thay cho cột "Vật
# tư"/"SL" trên Dashboard vốn luôn rỗng với các scope_type này (chỉ có nghĩa với scope="lot").
def _parent_label(db: Session, scope_type: str, obj) -> str | None:
    if scope_type == "brew_batch" and obj.brew_id:
        brew = db.get(BrewRecord, obj.brew_id)
        return f"Lô nấu {brew.brew_code}" if brew else None
    if scope_type == "filter" and obj.filter_order_id:
        order = db.get(FilterOrder, obj.filter_order_id)
        return f"Lô lọc {order.order_code}" if order else None
    if scope_type == "bottle" and obj.filter_code:
        return f"Mẻ lọc {obj.filter_code}"
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

    # Mẻ/lô công đoạn (brew_batch/ferment/filter/bottle) bị hold trực tiếp qua
    # quality_status (services/quality.py::set_hold/_cascade_hold_siblings) — không có
    # deviation mở kèm theo thì trước đây KHÔNG bao giờ lộ ra ở đây (chỉ suy luận "on_hold"
    # gián tiếp qua deviation trùng scope), khiến Dashboard "Hold/Release" bỏ sót các hold
    # loại này dù Lịch sử Hold/Release đã ghi nhận đúng.
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
    chạy máy) ĐÃ tự là đơn vị atomic (không bị tách ghi nhận qua nhiều FilterRecord như module
    cũ) nên KHÔNG cần gộp theo (batch_number/order_number/batch_seq_no) — mỗi mẻ = đúng 1 dòng.
    V lọc (V dịch nha + Nước bài khí, đổi hl -> lít) so ngưỡng Thấp/Cao cấu hình — mẻ "cuối"
    (is_final_batch, mẻ vét) loại khỏi phân loại để không báo động giả (yêu cầu người dùng
    2026-09-02)."""
    batches = db.execute(
        select(BatchFilterLotBatch)
        .where(BatchFilterLotBatch.ended_at.is_not(None),
               BatchFilterLotBatch.ended_at >= date_from, BatchFilterLotBatch.ended_at < date_to)
        .order_by(BatchFilterLotBatch.ended_at)
    ).scalars().all()
    batch_ids = [b.batch_link_id for b in batches]
    draws = db.execute(select(BatchFilterLotBatchDraw).where(
        BatchFilterLotBatchDraw.batch_link_id.in_(batch_ids))).scalars().all() if batch_ids else []
    draw_hl_by_batch: dict[str, float] = {}
    for d in draws:
        draw_hl_by_batch[d.batch_link_id] = draw_hl_by_batch.get(d.batch_link_id, 0.0) + (d.dich_nha_hl or 0.0)
    filter_lot_ids = {b.filter_lot_id for b in batches}
    filter_lots_by_id = {fl.filter_lot_id: fl for fl in db.execute(
        select(BatchFilterLot).where(BatchFilterLot.filter_lot_id.in_(filter_lot_ids))).scalars().all()} if filter_lot_ids else {}
    from ..models.master import BeerType
    beer_type_ids = {fl.beer_type_id for fl in filter_lots_by_id.values() if fl.beer_type_id}
    beer_types_by_id = {bt.beer_type_id: bt for bt in db.execute(
        select(BeerType).where(BeerType.beer_type_id.in_(beer_type_ids))).scalars().all()} if beer_type_ids else {}

    items = []
    for b in batches:
        fl = filter_lots_by_id.get(b.filter_lot_id)
        bt = beer_types_by_id.get(fl.beer_type_id) if fl and fl.beer_type_id else None
        v_dich_l = draw_hl_by_batch.get(b.batch_link_id, 0.0) * 100
        v_daw_l = (b.nuoc_bai_khi_hl or 0.0) * 100
        v_l = v_dich_l + v_daw_l
        cls = "cuoi" if b.is_final_batch else classify_yield_l(v_l, low_l, high_l)
        items.append({
            "batch_link_id": b.batch_link_id, "batch_seq_no": b.batch_seq_no,
            "filter_lot_id": fl.filter_lot_id if fl else None,
            "filter_lot_code": fl.filter_lot_code if fl else None,
            "beer_type": bt.name if bt else None,
            "ended_at": b.ended_at.isoformat() if b.ended_at else None,
            "v_dich_l": round(v_dich_l, 1), "v_daw_l": round(v_daw_l, 1),
            "v_l": round(v_l, 1), "classification": cls, "classification_label": _YIELD_LABEL[cls],
        })
    return items


def low_yield_filter_alerts(db: Session, days: int = 5, limit: int = 5) -> dict:
    """Cảnh báo sản lượng lọc thấp cho Dashboard — pipeline "Mẻ sản xuất" mới (yêu cầu người
    dùng 2026-09-02: đổi nguồn từ module Nấu-Lọc-Chiết cũ sang BatchFilterLotBatch, tính toán
    tương tự y hệt cách cũ — xem _batch_filter_lot_yield_items). Trong N ngày gần nhất (mặc
    định 5, tính theo `ended_at` — thời điểm kết thúc mẻ lọc), chỉ giữ classification="thap",
    sắp theo V lọc thấp nhất lên trước (mẻ hụt sản lượng nặng nhất đáng chú ý nhất), giới hạn
    top N dòng — mirror qc_attention_alerts (widget cảnh báo gọn trên Dashboard)."""
    from . import ops_setting as ops_setting_svc
    settings = ops_setting_svc.get_settings(db)
    date_to = utcnow()
    date_from = date_to - timedelta(days=days)
    all_items = _batch_filter_lot_yield_items(
        db, date_from, date_to, settings.filter_line_yield_low_l, settings.filter_line_yield_high_l)
    low_items = sorted((it for it in all_items if it["classification"] == "thap"),
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
