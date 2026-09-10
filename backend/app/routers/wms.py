"""WMS thành phẩm: vị trí, pallet/case, putaway/ship, phân giải barcode (P3-4)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..common import Role
from ..database import get_db
from ..schemas import PalletBuildIn, PutawayIn, WmsLocationIn, WmsLocationUpdate
from ..security import User, get_current_user, require_role
from ..services import wms as svc

router = APIRouter(prefix="/api/wms", tags=["wms"])


@router.get("/summary")
def summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.summary(db)


@router.get("/locations")
def locations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.list_locations(db)


@router.post("/locations", status_code=201)
def create_location(payload: WmsLocationIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    require_role(user, Role.ADMIN)
    loc = svc.create_location(db, payload.model_dump())
    return {"loc_id": loc.loc_id, "code": loc.code}


@router.put("/locations/{loc_id}")
def update_location(loc_id: str, payload: WmsLocationUpdate, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    require_role(user, Role.ADMIN)
    loc = svc.update_location(db, loc_id, payload.model_dump(exclude_unset=True))
    return {"loc_id": loc.loc_id, "code": loc.code}


@router.delete("/locations/{loc_id}", status_code=204)
def delete_location(loc_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_role(user, Role.ADMIN)
    svc.delete_location(db, loc_id)


@router.get("/pallets")
def pallets(status: str | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.list_pallets(db, status)


@router.post("/pallets", status_code=201)
def build_pallet(payload: PalletBuildIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    pallet = svc.build_pallet(db, payload.model_dump(), user)
    return {"pallet_id": pallet.pallet_id, "pallet_code": pallet.pallet_code, "status": pallet.status}


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
