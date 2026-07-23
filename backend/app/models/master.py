"""Master data: Product, Material. SoR là ERP/PLM trong thực tế; ở MVP
ta giữ bản sao có version/effective date (tài liệu §5.2, §8.1)."""

from typing import Optional

from sqlalchemy import Boolean, Float, ForeignKey, Integer, UnicodeText, Unicode
from sqlalchemy.orm import Mapped, mapped_column

from ..common import new_id
from ..database import Base


class BeerType(Base):
    """Loại bia (thương hiệu, VD Sapphire/Legend/lowCarb) — cấp trên Product: 1 Dịch bia
    (Product, có thể khác độ Bx/oP, VD SAPPHIRE-13OP và SAPPHIRE-14OP) thuộc về 1 Loại
    bia. Lọc/Chiết tra chỉ tiêu QC theo Loại bia (không phân biệt oP) thay vì theo Dịch
    bia cụ thể — xem StageQcGroup.beer_type_id, FilterOrder/FilterRecord/BottleRecord.beer_type_id."""

    __tablename__ = "beer_type"

    beer_type_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(Unicode(255))
    note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)


class Product(Base):
    """Dịch bia (công thức/loại bia đang chạy qua nấu→lên men→lọc) — KHÔNG phải sản
    phẩm đóng gói cuối cùng, xem FinishedProduct."""

    __tablename__ = "product"

    product_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(Unicode(255))
    uom: Mapped[str] = mapped_column(Unicode(255), default="L")
    description: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    ferment_days_std: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # số ngày lên men chuẩn (sẵn sàng chiết)
    spec_json: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)  # Quy định (chỉ tiêu công nghệ nấu) — xem services/braumat_import.py::SPEC_FIELDS, chỉ admin (master.manage) sửa được
    beer_type_id: Mapped[Optional[str]] = mapped_column(ForeignKey("beer_type.beer_type_id"), nullable=True, index=True)  # Loại bia (thương hiệu) — dùng để tra chỉ tiêu Lọc/Chiết


class FinishedProduct(Base):
    """Sản phẩm thành phẩm (SKU đóng gói, vd chai/lon/keg) — chọn ở bước Chiết cùng
    tank BBT nguồn. Khác Product (dịch bia): cùng 1 dịch bia có thể ra nhiều SKU khác
    nhau, mỗi SKU có thể cần bộ chỉ tiêu thành phẩm riêng (StageQcGroup.finished_product_id)."""

    __tablename__ = "finished_product"

    finished_product_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(Unicode(255))
    uom: Mapped[str] = mapped_column(Unicode(255), default="L")
    product_id: Mapped[Optional[str]] = mapped_column(ForeignKey("product.product_id"), nullable=True, index=True)  # dịch bia gốc (tuỳ chọn, để tham khảo)
    # Kho thành phẩm quản lý theo vỉ/keg (không theo pallet, xem services/wms.py) — mỗi SKU
    # khai báo loại đơn vị tồn kho (vi|keg) + số lượng nhỏ trong 1 đơn vị đó (pack_size):
    # vỉ = số lon/vỉ (VD 24); keg = 1 (mỗi keg tự nó là 1 đơn vị, không gộp).
    unit_type: Mapped[str] = mapped_column(Unicode(16), default="vi")  # vi | keg
    pack_size: Mapped[int] = mapped_column(Integer, default=24)  # Lon/vỉ (vi) hoặc 1 (keg)
    category: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True, index=True)  # Bia chai|Bia lon|Bia hơi|Bia tươi...
    description: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)


class MaterialGroup(Base):
    """Danh mục Nhóm vật tư (malt/gạo/hoa bia/men/...) — trước đây là danh sách cứng trong
    frontend (form Tạo vật tư) trong khi form Sửa lại cho nhập tự do, nên dữ liệu có thể
    lệch khỏi danh sách cứng đó (VD nhóm "gạo" từng lọt vào qua Sửa). Nay Material.category
    lưu đúng `code` của 1 dòng ở đây — cả Tạo lẫn Sửa đều chọn từ cùng 1 danh sách, và danh
    sách này tự quản lý được (thêm/sửa/xóa) thay vì sửa code."""

    __tablename__ = "material_group"

    group_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(Unicode(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Đánh dấu nhóm này là bao bì tiêu hao (nắp, thùng carton, tem nhãn...) — vật tư thuộc
    # nhóm này sẽ tự động xuất hiện ở báo cáo lô bao bì (tab Bao bì), tách biệt với vỏ
    # chai/két/keg tuần hoàn (packaging_type/packaging_move — tài sản đặt cọc, không tiêu hao).
    is_packaging: Mapped[bool] = mapped_column(Boolean, default=False)


class Material(Base):
    __tablename__ = "material"

    material_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(Unicode(255))
    uom: Mapped[str] = mapped_column(Unicode(255), default="kg")
    category: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)  # = MaterialGroup.code
    # Ngưỡng tồn tối thiểu (reorder point) — vượt dưới mức này thì stock_on_hand/inventory_report
    # trả về low_stock=True để cảnh báo. NULL = chưa khai báo ngưỡng, không cảnh báo.
    stock_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
