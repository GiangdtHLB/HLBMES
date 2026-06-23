"""Bao bì tuần hoàn: vỏ chai / két-gông / keg inox — khai báo + biến động (P)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import PackagingMoveIn, PackagingTypeIn
from ..security import User, get_current_user
from ..services import packaging as svc

router = APIRouter(prefix="/api/packaging", tags=["packaging"])


@router.get("")
def list_types(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"summary": svc.summary(db), "types": svc.list_types(db),
            "categories": svc.CATEGORIES, "moves": svc.MOVES}


@router.post("", status_code=201)
def create_type(payload: PackagingTypeIn, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    p = svc.create_type(db, payload.model_dump(), user)
    return {"pkg_id": p.pkg_id, "code": p.code}


@router.post("/move")
def move(payload: PackagingMoveIn, db: Session = Depends(get_db),
         user: User = Depends(get_current_user)):
    return svc.move(db, payload.pkg_id, payload.kind, payload.qty, user, payload.ref, payload.note)


@router.get("/moves")
def list_moves(pkg_id: str = None, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    return svc.list_moves(db, pkg_id)
