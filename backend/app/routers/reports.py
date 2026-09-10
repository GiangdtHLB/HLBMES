"""Báo cáo sản xuất — BC định mức NVL (Nấu/Lọc/Chiết, tổng hợp nhiều lệnh)."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..common import utcnow
from ..database import get_db
from ..security import User, get_current_user
from ..services import norm_report as norm_report_svc

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/material-norm")
def material_norm(days: int = 90, tol_pct: float = 5.0, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """BC định mức NVL: đối chiếu định mức ↔ thực tế tiêu thụ, tách riêng theo đúng 3 module
    đang vận hành thật (Nấu/Lọc/Chiết) — xem services/norm_report.py."""
    return {"days": days, "tol_pct": tol_pct,
            "nau": norm_report_svc.brew_norm_report(db, days, tol_pct),
            "loc": norm_report_svc.filter_norm_report(db, days, tol_pct),
            "chiet": norm_report_svc.packaging_actual_report(db, days)}


# ---- Báo cáo sản lượng chiết (lon) thật từ CSDL SCADA ngoài (SqlConnection.purpose="filling") ----
@router.get("/filling-bounds")
def filling_bounds(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import filling_external
    return filling_external.data_bounds(db)


@router.get("/filling-realtime")
def filling_realtime(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Trạng thái tức thời máy chiết lon 30K (bảng 30K_Realtime, cùng kết nối purpose="filling")."""
    from ..services import filling_external
    return filling_external.filling_realtime_status(db)


@router.get("/filling-report")
def filling_report(date_from: datetime = None, date_to: datetime = None,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import filling_external
    if not date_from or not date_to:
        # Mặc định: đúng 1 ngày gần nhất có dữ liệu — Ca 1 (06h) của ngày đó tới Ca 3 (06h ngày kế).
        bounds = filling_external.data_bounds(db)
        ref_day = datetime.fromisoformat(bounds["max_date"])
        date_from = date_from or ref_day.replace(hour=filling_external.SHIFT_ANCHOR_HOUR, minute=0, second=0)
        date_to = date_to or (date_from + timedelta(hours=24))
    return filling_external.filling_report(db, date_from, date_to)


# ---- Báo cáo trạng thái lô tổng hợp (Nấu/Lên men/Lọc/Chiết) ----
@router.get("/lo-status")
def lo_status(days: int = 180, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import lo_status as lo_status_svc
    return lo_status_svc.lo_status_report(db, days=days)


# ---- Tổng hợp cho Tổng quan (dashboard): lệnh/mẻ nấu-lọc-chiết + sản lượng chiết lon/keg ----
@router.get("/dashboard-summary")
def dashboard_summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import dashboard as dashboard_svc
    return dashboard_svc.production_summary(db)


@router.get("/qc-attention-alerts")
def qc_attention_alerts(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import dashboard as dashboard_svc
    return dashboard_svc.qc_attention_alerts(db)


@router.get("/overdue-action-alerts")
def overdue_action_alerts(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import dashboard as dashboard_svc
    return dashboard_svc.overdue_action_alerts(db)


@router.get("/low-yield-filter-alerts")
def low_yield_filter_alerts(days: int = 5, limit: int = 5, db: Session = Depends(get_db),
                            user: User = Depends(get_current_user)):
    from ..services import dashboard as dashboard_svc
    return dashboard_svc.low_yield_filter_alerts(db, days, limit)


@router.get("/bottled-not-approved")
def bottled_not_approved(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import dashboard as dashboard_svc
    return dashboard_svc.bottled_not_approved_report(db)


# ---- Báo cáo sản lượng lọc theo mẻ (Thấp/Bình thường/Cao so với ngưỡng OpsSetting) ----
@router.get("/filter-yield-report")
def filter_yield_report(date_from: datetime = None, date_to: datetime = None, group_by: str = "day",
                        db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import filter_yield_report as filter_yield_svc
    from ..services import ops_setting as ops_setting_svc
    if not date_from or not date_to:
        # Mặc định: 90 ngày gần nhất.
        date_to = date_to or utcnow()
        date_from = date_from or (date_to - timedelta(days=90))
    settings = ops_setting_svc.get_settings(db)
    return filter_yield_svc.filter_yield_report(db, date_from, date_to, settings.filter_yield_low_hl,
                                                settings.filter_yield_high_hl, group_by)


# ---- Báo cáo sản lượng lọc theo TỪNG DÒNG "mẻ lọc số" (kèm truy vết tank LM/mẻ nấu nguồn) ----
@router.get("/filter-line-yield-report")
def filter_line_yield_report(date_from: datetime = None, date_to: datetime = None,
                             db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import filter_yield_report as filter_yield_svc
    from ..services import ops_setting as ops_setting_svc
    if not date_from or not date_to:
        date_to = date_to or utcnow()
        date_from = date_from or (date_to - timedelta(days=90))
    settings = ops_setting_svc.get_settings(db)
    return filter_yield_svc.filter_line_yield_report(db, date_from, date_to,
                                                     settings.filter_line_yield_low_l,
                                                     settings.filter_line_yield_high_l)


