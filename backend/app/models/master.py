"""Master data: Product, Material. SoR là ERP/PLM trong thực tế; ở MVP
ta giữ bản sao có version/effective date (tài liệu §5.2, §8.1)."""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, UnicodeText, Unicode, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..common import UTCDateTime, new_id, utcnow
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


class UnitTypeCatalog(Base):
    """Danh mục Loại đơn vị tồn kho (WMS thành phẩm) — Vỉ/Keg mặc định + loại tự khai báo
    thêm (VD "Thùng"). Mỗi loại khai báo cách quy đổi "count" (số đơn vị đóng gói, tham số
    vào của mọi API WMS) sang "quantity" (SL đơn vị nhỏ lưu trên FinishedGoodsUnit) — xem
    services/wms.py::_pack_divisor: divide_by_pack_size=True (giống Vỉ) → quantity =
    count * FinishedProduct.pack_size; False (giống Keg) → quantity = count (1:1, không
    nhân pack_size). selectable=False dành cho loại hệ thống tự sinh (VD "lon" khi phân rã
    vỉ — xem services/wms.py::_decompose_one_vi), không cho chọn khi khai báo SKU mới ở
    Danh mục Sản phẩm dù vẫn cần có mặt trong danh mục để tra tên hiển thị."""

    __tablename__ = "unit_type_catalog"

    unit_type_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(Unicode(32), unique=True, index=True)  # "vi"|"keg"|"lon"|tự đặt thêm
    name: Mapped[str] = mapped_column(Unicode(64))  # Nhãn hiển thị, VD "Vỉ", "Keg", "Thùng"
    divide_by_pack_size: Mapped[bool] = mapped_column(Boolean, default=False)
    selectable: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


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
    # Dung tích 1 đơn vị đóng gói cuối cùng (lít) — VD 0.33 (lon 330ml), 20/30/50 (keg) — dùng
    # để đối chiếu V cấp chiết (hl, đo ở tank BBT) với SL ca1+ca2+ca3 (đếm vỉ/keg cuối line) lúc
    # "Kết thúc chiết" (xem routers/brewing.py::finish_bottle); để trống = bỏ qua đối chiếu
    # (SKU cũ chưa khai báo, không ép buộc backfill ngay).
    unit_volume_l: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Khối lượng (kg) — dùng để tính tải trọng hàng/chuyến xe (xem services/wms.py::
    # _line_weight_kg, vehicle_trip_report). weight_primary_kg = khối lượng 1 đơn vị đóng gói
    # CHÍNH của SKU này (1 vỉ NGUYÊN cả bao bì nếu unit_type="vi", hoặc 1 keg nếu unit_type=
    # "keg") — khác unit_volume_l (dung tích LON đơn lẻ), vì vỉ nguyên còn có khối lượng bao
    # bì/dây co ngoài N lon. weight_single_kg = khối lượng 1 lon/chai lẻ — chỉ có ý nghĩa với
    # SKU unit_type="vi" khi bị phân rã (xem decompose_unit/decompose_batch, unit_type="lon").
    weight_primary_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    weight_single_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class FinishedProductMonthlyPlan(Base):
    """Kế hoạch tiêu thụ tháng theo SKU — mỗi (SKU, năm, tháng) có 3 giá trị: kế hoạch ban đầu
    (lập từ đầu tháng), kế hoạch điều chỉnh (sửa lại giữa/cuối kỳ, tuỳ chọn), và lượng sản xuất
    dự kiến (kế hoạch đóng bia trong tháng đó). Cột "Tồn mục tiêu tháng" trên báo cáo NXT kho
    thành phẩm lấy kế hoạch điều chỉnh của THÁNG HIỆN TẠI nếu có, ngược lại lấy kế hoạch ban đầu
    — xem services/wms.py::_monthly_target_map."""

    __tablename__ = "finished_product_monthly_plan"
    __table_args__ = (UniqueConstraint("finished_product_id", "year", "month", name="uq_fp_monthly_plan"),)

    plan_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    finished_product_id: Mapped[str] = mapped_column(ForeignKey("finished_product.finished_product_id"), index=True)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)  # 1-12
    initial_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    adjusted_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    expected_production_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class FinishedProductGroup(Base):
    """Nhóm sản phẩm tự đặt tên (VD "Bia chai chủ lực") — dùng để lọc báo cáo "NXT kho thành
    phẩm" theo nhóm thay vì phải chọn từng SKU (tránh bảng quá dài). Thành viên lưu dạng
    finished_product_id nối dấu phẩy (giống quy ước Deviation.parameter), không dùng bảng
    liên kết riêng vì số lượng thành viên nhỏ và không cần join phức tạp."""

    __tablename__ = "finished_product_group"

    group_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(Unicode(255), unique=True, index=True)
    product_ids: Mapped[str] = mapped_column(UnicodeText, default="")
    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


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
    # Đánh dấu nhóm này là nguyên liệu (chính/phụ) — vật tư thuộc nhóm này khi khai báo chỉ
    # tiêu chất lượng (openLotQcModal) sẽ hiện thêm cột "Giá trị CA" (giá trị in trên bao bì
    # nhà cung cấp) bên cạnh giá trị nhà máy tự đo, để phân biệt phục vụ báo cáo sau này.
    is_raw_material: Mapped[bool] = mapped_column(Boolean, default=False)


