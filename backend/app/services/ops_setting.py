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
                       aging_caution_days=30.0, aging_warning_days=60.0, aging_critical_days=90.0)
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


def update_settings(db: Session, empty_cct_tolerance_hl: float, empty_bbt_tolerance_hl: float,
                    aging_caution_days: float, aging_warning_days: float, aging_critical_days: float,
                    user: User, factory_code: str = None) -> OpsSetting:
    s = get_settings(db)
    s.empty_cct_tolerance_hl = empty_cct_tolerance_hl
    s.empty_bbt_tolerance_hl = empty_bbt_tolerance_hl
    s.aging_caution_days = aging_caution_days
    s.aging_warning_days = aging_warning_days
    s.aging_critical_days = aging_critical_days
    s.factory_code = factory_code
    s.updated_by = user.username
    s.updated_at = utcnow()
    db.commit()
    db.refresh(s)
    return s
