"""WMS thành phẩm: vị trí, pallet/case, putaway/ship, phân giải barcode (P3-4)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..common import new_id
from ..database import get_db
from ..models.wms import WmsLocation
from ..schemas import PalletBuildIn, PutawayIn, WmsLocationIn
from ..security import User, get_current_user, require_perm
from ..services import wms as svc

router = APIRouter(prefix="/api/wms", tags=["wms"])


@router.get("/locations")
def locations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.list_locations(db)


@router.post("/locations", status_code=201)
def create_location(payload: WmsLocationIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    require_perm(user, "warehouse.receive")
    loc = WmsLocation(loc_id=new_id(), **payload.model_dump())
    db.add(loc)
    db.commit()
    return {"loc_id": loc.loc_id, "code": loc.code}


@router.get("/pallets")
def pallets(status: str = None, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    return svc.list_pallets(db, status)


@router.post("/pallets", status_code=201)
def build_pallet(payload: PalletBuildIn, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    p = svc.build_pallet(db, payload.model_dump(), user)
    return {"pallet_id": p.pallet_id, "pallet_code": p.pallet_code, "status": p.status}


@router.post("/pallets/{pallet_id}/putaway")
def putaway(pallet_id: str, payload: PutawayIn, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    return svc.putaway(db, pallet_id, payload.loc_id, user)


@router.post("/pallets/{pallet_id}/ship")
def ship(pallet_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.ship(db, pallet_id, user)


@router.get("/resolve")
def resolve(code: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.resolve(db, code)
