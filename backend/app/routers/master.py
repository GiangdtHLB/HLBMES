"""Master data: products, materials."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..common import new_id
from ..database import get_db
from ..models.master import Material, Product
from ..schemas import MaterialIn, MaterialOut, ProductIn, ProductOut

router = APIRouter(prefix="/api", tags=["master"])


@router.get("/products", response_model=list[ProductOut])
def list_products(db: Session = Depends(get_db)):
    return db.execute(select(Product).order_by(Product.code)).scalars().all()


@router.post("/products", response_model=ProductOut, status_code=201)
def create_product(payload: ProductIn, db: Session = Depends(get_db)):
    p = Product(product_id=new_id(), **payload.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.get("/materials", response_model=list[MaterialOut])
def list_materials(db: Session = Depends(get_db)):
    return db.execute(select(Material).order_by(Material.code)).scalars().all()


@router.post("/materials", response_model=MaterialOut, status_code=201)
def create_material(payload: MaterialIn, db: Session = Depends(get_db)):
    m = Material(material_id=new_id(), **payload.model_dump())
    db.add(m)
    db.commit()
    db.refresh(m)
    return m
