"""Xóa danh mục gốc (Loại bia/Dịch bia/Vật tư/Sản phẩm thành phẩm/Dây chuyền-Tank) — chặn nếu
mã đó đã được tham chiếu ở bất kỳ đâu (kể cả lịch sử, không chỉ bản ghi đang active), vì đây là
dữ liệu gốc ảnh hưởng truy xuất nguồn gốc một khi đã có bản ghi trỏ tới (mirror
qc_catalog.py::delete_group và wms.py::delete_ship_to)."""

from sqlalchemy import func, select, true
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..errors import DomainError, NotFoundError
from ..models.brewing import (BottleRecord, BrewOrder, BrewOrderMaterialLine, BrewRecord, FermentRecord,
    FilterOrder, FilterOrderMaterialLine, FilterOrderTank, FilterRecord)
from ..models.batches import BatchExecution
from ..models.lines import ProductionLine
from ..models.master import BeerType, FinishedProduct, Material, MaterialGroup, Product
from ..models.materials import MaterialLot, Supplier
from ..models.materials_ext import MaterialQcGroup
from ..models.metrics import OEERecord
from ..models.oee_ext import DowntimeEvent
from ..models.orders import ProductionOrder
from ..models.quality_ext import StageQcGroup
from ..models.recipes import Recipe
from ..models.scheduling import ScheduleSlot
from ..models.warehouse import MaterialRequestLine, StockMovement
from ..models.wms import FinishedGoodsUnit
from ..models.workorder import WorkOrder
from ..security import User, require_perm


def _used_by(db: Session, checks: list) -> list:
    """Chạy từng (nhãn, câu lệnh đếm) — trả về danh sách "N nhãn" cho những nhãn có count>0."""
    parts = []
    for label, stmt in checks:
        n = db.execute(stmt).scalar() or 0
        if n:
            parts.append(f"{n} {label}")
    return parts


def _block_if_used(parts: list, kind: str, code: str) -> None:
    if parts:
        raise DomainError(f"Không thể xóa {kind} '{code}' — đang được dùng bởi "
                          f"{', '.join(parts)}. Hãy xóa/gỡ các mục đó trước.")


def delete_beer_type(db: Session, beer_type_id: str, user: User) -> None:
    require_perm(user, "master.manage")
    bt = db.get(BeerType, beer_type_id)
    if not bt:
        raise NotFoundError("Loại bia không tồn tại.")
    checks = [
        ("dịch bia", select(func.count(Product.product_id)).where(Product.beer_type_id == beer_type_id)),
        ("lệnh lọc", select(func.count(FilterOrder.filter_order_id)).where(FilterOrder.beer_type_id == beer_type_id)),
        ("mẻ lọc", select(func.count(FilterRecord.filter_id)).where(FilterRecord.beer_type_id == beer_type_id)),
        ("mẻ chiết", select(func.count(BottleRecord.bottle_id)).where(BottleRecord.beer_type_id == beer_type_id)),
        ("nhóm chỉ tiêu công đoạn", select(func.count(StageQcGroup.link_id)).where(
            StageQcGroup.beer_type_id == beer_type_id, StageQcGroup.active == true())),
    ]
    _block_if_used(_used_by(db, checks), "Loại bia", bt.code)
    record_audit(db, entity_type="beer_type", entity_id=bt.beer_type_id, action="delete",
                 actor=user, before={"code": bt.code, "name": bt.name})
    db.delete(bt)
    db.commit()


def delete_material_group(db: Session, group_id: str, user: User) -> None:
    require_perm(user, "master.manage")
    g = db.get(MaterialGroup, group_id)
    if not g:
        raise NotFoundError("Nhóm vật tư không tồn tại.")
    checks = [
        ("vật tư", select(func.count(Material.material_id)).where(Material.category == g.code)),
    ]
    _block_if_used(_used_by(db, checks), "Nhóm vật tư", g.code)
    record_audit(db, entity_type="material_group", entity_id=g.group_id, action="delete",
                 actor=user, before={"code": g.code, "name": g.name})
    db.delete(g)
    db.commit()


