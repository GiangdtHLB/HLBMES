"""BC định mức NVL — đối chiếu định mức (định mức đã chốt lúc lập lệnh) ↔ thực tế tiêu thụ
(*MaterialUsage), tách riêng theo đúng 3 module thật đang vận hành: Nấu (BrewOrder), Lọc
(FilterOrder), Chiết (BottleRecord). Thay cho báo cáo cũ dựa trên BatchExecution/services/bom.py
— module "Mẻ sản xuất" đó đã ngừng dùng (xem frontend nav-unused "batches"), không còn phản ánh
đúng luồng SX thật (Lệnh nấu/Lệnh lọc/Chiết + Nhóm vật tư thay thế).

Chiết KHÔNG có định mức (chưa có BOM đóng gói theo SKU, xem BottleMaterialUsage docstring) —
chỉ hiện thực tế đã dùng, không so sánh/không trạng thái đạt-thiếu-vượt."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..common import utcnow
from ..models.brewing import (
    BottleMaterialUsage,
    BottleRecord,
    BrewOrder,
    BrewOrderMaterialLine,
    BrewRecord,
    FilterMaterialUsage,
    FilterOrder,
    FilterOrderMaterialLine,
    FilterRecord,
)
from ..models.materials import MaterialLot
from . import brew_order as brew_order_svc
from . import filter_order as filter_order_svc


def _classify(planned: float, actual: float, tol_pct: float) -> tuple:
    """Mirror services/bom.py::_classify — giữ đúng quy ước trạng thái cũ (đạt/thiếu/vượt/
    chưa dùng) để người dùng không phải học lại cách đọc báo cáo, chỉ đổi tol từ per-dòng-BOM
    (đã bỏ ở Formula) sang 1 ngưỡng chung truyền vào (tol_pct)."""
    diff = round(actual - planned, 3)
    pct = round((diff / planned * 100), 1) if planned else 0.0
    if planned <= 0:
        status = "vuot" if actual > 0 else "chua_dung"
    elif actual == 0:
        status = "chua_dung"
    elif abs(pct) <= tol_pct:
        status = "dat"
    elif diff > 0:
        status = "vuot"
    else:
        status = "thieu"
    return diff, pct, status


def _filter_actual_usage_by_material(db: Session, filter_order_ids: list) -> dict:
    """Tổng NVL lọc thực tế đã dùng (FilterMaterialUsage), gộp theo material_id thật — mirror
    services/brew_order.py::_actual_usage_by_material (batch_id -> filter_id)."""
    if not filter_order_ids:
        return {}
    filter_ids = db.execute(select(FilterRecord.filter_id).where(
        FilterRecord.filter_order_id.in_(filter_order_ids))).scalars().all()
    if not filter_ids:
        return {}
    usages = db.execute(select(FilterMaterialUsage).where(
        FilterMaterialUsage.filter_id.in_(filter_ids))).scalars().all()
    lot_ids = [u.lot_id for u in usages if u.lot_id]
    material_by_lot = dict(db.execute(select(MaterialLot.lot_id, MaterialLot.material_id)
                                      .where(MaterialLot.lot_id.in_(lot_ids))).all()) if lot_ids else {}
    out: dict[str, float] = {}
    for u in usages:
        mid = material_by_lot.get(u.lot_id) if u.lot_id else None
        if not mid:
            continue
        out[mid] = out.get(mid, 0.0) + u.quantity
    return out


def _aggregate_norm(db: Session, orders: list, lines_by_order: dict, actual_by_order: dict,
                    materials_by_id: dict, resolve_members, convert_member_qty, tol_pct: float) -> tuple:
    """Gộp các dòng định mức của nhiều lệnh (Nấu hoặc Lọc — cấu trúc dòng giống nhau) thành 2
    bảng: theo vật tư (gộp key=material_id hoặc "group:<code>") và theo lệnh (planned/actual
    tổng của riêng lệnh đó). `orders` là list (order_id, order_code)."""
    agg: dict = {}
    order_rows = []
    for order_id, order_code in orders:
        lines = lines_by_order.get(order_id, [])
        actual_by_material = actual_by_order.get(order_id, {})
        o_planned = o_actual = 0.0
        for line in lines:
            if line.is_header:
                continue
            group_code = line.material_group_code
            key = f"group:{group_code}" if group_code else (line.material_id or line.material_name)
            planned = line.qty_total or 0.0
            if group_code:
                member_ids = resolve_members(db, group_code)
                actual = sum(convert_member_qty(materials_by_id.get(mid), line.uom, actual_by_material.get(mid, 0.0) or 0.0)
                            for mid in member_ids)
            else:
                actual = actual_by_material.get(line.material_id, 0.0) or 0.0
            a = agg.setdefault(key, {"material_name": line.material_name, "uom": line.uom,
                                     "planned": 0.0, "actual": 0.0, "order_ids": set()})
            a["planned"] += planned
            a["actual"] += actual
            a["order_ids"].add(order_id)
            o_planned += planned
            o_actual += actual
        diff, pct, status = _classify(round(o_planned, 3), round(o_actual, 3), tol_pct)
        order_rows.append({"order_code": order_code, "planned_total": round(o_planned, 3),
                           "actual_total": round(o_actual, 3), "diff": diff, "pct": pct, "status": status})

    materials = []
    for key, a in agg.items():
        planned = round(a["planned"], 3)
        actual = round(a["actual"], 3)
        diff, pct, status = _classify(planned, actual, tol_pct)
        materials.append({"key": key, "material_name": a["material_name"], "uom": a["uom"],
                          "orders": len(a["order_ids"]), "planned": planned, "actual": actual,
                          "diff": diff, "pct": pct, "status": status})
    materials.sort(key=lambda x: abs(x["pct"]), reverse=True)
    return materials, order_rows


def brew_norm_report(db: Session, days: int, tol_pct: float = 5.0) -> dict:
    """BC định mức NVL — Nấu: gộp định mức (BrewOrderMaterialLine, đã chốt lúc lập Lệnh nấu)
    ↔ thực tế (BrewMaterialUsage) qua mọi Lệnh nấu CÓ mã nấu (BrewRecord) trong kỳ. Dòng Nhóm
    vật tư thay thế cộng dồn thực tế qua mọi mã thành viên đã dùng thật, không chỉ đúng mã
    khai trong công thức (khác mẻ có thể dùng mã khác nhau trong cùng nhóm)."""
    since = utcnow() - timedelta(days=days)
    order_ids = db.execute(select(BrewRecord.brew_order_id).where(
        BrewRecord.brew_date >= since, BrewRecord.brew_order_id.is_not(None))).scalars().all()
    order_ids = sorted(set(order_ids))
    if not order_ids:
        return {"order_count": 0, "materials": [], "orders": []}
    orders = db.execute(select(BrewOrder).where(BrewOrder.brew_order_id.in_(order_ids))).scalars().all()
    order_tuples = [(o.brew_order_id, o.order_code) for o in orders]

    lines_by_order = {}
    for l in db.execute(select(BrewOrderMaterialLine).where(
            BrewOrderMaterialLine.brew_order_id.in_(order_ids))).scalars().all():
        lines_by_order.setdefault(l.brew_order_id, []).append(l)

    brew_ids_by_order = {}
    for brew_order_id, brew_id in db.execute(select(BrewRecord.brew_order_id, BrewRecord.brew_id)
                                             .where(BrewRecord.brew_order_id.in_(order_ids))).all():
        brew_ids_by_order.setdefault(brew_order_id, []).append(brew_id)
    materials_by_id = brew_order_svc._materials_by_id(db)

    actual_by_order = {}
    for order_id, brew_ids in brew_ids_by_order.items():
        actual_by_order[order_id] = brew_order_svc._actual_usage_by_material(db, brew_ids)

    materials, order_rows = _aggregate_norm(
        db, order_tuples, lines_by_order, actual_by_order, materials_by_id,
        brew_order_svc._resolve_group_members, brew_order_svc._convert_member_qty, tol_pct)
    return {"order_count": len(orders), "materials": materials, "orders": order_rows}


def filter_norm_report(db: Session, days: int, tol_pct: float = 5.0) -> dict:
    """BC định mức NVL — Lọc: mirror brew_norm_report, dùng FilterOrderMaterialLine/
    FilterMaterialUsage (VD bột trợ lọc/diatomite)."""
    since = utcnow() - timedelta(days=days)
    order_ids = db.execute(select(FilterRecord.filter_order_id).where(
        FilterRecord.filter_date >= since, FilterRecord.filter_order_id.is_not(None))).scalars().all()
    order_ids = sorted(set(order_ids))
    if not order_ids:
        return {"order_count": 0, "materials": [], "orders": []}
    orders = db.execute(select(FilterOrder).where(FilterOrder.filter_order_id.in_(order_ids))).scalars().all()
    order_tuples = [(o.filter_order_id, o.order_code) for o in orders]

    lines_by_order = {}
    for l in db.execute(select(FilterOrderMaterialLine).where(
            FilterOrderMaterialLine.filter_order_id.in_(order_ids))).scalars().all():
        lines_by_order.setdefault(l.filter_order_id, []).append(l)

    materials_by_id = brew_order_svc._materials_by_id(db)
    actual_by_order = {}
    for order_id in order_ids:
        actual_by_order[order_id] = _filter_actual_usage_by_material(db, [order_id])

    materials, order_rows = _aggregate_norm(
        db, order_tuples, lines_by_order, actual_by_order, materials_by_id,
        filter_order_svc._resolve_group_members, brew_order_svc._convert_member_qty, tol_pct)
    return {"order_count": len(orders), "materials": materials, "orders": order_rows}


def packaging_actual_report(db: Session, days: int) -> dict:
    """BC NVL Chiết — CHỈ thực tế đã dùng (CO2/hóa chất vệ sinh/nắp/lon...), KHÔNG có định
    mức để so sánh (chưa có BOM đóng gói theo SKU, xem models.brewing.BottleMaterialUsage)."""
    since = utcnow() - timedelta(days=days)
    bottle_ids = db.execute(select(BottleRecord.bottle_id).where(
        BottleRecord.bottle_date >= since)).scalars().all()
    if not bottle_ids:
        return {"record_count": 0, "materials": []}
    usages = db.execute(select(BottleMaterialUsage).where(
        BottleMaterialUsage.bottle_id.in_(bottle_ids))).scalars().all()
    lot_ids = [u.lot_id for u in usages if u.lot_id]
    material_by_lot = dict(db.execute(select(MaterialLot.lot_id, MaterialLot.material_id)
                                      .where(MaterialLot.lot_id.in_(lot_ids))).all()) if lot_ids else {}
    materials_by_id = brew_order_svc._materials_by_id(db)
    agg: dict = {}
    for u in usages:
        mid = material_by_lot.get(u.lot_id) if u.lot_id else None
        mat = materials_by_id.get(mid) if mid else None
        key = mid or u.material_name
        a = agg.setdefault(key, {"material_name": mat.name if mat else u.material_name,
                                 "uom": u.uom, "actual": 0.0})
        a["actual"] += u.quantity
    materials = [{"key": k, "material_name": a["material_name"], "uom": a["uom"],
                 "actual": round(a["actual"], 3)} for k, a in agg.items()]
    materials.sort(key=lambda x: x["material_name"] or "")
    return {"record_count": len(bottle_ids), "materials": materials}
