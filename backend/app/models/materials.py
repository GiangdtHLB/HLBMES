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


class MaterialLocation(Base):
    """Vị trí cất trong Kho công ty (kho nguyên vật liệu) — danh mục khai báo trước, gán vào
    từng lô lúc nhập kho (xem services/warehouse.py::receive, bắt buộc chọn khi tạo lô mới) và
    có thể đổi sang vị trí khác trong quá trình làm việc (xem relocate_lot). Cố tình không có
    trường capacity/kind như WmsLocation (kho thành phẩm) — vật tư NVL rất khác đơn vị tính
    (kg/lít/cái...) nên không quy đổi chung 1 sức chứa số được, đây chỉ là nhãn vị trí vật lý."""
    __tablename__ = "material_location"

    loc_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(Unicode(255))
    zone: Mapped[Optional[str]] = mapped_column(Unicode(120), nullable=True)
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
    # Vị trí cất CỤ THỂ trong Kho công ty (xem MaterialLocation) — khác `location` ở trên vốn
    # chỉ là nhãn TẦNG kho (Kho công ty/Kho phân xưởng/Nhà máy khác, dạng chuỗi tự do dùng để
    # phân quyền/lọc báo cáo). Nullable vì lô ở Kho phân xưởng/Nhà máy khác không dùng vị trí
    # này (chưa có danh mục vị trí riêng cho phân xưởng); bắt buộc khi tạo lô mới tại Kho công
    # ty (xem receive()).
    location_id: Mapped[Optional[str]] = mapped_column(ForeignKey("material_location.loc_id"), nullable=True, index=True)
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
