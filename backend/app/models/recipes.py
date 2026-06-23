"""Recipe + RecipeVersion theo ISA-88 (tài liệu §7.2).

- Recipe: định danh ổn định gắn với product.
- RecipeVersion: bản version có workflow draft->review->approved->effective->obsolete,
  segregation of duties giữa người soạn và người duyệt.
- Khi batch được release, parameters/materials được SNAPSHOT vào batch để recipe
  thay đổi về sau không làm biến đổi hồ sơ mẻ đã chạy (tài liệu §4.2, §7.2).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..common import RecipeState, new_id, utcnow
from ..database import Base


class Recipe(Base):
    __tablename__ = "recipe"

    recipe_id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String)
    product_id: Mapped[str] = mapped_column(ForeignKey("product.product_id"))


class RecipeVersion(Base):
    __tablename__ = "recipe_version"
    __table_args__ = (UniqueConstraint("recipe_id", "version_no", name="uq_recipe_version"),)

    version_id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    recipe_id: Mapped[str] = mapped_column(ForeignKey("recipe.recipe_id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String, default=RecipeState.DRAFT.value)

    # Quy mô mẻ chuẩn mà BOM định mức tính cho (để scale theo planned_qty của mẻ).
    base_qty: Mapped[float] = mapped_column(Float, default=0.0)
    base_uom: Mapped[str] = mapped_column(String, default="L")

    # Tham số quy trình: list[{name, target, lower, upper, unit, phase}]
    parameters: Mapped[list] = mapped_column(JSON, default=list)
    # BOM / định mức vật tư: list[{material_code, qty, uom, tol_pct}]
    materials: Mapped[list] = mapped_column(JSON, default=list)
    # Các checkpoint QC bắt buộc: list[{parameter, method, lower, upper, unit, mandatory}]
    quality_checks: Mapped[list] = mapped_column(JSON, default=list)
    # Hiệu suất kỳ vọng theo công đoạn: list[{step_key, label, step_no, expected_pct, warn_pct}]
    # step_key ∈ {nau, len_men, loc, chiet}; warn_pct = ngưỡng cảnh báo (yield thực < warn_pct).
    yield_steps: Mapped[list] = mapped_column(JSON, default=list)
    # Lý do thay đổi (change-control) khi tạo version mới.
    change_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    created_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
