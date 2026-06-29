"""WMS — kho thành phẩm: vị trí (location) + pallet + case (thùng), có barcode.

Phân cấp đóng gói: Pallet chứa nhiều Case; mỗi Case chứa N đơn vị (lon/chai). Pallet
đặt tại một WmsLocation. pallet_code/case_code in được mã vạch Code39 cho đầu đọc cầm tay.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..common import new_id, utcnow
from ..database import Base


class WmsLocation(Base):
    __tablename__ = "wms_location"

    loc_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    zone: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    kind: Mapped[str] = mapped_column(String(255), default="bin")     # bin | staging | cold | dock
    capacity: Mapped[int] = mapped_column(Integer, default=10)   # số pallet tối đa
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Pallet(Base):
    __tablename__ = "pallet"

    pallet_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    pallet_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    product: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    lot_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    case_count: Mapped[int] = mapped_column(Integer, default=0)
    units_per_case: Mapped[int] = mapped_column(Integer, default=24)
    status: Mapped[str] = mapped_column(String(255), default="building", index=True)  # building|stored|shipped
    location_id: Mapped[Optional[str]] = mapped_column(ForeignKey("wms_location.loc_id"), nullable=True, index=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Case(Base):
    __tablename__ = "wms_case"

    case_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    case_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    pallet_id: Mapped[str] = mapped_column(ForeignKey("pallet.pallet_id"), index=True)
    product: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    units: Mapped[float] = mapped_column(Float, default=24)
    lot_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
