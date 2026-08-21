"""Production orders."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import OrderIn, OrderOut
from ..security import User, get_current_user, require_perm
from ..services import orders as order_svc

router = APIRouter(prefix="/api/orders", tags=["orders"],
                   dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[OrderOut])
def list_orders(db: Session = Depends(get_db)):
    return order_svc.list_orders(db)


@router.get("/bom-preview")
def preview_order_bom(recipe_version_id: str = None, planned_batch_count: int = 1,
                      db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Xem trước bảng định mức NVL (tự nạp từ Công thức) + tồn kho hiện tại — TRƯỚC khi tạo
    Lệnh SX thật, để biết ngay có đủ NVL hay không (nút "Xem NVL" ở form Tạo lệnh sản xuất)."""
    require_perm(user, "order.create")
    if not recipe_version_id:
        return []
    return order_svc.preview_bom(db, recipe_version_id, planned_batch_count)


@router.post("", response_model=OrderOut, status_code=201)
def create_order(payload: OrderIn, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    require_perm(user, "order.create")
    return order_svc.create_order(db, payload.model_dump(), user)


@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: str, db: Session = Depends(get_db)):
    return order_svc.get_order(db, order_id)


@router.put("/{order_id}", response_model=OrderOut)
def update_order(order_id: str, payload: OrderIn, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    require_perm(user, "order.create")
    return order_svc.update_order(db, order_id, payload.model_dump(), user)


@router.delete("/{order_id}", status_code=204)
def delete_order(order_id: str, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    require_perm(user, "order.create")
    order_svc.delete_order(db, order_id, user)
