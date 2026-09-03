"""Cấp phát nguyên liệu (dispense/backflush) — tài liệu §7.4, §7.6.

- Dispense: phiếu cấp liệu cho một mẻ (header), gom các dòng cấp theo lô cụ thể.
- DispenseLine: một dòng = một lô NVL cấp vào mẻ, gắn với genealogy edge consume.
- MaterialQcGroup: gán nhóm chỉ tiêu chất lượng (quality_ext.QCParameterGroup) cho một
  nguyên liệu — chỉ nguyên liệu có gán mới bị cổng nhập kho bắt buộc khai báo/duyệt QC.

Việc trừ tồn lô + tạo genealogy + chặn vượt định mức tái dùng batches.consume_lot.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, UnicodeText, Float, ForeignKey, Unicode
from sqlalchemy.orm import Mapped, mapped_column

from ..common import UTCDateTime, new_id, utcnow
from ..database import Base


class Dispense(Base):
    __tablename__ = "dispense"

    dispense_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    dispense_code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batch_execution.batch_id"), index=True)
    mode: Mapped[str] = mapped_column(Unicode(255), default="dispense")   # dispense | backflush
    status: Mapped[str] = mapped_column(Unicode(255), default="issued")   # issued (đã trừ tồn)
    note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class DispenseLine(Base):
    __tablename__ = "dispense_line"

    line_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    dispense_id: Mapped[str] = mapped_column(ForeignKey("dispense.dispense_id"), index=True)
    material_code: Mapped[str] = mapped_column(Unicode(64), index=True)
    lot_id: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    lot_code: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    uom: Mapped[str] = mapped_column(Unicode(255), default="kg")
    # fifo_ok=False khi người dùng chọn lô KHÁC lô FIFO/FEFO gợi ý — bắt buộc có `reason` lúc đó
    # (xem services/dispense.py::_plan_consume) để truy vết tại sao chọn lệch FIFO.
    fifo_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    reason: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class MaterialQcGroup(Base):
    __tablename__ = "material_qc_group"

    link_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    material_id: Mapped[str] = mapped_column(ForeignKey("material.material_id"), index=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("qc_parameter_group.group_id"), index=True)
    mandatory: Mapped[bool] = mapped_column(default=True)
    active: Mapped[bool] = mapped_column(default=True)
