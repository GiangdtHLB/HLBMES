"""Master data: products, materials (danh mục).

Tạo/sửa danh mục yêu cầu quyền 'master.manage' và được ghi audit (SoR nội bộ;
thực tế đồng bộ từ ERP/PLM — tài liệu §5.2, §8.1)."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import new_id
from ..database import get_db
from ..errors import NotFoundError, PermissionError_
from ..models.master import Material, Product
from ..schemas import MaterialIn, MaterialOut, ProductIn, ProductOut
from ..security import User, get_current_user, require_perm

router = APIRouter(prefix="/api", tags=["master"],
                   dependencies=[Depends(get_current_user)])


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
    before = {"code": p.code, "name": p.name, "uom": p.uom, "description": p.description}
    p.code = payload.code
    p.name = payload.name
    p.uom = payload.uom
    p.description = payload.description
    record_audit(db, entity_type="product", entity_id=p.product_id, action="update",
                 actor=user, before=before, after=payload.model_dump())
    db.commit()
    db.refresh(p)
    return p


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
