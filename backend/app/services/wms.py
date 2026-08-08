"""WMS thành phẩm: vị trí + đơn vị tồn kho theo LÔ (không phải theo từng vỉ/keg riêng lẻ —
xem docs/WMS-LOT-LEVEL-REDESIGN.md), putaway/ship theo vị trí, tồn theo vị trí, phân giải
barcode (cho đầu đọc cầm tay / kiosk)."""

import re
from datetime import datetime, timedelta

from sqlalchemy import and_, case, delete, false, func, or_, select, true
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import Role, new_id, utcnow
from ..errors import DomainError, NotFoundError
from ..models.audit import AuditLog
from ..models.brewing import BottleRecord
from ..models.master import FinishedProduct, UnitTypeCatalog
from ..models.materials import GenealogyEdge, Supplier
from ..models.warehouse import FactoryLocation
from ..models.wms import (ConsignedEntry, FactoryImportEntry, FinishedGoodsUnit, NearExpiryEntry, Shipment,
                          Vehicle, WmsLocation, WmsTransfer, WmsTransferLine, WmsWarehouse)
from ..security import User, require_perm, require_role, require_scope
from . import genealogy
from .opening_balance_import import parse_opening_balance_sheet

# Sentinel phân biệt "không lọc theo vị trí" với "lọc theo vị trí = chưa cất" (location_id
# IS NULL) trong _consume_lot_rows — None tự nó đã có nghĩa hợp lệ (chưa cất) nên không dùng
# được làm giá trị mặc định "bỏ qua tham số".
_LOC_UNSET = object()


def _divide_by_pack_codes(db: Session) -> frozenset[str]:
    """Tập hợp mã unit_type "chia theo pack_size" (giống Vỉ) tra từ Danh mục Loại đơn vị tồn
    kho (UnitTypeCatalog.divide_by_pack_size) — phần còn lại (giống Keg/Lon) luôn quy đổi 1:1.
    Gọi 1 LẦN ở đầu mỗi hàm nghiệp vụ rồi truyền xuống _pack_divisor/_pack_divisor_expr (bảng
    này rất nhỏ nhưng gọi lặp lại trong vòng lặp per-unit sẽ thành N+1 khi xử lý hàng trăm
    nghìn dòng — xem docs/WMS-LOT-LEVEL-REDESIGN.md)."""
    codes = db.execute(select(UnitTypeCatalog.code)
                       .where(UnitTypeCatalog.divide_by_pack_size == true())).scalars().all()
    return frozenset(codes) or frozenset({"vi"})


def _pack_divisor(fp: FinishedProduct | None, unit_type: str, divide_codes: frozenset[str]) -> int:
    """Quy đổi giữa "count" (đơn vị đóng gói vỉ/keg/lon/... — tham số vào của mọi API WMS) và
    "quantity" (SL đơn vị nhỏ lưu trên dòng FinishedGoodsUnit, xem model): 1 count = bao
    nhiêu quantity. Loại "chia theo pack_size" (giống Vỉ, xem divide_codes/UnitTypeCatalog):
    pack_size khai báo ở Danh mục Sản phẩm (FinishedProduct, tra qua finished_product_id).
    Không có SKU khai báo (finished_product_id NULL — VD "Nhập kho thủ công"/test dùng
    product_name tự do không qua Danh mục) → mặc định 1 (KHÔNG đoán 24): giá trị pack_size
    dùng lúc TẠO dòng (payload.pack_size của _create_units) không được lưu lại trên dòng để
    tra lại ở đây, nên giả định an toàn nhất khi không có SKU là "count = quantity" (không quy
    đổi), tránh đoán sai đơn vị tồn kho như khi mặc định 24 cho SKU không có thật. Loại còn lại
    (giống Keg/Lon) luôn là 1 (1 keg/1 lon = 1 đơn vị nhỏ, không nhân thêm)."""
    if unit_type not in divide_codes:
        return 1
    return fp.pack_size if fp and fp.pack_size else 1


def _pack_divisor_expr(divide_codes: frozenset[str], unit_type_col=FinishedGoodsUnit.unit_type,
                       pack_size_col=FinishedProduct.pack_size):
    """Biểu thức SQL tương đương _pack_divisor() để dùng trong SUM/GROUP BY (đếm số vỉ/keg/lon
    trực tiếp từ SUM(quantity) mà không cần tải từng dòng — xem list_lot_summaries/summary/...).
    Cần OUTER JOIN FinishedProduct qua finished_product_id ở câu truy vấn gọi hàm này."""
    return case((unit_type_col.in_(divide_codes), func.coalesce(func.nullif(pack_size_col, 0), 1)), else_=1)


def _line_weight_kg(fp: FinishedProduct | None, unit_type: str, quantity: float,
                    divide_codes: frozenset[str]) -> float:
    """Khối lượng (kg) của 1 dòng FinishedGoodsUnit — dùng cho báo cáo tải trọng chuyến xe
    (vehicle_trip_report). `quantity` luôn ở đơn vị nhỏ nhất (xem _pack_divisor); chia lại
    cho divisor để ra số đơn vị đóng gói vật lý thật (số vỉ/keg/lon), rồi nhân khối lượng
    tương ứng: chưa phân rã (unit_type == fp.unit_type — dòng "vi" của SKU vi, hoặc "keg" của
    SKU keg) dùng weight_primary_kg (1 vỉ/keg NGUYÊN); đã phân rã (VD "lon" từ SKU "vi") dùng
    weight_single_kg (1 lon/chai lẻ). Không có SKU hoặc chưa khai báo khối lượng → 0."""
    if not fp:
        return 0.0
    divisor = _pack_divisor(fp, unit_type, divide_codes)
    primary_count = (quantity or 0) / divisor
    if unit_type == fp.unit_type:
        return primary_count * (fp.weight_primary_kg or 0)
    return primary_count * (fp.weight_single_kg or 0)


def _liters_per_unit(fp: FinishedProduct | None) -> float | None:
    """Lít/1 đơn vị nhỏ nhất (lon/chai/keg) — ưu tiên FinishedProduct.unit_volume_l đã khai
    báo (VD 0.33 cho lon 330ml), fallback về parse tên SKU (_resolve_liters_per_unit) cho SKU
    cũ chưa khai báo field này."""
    if fp and fp.unit_volume_l:
        return fp.unit_volume_l
    return _resolve_liters_per_unit(fp.name if fp else None)


def _assert_wh_scope(db: Session, user: User, warehouse_id: str | None) -> None:
    """Chặn thao tác tại 1 Kho thành phẩm (WmsWarehouse) ngoài phạm vi được phân
    (`User.wms_warehouse_scope`: csv mã kho hoặc "*") — dùng cho mọi hành động chỉ định RÕ 1
    kho (nhập/cất/điều chuyển đến/đi, xuất kho). warehouse_id rỗng/None (chưa xác định được kho,
    vd đơn vị chưa cất vị trí) không bị chặn, theo đúng quy ước các chiều scope khác."""
    if not warehouse_id:
        return
    wh = db.get(WmsWarehouse, warehouse_id)
    require_scope(user, "wms_warehouse", wh.code if wh else warehouse_id)


def _assert_loc_scope(db: Session, user: User, loc_id: str | None) -> None:
    """Mirror _assert_wh_scope nhưng nhận thẳng loc_id (WmsLocation) — tự tra ra kho chứa vị
    trí đó rồi chặn theo scope, dùng ở mọi nơi người dùng chọn 1 vị trí kho cụ thể."""
    if not loc_id:
        return
    loc = db.get(WmsLocation, loc_id)
    if loc:
        _assert_wh_scope(db, user, loc.warehouse_id)


def _wh_scope_restricted(user: User) -> bool:
    """True nếu user bị giới hạn kho thành phẩm (khác "*", và không phải admin — admin luôn bỏ
    qua data-scoping, xem security.has_scope) — dùng để BẮT BUỘC chọn kho/vị trí tường minh ở
    các luồng trước đây cho phép bỏ trống (FIFO tự do toàn công ty), vì bỏ trống sẽ khiến hệ
    thống tự chọn xuyên qua kho ngoài phạm vi mà không có gì để chặn."""
    if user.role == Role.ADMIN.value:
        return False
    return getattr(user, "scope_wms_warehouse", "*") != "*"


def _location_used_count(db: Session, loc_id: str, exclude_unit_id: str | None = None) -> float:
    """Tổng số vỉ/keg/lon quy đổi (SUM(quantity)/pack_size từng dòng qua _pack_divisor_expr,
    KHÔNG đếm dòng — 1 vị trí có thể chứa lẫn nhiều SKU khác pack_size nhau) đang "stored"
    tại 1 vị trí kho — dùng để kiểm sức chứa (WmsLocation.capacity)."""
    stmt = (select(func.sum(FinishedGoodsUnit.quantity / _pack_divisor_expr(_divide_by_pack_codes(db))))
            .select_from(FinishedGoodsUnit)
            .outerjoin(FinishedProduct, FinishedProduct.finished_product_id == FinishedGoodsUnit.finished_product_id)
            .where(FinishedGoodsUnit.location_id == loc_id, FinishedGoodsUnit.status == "stored"))
    if exclude_unit_id:
        stmt = stmt.where(FinishedGoodsUnit.unit_id != exclude_unit_id)
    return db.execute(stmt).scalar() or 0


def _consume_lot_rows(db: Session, *, product_name: str, unit_type: str, status: str,
                      quantity_needed: float, lot_code: str | None = None,
                      location_id=_LOC_UNSET, exclude_ids: set | None = None,
                      near_expiry_only: bool = False, consigned_only: bool = False,
                      block_pending_manual: bool = False, warehouse_id: str | None = None
                      ) -> tuple[list[FinishedGoodsUnit], float]:
    """Tiêu thụ FIFO (cũ nhất trước, theo created_at) từ các dòng LÔ khớp tiêu chí tới khi đủ
    `quantity_needed` (đơn vị = cột quantity, KHÔNG phải số vỉ/keg — caller tự nhân với
    _pack_divisor() trước khi gọi). Dòng bị lấy TRỌN thì trả nguyên dòng đó; dòng bị lấy MỘT
    PHẦN thì TÁCH: 1 dòng mới mang đúng phần cần lấy (caller tự mutate status/location_id/
    shipment_id trên các dòng trả về sau khi hàm này xong), dòng gốc giữ phần dư — thay vì
    phải chọn/xóa/gộp nguyên dòng có thể đại diện hàng trăm nghìn vỉ đã gộp lại (xem
    docs/WMS-LOT-LEVEL-REDESIGN.md). Trả về (rows, tổng_quantity_lấy_được) — tổng nhỏ hơn
    quantity_needed nghĩa là không đủ tồn; caller tự chia lại cho divisor để báo lỗi đúng đơn
    vị (vỉ/keg/lon) người dùng hiểu, hàm này không tự raise vì không biết đơn vị hiển thị."""
    stmt = select(FinishedGoodsUnit).where(
        FinishedGoodsUnit.product_name == product_name,
        FinishedGoodsUnit.unit_type == unit_type,
        FinishedGoodsUnit.status == status,
    )
    if lot_code:
        stmt = stmt.where(FinishedGoodsUnit.lot_code == lot_code)
    if location_id is not _LOC_UNSET:
        stmt = stmt.where(FinishedGoodsUnit.location_id.is_(None) if location_id is None
                         else FinishedGoodsUnit.location_id == location_id)
    if warehouse_id:
        # Giới hạn FIFO trong 1 Kho thành phẩm — dùng khi Xuất kho/Xuất tự do chỉ định "Kho
        # xuất" (vd tài khoản bị giới hạn kho, xem _assert_wh_scope) — KHÔNG lọc bằng
        # location_id đơn lẻ vì 1 kho có nhiều vị trí.
        stmt = stmt.where(FinishedGoodsUnit.location_id.in_(
            select(WmsLocation.loc_id).where(WmsLocation.warehouse_id == warehouse_id)))
    if near_expiry_only:
        stmt = stmt.where(FinishedGoodsUnit.is_near_expiry == true())
    if consigned_only:
        stmt = stmt.where(FinishedGoodsUnit.is_consigned == true())
    if block_pending_manual:
        # "Nhập kho thủ công" (source="manual") chưa được Trưởng bộ phận kho duyệt
        # (received_confirmed_by IS NULL) thì KHÔNG được chọn để xuất — xem docstring
        # FinishedGoodsUnit.source. Các nguồn khác (chiet/None/near_expiry/consigned...) không
        # bị ảnh hưởng, giữ nguyên hành vi xuất-ngay đã có.
        stmt = stmt.where(or_(FinishedGoodsUnit.source.is_(None), FinishedGoodsUnit.source != "manual",
                              FinishedGoodsUnit.received_confirmed_by.isnot(None)))
    if exclude_ids:
        stmt = stmt.where(FinishedGoodsUnit.unit_id.notin_(exclude_ids))
    stmt = stmt.order_by(FinishedGoodsUnit.created_at)

    remaining = quantity_needed
    picked: list[FinishedGoodsUnit] = []
    for row in db.execute(stmt).scalars().all():
        if remaining <= 1e-9:
            break
        if row.quantity <= remaining + 1e-9:
            picked.append(row)
            remaining -= row.quantity
        else:
            split = FinishedGoodsUnit(
                unit_id=new_id(), unit_code=f"{row.unit_code}-S{new_id()[:4].upper()}",
                unit_type=row.unit_type, finished_product_id=row.finished_product_id,
                product_name=row.product_name, lot_code=row.lot_code, quantity=remaining,
                status=row.status, location_id=row.location_id, created_by=row.created_by,
                created_at=row.created_at, is_near_expiry=row.is_near_expiry,
                is_consigned=row.is_consigned,
            )
            db.add(split)
            row.quantity -= remaining
            db.flush()
            picked.append(split)
            remaining = 0
    return picked, quantity_needed - max(remaining, 0)


def create_warehouse(db: Session, payload: dict) -> WmsWarehouse:
    if db.execute(select(WmsWarehouse).where(WmsWarehouse.code == payload.get("code"))).scalar_one_or_none():
        raise DomainError(f"Mã kho '{payload.get('code')}' đã tồn tại.")
    wh = WmsWarehouse(warehouse_id=new_id(), **payload)
    db.add(wh)
    db.commit()
    db.refresh(wh)
    return wh


def update_warehouse(db: Session, warehouse_id: str, payload: dict) -> WmsWarehouse:
    wh = db.get(WmsWarehouse, warehouse_id)
    if not wh:
        raise NotFoundError("Kho thành phẩm không tồn tại.")
    for k, v in payload.items():
        if v is not None:
            setattr(wh, k, v)
    db.commit()
    db.refresh(wh)
    return wh


def delete_warehouse(db: Session, warehouse_id: str) -> None:
    wh = db.get(WmsWarehouse, warehouse_id)
    if not wh:
        raise NotFoundError("Kho thành phẩm không tồn tại.")
    used = db.execute(select(func.count(WmsLocation.loc_id))
                      .where(WmsLocation.warehouse_id == warehouse_id)).scalar() or 0
    if used:
        raise DomainError(f"Kho {wh.code} còn {used} vị trí — không thể xóa.")
    db.delete(wh)
    db.commit()


def list_warehouses(db: Session) -> list:
    rows = db.execute(select(WmsWarehouse).order_by(WmsWarehouse.code)).scalars().all()
    loc_counts = dict(db.execute(
        select(WmsLocation.warehouse_id, func.count(WmsLocation.loc_id))
        .group_by(WmsLocation.warehouse_id)).all())
    return [{"warehouse_id": w.warehouse_id, "code": w.code, "name": w.name, "address": w.address,
             "active": w.active, "location_count": loc_counts.get(w.warehouse_id, 0) or 0} for w in rows]


def create_location(db: Session, payload: dict) -> WmsLocation:
    loc = WmsLocation(loc_id=new_id(), **payload)
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return loc


def update_location(db: Session, loc_id: str, payload: dict) -> WmsLocation:
    loc = db.get(WmsLocation, loc_id)
    if not loc:
        raise NotFoundError("Vị trí không tồn tại.")
    for k, v in payload.items():
        if v is not None:
            setattr(loc, k, v)
    db.commit()
    db.refresh(loc)
    return loc


def delete_location(db: Session, loc_id: str) -> None:
    loc = db.get(WmsLocation, loc_id)
    if not loc:
        raise NotFoundError("Vị trí không tồn tại.")
    used = db.execute(select(func.count(FinishedGoodsUnit.unit_id)).where(
        FinishedGoodsUnit.location_id == loc_id, FinishedGoodsUnit.status == "stored")).scalar() or 0
    if used:
        raise DomainError(f"Vị trí {loc.code} đang chứa {used} vỉ/keg — không thể xóa.")
    db.delete(loc)
    db.commit()


def list_locations(db: Session) -> list:
    locs = db.execute(select(WmsLocation).order_by(WmsLocation.code)).scalars().all()
    # "used" = tổng vỉ/keg/lon quy đổi (SUM(quantity)/pack_size từng dòng), KHÔNG đếm dòng —
    # 1 dòng giờ có thể đại diện nhiều đơn vị đóng gói (xem docs/WMS-LOT-LEVEL-REDESIGN.md).
    counts = dict(db.execute(
        select(FinishedGoodsUnit.location_id, func.sum(FinishedGoodsUnit.quantity / _pack_divisor_expr(_divide_by_pack_codes(db))))
        .select_from(FinishedGoodsUnit)
        .outerjoin(FinishedProduct, FinishedProduct.finished_product_id == FinishedGoodsUnit.finished_product_id)
        .where(FinishedGoodsUnit.status == "stored").group_by(FinishedGoodsUnit.location_id)).all())
    wh_by_id = {w.warehouse_id: w for w in db.execute(select(WmsWarehouse)).scalars().all()}
    return [{"loc_id": l.loc_id, "code": l.code, "name": l.name, "zone": l.zone, "kind": l.kind,
             "capacity": l.capacity, "active": l.active, "used": counts.get(l.loc_id, 0) or 0,
             "warehouse_id": l.warehouse_id,
             "warehouse_code": wh_by_id[l.warehouse_id].code if l.warehouse_id in wh_by_id else None,
             "warehouse_name": wh_by_id[l.warehouse_id].name if l.warehouse_id in wh_by_id else None}
            for l in locs]


def _gen_vehicle_code(db: Session) -> str:
    """Mã xe cố định tăng dần ("XE0001", ...) — không đổi theo biển số, dùng làm liên kết ổn
    định cho báo cáo lượt xe (xem models/wms.py::Vehicle.vehicle_code)."""
    count = db.execute(select(func.count()).select_from(Vehicle)).scalar_one()
    while True:
        count += 1
        code = f"XE{count:04d}"
        if not db.execute(select(Vehicle.vehicle_id).where(Vehicle.vehicle_code == code)).first():
            return code


def create_vehicle(db: Session, payload: dict) -> Vehicle:
    if db.execute(select(Vehicle).where(Vehicle.plate == payload["plate"])).scalar_one_or_none():
        raise DomainError(f"Biển số '{payload['plate']}' đã tồn tại.")
    v = Vehicle(vehicle_id=new_id(), vehicle_code=_gen_vehicle_code(db), **payload)
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


def update_vehicle(db: Session, vehicle_id: str, payload: dict) -> Vehicle:
    v = db.get(Vehicle, vehicle_id)
    if not v:
        raise NotFoundError("Xe không tồn tại.")
    for k, val in payload.items():
        if val is not None:
            setattr(v, k, val)
    db.commit()
    db.refresh(v)
    return v


def delete_vehicle(db: Session, vehicle_id: str) -> None:
    v = db.get(Vehicle, vehicle_id)
    if not v:
        raise NotFoundError("Xe không tồn tại.")
    db.delete(v)
    db.commit()


def list_vehicles(db: Session) -> list:
    rows = db.execute(select(Vehicle).order_by(Vehicle.plate)).scalars().all()
    return [{"vehicle_id": v.vehicle_id, "vehicle_code": v.vehicle_code, "plate": v.plate,
             "driver_name": v.driver_name,
             "driver_short_name": v.driver_short_name, "capacity_kg": v.capacity_kg,
             "pallet_capacity": v.pallet_capacity, "phone": v.phone, "team": v.team,
             "active": v.active} for v in rows]


def summary(db: Session) -> dict:
    """Tổng hợp toàn kho: số vị trí + sức chứa, tổng vỉ/keg/lon theo trạng thái/loại — dùng
    SUM(quantity)/pack_size ở SQL (qua _pack_divisor_expr), KHÔNG đếm dòng và KHÔNG load
    từng dòng vào Python (kho có thể có hàng trăm ngàn đơn vị gộp vào rất ít dòng — xem
    docs/WMS-LOT-LEVEL-REDESIGN.md; đếm dòng giờ không còn phản ánh đúng số vỉ/keg/lon).
    units_total/by_type CHỈ tính dòng status=stored (tồn thật đang ở kho) — nếu gộp cả
    decomposed/shipped/issued_free vào đây, tổng sẽ không bao giờ về số nguyên sau khi xuất tự
    do 1 phần lẻ (dòng đó đổi status chứ không mất đi, cộng dồn mãi vào "Vỉ" dù đã xuất hết).
    by_status vẫn liệt kê đủ mọi trạng thái (kể cả lịch sử) vì bản thân nó dùng để xem phân bổ
    theo trạng thái, không phải "tồn hiện có"."""
    locs = db.execute(select(WmsLocation)).scalars().all()
    capacity = sum(l.capacity for l in locs)
    count_expr = func.sum(FinishedGoodsUnit.quantity / _pack_divisor_expr(_divide_by_pack_codes(db)))

    def _joined(*cols, stored_only=False):
        q = (select(*cols).select_from(FinishedGoodsUnit)
             .outerjoin(FinishedProduct, FinishedProduct.finished_product_id == FinishedGoodsUnit.finished_product_id))
        return q.where(FinishedGoodsUnit.status == "stored") if stored_only else q

    by_status = {k: v or 0 for k, v in db.execute(
        _joined(FinishedGoodsUnit.status, count_expr).group_by(FinishedGoodsUnit.status)).all()}
    by_type = {k: round(v or 0, 2) for k, v in db.execute(
        _joined(FinishedGoodsUnit.unit_type, count_expr, stored_only=True)
        .group_by(FinishedGoodsUnit.unit_type)).all()}
    units_stored = round(by_status.get("stored", 0), 2)
    units_total = round(sum(by_type.values()), 2)
    return {"locations": len(locs), "capacity_units": capacity,
            "units_total": units_total, "units_stored": units_stored,
            "fill_pct": round(units_stored / capacity * 100, 1) if capacity else 0.0,
            "by_status": by_status, "by_type": by_type}


def list_units(db: Session, status: str = None, unit_type: str = None,
               product_name: str = None, lot_code: str = None,
               limit: int = 1000, offset: int = 0) -> list:
    """`product_name`/`lot_code` giới hạn về 1 lô cụ thể — nên dùng khi cần liệt kê từng dòng
    của 1 lô cụ thể (VD trước khi xóa cả lô). Có phân trang (limit/offset, mặc định 1000,
    tối đa 5000) — dù redesign lô=1 dòng đã tự giảm mạnh số dòng/lô (xem
    docs/WMS-LOT-LEVEL-REDESIGN.md), tổng số dòng TOÀN kho vẫn tăng dần theo số lô tích lũy
    qua thời gian nên endpoint không lọc vẫn cần chặn không tải hết bảng."""
    limit = max(1, min(limit or 1000, 5000))
    offset = max(0, offset or 0)
    stmt = select(FinishedGoodsUnit).order_by(FinishedGoodsUnit.created_at)
    if status:
        stmt = stmt.where(FinishedGoodsUnit.status == status)
    if unit_type:
        stmt = stmt.where(FinishedGoodsUnit.unit_type == unit_type)
    if product_name:
        stmt = stmt.where(FinishedGoodsUnit.product_name == product_name)
    if lot_code:
        stmt = stmt.where(FinishedGoodsUnit.lot_code == lot_code)
    stmt = stmt.limit(limit).offset(offset)
    out = []
    loc_by = {l.loc_id: l for l in db.execute(select(WmsLocation)).scalars().all()}
    wh_by_id = {w.warehouse_id: w for w in db.execute(select(WmsWarehouse)).scalars().all()}
    ship_to_by = {s.supplier_id: s for s in db.execute(select(Supplier)).scalars().all()}
    bottle_codes_by_lot: dict[str, list] = {}
    for lot_no, bottle_code in db.execute(select(BottleRecord.lot_no, BottleRecord.bottle_code)
                                          .where(BottleRecord.lot_no.isnot(None))).all():
        bottle_codes_by_lot.setdefault(lot_no, []).append(bottle_code)
    for u in db.execute(stmt).scalars().all():
        loc = loc_by.get(u.location_id)
        wh = wh_by_id.get(loc.warehouse_id) if loc else None
        ship_to = ship_to_by.get(u.ship_to_id)
        # bottle_code: mã chiết đã sinh ra lô này — chỉ để hiển thị tham khảo (VD Kho TP), KHÔNG
        # dùng để gom nhóm/FIFO (vẫn theo lot_code = số lô bia, xem list_lot_summaries).
        out.append({"unit_id": u.unit_id, "unit_code": u.unit_code, "unit_type": u.unit_type,
                    "finished_product_id": u.finished_product_id, "product": u.product_name,
                    "lot_code": u.lot_code, "bottle_codes": bottle_codes_by_lot.get(u.lot_code, []),
                    "quantity": u.quantity, "status": u.status,
                    "location": loc.code if loc else None,
                    "warehouse_code": wh.code if wh else None, "warehouse_name": wh.name if wh else None,
                    "created_at": u.created_at, "shipped_at": u.shipped_at,
                    "ship_to_code": ship_to.code if ship_to else None,
                    "ship_to_name": ship_to.name if ship_to else None})
    return out


