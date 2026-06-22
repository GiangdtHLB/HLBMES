"""Kho NVL nhà máy."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..security import User, get_current_user, require_perm
from ..services import warehouse as svc
from ..schemas import (
    IssueIn,
    ReceiptIn,
    ReturnIn,
    TransferIn,
)

router = APIRouter(prefix="/api/warehouse", tags=["warehouse"])


@router.post("/receive")
def receive(payload: ReceiptIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "warehouse.receive")
    return svc.receive(db, payload.model_dump(), user)


@router.post("/return")
def return_stock(payload: ReturnIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "warehouse.issue")
    return svc.return_stock(db, payload.lot_id, payload.quantity, user, payload.reason)


@router.post("/issue")
def issue(payload: IssueIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "warehouse.issue")
    return svc.issue(db, payload.lot_id, payload.quantity, user, payload.mode, payload.reason, payload.ref_doc)


@router.post("/transfer")
def transfer(payload: TransferIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "warehouse.issue")
    return svc.transfer(db, payload.lot_id, payload.quantity, payload.location_to, user, payload.reason)


@router.get("/stock")
def stock(db: Session = Depends(get_db)):
    return svc.stock_on_hand(db)


@router.get("/card")
def card(material_id: str = None, lot_id: str = None, db: Session = Depends(get_db)):
    return svc.stock_card(db, material_id, lot_id)


@router.get("/expiry")
def expiry(warn_days: int = 30, db: Session = Depends(get_db)):
    return svc.expiry_report(db, warn_days)


@router.get("/report")
def report(days: int = 30, db: Session = Depends(get_db)):
    return svc.inventory_report(db, days)
