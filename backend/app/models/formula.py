"""Công thức nguyên vật liệu theo dịch bia — thay thế mô hình Recipe/RecipeVersion (version hóa,
6 trạng thái, tham số/QC/ISA-88) cho nhu cầu vận hành thực tế: mỗi lần đổi định mức NVL thì tạo
1 công thức MỚI (không sửa/thêm version vào công thức cũ), mỗi dịch bia (Product) có thể có
NHIỀU công thức độc lập nhưng CHỈ ĐÚNG 1 công thức đang hiệu lực tại 1 thời điểm — Lệnh nấu
(xem services/brew_order.py::_effective_bom) luôn nạp NVL theo công thức đang hiệu lực đó.

Cố tình KHÔNG đụng vào models/recipes.py (Recipe/RecipeVersion) — bảng đó vẫn được
Công thức+ (nav-unused)/RecipeChange/Signature tham chiếu, giữ nguyên để không vỡ lịch sử
change-control/e-signature cũ. Xem migration chuyển đổi dữ liệu 1 lần từ recipe_version sang
formula (mỗi recipe_version cũ -> 1 dòng formula, version đang 'effective' -> is_active=True).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Unicode, UnicodeText
from sqlalchemy.orm import Mapped, mapped_column

from ..common import UTCDateTime, new_id, utcnow
from ..database import Base


class Formula(Base):
    __tablename__ = "formula"

    formula_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    # KHÔNG unique — 1 dịch bia (product) có thể có nhiều công thức độc lập, khác Recipe cũ.
    product_id: Mapped[str] = mapped_column(ForeignKey("product.product_id"), index=True)
    note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    # Nội dung quyết định ban hành công thức + quy trình sản xuất (số QĐ, biểu công nghệ, lần
    # ban hành...) — khai báo 1 lần trên công thức, in nguyên văn vào phiếu Lệnh nấu mỗi khi
    # công thức này được chọn cho 1 lệnh nấu nhỏ (xem frontend/app.js::printBrewOrder và
    # services/brew_order.py::_child_summary/get_order, field "formula_process_note").
    process_reference_note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)

    # Quy mô mẻ chuẩn mà định mức NVL tính cho — dùng để scale theo planned_volume của Lệnh nấu
    # (xem services/bom.py::factor_for), KHÔNG thuộc phần bị lược bỏ (chỉ bỏ tham số/QC/ISA-88).
    base_qty: Mapped[float] = mapped_column(Float, default=0.0)
    base_uom: Mapped[str] = mapped_column(Unicode(255), default="L")
    # Định mức NVL: list[{material_code, qty, uom}] — bỏ tol_pct so với RecipeVersion.materials
    # cũ vì không còn dùng cho đối chiếu dung sai QC (services/bom.py::_classify) ở luồng mới.
    materials: Mapped[list] = mapped_column(JSON, default=list)

    # Đang hiệu lực — CHỈ 1 formula/product được True tại 1 thời điểm, đảm bảo bởi
    # services/formula.py::activate_formula (tự động hạ formula cũ trước khi bật formula mới),
    # không dựa vào unique constraint DB (SQLite/MSSQL đều cần ứng dụng tự đảm bảo).
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Khóa để chặn sửa vĩnh viễn — mirror đúng pattern locked/locked_by/locked_at đã dùng ở
    # 8 bảng khác (xem services/lot_lock.py), do chính người quản lý công thức tự khóa/mở khóa.
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    locked_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    locked_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)

    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class FormulaActivationLog(Base):
    """Lịch sử bật/tắt hiệu lực của từng công thức — hiển thị ngay dưới danh sách công thức
    của mỗi dịch bia (ai, lúc nào, đổi gì), KHÔNG dùng chung với audit log tổng (record_audit
    vẫn được gọi song song để nhất quán với tab Audit chung, nhưng bảng này phục vụ hiển thị
    trực tiếp tại màn Công thức mà không cần sang tab khác)."""
    __tablename__ = "formula_activation_log"

    log_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    formula_id: Mapped[str] = mapped_column(ForeignKey("formula.formula_id"), index=True)
    product_id: Mapped[str] = mapped_column(Unicode(64), index=True)
    action: Mapped[str] = mapped_column(Unicode(32))  # "activate" | "deactivate"
    note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    changed_by: Mapped[str] = mapped_column(Unicode(255))
    changed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