def _parse_received_at(received_at, now: datetime, skip_cap: bool = False) -> datetime:
    """Chuẩn hoá + validate "Ngày nhập" do người dùng nhập tay — dùng chung cho nhập kho thủ
    công/tồn đầu (_create_units) và khai báo nhập từ nhà máy khác
    (create_factory_import_entry/update_factory_import_entry)."""
    if not received_at:
        return now
    received_dt = datetime.fromisoformat(received_at) if isinstance(received_at, str) else received_at
    if received_dt.tzinfo is None:
        received_dt = received_dt.replace(tzinfo=now.tzinfo)
    if received_dt > now:
        raise DomainError("Ngày nhập không được sau thời điểm hiện tại.")
    # Tồn đầu hợp lệ với ngày rất xa trong quá khứ — giới hạn 15 ngày chỉ áp dụng cho nhập
    # kho thủ công thường (tránh gõ nhầm ngày), xem receive() cho cùng quy tắc bên kho NVL.
    if not skip_cap and received_dt < now - timedelta(days=15):
        raise DomainError("Ngày nhập không được quá 15 ngày trước thời điểm hiện tại.")
    return received_dt


def _create_units(db: Session, payload: dict, created_by: str, actor: User) -> list[FinishedGoodsUnit]:
    """Sinh 1 dòng LÔ duy nhất (quantity=total) — KHÔNG kiểm tra quyền, dùng nội bộ (vd
    approve_bottle tự động nhập kho thành phẩm sau khi KCS duyệt chiết, không đi qua quyền
    warehouse.receive). Trước đây sinh n=ceil(total/pack_size) dòng (1 dòng/vỉ) — 1 lô lớn
    (VD ca_total=190.000 vỉ) tạo ra hàng trăm nghìn INSERT row-by-row, qua mạng tới SQL
    Server mất ~1 giờ, Cloudflare cắt ở 100s → nút Duyệt "treo" (xem
    docs/WMS-LOT-LEVEL-REDESIGN.md). Giờ luôn ĐÚNG 1 INSERT bất kể quy mô lô; `pack_size`
    không còn dùng để tách dòng ở đây nữa, chỉ còn ý nghĩa ở tầng đọc (xem _pack_divisor) để
    quy đổi ngược `quantity` (SL đơn vị nhỏ) ra số vỉ/keg hiển thị. Trả về list 1 phần tử để
    giữ nguyên chữ ký cho các nơi gọi hiện có (vòng lặp `for u in units` tự động chỉ còn 1
    lần — approve_bottle nhờ vậy cũng tự động chỉ còn 1 cạnh phả hệ thay vì vòng lặp)."""
    total = float(payload.get("total", 0) or 0)
    unit_type = payload.get("unit_type") or "vi"
    # Phòng thủ: unit_type ghi MỚI vào 1 dòng tồn kho phải khớp CHÍNH XÁC 1 mã đang có trong
    # Danh mục Loại đơn vị tồn kho — mọi logic đọc lại (_pack_divisor/_divide_by_pack_codes) so
    # khớp theo chuỗi, 1 mã lạ (VD do gán sai ở Danh mục Sản phẩm) sẽ lặng lẽ không được nhận
    # diện là "chia theo pack_size" và đếm sai tồn kho hàng loạt mà không có lỗi nào báo trước.
    if not db.execute(select(UnitTypeCatalog.unit_type_id)
                      .where(UnitTypeCatalog.code == unit_type)).first():
        raise DomainError(f"Loại đơn vị '{unit_type}' không có trong Danh mục Loại đơn vị tồn kho.")
    if total <= 0:
        raise DomainError("Tổng số lượng phải > 0.")
    now = utcnow()
    received_dt = _parse_received_at(payload.get("received_at"), now,
                                     skip_cap=bool(payload.get("is_opening_balance") or payload.get("skip_date_cap")))
    loc_id = payload.get("loc_id") or None
    loc = None
    if loc_id:
        loc = db.get(WmsLocation, loc_id)
        if not loc:
            raise NotFoundError("Vị trí không tồn tại.")
    prefix = unit_type.upper() if unit_type else "VI"
    stamp = f"{now:%y%m%d}-{new_id()[:4].upper()}"
    u = FinishedGoodsUnit(unit_id=new_id(), unit_code=f"{prefix}-{stamp}-0001", unit_type=unit_type,
                         finished_product_id=payload.get("finished_product_id"),
                         product_name=payload.get("product_name"), lot_code=payload.get("lot_code"),
                         quantity=total, status="stored", created_by=created_by, created_at=received_dt,
                         location_id=loc_id, source=payload.get("source"))
    if payload.get("is_opening_balance"):
        # Tồn đầu đã yêu cầu quyền ADMIN riêng (xem build_units) — coi như tự động "duyệt nhập
        # kho" ngay lúc tạo, không bắt qua thêm bước Trưởng bộ phận kho duyệt nữa (khác
        # source="manual", xem docstring FinishedGoodsUnit.source).
        u.received_confirmed_by = created_by
        u.received_confirmed_at = now
    if loc and not _capacity_ok(db, loc, u):
        raise DomainError(f"Vị trí {loc.code} đã đầy (sức chứa {loc.capacity}).")
    db.add(u)
    db.flush()
    record_audit(db, entity_type="finished_goods_unit", entity_id=u.unit_id, action="build", actor=actor,
                 after={"unit_type": unit_type, "total": total, "lot_code": payload.get("lot_code")},
                 reason=payload.get("reason"))
    db.commit()
    db.refresh(u)
    return [u]


def _next_wms_lot_code(db: Session, year: int) -> str:
    """Mã lô TP tự sinh cho "Nhập kho thủ công" (mirror services/warehouse.py::_next_lot_code
    cho Kho công ty NVL) — người dùng không tự gõ tay nữa, tránh trùng/nhầm lô. Tăng dần theo
    năm, năm sau đánh lại từ 1; kiểm tra trùng với MỌI lot_code đã có trong finished_goods_unit
    (kể cả từ chiết/tồn đầu/import/near-expiry/consigned), không chỉ lô cùng năm."""
    count = db.execute(select(func.count()).select_from(FinishedGoodsUnit)
                       .where(FinishedGoodsUnit.lot_code.like(f"{year}-%"))).scalar_one()
    while True:
        count += 1
        code = f"{year}-{count:05d}"
        exists = db.execute(select(FinishedGoodsUnit.unit_id)
                            .where(FinishedGoodsUnit.lot_code == code)).first()
        if not exists:
            return code


def build_units(db: Session, payload: dict, user: User) -> list[FinishedGoodsUnit]:
    require_perm(user, "warehouse.receive")
    # Nhập kho thủ công VÀ Nhập tồn đầu đều bắt buộc chọn vị trí kho ngay lúc nhập — không còn
    # cho phép "(chưa cất)" ở 2 luồng này (khác với đơn vị tạo tự động sau khi duyệt chiết,
    # nơi để trống vẫn hợp lệ vì có tab "Cất vào vị trí" xử lý riêng sau).
    if not payload.get("loc_id"):
        raise DomainError("Vui lòng chọn vị trí kho trước khi nhập.")
    _assert_loc_scope(db, user, payload["loc_id"])
    if payload.get("is_opening_balance"):
        # Nhập tồn đầu kho thành phẩm — CHỈ ADMIN, khác nhập kho thủ công thường (mở cho ai có
        # quyền warehouse.receive) vì đây là thao tác chỉnh số liệu gốc, không qua chiết thật.
        require_role(user, Role.ADMIN)
    else:
        # Nhập kho thủ công thường — Lô TP tự sinh nếu người gọi KHÔNG tự truyền lot_code (giao
        # diện "Nhập kho thủ công" đã bỏ hẳn ô nhập tay, xem _next_wms_lot_code); vẫn cho phép
        # truyền lot_code tường minh (import Excel/nội bộ/test fixture cần mã cố định) — không
        # ép ghi đè. Luôn đánh dấu source="manual" để bắt qua bước Trưởng bộ phận kho duyệt
        # trước khi xuất được (xem confirm_receipt_by_lot + create_shipment/_consume_lot_rows).
        payload = dict(payload)
        if not payload.get("lot_code"):
            payload["lot_code"] = _next_wms_lot_code(db, utcnow().year)
        payload["source"] = "manual"
    return _create_units(db, payload, user.username, user)


def import_opening_balance_units(db: Session, content: bytes, user: User) -> dict:
    """Import Excel hàng loạt tồn đầu kho thành phẩm (WMS) — CHỈ ADMIN. Mẫu 4 cột bắt buộc:
    NGÀY NHẬP, MÃ SẢN PHẨM, LÔ, SỐ LƯỢNG (pack_size/unit_type tự lấy theo danh mục Sản phẩm,
    Excel không cần khai lại) + cột VỊ TRÍ (mã vị trí kho — BẮT BUỘC, xem build_units()). Mỗi
    dòng hợp lệ gọi lại build_units() với is_opening_balance=True — build_units()/_create_units()
    tự commit từng dòng nên 1 dòng lỗi (kể cả thiếu vị trí) không làm mất các dòng đã nhập
    thành công trước đó, chỉ báo lỗi riêng dòng đó trong "failed"."""
    require_role(user, Role.ADMIN)
    rows = parse_opening_balance_sheet(content, "MÃ SẢN PHẨM", optional_headers={"vi_tri": "VỊ TRÍ"})
    created, failed = [], []
    for r in rows:
        if r["error"]:
            failed.append({"row": r["row"], "reason": r["error"]})
            continue
        fp = db.execute(select(FinishedProduct).where(FinishedProduct.code == r["ma"])).scalar_one_or_none()
        if not fp:
            failed.append({"row": r["row"], "reason": f"Không tìm thấy sản phẩm mã '{r['ma']}'."})
            continue
        loc_id = None
        if r["vi_tri"]:
            loc = db.execute(select(WmsLocation).where(WmsLocation.code == r["vi_tri"])).scalar_one_or_none()
            if not loc:
                failed.append({"row": r["row"], "reason": f"Không tìm thấy vị trí kho mã '{r['vi_tri']}'."})
                continue
            loc_id = loc.loc_id
        try:
            units = build_units(db, {
                "finished_product_id": fp.finished_product_id, "product_name": fp.code,
                "lot_code": r["lo"] or None, "total": r["so_luong"], "pack_size": fp.pack_size,
                "unit_type": fp.unit_type, "loc_id": loc_id,
                "received_at": r["ngay_nhap"].isoformat() if r["ngay_nhap"] else None,
                "reason": "Nhập tồn đầu (import Excel)", "is_opening_balance": True,
            }, user)
        except DomainError as e:
            failed.append({"row": r["row"], "reason": str(e)})
            continue
        created.append({"row": r["row"], "product_code": fp.code, "unit_code": units[0].unit_code,
                        "quantity": units[0].quantity})
    return {"created": created, "failed": failed, "total": len(rows)}


# ---- Nhập bia cận date: khai báo trực tiếp theo Sản phẩm + SL + Vị trí, sinh lô riêng ----

def _gen_candate_lot_code(db: Session) -> str:
    """Sinh mã lô cận date DUY NHẤT, không trùng với lô sản xuất thật nào — cố ý KHÔNG tái sử
    dụng lot_code của lô chiết gốc (khác trước đây, xem create_near_expiry_entry): thực tế tồn
    cận date thường là gộp từ nhiều lô sản xuất khác nhau, không thể quy về đúng 1 lô — tự sinh
    riêng để list_lot_summaries (nhóm theo product_name+lot_code) tách nó thành 1 DÒNG RIÊNG
    trong Xuất kho thay vì gộp lẫn vào tồn thường của SKU đó."""
    for _ in range(5):
        code = f"CD{utcnow():%y%m%d}-{new_id()[:6].upper()}"
        exists = db.execute(select(FinishedGoodsUnit.unit_id)
                            .where(FinishedGoodsUnit.lot_code == code)).first()
        if not exists:
            return code
    raise DomainError("Không sinh được mã lô cận date, thử lại.")


def create_near_expiry_entry(db: Session, finished_product_id: str, quantity: int,
                             location_id: str | None, user: User, note: str = None) -> dict:
    """Khai báo "Nhập bia cận date": chỉ cần chọn Sản phẩm + Số lượng + Vị trí kho nhận (KHÔNG
    còn tự nhận lô chiết theo ngày giờ — xem docstring NearExpiryEntry). CHƯA tăng tồn kho —
    chỉ tự sinh sẵn 1 lot_code riêng (_gen_candate_lot_code) và ghi bản khai chờ duyệt
    (approved_by=None). Trưởng bộ phận kho duyệt (approve_near_expiry_entry) mới thực sự tạo
    FinishedGoodsUnit + tăng tồn kho."""
    require_perm(user, "warehouse.receive")
    fp = db.get(FinishedProduct, finished_product_id)
    if not fp:
        raise NotFoundError("Không tìm thấy sản phẩm tương ứng.")
    if quantity <= 0:
        raise DomainError("Số lượng phải > 0.")
    unit_type = fp.unit_type or "vi"
    product_name = fp.code
    lot_code = _gen_candate_lot_code(db)
    entry = NearExpiryEntry(entry_id=new_id(), direction="in", finished_product_id=finished_product_id,
                            product_name=product_name, lot_code=lot_code, unit_type=unit_type,
                            quantity=quantity, location_id=location_id, declared_at=utcnow(),
                            note=note, created_by=user.username, created_at=utcnow())
    db.add(entry)
    record_audit(db, entity_type="near_expiry_entry", entity_id=entry.entry_id, action="create", actor=user,
                after={"product_name": product_name, "lot_code": lot_code, "count": quantity})
    db.commit()
    return {"entry_id": entry.entry_id, "product_name": product_name, "lot_code": lot_code,
            "unit_type": unit_type, "count": quantity}


def update_near_expiry_entry(db: Session, entry_id: str, payload: dict, user: User) -> dict:
    """Sửa 1 bản khai "Nhập bia cận date" ĐANG CHỜ DUYỆT — cho sửa toàn bộ (sản phẩm/số lượng/
    vị trí/ghi chú) vì chưa có FinishedGoodsUnit nào được tạo (an toàn tuyệt đối). Chặn nếu đã
    duyệt (approved_by) hoặc đã hoàn tác."""
    require_perm(user, "warehouse.receive")
    entry = db.get(NearExpiryEntry, entry_id)
    if not entry or entry.direction != "in":
        raise NotFoundError("Không tìm thấy bản khai.")
    if entry.reversed:
        raise DomainError("Bản khai này đã bị hủy — không thể sửa.")
    if entry.approved_by:
        raise DomainError("Bản khai này đã được duyệt — không thể sửa.")
    if payload.get("finished_product_id") and payload["finished_product_id"] != entry.finished_product_id:
        fp = db.get(FinishedProduct, payload["finished_product_id"])
        if not fp:
            raise NotFoundError("Không tìm thấy sản phẩm tương ứng.")
        entry.finished_product_id = fp.finished_product_id
        entry.product_name = fp.code
        entry.unit_type = fp.unit_type or "vi"
    if payload.get("quantity") is not None:
        if payload["quantity"] <= 0:
            raise DomainError("Số lượng phải > 0.")
        entry.quantity = payload["quantity"]
    if "location_id" in payload:
        entry.location_id = payload["location_id"]
    if "note" in payload:
        entry.note = payload["note"]
    record_audit(db, entity_type="near_expiry_entry", entity_id=entry.entry_id, action="update", actor=user,
                after={"product_name": entry.product_name, "count": entry.quantity})
    db.commit()
    return {"entry_id": entry.entry_id}


def approve_near_expiry_entry(db: Session, entry_id: str, user: User) -> dict:
    """Trưởng bộ phận kho duyệt 1 bản khai "Nhập bia cận date" đang chờ — LÚC NÀY mới thực sự
    tạo FinishedGoodsUnit (is_near_expiry=True, coi như đã "duyệt nhập kho" luôn vì chính hành
    động duyệt tạo ra dòng tồn kho) và tăng tồn kho công ty. Sau khi duyệt: khoá hẳn — không
    sửa/hoàn tác được nữa (mirror services/warehouse.py::approve_count)."""
    require_perm(user, "wms.confirm_receipt")
    entry = db.get(NearExpiryEntry, entry_id)
    if not entry or entry.direction != "in":
        raise NotFoundError("Không tìm thấy bản khai.")
    if entry.reversed:
        raise DomainError("Bản khai này đã bị hủy — không thể duyệt.")
    if entry.approved_by:
        raise DomainError("Bản khai này đã được duyệt trước đó.")
    fp = db.get(FinishedProduct, entry.finished_product_id) if entry.finished_product_id else None
    pack_size = (fp.pack_size or 1) if fp else 1
    units = _create_units(db, {
        "finished_product_id": entry.finished_product_id, "product_name": entry.product_name,
        "lot_code": entry.lot_code, "total": entry.quantity * pack_size, "pack_size": pack_size,
        "unit_type": entry.unit_type, "loc_id": entry.location_id,
    }, created_by=entry.created_by or user.username, actor=user)
    now = utcnow()
    for u in units:
        u.is_near_expiry = True
        u.received_confirmed_by = user.username
        u.received_confirmed_at = now
    entry.unit_codes = ",".join(u.unit_code for u in units)
    entry.approved_by = user.username
    entry.approved_at = now
    record_audit(db, entity_type="near_expiry_entry", entity_id=entry.entry_id, action="approve", actor=user,
                after={"product_name": entry.product_name, "lot_code": entry.lot_code, "count": entry.quantity})
    db.commit()
    return {"entry_id": entry.entry_id, "count": entry.quantity, "unit_codes": [u.unit_code for u in units]}


def list_near_expiry_entries(db: Session) -> list[dict]:
    entries = db.execute(select(NearExpiryEntry).order_by(NearExpiryEntry.created_at.desc())).scalars().all()
    out = []
    for e in entries:
        shipment = db.get(Shipment, e.shipment_id) if e.shipment_id else None
        loc = db.get(WmsLocation, e.location_id) if e.location_id else None
        pending = e.direction == "in" and not e.reversed and not e.approved_by
        out.append({"entry_id": e.entry_id, "direction": e.direction,
                    "finished_product_id": e.finished_product_id, "product_name": e.product_name,
                    "lot_code": e.lot_code, "unit_type": e.unit_type, "quantity": e.quantity,
                    "location_code": loc.code if loc else None,
                    "declared_at": e.declared_at, "shipment_code": shipment.shipment_code if shipment else None,
                    "note": e.note, "created_by": e.created_by, "created_at": e.created_at,
                    "reversed": e.reversed, "approved_by": e.approved_by, "approved_at": e.approved_at,
                    "can_edit": pending, "can_approve": pending, "can_undo": pending})
    return out


def undo_near_expiry_entry(db: Session, entry_id: str, user: User) -> dict:
    """Hủy 1 bản khai "Nhập bia cận date" (direction="in") ĐANG CHỜ DUYỆT — chỉ đánh dấu
    reversed, KHÔNG có FinishedGoodsUnit nào để xoá (chưa tăng tồn kho, xem
    create_near_expiry_entry). Chặn nếu đã duyệt — duyệt là mốc khóa cuối cùng, không hoàn tác
    được nữa (mirror services/warehouse.py::approve_count/undo_count)."""
    require_perm(user, "warehouse.receive")
    entry = db.get(NearExpiryEntry, entry_id)
    if not entry:
        raise NotFoundError("Không tìm thấy bản khai.")
    if entry.direction != "in":
        raise DomainError("Chỉ có thể hủy bản khai \"Nhập bia cận date\" (không áp dụng cho dòng tự động khi xuất kho).")
    if entry.reversed:
        raise DomainError("Bản khai này đã được hủy trước đó.")
    if entry.approved_by:
        raise DomainError("Bản khai này đã được duyệt — không thể hủy.")
    entry.reversed = True
    record_audit(db, entity_type="near_expiry_entry", entity_id=entry.entry_id, action="undo", actor=user,
                before={"count": entry.quantity}, after={"reversed": True})
    db.commit()
    return {"entry_id": entry.entry_id}


# ---- Nhập bia gửi: mirror y hệt bia cận date, khác ở chỗ được ưu tiên xuất TRƯỚC cả cận
# date (xem sort trong VIEWS.wms xuatkho) và bị TRỪ khỏi báo cáo xuất theo ca/ngày (xem
# finished_goods_shift_report) — vì đây là phần bia ĐÃ tính vào lượt xuất buổi sáng (phiếu
# gốc), xuất lại lần 2 sẽ bị đếm trùng nếu không trừ. ----

def _gen_consigned_lot_code(db: Session) -> str:
    """Sinh mã lô bia gửi DUY NHẤT — mirror _gen_candate_lot_code, đổi tiền tố GUI để phân
    biệt trực quan với lô cận date (CD) và lô sản xuất thật."""
    for _ in range(5):
        code = f"GUI{utcnow():%y%m%d}-{new_id()[:6].upper()}"
        exists = db.execute(select(FinishedGoodsUnit.unit_id)
                            .where(FinishedGoodsUnit.lot_code == code)).first()
        if not exists:
            return code
    raise DomainError("Không sinh được mã lô bia gửi, thử lại.")


def create_consigned_entry(db: Session, finished_product_id: str, quantity: int,
                           location_id: str, vehicle_id: str, user: User, note: str = None) -> dict:
    """Khai báo "Nhập bia gửi": xe đã xuất phiếu đi giao trong ngày nhưng giao không hết,
    mang phần dư về gửi lại kho — mirror y hệt create_near_expiry_entry (Sản phẩm + Số lượng
    + Vị trí kho nhận trực tiếp, tự sinh lot_code riêng qua _gen_consigned_lot_code, đánh dấu
    is_consigned=True) + ghi 1 dòng lịch sử riêng (ConsignedEntry, direction="in"). CHƯA tăng
    tồn kho tới khi duyệt (mirror create_near_expiry_entry) — xem approve_consigned_entry.
    Khác NearExpiryEntry: BẮT BUỘC vị trí kho nhận (không cho "chưa cất") và bắt buộc biển số
    xe đã mang bia về — dùng để hiện "xe đã gửi" ở picker Xuất kho (xem list_lot_summaries).
    Số lượng khai + sản phẩm PHẢI khớp với chính phiếu xuất kho của xe đó trong khoảng [Ca 2
    ngày hôm trước 14h VN, hiện tại] — xem _consigned_available_qty; chặn khai khống/vượt số
    lượng thực tế đã xuất."""
    require_perm(user, "warehouse.receive")
    fp = db.get(FinishedProduct, finished_product_id)
    if not fp:
        raise NotFoundError("Không tìm thấy sản phẩm tương ứng.")
    if quantity <= 0:
        raise DomainError("Số lượng phải > 0.")
    if not location_id or not db.get(WmsLocation, location_id):
        raise DomainError("Vui lòng chọn vị trí kho nhận trước khi nhập bia gửi.")
    if not vehicle_id or not db.get(Vehicle, vehicle_id):
        raise DomainError("Vui lòng chọn biển số xe.")
    available = _consigned_available_qty(db, vehicle_id, finished_product_id)
    if available <= 0:
        raise DomainError("Xe này không có phiếu xuất kho chứa sản phẩm này trong khoảng cho phép "
                          "(từ 14h Ca 2 ngày hôm trước đến hiện tại) — không thể nhập bia gửi.")
    if quantity > available:
        raise DomainError(f"Số lượng bia gửi ({quantity}) vượt quá số lượng xe đã xuất cho sản phẩm "
                          f"này còn lại có thể nhận gửi ({available:g}) trong khoảng cho phép.")
    unit_type = fp.unit_type or "vi"
    product_name = fp.code
    lot_code = _gen_consigned_lot_code(db)
    entry = ConsignedEntry(entry_id=new_id(), direction="in", finished_product_id=finished_product_id,
                           product_name=product_name, lot_code=lot_code, unit_type=unit_type,
                           quantity=quantity, location_id=location_id, vehicle_id=vehicle_id,
                           declared_at=utcnow(),
                           note=note, created_by=user.username, created_at=utcnow())
    db.add(entry)
    record_audit(db, entity_type="consigned_entry", entity_id=entry.entry_id, action="create", actor=user,
                after={"product_name": product_name, "lot_code": lot_code, "count": quantity})
    db.commit()
    return {"entry_id": entry.entry_id, "product_name": product_name, "lot_code": lot_code,
            "unit_type": unit_type, "count": quantity}


