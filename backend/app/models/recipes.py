"""Recipe + RecipeVersion theo ISA-88 (tài liệu §7.2).

- Recipe: định danh ổn định gắn với 1 Loại bia (BeerType, VD Sapphire) — không gắn trực tiếp
  1 Product/dịch bia cụ thể, vì chỉ tiêu nấu/lên men khác nhau THEO DỊCH (VD 13oP/14oP) trong
  khi bản thân công thức (quy trình soạn/duyệt) vẫn quản lý chung theo thương hiệu.
- RecipeVersion: bản version có workflow draft->review->approved->effective->obsolete,
  segregation of duties giữa người soạn và người duyệt — MỖI version tự gắn 1 Product/dịch bia
  cụ thể (product_id) thuộc đúng Loại bia của Recipe, vì BOM/tham số/chỉ tiêu của version đó
  chỉ áp dụng cho đúng dịch đó (VD version cho 13oP và version cho 14oP cùng nằm trong 1 Recipe
  Sapphire nhưng có thể cùng "effective" song song — không cái nào thay thế cái nào).
- Khi batch được release, parameters/materials được SNAPSHOT vào batch để recipe
  thay đổi về sau không làm biến đổi hồ sơ mẻ đã chạy (tài liệu §4.2, §7.2).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Float, ForeignKey, Integer, Unicode, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..common import RecipeState, UTCDateTime, new_id, utcnow
from ..database import Base


class Recipe(Base):
    __tablename__ = "recipe"

    recipe_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(Unicode(255))
    # 1 Loại bia = đúng 1 công thức (nhiều version bên trong RecipeVersion, mỗi version gắn 1
    # dịch bia cụ thể qua RecipeVersion.product_id) — unique để chọn công thức theo Loại bia
    # (Lệnh nấu/Lệnh SX) luôn ra đúng 1 Recipe.
    beer_type_id: Mapped[str] = mapped_column(ForeignKey("beer_type.beer_type_id"), unique=True, index=True)


class RecipeVersion(Base):
    __tablename__ = "recipe_version"
    __table_args__ = (UniqueConstraint("recipe_id", "version_no", name="uq_recipe_version"),)

    version_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    recipe_id: Mapped[str] = mapped_column(ForeignKey("recipe.recipe_id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(Unicode(255), default=RecipeState.DRAFT.value)
    # Dịch bia cụ thể (VD SAPPHIRE-13OP) mà version này áp dụng — phải cùng Loại bia với
    # Recipe cha (xem services/recipes.py::create_version).
    product_id: Mapped[str] = mapped_column(ForeignKey("product.product_id"), index=True)

    # Quy mô mẻ chuẩn mà BOM định mức tính cho (để scale theo planned_qty của mẻ).
    base_qty: Mapped[float] = mapped_column(Float, default=0.0)
    base_uom: Mapped[str] = mapped_column(Unicode(255), default="L")

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
    change_reason: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    # Thủ tục ISA-88: list unit procedure → operation → phase.
    # [{name, unit_class, operations:[{name, phases:[{name, params:[{name,setpoint,unit}], duration_min}]}]}]
    procedure: Mapped[list] = mapped_column(JSON, default=list)

    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
