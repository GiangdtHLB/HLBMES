"""Nấu-Lọc-Chiết chi tiết: nguyên liệu, nấu, lên men, lọc, chiết, chỉ tiêu, cảnh báo."""


from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..common import new_id, utcnow
from ..database import get_db
from ..errors import NotFoundError
from ..models.brewing import (
    BottleRecord,
    BrewRecord,
    FermentRecord,
    FilterRecord,
    MaterialReceipt,
    StageIndicator,
)
from ..schemas import (
    BottleIn,
    BrewIn,
    FermentIn,
    FilterIn,
    MaterialReceiptIn,
    StageIndicatorIn,
)
from ..security import User, get_current_user, require_perm

# Mọi route yêu cầu đăng nhập (an toàn mặc định); thao tác ghi thêm require_perm bên dưới.
router = APIRouter(prefix="/api/brewing", tags=["brewing"],
                   dependencies=[Depends(get_current_user)])

# Trạng thái lọc/chiết hiển thị
FILTER_STATUS = {"cho_chiet": "Chờ chiết", "chiet_1_phan": "Chiết 1 phần", "da_chiet_het": "Đã chiết hết"}


def _has_indicators(db, stage, code):
    return db.execute(select(StageIndicator).where(
        StageIndicator.stage == stage, StageIndicator.scope_code == code)).first() is not None


# ===== Thông tin nguyên liệu =====
@router.get("/materials")
def list_materials(db: Session = Depends(get_db)):
    rows = db.execute(select(MaterialReceipt).order_by(MaterialReceipt.receipt_date.desc())).scalars().all()
    out = []
    for r in rows:
        # màu: đỏ=chưa số lô, xanh lá=chưa chỉ tiêu, xanh dương=đầy đủ
        if not (r.lot_pm and r.lot_kcs):
            color = "red"
        elif not r.has_indicators:
            color = "green"
        else:
            color = "blue"
        out.append({"receipt_id": r.receipt_id, "mskt": r.mskt, "receipt_date": r.receipt_date,
                    "material_name": r.material_name, "lot_pm": r.lot_pm, "lot_kcs": r.lot_kcs,
                    "quantity": r.quantity, "uom": r.uom, "location": r.location, "note": r.note,
                    "supplier": r.supplier, "color": color})
    return out