def update_consigned_entry(db: Session, entry_id: str, payload: dict, user: User) -> dict:
    """Sửa 1 bản khai "Nhập bia gửi" ĐANG CHỜ DUYỆT — mirror update_near_expiry_entry."""
    require_perm(user, "warehouse.receive")
    entry = db.get(ConsignedEntry, entry_id)
    if not entry or entry.direction != "in":
        raise NotFoundError("Không tìm thấy bản khai.")
    if entry.reversed:
        raise DomainError("Bản khai này đã bị hủy — không thể sửa.")
    if entry.approved_by:
        raise DomainError("Bản khai này đã được duyệt — không thể sửa.")
    if payload.get("finished_product_id") and payload["finished_product_id"] != entry.finished_product_id:
        fp = db.get(FinishedProduct, payload["finished_product_id"])
        if not fp:
            raise NotFoundError("Không tìm thấy sản phẩm tương ứng.")
        entry.finished_product_id = fp.finished_product_id
        entry.product_name = fp.code
        entry.unit_type = fp.unit_type or "vi"
    if payload.get("quantity") is not None:
        if payload["quantity"] <= 0:
            raise DomainError("Số lượng phải > 0.")
        entry.quantity = payload["quantity"]
    if "location_id" in payload:
        entry.location_id = payload["location_id"]
    if "note" in payload:
        entry.note = payload["note"]
    if entry.vehicle_id:
        available = _consigned_available_qty(db, entry.vehicle_id, entry.finished_product_id,
                                              exclude_entry_id=entry.entry_id)
        if entry.quantity > available:
            raise DomainError(f"Số lượng bia gửi ({entry.quantity}) vượt quá số lượng xe đã xuất cho "
                              f"sản phẩm này còn lại có thể nhận gửi ({available:g}) trong khoảng cho phép.")
    record_audit(db, entity_type="consigned_entry", entity_id=entry.entry_id, action="update", actor=user,
                after={"product_name": entry.product_name, "count": entry.quantity})
    db.commit()
    return {"entry_id": entry.entry_id}


def approve_consigned_entry(db: Session, entry_id: str, user: User) -> dict:
    """Trưởng bộ phận kho duyệt 1 bản khai "Nhập bia gửi" đang chờ — mirror
    approve_near_expiry_entry (LÚC NÀY mới tạo FinishedGoodsUnit + tăng tồn kho; sau khi duyệt
    khoá hẳn, không sửa/hoàn tác được nữa)."""
    require_perm(user, "wms.confirm_receipt")
    entry = db.get(ConsignedEntry, entry_id)
    if not entry or entry.direction != "in":
        raise NotFoundError("Không tìm thấy bản khai.")
    if entry.reversed:
        raise DomainError("Bản khai này đã bị hủy — không thể duyệt.")
    if entry.approved_by:
        raise DomainError("Bản khai này đã được duyệt trước đó.")
    fp = db.get(FinishedProduct, entry.finished_product_id) if entry.finished_product_id else None
    pack_size = (fp.pack_size or 1) if fp else 1
    units = _create_units(db, {
        "finished_product_id": entry.finished_product_id, "product_name": entry.product_name,
        "lot_code": entry.lot_code, "total": entry.quantity * pack_size, "pack_size": pack_size,
        "unit_type": entry.unit_type, "loc_id": entry.location_id,
    }, created_by=entry.created_by or user.username, actor=user)
    now = utcnow()
    for u in units:
        u.is_consigned = True
        u.received_confirmed_by = user.username
        u.received_confirmed_at = now
    entry.unit_codes = ",".join(u.unit_code for u in units)
    entry.approved_by = user.username
    entry.approved_at = now
    record_audit(db, entity_type="consigned_entry", entity_id=entry.entry_id, action="approve", actor=user,
                after={"product_name": entry.product_name, "lot_code": entry.lot_code, "count": entry.quantity})
    db.commit()
    return {"entry_id": entry.entry_id, "count": entry.quantity, "unit_codes": [u.unit_code for u in units]}


def list_consigned_entries(db: Session) -> list[dict]:
    entries = db.execute(select(ConsignedEntry).order_by(ConsignedEntry.created_at.desc())).scalars().all()
    out = []
    for e in entries:
        shipment = db.get(Shipment, e.shipment_id) if e.shipment_id else None
        loc = db.get(WmsLocation, e.location_id) if e.location_id else None
        vehicle = db.get(Vehicle, e.vehicle_id) if e.vehicle_id else None
        pending = e.direction == "in" and not e.reversed and not e.approved_by
        out.append({"entry_id": e.entry_id, "direction": e.direction,
                    "finished_product_id": e.finished_product_id, "product_name": e.product_name,
                    "lot_code": e.lot_code, "unit_type": e.unit_type, "quantity": e.quantity,
                    "location_code": loc.code if loc else None,
                    "vehicle_plate": vehicle.plate if vehicle else None,
                    "vehicle_code": vehicle.vehicle_code if vehicle else None,
                    "declared_at": e.declared_at, "shipment_code": shipment.shipment_code if shipment else None,
                    "note": e.note, "created_by": e.created_by, "created_at": e.created_at,
                    "reversed": e.reversed, "approved_by": e.approved_by, "approved_at": e.approved_at,
                    "can_edit": pending, "can_approve": pending, "can_undo": pending})
    return out


def undo_consigned_entry(db: Session, entry_id: str, user: User) -> dict:
    """Hủy 1 bản khai "Nhập bia gửi" (direction="in") ĐANG CHỜ DUYỆT — mirror
    undo_near_expiry_entry (chỉ đánh dấu reversed, chưa có FinishedGoodsUnit nào để xoá; chặn
    nếu đã duyệt)."""
    require_perm(user, "warehouse.receive")
    entry = db.get(ConsignedEntry, entry_id)
    if not entry:
        raise NotFoundError("Không tìm thấy bản khai.")
    if entry.direction != "in":
        raise DomainError("Chỉ có thể hủy bản khai \"Nhập bia gửi\" (không áp dụng cho dòng tự động khi xuất kho).")
    if entry.reversed:
        raise DomainError("Bản khai này đã được hủy trước đó.")
    if entry.approved_by:
        raise DomainError("Bản khai này đã được duyệt — không thể hủy.")
    entry.reversed = True
    record_audit(db, entity_type="consigned_entry", entity_id=entry.entry_id, action="undo", actor=user,
                before={"count": entry.quantity}, after={"reversed": True})
    db.commit()
    return {"entry_id": entry.entry_id}


# ---- Nhập từ nhà máy khác: mirror bia cận date (khai báo -> duyệt mới tăng tồn kho) nhưng
# KHÔNG có xử lý đặc biệt gì sau khi duyệt (không ưu tiên xuất, không trừ báo cáo) — cờ
# is_factory_import trên đơn vị chỉ để dành cho báo cáo riêng sau này. ----

def create_factory_import_entry(db: Session, finished_product_id: str, quantity: int,
                                location_id: str, factory_id: str, user: User, note: str = None,
                                received_at: str = None) -> dict:
    """Khai báo "Nhập từ nhà máy khác": Sản phẩm + Số lượng + Vị trí kho nhận + Nhà máy nguồn
    (Danh mục Nhà máy) đều bắt buộc — factory_id là "dấu hiệu" để biết bia này không do nhà máy
    đang chạy hệ thống này sản xuất. CHƯA tăng tồn kho — chỉ ghi bản khai chờ duyệt, xem
    approve_factory_import_entry. received_at ("Ngày nhập") lưu vào declared_at — mặc định thời
    điểm khai báo nếu để trống; đây cũng là ngày sẽ gán cho FinishedGoodsUnit.created_at lúc
    duyệt (xem approve_factory_import_entry), không phải thời điểm bấm Duyệt."""
    require_perm(user, "warehouse.receive")
    fp = db.get(FinishedProduct, finished_product_id)
    if not fp:
        raise NotFoundError("Không tìm thấy sản phẩm tương ứng.")
    if quantity <= 0:
        raise DomainError("Số lượng phải > 0.")
    if not location_id or not db.get(WmsLocation, location_id):
        raise DomainError("Vui lòng chọn vị trí kho nhận.")
    _assert_loc_scope(db, user, location_id)
    if not factory_id or not db.get(FactoryLocation, factory_id):
        raise DomainError("Vui lòng chọn nhà máy nguồn.")
    unit_type = fp.unit_type or "vi"
    product_name = fp.code
    now = utcnow()
    declared_at = _parse_received_at(received_at, now)
    entry = FactoryImportEntry(entry_id=new_id(), finished_product_id=finished_product_id,
                               product_name=product_name, unit_type=unit_type, quantity=quantity,
                               location_id=location_id, factory_id=factory_id, declared_at=declared_at,
                               note=note, created_by=user.username, created_at=now)
    db.add(entry)
    record_audit(db, entity_type="factory_import_entry", entity_id=entry.entry_id, action="create", actor=user,
                after={"product_name": product_name, "count": quantity, "factory_id": factory_id})
    db.commit()
    return {"entry_id": entry.entry_id, "product_name": product_name, "unit_type": unit_type, "count": quantity}


def update_factory_import_entry(db: Session, entry_id: str, payload: dict, user: User) -> dict:
    """Sửa 1 bản khai "Nhập từ nhà máy khác" ĐANG CHỜ DUYỆT — mirror update_near_expiry_entry."""
    require_perm(user, "warehouse.receive")
    entry = db.get(FactoryImportEntry, entry_id)
    if not entry:
        raise NotFoundError("Không tìm thấy bản khai.")
    if entry.reversed:
        raise DomainError("Bản khai này đã bị hủy — không thể sửa.")
    if entry.approved_by:
        raise DomainError("Bản khai này đã được duyệt — không thể sửa.")
    if payload.get("finished_product_id") and payload["finished_product_id"] != entry.finished_product_id:
        fp = db.get(FinishedProduct, payload["finished_product_id"])
        if not fp:
            raise NotFoundError("Không tìm thấy sản phẩm tương ứng.")
        entry.finished_product_id = fp.finished_product_id
        entry.product_name = fp.code
        entry.unit_type = fp.unit_type or "vi"
    if payload.get("quantity") is not None:
        if payload["quantity"] <= 0:
            raise DomainError("Số lượng phải > 0.")
        entry.quantity = payload["quantity"]
    if payload.get("location_id"):
        if not db.get(WmsLocation, payload["location_id"]):
            raise NotFoundError("Không tìm thấy vị trí kho tương ứng.")
        _assert_loc_scope(db, user, payload["location_id"])
        entry.location_id = payload["location_id"]
    if payload.get("factory_id"):
        if not db.get(FactoryLocation, payload["factory_id"]):
            raise NotFoundError("Không tìm thấy nhà máy tương ứng.")
        entry.factory_id = payload["factory_id"]
    if "note" in payload:
        entry.note = payload["note"]
    if payload.get("received_at"):
        entry.declared_at = _parse_received_at(payload["received_at"], utcnow())
    record_audit(db, entity_type="factory_import_entry", entity_id=entry.entry_id, action="update", actor=user,
                after={"product_name": entry.product_name, "count": entry.quantity})
    db.commit()
    return {"entry_id": entry.entry_id}


def approve_factory_import_entry(db: Session, entry_id: str, user: User) -> dict:
    """Trưởng bộ phận kho duyệt 1 bản khai "Nhập từ nhà máy khác" đang chờ — mirror
    approve_near_expiry_entry (LÚC NÀY mới tạo FinishedGoodsUnit is_factory_import=True + tăng
    tồn kho; sau khi duyệt khoá hẳn). Lô tự sinh theo năm như "Nhập kho thủ công" thường (xem
    _next_wms_lot_code) — sau khi vào kho, đơn vị này KHÔNG khác gì hàng thường (không lô riêng
    như bia gửi/cận date) vì không cần tách dòng ở Xuất kho."""
    require_perm(user, "wms.confirm_receipt")
    entry = db.get(FactoryImportEntry, entry_id)
    if not entry:
        raise NotFoundError("Không tìm thấy bản khai.")
    if entry.reversed:
        raise DomainError("Bản khai này đã bị hủy — không thể duyệt.")
    if entry.approved_by:
        raise DomainError("Bản khai này đã được duyệt trước đó.")
    fp = db.get(FinishedProduct, entry.finished_product_id) if entry.finished_product_id else None
    pack_size = (fp.pack_size or 1) if fp else 1
    lot_code = _next_wms_lot_code(db, utcnow().year)
    units = _create_units(db, {
        "finished_product_id": entry.finished_product_id, "product_name": entry.product_name,
        "lot_code": lot_code, "total": entry.quantity * pack_size, "pack_size": pack_size,
        "unit_type": entry.unit_type, "loc_id": entry.location_id,
        # declared_at = "Ngày nhập" người dùng khai báo, có thể đã lùi quá 15 ngày so với lúc
        # bấm Duyệt (Trưởng bộ phận kho có thể duyệt trễ) — đã validate ở lúc khai báo rồi nên
        # bỏ qua cap 15 ngày ở đây (skip_date_cap), không phải is_opening_balance thật.
        "received_at": entry.declared_at, "skip_date_cap": True,
    }, created_by=entry.created_by or user.username, actor=user)
    now = utcnow()
    for u in units:
        u.is_factory_import = True
        u.received_confirmed_by = user.username
        u.received_confirmed_at = now
    entry.lot_code = lot_code
    entry.unit_codes = ",".join(u.unit_code for u in units)
    entry.approved_by = user.username
    entry.approved_at = now
    record_audit(db, entity_type="factory_import_entry", entity_id=entry.entry_id, action="approve", actor=user,
                after={"product_name": entry.product_name, "lot_code": lot_code, "count": entry.quantity})
    db.commit()
    return {"entry_id": entry.entry_id, "count": entry.quantity, "unit_codes": [u.unit_code for u in units]}


def list_factory_import_entries(db: Session) -> list[dict]:
    entries = db.execute(select(FactoryImportEntry).order_by(FactoryImportEntry.created_at.desc())).scalars().all()
    out = []
    for e in entries:
        loc = db.get(WmsLocation, e.location_id) if e.location_id else None
        wh = db.get(WmsWarehouse, loc.warehouse_id) if loc and loc.warehouse_id else None
        factory = db.get(FactoryLocation, e.factory_id) if e.factory_id else None
        pending = not e.reversed and not e.approved_by
        out.append({"entry_id": e.entry_id, "finished_product_id": e.finished_product_id,
                    "product_name": e.product_name, "lot_code": e.lot_code, "unit_type": e.unit_type,
                    "quantity": e.quantity, "location_code": loc.code if loc else None,
                    "location_name": loc.name if loc else None, "location_zone": loc.zone if loc else None,
                    "warehouse_name": wh.name if wh else None,
                    "factory_id": e.factory_id, "factory_name": factory.name if factory else None,
                    "declared_at": e.declared_at, "note": e.note, "created_by": e.created_by,
                    "created_at": e.created_at, "reversed": e.reversed, "approved_by": e.approved_by,
                    "approved_at": e.approved_at, "can_edit": pending, "can_approve": pending, "can_undo": pending})
    return out


def undo_factory_import_entry(db: Session, entry_id: str, user: User) -> dict:
    """Hủy 1 bản khai "Nhập từ nhà máy khác" ĐANG CHỜ DUYỆT — mirror undo_near_expiry_entry."""
    require_perm(user, "warehouse.receive")
    entry = db.get(FactoryImportEntry, entry_id)
    if not entry:
        raise NotFoundError("Không tìm thấy bản khai.")
    if entry.reversed:
        raise DomainError("Bản khai này đã được hủy trước đó.")
    if entry.approved_by:
        raise DomainError("Bản khai này đã được duyệt — không thể hủy.")
    entry.reversed = True
    record_audit(db, entity_type="factory_import_entry", entity_id=entry.entry_id, action="undo", actor=user,
                before={"count": entry.quantity}, after={"reversed": True})
    db.commit()
    return {"entry_id": entry.entry_id}


def adjust_bottle_finish_stock(db: Session, *, finished_product_id: str | None, product_name: str,
                               lot_code: str, unit_type: str, pack_size: int, delta_total: float,
                               bottle_id: str, actor: User) -> dict:
    """Điều chỉnh tồn kho thành phẩm khi Ca 1/2/3 của 1 mẻ chiết ĐÃ DUYỆT bị sửa lại (gọi lại
    finish_bottle sau approve_bottle) — trước đây approve_bottle chỉ nhập kho ĐÚNG 1 LẦN lúc
    duyệt, sửa Ca sau đó không cập nhật lại số vỉ/keg đã tạo, khiến tồn kho lệch khỏi sản
    lượng hiển thị (bug thực tế — xem finish_bottle). delta>0: tạo thêm vỉ/keg mới (mirror
    approve_bottle/_create_units). delta<0: bớt từ các đơn vị "stored" MỚI TẠO TRƯỚC (LIFO —
    ưu tiên hoàn tác đúng phần vừa cộng dư do sửa số, không đụng hàng cũ hơn đã có sẵn từ
    trước khi sửa). Chặn nếu tồn "stored" không đủ để bớt (nghĩa là 1 phần đã xuất/điều
    chuyển đi nơi khác) — không tự ý xóa hàng đã rời kho."""
    if delta_total == 0:
        return {"created": 0, "removed": 0}
    if delta_total > 0:
        units = _create_units(db, {
            "finished_product_id": finished_product_id, "product_name": product_name,
            "lot_code": lot_code, "total": delta_total, "pack_size": pack_size, "unit_type": unit_type,
        }, created_by=actor.username, actor=actor)
        for u in units:
            genealogy.add_edge(db, from_type="bottle", from_id=bottle_id, to_type="finished_goods_unit",
                               to_id=u.unit_id, relation="nhập kho (sửa SL)", quantity=u.quantity, uom=u.unit_type)
        divisor = _pack_divisor(db.get(FinishedProduct, finished_product_id) if finished_product_id else None,
                                unit_type, _divide_by_pack_codes(db))
        created_count = delta_total / divisor
        record_audit(db, entity_type="finished_goods_unit", entity_id=units[0].unit_id, action="adjust_bottle_finish",
                     actor=actor, before={"bottle_id": bottle_id, "delta": delta_total},
                     after={"created": created_count})
        db.commit()
        return {"created": created_count, "removed": 0}

    need = -delta_total
    candidates = db.execute(select(FinishedGoodsUnit).where(
        FinishedGoodsUnit.product_name == product_name, FinishedGoodsUnit.lot_code == lot_code,
        FinishedGoodsUnit.unit_type == unit_type, FinishedGoodsUnit.status == "stored",
    ).order_by(FinishedGoodsUnit.created_at.desc())).scalars().all()
    available = sum(u.quantity for u in candidates)
    if available < need:
        raise DomainError(
            f"Không thể tự động giảm tồn kho theo Ca mới — chỉ còn {available:g} {unit_type} đang ở trạng "
            f"thái tồn kho trong khi cần giảm {need:g} (phần còn lại có thể đã xuất/điều chuyển đi nơi khác). "
            "Hãy xử lý điều chỉnh tồn kho thủ công.")
    removed_ids = []
    remaining = need
    for u in candidates:
        if remaining <= 0:
            break
        if u.quantity <= remaining:
            remaining -= u.quantity
            removed_ids.append(u.unit_id)
            db.delete(u)
        else:
            u.quantity -= remaining
            remaining = 0
    # Chia nhỏ IN(...) theo lô 500 id — SQLite giới hạn số biến/câu lệnh (~999), số lượng đơn
    # vị cần xóa có thể lên tới hàng chục nghìn dòng nếu Ca bị sửa giảm rất nhiều.
    for i in range(0, len(removed_ids), 500):
        chunk = removed_ids[i:i + 500]
        edges = db.execute(select(GenealogyEdge).where(
            GenealogyEdge.to_type == "finished_goods_unit", GenealogyEdge.to_id.in_(chunk))).scalars().all()
        for e in edges:
            db.delete(e)
    divisor = _pack_divisor(db.get(FinishedProduct, finished_product_id) if finished_product_id else None,
                            unit_type, _divide_by_pack_codes(db))
    removed_count = need / divisor
    record_audit(db, entity_type="finished_goods_unit", entity_id=bottle_id, action="adjust_bottle_finish",
                 actor=actor, before={"bottle_id": bottle_id, "delta": delta_total},
                 after={"removed_units": removed_count, "removed_qty": need})
    db.commit()
    return {"created": 0, "removed": removed_count}


def _capacity_ok(db: Session, loc: WmsLocation, unit: FinishedGoodsUnit) -> bool:
    """Còn đủ chỗ cho TOÀN BỘ số vỉ/keg/lon mà `unit` đại diện hay không (quy đổi qua
    _pack_divisor — 1 dòng giờ có thể đại diện nhiều đơn vị đóng gói, không còn luôn là "1
    chỗ" như trước, xem docs/WMS-LOT-LEVEL-REDESIGN.md)."""
    fp = db.get(FinishedProduct, unit.finished_product_id) if unit.finished_product_id else None
    own_count = unit.quantity / _pack_divisor(fp, unit.unit_type, _divide_by_pack_codes(db))
    used = _location_used_count(db, loc.loc_id, exclude_unit_id=unit.unit_id)
    return used + own_count <= loc.capacity


def putaway(db: Session, unit_id: str, loc_id: str, user: User) -> dict:
    require_perm(user, "warehouse.issue")
    u = db.get(FinishedGoodsUnit, unit_id)
    if not u:
        raise NotFoundError("Vỉ/keg không tồn tại.")
    if u.status != "stored":
        raise DomainError(f"{u.unit_code} không ở trạng thái tồn kho (đã xuất/đã phân rã) — không thể cất.")
    loc = db.get(WmsLocation, loc_id)
    if not loc:
        raise NotFoundError("Vị trí không tồn tại.")
    _assert_wh_scope(db, user, loc.warehouse_id)
    if not _capacity_ok(db, loc, u):
        raise DomainError(f"Vị trí {loc.code} đã đầy (sức chứa {loc.capacity}).")
    before = {"location": u.location_id, "status": u.status}
    u.location_id = loc.loc_id
    u.status = "stored"
    record_audit(db, entity_type="finished_goods_unit", entity_id=unit_id, action="putaway", actor=user,
                 before=before, after={"location": loc.code})
    db.commit()
    return {"unit_code": u.unit_code, "location": loc.code, "status": u.status}


