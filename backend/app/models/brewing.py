"""Lệnh nấu (BrewOrder) và Cấu hình vận hành (OpsSetting).

Trước đây file này còn chứa toàn bộ luồng "Nấu-Lọc-Chiết" chi tiết theo công đoạn
(nguyên liệu → nấu → lên men → lọc → chiết), nay đã được thay thế hoàn toàn bởi
pipeline "Mẻ sản xuất" (models/batch_pipeline.py: BatchExecution→BatchTank→
BatchFilterLot→BatchPackLot) — các model cũ đã bị xóa (xem migration xóa 19 bảng
legacy). BrewOrder/BrewOrderMaterialLine vẫn dùng cho tính năng "Lệnh nấu" hiện tại
(services/brew_order.py); OpsSetting là cấu hình chia sẻ, không thuộc luồng cũ.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, UnicodeText, Boolean, Float, ForeignKey, Integer, Unicode, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..common import UTCDateTime, new_id, utcnow
from ..database import Base


class BrewOrder(Base):
    """Lệnh sản xuất (nấu) — mẫu giấy thật "LỆNH NẤU BIA KIÊM PHIẾU XUẤT KHO": 1 lệnh ứng với
    đúng 1 dịch bia (Công thức/RecipeVersion), có đủ phần hành chính ngay trên chính dòng này
    (issued_by/executor_unit/warehouse_keeper/reference_note/start_date/end_date/safety_note).
    Có thể ứng với NHIỀU mã nấu (nhiều tank lên men) — sản lượng thực tế (BrewRecord.volume_hl)
    cộng dồn qua các mã nấu tới khi lệch trong khoảng ±volume_tolerance_hl so với
    planned_volume_hl thì lệnh hoàn thành, không cho chọn thêm nữa (xem
    services/brew_order.py::_is_complete, routers/brewing.py::add_brew)."""
    __tablename__ = "brew_order"
    # order_code chỉ duy nhất TRONG 1 năm (order_year = năm created_at, snapshot lúc tạo) —
    # sang năm khác được đánh lại từ đầu, đúng quy ước đánh số trên giấy tờ thật.
    __table_args__ = (UniqueConstraint("order_year", "order_code", name="uq_brew_order_year_code"),)

    brew_order_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    order_code: Mapped[str] = mapped_column(Unicode(64), index=True)   # Số: 36/PXSXBĐM-T6/2026
    order_year: Mapped[int] = mapped_column(Integer, index=True)
    issued_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)          # I. Người ra lệnh
    executor_unit: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)      # II.1 Người thực hiện
    warehouse_keeper: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)   # II.2 Người xuất hàng
    reference_note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)  # "Căn cứ theo nghị quyết..."
    start_date: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    end_date: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    safety_note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    product_id: Mapped[Optional[str]] = mapped_column(ForeignKey("product.product_id"), nullable=True, index=True)
    # CŨ — không còn dùng (Công thức đổi về hệ Recipe/RecipeVersion, xem recipe_version_id bên
    # dưới); giữ cột lại (không xóa/migrate) để tránh đổi schema không cần thiết trên MSSQL.
    formula_id: Mapped[Optional[str]] = mapped_column(ForeignKey("formula.formula_id"), nullable=True, index=True)
    # Công thức (BOM) người lập lệnh CHỌN dùng cho lệnh nhỏ này — 1 dịch bia có đúng 1 Recipe,
    # nhiều RecipeVersion bên trong; chọn 1 version đang "effective" (xem services/recipes.py,
    # services/brew_order.py::_validate_recipe_version_selection). Nullable vì lệnh cũ trước khi
    # có field này không cần backfill (BOM đã snapshot cứng trong BrewOrderMaterialLine).
    recipe_version_id: Mapped[Optional[str]] = mapped_column(ForeignKey("recipe_version.version_id"), nullable=True, index=True)
    product_desc: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)  # "Bia lon Sapphire Mã số...+ chai..."
    planned_batch_count: Mapped[int] = mapped_column(Integer, default=1)     # 12 mẻ
    planned_volume_hl: Mapped[float] = mapped_column(Float, default=0.0)      # kế hoạch (hl) — dùng để scale BOM/mẻ VÀ so với sản lượng nấu thật
    volume_tolerance_hl: Mapped[float] = mapped_column(Float, default=0.0)    # ±hl để coi lệnh hoàn thành
    bx_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bx_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tank_lm: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    batch_range_from: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)   # mẻ 265-276
    batch_range_to: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    # Khóa lô (xem services/lot_lock.py) — set khi 1 mẻ chiết hạ nguồn bị KCS "Khóa lô", chặn
    # mọi sửa/xóa/chuyển trạng thái ở lệnh này VÀ (qua guard hiệu lực) ở mọi mã nấu con.
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    locked_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    locked_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)


class BrewOrderMaterialLine(Base):
    """1 dòng Định mức NVL trong Lệnh nấu — snapshot tồn kho ghi lại LÚC LẬP PHIẾU (không
    phải tồn sống), đúng tính chất văn bản đã ký/in ra."""
    __tablename__ = "brew_order_material_line"

    line_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    brew_order_id: Mapped[str] = mapped_column(ForeignKey("brew_order.brew_order_id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    stt_label: Mapped[Optional[str]] = mapped_column(Unicode(16), nullable=True)   # "1","2.1","A"...
    is_header: Mapped[bool] = mapped_column(Boolean, default=False)  # dòng nhóm "A Nguyên liệu chính" (không SL)
    material_id: Mapped[Optional[str]] = mapped_column(ForeignKey("material.material_id"), nullable=True)
    material_name: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)  # tên tự do nếu chưa có trong Danh mục
    # Set khi dòng này khai theo Nhóm vật tư thay thế (MaterialAltGroup.code) thay vì 1
    # material_id cụ thể — material_id/material_name ở trên vẫn để None/tên nhóm tương ứng.
    # Xem services/brew_order.py::_resolve_group_members.
    material_group_code: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    # Snapshot định mức RIÊNG từng thành viên lúc lập phiếu — chỉ có khi Công thức khai dòng
    # nhóm này theo kiểu "mỗi thành viên 1 định mức riêng" (RecipeVersion.materials::member_qty,
    # xem services/brew_order.py::build_lines_from_recipe_version). None với dòng nhóm kiểu cũ
    # (1 định mức dùng chung cho mọi thành viên — qty_per_batch/qty_total ở dưới vẫn áp dụng
    # như trước). List các dict {material_id, material_code, material_name, qty_per_batch,
    # qty_total} — dùng để get_order() dựng lại đúng member_breakdown có định mức, không cần
    # (và không nên) tính lại từ định mức Công thức hiện tại vì Công thức có thể đã sửa sau khi
    # lệnh đã lập (giống mọi snapshot khác trên dòng này).
    member_qty_snapshot: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    uom: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    qty_per_batch: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # Nhu cầu 1 mẻ
    qty_total: Mapped[Optional[float]] = mapped_column(Float, nullable=True)       # Nhu cầu Tổng mẻ
    unit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stock_company_snapshot: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # tồn Kho công ty lúc lập phiếu
    stock_workshop_snapshot: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # tồn Kho phân xưởng lúc lập phiếu
    # SL thực xuất tách theo 2 nguồn — mặc định GỢI Ý (ưu tiên dùng hết tồn đang có tại Kho
    # phân xưởng, tối đa bằng Nhu cầu Tổng mẻ; phần còn thiếu lấy tại Kho công ty), người lập
    # lệnh nấu có thể sửa lại 2 số này trước khi lưu (xem services/brew_order.py::_suggest_qty_split).
    # In lên cột "Thực xuất" của biểu mẫu Lệnh nấu (frontend printBrewOrder).
    qty_from_company: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    qty_from_workshop: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class OpsSetting(Base):
    """Cấu hình vận hành toàn hệ thống (1 dòng duy nhất) — hiện chỉ có 2 ngưỡng dung sai thể
    tích cho phép "Làm rỗng" tank CCT/BBT khi tank vật lý đã cạn thật nhưng số liệu phần mềm
    còn lệch một khoảng nhỏ (hao hụt đo đạc/cặn/foam khiến lọc/chiết không bao giờ rút hết
    theo số liệu) — chặn không cho làm rỗng nếu phần lệch vượt ngưỡng (tránh xoá nhầm sai
    lệch lớn do lỗi nhập liệu thật). Xem services/batch_pipeline.py (empty tank tương đương)."""
    __tablename__ = "ops_setting"

    setting_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    empty_cct_tolerance_hl: Mapped[float] = mapped_column(Float, default=2.0)
    empty_bbt_tolerance_hl: Mapped[float] = mapped_column(Float, default=2.0)
    # Ngưỡng số ngày tồn kho (báo cáo "Tồn kho theo tuổi") để phân loại mức cảnh báo — số
    # thực (vd 1.5 ngày) để cho phép cảnh báo sớm hơn 1 ngày tròn. Xem services/wms.py::lot_aging_report.
    aging_caution_days: Mapped[float] = mapped_column(Float, default=30.0)
    aging_warning_days: Mapped[float] = mapped_column(Float, default=60.0)
    aging_critical_days: Mapped[float] = mapped_column(Float, default=90.0)
    # KHÔNG CÒN DÙNG — trước đây phân loại 1 mẻ lọc (FilterRecord, module Nấu-Lọc-Chiết cũ,
    # đã xóa hẳn) ĐÃ KẾT THÚC là Thấp/Bình thường/Cao theo sản lượng (hl). Giữ lại cột (không
    # đáng để migration riêng), không còn code nào đọc 2 field này.
    filter_yield_low_hl: Mapped[float] = mapped_column(Float, default=50.0)
    filter_yield_high_hl: Mapped[float] = mapped_column(Float, default=150.0)
    # Ngưỡng sản lượng (LÍT) để phân loại từng mẻ lọc (BatchFilterLotBatch, pipeline "Mẻ sản
    # xuất") ĐÃ KẾT THÚC là Thấp/Bình thường/Cao — so trên (v_dich_hl + nuoc_bai_khi_hl) * 100
    # của mẻ đó. Dùng cho services/dashboard.py::_batch_filter_lot_yield_items/
    # low_yield_filter_alerts (classify_yield_l ở services/filter_yield_report.py). <= low =
    # Thấp (cảnh báo); > low và <= high = Bình thường; > high = Cao.
    filter_line_yield_low_l: Mapped[float] = mapped_column(Float, default=500.0)
    filter_line_yield_high_l: Mapped[float] = mapped_column(Float, default=2000.0)
    # Ngưỡng số ngày tồn dự kiến (= tồn thực tế / lượng xuất TB 7 ngày) để đề xuất "Đóng bổ
    # sung" trên báo cáo NXT kho thành phẩm — áp dụng chung mọi SKU, không phải/SKU (giống 2
    # cặp ngưỡng sản lượng lọc ở trên). Xem services/wms.py::finished_goods_stock_inout_report.
    # Cũng dùng làm biên Vàng/Xanh cho màu cột "Số ngày tồn dự kiến" trên báo cáo đó — dưới
    # fg_days_of_stock_critical_days = Đỏ, dưới finished_goods_restock_days = Vàng, còn lại
    # = Xanh (xem frontend/views_ext.js::fsDaysBadge).
    finished_goods_restock_days: Mapped[float] = mapped_column(Float, default=7.0)
    fg_days_of_stock_critical_days: Mapped[float] = mapped_column(Float, default=3.0)
    # Ngưỡng màu cho cột "Số ngày lưu kho" (từ ngày sản xuất gần nhất tới hiện tại) trên báo
    # cáo NXT kho thành phẩm — chỉ 2 mức: trên ngưỡng này = Vàng (tồn lâu, cần lưu ý xuất trước),
    # bằng/dưới = Xanh. Không có mức Đỏ riêng cho cột này.
    fg_days_in_stock_warning_days: Mapped[float] = mapped_column(Float, default=30.0)
    # Mã nhận dạng nhà máy — khai báo ở Danh mục cùng "Cài đặt vận hành", giúp truy vết ngoài
    # thị trường sản phẩm được chiết từ nhà máy nào (hữu ích khi hệ thống mở rộng nhiều nhà máy).
    factory_code: Mapped[Optional[str]] = mapped_column(Unicode(32), nullable=True)
    # Số ngày lùi về quá khứ tối đa cho phép ở "Ngày nhập" khi nhập kho thủ công thành phẩm/khai
    # báo Nhập từ nhà máy khác (tránh gõ nhầm ngày) — trước đây hardcode 15, nay cấu hình được ở
    # Cài đặt vận hành. Không áp dụng cho Nhập tồn đầu (luôn bỏ qua, xem services/wms.py::_create_units).
    finished_goods_receive_max_backdate_days: Mapped[float] = mapped_column(Float, default=15.0)
    # Giờ cắt "ngày vận hành" (0-23, giờ VN) cho báo cáo NXT kho thành phẩm THEO NGÀY — 1 "ngày"
    # = từ giờ này của ngày hôm trước đến đúng giờ này của ngày hôm sau, KHÔNG cố định 00h-24h
    # (khớp thực tế ca đêm 22h-06h không bị cắt đôi giữa 2 ngày lịch). Xem
    # services/wms.py::finished_goods_daily_stock_report.
    fg_day_cutoff_hour: Mapped[int] = mapped_column(Integer, default=0)
    # KHÔNG CÒN DÙNG — trước đây là sai số sản lượng (±hl) để tự động xét "hoàn thành" cho Lệnh
    # SX (ERP, ProductionOrder, đã xóa hẳn). Giữ lại cột (không đáng để migration riêng), không
    # còn code nào đọc field này. BrewOrder tự tính "hoàn thành" qua volume_tolerance_hl riêng.
    erp_order_volume_tolerance_hl: Mapped[float] = mapped_column(Float, default=5.0)
    updated_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
