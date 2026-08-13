"""Sự kiện dừng máy (downtime) cho reason-tree + Pareto + MTBF/MTTR (§7.7).

Cây lý do (reason-tree) từng là hằng số REASON_TREE trong services/downtime.py, nay chuyển
sang OeeReasonCatalog (theo dây chuyền, có target %, khớp đúng cấu trúc OPI thật của nhà máy —
xem file OPI Excel gốc: 8 nhóm Bảo trì ngoài/NONA/Dừng có kế hoạch/Chuyển máy/Dừng NVL/
Breakdown/Dừng lắt nhắt/SP lỗi). DowntimeEvent gắn reason_catalog_id để phân tích Pareto/
waterfall theo tháng (services/oee_waterfall.py) và 6 big losses cũ. Sự cố (breakdown) đủ
nghiêm trọng có thể gắn thêm OeeRcfa (phân tích nguyên nhân gốc + 5 Whys). OeeMinorStopTally
đếm SỐ LẦN xảy ra các lỗi dừng lắt nhắt cố định theo tuần (khác "Dừng lắt nhắt" ở waterfall —
đó là phút RESIDUAL không giải trình được bằng lý do cụ thể nào, còn tally này đếm số lần theo
nguyên nhân cụ thể để ưu tiên khắc phục, mirror sheet MS&SL). MTBF/MTTR suy ra từ DowntimeEvent
+ Incident theo thiết bị.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, UnicodeText, Boolean, Float, ForeignKey, Integer, Unicode, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..common import UTCDateTime, new_id, utcnow
from ..database import Base


class OeeReasonCatalog(Base):
    """Danh mục lý do dừng máy 2 cấp + target % theo dây chuyền (thay REASON_TREE hardcode)."""

    __tablename__ = "oee_reason_catalog"

    reason_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    # null = áp dụng mọi dây chuyền (dùng khi 1 lý do chung, vd "Mất điện" giống nhau mọi line)
    line_code: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True, index=True)
    # bao_tri_ngoai|nona|ke_hoach|chuyen_may|thieu_vat_tu|breakdown|dung_lat_nhat|sp_loi
    category: Mapped[str] = mapped_column(Unicode(64), index=True)
    sub_code: Mapped[str] = mapped_column(Unicode(64))
    sub_label: Mapped[str] = mapped_column(Unicode(255))
    # Chỉ dùng cho category="breakdown" — vị trí máy cụ thể (Dỡ lon/Băng tải/Chiết...)
    machine_position: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    target_pct: Mapped[float] = mapped_column(Float, default=0.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (UniqueConstraint("line_code", "category", "sub_code", name="uq_oee_reason_line_cat_sub"),)


class OeeRcfa(Base):
    """RCFA (Root Cause Failure Analysis) + 5 Whys — mirror sheet RCFA/5Whys của file OPI gốc."""

    __tablename__ = "oee_rcfa"

    rcfa_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    rcfa_no: Mapped[str] = mapped_column(Unicode(32), unique=True)
    line_code: Mapped[str] = mapped_column(Unicode(64), index=True)
    machine: Mapped[str] = mapped_column(Unicode(255))
    part: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    stop_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    duration_min: Mapped[float] = mapped_column(Float, default=0.0)
    failure_function: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    prior_signs: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    technician: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    repair_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    wait_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    replaced_parts: Mapped[list] = mapped_column(JSON, default=list)
    working_principle: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    failure_mechanism: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    analyst: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    factor: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    # [{level: 1..5, text, category}] — category thuộc tập cố định sheet 5Whys (qua_tai|
    # hu_hong_theo_thoi_gian|hong_dot_ngot|ap_luc_tang_dan|dieu_kien_co_ban|dieu_kien_van_hanh|
    # hu_hong_do_quen|diem_yeu_thiet_ke|loi_tho_van_hanh|loi_tho_bao_duong)
    five_whys: Mapped[list] = mapped_column(JSON, default=list)
    category_4m1e: Mapped[Optional[str]] = mapped_column(Unicode(32), nullable=True)  # method|material|machine|man
    corrective_action: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    preventive_action: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    executor: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    complete_date: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    checker: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    # [{week_offset: 1..12, checked: bool, checked_at, note}] — mirror "W+1..W+12"
    recheck_schedule: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class OeeMinorStopTally(Base):
    """Đếm số lần dừng lắt nhắt theo tuần/ca cho từng nguyên nhân cố định — mirror sheet MS&SL."""

    __tablename__ = "oee_minor_stop_tally"

    tally_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    reason_id: Mapped[str] = mapped_column(ForeignKey("oee_reason_catalog.reason_id"), index=True)
    iso_year: Mapped[int] = mapped_column(Integer, index=True)
    iso_week: Mapped[int] = mapped_column(Integer)
    shift: Mapped[str] = mapped_column(Unicode(16))
    count: Mapped[int] = mapped_column(Integer, default=0)
    updated_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    __table_args__ = (UniqueConstraint("reason_id", "iso_year", "iso_week", "shift", name="uq_oee_minor_stop_slot"),)


class DowntimeEvent(Base):
    __tablename__ = "downtime_event"

    event_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    line: Mapped[str] = mapped_column(Unicode(255), index=True)
    equipment_id: Mapped[Optional[str]] = mapped_column(ForeignKey("equipment.equipment_id"), nullable=True, index=True)
    shift: Mapped[str] = mapped_column(Unicode(255), default="A")
    shift_date: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    # Nhóm/nhãn suy ra từ OeeReasonCatalog tại thời điểm ghi (giữ 2 cột này để Pareto/6-big-
    # losses cũ không cần đổi schema) — nguồn sự thật là reason_catalog_id bên dưới.
    reason_group: Mapped[str] = mapped_column(Unicode(255), index=True)
    reason_code: Mapped[str] = mapped_column(Unicode(64), index=True)
    reason_label: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    reason_catalog_id: Mapped[Optional[str]] = mapped_column(ForeignKey("oee_reason_catalog.reason_id"), nullable=True, index=True)
    # Phân loại 6 big losses (availability/performance/quality loss)
    loss_category: Mapped[str] = mapped_column(Unicode(255), default="availability")
    minutes: Mapped[float] = mapped_column(Float, default=0.0)
    start_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    end_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    # Chỉ dùng khi reason_catalog.category="breakdown"
    error_code: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    rcfa_id: Mapped[Optional[str]] = mapped_column(ForeignKey("oee_rcfa.rcfa_id"), nullable=True, index=True)
    repair_start_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    repair_end_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    repaired_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    corrective_action: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    # {"co_dien": {"by":.., "at":..}, "quan_doc_pxsx": {...}, "quan_doc_pxcd": {...}}
    confirmations: Mapped[dict] = mapped_column(JSON, default=dict)
    note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    recorded_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