def transfer_units(db: Session, unit_ids: list, to_loc_id: str, user: User) -> dict:
    """Điều chuyển nội bộ theo unit_id cụ thể (khác relocate_batch — chọn theo số lượng, xem
    đó): đổi vị trí cho các dòng lô chỉ định — vị trí nguồn giảm, vị trí đích tăng (không đổi
    tổng tồn toàn kho). "moved" trả về là tổng số vỉ/keg/lon quy đổi (SUM(quantity)/pack_size
    từng dòng), KHÔNG phải số dòng — 1 dòng giờ có thể đại diện nhiều đơn vị đóng gói."""
    require_perm(user, "warehouse.issue")
    if not unit_ids:
        raise DomainError("Phải chọn ít nhất 1 đơn vị để điều chuyển.")
    to_loc = db.get(WmsLocation, to_loc_id)
    if not to_loc:
        raise NotFoundError("Vị trí đích không tồn tại.")

    units = []
    for unit_id in unit_ids:
        u = db.get(FinishedGoodsUnit, unit_id)
        if not u:
            raise NotFoundError("Vỉ/keg/lon không tồn tại.")
        if u.status != "stored":
            raise DomainError(f"{u.unit_code} không ở trạng thái tồn kho (đã xuất/đã phân rã) — không thể điều chuyển.")
        units.append(u)

    fp_cache: dict = {}
    divide_codes = _divide_by_pack_codes(db)
    def _divisor_of(u):
        if u.finished_product_id not in fp_cache:
            fp_cache[u.finished_product_id] = db.get(FinishedProduct, u.finished_product_id) if u.finished_product_id else None
        return _pack_divisor(fp_cache[u.finished_product_id], u.unit_type, divide_codes)

    moving_in = [u for u in units if u.location_id != to_loc_id]
    if moving_in:
        used_at_dest = _location_used_count(db, to_loc_id)
        moving_in_count = sum(u.quantity / _divisor_of(u) for u in moving_in)
        if used_at_dest + moving_in_count > to_loc.capacity:
            raise DomainError(f"Vị trí {to_loc.code} không đủ sức chứa (sức chứa {to_loc.capacity}, "
                              f"hiện có {used_at_dest:g}, cần thêm {moving_in_count:g}).")

    loc_by = {l.loc_id: l for l in db.execute(select(WmsLocation)).scalars().all()}
    from_codes = [loc_by[u.location_id].code if u.location_id in loc_by else None for u in units]
    unit_codes = [u.unit_code for u in units]
    moved_count = sum(u.quantity / _divisor_of(u) for u in units)
    for u in units:
        u.location_id = to_loc_id
    record_audit(db, entity_type="finished_goods_unit", entity_id=new_id(), action="transfer", actor=user,
                 before={"unit_codes": unit_codes, "from_locations": from_codes},
                 after={"unit_codes": unit_codes, "to_location": to_loc.code})
    db.commit()
    return {"moved": moved_count, "to_location": to_loc.code, "unit_codes": unit_codes}


def _decompose_one_pack_unit(db: Session, u: FinishedGoodsUnit, actor_username: str) -> list:
    """Sinh 1 dòng LON từ 1 dòng đơn vị ĐÓNG GÓI bất kỳ (Vỉ, Két, Lốc... — bất kỳ loại nào có
    divide_by_pack_size=True trong Danh mục Loại đơn vị tồn kho, xem decompose_unit/
    decompose_batch; KHÔNG còn giới hạn riêng "vỉ" như tên hàm cũ). unit_type đích luôn là mã
    hệ thống dùng chung "lon" (không phải luôn lon vật lý — suy danh từ hiển thị thật từ tên
    sản phẩm ở tầng đọc, xem genealogy.py::_small_unit_noun/wms.py::_unit_noun/
    views_ext.js::smallUnitNoun — KHÔNG đổi ở đây để không phá vỡ mọi chỗ đang lọc theo
    unit_type=="lon"). quantity vốn đã tính theo SL nhỏ nhất ngay từ đầu (xem
    docs/WMS-LOT-LEVEL-REDESIGN.md) nên dòng lon KẾ THỪA NGUYÊN quantity của dòng nguồn — phân
    rã không đổi tổng số lon, chỉ đổi unit_type; không cần nhân/chia pack_size ở đây (khác hẳn
    trước đây khi 1 dòng=1 vỉ, quantity=lon/vỉ, phải sinh round(quantity) dòng lon riêng lẻ).
    Đánh dấu dòng nguồn status="decomposed" (không xóa, giữ để truy vết genealogy/audit, loại
    khỏi mọi truy vấn tồn khả dụng). Dòng lon kế thừa created_at của dòng nguồn để FIFO tính
    đúng theo tuổi bia thật."""
    stamp = f"{utcnow():%y%m%d}-{new_id()[:4].upper()}"
    lon = FinishedGoodsUnit(unit_id=new_id(), unit_code=f"LON-{stamp}-0001", unit_type="lon",
                            finished_product_id=u.finished_product_id, product_name=u.product_name,
                            lot_code=u.lot_code, quantity=u.quantity, status="stored", location_id=u.location_id,
                            created_by=actor_username, created_at=u.created_at)
    db.add(lon)
    db.flush()
    u.status = "decomposed"
    genealogy.add_edge(db, from_type="finished_goods_unit", from_id=u.unit_id,
                       to_type="finished_goods_unit", to_id=lon.unit_id, relation="phân rã",
                       quantity=lon.quantity, uom="lon")
    return [lon]


def decompose_unit(db: Session, unit_id: str, user: User) -> dict:
    """Phân rã 1 dòng đơn vị đóng gói cụ thể (theo unit_id) thành 1 dòng lon — cho phép với
    BẤT KỲ loại đơn vị nào có divide_by_pack_size=True trong Danh mục Loại đơn vị tồn kho
    (Vỉ, Két, Lốc...), không còn giới hạn cứng riêng "vỉ"."""
    require_perm(user, "warehouse.issue")
    u = db.get(FinishedGoodsUnit, unit_id)
    if not u:
        raise NotFoundError("Đơn vị không tồn tại.")
    if u.unit_type not in _divide_by_pack_codes(db):
        raise DomainError("Chỉ có thể phân rã loại đơn vị đóng gói (xem Danh mục Loại đơn vị tồn kho).")
    if u.status != "stored":
        raise DomainError("Chỉ phân rã được đơn vị đang tồn kho (chưa xuất/chưa phân rã).")

    lon_qty = u.quantity
    lon_units = _decompose_one_pack_unit(db, u, user.username)
    record_audit(db, entity_type="finished_goods_unit", entity_id=u.unit_id, action="decompose", actor=user,
                 before={"unit_code": u.unit_code, "quantity": u.quantity,
                         "product_name": u.product_name, "lot_code": u.lot_code},
                 after={"lon_codes": [l.unit_code for l in lon_units], "count": lon_qty})
    db.commit()
    return {"source_unit_code": u.unit_code, "count": lon_qty,
            "lon_unit_codes": [l.unit_code for l in lon_units]}


def decompose_batch(db: Session, product_name: str, lot_code: str, unit_type: str, count: int, user: User) -> dict:
    """Phân rã N đơn vị đóng gói (Vỉ/Két/Lốc..., cũ nhất trước — FIFO) của 1 sản phẩm/lô thành
    lon — dùng cho kho có hàng trăm ngàn đơn vị dồn vào rất ít dòng (xem
    docs/WMS-LOT-LEVEL-REDESIGN.md), không yêu cầu chọn từng đơn vị một. unit_type PHẢI là
    loại có divide_by_pack_size=True trong Danh mục Loại đơn vị tồn kho — 1 lô có thể đồng
    thời tồn nhiều loại đơn vị khác nhau (VD vừa Két vừa Chai lẻ) nên không được đoán ngầm,
    phải chỉ rõ loại nào cần phân rã. Nếu tồn ít hơn N, phân rã hết số hiện có (trả về đúng số
    đã xử lý để frontend báo nếu thiếu)."""
    require_perm(user, "warehouse.issue")
    if count <= 0:
        raise DomainError("Số lượng cần phân rã phải > 0.")
    if unit_type not in _divide_by_pack_codes(db):
        raise DomainError("Chỉ có thể phân rã loại đơn vị đóng gói (xem Danh mục Loại đơn vị tồn kho).")
    fp = db.execute(select(FinishedProduct).where(FinishedProduct.code == product_name)).scalar_one_or_none()
    divisor = _pack_divisor(fp, unit_type, _divide_by_pack_codes(db))
    candidates, got = _consume_lot_rows(db, product_name=product_name, unit_type=unit_type, status="stored",
                                        quantity_needed=count * divisor, lot_code=lot_code,
                                        block_pending_manual=True)
    if not candidates:
        raise DomainError("Không còn đơn vị nào tồn kho cho sản phẩm/lô/loại này (hoặc chỉ còn lô "
                          "nhập tay chưa được duyệt nhập kho).")

    vi_decomposed = got / divisor
    source_unit_ids = [u.unit_id for u in candidates]
    lon_unit_ids = []
    lon_created = 0.0
    for u in candidates:
        lons = _decompose_one_pack_unit(db, u, user.username)
        lon_unit_ids += [lon.unit_id for lon in lons]
        lon_created += sum(lon.quantity for lon in lons)

    entry = record_audit(db, entity_type="finished_goods_unit", entity_id=new_id(), action="decompose_batch", actor=user,
                         before={"product_name": product_name, "lot_code": lot_code, "unit_type": unit_type, "requested": count},
                         after={"vi_decomposed": vi_decomposed, "lon_created": lon_created,
                                "source_unit_ids": source_unit_ids, "lon_unit_ids": lon_unit_ids})
    db.commit()
    return {"vi_decomposed": vi_decomposed, "lon_created": lon_created, "requested": count,
            "audit_id": entry.audit_id}


def undo_decompose_batch(db: Session, audit_id: str, user: User) -> dict:
    """Hoàn tác 1 lượt phân rã hàng loạt (decompose_batch) — CHỈ khi toàn bộ lon sinh ra từ
    lượt đó chưa xuất kho (status vẫn "stored", chưa gắn Shipment nào — "chưa xuất sử dụng").
    Không sửa/xóa bản ghi audit gốc (chuỗi hash audit bất biến, §10.3) — xóa các lon đã sinh
    + trả vỉ nguồn về "stored", rồi ghi 1 audit MỚI action="undo_decompose_batch" tham chiếu
    lại audit_id gốc (dùng để phát hiện & chặn hoàn tác 2 lần cho cùng 1 lượt)."""
    require_perm(user, "warehouse.issue")
    entry = db.get(AuditLog, audit_id)
    if not entry or entry.entity_type != "finished_goods_unit" or entry.action != "decompose_batch":
        raise NotFoundError("Không tìm thấy lượt phân rã này.")

    prior_undos = db.execute(select(AuditLog).where(
        AuditLog.entity_type == "finished_goods_unit", AuditLog.action == "undo_decompose_batch")).scalars().all()
    if any((u.before or {}).get("decompose_audit_id") == audit_id for u in prior_undos):
        raise DomainError("Lượt phân rã này đã được hoàn tác trước đó.")

    source_unit_ids = (entry.after or {}).get("source_unit_ids") or []
    lon_unit_ids = (entry.after or {}).get("lon_unit_ids") or []
    if not source_unit_ids or not lon_unit_ids:
        raise DomainError("Lượt phân rã này thực hiện trước khi hỗ trợ hoàn tác — không thể hoàn tác.")

    lons = db.execute(select(FinishedGoodsUnit).where(FinishedGoodsUnit.unit_id.in_(lon_unit_ids))).scalars().all()
    if len(lons) != len(lon_unit_ids):
        raise DomainError("Một số lon từ lượt phân rã này đã bị xoá ở nơi khác — không thể hoàn tác.")
    if any(l.status != "stored" for l in lons):
        raise DomainError("Đã có lon xuất kho/sử dụng từ lượt phân rã này — không thể hoàn tác.")
    # Tiêu thụ MỘT PHẦN (xuất/điều chuyển...) chỉ tách dòng, KHÔNG đổi status của phần còn
    # lại (xem docs/WMS-LOT-LEVEL-REDESIGN.md) — phải so tổng quantity còn lại với
    # lon_created đã ghi lúc phân rã mới phát hiện được, không thể chỉ dựa vào status/len.
    recorded_lon_created = (entry.after or {}).get("lon_created")
    current_lon_qty = sum(l.quantity for l in lons)
    if recorded_lon_created is not None and current_lon_qty + 1e-6 < recorded_lon_created:
        raise DomainError(
            f"Đã có {recorded_lon_created - current_lon_qty:g} lon rời khỏi lượt phân rã này (xuất/điều chuyển "
            "một phần) — không thể hoàn tác nguyên vẹn.")

    sources = db.execute(select(FinishedGoodsUnit).where(FinishedGoodsUnit.unit_id.in_(source_unit_ids))).scalars().all()
    edges = db.execute(select(GenealogyEdge).where(
        GenealogyEdge.from_type == "finished_goods_unit", GenealogyEdge.from_id.in_(source_unit_ids),
        GenealogyEdge.to_type == "finished_goods_unit", GenealogyEdge.to_id.in_(lon_unit_ids))).scalars().all()
    for e in edges:
        db.delete(e)
    for l in lons:
        db.delete(l)
    for s in sources:
        s.status = "stored"

    vi_restored = (entry.after or {}).get("vi_decomposed", len(sources))
    record_audit(db, entity_type="finished_goods_unit", entity_id=entry.entity_id, action="undo_decompose_batch",
                 actor=user, before={"decompose_audit_id": audit_id,
                                     "product_name": (entry.before or {}).get("product_name"),
                                     "lot_code": (entry.before or {}).get("lot_code")},
                 after={"vi_restored": vi_restored, "lon_removed": current_lon_qty})
    db.commit()
    return {"vi_restored": vi_restored, "lon_removed": current_lon_qty}


def free_issue_batch(db: Session, product_name: str, lot_code: str | None, unit_type: str,
                     count: int, reason: str, user: User) -> dict:
    """Xuất tự do (không qua Shipment) N vỉ/keg/lon CŨ NHẤT (FIFO) của 1 sản phẩm/lô — dùng
    cho hao hụt nội bộ/hủy hàng/kiểm tra chất lượng, KHÔNG phải bán hàng thật (đã có Xuất
    kho/Shipment riêng cho việc đó). Chỉ admin, bắt buộc nêu lý do (mirror return_to_supplier)
    — mirror decompose_batch nhưng đánh dấu status="issued_free" (loại khỏi tồn khả dụng, xem
    list_lot_summaries lọc status="stored") thay vì tạo dòng con; hoàn tác được như
    undo_decompose_batch (xem undo_free_issue_batch)."""
    require_role(user, Role.ADMIN)
    if not reason or not reason.strip():
        raise DomainError("Phải nhập lý do xuất tự do.")
    if count <= 0:
        raise DomainError("Số lượng xuất phải > 0.")
    fp = db.execute(select(FinishedProduct).where(FinishedProduct.code == product_name)).scalar_one_or_none()
    divisor = _pack_divisor(fp, unit_type, _divide_by_pack_codes(db))
    candidates, got = _consume_lot_rows(db, product_name=product_name, unit_type=unit_type, status="stored",
                                        quantity_needed=count * divisor, lot_code=lot_code,
                                        block_pending_manual=True)
    if not candidates:
        raise DomainError("Không còn đơn vị nào tồn kho cho sản phẩm/lô này (hoặc chỉ còn lô nhập "
                          "tay chưa được duyệt nhập kho).")

    for u in candidates:
        u.status = "issued_free"
    unit_ids = [u.unit_id for u in candidates]
    issued_count = got / divisor

    entry = record_audit(db, entity_type="finished_goods_unit", entity_id=new_id(), action="free_issue_batch",
                         actor=user, before={"product_name": product_name, "lot_code": lot_code,
                                             "unit_type": unit_type, "requested": count},
                         after={"issued": issued_count, "unit_ids": unit_ids,
                                "unit_codes": [u.unit_code for u in candidates]},
                         reason=reason)
    db.commit()
    return {"issued": issued_count, "requested": count, "audit_id": entry.audit_id}


def undo_free_issue_batch(db: Session, audit_id: str, user: User) -> dict:
    """Hoàn tác 1 lượt xuất tự do (free_issue_batch) — CHỈ khi toàn bộ đơn vị của lượt đó
    vẫn còn status="issued_free" (chưa bị thao tác gì khác từ lúc xuất). Mirror
    undo_decompose_batch: không sửa/xóa audit gốc, trả các đơn vị về "stored" rồi ghi 1
    audit mới tham chiếu lại audit_id gốc (chặn hoàn tác 2 lần)."""
    require_role(user, Role.ADMIN)
    entry = db.get(AuditLog, audit_id)
    if not entry or entry.entity_type != "finished_goods_unit" or entry.action != "free_issue_batch":
        raise NotFoundError("Không tìm thấy lượt xuất tự do này.")

    prior_undos = db.execute(select(AuditLog).where(
        AuditLog.entity_type == "finished_goods_unit", AuditLog.action == "undo_free_issue_batch")).scalars().all()
    if any((u.before or {}).get("free_issue_audit_id") == audit_id for u in prior_undos):
        raise DomainError("Lượt xuất tự do này đã được hoàn tác trước đó.")

    unit_ids = (entry.after or {}).get("unit_ids") or []
    if not unit_ids:
        raise DomainError("Lượt xuất tự do này không có dữ liệu để hoàn tác.")
    units = db.execute(select(FinishedGoodsUnit).where(FinishedGoodsUnit.unit_id.in_(unit_ids))).scalars().all()
    if any(u.status != "issued_free" for u in units):
        raise DomainError("Có đơn vị đã thay đổi trạng thái sau khi xuất — không thể hoàn tác.")

    for u in units:
        u.status = "stored"
    restored_count = (entry.after or {}).get("issued", len(units))
    record_audit(db, entity_type="finished_goods_unit", entity_id=entry.entity_id, action="undo_free_issue_batch",
                 actor=user, before={"free_issue_audit_id": audit_id,
                                     "product_name": (entry.before or {}).get("product_name"),
                                     "lot_code": (entry.before or {}).get("lot_code")},
                 after={"restored": restored_count})
    db.commit()
    return {"restored": restored_count}


def list_free_issues(db: Session, limit: int = 200) -> list[dict]:
    """Lịch sử xuất tự do (kho thành phẩm) — mỗi lượt free_issue_batch kèm cờ đã hoàn tác
    hay chưa (tra theo undo_free_issue_batch tham chiếu lại)."""
    entries = db.execute(select(AuditLog).where(
        AuditLog.entity_type == "finished_goods_unit",
        AuditLog.action.in_(["free_issue_batch", "undo_free_issue_batch"])
    ).order_by(AuditLog.ts.desc()).limit(limit * 2)).scalars().all()
    undone_ids = {(e.before or {}).get("free_issue_audit_id") for e in entries
                  if e.action == "undo_free_issue_batch"}
    rows = []
    for e in entries:
        if e.action != "free_issue_batch":
            continue
        rows.append({"audit_id": e.audit_id, "ts": e.ts, "actor": e.actor,
                    "product_name": (e.before or {}).get("product_name"),
                    "lot_code": (e.before or {}).get("lot_code"),
                    "unit_type": (e.before or {}).get("unit_type"),
                    "requested": (e.before or {}).get("requested"),
                    "issued": (e.after or {}).get("issued"),
                    "reason": e.reason, "undone": e.audit_id in undone_ids})
    return rows[:limit]


def list_lot_summaries(db: Session) -> list:
    """Tổng hợp tồn kho theo (sản phẩm, lô) — mỗi dòng gộp số lượng vỉ/keg/lon, dùng cho
    picker Xuất kho (không liệt kê từng đơn vị — kho có thể có hàng trăm ngàn vỉ).
    has_lon: lô này đã từng phân rã ra lon lẻ (còn tồn) hay chưa — dùng cho bộ lọc.
    {type}_fifo_ok: lô này có phải lô CŨ NHẤT còn tồn của (sản phẩm, loại đơn vị) này
    không — để người dùng thấy ngay có nên chọn lô này trước hay không, đúng thứ tự FIFO
    mà create_shipment vẫn áp dụng khi tự chọn đơn vị.
    bottle_codes: mã chiết (BottleRecord.bottle_code) đã sinh ra lot_code này — tra qua
    BottleRecord.lot_no == lot_code (thường 1:1, nhưng liệt kê hết phòng khi trùng số lô bia
    thủ công) — chỉ để hiển thị tham khảo, KHÔNG dùng để gom nhóm/FIFO (vẫn theo lot_code).
    bottle_date: thời điểm chiết SỚM NHẤT của lô (BottleRecord.bottle_date) — cho picker
    "Cất vào vị trí" biết lô mới nhập kho được chiết từ lúc nào.
    lines: danh sách dây chuyền (BottleRecord.line) đã chiết ra lô này — cùng mục đích trên.
    {type}_locations: danh sách [{"code","name","count"}] các vị trí kho đang giữ loại đơn vị
    đó của lô này (1 lô/loại vẫn có thể nằm rải rác nhiều vị trí) — "(chưa cất vị trí)" tính
    riêng qua {type}_unplaced, không lẫn vào đây.
    {type}_near_expiry_count: số vỉ/keg/lon quy đổi ĐANG is_near_expiry=True của (lô, loại)
    này — dùng để chỉ bật ô chọn "Cận date" ở picker Xuất kho khi lô thực sự có hàng cận date
    (tránh người dùng tick nhầm lô không có bia cận date nào).
    {type}_consigned_count: tương tự nhưng cho is_consigned=True (bia gửi) — mirror y hệt.
    {type}_pending_count/{type}_confirmed_count: số vỉ/keg/lon quy đổi đang chờ/đã được Trưởng
    bộ phận kho duyệt nhập kho (nguồn "chiet" hoặc "manual" — xem docstring
    FinishedGoodsUnit.source), dùng cho cột "Duyệt nhập kho" ở bảng Kho TP."""
    # "count" = tổng vỉ/keg/lon quy đổi (SUM(quantity)/pack_size — qua _pack_divisor_expr,
    # JOIN FinishedProduct), KHÔNG đếm dòng — 1 dòng giờ có thể đại diện nhiều đơn vị đóng
    # gói (xem docs/WMS-LOT-LEVEL-REDESIGN.md). "qty" (tổng SL nhỏ) không đổi ý nghĩa.
    divide_codes = _divide_by_pack_codes(db)
    rows = db.execute(select(FinishedGoodsUnit.product_name, FinishedGoodsUnit.lot_code,
                             FinishedGoodsUnit.unit_type, FinishedGoodsUnit.location_id,
                             func.sum(FinishedGoodsUnit.quantity / _pack_divisor_expr(divide_codes)),
                             func.sum(FinishedGoodsUnit.quantity), func.min(FinishedGoodsUnit.created_at),
                             func.sum(case((FinishedGoodsUnit.is_near_expiry == true(),
                                           FinishedGoodsUnit.quantity / _pack_divisor_expr(divide_codes)), else_=0.0)),
                             func.sum(case((FinishedGoodsUnit.is_consigned == true(),
                                           FinishedGoodsUnit.quantity / _pack_divisor_expr(divide_codes)), else_=0.0)),
                             func.sum(case((and_(FinishedGoodsUnit.source.in_(("chiet", "manual")),
                                                FinishedGoodsUnit.received_confirmed_by.is_(None)),
                                           FinishedGoodsUnit.quantity / _pack_divisor_expr(divide_codes)), else_=0.0)),
                             func.sum(case((and_(FinishedGoodsUnit.source.in_(("chiet", "manual")),
                                                FinishedGoodsUnit.received_confirmed_by.isnot(None)),
                                           FinishedGoodsUnit.quantity / _pack_divisor_expr(divide_codes)), else_=0.0)))
                      .select_from(FinishedGoodsUnit)
                      .outerjoin(FinishedProduct, FinishedProduct.finished_product_id == FinishedGoodsUnit.finished_product_id)
                      .where(FinishedGoodsUnit.status == "stored")
                      .group_by(FinishedGoodsUnit.product_name, FinishedGoodsUnit.lot_code,
                               FinishedGoodsUnit.unit_type, FinishedGoodsUnit.location_id)).all()
    # bottle_date/line: thời gian chiết + dây chuyền đã chiết ra lô này — tra qua BottleRecord
    # (lot_no == lot_code, xem ghi chú ở docstring) để hiển thị ở picker "Cất vào vị trí" (biết
    # lô mới nhập kho được chiết lúc nào, từ dây chuyền nào trước khi cất vào vị trí kho thật).
    bottle_codes_by_lot: dict[str, list] = {}
    bottle_date_by_lot: dict[str, datetime] = {}
    lines_by_lot: dict[str, set] = {}
    for lot_no, bottle_code, bottle_date, line in db.execute(
            select(BottleRecord.lot_no, BottleRecord.bottle_code, BottleRecord.bottle_date, BottleRecord.line)
            .where(BottleRecord.lot_no.isnot(None))).all():
        bottle_codes_by_lot.setdefault(lot_no, []).append(bottle_code)
        if bottle_date and (lot_no not in bottle_date_by_lot or bottle_date < bottle_date_by_lot[lot_no]):
            bottle_date_by_lot[lot_no] = bottle_date
        if line:
            lines_by_lot.setdefault(lot_no, set()).add(line)
    wh_by_id = {w.warehouse_id: w for w in db.execute(select(WmsWarehouse)).scalars().all()}
    loc_meta_by_id = {l.loc_id: (l.code, l.name, l.warehouse_id, l.zone)
                      for l in db.execute(select(WmsLocation)).scalars().all()}
    # vehicle_by_lot: xe đã mang bia gửi về, tra qua ConsignedEntry(direction="in").lot_code —
    # dùng để hiện "xe đã gửi" ở picker Xuất kho khi chọn hàng bia gửi (is_consigned).
    vehicle_by_id = {v.vehicle_id: v for v in db.execute(select(Vehicle)).scalars().all()}
    vehicle_by_lot: dict[str, Vehicle] = {}
    for lot_code, vehicle_id in db.execute(
            select(ConsignedEntry.lot_code, ConsignedEntry.vehicle_id)
            .where(ConsignedEntry.direction == "in", ConsignedEntry.vehicle_id.isnot(None))).all():
        if lot_code and vehicle_id in vehicle_by_id:
            vehicle_by_lot[lot_code] = vehicle_by_id[vehicle_id]
    grouped: dict[tuple, dict] = {}
    oldest_by_type: dict[tuple, object] = {}
    loc_counts: dict[tuple, dict] = {}  # (product_name, lot_code, unit_type) -> {loc_id: count}
    # types_by_key: theo dõi ĐÚNG các loại đơn vị thực sự xuất hiện ở mỗi (sản phẩm, lô) — trước
    # đây hardcode 3 loại (vi/keg/lon) nên bất kỳ loại tự khai báo nào khác ở Danh mục "Loại đơn
    # vị tồn kho" (VD "lốc", "két") đều bị ĐẾM RỖNG ở đây, khiến cả lô đó biến mất khỏi bảng Kho
    # TP/picker Xuất kho/Cất vào vị trí dù tồn kho thật vẫn còn (không chỉ sai nhãn như "lon").
    types_by_key: dict[tuple, set] = {}
    for (product_name, lot_code, unit_type, location_id, count, qty, oldest_at, near_expiry_count,
         consigned_count, pending_count, confirmed_count) in rows:
        key = (product_name, lot_code)
        consigned_vehicle = vehicle_by_lot.get(lot_code)
        g = grouped.setdefault(key, {"product_name": product_name, "lot_code": lot_code,
                                     "bottle_codes": bottle_codes_by_lot.get(lot_code, []),
                                     "bottle_date": bottle_date_by_lot.get(lot_code).isoformat() if bottle_date_by_lot.get(lot_code) else None,
                                     "lines": sorted(lines_by_lot.get(lot_code, [])),
                                     "consigned_vehicle_plate": consigned_vehicle.plate if consigned_vehicle else None,
                                     "consigned_vehicle_code": consigned_vehicle.vehicle_code if consigned_vehicle else None})
        types_by_key.setdefault(key, set()).add(unit_type)
        g.setdefault(f"{unit_type}_count", 0)
        g.setdefault(f"{unit_type}_qty", 0.0)
        g.setdefault(f"{unit_type}_unplaced", 0)
        g.setdefault(f"{unit_type}_near_expiry_count", 0.0)
        g.setdefault(f"{unit_type}_consigned_count", 0.0)
        g.setdefault(f"{unit_type}_pending_count", 0.0)
        g.setdefault(f"{unit_type}_confirmed_count", 0.0)
        g[f"{unit_type}_count"] += count
        g[f"{unit_type}_qty"] += qty or 0
        g[f"{unit_type}_near_expiry_count"] += near_expiry_count or 0
        g[f"{unit_type}_consigned_count"] += consigned_count or 0
        g[f"{unit_type}_pending_count"] += pending_count or 0
        g[f"{unit_type}_confirmed_count"] += confirmed_count or 0
        if location_id is None:
            g[f"{unit_type}_unplaced"] += count
        else:
            lc = loc_counts.setdefault((product_name, lot_code, unit_type), {})
            lc[location_id] = lc.get(location_id, 0) + count
        prev_oldest = g.get(f"{unit_type}_oldest_at")
        if prev_oldest is None or (oldest_at and oldest_at < prev_oldest):
            g[f"{unit_type}_oldest_at"] = oldest_at
        type_key = (product_name, unit_type)
        if type_key not in oldest_by_type or (oldest_at and oldest_at < oldest_by_type[type_key]):
            oldest_by_type[type_key] = oldest_at
    for key, g in grouped.items():
        types = sorted(types_by_key.get(key, ()))
        g["unit_types"] = types
        g["has_lon"] = g.get("lon_count", 0) > 0
        for t in types:
            oldest_at = g.pop(f"{t}_oldest_at", None)
            if g[f"{t}_count"] > 0:
                g[f"{t}_fifo_ok"] = oldest_at == oldest_by_type.get((g["product_name"], t))
                g[f"{t}_oldest_at"] = oldest_at.isoformat() if oldest_at else None
            else:
                g[f"{t}_fifo_ok"] = None
                g[f"{t}_oldest_at"] = None
            lc = loc_counts.get((g["product_name"], g["lot_code"], t), {})

            def _loc_entry(loc_id, cnt):
                code, name, wh_id, zone = loc_meta_by_id.get(loc_id, (loc_id, None, None, None))
                wh = wh_by_id.get(wh_id)
                return {"loc_id": loc_id, "code": code, "name": name, "zone": zone, "count": cnt,
                       "warehouse_id": wh_id, "warehouse_code": wh.code if wh else None,
                       "warehouse_name": wh.name if wh else None}
            g[f"{t}_locations"] = sorted((_loc_entry(loc_id, cnt) for loc_id, cnt in lc.items()),
                                         key=lambda x: -x["count"])
    return sorted(grouped.values(), key=lambda g: (g["product_name"] or "", g["lot_code"] or ""))


