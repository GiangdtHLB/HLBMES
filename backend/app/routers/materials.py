"""Material/product lots."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import new_id
from ..database import get_db
from ..models.materials import MaterialLot
from ..schemas import LotIn, LotOut
from ..security import User, get_current_user

router = APIRouter(prefix="/api/lots", tags=["lots"])


@router.get("", response_model=list[LotOut])
def list_lots(db: Session = Depends(get_db)):
    return db.execute(select(MaterialLot).order_by(MaterialLot.created_at.desc())).scalars().all()


@router.post("", response_model=LotOut, status_code=201)
def create_lot(payload: LotIn, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    lot = MaterialLot(lot_id=new_id(), **payload.model_dump())
    db.add(lot)
    record_audit(db, entity_type="lot", entity_id=lot.lot_id, action="create",
                 actor=user, after={"lot_code": lot.lot_code, "quantity": lot.quantity})
    db.commit()
    db.refresh(lot)
    return lot
