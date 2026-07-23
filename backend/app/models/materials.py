"""MaterialLot + GenealogyEdge — truy xuất nguồn gốc (tài liệu §7.6, §8.2).

GenealogyEdge là cạnh có hướng trong đồ thị phả hệ; mọi consume/produce/
split/merge/transfer tạo một cạnh có timestamp, quantity, source/destination.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Float, ForeignKey, Integer, Unicode, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..common import GenealogyRelation, LotStatus, UTCDateTime, new_id, utcnow
from ..database import Base


class Supplier(Base):
    """Danh mục nhà cung cấp — gắn vào lô NVL lúc nhập kho để biết nguồn gốc."""
    __tablename__ = "supplier"

    supplier_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(Unicode(255))
    address: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    contact: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class MaterialLot(Base):
    __tablename__ = "material_lot"
    # Mã lô do phần mềm tự sinh tăng dần theo năm (VD 2026-00001) — năm sau đánh lại từ 1,
    # nên khóa duy nhất phải gồm cả lot_year, không chỉ lot_code (mirror BrewBatch.batch_year).
    __table_args__ = (UniqueConstraint("lot_year", "lot_code", name="uq_material_lot_year_code"),)

    lot_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    lot_code: Mapped[str] = mapped_column(Unicode(64), index=True)
    lot_year: Mapped[int] = mapped_column(Integer, index=True)  # năm nhập — phạm vi reset số lô
    # Lô có thể là nguyên liệu (material_id) hoặc thành phẩm/bán thành phẩm (product_id).
    material_id: Mapped[Optional[str]] = mapped_column(ForeignKey("material.material_id"), nullable=True)
    product_id: Mapped[Optional[str]] = mapped_column(ForeignKey("product.product_id"), nullable=True)
    lot_type: Mapped[str] = mapped_column(Unicode(255), default="material")  # material | brew | package ...

    supplier_lot: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    supplier_id: Mapped[Optional[str]] = mapped_column(ForeignKey("supplier.supplier_id"), nullable=True)
    kcs_lot_no: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)  # số lô do KCS tự điền khi khai báo chỉ tiêu
    unit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    uom: Mapped[str] = mapped_column(Unicode(255), default="kg")
    status: Mapped[str] = mapped_column(Unicode(255), default=LotStatus.AVAILABLE.value)
    expiry: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    location: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class GenealogyEdge(Base):
    __tablename__ = "genealogy_edge"

    edge_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    # node được biểu diễn bằng (type, id): type ∈ {lot, batch}
    from_type: Mapped[str] = mapped_column(Unicode(255))
    from_id: Mapped[str] = mapped_column(Unicode(64), index=True)
    to_type: Mapped[str] = mapped_column(Unicode(255))
    to_id: Mapped[str] = mapped_column(Unicode(64), index=True)
    relation: Mapped[str] = mapped_column(Unicode(255), default=GenealogyRelation.CONSUME.value)
    quantity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    uom: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    source_event: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    event_time: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