# Ngưỡng mặc định (số ngày tồn kho kể từ đơn vị nhập sớm nhất trong nhóm) để tô màu cảnh báo ở
# báo cáo tồn kho theo tuổi — khối kinh doanh dùng để biết lô nào cần đẩy bán gấp. Có thể chỉnh
# qua Cài đặt vận hành (OpsSetting.aging_*_days), xem lot_aging_report().
AGING_BUCKETS = [(90, "critical"), (60, "warning"), (30, "caution")]


def lot_aging_report(db: Session, caution_days: float = 30.0, warning_days: float = 60.0,
                     critical_days: float = 90.0) -> list[dict]:
    """Báo cáo tồn kho thành phẩm theo TUỔI LÔ — mỗi dòng 1 (sản phẩm, lô, loại đơn vị) còn
    tồn kho ("stored"), kèm ngày nhập sớm nhất, số ngày đã tồn và vị trí kho — để khối kinh
    doanh biết lô nào tồn lâu cần đẩy nhanh tiến độ bán hàng. Gộp qua SQL GROUP BY (không tải
    từng đơn vị — 1 lô có thể có hàng trăm nghìn vỉ, xem list_lot_summaries). Ngưỡng cảnh báo
    (caution/warning/critical) lấy từ Cài đặt vận hành, mặc định 30/60/90 ngày."""
    buckets = [(critical_days, "critical"), (warning_days, "warning"), (caution_days, "caution")]
    # "count" = tổng vỉ/keg/lon quy đổi (SUM(quantity)/pack_size), KHÔNG đếm dòng — xem
    # docs/WMS-LOT-LEVEL-REDESIGN.md.
    rows = db.execute(select(FinishedGoodsUnit.product_name, FinishedGoodsUnit.lot_code,
                             FinishedGoodsUnit.unit_type, FinishedGoodsUnit.location_id,
                             func.sum(FinishedGoodsUnit.quantity / _pack_divisor_expr(_divide_by_pack_codes(db))),
                             func.sum(FinishedGoodsUnit.quantity), func.min(FinishedGoodsUnit.created_at))
                      .select_from(FinishedGoodsUnit)
                      .outerjoin(FinishedProduct, FinishedProduct.finished_product_id == FinishedGoodsUnit.finished_product_id)
                      .where(FinishedGoodsUnit.status == "stored")
                      .group_by(FinishedGoodsUnit.product_name, FinishedGoodsUnit.lot_code,
                               FinishedGoodsUnit.unit_type, FinishedGoodsUnit.location_id)).all()
    wh_by_id_ag = {w.warehouse_id: w for w in db.execute(select(WmsWarehouse)).scalars().all()}
    loc_meta_by_id_ag = {l.loc_id: (l.code, l.name, l.zone, l.warehouse_id)
                        for l in db.execute(select(WmsLocation)).scalars().all()}
    # FinishedGoodsUnit.product_name thực ra lưu MÃ SKU (vd "FLGN200"), không phải tên hiển thị —
    # tra thêm bảng finished_product để lấy đúng tên tiếng Việt (vd "Bia tươi Legend 20L") cho
    # báo cáo/Dashboard hiển thị, không đổi tên cột product_name (đã dùng khắp module này làm khoá).
    fp_name_by_code = {fp.code: fp.name for fp in db.execute(select(FinishedProduct)).scalars().all()}
    now = utcnow()
    grouped: dict[tuple, dict] = {}
    # Gộp thêm theo warehouse_id (không chỉ product+lot+loại đơn vị) — cùng 1 lô nằm ở 2 KHO
    # THÀNH PHẨM khác nhau phải ra 2 dòng riêng (tồn kho vật lý tách biệt thật sự), còn rải nhiều
    # VỊ TRÍ trong CÙNG 1 kho vẫn gộp 1 dòng (mảng "locations" liệt kê chi tiết từng vị trí) —
    # mirror cách list_lot_summaries/renderUnits (Kho TP) đã tách theo kho ở frontend.
    for product_name, lot_code, unit_type, location_id, count, qty, oldest_at in rows:
        if location_id is None:
            loc_code, loc_name, loc_zone, warehouse_id = None, None, None, None
        else:
            loc_code, loc_name, loc_zone, warehouse_id = loc_meta_by_id_ag.get(location_id, (None, None, None, None))
        key = (product_name, lot_code, unit_type, warehouse_id)
        wh_ag = wh_by_id_ag.get(warehouse_id)
        g = grouped.setdefault(key, {"product_name": product_name,
                                     "product_display_name": fp_name_by_code.get(product_name, product_name),
                                     "lot_code": lot_code,
                                     "unit_type": unit_type, "count": 0, "quantity": 0.0,
                                     "warehouse_id": warehouse_id,
                                     "warehouse_code": wh_ag.code if wh_ag else None,
                                     "warehouse_name": wh_ag.name if wh_ag else None,
                                     "oldest_at": None, "locations": [], "unplaced": 0})
        g["count"] += count
        g["quantity"] += qty or 0
        if location_id is None:
            g["unplaced"] += count
        else:
            g["locations"].append({"code": loc_code, "name": loc_name, "zone": loc_zone, "count": count,
                                   "warehouse_code": wh_ag.code if wh_ag else None})
        if g["oldest_at"] is None or (oldest_at and oldest_at < g["oldest_at"]):
            g["oldest_at"] = oldest_at
    out = []
    for g in grouped.values():
        oldest_at = g.pop("oldest_at")
        # Dùng total_seconds()/86400 (số thực) thay vì .days (làm tròn xuống số nguyên) — ngưỡng
        # cảnh báo cho phép nhập số thực (VD 0.2 ngày ~ 4.8 giờ) nên tuổi lô cũng phải giữ phần lẻ,
        # nếu không mọi lô mới nhập trong vòng chưa đủ 24h đều ra age_days=0, không bao giờ vượt
        # ngưỡng < 1 ngày.
        age_days = round((now - oldest_at).total_seconds() / 86400, 2) if oldest_at else None
        bucket = next((b for days, b in buckets if age_days is not None and age_days >= days), "ok")
        out.append({**g, "received_at": oldest_at.isoformat() if oldest_at else None,
                    "age_days": age_days, "age_bucket": bucket})
    return sorted(out, key=lambda g: -(g["age_days"] or 0))


# ---- Báo cáo xuất thành phẩm theo ca (Ca 1/2/3, cùng khung giờ với báo cáo Năng lượng) ----

_ML_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*ml", re.IGNORECASE)
_L_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*l(?:ít|it)?\b", re.IGNORECASE)


def _resolve_liters_per_unit(display_name: str | None) -> float | None:
    """Suy thể tích (lít) của 1 đơn vị nhỏ (1 lon/chai hoặc 1 keg) từ TÊN HIỂN THỊ SKU
    (FinishedProduct.name, vd "Bia lon Sapphire 330ml", "Bia tươi Legend 20L") — không có cột
    thể tích riêng trong Danh mục Sản phẩm, nhưng mọi SKU thật đều đặt tên kèm dung tích. Trả
    None nếu không khớp mẫu ml/L nào — dòng đó bị loại khỏi tổng lít và liệt kê ở
    unmatched_products (xem finished_goods_shift_report) để người dùng biết cần sửa tên SKU,
    KHÔNG đoán bừa một con số sai."""
    if not display_name:
        return None
    m = _ML_RE.search(display_name)
    if m:
        return float(m.group(1).replace(",", ".")) / 1000
    m = _L_RE.search(display_name)
    if m:
        return float(m.group(1).replace(",", "."))
    return None


_SHIFT_VN_OFFSET = timedelta(hours=7)  # shipped_at lưu UTC (xem UTCDateTime) — ca 1/2/3 tính
# theo giờ VN (dashboard.py::VN_OFFSET dùng cùng quy ước), phải quy đổi trước khi lấy .hour/
# .date() nếu không mốc 0h-6h59 giờ VN (= 17h-23h59 UTC hôm trước) sẽ bị tính nhầm sang Ca 2.


def _bucket_shift(dt: datetime) -> tuple[str, int]:
    """Quy đổi 1 mốc thời gian BẤT KỲ (FinishedGoodsUnit.shipped_at, lưu UTC) về (ngày, ca) —
    Ca 1: 06h-14h, Ca 2: 14h-22h, Ca 3: 22h-06h hôm sau giờ VN, tính về NGÀY BẮT ĐẦU ca (giống
    quy ước keg_external.aggregate_keg_values). Khác filling_external.ca_number(): hàm đó chỉ
    đúng cho mốc ranh giới cố định (06h/14h/22h đúng giờ), còn hàm này phân loại mốc lẻ bất kỳ
    trong ngày (shipped_at là thời điểm xuất thật, không phải mốc lấy mẫu SCADA)."""
    local = dt + _SHIFT_VN_OFFSET
    h = local.hour
    if 6 <= h < 14:
        return local.date().isoformat(), 1
    if 14 <= h < 22:
        return local.date().isoformat(), 2
    if h >= 22:
        return local.date().isoformat(), 3
    return (local.date() - timedelta(days=1)).isoformat(), 3


_CA_HOUR_OFFSETS = {1: (6, 14), 2: (14, 22), 3: (22, 30)}  # giờ lệch so với 00h của "ngày" bucket (ca3 kết thúc 06h hôm sau = 30h)


def _consigned_window_start(now: datetime) -> datetime:
    """Mốc bắt đầu cho phép chọn xe/validate số lượng ở "Nhập bia gửi": 14h00 giờ VN (đầu Ca 2)
    của NGÀY HÔM TRƯỚC so với `now` — VD now là 06/08 bất kỳ giờ nào thì mốc là 05/08 14:00 VN.
    Trả về UTC (trừ lại _SHIFT_VN_OFFSET) để so sánh trực tiếp với Shipment.created_at."""
    vn_now = now + _SHIFT_VN_OFFSET
    ca2_prev_day_local = (vn_now - timedelta(days=1)).replace(hour=14, minute=0, second=0, microsecond=0)
    return ca2_prev_day_local - _SHIFT_VN_OFFSET


def consigned_eligible_vehicles(db: Session) -> list[dict]:
    """Xe đủ điều kiện chọn ở "Nhập bia gửi": có phiếu xuất kho (Shipment.vehicle_id) tạo trong
    khoảng [Ca 2 ngày hôm trước 14h VN, hiện tại] — xem _consigned_window_start. Kèm danh sách
    (sản phẩm, số lượng đã xuất quy đổi vỉ/keg) của xe đó trong khoảng này, để frontend chỉ cho
    chọn đúng sản phẩm đã xuất và hiện số lượng tối đa được nhập gửi lại — validate thật ở
    create_consigned_entry (_consigned_available_qty), đây chỉ phục vụ hiển thị/lọc UI."""
    now = utcnow()
    window_start = _consigned_window_start(now)
    ships = db.execute(select(Shipment).where(
        Shipment.vehicle_id.isnot(None), Shipment.created_at >= window_start,
        Shipment.created_at <= now)).scalars().all()
    if not ships:
        return []
    shipment_ids = [s.shipment_id for s in ships]
    vehicle_by_shipment = {s.shipment_id: s.vehicle_id for s in ships}
    units = db.execute(select(FinishedGoodsUnit).where(
        FinishedGoodsUnit.shipment_id.in_(shipment_ids))).scalars().all()
    divide_codes = _divide_by_pack_codes(db)
    fp_cache: dict = {}

    def _fp_of(fpid):
        if fpid not in fp_cache:
            fp_cache[fpid] = db.get(FinishedProduct, fpid) if fpid else None
        return fp_cache[fpid]

    by_vehicle: dict[str, dict[str, dict]] = {}
    for u in units:
        vehicle_id = vehicle_by_shipment.get(u.shipment_id)
        if not vehicle_id or not u.finished_product_id:
            continue
        fp = _fp_of(u.finished_product_id)
        divisor = _pack_divisor(fp, u.unit_type, divide_codes)
        prod_map = by_vehicle.setdefault(vehicle_id, {})
        entry = prod_map.setdefault(u.finished_product_id, {
            "finished_product_id": u.finished_product_id,
            "code": fp.code if fp else u.product_name, "shipped_count": 0.0, "unit_type": u.unit_type})
        entry["shipped_count"] += u.quantity / divisor
    if not by_vehicle:
        return []
    already: dict[tuple, float] = {}
    for vehicle_id, fpid, total in db.execute(select(
            ConsignedEntry.vehicle_id, ConsignedEntry.finished_product_id, func.sum(ConsignedEntry.quantity))
            .where(ConsignedEntry.direction == "in", ConsignedEntry.reversed == false(),
                   ConsignedEntry.vehicle_id.in_(by_vehicle.keys()),
                   ConsignedEntry.declared_at >= window_start)
            .group_by(ConsignedEntry.vehicle_id, ConsignedEntry.finished_product_id)).all():
        already[(vehicle_id, fpid)] = total or 0.0
    out = []
    for v in db.execute(select(Vehicle).where(Vehicle.vehicle_id.in_(by_vehicle.keys()))).scalars().all():
        products = []
        for p in by_vehicle[v.vehicle_id].values():
            remaining = p["shipped_count"] - already.get((v.vehicle_id, p["finished_product_id"]), 0.0)
            products.append({**p, "shipped_count": round(p["shipped_count"], 3),
                             "remaining": round(max(remaining, 0.0), 3)})
        out.append({"vehicle_id": v.vehicle_id, "vehicle_code": v.vehicle_code, "plate": v.plate,
                    "driver_name": v.driver_name, "driver_short_name": v.driver_short_name,
                    "active": v.active, "products": products})
    return sorted(out, key=lambda r: r["plate"])


def _consigned_available_qty(db: Session, vehicle_id: str, finished_product_id: str,
                             exclude_entry_id: str = None) -> float:
    """Số lượng (quy đổi vỉ/keg) còn được phép nhập bia gửi cho (xe, sản phẩm) này = tổng đã
    xuất trong khoảng [Ca 2 ngày hôm trước 14h VN, hiện tại] (Shipment.vehicle_id + FinishedGoodsUnit
    cùng finished_product_id) TRỪ tổng đã khai báo "Nhập bia gửi" trước đó cho đúng cặp (xe, sản
    phẩm) trong cùng khoảng — chặn khai 2 lần vượt quá thực tế đã xuất. `exclude_entry_id` dùng
    khi SỬA 1 bản khai đã có (không tự trừ chính nó)."""
    now = utcnow()
    window_start = _consigned_window_start(now)
    shipment_ids = db.execute(select(Shipment.shipment_id).where(
        Shipment.vehicle_id == vehicle_id, Shipment.created_at >= window_start,
        Shipment.created_at <= now)).scalars().all()
    if not shipment_ids:
        return 0.0
    units = db.execute(select(FinishedGoodsUnit).where(
        FinishedGoodsUnit.shipment_id.in_(shipment_ids),
        FinishedGoodsUnit.finished_product_id == finished_product_id)).scalars().all()
    if not units:
        return 0.0
    divide_codes = _divide_by_pack_codes(db)
    fp = db.get(FinishedProduct, finished_product_id)
    shipped_count = sum(u.quantity / _pack_divisor(fp, u.unit_type, divide_codes) for u in units)
    already_q = select(func.sum(ConsignedEntry.quantity)).where(
        ConsignedEntry.direction == "in", ConsignedEntry.reversed == false(),
        ConsignedEntry.vehicle_id == vehicle_id, ConsignedEntry.finished_product_id == finished_product_id,
        ConsignedEntry.declared_at >= window_start)
    if exclude_entry_id:
        already_q = already_q.where(ConsignedEntry.entry_id != exclude_entry_id)
    already_declared = db.execute(already_q).scalar() or 0.0
    return max(shipped_count - already_declared, 0.0)


def finished_goods_shift_report(db: Session, date_from: datetime, date_to: datetime) -> dict:
    """Báo cáo Xuất thành phẩm theo ca — tổng LÍT xuất kho trong khoảng [date_from, date_to),
    quy đổi từ FinishedGoodsUnit.quantity (SL lon/chai/keg xuất) x thể tích/đơn vị suy ra từ
    tên SKU (1 lon 330ml=0.33L, 1 keg 20L/30L=20/30L — _resolve_liters_per_unit). Nguồn dữ
    liệu là DB nội bộ (không phải SCADA ngoài như filling/keg/energy) nên không có khái niệm
    "khoảng trống dữ liệu" — mỗi vỉ/keg là 1 sự kiện xuất thật, cộng dồn trực tiếp theo
    (ngày, ca) suy từ shipped_at.
    LOẠI TRỪ is_consigned=True (bia gửi): xe đã xuất phiếu gốc buổi sáng (đã tính vào lượt
    xuất/lượng lít của phiếu đó), phần dư mang về gửi rồi xuất lại lần 2 nếu tính tiếp sẽ bị
    đếm trùng lượng lít đã xuất — xem docstring ConsignedEntry. Bia cận date (is_near_expiry)
    KHÔNG bị trừ vì không phải xuất trùng của cùng 1 chuyến."""
    rows = db.execute(
        select(FinishedGoodsUnit.quantity, FinishedGoodsUnit.shipped_at,
               FinishedGoodsUnit.product_name, FinishedProduct.name, FinishedProduct.category,
               FinishedGoodsUnit.unit_type, FinishedProduct.pack_size)
        .select_from(FinishedGoodsUnit)
        .outerjoin(FinishedProduct, FinishedProduct.finished_product_id == FinishedGoodsUnit.finished_product_id)
        .where(FinishedGoodsUnit.status == "shipped",
               FinishedGoodsUnit.shipped_at.isnot(None),
               FinishedGoodsUnit.shipped_at >= date_from,
               FinishedGoodsUnit.shipped_at < date_to,
               FinishedGoodsUnit.is_consigned == false())
    ).all()

    # by_sku: báo cáo xuất theo TỪNG SKU cụ thể (số lượng thật theo đơn vị đóng gói — vỉ/keg/lon,
    # KHÔNG quy đổi lít) — khác with by_category/by_day ở trên vốn tính bằng lít cho báo cáo theo
    # ca. divide_codes/ut_names tra 1 lần (không lặp trong vòng for, xem _divide_by_pack_codes).
    divide_codes = _divide_by_pack_codes(db)
    ut_names = dict(db.execute(select(UnitTypeCatalog.code, UnitTypeCatalog.name)).all())

    def _unit_noun(unit_type: str, display_name: str | None) -> str:
        # unit_type "lon" là mã dùng chung cho MỌI đơn vị nhỏ đã phân rã (có thể là lon HOẶC
        # chai vật lý) — suy danh từ đúng từ tên SKU, cùng cách views_ext.js::smallUnitNoun làm
        # ở các bảng WMS khác (xem ghi chú tại genealogy.py::_bottle_forward_groups).
        if unit_type == "lon":
            t = (display_name or "").lower()
            if "chai" in t:
                return "chai"
            if "keg" in t:
                return "keg"
            if "lon" in t:
                return "lon"
            return "lẻ"
        return ut_names.get(unit_type, unit_type)

    day_ca: dict[str, dict[int, float]] = {}
    cat_agg: dict[str, dict[int, float]] = {}
    unmatched: dict[str, dict] = {}
    sku_agg: dict[tuple, dict] = {}
    total_liters = 0.0

    for qty, shipped_at, sku_code, sku_name, category, unit_type, pack_size in rows:
        divisor = (pack_size or 1) if unit_type in divide_codes else 1
        sku_key = (sku_code, unit_type)
        s = sku_agg.setdefault(sku_key, {
            "product_name": sku_code, "display_name": sku_name or sku_code or "(không tên)",
            "category": category or "Khác", "unit_type": unit_type,
            "unit_label": _unit_noun(unit_type, sku_name), "count": 0.0, "quantity": 0.0})
        s["count"] += (qty or 0) / divisor
        s["quantity"] += qty or 0

        lpu = _resolve_liters_per_unit(sku_name)
        if lpu is None:
            label = sku_name or sku_code or "(không tên)"
            u = unmatched.setdefault(label, {"product_name": label, "units": 0.0})
            u["units"] += qty or 0
            continue
        liters = (qty or 0) * lpu
        total_liters += liters
        d, ca = _bucket_shift(shipped_at)
        day_ca.setdefault(d, {1: 0.0, 2: 0.0, 3: 0.0})[ca] += liters
        cat = category or "Khác"
        cat_agg.setdefault(cat, {1: 0.0, 2: 0.0, 3: 0.0})[ca] += liters

    by_day = [{"date": d, "ca1": round(v[1]), "ca2": round(v[2]), "ca3": round(v[3])}
              for d, v in sorted(day_ca.items())]

    by_ca_agg = {1: 0.0, 2: 0.0, 3: 0.0}
    for v in day_ca.values():
        for ca in (1, 2, 3):
            by_ca_agg[ca] += v[ca]
    by_ca = [{"ca": ca, "label": f"Ca {ca}", "liters": round(v)} for ca, v in sorted(by_ca_agg.items())]

    by_category = [{"category": cat, "ca1": round(v[1]), "ca2": round(v[2]), "ca3": round(v[3]),
                    "total": round(sum(v.values()))} for cat, v in sorted(cat_agg.items())]

    shifts = []
    for d, v in sorted(day_ca.items()):
        base = datetime.fromisoformat(d)
        for ca in (1, 2, 3):
            h0, h1 = _CA_HOUR_OFFSETS[ca]
            shifts.append({"date": d, "ca": ca,
                          "start": (base + timedelta(hours=h0)).isoformat(),
                          "end": (base + timedelta(hours=h1)).isoformat(),
                          "liters": round(v[ca])})

    # Làm tròn count/quantity hiển thị (giữ 2 chữ số thập phân — count có thể lẻ do lô đã bị
    # phân rã/điều chuyển một phần, xem list_lot_summaries) + tổng theo TỪNG danh từ đơn vị
    # (không cộng gộp vỉ với keg thành 1 số vô nghĩa — mỗi danh từ 1 dòng tổng riêng).
    for s in sku_agg.values():
        s["count"] = round(s["count"], 2)
        s["quantity"] = round(s["quantity"], 2)
    by_sku = sorted(sku_agg.values(), key=lambda s: (s["category"], s["display_name"]))
    unit_totals_map: dict[str, float] = {}
    for s in by_sku:
        unit_totals_map[s["unit_label"]] = unit_totals_map.get(s["unit_label"], 0.0) + s["count"]
    unit_totals = [{"unit_label": lbl, "total_count": round(v, 2)}
                   for lbl, v in sorted(unit_totals_map.items())]

    return {
        "total_liters": round(total_liters),
        "by_ca": by_ca, "by_day": by_day, "by_category": by_category, "shifts": shifts,
        "unmatched_products": sorted(unmatched.values(), key=lambda u: -u["units"]),
        "by_sku": by_sku, "unit_totals": unit_totals,
    }


