"""Tổng hợp số liệu cho Tổng quan (dashboard): lệnh nấu/lọc, mẻ nấu/lọc/chiết (thực thi
thật, không phải trạng thái ERP). Sản lượng chiết lon/keg theo ngày+ca hiển thị trên
dashboard lấy trực tiếp từ báo cáo SCADA thật (services/filling_external.py,
keg_external.py) — không tính lại ở đây."""
from datetime import timedelta

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from ..common import DeviationState, LotStatus, QualityStatus, ResultStatus, utcnow
from ..models.batches import BatchExecution
from ..models.brewing import BottleRecord, BrewBatch, BrewRecord, FermentRecord, FilterOrder, FilterRecord
from ..models.lines import ProductionLine
from ..models.master import FinishedProduct, Material
from ..models.materials import MaterialLot
from ..models.quality import Deviation, QualityResult
from ..models.quality_ext import QCParameter
from . import brew_order as brew_order_svc
from . import derived
from . import filter_order as filter_order_svc
from . import quality as quality_svc

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


def _batch_counts(rows: list) -> dict:
    total = len(rows)
    today = _local_date(utcnow())
    done = sum(1 for r in rows if r.ended_at is not None)
    done_today = sum(1 for r in rows if r.ended_at is not None and _local_date(r.ended_at) == today)
    return {"total": total, "dang_thuc_hien": total - done, "hoan_thanh": done, "hoan_thanh_hom_nay": done_today}


def _ferment_tank_rows(db: Session) -> tuple:
    """Danh sách tank lên men (CCT) đã khai báo (Danh mục "Tank lên men", ProductionLine.kind
    == "tank") + tập mã tank đang thật sự bị chiếm dụng. Một tank được coi là "đang lên men"
    nếu có ÍT NHẤT 1 FermentRecord ứng với tank đó chưa lọc hết (derived.ferment_status !=
    "da_loc_het") — tank có toàn bộ lô đã lọc hết coi như trống, sẵn sàng nhận lô mới. Dùng
    chung bởi _tank_len_men_counts (đếm tổng hợp) và available_ferment_tanks (từng tank)."""
    tanks = db.execute(select(ProductionLine).where(
        ProductionLine.kind == "tank", ProductionLine.active == True)).scalars().all()
    ferments = db.execute(select(FermentRecord)).scalars().all()
    occupied_codes = {f.tank_lm for f in ferments if derived.ferment_status(f) != "da_loc_het"}
    return tanks, occupied_codes


def _tank_len_men_counts(db: Session) -> dict:
    tanks, occupied_codes = _ferment_tank_rows(db)
    total = len(tanks)
    dang_su_dung = sum(1 for t in tanks if t.code in occupied_codes)
    return {"total": total, "dang_su_dung": dang_su_dung, "trong": total - dang_su_dung}


def available_ferment_tanks(db: Session) -> list:
    """Từng tank lên men (CCT) kèm cờ đang chiếm dụng hay không — dùng cho picker "Tank lên
    men" khi tạo mã nấu (tab Nấu), lọc chỉ hiện tank "trống" thay vì liệt kê mọi tank trong
    Danh mục không phân biệt (xem routers/brewing.py::list_available_ferment_tanks)."""
    tanks, occupied_codes = _ferment_tank_rows(db)
    return [{"code": t.code, "name": t.name, "occupied": t.code in occupied_codes}
            for t in sorted(tanks, key=lambda t: t.code)]


