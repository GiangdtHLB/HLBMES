"""Production order. SoR thực tế là ERP; MES nhận bản release để thực thi
và không sửa thông tin tài chính (tài liệu §5.2)."""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, Unicode, UnicodeText
from sqlalchemy.orm import Mapped, mapped_column

from ..common import UTCDateTime, new_id, utcnow
from ..database import Base


class ProductionOrder(Base):
    __tablename__ = "production_order"

    order_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    order_code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("product.product_id"))
    planned_qty: Mapped[float] = mapped_column(Float)
    uom: Mapped[str] = mapped_column(Unicode(255), default="L")
    due_time: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=5)
    # released = sẵn sàng dispatch; in_progress = đã tạo batch; completed; cancelled
    status: Mapped[str] = mapped_column(Unicode(255), default="released")
    source_version: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)  # version từ ERP
    # Công thức (BOM) người lập CHỌN dùng cho lệnh này — mirror brew_order.recipe_version_id,
    # KHÔNG tự suy ra từ product_id (1 sản phẩm có thể có nhiều version, chỉ 1 đang effective
    # tại 1 thời điểm nhưng model không cấm 2 version effective song song).
    recipe_version_id: Mapped[Optional[str]] = mapped_column(ForeignKey("recipe_version.version_id"), nullable=True, index=True)
    # Số mẻ kế hoạch — thuần thông tin kế hoạch để chia định mức NVL/mẻ (xem
    # services/orders.py::preview_bom), KHÔNG phải nguồn sự thật cho sản lượng (đó vẫn là
    # planned_qty/uom).
    planned_batch_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Phần hành chính mirror BrewOrder (mẫu giấy "LỆNH SẢN XUẤT KIÊM PHIẾU XUẤT KHO") — 1 Lệnh
    # SX (ERP) = 1 dòng, các trường này nằm thẳng trên chính dòng đó.
    issued_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)          # Người ra lệnh
    executor_unit: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)      # Người thực hiện
    warehouse_keeper: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)   # Người xuất hàng
    reference_note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    start_date: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    end_date: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    safety_note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class ProductionOrderMaterialLine(Base):
    """1 dòng Định mức NVL trong Lệnh SX (ERP) — mirror BrewOrderMaterialLine (snapshot tồn
    kho + SL lấy tại Kho công ty/phân xưởng NGAY LÚC LẬP PHIẾU, đúng tính chất văn bản đã ký/
    in ra). Chỉ có khi lệnh có chọn Công thức (recipe_version_id) — xem services/orders.py."""
    __tablename__ = "production_order_material_line"

    line_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    order_id: Mapped[str] = mapped_column(ForeignKey("production_order.order_id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    stt_label: Mapped[Optional[str]] = mapped_column(Unicode(16), nullable=True)
    is_header: Mapped[bool] = mapped_column(Boolean, default=False)
    material_id: Mapped[Optional[str]] = mapped_column(ForeignKey("material.material_id"), nullable=True)
    material_name: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    material_group_code: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    member_qty_snapshot: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    uom: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    qty_per_batch: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    qty_total: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stock_company_snapshot: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stock_workshop_snapshot: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    qty_from_company: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    qty_from_workshop: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