def shipment_classification_report(db: Session, date_from: datetime, date_to: datetime,
                                    group_by: str = "day") -> dict:
    """Báo cáo lượng bia khuyến mại / đổi trả / cận date / gửi theo ngày hoặc tháng — 4 chỉ
    số ĐỘC LẬP, KHÔNG loại trừ nhau (1 đơn vị xuất có thể vừa khuyến mại vừa cận date, ví dụ)
    tính trên FinishedGoodsUnit đã status="shipped" trong kỳ [date_from, date_to):
    - promo/return: FinishedGoodsUnit.shipment_line_type CỦA CHÍNH đơn vị đó (1 phiếu xuất giờ
      có thể gồm nhiều dòng với Loại xuất khác nhau, xem create_shipment).
    - near_expiry/consigned: cờ is_near_expiry/is_consigned của chính đơn vị đó (không phụ
      thuộc dòng xuất là loại gì — 1 dòng "Thường" vẫn có thể là bia cận date/gửi).
    Số liệu tính bằng "count" (vỉ/keg/lon quy đổi qua pack_size — như list_lot_summaries),
    KHÔNG quy đổi lít (khác finished_goods_shift_report) vì đây là báo cáo tổng số lượng theo
    phân loại, không phải sản lượng ca. group_by="day" bucket theo ngày giờ VN (dùng chung
    _bucket_shift để nhất quán với báo cáo Xuất TP theo ca — không lệch UTC quanh nửa đêm),
    "month" cắt ngắn về "YYYY-MM" từ cùng mốc ngày đó."""
    if group_by not in ("day", "month"):
        raise DomainError("group_by phải là 'day' hoặc 'month'.")
    divide_codes = _divide_by_pack_codes(db)
    rows = db.execute(
        select(FinishedGoodsUnit.quantity, FinishedGoodsUnit.shipped_at, FinishedGoodsUnit.unit_type,
               FinishedProduct.pack_size, FinishedGoodsUnit.shipment_line_type,
               FinishedGoodsUnit.is_near_expiry, FinishedGoodsUnit.is_consigned)
        .select_from(FinishedGoodsUnit)
        .outerjoin(FinishedProduct, FinishedProduct.finished_product_id == FinishedGoodsUnit.finished_product_id)
        .where(FinishedGoodsUnit.status == "shipped", FinishedGoodsUnit.shipped_at.isnot(None),
               FinishedGoodsUnit.shipped_at >= date_from, FinishedGoodsUnit.shipped_at < date_to)
    ).all()

    buckets: dict[str, dict] = {}
    for qty, shipped_at, unit_type, pack_size, shipment_line_type, is_near_expiry, is_consigned in rows:
        divisor = (pack_size or 1) if unit_type in divide_codes else 1
        count = (qty or 0) / divisor
        day_key, _ca = _bucket_shift(shipped_at)
        key = day_key[:7] if group_by == "month" else day_key
        b = buckets.setdefault(key, {"period": key, "promo": 0.0, "return": 0.0,
                                     "near_expiry": 0.0, "consigned": 0.0})
        if shipment_line_type == "promo":
            b["promo"] += count
        elif shipment_line_type == "return":
            b["return"] += count
        if is_near_expiry:
            b["near_expiry"] += count
        if is_consigned:
            b["consigned"] += count
    rows_out = sorted(buckets.values(), key=lambda r: r["period"])
    for r in rows_out:
        for k in ("promo", "return", "near_expiry", "consigned"):
            r[k] = round(r[k], 2)
    return {"group_by": group_by, "rows": rows_out}


def shipment_net_liters_report(db: Session, date_from: datetime, date_to: datetime) -> dict:
    """Báo cáo tổng lít xuất theo (ngày, loại bia) trong 1 khoảng thời gian tùy chọn [date_from,
    date_to) — khác finished_goods_shift_report (chia theo CA, đã loại bia gửi khỏi tổng ngay
    từ đầu) ở chỗ báo cáo này giữ TỔNG LÍT GỘP (gồm cả bia gửi) rồi hiện riêng 2 cột cận
    date/gửi để người xem thấy rõ cấu thành, và tự trừ ở cột cuối: Thực xuất = Tổng lít - Gửi
    (KHÔNG trừ cận date, vì cận date không phải xuất trùng của cùng 1 chuyến — xem docstring
    ConsignedEntry/finished_goods_shift_report). Quy đổi lít theo tên SKU giống
    finished_goods_shift_report (_resolve_liters_per_unit); SKU không suy được dung tích bị
    loại khỏi tổng, liệt kê ở unmatched_products."""
    rows = db.execute(
        select(FinishedGoodsUnit.quantity, FinishedGoodsUnit.shipped_at, FinishedProduct.name,
               FinishedProduct.category, FinishedGoodsUnit.is_near_expiry, FinishedGoodsUnit.is_consigned)
        .select_from(FinishedGoodsUnit)
        .outerjoin(FinishedProduct, FinishedProduct.finished_product_id == FinishedGoodsUnit.finished_product_id)
        .where(FinishedGoodsUnit.status == "shipped", FinishedGoodsUnit.shipped_at.isnot(None),
               FinishedGoodsUnit.shipped_at >= date_from, FinishedGoodsUnit.shipped_at < date_to)
    ).all()

    # Cộng dồn bằng float thô (chưa làm tròn) ở cả 3 tầng (theo ngày+loại bia / theo ngày /
    # tổng toàn kỳ) TỪ CÙNG NGUỒN — không cộng lại các số đã làm tròn ở tầng dưới, tránh lệch
    # do làm tròn nhiều lần (mỗi tầng làm tròn 1 lần duy nhất ở bước cuối, xem _finish).
    buckets: dict[tuple, dict] = {}
    day_totals: dict[str, dict] = {}
    grand = {"total_liters": 0.0, "near_expiry_liters": 0.0, "consigned_liters": 0.0}
    unmatched: dict[str, dict] = {}

    for qty, shipped_at, sku_name, category, is_near_expiry, is_consigned in rows:
        lpu = _resolve_liters_per_unit(sku_name)
        if lpu is None:
            label = sku_name or "(không tên)"
            u = unmatched.setdefault(label, {"product_name": label, "units": 0.0})
            u["units"] += qty or 0
            continue
        liters = (qty or 0) * lpu
        day_key, _ca = _bucket_shift(shipped_at)
        cat = category or "Khác"

        b = buckets.setdefault((day_key, cat), {"date": day_key, "category": cat,
                                                "total_liters": 0.0, "near_expiry_liters": 0.0,
                                                "consigned_liters": 0.0})
        d = day_totals.setdefault(day_key, {"date": day_key, "total_liters": 0.0,
                                            "near_expiry_liters": 0.0, "consigned_liters": 0.0})
        b["total_liters"] += liters
        d["total_liters"] += liters
        grand["total_liters"] += liters
        if is_near_expiry:
            b["near_expiry_liters"] += liters
            d["near_expiry_liters"] += liters
            grand["near_expiry_liters"] += liters
        if is_consigned:
            b["consigned_liters"] += liters
            d["consigned_liters"] += liters
            grand["consigned_liters"] += liters

    def _finish(r: dict) -> dict:
        r["total_liters"] = round(r["total_liters"])
        r["near_expiry_liters"] = round(r["near_expiry_liters"])
        r["consigned_liters"] = round(r["consigned_liters"])
        r["net_liters"] = r["total_liters"] - r["consigned_liters"]
        return r

    rows_out = sorted((_finish(b) for b in buckets.values()), key=lambda r: (r["date"], r["category"]))
    by_day = sorted((_finish(d) for d in day_totals.values()), key=lambda r: r["date"])
    totals = _finish(grand)

    return {"rows": rows_out, "by_day": by_day, "totals": totals,
            "unmatched_products": sorted(unmatched.values(), key=lambda u: -u["units"])}


def list_lot_summaries_by_location(db: Session, loc_id: str) -> list:
    """Tổng hợp tồn "stored" theo (sản phẩm, lô, loại đơn vị) tại RIÊNG 1 vị trí kho — dùng
    cho picker Điều chuyển nội bộ (chọn vị trí nguồn rồi xem có gì để chuyển), tính bằng
    GROUP BY ở SQL thay vì tải hết đơn vị toàn kho về rồi lọc/gộp bằng Python (kho có thể có
    hàng trăm ngàn đơn vị)."""
    rows = db.execute(select(FinishedGoodsUnit.product_name, FinishedGoodsUnit.lot_code,
                             FinishedGoodsUnit.unit_type, func.sum(FinishedGoodsUnit.quantity / _pack_divisor_expr(_divide_by_pack_codes(db))))
                      .select_from(FinishedGoodsUnit)
                      .outerjoin(FinishedProduct, FinishedProduct.finished_product_id == FinishedGoodsUnit.finished_product_id)
                      .where(FinishedGoodsUnit.status == "stored", FinishedGoodsUnit.location_id == loc_id)
                      .group_by(FinishedGoodsUnit.product_name, FinishedGoodsUnit.lot_code,
                               FinishedGoodsUnit.unit_type)).all()
    return [{"product_name": product_name, "lot_code": lot_code, "unit_type": unit_type, "count": count or 0}
            for product_name, lot_code, unit_type, count in rows]


def confirm_receipt_by_lot(db: Session, product_name: str, lot_code: str | None, unit_type: str,
                           user: User) -> dict:
    """Trưởng bộ phận kho duyệt nhập kho cho 1 lô đến từ chiết (source="chiet") HOẶC nhập tay
    thủ công (source="manual") — chỉ khoá lại (đánh dấu đã duyệt), KHÔNG đổi số liệu tồn kho.
    Sau khi duyệt: delete_unit/delete_units/delete_units_by_criteria chặn xóa các dòng này
    (mirror confirm_shipment); riêng lô "manual" còn được MỞ khoá xuất (create_shipment, xem
    _consume_lot_rows(block_pending_manual=True)) — lô "chiet" xuất được ngay từ đầu, duyệt chỉ
    ảnh hưởng tới xóa. Lô tồn đầu/near-expiry/consigned tự động đã "duyệt" từ lúc tạo, không
    còn khớp WHERE received_confirmed_by IS NULL nên không xuất hiện ở đây nữa."""
    require_perm(user, "wms.confirm_receipt")
    rows = db.execute(select(FinishedGoodsUnit).where(
        FinishedGoodsUnit.product_name == product_name, FinishedGoodsUnit.lot_code == lot_code,
        FinishedGoodsUnit.unit_type == unit_type, FinishedGoodsUnit.status == "stored",
        FinishedGoodsUnit.source.in_(("chiet", "manual")), FinishedGoodsUnit.received_confirmed_by.is_(None))).scalars().all()
    if not rows:
        raise DomainError("Không có lô nào đang chờ duyệt khớp tiêu chí này.")
    now = utcnow()
    for u in rows:
        u.received_confirmed_by = user.username
        u.received_confirmed_at = now
    record_audit(db, entity_type="finished_goods_unit", entity_id=rows[0].unit_id, action="confirm_receipt",
                 actor=user, after={"product_name": product_name, "lot_code": lot_code,
                                    "unit_type": unit_type, "confirmed": len(rows)})
    db.commit()
    return {"confirmed": len(rows)}


def delete_units_by_criteria(db: Session, product_name: str, lot_code: str | None, unit_type: str,
                             user: User) -> dict:
    """Xóa CẢ LÔ vỉ/keg theo (sản phẩm, lô, loại) thay vì theo danh sách unit_id — tránh phải
    tải/gửi hàng trăm ngàn unit_id qua mạng (xem delete_units cho trường hợp chọn từng đơn
    vị cụ thể). CHỈ xóa các dòng đang "stored" (đã xuất/phân rã thì lô này không còn khớp
    tiêu chí lọc status='stored' nên tự động không bị đụng tới — không cần kiểm tra riêng
    từng dòng như delete_units)."""
    require_perm(user, "warehouse.issue")
    confirmed_count = db.execute(select(func.count()).select_from(FinishedGoodsUnit).where(
        FinishedGoodsUnit.product_name == product_name, FinishedGoodsUnit.lot_code == lot_code,
        FinishedGoodsUnit.unit_type == unit_type, FinishedGoodsUnit.status == "stored",
        FinishedGoodsUnit.source.in_(("chiet", "manual")),
        FinishedGoodsUnit.received_confirmed_by.isnot(None))).scalar_one()
    if confirmed_count:
        raise DomainError("Lô này đã được Trưởng bộ phận kho duyệt nhập kho — không thể xóa.")
    ids = [row[0] for row in db.execute(select(FinishedGoodsUnit.unit_id).where(
        FinishedGoodsUnit.product_name == product_name, FinishedGoodsUnit.lot_code == lot_code,
        FinishedGoodsUnit.unit_type == unit_type, FinishedGoodsUnit.status == "stored")).all()]
    if not ids:
        raise DomainError("Không tìm thấy vỉ/keg nào khớp lô này để xóa.")
    bottles_reset = set()
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        edges = db.execute(select(GenealogyEdge).where(or_(
            and_(GenealogyEdge.to_type == "finished_goods_unit", GenealogyEdge.to_id.in_(chunk)),
            and_(GenealogyEdge.from_type == "finished_goods_unit", GenealogyEdge.from_id.in_(chunk))))).scalars().all()
        for e in edges:
            if e.to_type == "finished_goods_unit" and e.to_id in chunk and e.from_type == "bottle":
                bottle = db.get(BottleRecord, e.from_id)
                if bottle:
                    bottle.approved = False
                    bottle.stocked = False
                    bottles_reset.add(bottle.bottle_code)
            db.delete(e)
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        db.execute(delete(FinishedGoodsUnit).where(FinishedGoodsUnit.unit_id.in_(chunk)))
    record_audit(db, entity_type="finished_goods_unit", entity_id=ids[0], action="delete_by_lot", actor=user,
                 before={"product_name": product_name, "lot_code": lot_code, "unit_type": unit_type},
                 after={"deleted": len(ids), "bottles_reset": sorted(bottles_reset)})
    db.commit()
    return {"deleted": len(ids), "bottles_reset": sorted(bottles_reset)}


def _next_shipment_code(db: Session, year: int) -> str:
    """Số phiếu xuất kho theo đúng mẫu biên bản bàn giao hàng hóa giấy: {số:03d}/{năm}/BBBG-BHL.
    Dựa trên SỐ LỚN NHẤT đã dùng cho năm đó (không phải COUNT) — xóa 1 phiếu ở giữa vẫn phải
    tiếp tục tăng từ số cao nhất, không cấp lại trùng số đã xóa (cùng cách với LoadSlip.slip_code
    ở services/load_slip.py::_next_slip_code, nhưng đây là dãy số RIÊNG cho Shipment)."""
    suffix = f"/{year}/BBBG-BHL"
    existing = db.execute(select(Shipment.shipment_code)
                         .where(Shipment.shipment_code.like(f"%{suffix}"))).scalars().all()
    max_seq = 0
    for code in existing:
        try:
            max_seq = max(max_seq, int(code.split("/")[0]))
        except (ValueError, IndexError):
            pass
    return f"{max_seq + 1:03d}{suffix}"


def create_shipment(db: Session, ship_to_id: str, lines: list, user: User, header: dict | None = None,
                    warehouse_id: str | None = None) -> dict:
    """Xuất kho — mỗi dòng chọn (sản phẩm, lô, loại đơn vị, số lượng); hệ thống tự chọn
    đúng số vỉ/keg/lon cũ nhất (FIFO) trong lô đó, không cần liệt kê/chọn từng đơn vị (kho
    có thể có hàng trăm ngàn vỉ). Không đủ tồn cho 1 dòng thì báo lỗi rõ ràng (không xuất
    thiếu âm thầm). FIFO check: nếu unit được chọn trong khi còn unit CÙNG SẢN PHẨM cũ hơn
    (created_at sớm hơn) mà KHÔNG nằm trong danh sách đang xuất, coi là vi phạm FIFO.
    warehouse_id ("Kho xuất"): giới hạn FIFO trong 1 Kho thành phẩm — BẮT BUỘC nếu tài khoản
    bị giới hạn kho (xem _wh_scope_restricted), tuỳ chọn nếu không (mặc định FIFO tự do toàn
    công ty như trước)."""
    require_perm(user, "warehouse.issue")
    if not ship_to_id:
        raise DomainError("Phải chọn nơi xuất đến.")
    ship_to = db.get(Supplier, ship_to_id)
    if not ship_to:
        raise NotFoundError("Nơi xuất đến không tồn tại.")
    if not lines:
        raise DomainError("Phải chọn ít nhất 1 dòng sản phẩm để xuất.")
    if warehouse_id:
        _assert_wh_scope(db, user, warehouse_id)
    elif _wh_scope_restricted(user):
        raise DomainError("Vui lòng chọn kho xuất (tài khoản bị giới hạn kho thành phẩm).")

    divide_codes = _divide_by_pack_codes(db)
    units = []
    picked_so_far = set()
    # 1 phiếu (Shipment) giờ có thể gồm nhiều dòng với "Loại xuất" khác nhau (VD 1 dòng thường
    # + 1 dòng khuyến mại, cùng 1 nhà phân phối) — lưu type CỦA TỪNG DÒNG lên chính đơn vị được
    # chọn cho dòng đó (FinishedGoodsUnit.shipment_line_type), KHÔNG còn dùng 1 giá trị chung
    # cho cả Shipment (xem docstring model + list_shipments/shipment_classification_report).
    unit_line_type: dict[str, str] = {}
    line_types_used: set[str] = set()
    for line in lines:
        product_name = line.get("product_name")
        unit_type = line.get("unit_type")
        lot_code = line.get("lot_code")
        qty = int(line.get("quantity") or 0)
        near_expiry_only = bool(line.get("near_expiry_only"))
        consigned_only = bool(line.get("consigned_only"))
        shipment_type_line = line.get("shipment_type") or "normal"
        if not product_name or not unit_type:
            raise DomainError("Mỗi dòng phải có sản phẩm và loại đơn vị.")
        if qty <= 0:
            raise DomainError(f"Số lượng cần xuất cho {product_name} phải > 0.")
        if near_expiry_only and consigned_only:
            raise DomainError(f"{product_name}: 1 dòng chỉ được chọn 1 trong 2 — bia cận date HOẶC bia gửi.")
        fp = db.execute(select(FinishedProduct).where(FinishedProduct.code == product_name)).scalar_one_or_none()
        divisor = _pack_divisor(fp, unit_type, divide_codes)
        # KHÔNG loại trừ hàng "chưa cất" ở đây — chặn chọn hàng chưa cất vị trí là quy tắc UX
        # của picker Xuất kho (frontend renderLots/sellable trong views_ext.js), không áp bắt
        # buộc ở API để không phá các luồng test/nghiệp vụ khác đang xuất thẳng hàng mới nhập
        # chưa kịp cất vị trí (ví dụ tồn đầu kho, test nội bộ).
        candidates, got = _consume_lot_rows(
            db, product_name=product_name, unit_type=unit_type, status="stored",
            quantity_needed=qty * divisor, lot_code=lot_code, exclude_ids=picked_so_far,
            near_expiry_only=near_expiry_only, consigned_only=consigned_only, block_pending_manual=True,
            warehouse_id=warehouse_id)
        if got + 1e-9 < qty * divisor:
            special_note = " (bia cận date)" if near_expiry_only else " (bia gửi)" if consigned_only else ""
            # Gợi ý lý do thiếu hàng khi thực ra còn "Nhập kho thủ công" đang chờ Trưởng bộ phận
            # kho duyệt (chưa xuất được, xem _consume_lot_rows(block_pending_manual=True)) — tránh
            # người dùng tưởng nhầm là kho thật sự hết hàng.
            pending_stmt = select(func.sum(FinishedGoodsUnit.quantity)).where(
                FinishedGoodsUnit.product_name == product_name, FinishedGoodsUnit.unit_type == unit_type,
                FinishedGoodsUnit.status == "stored", FinishedGoodsUnit.source == "manual",
                FinishedGoodsUnit.received_confirmed_by.is_(None))
            if lot_code:
                pending_stmt = pending_stmt.where(FinishedGoodsUnit.lot_code == lot_code)
            pending = db.execute(pending_stmt).scalar() or 0
            pending_note = (f" (còn {pending / divisor:g} đang chờ Trưởng bộ phận kho duyệt nhập kho)"
                            if pending else "")
            raise DomainError(f"{product_name} {lot_code or ''}{special_note}: chỉ còn {got / divisor:g} "
                              f"đơn vị tồn kho, không đủ {qty} yêu cầu.{pending_note}")
        units.extend(candidates)
        picked_so_far.update(u.unit_id for u in candidates)
        line_types_used.add(shipment_type_line)
        for u in candidates:
            unit_line_type[u.unit_id] = shipment_type_line

    picked_ids = picked_so_far
    fifo_ok = True
    for u in units:
        if not u.product_name:
            continue
        older = db.execute(select(FinishedGoodsUnit).where(
            FinishedGoodsUnit.product_name == u.product_name, FinishedGoodsUnit.status == "stored",
            FinishedGoodsUnit.unit_id != u.unit_id, FinishedGoodsUnit.created_at < u.created_at)).scalars().all()
        if any(o.unit_id not in picked_ids for o in older):
            fifo_ok = False
            break

    # Xuất tại kho = vị trí hiện đang lưu các vỉ/keg được chọn — tự suy ra từ location_id
    # của chính các đơn vị này (TRƯỚC khi bị xóa ở vòng lặp dưới), không cho nhập tay nữa vì
    # dễ sai/không khớp thực tế. Ghi cả mã + tên (không chỉ mã) để hiển thị rõ ràng ở Lịch sử
    # xuất kho. Nhiều vị trí khác nhau thì liệt kê cách nhau dấu phẩy.
    loc_ids = {u.location_id for u in units if u.location_id}
    locs = db.execute(select(WmsLocation).where(WmsLocation.loc_id.in_(loc_ids))).scalars().all() if loc_ids else []
    from_location = ", ".join(sorted({f"{l.code} - {l.name}" if l.name else l.code for l in locs})) or None

    header = header or {}
    # Shipment.shipment_type (cột cũ) nay chỉ còn ý nghĩa TÓM TẮT cho cả phiếu — giống nhau ở
    # mọi dòng thì giữ giá trị đó (in phiếu/lịch sử cũ vẫn đọc đúng), khác nhau thì "mixed" (UI
    # hiện "Loại xuất" thật theo TỪNG DÒNG, xem list_shipments/shipment_line_type ở trên).
    header_shipment_type = (next(iter(line_types_used)) if len(line_types_used) == 1
                            else "mixed" if line_types_used else "normal")
    shipment = Shipment(shipment_id=new_id(), shipment_code=_next_shipment_code(db, utcnow().year),
                        ship_to_id=ship_to_id, created_by=user.username, created_at=utcnow(),
                        fifo_ok=fifo_ok, note=header.get("note"),
                        recipient_name=header.get("recipient_name"), recipient_dept=header.get("recipient_dept"),
                        driver_name=header.get("driver_name"), vehicle_plate=header.get("vehicle_plate"),
                        vehicle_id=header.get("vehicle_id") if header.get("vehicle_id") and
                                  db.get(Vehicle, header.get("vehicle_id")) else None,
                        from_location=from_location, delivery_place=header.get("delivery_place"),
                        shipment_type=header_shipment_type)
    db.add(shipment)
    db.flush()

    out_lines = []
    near_expiry_groups: dict[tuple, float] = {}
    consigned_groups: dict[tuple, float] = {}
    fp_cache: dict = {}

    def _divisor_of(u):
        if u.finished_product_id not in fp_cache:
            fp_cache[u.finished_product_id] = db.get(FinishedProduct, u.finished_product_id) if u.finished_product_id else None
        return _pack_divisor(fp_cache[u.finished_product_id], u.unit_type, divide_codes)

    for u in units:
        u.status = "shipped"
        u.location_id = None
        u.shipped_at = utcnow()
        u.shipment_id = shipment.shipment_id
        u.ship_to_id = ship_to_id
        u.shipment_line_type = unit_line_type.get(u.unit_id, "normal")
        genealogy.add_edge(db, from_type="finished_goods_unit", from_id=u.unit_id, to_type="ship_to",
                           to_id=ship_to_id, relation="xuất kho", quantity=u.quantity, uom=u.unit_type)
        out_lines.append({"unit_code": u.unit_code, "product": u.product_name, "lot_code": u.lot_code})
        if u.is_near_expiry:
            # Đếm theo SL vỉ/keg/lon quy đổi (quantity/pack_size), KHÔNG +1 mỗi dòng — 1 dòng
            # giờ có thể đại diện nhiều đơn vị đóng gói (xem docs/WMS-LOT-LEVEL-REDESIGN.md).
            key = (u.product_name, u.lot_code, u.unit_type)
            near_expiry_groups[key] = near_expiry_groups.get(key, 0) + u.quantity / _divisor_of(u)
        if u.is_consigned:
            key = (u.product_name, u.lot_code, u.unit_type)
            consigned_groups[key] = consigned_groups.get(key, 0) + u.quantity / _divisor_of(u)

    # Xuất kho có bao gồm bia cận date — tự động ghi thêm dòng "xuất" vào lịch sử riêng
    # (tách khỏi lịch sử xuất kho thông thường) để tra cứu vòng đời bia cận date đầy đủ.
    for (product_name, lot_code, unit_type), count in near_expiry_groups.items():
        db.add(NearExpiryEntry(entry_id=new_id(), direction="out", product_name=product_name, lot_code=lot_code,
                               unit_type=unit_type, quantity=count, shipment_id=shipment.shipment_id,
                               created_by=user.username, created_at=utcnow()))
    # Tương tự cho bia gửi — mirror y hệt near_expiry_groups ở trên.
    for (product_name, lot_code, unit_type), count in consigned_groups.items():
        db.add(ConsignedEntry(entry_id=new_id(), direction="out", product_name=product_name, lot_code=lot_code,
                              unit_type=unit_type, quantity=count, shipment_id=shipment.shipment_id,
                              created_by=user.username, created_at=utcnow()))

    record_audit(db, entity_type="shipment", entity_id=shipment.shipment_id, action="create", actor=user,
                 after={"shipment_code": shipment.shipment_code, "ship_to": ship_to.code,
                        "units": out_lines, "fifo_ok": fifo_ok})
    db.commit()
    return {"shipment_id": shipment.shipment_id, "shipment_code": shipment.shipment_code,
            "ship_to_code": ship_to.code, "fifo_ok": fifo_ok, "units": out_lines}