def production_summary(db: Session) -> dict:
    # Đếm theo LỆNH (Lệnh SX/master order — cái người dùng thực sự tạo ra), không phải theo
    # lệnh nhỏ (con) bên trong — trước đây "Lệnh nấu" đếm nhầm brew_order_svc.list_orders()
    # (danh sách lệnh nhỏ) trong khi "Lệnh lọc" đã đúng đếm theo master order, khiến 1 Lệnh
    # nấu có 2 lệnh nhỏ hiện thành "2" thay vì "1" — không khớp Lệnh lọc cùng màn hình.
    brew_orders = brew_order_svc.list_master_orders(db)
    filter_orders = filter_order_svc.list_master_orders(db)
    batches = db.execute(select(BrewBatch)).scalars().all()
    filters = db.execute(select(FilterRecord)).scalars().all()
    bottles = db.execute(select(BottleRecord)).scalars().all()
    return {
        "lenh_nau": _order_counts(brew_orders, "is_complete_all", "is_executed_any"),
        "lenh_loc": _order_counts(filter_orders, "is_complete_all", "is_executed_any"),
        "me_nau": _batch_counts(batches),
        "me_loc": _batch_counts(filters),
        "me_chiet": _batch_counts(bottles),
        "tank_len_men": _tank_len_men_counts(db),
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


def low_yield_filter_alerts(db: Session, days: int = 5, limit: int = 5) -> dict:
    """Cảnh báo sản lượng lọc thấp cho Dashboard: lấy báo cáo "Theo mẻ lọc số"
    (filter_yield_report_svc.filter_line_yield_report, xem tab Báo cáo › Sản lượng lọc) trong
    N ngày gần nhất (mặc định 5, tính theo `ended_at` — thời điểm kết thúc mẻ lọc), chỉ giữ các
    dòng classification="thap" (dưới ngưỡng Thấp cấu hình ở Cài đặt vận hành), sắp theo V bia
    thấp nhất lên trước (mẻ hụt sản lượng nặng nhất đáng chú ý nhất), giới hạn top N dòng —
    mirror qc_attention_alerts (widget cảnh báo gọn trên Dashboard, xem đầy đủ ở tab Báo cáo)."""
    from . import filter_yield_report as filter_yield_svc
    from . import ops_setting as ops_setting_svc
    settings = ops_setting_svc.get_settings(db)
    date_to = utcnow()
    date_from = date_to - timedelta(days=days)
    report = filter_yield_svc.filter_line_yield_report(
        db, date_from, date_to, settings.filter_line_yield_low_l, settings.filter_line_yield_high_l)
    low_items = sorted((it for it in report["items"] if it["classification"] == "thap"),
                       key=lambda it: it["v_l"])
    return {"items": low_items[:limit], "total": len(low_items),
            "date_from": report["date_from"], "date_to": report["date_to"], "low_l": report["low_l"]}


def bottled_not_approved_report(db: Session) -> dict:
    """Báo cáo "Đã chiết nhưng chưa duyệt" — mẻ chiết đã bấm "Kết thúc" (ended_at có giá trị,
    số liệu ca1/ca2/ca3/v_cap_chiet_hl đã chốt) nhưng chưa được Giám đốc SX duyệt nhập kho
    (approved=False, xem routers/brewing.py::approve_bottle) — trước đây không có báo cáo/bộ
    lọc riêng cho khoảng trống này nên dễ bị bỏ sót, hàng chiết xong nằm chờ vô thời hạn mà
    không ai để ý."""
    rows = db.execute(select(BottleRecord).where(
        BottleRecord.ended_at.isnot(None), BottleRecord.approved == false()
    ).order_by(BottleRecord.ended_at)).scalars().all()
    products = {p.finished_product_id: p for p in db.execute(select(FinishedProduct)).scalars().all()}
    now = utcnow()
    items = []
    for b in rows:
        fp = products.get(b.finished_product_id)
        items.append({
            "bottle_id": b.bottle_id, "bottle_code": b.bottle_code, "beer_type": b.beer_type,
            "finished_product_code": fp.code if fp else None, "finished_product_name": fp.name if fp else None,
            "from_bbt": b.from_bbt, "ended_at": b.ended_at,
            "hours_waiting": round((now - b.ended_at).total_seconds() / 3600, 1),
            "v_cap_chiet_hl": b.v_cap_chiet_hl, "ca1": b.ca1, "ca2": b.ca2, "ca3": b.ca3,
        })
    return {"items": items, "total": len(items)}
