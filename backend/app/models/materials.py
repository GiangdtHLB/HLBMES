"""MaterialLot + GenealogyEdge — truy xuất nguồn gốc (tài liệu §7.6, §8.2).

GenealogyEdge là cạnh có hướng trong đồ thị phả hệ; mọi consume/produce/
split/merge/transfer tạo một cạnh có timestamp, quantity, source/destination.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ..common import GenealogyRelation, LotStatus, new_id, utcnow
from ..database import Base


class MaterialLot(Base):
    __tablename__ = "material_lot"

    lot_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    lot_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # Lô có thể là nguyên liệu (material_id) hoặc thành phẩm/bán thành phẩm (product_id).
    material_id: Mapped[Optional[str]] = mapped_column(ForeignKey("material.material_id"), nullable=True)
    product_id: Mapped[Optional[str]] = mapped_column(ForeignKey("product.product_id"), nullable=True)
    lot_type: Mapped[str] = mapped_column(String(255), default="material")  # material | brew | package ...

    supplier_lot: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    uom: Mapped[str] = mapped_column(String(255), default="kg")
    status: Mapped[str] = mapped_column(String(255), default=LotStatus.AVAILABLE.value)
    expiry: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GenealogyEdge(Base):
    __tablename__ = "genealogy_edge"

    edge_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    # node được biểu diễn bằng (type, id): type ∈ {lot, batch}
    from_type: Mapped[str] = mapped_column(String(255))
    from_id: Mapped[str] = mapped_column(String(64), index=True)
    to_type: Mapped[str] = mapped_column(String(255))
    to_id: Mapped[str] = mapped_column(String(64), index=True)
    relation: Mapped[str] = mapped_column(String(255), default=GenealogyRelation.CONSUME.value)
    quantity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    uom: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_event: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