def delete_supplier(db: Session, supplier_id: str, user: User) -> None:
    require_perm(user, "master.manage")
    sup = db.get(Supplier, supplier_id)
    if not sup:
        raise NotFoundError("Nhà cung cấp không tồn tại.")
    checks = [
        ("lô NVL", select(func.count(MaterialLot.lot_id)).where(MaterialLot.supplier_id == supplier_id)),
    ]
    _block_if_used(_used_by(db, checks), "Nhà cung cấp", sup.code)
    record_audit(db, entity_type="supplier", entity_id=sup.supplier_id, action="delete",
                 actor=user, before={"code": sup.code, "name": sup.name})
    db.delete(sup)
    db.commit()


def delete_product(db: Session, product_id: str, user: User) -> None:
    require_perm(user, "master.manage")
    p = db.get(Product, product_id)
    if not p:
        raise NotFoundError("Dịch bia không tồn tại.")
    checks = [
        ("lệnh nấu", select(func.count(BrewOrder.brew_order_id)).where(BrewOrder.product_id == product_id)),
        ("mẻ nấu", select(func.count(BrewRecord.brew_id)).where(BrewRecord.product_id == product_id)),
        ("lô lên men", select(func.count(FermentRecord.ferment_id)).where(FermentRecord.product_id == product_id)),
        ("mẻ lọc", select(func.count(FilterRecord.filter_id)).where(FilterRecord.product_id == product_id)),
        ("mẻ chiết", select(func.count(BottleRecord.bottle_id)).where(BottleRecord.product_id == product_id)),
        ("lô hàng tồn kho", select(func.count(MaterialLot.lot_id)).where(MaterialLot.product_id == product_id)),
        ("sản phẩm thành phẩm", select(func.count(FinishedProduct.finished_product_id)).where(
            FinishedProduct.product_id == product_id)),
        ("nhóm chỉ tiêu công đoạn", select(func.count(StageQcGroup.link_id)).where(
            StageQcGroup.product_id == product_id, StageQcGroup.active == true())),
        ("lệnh sản xuất (ERP cũ)", select(func.count(ProductionOrder.order_id)).where(
            ProductionOrder.product_id == product_id)),
        ("work order", select(func.count(WorkOrder.wo_id)).where(WorkOrder.product_id == product_id)),
        ("công thức", select(func.count(Recipe.recipe_id)).where(Recipe.product_id == product_id)),
        ("mẻ sản xuất (module cũ)", select(func.count(BatchExecution.batch_id)).where(
            BatchExecution.product_id == product_id)),
    ]
    _block_if_used(_used_by(db, checks), "Dịch bia", p.code)
    record_audit(db, entity_type="product", entity_id=p.product_id, action="delete",
                 actor=user, before={"code": p.code, "name": p.name})
    db.delete(p)
    db.commit()


def delete_material(db: Session, material_id: str, user: User) -> None:
    require_perm(user, "master.manage")
    m = db.get(Material, material_id)
    if not m:
        raise NotFoundError("Vật tư không tồn tại.")
    checks = [
        ("dòng vật tư lệnh nấu", select(func.count(BrewOrderMaterialLine.line_id)).where(
            BrewOrderMaterialLine.material_id == material_id)),
        ("dòng vật tư lệnh lọc", select(func.count(FilterOrderMaterialLine.line_id)).where(
            FilterOrderMaterialLine.material_id == material_id)),
        ("lô hàng tồn kho", select(func.count(MaterialLot.lot_id)).where(MaterialLot.material_id == material_id)),
        ("gán nhóm chỉ tiêu QC", select(func.count(MaterialQcGroup.link_id)).where(
            MaterialQcGroup.material_id == material_id, MaterialQcGroup.active == true())),
        ("phiếu nhập/xuất kho", select(func.count(StockMovement.movement_id)).where(
            StockMovement.material_id == material_id)),
        ("đề nghị nhận kho", select(func.count(MaterialRequestLine.line_id)).where(
            MaterialRequestLine.material_id == material_id)),
    ]
    _block_if_used(_used_by(db, checks), "Vật tư", m.code)
    record_audit(db, entity_type="material", entity_id=m.material_id, action="delete",
                 actor=user, before={"code": m.code, "name": m.name})
    db.delete(m)
    db.commit()


