"""QualityResult + Deviation (tài liệu §7.5, §8.2).

Một kết quả chỉ có một SoR; pass/fail tính theo limit số học chứ không
phải text tùy ý. Deviation có workflow và liên kết tới batch/lot."""

from datetime import datetime
from typing import Optional

from sqlalchemy import UnicodeText, Float, Unicode
from sqlalchemy.orm import Mapped, mapped_column

from ..common import DeviationState, ResultStatus, UTCDateTime, new_id, utcnow
from ..database import Base


class QualityResult(Base):
    __tablename__ = "quality_result"

    result_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    sample_id: Mapped[str] = mapped_column(Unicode(64), index=True)
    # phạm vi: scope_type ∈ {batch, lot}, scope_id trỏ tới batch_id/lot_id
    scope_type: Mapped[str] = mapped_column(Unicode(255), default="batch")
    scope_id: Mapped[str] = mapped_column(Unicode(64), index=True)

    parameter: Mapped[str] = mapped_column(Unicode(255))
    method: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    instrument: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Giá trị in trên bao bì/CA của nhà cung cấp — khác `value` (nhà máy tự đo); chỉ mang tính
    # tham khảo/báo cáo, KHÔNG dùng để tính `status` (pass/fail vẫn chỉ theo `value` vs limit).
    ca_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    lower_limit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    upper_limit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(Unicode(255), default=ResultStatus.PENDING.value)

    recorded_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Deviation(Base):
    __tablename__ = "deviation"

    deviation_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    deviation_code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    scope_type: Mapped[str] = mapped_column(Unicode(255), default="batch")
    scope_id: Mapped[str] = mapped_column(Unicode(64), index=True)
    severity: Mapped[str] = mapped_column(Unicode(255), default="minor")  # minor/major/critical
    reason: Mapped[str] = mapped_column(UnicodeText)
    state: Mapped[str] = mapped_column(Unicode(255), default=DeviationState.OPEN.value)
    investigation: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    disposition: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    opened_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    closed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
