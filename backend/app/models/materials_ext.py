"""Cấp phát nguyên liệu (dispense/backflush) — tài liệu §7.4, §7.6.

- Dispense: phiếu cấp liệu cho một mẻ (header), gom các dòng cấp theo lô cụ thể.
- DispenseLine: một dòng = một lô NVL cấp vào mẻ, gắn với genealogy edge consume.

Việc trừ tồn lô + tạo genealogy + chặn vượt định mức tái dùng batches.consume_lot.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Text, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ..common import new_id, utcnow
from ..database import Base


class Dispense(Base):
    __tablename__ = "dispense"

    dispense_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    dispense_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batch_execution.batch_id"), index=True)
    mode: Mapped[str] = mapped_column(String(255), default="dispense")   # dispense | backflush
    status: Mapped[str] = mapped_column(String(255), default="issued")   # issued (đã trừ tồn)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DispenseLine(Base):
    __tablename__ = "dispense_line"

    line_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    dispense_id: Mapped[str] = mapped_column(ForeignKey("dispense.dispense_id"), index=True)
    material_code: Mapped[str] = mapped_column(String(64), index=True)
    lot_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    lot_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    uom: Mapped[str] = mapped_column(String(255), default="kg")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
