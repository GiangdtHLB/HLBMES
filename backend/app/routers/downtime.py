"""Downtime: danh mục lý do (OeeReasonCatalog), ghi sự kiện dừng, Pareto (theo lý do/category),
6 big losses, MTBF/MTTR, thác nước OPI theo tháng, đếm dừng lắt nhắt theo tuần (§7.7)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import DowntimeIn, OeeMinorStopTallyIn, OeeReasonCatalogIn, OeeReasonCatalogUpdate
from ..security import User, get_current_user
from ..services import downtime as svc
from ..services import oee_minor_stop, oee_summary, oee_waterfall

router = APIRouter(prefix="/api/downtime", tags=["downtime"])


@router.get("/reason-tree")
def reason_tree(line_code: str = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.reason_tree(db, line_code)


@router.get("/reason-catalog")
def list_reason_catalog(line_code: str = None, category: str = None, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    return svc.list_reason_catalog(db, line_code, category, active_only=False)


@router.post("/reason-catalog", status_code=201)
def create_reason_catalog(payload: OeeReasonCatalogIn, db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    row = svc.create_reason(db, payload.model_dump(), user)
    return {"reason_id": row.reason_id}


@router.put("/reason-catalog/{reason_id}")
def update_reason_catalog(reason_id: str, payload: OeeReasonCatalogUpdate, db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    row = svc.update_reason(db, reason_id, payload.model_dump(exclude_unset=True), user)
    return {"reason_id": row.reason_id}


@router.delete("/reason-catalog/{reason_id}", status_code=204)
def delete_reason_catalog(reason_id: str, db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    svc.delete_reason(db, reason_id, user)


@router.get("")
def list_events(line: str = None, limit: int = None, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    return svc.list_events(db, line, limit)


@router.post("", status_code=201)
def record(payload: DowntimeIn, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    ev = svc.record_downtime(db, payload.model_dump(), user)
    return {"event_id": ev.event_id, "line": ev.line, "minutes": ev.minutes,
            "reason_label": ev.reason_label, "loss_category": ev.loss_category}


@router.get("/pareto")
def pareto(line: str = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.pareto(db, line)


@router.get("/pareto-by-category")
def pareto_by_category(line: str = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.pareto_by_category(db, line)


@router.get("/big-losses")
def big_losses(line: str = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.big_losses(db, line)


@router.get("/mtbf")
def mtbf(days: int = 30, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.mtbf_mttr(db, days)


@router.get("/waterfall")
def waterfall(line_code: str, year: int, month: int, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    return oee_waterfall.waterfall_report(db, line_code, year, month)


@router.get("/opi-summary")
def opi_summary(line_code: str, year: int, month: int, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    return oee_waterfall.opi_summary(db, line_code, year, month)


@router.get("/summary-dashboard")
def summary_dashboard(line_code: str, year: int, month: int, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    return oee_summary.summary_dashboard(db, line_code, year, month)


@router.get("/minor-stop-tally")
def minor_stop_tally(line_code: str, iso_year: int, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    return oee_minor_stop.weekly_grid(db, line_code, iso_year)


@router.put("/minor-stop-tally", status_code=200)
def upsert_minor_stop_tally(payload: OeeMinorStopTallyIn, db: Session = Depends(get_db),
                            user: User = Depends(get_current_user)):
    row = oee_minor_stop.upsert_tally(db, payload.reason_id, payload.iso_year, payload.iso_week,
                                      payload.shift, payload.count, user)
    return {"tally_id": row.tally_id}


@router.get("/minor-stop-pareto")
def minor_stop_pareto(line_code: str, iso_year: int, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    return oee_minor_stop.weekly_pareto(db, line_code, iso_year)
