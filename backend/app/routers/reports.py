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


# ---- Trạm quan trắc nước thải Hạ Long (SqlConnection.purpose="wastewater") ----
@router.get("/wastewater-realtime")
def wastewater_realtime(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Snapshot tức thời trạm quan trắc nước thải Hạ Long (bảng QT_Realtime)."""
    from ..services import wastewater_external
    return wastewater_external.wastewater_realtime_status(db)


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


# ---- Báo cáo sản lượng chiết KEG thật từ CSDL SCADA ngoài (SqlConnection.purpose="filling_keg") ----
@router.get("/keg-bounds")
def keg_bounds(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import keg_external
    return keg_external.data_bounds(db)


@router.get("/keg-report")
def keg_report(date_from: datetime = None, date_to: datetime = None,
              db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import keg_external
    if not date_from or not date_to:
        # Mặc định: ngày hôm qua — Ca 1 (06h) hôm qua tới Ca 3 (06h hôm nay).
        ref_day = (utcnow() - timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
        date_from = date_from or ref_day
        date_to = date_to or (date_from + timedelta(hours=24))
    return keg_external.keg_report(db, date_from, date_to)


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


# ---- Báo cáo xuất thành phẩm theo ca (Ca 1/2/3, giống Năng lượng) ----
@router.get("/finished-goods-shift-report")
def finished_goods_shift_report(date_from: datetime = None, date_to: datetime = None,
                                db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import wms as wms_svc
    if not date_from or not date_to:
        # Mặc định: ngày hôm qua — Ca 1 (06h) hôm qua tới Ca 3 (06h hôm nay), giống keg_report.
        ref_day = (utcnow() - timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
        date_from = date_from or ref_day
        date_to = date_to or (date_from + timedelta(hours=24))
    result = wms_svc.finished_goods_shift_report(db, date_from, date_to)
    result.update({"date_from": date_from.isoformat(), "date_to": date_to.isoformat()})
    return result


# ---- Báo cáo lượng bia khuyến mại/đổi trả/cận date/gửi theo ngày hoặc tháng ----
@router.get("/shipment-classification-report")
def shipment_classification_report(date_from: datetime = None, date_to: datetime = None,
                                    group_by: str = "day", db: Session = Depends(get_db),
                                    user: User = Depends(get_current_user)):
    from ..services import wms as wms_svc
    if not date_from or not date_to:
        ref_day = (utcnow() - timedelta(days=30)).replace(hour=6, minute=0, second=0, microsecond=0)
        date_from = date_from or ref_day
        date_to = date_to or utcnow()
    result = wms_svc.shipment_classification_report(db, date_from, date_to, group_by)
    result.update({"date_from": date_from.isoformat(), "date_to": date_to.isoformat()})
    return result


# ---- Báo cáo tổng lít xuất theo (ngày, loại bia) trong 1 kỳ tùy chọn — trong đó gồm bao
# nhiêu cận date/gửi, cột cuối tự trừ bia gửi ra khỏi tổng (Thực xuất = Tổng lít - Gửi) ----
@router.get("/shipment-net-liters-report")
def shipment_net_liters_report(date_from: datetime = None, date_to: datetime = None,
                               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import wms as wms_svc
    if not date_from or not date_to:
        ref_day = (utcnow() - timedelta(days=30)).replace(hour=6, minute=0, second=0, microsecond=0)
        date_from = date_from or ref_day
        date_to = date_to or utcnow()
    result = wms_svc.shipment_net_liters_report(db, date_from, date_to)
    result.update({"date_from": date_from.isoformat(), "date_to": date_to.isoformat()})
    return result


# ---- Báo cáo lượt xe & tải trọng / tổng hợp bia gửi / định mức nhiên liệu ----
def _default_report_range(date_from, date_to, days=30):
    if not date_from or not date_to:
        ref_day = (utcnow() - timedelta(days=days)).replace(hour=6, minute=0, second=0, microsecond=0)
        date_from = date_from or ref_day
        date_to = date_to or utcnow()
    return date_from, date_to


@router.get("/vehicle-trip-report")
def vehicle_trip_report(date_from: datetime = None, date_to: datetime = None,
                        db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import wms as wms_svc
    date_from, date_to = _default_report_range(date_from, date_to)
    return {"date_from": date_from.isoformat(), "date_to": date_to.isoformat(),
            "rows": wms_svc.vehicle_trip_report(db, date_from, date_to)}


@router.get("/consigned-summary-report")
def consigned_summary_report(date_from: datetime = None, date_to: datetime = None,
                             db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import wms as wms_svc
    date_from, date_to = _default_report_range(date_from, date_to)
    return {"date_from": date_from.isoformat(), "date_to": date_to.isoformat(),
            "rows": wms_svc.consigned_summary_report(db, date_from, date_to)}


@router.get("/fuel-efficiency-report")
def fuel_efficiency_report(date_from: datetime = None, date_to: datetime = None,
                           db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import wms as wms_svc
    date_from, date_to = _default_report_range(date_from, date_to)
    return {"date_from": date_from.isoformat(), "date_to": date_to.isoformat(),
            "rows": wms_svc.fuel_efficiency_report(db, date_from, date_to)}


@router.get("/low-yield-filter-alerts")
def low_yield_filter_alerts(days: int = 5, limit: int = 5, db: Session = Depends(get_db),
                            user: User = Depends(get_current_user)):
    from ..services import dashboard as dashboard_svc
    return dashboard_svc.low_yield_filter_alerts(db, days, limit)


@router.get("/bottled-not-approved")
def bottled_not_approved(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import dashboard as dashboard_svc
    return dashboard_svc.bottled_not_approved_report(db)


# ---- Báo cáo tồn kho thành phẩm theo tuổi lô (cho khối kinh doanh đẩy nhanh bán hàng) ----
@router.get("/inventory-aging")
def inventory_aging(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import ops_setting as ops_setting_svc
    from ..services import wms as wms_svc
    settings = ops_setting_svc.get_settings(db)
    return wms_svc.lot_aging_report(db, settings.aging_caution_days, settings.aging_warning_days,
                                    settings.aging_critical_days)


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


# ---- Báo cáo Nhập-Xuất-Tồn kho thành phẩm (theo mẫu Excel NXT KHO THANH PHAM) ----
@router.get("/finished-goods-stock-report")
def finished_goods_stock_report(date_from: datetime = None, date_to: datetime = None, product_ids: str = None,
                                db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import ops_setting as ops_setting_svc
    from ..services import wms as wms_svc
    if not date_from or not date_to:
        date_to = date_to or utcnow()
        date_from = date_from or (date_to - timedelta(days=7))
    settings = ops_setting_svc.get_settings(db)
    ids = [p for p in product_ids.split(",") if p] if product_ids else None
    result = wms_svc.finished_goods_stock_inout_report(db, date_from, date_to,
                                                       settings.finished_goods_restock_days, ids)
    result.update({"date_from": date_from.isoformat(), "date_to": date_to.isoformat(),
                   "restock_days": settings.finished_goods_restock_days,
                   "days_of_stock_critical_days": settings.fg_days_of_stock_critical_days,
                   "days_in_stock_warning_days": settings.fg_days_in_stock_warning_days})
    return result