@router.post("/materials", status_code=201)
def add_material(payload: MaterialReceiptIn, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    require_perm(user, "batch.execute")
    data = payload.model_dump()
    data["mskt"] = data.get("mskt") or f"{50000 + int(utcnow().timestamp()) % 9999}"
    r = MaterialReceipt(receipt_id=new_id(), **data)
    db.add(r); db.commit(); db.refresh(r)
    return r


# ===== Thông tin nấu =====
@router.get("/brews")
def list_brews(db: Session = Depends(get_db)):
    rows = db.execute(select(BrewRecord).order_by(BrewRecord.brew_date.desc())).scalars().all()
    return [{"brew_id": b.brew_id, "brew_code": b.brew_code, "brew_date": b.brew_date,
             "wort_type": b.wort_type, "volume_hl": b.volume_hl, "original_extract": b.original_extract,
             "plato": b.plato, "note": b.note,
             "color": "blue" if (b.original_extract is not None and b.plato is not None) else "red"}
            for b in rows]


@router.post("/brews", status_code=201)
def add_brew(payload: BrewIn, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    require_perm(user, "batch.execute")
    b = BrewRecord(brew_id=new_id(), **payload.model_dump())
    db.add(b); db.commit(); db.refresh(b)
    return b


# ===== Thông tin lên men =====
@router.get("/ferments")
def list_ferments(db: Session = Depends(get_db)):
    rows = db.execute(select(FermentRecord).order_by(FermentRecord.brew_date.desc())).scalars().all()
    total_brew = sum(r.volume_hl for r in rows)
    total_cct = sum(r.on_hand_cct for r in rows)
    items = [{"ferment_id": r.ferment_id, "lm_code": r.lm_code, "brew_code": r.brew_code,
              "brew_date": r.brew_date, "kt_date": r.kt_date, "batch_numbers": r.batch_numbers,
              "wort_type": r.wort_type, "yeast_gen": r.yeast_gen, "tank_lm": r.tank_lm,
              "volume_hl": r.volume_hl, "on_hand_cct": r.on_hand_cct,
              "status": r.status, "ferment_days": r.ferment_days} for r in rows]
    return {"items": items, "total_brew_hl": round(total_brew, 1), "total_cct_hl": round(total_cct, 1)}


@router.post("/ferments", status_code=201)
def add_ferment(payload: FermentIn, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    require_perm(user, "batch.execute")
    f = FermentRecord(ferment_id=new_id(), **payload.model_dump())
    if not f.on_hand_cct:
        f.on_hand_cct = f.volume_hl
    db.add(f); db.commit(); db.refresh(f)
    return f


# ===== Thông tin lọc =====
@router.get("/filters")
def list_filters(db: Session = Depends(get_db)):
    rows = db.execute(select(FilterRecord).order_by(FilterRecord.filter_date.desc())).scalars().all()
    out = []
    for r in rows:
        if r.filter_type == "ve_bbt_phoi":
            color = "cyan"
        elif not r.has_indicators:
            color = "red"
        elif not r.has_nvl:
            color = "green"
        else:
            color = "blue"
        out.append({"filter_id": r.filter_id, "filter_code": r.filter_code, "brew_code": r.brew_code,
                    "lot_loc": r.lot_loc, "filter_phoi_code": r.filter_phoi_code, "filter_date": r.filter_date,
                    "filter_type": r.filter_type, "wort_type": r.wort_type, "from_cct": r.from_cct,
                    "v_dich_hl": r.v_dich_hl, "beer_type": r.beer_type, "v_beer_hl": r.v_beer_hl,
                    "to_bbt": r.to_bbt, "status": r.status, "status_label": FILTER_STATUS.get(r.status, r.status),
                    "on_hand_bbt": r.on_hand_bbt, "color": color})
    return out


@router.post("/filters", status_code=201)
def add_filter(payload: FilterIn, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    require_perm(user, "batch.execute")
    f = FilterRecord(filter_id=new_id(), **payload.model_dump())
    if not f.on_hand_bbt:
        f.on_hand_bbt = f.v_beer_hl
    db.add(f); db.commit(); db.refresh(f)
    return f


# ===== Thông tin chiết =====
@router.get("/bottles")
def list_bottles(db: Session = Depends(get_db)):
    rows = db.execute(select(BottleRecord).order_by(BottleRecord.bottle_date.desc())).scalars().all()
    out = []
    for b in rows:
        total = b.ca1 + b.ca2 + b.ca3
        if not b.has_indicators:
            color = "red"
        elif not b.has_nvl:
            color = "green"
        else:
            color = "blue"
        out.append({"bottle_id": b.bottle_id, "bottle_code": b.bottle_code, "filter_code": b.filter_code,
                    "bottle_date": b.bottle_date, "beer_type": b.beer_type, "lot_no": b.lot_no,
                    "v_cap_chiet_hl": b.v_cap_chiet_hl, "from_bbt": b.from_bbt, "line": b.line,
                    "ca1": b.ca1, "ca2": b.ca2, "ca3": b.ca3, "total": round(total, 1),
                    "stocked": b.stocked, "approved": b.approved, "note": b.note, "color": color})
    return out


@router.post("/bottles", status_code=201)
def add_bottle(payload: BottleIn, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    require_perm(user, "batch.execute")
    b = BottleRecord(bottle_id=new_id(), **payload.model_dump())
    db.add(b); db.commit(); db.refresh(b)
    return b


@router.post("/bottles/{bottle_id}/approve")
def approve_bottle(bottle_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    b = db.get(BottleRecord, bottle_id)
    if not b:
        raise NotFoundError("Bản ghi chiết không tồn tại.")
    b.approved = True
    db.commit()
    return {"bottle_id": bottle_id, "approved": True}


# ===== Chỉ tiêu phân tích =====
@router.get("/indicators")
def list_indicators(stage: str, scope_code: str, db: Session = Depends(get_db)):
    return db.execute(select(StageIndicator).where(
        StageIndicator.stage == stage, StageIndicator.scope_code == scope_code)
        .order_by(StageIndicator.name)).scalars().all()


@router.post("/indicators", status_code=201)
def add_indicator(payload: StageIndicatorIn, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    ind = StageIndicator(indicator_id=new_id(), analyst=user.username, updated_at=utcnow(),
                         **payload.model_dump())
    db.add(ind)
    # đánh dấu công đoạn đã có chỉ tiêu
    if payload.stage == "loc":
        rec = db.execute(select(FilterRecord).where(FilterRecord.filter_code == payload.scope_code)).scalar_one_or_none()
        if rec:
            rec.has_indicators = True
    elif payload.stage == "chiet":
        rec = db.execute(select(BottleRecord).where(BottleRecord.bottle_code == payload.scope_code)).scalar_one_or_none()
        if rec:
            rec.has_indicators = True
    db.commit(); db.refresh(ind)
    return ind


# ===== Cảnh báo chỉ tiêu chất lượng (theo tháng/năm) =====
@router.get("/alerts")
def alerts(month: int = None, year: int = None, db: Session = Depends(get_db)):
    from ..services import derived
    return derived.brewing_alerts(db, month, year)
