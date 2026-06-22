"""BatchExecution — nguồn chuẩn (SoR) cho trạng thái thực thi cấp nhà máy
(tài liệu §5.2). Snapshot recipe bất biến tại thời điểm release."""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..common import BatchState, QualityStatus, new_id, utcnow
from ..database import Base


class BatchExecution(Base):
    __tablename__ = "batch_execution"

    batch_id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    batch_code: Mapped[str] = mapped_column(String, unique=True, index=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("production_order.order_id"), index=True)
    work_order_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    recipe_version_id: Mapped[str] = mapped_column(ForeignKey("recipe_version.version_id"))
    product_id: Mapped[str] = mapped_column(ForeignKey("product.product_id"))

    state: Mapped[str] = mapped_column(String, default=BatchState.PLANNED.value)
    quality_status: Mapped[str] = mapped_column(String, default=QualityStatus.PENDING.value)

    planned_qty: Mapped[float] = mapped_column(Float)
    actual_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    uom: Mapped[str] = mapped_column(String, default="L")

    # Snapshot bất biến của recipe version tại thời điểm release (parameters/materials/checks).
    recipe_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    # Ghi nhận actual: list[{name, target, actual, unit, phase, recorded_by, recorded_at}]
    actuals: Mapped[list] = mapped_column(JSON, default=list)

    start_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Khóa hồ sơ EBR: sau khi khóa, mẻ bất biến (chỉ amendment) — tài liệu §7.6.
    ebr_locked: Mapped[bool] = mapped_column(Boolean, default=False)

    # Optimistic concurrency + audit (tài liệu Phụ lục C).
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
