"""Production orders."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import new_id
from ..database import get_db
from ..models.orders import ProductionOrder
from ..schemas import OrderIn, OrderOut
from ..security import User, get_current_user, require_perm

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.get("", response_model=list[OrderOut])
def list_orders(db: Session = Depends(get_db)):
    return db.execute(select(ProductionOrder).order_by(ProductionOrder.created_at.desc())).scalars().all()


@router.post("", response_model=OrderOut, status_code=201)
def create_order(payload: OrderIn, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    require_perm(user, "order.create")
    order = ProductionOrder(order_id=new_id(), **payload.model_dump())
    db.add(order)
    record_audit(db, entity_type="order", entity_id=order.order_id, action="create",
                 actor=user, after={"order_code": order.order_code})
    db.commit()
    db.refresh(order)
    return order


@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: str, db: Session = Depends(get_db)):
    from ..errors import NotFoundError
    order = db.get(ProductionOrder, order_id)
    if not order:
        raise NotFoundError("Order không tồn tại.")
    return order