def delete_finished_product(db: Session, finished_product_id: str, user: User) -> None:
    require_perm(user, "master.manage")
    fp = db.get(FinishedProduct, finished_product_id)
    if not fp:
        raise NotFoundError("Sản phẩm không tồn tại.")
    checks = [
        ("mẻ chiết", select(func.count(BottleRecord.bottle_id)).where(
            BottleRecord.finished_product_id == finished_product_id)),
        ("nhóm chỉ tiêu công đoạn", select(func.count(StageQcGroup.link_id)).where(
            StageQcGroup.finished_product_id == finished_product_id, StageQcGroup.active == true())),
        ("vỉ/keg tồn kho thành phẩm", select(func.count(FinishedGoodsUnit.unit_id)).where(
            FinishedGoodsUnit.finished_product_id == finished_product_id)),
    ]
    _block_if_used(_used_by(db, checks), "Sản phẩm", fp.code)
    record_audit(db, entity_type="finished_product", entity_id=fp.finished_product_id, action="delete",
                 actor=user, before={"code": fp.code, "name": fp.name})
    db.delete(fp)
    db.commit()


def delete_production_line(db: Session, line_id: str, user: User) -> None:
    """Mã dây chuyền/tank là text tự do (không phải FK thật) — chặn theo so khớp `code` trên
    mọi bảng có thể lưu mã đó, bất kể `kind` (line/tank/tank_bbt) để không sót cột."""
    require_perm(user, "master.manage")
    line = db.get(ProductionLine, line_id)
    if not line:
        raise NotFoundError("Dây chuyền/tank không tồn tại.")
    code = line.code
    checks = [
        ("mẻ chiết (dây chuyền)", select(func.count(BottleRecord.bottle_id)).where(BottleRecord.line == code)),
        ("work order (dây chuyền)", select(func.count(WorkOrder.wo_id)).where(WorkOrder.line == code)),
        ("bản ghi OEE", select(func.count(OEERecord.oee_id)).where(OEERecord.line == code)),
        ("sự kiện dừng máy", select(func.count(DowntimeEvent.event_id)).where(DowntimeEvent.line == code)),
        ("lịch sản xuất", select(func.count(ScheduleSlot.slot_id)).where(ScheduleSlot.resource == code)),
        ("lệnh nấu (tank LM)", select(func.count(BrewOrder.brew_order_id)).where(BrewOrder.tank_lm == code)),
        ("lô lên men (tank LM)", select(func.count(FermentRecord.ferment_id)).where(FermentRecord.tank_lm == code)),
        ("mẻ lọc (lọc từ)", select(func.count(FilterRecord.filter_id)).where(FilterRecord.from_cct == code)),
        ("mẻ lọc (đổ vào BBT)", select(func.count(FilterRecord.filter_id)).where(FilterRecord.to_bbt == code)),
        ("mẻ chiết (từ BBT)", select(func.count(BottleRecord.bottle_id)).where(BottleRecord.from_bbt == code)),
        ("tank BBT nguồn lọc lại", select(func.count(FilterOrderTank.line_id)).where(
            FilterOrderTank.source_bbt_code == code)),
    ]
    _block_if_used(_used_by(db, checks), "Dây chuyền/tank", code)
    record_audit(db, entity_type="line", entity_id=line.line_id, action="delete",
                 actor=user, before={"code": code, "name": line.name})
    db.delete(line)
    db.commit()
