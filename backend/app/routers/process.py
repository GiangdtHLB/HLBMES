"""Nấu-Lọc-Chiết, hóa chất, thu hồi men, cảnh báo chỉ tiêu chất lượng."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import LotStatus, new_id, utcnow
from ..database import get_db
from ..errors import DomainError, NotFoundError
from ..models.batches import BatchExecution
from ..models.metrics import ProcessReading
from ..models.process import ChemicalUsage, YeastIssue, YeastLot
from ..models.quality import QualityResult
from ..schemas import ChemicalUsageIn, YeastIssueIn, YeastLotIn
from ..security import User, get_current_user

router = APIRouter(prefix="/api/process", tags=["process"])


# ---- Thông tin công đoạn theo mẻ (tổng hợp từ dữ liệu sẵn có) ----
@router.get("/stage-info/{batch_id}")
def stage_info(batch_id: str, db: Session = Depends(get_db)):
    b = db.get(BatchExecution, batch_id)
    if not b:
        raise NotFoundError("Batch không tồn tại.")
    readings = db.execute(select(ProcessReading).where(ProcessReading.batch_id == batch_id)).scalars().all()
    results = db.execute(select(QualityResult).where(QualityResult.scope_type == "batch",
                                                     QualityResult.scope_id == batch_id)).scalars().all()
    chems = db.execute(select(ChemicalUsage).where(ChemicalUsage.batch_id == batch_id)).scalars().all()

    def summarize(values):
        vals = [v for v in values if v is not None]
        if not vals:
            return None
        return {"min": round(min(vals), 2), "max": round(max(vals), 2),
                "avg": round(sum(vals) / len(vals), 2), "last": round(vals[-1], 2), "n": len(vals)}

    by_param = {}
    for r in readings:
        by_param.setdefault(r.parameter, []).append(r.value)

    return {
        "batch_code": b.batch_code,
        "state": b.state,
        "actuals": b.actuals,
        "readings_summary": {p: summarize(v) for p, v in by_param.items()},
        "quality": [{"parameter": r.parameter, "value": r.value, "unit": r.unit, "status": r.status}
                    for r in results],
        "chemicals": [{"stage": c.stage, "chemical": c.chemical, "quantity": c.quantity,
                       "uom": c.uom, "ts": c.ts} for c in chems],
    }


# ---- Sử dụng hóa chất ----
@router.get("/chemicals")
def list_chemicals(batch_id: str = None, db: Session = Depends(get_db)):
    stmt = select(ChemicalUsage).order_by(ChemicalUsage.ts.desc())
    if batch_id:
        stmt = stmt.where(ChemicalUsage.batch_id == batch_id)
    return db.execute(stmt).scalars().all()


@router.post("/chemicals", status_code=201)
def add_chemical(payload: ChemicalUsageIn, db: Session = Depends(get_db)):
    c = ChemicalUsage(usage_id=new_id(), **payload.model_dump())
    db.add(c); db.commit(); db.refresh(c)
    return c


# ---- Thu hồi men ----
@router.get("/yeast")
def list_yeast(db: Session = Depends(get_db)):
    return db.execute(select(YeastLot).order_by(YeastLot.harvest_at.desc())).scalars().all()


@router.post("/yeast", status_code=201)
def harvest_yeast(payload: YeastLotIn, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    y = YeastLot(yeast_lot_id=new_id(), **payload.model_dump())
    db.add(y)
    record_audit(db, entity_type="yeast_lot", entity_id=y.yeast_lot_id, action="harvest",
                 actor=user, after={"code": y.code, "generation": y.generation})
    db.commit(); db.refresh(y)
    return y


@router.post("/yeast/{yeast_lot_id}/issue", status_code=201)
def issue_yeast(yeast_lot_id: str, payload: YeastIssueIn, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    y = db.get(YeastLot, yeast_lot_id)
    if not y:
        raise NotFoundError("Lô men không tồn tại.")
    if y.status != LotStatus.AVAILABLE.value:
        raise DomainError("Lô men không ở trạng thái khả dụng.")
    if payload.quantity <= 0 or payload.quantity > y.quantity:
        raise DomainError(f"Số lượng xuất không hợp lệ (tồn {y.quantity} {y.uom}).")
    y.quantity -= payload.quantity
    if y.quantity == 0:
        y.status = "used"
    iss = YeastIssue(issue_id=new_id(), yeast_lot_id=yeast_lot_id, batch_id=payload.batch_id,
                     quantity=payload.quantity, uom=y.uom, actor=user.username, ts=utcnow())
    db.add(iss)
    record_audit(db, entity_type="yeast_lot", entity_id=y.yeast_lot_id, action="issue",
                 actor=user, after={"quantity": payload.quantity, "batch": payload.batch_id})
    db.commit(); db.refresh(iss)
    return iss


@router.get("/yeast/issues")
def yeast_issues(db: Session = Depends(get_db)):
    issues = db.execute(select(YeastIssue).order_by(YeastIssue.ts.desc())).scalars().all()
    out = []
    for i in issues:
        y = db.get(YeastLot, i.yeast_lot_id)
        b = db.get(BatchExecution, i.batch_id) if i.batch_id else None
        out.append({"ts": i.ts, "yeast_code": y.code if y else i.yeast_lot_id,
                    "batch": b.batch_code if b else None, "quantity": i.quantity,
                    "uom": i.uom, "actor": i.actor})
    return out


# ---- Cảnh báo chỉ tiêu chất lượng ----
@router.get("/alerts")
def quality_alerts(db: Session = Depends(get_db)):
    """Tổng hợp cảnh báo: QC FAIL + reading vượt giới hạn QC trong recipe snapshot."""
    from ..services import derived
    return derived.process_quality_alerts(db)
