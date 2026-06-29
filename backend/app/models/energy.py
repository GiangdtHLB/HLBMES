"""Năng lượng: nhóm (điện/nước/hơi/khí nén...), khu, và số đọc hàng ngày.

Tổng hợp tháng được tính từ reading ngày (không lưu trùng)."""

from datetime import datetime
from typing import Optional

from sqlalchemy import UnicodeText, Date, DateTime, Float, ForeignKey, Unicode, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..common import new_id, utcnow
from ..database import Base


class EnergyGroup(Base):
    __tablename__ = "energy_group"

    group_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(Unicode(255))
    unit: Mapped[str] = mapped_column(Unicode(255), default="kWh")


class EnergyArea(Base):
    __tablename__ = "energy_area"

    area_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(Unicode(255))


class EnergyReading(Base):
    __tablename__ = "energy_reading"
    __table_args__ = (UniqueConstraint("day", "group_id", "area_id", name="uq_energy_daily"),)

    reading_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    day: Mapped[datetime] = mapped_column(Date, index=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("energy_group.group_id"), index=True)
    area_id: Mapped[Optional[str]] = mapped_column(ForeignKey("energy_area.area_id"), nullable=True)
    value: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
