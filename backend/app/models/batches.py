"""BatchExecution — nguồn chuẩn (SoR) cho trạng thái thực thi cấp nhà máy
(tài liệu §5.2). Snapshot recipe bất biến tại thời điểm release."""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, Unicode, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..common import BatchState, QualityStatus, UTCDateTime, new_id, utcnow
from ..database import Base


class BatchExecution(Base):
    __tablename__ = "batch_execution"
    # Mã mẻ Braumat (batch_code) unique THEO NĂM (batch_year), không phải toàn hệ thống — mirror
    # đúng quy ước đã áp dụng cho brew_code/lm_code/filter_code/bottle_code (xem
    # b4c5d6e7f8b0_year_scoped_code_uniqueness.py): số reset lại mỗi năm, năm sau dùng lại được
    # số đã dùng năm trước (yêu cầu người dùng 2026-09-02: "khi hết năm thì sẽ tự tính lại từ
    # đầu... còn năm sau sẽ lặp lại được"). Từ nay batch_code BẮT BUỘC là số nguyên dương (xem
    # services/batches.py::create_batch) — dữ liệu cũ (trước ràng buộc này) có thể còn mã dạng
    # chữ, KHÔNG bị ép chuyển đổi ngược, chỉ áp dụng cho bản ghi tạo mới.
    __table_args__ = (UniqueConstraint("batch_year", "batch_code", name="uq_batch_execution_year_code"),)

    batch_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    batch_code: Mapped[str] = mapped_column(Unicode(64), index=True)
    batch_year: Mapped[int] = mapped_column(Integer, index=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("brew_order.brew_order_id"), index=True)
    work_order_id: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True, index=True)
    # Dây chuyền nấu THẬT (ProductionLine kind="brewhouse") — mặc định lấy theo Lệnh SX (điều độ)
    # đã chọn (WorkOrder.brewhouse_line_id) nếu có, nhưng chọn/sửa được độc lập ngay ở "Tạo mẻ"
    # dù không gắn Lệnh SX nào.
    brewhouse_line_id: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True, index=True)
    recipe_version_id: Mapped[str] = mapped_column(ForeignKey("recipe_version.version_id"))
    product_id: Mapped[str] = mapped_column(ForeignKey("product.product_id"))

    state: Mapped[str] = mapped_column(Unicode(255), default=BatchState.PLANNED.value)
    quality_status: Mapped[str] = mapped_column(Unicode(255), default=QualityStatus.PENDING.value)

    planned_qty: Mapped[float] = mapped_column(Float)
    actual_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    uom: Mapped[str] = mapped_column(Unicode(255), default="L")

    # Snapshot bất biến của recipe version tại thời điểm release (parameters/materials/checks).
    recipe_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    # Ghi nhận actual: list[{name, target, actual, unit, phase, recorded_by, recorded_at}]
    actuals: Mapped[list] = mapped_column(JSON, default=list)

    start_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    end_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)

    # Khóa hồ sơ EBR: sau khi khóa, mẻ bất biến (chỉ amendment) — tài liệu §7.6.
    ebr_locked: Mapped[bool] = mapped_column(Boolean, default=False)

    # Optimistic concurrency + audit (tài liệu Phụ lục C).
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
