"""Kho NVL: sổ cái dịch chuyển kho (StockMovement) trên nền MaterialLot.

MaterialLot giữ tồn hiện tại; StockMovement là ledger bất biến mọi nhập/xuất/
hoàn/sang ngang để dựng thẻ kho và báo cáo nhập-xuất-tồn (tài liệu §7.4, §8.1).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ..common import new_id, utcnow
from ..database import Base


class StockMovement(Base):
    __tablename__ = "stock_movement"

    movement_id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    # receipt=nhập | issue=xuất | return=nhập hoàn | transfer=xuất sang ngang | adjust
    movement_type: Mapped[str] = mapped_column(String, index=True)
    material_id: Mapped[Optional[str]] = mapped_column(ForeignKey("material.material_id"), index=True)
    lot_id: Mapped[Optional[str]] = mapped_column(ForeignKey("material_lot.lot_id"), index=True)
    lot_code: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    quantity: Mapped[float] = mapped_column(Float)        # luôn dương; dấu suy từ type
    uom: Mapped[str] = mapped_column(String, default="kg")
    location_from: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    location_to: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    mode: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # de_nghi | tu_do | sang_ngang
    reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    ref_doc: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    actor: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
