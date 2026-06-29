"""Lệnh sản xuất (Work Order) & điều độ (tài liệu §7.1).

Phân tầng: ProductionOrder (nhận từ ERP) → WorkOrder (điều độ xuống xưởng theo
line/ca/ngày) → BatchExecution (thực thi). WO có kế hoạch ngày/ca, trạng thái,
và planned vs actual (gộp từ các mẻ liên kết).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Text, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..common import WorkOrderState, new_id, utcnow
from ..database import Base


class WorkOrder(Base):
    __tablename__ = "work_order"

    wo_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    wo_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    production_order_id: Mapped[str] = mapped_column(ForeignKey("production_order.order_id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("product.product_id"))
    recipe_version_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("recipe_version.version_id"), nullable=True)  # recipe mục tiêu để dispatch

    planned_qty: Mapped[float] = mapped_column(Float)
    uom: Mapped[str] = mapped_column(String(255), default="L")
    line: Mapped[Optional[str]] = mapped_column(String(255), index=True)   # dây chuyền/khu
    shift: Mapped[Optional[str]] = mapped_column(String(255), default="A")  # ca A/B/C
    scheduled_date: Mapped[datetime] = mapped_column(Date, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=5)
    status: Mapped[str] = mapped_column(String(255), default=WorkOrderState.PLANNED.value, index=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
