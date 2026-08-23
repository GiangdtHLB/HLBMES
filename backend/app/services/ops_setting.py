"""Cài đặt vận hành toàn hệ thống (hiện chỉ có ngưỡng dung sai thể tích cho "Làm rỗng" tank
CCT/BBT) — 1 dòng duy nhất, tạo sẵn bởi migration; get_settings tự tạo nếu vì lý do nào đó
chưa có dòng nào (phòng hờ, không nên xảy ra trong vận hành bình thường)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..common import new_id, utcnow
from ..models.brewing import OpsSetting
from ..security import User


def get_settings(db: Session) -> OpsSetting:
    s = db.execute(select(OpsSetting)).scalars().first()
    if not s:
        s = OpsSetting(setting_id=new_id(), empty_cct_tolerance_hl=2.0, empty_bbt_tolerance_hl=2.0,
                       aging_caution_days=30.0, aging_warning_days=60.0, aging_critical_days=90.0,
                       filter_yield_low_hl=50.0, filter_yield_high_hl=150.0,
                       filter_line_yield_low_l=500.0, filter_line_yield_high_l=2000.0,
                       finished_goods_restock_days=7.0, fg_days_of_stock_critical_days=3.0,
                       fg_days_in_stock_warning_days=30.0,
                       finished_goods_receive_max_backdate_days=15.0, fg_day_cutoff_hour=0,
                       erp_order_volume_tolerance_hl=5.0)
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


def update_settings(db: Session, empty_cct_tolerance_hl: float, empty_bbt_tolerance_hl: float,
                    aging_caution_days: float, aging_warning_days: float, aging_critical_days: float,
                    user: User, factory_code: str = None,
                    filter_yield_low_hl: float = 50.0, filter_yield_high_hl: float = 150.0,
                    filter_line_yield_low_l: float = 500.0, filter_line_yield_high_l: float = 2000.0,
                    finished_goods_restock_days: float = 7.0,
                    fg_days_of_stock_critical_days: float = 3.0,
                    fg_days_in_stock_warning_days: float = 30.0,
                    finished_goods_receive_max_backdate_days: float = 15.0,
                    fg_day_cutoff_hour: int = 0,
                    erp_order_volume_tolerance_hl: float = 5.0) -> OpsSetting:
    s = get_settings(db)
    s.empty_cct_tolerance_hl = empty_cct_tolerance_hl
    s.empty_bbt_tolerance_hl = empty_bbt_tolerance_hl
    s.aging_caution_days = aging_caution_days
    s.aging_warning_days = aging_warning_days
    s.aging_critical_days = aging_critical_days
    s.filter_yield_low_hl = filter_yield_low_hl
    s.filter_yield_high_hl = filter_yield_high_hl
    s.filter_line_yield_low_l = filter_line_yield_low_l
    s.filter_line_yield_high_l = filter_line_yield_high_l
    s.finished_goods_restock_days = finished_goods_restock_days
    s.fg_days_of_stock_critical_days = fg_days_of_stock_critical_days
    s.fg_days_in_stock_warning_days = fg_days_in_stock_warning_days
    s.finished_goods_receive_max_backdate_days = finished_goods_receive_max_backdate_days
    s.fg_day_cutoff_hour = fg_day_cutoff_hour
    s.factory_code = factory_code
    s.erp_order_volume_tolerance_hl = erp_order_volume_tolerance_hl
    s.updated_by = user.username
    s.updated_at = utcnow()
    db.commit()
    db.refresh(s)
    return s
