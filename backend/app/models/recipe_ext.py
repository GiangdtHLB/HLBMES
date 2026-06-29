"""Mở rộng Recipe/BOM (tài liệu §7.2):

- BatchYieldActual: hiệu suất THỰC TẾ theo từng công đoạn (nấu→lên men→lọc→chiết)
  của một mẻ, để tính cumulative yield & loss và cảnh báo khi yield thấp.
- RecipeChange: phiếu kiểm soát thay đổi công thức (change-control) — lý do, người
  yêu cầu/duyệt, chữ ký điện tử (re-auth), diff giữa version cũ↔mới.

Lưu ý: yield kỳ vọng (expected) và "nguyên liệu thay thế" (alternates) KHÔNG tách
bảng — chúng nằm trong JSON của RecipeVersion (yield_steps + key 'alternates' trong
từng dòng materials) để bám đúng quy ước 'BOM lưu JSON list[dict]'.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Text, JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..common import new_id, utcnow
from ..database import Base


class BatchYieldActual(Base):
    """Hiệu suất THỰC TẾ theo công đoạn của một mẻ. input/output cùng uom."""

    __tablename__ = "batch_yield_actual"

    yield_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batch_execution.batch_id"), index=True)
    step_key: Mapped[str] = mapped_column(String(255))              # nau|len_men|loc|chiet
    step_no: Mapped[int] = mapped_column(Integer, default=0)   # thứ tự công đoạn (1..n)
    input_qty: Mapped[float] = mapped_column(Float, default=0.0)
    output_qty: Mapped[float] = mapped_column(Float, default=0.0)
    uom: Mapped[str] = mapped_column(String(255), default="L")
    expected_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recorded_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecipeChange(Base):
    """Phiếu kiểm soát thay đổi công thức (change-control / 21 CFR Part 11)."""

    __tablename__ = "recipe_change"

    change_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    change_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    recipe_id: Mapped[str] = mapped_column(String(64), index=True)
    version_id: Mapped[str] = mapped_column(String(64), index=True)        # version mới
    from_version_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # version cũ (baseline)
    reason: Mapped[str] = mapped_column(Text)                        # lý do thay đổi (bắt buộc)
    diff: Mapped[dict] = mapped_column(JSON, default=dict)             # tóm tắt khác biệt cũ↔mới
    state: Mapped[str] = mapped_column(String(255), default="open")         # open|approved
    requested_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