def list_shipments(db: Session, limit: int = 200, offset: int = 0) -> list:
    """Có phân trang (limit tối đa 2000, offset) — số phiếu xuất kho tăng dần vô hạn theo thời
    gian. Nạp 1 LẦN toàn bộ FinishedGoodsUnit của các phiếu trong trang hiện tại rồi nhóm theo
    shipment_id trong Python, thay vì mỗi phiếu 1 query riêng (N+1) như trước."""
    limit = max(1, min(limit or 200, 2000))
    offset = max(0, offset or 0)
    ships = db.execute(select(Shipment).order_by(Shipment.created_at.desc())
                      .limit(limit).offset(offset)).scalars().all()
    ship_to_by = {s.supplier_id: s for s in db.execute(select(Supplier)).scalars().all()}
    vehicle_by_id = {v.vehicle_id: v for v in db.execute(select(Vehicle)).scalars().all()}
    fp_cache: dict = {}
    divide_codes = _divide_by_pack_codes(db)

    def _divisor_of(u):
        if u.finished_product_id not in fp_cache:
            fp_cache[u.finished_product_id] = db.get(FinishedProduct, u.finished_product_id) if u.finished_product_id else None
        return _pack_divisor(fp_cache[u.finished_product_id], u.unit_type, divide_codes)

    shipment_ids = [s.shipment_id for s in ships]
    units_by_shipment: dict[str, list] = {}
    if shipment_ids:
        for u in db.execute(select(FinishedGoodsUnit).where(
                FinishedGoodsUnit.shipment_id.in_(shipment_ids))).scalars().all():
            units_by_shipment.setdefault(u.shipment_id, []).append(u)

    out = []
    for s in ships:
        units = units_by_shipment.get(s.shipment_id, [])
        # Gom nhóm theo (product, lot_code, unit_type) để in phiếu — thay cho bảng dòng riêng.
        # "count" = số vỉ/keg/lon quy đổi (quantity/pack_size), KHÔNG đếm dòng (1 dòng giờ có
        # thể đại diện nhiều đơn vị đóng gói, xem docs/WMS-LOT-LEVEL-REDESIGN.md).
        grouped: dict[tuple, dict] = {}
        for u in units:
            line_type = u.shipment_line_type or "normal"
            key = (u.product_name, u.lot_code, u.unit_type, line_type)
            g = grouped.setdefault(key, {"product": u.product_name, "lot_code": u.lot_code,
                                         "unit_type": u.unit_type, "count": 0.0, "quantity": 0.0,
                                         "near_expiry": False, "consigned": False, "type": line_type})
            g["count"] += u.quantity / _divisor_of(u)
            g["quantity"] += u.quantity
            if u.is_near_expiry:
                g["near_expiry"] = True
            if u.is_consigned:
                g["consigned"] = True
        ship_to = ship_to_by.get(s.ship_to_id)
        vehicle = vehicle_by_id.get(s.vehicle_id) if s.vehicle_id else None
        unit_count = sum(g["count"] for g in grouped.values())
        out.append({"shipment_id": s.shipment_id, "shipment_code": s.shipment_code,
                    "ship_to_code": ship_to.code if ship_to else None,
                    "ship_to_name": ship_to.name if ship_to else None,
                    "ship_to_address": ship_to.address if ship_to else None,
                    "created_by": s.created_by, "created_at": s.created_at, "fifo_ok": s.fifo_ok,
                    "shipment_type": s.shipment_type,
                    "note": s.note, "recipient_name": s.recipient_name, "recipient_dept": s.recipient_dept,
                    "driver_name": s.driver_name, "vehicle_plate": s.vehicle_plate,
                    "vehicle_code": vehicle.vehicle_code if vehicle else None,
                    "km": s.km, "fuel_liters": s.fuel_liters,
                    "from_location": s.from_location, "delivery_place": s.delivery_place,
                    "confirmed_by": s.confirmed_by, "confirmed_at": s.confirmed_at,
                    "unit_count": unit_count, "lines": list(grouped.values())})
    return out


def confirm_shipment(db: Session, shipment_id: str, user: User) -> dict:
    """Trưởng bộ phận kho xác nhận phiếu xuất kho — chỉ khoá lại (đánh dấu đã xác nhận), KHÔNG
    đổi số liệu tồn kho. Sau khi xác nhận, undo_shipment() khoá lại — chỉ ADMIN mới "Hoàn tác"
    được nữa."""
    require_perm(user, "wms.confirm_shipment")
    shipment = db.get(Shipment, shipment_id)
    if not shipment:
        raise NotFoundError("Phiếu xuất kho không tồn tại.")
    if shipment.confirmed_by:
        raise DomainError("Phiếu này đã được xác nhận trước đó.")
    shipment.confirmed_by = user.username
    shipment.confirmed_at = utcnow()
    record_audit(db, entity_type="shipment", entity_id=shipment.shipment_id, action="confirm", actor=user)
    db.commit()
    return {"shipment_id": shipment.shipment_id, "confirmed_by": shipment.confirmed_by,
            "confirmed_at": shipment.confirmed_at}


def update_shipment_trip(db: Session, shipment_id: str, km: float | None, fuel_liters: float | None,
                         user: User) -> dict:
    """Điền km/lít xăng của 1 chuyến xuất — chỉ cho phép SAU KHI phiếu đã Duyệt (confirmed_by),
    vì trước đó chuyến chưa thực sự khởi hành. Cho sửa lại nhiều lần (không khoá), dùng cho báo
    cáo định mức nhiên liệu (xem fuel_efficiency_report)."""
    require_perm(user, "warehouse.issue")
    shipment = db.get(Shipment, shipment_id)
    if not shipment:
        raise NotFoundError("Phiếu xuất kho không tồn tại.")
    if not shipment.confirmed_by:
        raise DomainError("Chỉ được điền km/lít xăng sau khi phiếu đã được duyệt.")
    shipment.km = km
    shipment.fuel_liters = fuel_liters
    record_audit(db, entity_type="shipment", entity_id=shipment.shipment_id, action="update_trip", actor=user,
                after={"km": km, "fuel_liters": fuel_liters})
    db.commit()
    return {"shipment_id": shipment.shipment_id, "km": shipment.km, "fuel_liters": shipment.fuel_liters}


_SHIPMENT_EDITABLE_FIELDS = ("note", "recipient_name", "recipient_dept", "driver_name",
                             "vehicle_plate", "from_location", "delivery_place", "shipment_type")


def update_shipment(db: Session, shipment_id: str, payload: dict, user: User) -> dict:
    """Sửa thông tin đầu phiếu xuất kho (người nhận, lái xe, biển số, địa điểm, lý do...) — chỉ
    các trường mô tả, KHÔNG đụng tới số liệu tồn kho/dòng hàng. Chặn sửa sau khi đã "Duyệt"
    (confirmed_by) — lúc đó phiếu coi như chốt, chỉ còn Hoàn tác (ADMIN) mới đổi được."""
    require_perm(user, "warehouse.issue")
    shipment = db.get(Shipment, shipment_id)
    if not shipment:
        raise NotFoundError("Phiếu xuất kho không tồn tại.")
    if shipment.confirmed_by:
        raise DomainError("Phiếu đã được duyệt — không thể sửa nữa.")
    before = {f: getattr(shipment, f) for f in _SHIPMENT_EDITABLE_FIELDS}
    for field in _SHIPMENT_EDITABLE_FIELDS:
        if field in payload:
            setattr(shipment, field, payload[field])
    record_audit(db, entity_type="shipment", entity_id=shipment.shipment_id, action="update",
                 actor=user, before=before, after={f: getattr(shipment, f) for f in _SHIPMENT_EDITABLE_FIELDS})
    db.commit()
    return {"shipment_id": shipment.shipment_id}


def undo_shipment(db: Session, shipment_id: str, user: User) -> dict:
    """Hoàn tác 1 phiếu xuất kho — trả các vỉ/keg/lon đã xuất về "stored" (gỡ khỏi phiếu/nơi
    xuất đến). Không giữ lại location_id gốc (đã bị xóa lúc xuất) — hàng về kho coi như chưa
    xếp vị trí, xếp lại thủ công (Điều chuyển) nếu cần. Không xóa phiếu (giữ làm lịch sử) —
    idempotent tự nhiên: sau khi hoàn tác, truy vấn theo shipment_id không còn ra unit nào
    nên gọi lại sẽ báo lỗi thay vì hoàn tác lần 2.

    Nếu Trưởng bộ phận kho đã xác nhận (confirmed_by), CHỈ ADMIN mới được hoàn tác."""
    require_perm(user, "warehouse.issue")
    shipment = db.get(Shipment, shipment_id)
    if not shipment:
        raise NotFoundError("Phiếu xuất kho không tồn tại.")
    if shipment.confirmed_by:
        require_role(user, Role.ADMIN)
    units = db.execute(select(FinishedGoodsUnit).where(
        FinishedGoodsUnit.shipment_id == shipment_id)).scalars().all()
    if not units:
        raise DomainError("Phiếu này không còn đơn vị nào để hoàn tác (có thể đã hoàn tác trước đó).")
    unit_ids = [u.unit_id for u in units]
    fp_cache: dict = {}
    divide_codes = _divide_by_pack_codes(db)

    def _divisor_of(u):
        if u.finished_product_id not in fp_cache:
            fp_cache[u.finished_product_id] = db.get(FinishedProduct, u.finished_product_id) if u.finished_product_id else None
        return _pack_divisor(fp_cache[u.finished_product_id], u.unit_type, divide_codes)

    restored_count = sum(u.quantity / _divisor_of(u) for u in units)
    for u in units:
        u.status = "stored"
        u.shipped_at = None
        u.shipment_id = None
        u.ship_to_id = None
    edges = db.execute(select(GenealogyEdge).where(
        GenealogyEdge.from_type == "finished_goods_unit", GenealogyEdge.from_id.in_(unit_ids),
        GenealogyEdge.to_type == "ship_to", GenealogyEdge.to_id == shipment.ship_to_id)).scalars().all()
    for e in edges:
        db.delete(e)
    record_audit(db, entity_type="shipment", entity_id=shipment_id, action="undo", actor=user,
                 before={"unit_count": restored_count}, after={"restored": restored_count})
    db.commit()
    return {"shipment_id": shipment_id, "restored": restored_count}


def delete_unit(db: Session, unit_id: str, user: User) -> None:
    """Xóa 1 vỉ/keg — chỉ khi CHƯA xuất kho (status != "shipped"), vì hàng đã xuất là đã ra
    khỏi nhà máy trong thực tế, xóa bản ghi sẽ làm sai lệch hồ sơ/không khớp thực tế. Xóa
    xong phải "mở khóa" lại bản ghi Chiết nguồn (approved/stocked -> False, xem
    routers/brewing.py::approve_bottle) để người dùng có thể sửa/xóa lại chiết nếu cần —
    đúng quy tắc "muốn xóa bước trước thì bước sau phải được xóa trước"."""
    require_perm(user, "warehouse.issue")
    u = db.get(FinishedGoodsUnit, unit_id)
    if not u:
        raise NotFoundError("Vỉ/keg không tồn tại.")
    if u.status == "shipped":
        raise DomainError("Đã xuất kho — không thể xóa.")
    if u.status == "decomposed":
        raise DomainError("Đã phân rã thành lon — không thể xóa (còn lon con phụ thuộc).")
    if u.source in ("chiet", "manual") and u.received_confirmed_by:
        raise DomainError("Đã được Trưởng bộ phận kho duyệt nhập kho — không thể xóa.")
    for e in db.execute(select(GenealogyEdge).where(or_(
            and_(GenealogyEdge.to_type == "finished_goods_unit", GenealogyEdge.to_id == unit_id),
            and_(GenealogyEdge.from_type == "finished_goods_unit", GenealogyEdge.from_id == unit_id)))).scalars().all():
        if e.to_type == "finished_goods_unit" and e.to_id == unit_id and e.from_type == "bottle":
            bottle = db.get(BottleRecord, e.from_id)
            if bottle:
                bottle.approved = False
                bottle.stocked = False
        db.delete(e)
    record_audit(db, entity_type="finished_goods_unit", entity_id=unit_id, action="delete", actor=user,
                 before={"unit_code": u.unit_code, "status": u.status})
    db.delete(u)
    db.commit()


def delete_units(db: Session, unit_ids: list[str], user: User) -> dict:
    """Xóa CẢ LÔ vỉ/keg cùng lúc (VD xóa nguyên lần nhập kho tự động sau khi duyệt chiết) —
    mirror delete_unit nhưng gộp nhiều dòng, validate HẾT trước khi xóa dòng nào (không xóa
    dở dang nếu 1 dòng ở giữa bị chặn). Cùng logic "mở khóa" lại Chiết nguồn — xem
    delete_unit."""
    require_perm(user, "warehouse.issue")
    if not unit_ids:
        raise DomainError("Chưa chọn vỉ/keg nào để xóa.")
    units = []
    for unit_id in unit_ids:
        u = db.get(FinishedGoodsUnit, unit_id)
        if not u:
            raise NotFoundError("Vỉ/keg không tồn tại.")
        if u.status == "shipped":
            raise DomainError(f"{u.unit_code} đã xuất kho — không thể xóa.")
        if u.status == "decomposed":
            raise DomainError(f"{u.unit_code} đã phân rã thành lon — không thể xóa (còn lon con phụ thuộc).")
        if u.source in ("chiet", "manual") and u.received_confirmed_by:
            raise DomainError(f"{u.unit_code} đã được Trưởng bộ phận kho duyệt nhập kho — không thể xóa.")
        units.append(u)
    bottles_reset = set()
    for u in units:
        for e in db.execute(select(GenealogyEdge).where(or_(
                and_(GenealogyEdge.to_type == "finished_goods_unit", GenealogyEdge.to_id == u.unit_id),
                and_(GenealogyEdge.from_type == "finished_goods_unit", GenealogyEdge.from_id == u.unit_id)))).scalars().all():
            if e.to_type == "finished_goods_unit" and e.to_id == u.unit_id and e.from_type == "bottle":
                bottle = db.get(BottleRecord, e.from_id)
                if bottle:
                    bottle.approved = False
                    bottle.stocked = False
                    bottles_reset.add(bottle.bottle_code)
            db.delete(e)
        record_audit(db, entity_type="finished_goods_unit", entity_id=u.unit_id, action="delete", actor=user,
                     before={"unit_code": u.unit_code, "status": u.status})
        db.delete(u)
    db.commit()
    return {"deleted": len(units), "bottles_reset": sorted(bottles_reset)}


def resolve(db: Session, code: str) -> dict:
    """Phân giải barcode (cho kiosk/đầu đọc) — mã vạch/QR in theo LÔ (không in riêng từng
    vỉ), nên trước tiên tra theo lot_code (tổng hợp số lượng theo trạng thái/loại); chỉ
    còn tra theo unit_code (mã nội bộ từng dòng) để tương thích các tem cũ đã in trước đây."""
    lot_units = db.execute(select(FinishedGoodsUnit).where(FinishedGoodsUnit.lot_code == code)).scalars().all()
    if lot_units:
        # Đếm theo SL vỉ/keg/lon quy đổi (quantity/pack_size), KHÔNG đếm dòng — xem
        # docs/WMS-LOT-LEVEL-REDESIGN.md. fp_cache tránh tra FinishedProduct lặp lại nhiều lần.
        fp_cache: dict = {}
        divide_codes = _divide_by_pack_codes(db)

        def _divisor_of(u):
            if u.finished_product_id not in fp_cache:
                fp_cache[u.finished_product_id] = db.get(FinishedProduct, u.finished_product_id) if u.finished_product_id else None
            return _pack_divisor(fp_cache[u.finished_product_id], u.unit_type, divide_codes)

        by_status: dict = {}
        by_type: dict = {}
        unit_count = 0.0
        for u in lot_units:
            n = u.quantity / _divisor_of(u)
            by_status[u.status] = by_status.get(u.status, 0) + n
            by_type[u.unit_type] = by_type.get(u.unit_type, 0) + n
            unit_count += n
        return {"type": "lot", "lot_code": code, "product": lot_units[0].product_name,
                "unit_count": unit_count, "by_status": by_status, "by_type": by_type}
    u = db.execute(select(FinishedGoodsUnit).where(FinishedGoodsUnit.unit_code == code)).scalar_one_or_none()
    if u:
        loc = db.get(WmsLocation, u.location_id) if u.location_id else None
        return {"type": "finished_goods_unit", "unit_code": u.unit_code, "unit_type": u.unit_type,
                "product": u.product_name, "lot_code": u.lot_code, "quantity": u.quantity,
                "status": u.status, "location": loc.code if loc else None}
    return {"type": "unknown", "code": code}


def relocate_batch(db: Session, product_name: str, lot_code: str, unit_type: str,
                   from_loc_id: str | None, to_loc_id: str, count: int, user: User) -> dict:
    """Gán/chuyển vị trí cho N đơn vị (cũ nhất trước) của 1 sản phẩm/lô/loại — dùng cho
    "Cất" hàng loạt (from_loc_id=None: đơn vị chưa có vị trí) hoặc điều chuyển hàng loạt
    theo số lượng thay vì phải chọn từng đơn vị. Dòng lô có thể đại diện hàng trăm nghìn
    vỉ/keg gộp lại (xem docs/WMS-LOT-LEVEL-REDESIGN.md) nên tiêu thụ qua _consume_lot_rows
    (tách dòng khi chỉ chuyển MỘT PHẦN của 1 dòng lớn), không còn chọn nguyên dòng như trước."""
    require_perm(user, "warehouse.issue")
    if count <= 0:
        raise DomainError("Số lượng phải > 0.")
    to_loc = db.get(WmsLocation, to_loc_id)
    if not to_loc:
        raise NotFoundError("Vị trí đích không tồn tại.")
    _assert_wh_scope(db, user, to_loc.warehouse_id)
    if from_loc_id:
        # Chỉ chặn khi có vị trí nguồn thật (đang cất) — hàng "chưa cất" (from_loc_id=None) chưa
        # thuộc kho nào nên không có gì để so sánh, vẫn cho cất vào bất kỳ kho nào như trước.
        from_loc_check = db.get(WmsLocation, from_loc_id)
        if from_loc_check and from_loc_check.warehouse_id != to_loc.warehouse_id:
            raise DomainError("Chỉ được chuyển vị trí trong cùng 1 kho thành phẩm — chọn vị trí đích cùng kho với vị trí nguồn.")

    fp = db.execute(select(FinishedProduct).where(FinishedProduct.code == product_name)).scalar_one_or_none()
    divisor = _pack_divisor(fp, unit_type, _divide_by_pack_codes(db))
    candidates, got = _consume_lot_rows(db, product_name=product_name, unit_type=unit_type, status="stored",
                                        quantity_needed=count * divisor, lot_code=lot_code,
                                        location_id=from_loc_id, block_pending_manual=True)
    if not candidates:
        raise DomainError("Không còn đơn vị nào phù hợp để xử lý (hoặc chỉ còn lô nhập tay chưa "
                          "được duyệt nhập kho).")
    moved_count = got / divisor

    moving_in = [u for u in candidates if u.location_id != to_loc_id]
    if moving_in:
        used_at_dest = _location_used_count(db, to_loc_id)
        moving_in_count = sum(u.quantity for u in moving_in) / divisor
        if used_at_dest + moving_in_count > to_loc.capacity:
            raise DomainError(f"Vị trí {to_loc.code} không đủ sức chứa (sức chứa {to_loc.capacity}, "
                              f"hiện có {used_at_dest:g}, cần thêm {moving_in_count:g}).")

    from_loc = db.get(WmsLocation, from_loc_id) if from_loc_id else None
    for u in candidates:
        u.location_id = to_loc_id
    record_audit(db, entity_type="finished_goods_unit", entity_id=new_id(), action="relocate_batch", actor=user,
                 before={"product_name": product_name, "lot_code": lot_code, "unit_type": unit_type, "requested": count,
                         "from_location": from_loc.code if from_loc else None},
                 after={"moved": moved_count, "to_location": to_loc.code})
    db.commit()
    return {"moved": moved_count, "to_location": to_loc.code, "requested": count}


