"""Cấp phát nguyên liệu cho mẻ: dispense (chọn lô/FEFO) + backflush (§7.4)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import BackflushIn, DispenseIn
from ..security import User, get_current_user, require_perm
from ..services import dispense as svc

router = APIRouter(prefix="/api/dispense", tags=["dispense"])


@router.get("")
def list_dispenses(batch_id: str = None, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    return svc.list_dispenses(db, batch_id)


@router.post("/{batch_id}")
def dispense(batch_id: str, payload: DispenseIn, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    """Cấp liệu cho mẻ (trừ tồn lô + genealogy + chặn vượt định mức / lô hết hạn)."""
    require_perm(user, "batch.execute")
    return svc.dispense(db, batch_id, [l.model_dump() for l in payload.lines], user, payload.note)


@router.post("/{batch_id}/backflush")
def backflush(batch_id: str, payload: BackflushIn, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    """Backflush: tự khấu trừ NVL theo định mức BOM × tỉ lệ sản lượng đã sản xuất."""
    require_perm(user, "batch.execute")
    return svc.backflush(db, batch_id, payload.produced_qty, user)
