"""Bảo trì & Kiểm định (CMMS — tài liệu §7.7).

Equipment/SparePart (danh mục), Incident (sự cố), MaintenancePlan (bảo trì/
kiểm tra/tu bổ), Calibration (kiểm định/hiệu chuẩn)."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Text, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..common import new_id, utcnow
from ..database import Base


class Equipment(Base):
    __tablename__ = "equipment"

    equipment_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    eq_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)   # loại thiết bị
    system: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)    # hệ thống
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(255), default="running")  # running/idle/maintenance/broken


class SparePart(Base):
    __tablename__ = "spare_part"

    part_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    uom: Mapped[str] = mapped_column(String(255), default="cái")
    stock: Mapped[float] = mapped_column(Float, default=0.0)
    stock_min: Mapped[float] = mapped_column(Float, default=0.0)


class Incident(Base):
    __tablename__ = "incident"

    incident_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    incident_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    equipment_id: Mapped[Optional[str]] = mapped_column(ForeignKey("equipment.equipment_id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(255), default="minor")  # minor/major/critical
    status: Mapped[str] = mapped_column(String(255), default="open")     # open/in_progress/resolved/closed
    downtime_min: Mapped[float] = mapped_column(Float, default=0.0)
    reported_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    resolution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class MaintenancePlan(Base):
    __tablename__ = "maintenance_plan"

    plan_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    equipment_id: Mapped[str] = mapped_column(ForeignKey("equipment.equipment_id"), index=True)
    plan_type: Mapped[str] = mapped_column(String(255), default="bao_tri")  # bao_tri/kiem_tra/tu_bo
    scheduled_date: Mapped[datetime] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(255), default="planned")     # planned/done/overdue
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    done_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Calibration(Base):
    __tablename__ = "calibration"

    calib_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    equipment_id: Mapped[Optional[str]] = mapped_column(ForeignKey("equipment.equipment_id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    # phong_xa | van_an_toan | hieu_chuan_tbd | yc_nnvat
    calib_type: Mapped[str] = mapped_column(String(255), default="hieu_chuan_tbd")
    last_date: Mapped[Optional[datetime]] = mapped_column(Date, nullable=True)
    due_date: Mapped[datetime] = mapped_column(Date, index=True)
    interval_months: Mapped[int] = mapped_column(Integer, default=12)
    result: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # pass/fail
    status: Mapped[str] = mapped_column(String(255), default="valid")          # valid/due/overdue