def _next_transfer_code(db: Session, year: int) -> str:
    """Số phiếu điều chuyển — mirror _next_shipment_code nhưng dãy số RIÊNG cho WmsTransfer."""
    suffix = f"/{year}/DC-BHL"
    existing = db.execute(select(WmsTransfer.transfer_code)
                         .where(WmsTransfer.transfer_code.like(f"%{suffix}"))).scalars().all()
    max_seq = 0
    for code in existing:
        try:
            max_seq = max(max_seq, int(code.split("/")[0]))
        except (ValueError, IndexError):
            pass
    return f"{max_seq + 1:03d}{suffix}"


def create_transfer(db: Session, to_location_id: str, lines: list, user: User, header: dict | None = None) -> dict:
    """Điều chuyển nội bộ — mirror y hệt create_shipment (chọn theo sản phẩm/lô/loại đơn vị/số
    lượng, hệ thống tự chọn FIFO cũ nhất, kiểm tra vi phạm FIFO, có thể kèm xe/lái xe) NHƯNG đích
    là 1 WmsLocation (không phải Supplier/ship_to) và KHÔNG làm giảm tổng tồn kho toàn công ty:
    CHỈ đổi FinishedGoodsUnit.location_id (giữ status="stored"), KHÔNG tạo genealogy edge ra
    ngoài, KHÔNG đụng lot_code — giữ nguyên mã chiết để truy xuất nguồn gốc không đứt. Không có
    near_expiry_only/consigned_only/shipment_type (không có ý nghĩa cho luồng nội bộ — các cờ
    is_near_expiry/is_consigned trên đơn vị vẫn giữ nguyên nguyên vẹn qua lần điều chuyển)."""
    require_perm(user, "warehouse.issue")
    if not to_location_id:
        raise DomainError("Phải chọn vị trí đích.")
    to_loc = db.get(WmsLocation, to_location_id)
    if not to_loc:
        raise NotFoundError("Vị trí đích không tồn tại.")
    _assert_wh_scope(db, user, to_loc.warehouse_id)
    if not lines:
        raise DomainError("Phải chọn ít nhất 1 dòng sản phẩm để điều chuyển.")

    restricted = _wh_scope_restricted(user)
    divide_codes = _divide_by_pack_codes(db)
    units: list[FinishedGoodsUnit] = []
    picked_so_far: set = set()
    for line in lines:
        product_name = line.get("product_name")
        unit_type = line.get("unit_type")
        lot_code = line.get("lot_code")
        qty = int(line.get("quantity") or 0)
        if not product_name or not unit_type:
            raise DomainError("Mỗi dòng phải có sản phẩm và loại đơn vị.")
        if qty <= 0:
            raise DomainError(f"Số lượng cần chuyển cho {product_name} phải > 0.")
        # Người dùng bị giới hạn kho thành phẩm bắt buộc phải chọn vị trí nguồn tường minh —
        # bỏ trống sẽ khiến FIFO tự do trên toàn công ty, xuyên qua kho ngoài phạm vi.
        if restricted and not line.get("location_id"):
            raise DomainError(f"{product_name}: vui lòng chọn vị trí kho nguồn (tài khoản bị giới hạn kho thành phẩm).")
        if line.get("location_id"):
            _assert_loc_scope(db, user, line["location_id"])
        fp = db.execute(select(FinishedProduct).where(FinishedProduct.code == product_name)).scalar_one_or_none()
        divisor = _pack_divisor(fp, unit_type, divide_codes)
        # location_id: giữ FIFO trong đúng vị trí kho NGUỒN người dùng chọn ở picker — nếu
        # không truyền (request cũ) thì giữ hành vi cũ, FIFO tự do trên toàn công ty.
        line_location_id = line.get("location_id") or _LOC_UNSET
        candidates, got = _consume_lot_rows(
            db, product_name=product_name, unit_type=unit_type, status="stored",
            quantity_needed=qty * divisor, lot_code=lot_code, location_id=line_location_id,
            exclude_ids=picked_so_far, block_pending_manual=True)
        if got + 1e-9 < qty * divisor:
            raise DomainError(f"{product_name} {lot_code or ''}: chỉ còn {got / divisor:g} đơn vị "
                              f"tồn kho, không đủ {qty} yêu cầu.")
        units.extend(candidates)
        picked_so_far.update(u.unit_id for u in candidates)

    picked_ids = picked_so_far
    fifo_ok = True
    for u in units:
        if not u.product_name:
            continue
        older = db.execute(select(FinishedGoodsUnit).where(
            FinishedGoodsUnit.product_name == u.product_name, FinishedGoodsUnit.status == "stored",
            FinishedGoodsUnit.unit_id != u.unit_id, FinishedGoodsUnit.created_at < u.created_at)).scalars().all()
        if any(o.unit_id not in picked_ids for o in older):
            fifo_ok = False
            break

    # Vị trí xuất phát — tự suy ra từ location_id của các đơn vị được chọn TRƯỚC khi chuyển
    # (giống Shipment.from_location), CHƯA đổi gì ở bước này.
    loc_ids = {u.location_id for u in units if u.location_id}
    locs = db.execute(select(WmsLocation).where(WmsLocation.loc_id.in_(loc_ids))).scalars().all() if loc_ids else []
    from_location = ", ".join(sorted({f"{l.code} - {l.name}" if l.name else l.code for l in locs})) or None

    # Kiểm sức chứa đích — chỉ tính các đơn vị THỰC SỰ đổi vị trí (loại trừ đơn vị đã sẵn ở
    # đích nếu người dùng lỡ chọn trùng — mirror transfer_units/relocate_batch).
    fp_cache: dict = {}

    def _divisor_of(u):
        if u.finished_product_id not in fp_cache:
            fp_cache[u.finished_product_id] = db.get(FinishedProduct, u.finished_product_id) if u.finished_product_id else None
        return _pack_divisor(fp_cache[u.finished_product_id], u.unit_type, divide_codes)

    moving_in = [u for u in units if u.location_id != to_location_id]
    if moving_in:
        used_at_dest = _location_used_count(db, to_location_id)
        moving_in_count = sum(u.quantity / _divisor_of(u) for u in moving_in)
        if used_at_dest + moving_in_count > to_loc.capacity:
            raise DomainError(f"Vị trí {to_loc.code} không đủ sức chứa (sức chứa {to_loc.capacity}, "
                              f"hiện có {used_at_dest:g}, cần thêm {moving_in_count:g}).")

    header = header or {}
    transfer = WmsTransfer(transfer_id=new_id(), transfer_code=_next_transfer_code(db, utcnow().year),
                           to_location_id=to_location_id, created_by=user.username, created_at=utcnow(),
                           fifo_ok=fifo_ok, note=header.get("note"), driver_name=header.get("driver_name"),
                           vehicle_plate=header.get("vehicle_plate"),
                           vehicle_id=header.get("vehicle_id") if header.get("vehicle_id") and
                                     db.get(Vehicle, header.get("vehicle_id")) else None,
                           from_location=from_location)
    db.add(transfer)
    db.flush()

    out_lines = []
    for u in units:
        db.add(WmsTransferLine(line_id=new_id(), transfer_id=transfer.transfer_id, unit_id=u.unit_id,
                               from_location_id=u.location_id))
        u.location_id = to_location_id
        u.transfer_id = transfer.transfer_id
        out_lines.append({"unit_code": u.unit_code, "product": u.product_name, "lot_code": u.lot_code})

    record_audit(db, entity_type="wms_transfer", entity_id=transfer.transfer_id, action="create", actor=user,
                after={"transfer_code": transfer.transfer_code, "to_location": to_loc.code,
                       "units": out_lines, "fifo_ok": fifo_ok})
    db.commit()
    return {"transfer_id": transfer.transfer_id, "transfer_code": transfer.transfer_code,
            "to_location_code": to_loc.code, "fifo_ok": fifo_ok, "units": out_lines}


def list_transfers(db: Session, limit: int = 200, offset: int = 0) -> list:
    """Mirror list_shipments — có phân trang, nạp 1 LẦN toàn bộ FinishedGoodsUnit của các phiếu
    trong trang hiện tại rồi nhóm theo transfer_id trong Python (không N+1)."""
    limit = max(1, min(limit or 200, 2000))
    offset = max(0, offset or 0)
    transfers = db.execute(select(WmsTransfer).order_by(WmsTransfer.created_at.desc())
                           .limit(limit).offset(offset)).scalars().all()
    loc_by_id = {l.loc_id: l for l in db.execute(select(WmsLocation)).scalars().all()}
    vehicle_by_id = {v.vehicle_id: v for v in db.execute(select(Vehicle)).scalars().all()}
    fp_cache: dict = {}
    divide_codes = _divide_by_pack_codes(db)

    def _divisor_of(u):
        if u.finished_product_id not in fp_cache:
            fp_cache[u.finished_product_id] = db.get(FinishedProduct, u.finished_product_id) if u.finished_product_id else None
        return _pack_divisor(fp_cache[u.finished_product_id], u.unit_type, divide_codes)

    transfer_ids = [t.transfer_id for t in transfers]
    units_by_transfer: dict[str, list] = {}
    if transfer_ids:
        for u in db.execute(select(FinishedGoodsUnit).where(
                FinishedGoodsUnit.transfer_id.in_(transfer_ids))).scalars().all():
            units_by_transfer.setdefault(u.transfer_id, []).append(u)

    out = []
    for t in transfers:
        units = units_by_transfer.get(t.transfer_id, [])
        grouped: dict[tuple, dict] = {}
        for u in units:
            key = (u.product_name, u.lot_code, u.unit_type)
            g = grouped.setdefault(key, {"product": u.product_name, "lot_code": u.lot_code,
                                         "unit_type": u.unit_type, "count": 0.0, "quantity": 0.0})
            g["count"] += u.quantity / _divisor_of(u)
            g["quantity"] += u.quantity
        to_loc = loc_by_id.get(t.to_location_id)
        vehicle = vehicle_by_id.get(t.vehicle_id) if t.vehicle_id else None
        unit_count = sum(g["count"] for g in grouped.values())
        out.append({"transfer_id": t.transfer_id, "transfer_code": t.transfer_code,
                    "to_location_code": to_loc.code if to_loc else None,
                    "to_location_name": to_loc.name if to_loc else None,
                    "created_by": t.created_by, "created_at": t.created_at, "fifo_ok": t.fifo_ok,
                    "note": t.note, "driver_name": t.driver_name, "vehicle_plate": t.vehicle_plate,
                    "vehicle_code": vehicle.vehicle_code if vehicle else None,
                    "km": t.km, "fuel_liters": t.fuel_liters, "from_location": t.from_location,
                    "confirmed_by": t.confirmed_by, "confirmed_at": t.confirmed_at,
                    "unit_count": unit_count, "lines": list(grouped.values())})
    return out


def confirm_transfer(db: Session, transfer_id: str, user: User) -> dict:
    """Trưởng bộ phận kho xác nhận phiếu điều chuyển — mirror confirm_shipment, dùng LẠI quyền
    wms.confirm_shipment (không tách quyền riêng vì cùng người duyệt/cùng ý nghĩa "chốt phiếu
    kho"). Chỉ khoá lại, KHÔNG đổi số liệu tồn kho (đã đổi ngay lúc create_transfer)."""
    require_perm(user, "wms.confirm_shipment")
    transfer = db.get(WmsTransfer, transfer_id)
    if not transfer:
        raise NotFoundError("Phiếu điều chuyển không tồn tại.")
    if transfer.confirmed_by:
        raise DomainError("Phiếu này đã được xác nhận trước đó.")
    transfer.confirmed_by = user.username
    transfer.confirmed_at = utcnow()
    record_audit(db, entity_type="wms_transfer", entity_id=transfer.transfer_id, action="confirm", actor=user)
    db.commit()
    return {"transfer_id": transfer.transfer_id, "confirmed_by": transfer.confirmed_by,
            "confirmed_at": transfer.confirmed_at}


def update_transfer_trip(db: Session, transfer_id: str, km: float | None, fuel_liters: float | None,
                         user: User) -> dict:
    """Điền km/lít xăng của 1 chuyến điều chuyển — mirror update_shipment_trip, chỉ cho phép SAU
    KHI phiếu đã Duyệt. Cho sửa lại nhiều lần (không khoá)."""
    require_perm(user, "warehouse.issue")
    transfer = db.get(WmsTransfer, transfer_id)
    if not transfer:
        raise NotFoundError("Phiếu điều chuyển không tồn tại.")
    if not transfer.confirmed_by:
        raise DomainError("Chỉ được điền km/lít xăng sau khi phiếu đã được duyệt.")
    transfer.km = km
    transfer.fuel_liters = fuel_liters
    record_audit(db, entity_type="wms_transfer", entity_id=transfer.transfer_id, action="update_trip", actor=user,
                after={"km": km, "fuel_liters": fuel_liters})
    db.commit()
    return {"transfer_id": transfer.transfer_id, "km": transfer.km, "fuel_liters": transfer.fuel_liters}


_TRANSFER_EDITABLE_FIELDS = ("note", "driver_name", "vehicle_plate")


def update_transfer(db: Session, transfer_id: str, payload: dict, user: User) -> dict:
    """Sửa thông tin đầu phiếu điều chuyển (ghi chú/lái xe/biển số) — mirror update_shipment,
    KHÔNG cho sửa vị trí đích (đổi vị trí đích sau khi đã chọn/chuyển thật là vô nghĩa, phải Hoàn
    tác + lập phiếu mới). Chặn sửa sau khi đã "Duyệt"."""
    require_perm(user, "warehouse.issue")
    transfer = db.get(WmsTransfer, transfer_id)
    if not transfer:
        raise NotFoundError("Phiếu điều chuyển không tồn tại.")
    if transfer.confirmed_by:
        raise DomainError("Phiếu đã được duyệt — không thể sửa nữa.")
    before = {f: getattr(transfer, f) for f in _TRANSFER_EDITABLE_FIELDS}
    for field in _TRANSFER_EDITABLE_FIELDS:
        if field in payload:
            setattr(transfer, field, payload[field])
    record_audit(db, entity_type="wms_transfer", entity_id=transfer.transfer_id, action="update",
                actor=user, before=before, after={f: getattr(transfer, f) for f in _TRANSFER_EDITABLE_FIELDS})
    db.commit()
    return {"transfer_id": transfer.transfer_id}


def undo_transfer(db: Session, transfer_id: str, user: User) -> dict:
    """Hoàn tác 1 phiếu điều chuyển — trả các vỉ/keg/lon về ĐÚNG vị trí TRƯỚC khi chuyển (ghi ở
    WmsTransferLine.from_location_id lúc tạo phiếu) — khác undo_shipment (Xuất kho luôn xóa
    location_id nên không có vị trí gốc để trả). CHỈ trả lại đơn vị mà transfer_id hiện tại vẫn
    còn khớp ĐÚNG phiếu này (FinishedGoodsUnit.transfer_id == transfer_id) — đơn vị đã bị 1 thao
    tác khác (điều chuyển/xuất kho khác) "chạm" vào sau đó thì bỏ qua, không trả về (không còn
    đúng nguyên trạng để hoàn tác an toàn); trả kèm "skipped" để người dùng biết có phần không
    hoàn tác được. Không xóa WmsTransferLine (giữ làm lịch sử) — gọi lại lần 2 tự nhiên báo
    "không còn gì để hoàn tác" vì mọi đơn vị đã có transfer_id khác/None."""
    require_perm(user, "warehouse.issue")
    transfer = db.get(WmsTransfer, transfer_id)
    if not transfer:
        raise NotFoundError("Phiếu điều chuyển không tồn tại.")
    if transfer.confirmed_by:
        require_role(user, Role.ADMIN)
    lines = db.execute(select(WmsTransferLine).where(WmsTransferLine.transfer_id == transfer_id)).scalars().all()
    if not lines:
        raise DomainError("Phiếu này không có dòng nào để hoàn tác.")

    fp_cache: dict = {}
    divide_codes = _divide_by_pack_codes(db)

    def _divisor_of(u):
        if u.finished_product_id not in fp_cache:
            fp_cache[u.finished_product_id] = db.get(FinishedProduct, u.finished_product_id) if u.finished_product_id else None
        return _pack_divisor(fp_cache[u.finished_product_id], u.unit_type, divide_codes)

    restored_count = 0.0
    skipped = 0
    for line in lines:
        u = db.get(FinishedGoodsUnit, line.unit_id)
        if not u or u.transfer_id != transfer_id:
            skipped += 1
            continue
        u.location_id = line.from_location_id
        u.transfer_id = None
        restored_count += u.quantity / _divisor_of(u)
    if restored_count == 0:
        raise DomainError("Phiếu này không còn đơn vị nào để hoàn tác (có thể đã hoàn tác trước đó, "
                          "hoặc toàn bộ đơn vị đã bị 1 thao tác khác thay đổi sau đó).")
    record_audit(db, entity_type="wms_transfer", entity_id=transfer_id, action="undo", actor=user,
                before={"unit_count": restored_count}, after={"restored": restored_count, "skipped": skipped})
    db.commit()
    return {"transfer_id": transfer_id, "restored": restored_count, "skipped": skipped}


# ---- Báo cáo lượt xe & tải trọng / tổng hợp bia gửi / định mức nhiên liệu ----

def vehicle_trip_report(db: Session, date_from: datetime, date_to: datetime) -> list[dict]:
    """Số lượt mỗi xe đã chở đi (1 phiếu xuất kho = 1 lượt) + tổng tải trọng (kg, tính qua
    _line_weight_kg) trong [date_from, date_to) theo Shipment.created_at. So sánh với
    Vehicle.capacity_kg để đếm số lượt vượt tải (chỉ tính khi xe đã khai báo capacity_kg).
    Chỉ tính các phiếu đã gắn vehicle_id (chọn xe từ Danh mục lái xe lúc tạo phiếu) — phiếu cũ/
    gõ tay biển số không qua danh mục sẽ không xuất hiện ở đây."""
    divide_codes = _divide_by_pack_codes(db)
    ships = db.execute(select(Shipment).where(
        Shipment.vehicle_id.isnot(None), Shipment.created_at >= date_from,
        Shipment.created_at < date_to)).scalars().all()
    shipment_ids = [s.shipment_id for s in ships]
    units_by_shipment: dict[str, list] = {}
    if shipment_ids:
        for u in db.execute(select(FinishedGoodsUnit).where(
                FinishedGoodsUnit.shipment_id.in_(shipment_ids))).scalars().all():
            units_by_shipment.setdefault(u.shipment_id, []).append(u)
    fp_cache: dict = {}

    def _fp_of(finished_product_id):
        if finished_product_id not in fp_cache:
            fp_cache[finished_product_id] = db.get(FinishedProduct, finished_product_id) if finished_product_id else None
        return fp_cache[finished_product_id]

    by_vehicle: dict[str, dict] = {}
    for s in ships:
        trip_kg = sum(_line_weight_kg(_fp_of(u.finished_product_id), u.unit_type, u.quantity, divide_codes)
                      for u in units_by_shipment.get(s.shipment_id, []))
        acc = by_vehicle.setdefault(s.vehicle_id, {"trip_count": 0, "total_kg": 0.0, "over_capacity_trip_count": 0})
        acc["trip_count"] += 1
        acc["total_kg"] += trip_kg
        vehicle = db.get(Vehicle, s.vehicle_id)
        if vehicle and vehicle.capacity_kg and trip_kg > vehicle.capacity_kg:
            acc["over_capacity_trip_count"] += 1

    out = []
    for vehicle_id, acc in by_vehicle.items():
        vehicle = db.get(Vehicle, vehicle_id)
        out.append({"vehicle_id": vehicle_id, "vehicle_code": vehicle.vehicle_code if vehicle else None,
                    "plate": vehicle.plate if vehicle else None,
                    "driver_name": vehicle.driver_name if vehicle else None,
                    "capacity_kg": vehicle.capacity_kg if vehicle else None,
                    "trip_count": acc["trip_count"], "total_kg": round(acc["total_kg"], 2),
                    "avg_kg_per_trip": round(acc["total_kg"] / acc["trip_count"], 2),
                    "avg_tons_per_trip": round(acc["total_kg"] / acc["trip_count"] / 1000, 3),
                    "over_capacity_trip_count": acc["over_capacity_trip_count"]})
    return sorted(out, key=lambda r: -r["trip_count"])


def consigned_summary_report(db: Session, date_from: datetime, date_to: datetime) -> list[dict]:
    """Tổng hợp số lượng bia gửi đã nhận về (ConsignedEntry direction="in") trong khoảng
    [date_from, date_to) theo declared_at, gộp theo (sản phẩm, loại đơn vị)."""
    rows = db.execute(select(ConsignedEntry.product_name, ConsignedEntry.unit_type,
                             func.sum(ConsignedEntry.quantity), func.count())
                      .where(ConsignedEntry.direction == "in", ConsignedEntry.reversed == false(),
                             ConsignedEntry.declared_at.isnot(None),
                             ConsignedEntry.declared_at >= date_from, ConsignedEntry.declared_at < date_to)
                      .group_by(ConsignedEntry.product_name, ConsignedEntry.unit_type)).all()
    return [{"product_name": product_name, "unit_type": unit_type,
            "total_quantity": total_quantity or 0, "entry_count": entry_count}
            for product_name, unit_type, total_quantity, entry_count in rows]


def fuel_efficiency_report(db: Session, date_from: datetime, date_to: datetime) -> list[dict]:
    """Định mức nhiên liệu mỗi chuyến xuất đã điền đủ km + lít xăng (update_shipment_trip),
    trong [date_from, date_to) theo Shipment.confirmed_at (chỉ có km/fuel sau khi duyệt).
    lít bia = tổng SL đơn vị nhỏ x lít/đơn vị (_liters_per_unit) của mọi FinishedGoodsUnit
    thuộc phiếu đó. Bỏ qua chia-0 (liters_beer/fuel_liters = 0) — trả None cho tỉ lệ đó."""
    ships = db.execute(select(Shipment).where(
        Shipment.vehicle_id.isnot(None), Shipment.km.isnot(None), Shipment.fuel_liters.isnot(None),
        Shipment.confirmed_at.isnot(None), Shipment.confirmed_at >= date_from,
        Shipment.confirmed_at < date_to)).scalars().all()
    shipment_ids = [s.shipment_id for s in ships]
    units_by_shipment: dict[str, list] = {}
    if shipment_ids:
        for u in db.execute(select(FinishedGoodsUnit).where(
                FinishedGoodsUnit.shipment_id.in_(shipment_ids))).scalars().all():
            units_by_shipment.setdefault(u.shipment_id, []).append(u)
    fp_cache: dict = {}

    def _fp_of(finished_product_id):
        if finished_product_id not in fp_cache:
            fp_cache[finished_product_id] = db.get(FinishedProduct, finished_product_id) if finished_product_id else None
        return fp_cache[finished_product_id]

    out = []
    for s in ships:
        liters_beer = sum((u.quantity or 0) * (_liters_per_unit(_fp_of(u.finished_product_id)) or 0)
                          for u in units_by_shipment.get(s.shipment_id, []))
        vehicle = db.get(Vehicle, s.vehicle_id)
        out.append({"shipment_code": s.shipment_code,
                    "vehicle_code": vehicle.vehicle_code if vehicle else None,
                    "plate": vehicle.plate if vehicle else None,
                    "driver_name": vehicle.driver_name if vehicle else None,
                    "km": s.km, "fuel_liters": s.fuel_liters, "liters_beer": round(liters_beer, 2),
                    "l_fuel_per_l_beer": round(s.fuel_liters / liters_beer, 4) if liters_beer else None,
                    "km_per_l_fuel": round(s.km / s.fuel_liters, 2) if s.fuel_liters else None})
    return sorted(out, key=lambda r: r["shipment_code"])
