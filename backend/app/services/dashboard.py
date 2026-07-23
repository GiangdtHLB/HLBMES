"""Tổng hợp số liệu cho Tổng quan (dashboard): lệnh nấu/lọc, mẻ nấu/lọc/chiết (thực thi
thật, không phải trạng thái ERP). Sản lượng chiết lon/keg theo ngày+ca hiển thị trên
dashboard lấy trực tiếp từ báo cáo SCADA thật (services/filling_external.py,
keg_external.py) — không tính lại ở đây."""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..common import DeviationState, LotStatus, ResultStatus, utcnow
from ..models.brewing import BottleRecord, BrewBatch, FermentRecord, FilterRecord
from ..models.lines import ProductionLine
from ..models.master import Material
from ..models.materials import MaterialLot
from ..models.quality import Deviation
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
                      "material_code": mat_by_id[l.material_id].code if l.material_id in mat_by_id else None,
                      "quantity": l.quantity, "uom": l.uom, "reasons": ["on_hold"],
                      "deviation_count": 0, "opened_at": None}

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
            items[key] = {"scope_type": d.scope_type, "scope_id": d.scope_id,
                          "lot_code": lot.lot_code if lot else None,
                          "material_code": (mat_by_id[lot.material_id].code
                                           if lot and lot.material_id in mat_by_id else None),
                          "quantity": lot.quantity if lot else None, "uom": lot.uom if lot else None,
                          "reasons": [], "deviation_count": 0, "opened_at": None}
        items[key]["reasons"].append("deviation")
        items[key]["deviation_count"] = dev_counts[key]
        items[key]["opened_at"] = dev_earliest[key]

    for key, item in items.items():
        scope_type, scope_id = key.split(":", 1)
        latest_by_param = quality_svc.latest_results_by_param(db, scope_type, scope_id)
        item["fail_param_count"] = sum(1 for r in latest_by_param.values()
                                       if r.status == ResultStatus.FAIL.value)

    out = sorted(items.values(), key=lambda i: (i["opened_at"] is None, i["opened_at"]))
    return {"items": out, "total": len(out)}
