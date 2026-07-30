"""Master data: products, materials (danh mục).

Tạo/sửa danh mục yêu cầu quyền 'master.manage' và được ghi audit (SoR nội bộ;
thực tế đồng bộ từ ERP/PLM — tài liệu §5.2, §8.1)."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import new_id
from ..database import get_db
from ..errors import DomainError, NotFoundError, PermissionError_
from ..models.master import BeerType, FinishedProduct, Material, MaterialGroup, Product, UnitTypeCatalog
from ..models.materials import Supplier
from ..schemas import (BeerTypeIn, BeerTypeOut, FinishedProductIn, FinishedProductOut, MaterialGroupIn,
    MaterialGroupOut, MaterialIn, MaterialOut, MaterialQcGroupIn, OpsSettingIn, OpsSettingOut,
    ProductBrewSpecIn, ProductIn, ProductOut, SupplierIn, SupplierOut, UnitTypeCatalogIn, UnitTypeCatalogOut)
from ..security import User, get_current_user, require_perm
from ..services import braumat_import as braumat_svc
from ..services import master_data, ops_setting as ops_setting_svc
from ..services import qc_catalog

router = APIRouter(prefix="/api", tags=["master"],
                   dependencies=[Depends(get_current_user)])


# ---- Loại bia (thương hiệu — VD Sapphire, gộp nhiều Dịch bia khác độ oP) ----
@router.get("/beer-types", response_model=list[BeerTypeOut])
def list_beer_types(db: Session = Depends(get_db)):
    return db.execute(select(BeerType).order_by(BeerType.code)).scalars().all()


@router.post("/beer-types", response_model=BeerTypeOut, status_code=201)
def create_beer_type(payload: BeerTypeIn, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    require_perm(user, "master.manage")
    if db.execute(select(BeerType).where(BeerType.code == payload.code)).scalar_one_or_none():
        raise PermissionError_(f"Mã loại bia '{payload.code}' đã tồn tại.")
    bt = BeerType(beer_type_id=new_id(), **payload.model_dump())
    db.add(bt)
    record_audit(db, entity_type="beer_type", entity_id=bt.beer_type_id, action="create",
                 actor=user, after={"code": bt.code, "name": bt.name})
    db.commit()
    db.refresh(bt)
    return bt


@router.put("/beer-types/{beer_type_id}", response_model=BeerTypeOut)
def update_beer_type(beer_type_id: str, payload: BeerTypeIn, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    require_perm(user, "master.manage")
    bt = db.get(BeerType, beer_type_id)
    if not bt:
        raise NotFoundError("Loại bia không tồn tại.")
    before = {"code": bt.code, "name": bt.name, "note": bt.note}
    bt.code = payload.code
    bt.name = payload.name
    bt.note = payload.note
    record_audit(db, entity_type="beer_type", entity_id=bt.beer_type_id, action="update",
                 actor=user, before=before, after=payload.model_dump())
    db.commit()
    db.refresh(bt)
    return bt


@router.delete("/beer-types/{beer_type_id}", status_code=204)
def delete_beer_type(beer_type_id: str, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    master_data.delete_beer_type(db, beer_type_id, user)


# ---- Loại đơn vị tồn kho (WMS thành phẩm — Vỉ/Keg mặc định + tự khai báo thêm) ----
@router.get("/unit-types", response_model=list[UnitTypeCatalogOut])
def list_unit_types(db: Session = Depends(get_db)):
    return db.execute(select(UnitTypeCatalog).order_by(UnitTypeCatalog.code)).scalars().all()


@router.post("/unit-types", response_model=UnitTypeCatalogOut, status_code=201)
def create_unit_type(payload: UnitTypeCatalogIn, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    require_perm(user, "master.manage")
    if db.execute(select(UnitTypeCatalog).where(UnitTypeCatalog.code == payload.code)).scalar_one_or_none():
        raise PermissionError_(f"Mã loại đơn vị '{payload.code}' đã tồn tại.")
    ut = UnitTypeCatalog(unit_type_id=new_id(), **payload.model_dump())
    db.add(ut)
    record_audit(db, entity_type="unit_type_catalog", entity_id=ut.unit_type_id, action="create",
                 actor=user, after={"code": ut.code, "name": ut.name})
    db.commit()
    db.refresh(ut)
    return ut


@router.put("/unit-types/{unit_type_id}", response_model=UnitTypeCatalogOut)
def update_unit_type(unit_type_id: str, payload: UnitTypeCatalogIn, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    require_perm(user, "master.manage")
    ut = db.get(UnitTypeCatalog, unit_type_id)
    if not ut:
        raise NotFoundError("Loại đơn vị tồn kho không tồn tại.")
    if ut.code in master_data._SYSTEM_UNIT_TYPE_CODES and payload.code != ut.code:
        # Nhiều nơi trong services/wms.py so sánh trực tiếp chuỗi "vi"/"keg"/"lon" (VD
        # _decompose_one_vi luôn sinh unit_type="lon") — đổi mã sẽ làm lệch khỏi hành vi cứng
        # đó, có thể xóa/tạo nhầm loại. Vẫn cho sửa tên hiển thị/cờ quy đổi/trạng thái bình thường.
        raise PermissionError_(f"Không thể đổi mã của loại hệ thống '{ut.code}' — chỉ được sửa tên/cờ quy đổi.")
    before = {"code": ut.code, "name": ut.name, "divide_by_pack_size": ut.divide_by_pack_size,
             "selectable": ut.selectable, "active": ut.active}
    for k, v in payload.model_dump().items():
        setattr(ut, k, v)
    record_audit(db, entity_type="unit_type_catalog", entity_id=ut.unit_type_id, action="update",
                 actor=user, before=before, after=payload.model_dump())
    db.commit()
    db.refresh(ut)
    return ut


@router.delete("/unit-types/{unit_type_id}", status_code=204)
def delete_unit_type(unit_type_id: str, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    master_data.delete_unit_type(db, unit_type_id, user)


# ---- Nhà cung cấp (danh mục dùng khi nhập kho NVL) ----
@router.get("/suppliers", response_model=list[SupplierOut])
def list_suppliers(db: Session = Depends(get_db)):
    return db.execute(select(Supplier).order_by(Supplier.code)).scalars().all()


@router.post("/suppliers", response_model=SupplierOut, status_code=201)
def create_supplier(payload: SupplierIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    require_perm(user, "master.manage")
    if db.execute(select(Supplier).where(Supplier.code == payload.code)).scalar_one_or_none():
        raise PermissionError_(f"Mã nhà cung cấp '{payload.code}' đã tồn tại.")
    sup = Supplier(supplier_id=new_id(), **payload.model_dump())
    db.add(sup)
    record_audit(db, entity_type="supplier", entity_id=sup.supplier_id, action="create",
                 actor=user, after={"code": sup.code, "name": sup.name})
    db.commit()
    db.refresh(sup)
    return sup


@router.put("/suppliers/{supplier_id}", response_model=SupplierOut)
def update_supplier(supplier_id: str, payload: SupplierIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    require_perm(user, "master.manage")
    sup = db.get(Supplier, supplier_id)
    if not sup:
        raise NotFoundError("Nhà cung cấp không tồn tại.")
    before = {"code": sup.code, "name": sup.name}
    sup.code = payload.code
    sup.name = payload.name
    sup.address = payload.address
    sup.contact = payload.contact
    sup.note = payload.note
    record_audit(db, entity_type="supplier", entity_id=sup.supplier_id, action="update",
                 actor=user, before=before, after=payload.model_dump())
    db.commit()
    db.refresh(sup)
    return sup


@router.delete("/suppliers/{supplier_id}", status_code=204)
def delete_supplier(supplier_id: str, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    master_data.delete_supplier(db, supplier_id, user)


# ---- Nhóm vật tư (danh mục "Nhóm" dùng ở panel Vật tư/Nguyên liệu) ----
@router.get("/material-groups", response_model=list[MaterialGroupOut])
def list_material_groups(db: Session = Depends(get_db)):
    return db.execute(select(MaterialGroup).order_by(MaterialGroup.code)).scalars().all()


@router.post("/material-groups", response_model=MaterialGroupOut, status_code=201)
def create_material_group(payload: MaterialGroupIn, db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    require_perm(user, "master.manage")
    if db.execute(select(MaterialGroup).where(MaterialGroup.code == payload.code)).scalar_one_or_none():
        raise PermissionError_(f"Mã nhóm vật tư '{payload.code}' đã tồn tại.")
    g = MaterialGroup(group_id=new_id(), **payload.model_dump())
    db.add(g)
    record_audit(db, entity_type="material_group", entity_id=g.group_id, action="create",
                 actor=user, after={"code": g.code, "name": g.name})
    db.commit()
    db.refresh(g)
    return g


@router.put("/material-groups/{group_id}", response_model=MaterialGroupOut)
def update_material_group(group_id: str, payload: MaterialGroupIn, db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    require_perm(user, "master.manage")
    g = db.get(MaterialGroup, group_id)
    if not g:
        raise NotFoundError("Nhóm vật tư không tồn tại.")
    before = {"code": g.code, "name": g.name, "active": g.active, "is_packaging": g.is_packaging,
              "is_raw_material": g.is_raw_material}
    g.code = payload.code
    g.name = payload.name
    g.active = payload.active
    g.is_packaging = payload.is_packaging
    g.is_raw_material = payload.is_raw_material
    record_audit(db, entity_type="material_group", entity_id=g.group_id, action="update",
                 actor=user, before=before, after=payload.model_dump())
    db.commit()
    db.refresh(g)
    return g


@router.delete("/material-groups/{group_id}", status_code=204)
def delete_material_group(group_id: str, db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    master_data.delete_material_group(db, group_id, user)


# ---- Sản phẩm ----
@router.get("/products", response_model=list[ProductOut])
def list_products(db: Session = Depends(get_db)):
    return db.execute(select(Product).order_by(Product.code)).scalars().all()


@router.post("/products", response_model=ProductOut, status_code=201)
def create_product(payload: ProductIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    require_perm(user, "master.manage")
    if db.execute(select(Product).where(Product.code == payload.code)).scalar_one_or_none():
        raise PermissionError_(f"Mã sản phẩm '{payload.code}' đã tồn tại.")
    p = Product(product_id=new_id(), **payload.model_dump())
    db.add(p)
    record_audit(db, entity_type="product", entity_id=p.product_id, action="create",
                 actor=user, after={"code": p.code, "name": p.name, "uom": p.uom})
    db.commit()
    db.refresh(p)
    return p


@router.put("/products/{product_id}", response_model=ProductOut)
def update_product(product_id: str, payload: ProductIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    require_perm(user, "master.manage")
    p = db.get(Product, product_id)
    if not p:
        raise NotFoundError("Sản phẩm không tồn tại.")
    before = {"code": p.code, "name": p.name, "uom": p.uom, "description": p.description,
              "ferment_days_std": p.ferment_days_std, "beer_type_id": p.beer_type_id}
    p.code = payload.code
    p.name = payload.name
    p.uom = payload.uom
    p.description = payload.description
    p.ferment_days_std = payload.ferment_days_std
    p.beer_type_id = payload.beer_type_id
    record_audit(db, entity_type="product", entity_id=p.product_id, action="update",
                 actor=user, before=before, after=payload.model_dump())
    db.commit()
    db.refresh(p)
    return p


@router.delete("/products/{product_id}", status_code=204)
def delete_product(product_id: str, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    master_data.delete_product(db, product_id, user)


# ---- Quy định công nghệ nấu (Sapphire form QT-KCS-QT-BM-05) theo dịch bia ----
@router.get("/products/{product_id}/brew-spec")
def get_product_brew_spec(product_id: str, db: Session = Depends(get_db)):
    return braumat_svc.get_spec_values(db, product_id)


@router.put("/products/{product_id}/brew-spec")
def update_product_brew_spec(product_id: str, payload: ProductBrewSpecIn, db: Session = Depends(get_db),
                             user: User = Depends(get_current_user)):
    before = braumat_svc.get_spec_values(db, product_id)
    values = braumat_svc.update_spec_values(db, product_id, payload.model_dump(exclude_unset=True), user)
    record_audit(db, entity_type="product_brew_spec", entity_id=product_id, action="update",
                 actor=user, before=before, after=values)
    db.commit()
    return values


# ---- Sản phẩm (thành phẩm/SKU đóng gói) — khác Dịch bia (Product) ở trên ----
def _assert_unit_type_exists(db: Session, code: str) -> None:
    # Chặn gán cho SKU 1 mã KHÔNG có trong Danh mục Loại đơn vị tồn kho — nếu không, mọi lô
    # nhập kho thủ công/tồn đầu sau này của SKU đó sẽ mang unit_type lạ, không khớp code nào ở
    # _pack_divisor/_divide_by_pack_codes (services/wms.py) và bị đếm sai tồn kho hàng loạt mà
    # không có cảnh báo nào cho tới khi phát hiện trên số liệu thật.
    if not db.execute(select(UnitTypeCatalog.unit_type_id)
                      .where(UnitTypeCatalog.code == code)).first():
        raise DomainError(f"Loại đơn vị '{code}' không có trong Danh mục Loại đơn vị tồn kho.")


@router.get("/finished-products", response_model=list[FinishedProductOut])
def list_finished_products(db: Session = Depends(get_db)):
    return db.execute(select(FinishedProduct).order_by(FinishedProduct.code)).scalars().all()


@router.post("/finished-products", response_model=FinishedProductOut, status_code=201)
def create_finished_product(payload: FinishedProductIn, db: Session = Depends(get_db),
                            user: User = Depends(get_current_user)):
    require_perm(user, "master.manage")
    if db.execute(select(FinishedProduct).where(FinishedProduct.code == payload.code)).scalar_one_or_none():
        raise PermissionError_(f"Mã sản phẩm '{payload.code}' đã tồn tại.")
    _assert_unit_type_exists(db, payload.unit_type)
    fp = FinishedProduct(finished_product_id=new_id(), **payload.model_dump())
    db.add(fp)
    record_audit(db, entity_type="finished_product", entity_id=fp.finished_product_id, action="create",
                 actor=user, after={"code": fp.code, "name": fp.name, "uom": fp.uom})
    db.commit()
    db.refresh(fp)
    return fp


@router.put("/finished-products/{finished_product_id}", response_model=FinishedProductOut)
def update_finished_product(finished_product_id: str, payload: FinishedProductIn, db: Session = Depends(get_db),
                            user: User = Depends(get_current_user)):
    require_perm(user, "master.manage")
    fp = db.get(FinishedProduct, finished_product_id)
    if not fp:
        raise NotFoundError("Sản phẩm không tồn tại.")
    _assert_unit_type_exists(db, payload.unit_type)
    before = {"code": fp.code, "name": fp.name, "uom": fp.uom, "product_id": fp.product_id,
              "unit_type": fp.unit_type, "pack_size": fp.pack_size, "category": fp.category,
              "description": fp.description}
    fp.code = payload.code
    fp.name = payload.name
    fp.uom = payload.uom
    fp.product_id = payload.product_id
    fp.unit_type = payload.unit_type
    fp.pack_size = payload.pack_size
    fp.category = payload.category
    fp.description = payload.description
    record_audit(db, entity_type="finished_product", entity_id=fp.finished_product_id, action="update",
                 actor=user, before=before, after=payload.model_dump())
    db.commit()
    db.refresh(fp)
    return fp


@router.delete("/finished-products/{finished_product_id}", status_code=204)
def delete_finished_product(finished_product_id: str, db: Session = Depends(get_db),
                            user: User = Depends(get_current_user)):
    master_data.delete_finished_product(db, finished_product_id, user)


# ---- Vật tư / nguyên liệu ----
@router.get("/materials", response_model=list[MaterialOut])
def list_materials(db: Session = Depends(get_db)):
    return db.execute(select(Material).order_by(Material.code)).scalars().all()


@router.post("/materials", response_model=MaterialOut, status_code=201)
def create_material(payload: MaterialIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    require_perm(user, "master.manage")
    if db.execute(select(Material).where(Material.code == payload.code)).scalar_one_or_none():
        raise PermissionError_(f"Mã vật tư '{payload.code}' đã tồn tại.")
    m = Material(material_id=new_id(), **payload.model_dump())
    db.add(m)
    record_audit(db, entity_type="material", entity_id=m.material_id, action="create",
                 actor=user, after={"code": m.code, "name": m.name, "category": m.category})
    db.commit()
    db.refresh(m)
    return m


@router.put("/materials/{material_id}", response_model=MaterialOut)
def update_material(material_id: str, payload: MaterialIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    require_perm(user, "master.manage")
    m = db.get(Material, material_id)
    if not m:
        raise NotFoundError("Vật tư không tồn tại.")
    before = {"code": m.code, "name": m.name, "uom": m.uom, "category": m.category}
    m.code = payload.code
    m.name = payload.name
    m.uom = payload.uom
    m.category = payload.category
    record_audit(db, entity_type="material", entity_id=m.material_id, action="update",
                 actor=user, before=before, after=payload.model_dump())
    db.commit()
    db.refresh(m)
    return m


@router.delete("/materials/{material_id}", status_code=204)
def delete_material(material_id: str, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    master_data.delete_material(db, material_id, user)


# ---- Gán nhóm chỉ tiêu chất lượng cho nguyên liệu ----
@router.get("/materials/{material_id}/qc-groups")
def list_material_qc_groups(material_id: str, db: Session = Depends(get_db),
                            user: User = Depends(get_current_user)):
    return qc_catalog.list_material_groups(db, material_id)


@router.post("/materials/{material_id}/qc-groups", status_code=201)
def link_material_qc_group(material_id: str, payload: MaterialQcGroupIn,
                           db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return qc_catalog.link_material_group(db, material_id, payload.model_dump(), user)


@router.delete("/materials/{material_id}/qc-groups/{group_id}", status_code=204)
def unlink_material_qc_group(material_id: str, group_id: str, db: Session = Depends(get_db),
                             user: User = Depends(get_current_user)):
    qc_catalog.unlink_material_group(db, material_id, group_id, user)


# ---- Cài đặt vận hành (ngưỡng dung sai "Làm rỗng" tank CCT/BBT) ----
@router.get("/ops-settings", response_model=OpsSettingOut)
def get_ops_settings(db: Session = Depends(get_db)):
    return ops_setting_svc.get_settings(db)


@router.put("/ops-settings", response_model=OpsSettingOut)
def update_ops_settings(payload: OpsSettingIn, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    require_perm(user, "master.manage")
    return ops_setting_svc.update_settings(db, payload.empty_cct_tolerance_hl,
                                           payload.empty_bbt_tolerance_hl,
                                           payload.aging_caution_days, payload.aging_warning_days,
                                           payload.aging_critical_days, user, payload.factory_code,
                                           payload.filter_yield_low_hl, payload.filter_yield_high_hl,
                                           payload.filter_line_yield_low_l, payload.filter_line_yield_high_l)
