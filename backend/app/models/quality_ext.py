"""Quality hardcore (tài liệu §7.5):

- QCParameter: định nghĩa chỉ tiêu SPC (target + spec limit USL/LSL) để vẽ control
  chart, tính Cp/Cpk, áp luật Western Electric.
- CAPA: hành động khắc phục/phòng ngừa gắn với deviation (workflow open→...→closed).
- Sample: phiếu mẫu LIMS-lite (đăng ký mẫu → chờ test → hoàn thành), gom QualityResult.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import UnicodeText, Date, DateTime, Float, Unicode
from sqlalchemy.orm import Mapped, mapped_column

from ..common import new_id, utcnow
from ..database import Base


class QCParameter(Base):
    __tablename__ = "qc_parameter"

    param_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(Unicode(255))
    unit: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    target: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    usl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # upper spec limit
    lsl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # lower spec limit
    stage: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)  # nau|len_men|loc|chiet
    active: Mapped[bool] = mapped_column(default=True)


class CAPA(Base):
    __tablename__ = "capa"

    capa_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    capa_code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    deviation_id: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True, index=True)
    title: Mapped[str] = mapped_column(Unicode(255))
    capa_type: Mapped[str] = mapped_column(Unicode(255), default="corrective")  # corrective | preventive
    severity: Mapped[str] = mapped_column(Unicode(255), default="minor")
    # open → investigation → action → verification → closed
    state: Mapped[str] = mapped_column(Unicode(255), default="open")
    root_cause: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    action_plan: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    effectiveness: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    owner: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    due_date: Mapped[Optional[datetime]] = mapped_column(Date, nullable=True)
    opened_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    closed_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Sample(Base):
    """Phiếu mẫu LIMS-lite — gom các QualityResult cùng sample_id."""

    __tablename__ = "lims_sample"

    sample_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    sample_code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    scope_type: Mapped[str] = mapped_column(Unicode(255), default="batch")
    scope_id: Mapped[str] = mapped_column(Unicode(64), index=True)
    stage: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    # registered → in_test → completed
    status: Mapped[str] = mapped_column(Unicode(255), default="registered")
    test_set: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)  # csv tên parameter cần test
    registered_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
