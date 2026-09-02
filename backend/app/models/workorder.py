"""Lệnh sản xuất (Work Order) & điều độ (tài liệu §7.1).

Phân tầng: BrewOrder (Lệnh nấu, đã chọn Loại bia/Version/BOM) → WorkOrder (điều độ
xuống xưởng theo line/ca/ngày) → BrewRecord/BrewBatch (thực thi, "Phát mẻ" — xem
services/workorders.py::dispatch). WO có kế hoạch ngày/ca, trạng thái, và planned
vs actual (gộp từ các mẻ liên kết).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import UnicodeText, Date, Float, ForeignKey, Integer, Unicode
from sqlalchemy.orm import Mapped, mapped_column

from ..common import UTCDateTime, WorkOrderState, new_id, utcnow
from ..database import Base


class WorkOrder(Base):
    __tablename__ = "work_order"

    wo_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    wo_code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    brew_order_id: Mapped[str] = mapped_column(ForeignKey("brew_order.brew_order_id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("product.product_id"))
    recipe_version_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("recipe_version.version_id"), nullable=True)  # recipe mục tiêu để dispatch

    planned_qty: Mapped[float] = mapped_column(Float)
    uom: Mapped[str] = mapped_column(Unicode(255), default="L")
    line: Mapped[Optional[str]] = mapped_column(Unicode(255), index=True)   # Khu vực (phân quyền tài khoản) — KHÔNG phải dây chuyền nấu thật
    # Dây chuyền nấu THẬT (ProductionLine kind="brewhouse") — chọn ngay lúc lập lệnh điều độ
    # (không còn chọn lại lúc "Phát mẻ", xem services/workorders.py::dispatch).
    brewhouse_line_id: Mapped[Optional[str]] = mapped_column(ForeignKey("production_line.line_id"), index=True)
    shift: Mapped[Optional[str]] = mapped_column(Unicode(255), default="A")  # ca A/B/C
    scheduled_date: Mapped[datetime] = mapped_column(Date, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=5)
    status: Mapped[str] = mapped_column(Unicode(255), default=WorkOrderState.PLANNED.value, index=True)
    note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