class MaterialAltGroup(Base):
    """Nhóm vật tư thay thế (VD "Malt Úc" gồm 2 mã cụ thể: Malt Úc rời + Malt Úc bao — cùng
    bản chất, khác quy cách đóng gói/nhà cung cấp). KHÁC với MaterialGroup ở trên — đó là
    phân loại rộng (malt/gạo/hoa bia...) dùng cho QC/bao bì, còn nhóm này là tập hợp các mã
    vật tư CỤ THỂ có thể dùng thay thế cho nhau.

    Công thức (Formula.materials) có thể khai 1 dòng NVL bằng NHÓM này (alt_group_code) thay
    vì 1 material_code cụ thể — nghĩa là "cần 825kg Malt Úc", không quan tâm rời hay bao.
    Việc chọn mã cụ thể nào để xuất kho vẫn do thủ kho quyết định lúc xuất thật (xem
    services/brew_order.py::_resolve_group_members, frontend openBrewMaterialsModal) — nơi
    xuất kho thật (services/warehouse.py::issue) vốn đã cho chọn tự do bất kỳ vật tư nào,
    nhóm này chỉ ảnh hưởng tầng khai báo/gợi ý, không đổi gì ở tầng xuất kho."""

    __tablename__ = "material_alt_group"

    group_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(Unicode(255))
    member_material_ids: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Đơn vị của nhóm — mọi thành viên phải khai được đơn vị này (bằng uom chính hoặc alt_uom
    # của chính vật tư đó, xem services/master_data.py::_group_unit_options); dùng để quy đổi
    # tồn kho từng thành viên về cùng 1 đơn vị trước khi cộng (xem services/brew_order.py::
    # _line_stock, services/filter_order.py::_validate_material_lines) — không còn cộng thô
    # số lượng khác đơn vị với nhau. Nullable chỉ để migrate dữ liệu cũ; router luôn bắt buộc.
    unit: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)


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
    # Đơn vị phụ tuỳ chọn (VD "kg" cho vật tư có uom chính là "Lon") + tỷ lệ quy đổi: 1 uom
    # chính = alt_uom_ratio đơn vị phụ (VD 2 nghĩa là 1 Lon = 2kg). Chỉ dùng để cho phép nhập/
    # xuất theo đơn vị phụ ở 1 số màn hình (frontend tự quy đổi về uom chính trước khi gọi API,
    # xem app.js altUomConvert) — không đổi cách lưu trữ/tính tồn kho (luôn theo uom chính).
    alt_uom: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    alt_uom_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
