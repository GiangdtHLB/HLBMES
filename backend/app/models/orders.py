"""Production order. SoR thực tế là ERP; MES nhận bản release để thực thi
và không sửa thông tin tài chính (tài liệu §5.2)."""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..common import new_id, utcnow
from ..database import Base


class ProductionOrder(Base):
    __tablename__ = "production_order"

    order_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    order_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("product.product_id"))
    planned_qty: Mapped[float] = mapped_column(Float)
    uom: Mapped[str] = mapped_column(String(255), default="L")
    due_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=5)
    # released = sẵn sàng dispatch; in_progress = đã tạo batch; completed; cancelled
    status: Mapped[str] = mapped_column(String(255), default="released")
    source_version: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # version từ ERP
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
