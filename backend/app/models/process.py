"""Nấu-Lọc-Chiết + Thu hồi men (tài liệu §4, §7.4).

- ChemicalUsage: hóa chất dùng theo công đoạn của mẻ.
- YeastLot: lô men thu hồi (strain, generation, viability...).
- YeastIssue: lịch sử xuất men thu hồi xuống mẻ.
Thông tin các công đoạn nấu/lên men/lọc/chiết tổng hợp từ readings/actuals/QC
sẵn có của mẻ (không tạo bảng trùng lặp).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..common import new_id, utcnow
from ..database import Base


class ChemicalUsage(Base):
    __tablename__ = "chemical_usage"

    usage_id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    batch_id: Mapped[Optional[str]] = mapped_column(ForeignKey("batch_execution.batch_id"), index=True)
    stage: Mapped[str] = mapped_column(String, default="nau")  # nau/len_men/loc/chiet/cip
    chemical: Mapped[str] = mapped_column(String)
    quantity: Mapped[float] = mapped_column(Float)
    uom: Mapped[str] = mapped_column(String, default="kg")
    note: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class YeastLot(Base):
    __tablename__ = "yeast_lot"

    yeast_lot_id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String, unique=True, index=True)
    strain: Mapped[str] = mapped_column(String, default="W-34/70")
    generation: Mapped[int] = mapped_column(Integer, default=1)
    source_tank: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_batch_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    uom: Mapped[str] = mapped_column(String, default="L")
    viability: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # % sống
    vitality: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String, default="available")  # available/used/discarded
    harvest_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class YeastIssue(Base):
    __tablename__ = "yeast_issue"

    issue_id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    yeast_lot_id: Mapped[str] = mapped_column(ForeignKey("yeast_lot.yeast_lot_id"), index=True)
    batch_id: Mapped[Optional[str]] = mapped_column(ForeignKey("batch_execution.batch_id"), index=True)
    quantity: Mapped[float] = mapped_column(Float)
    uom: Mapped[str] = mapped_column(String, default="L")
    actor: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
