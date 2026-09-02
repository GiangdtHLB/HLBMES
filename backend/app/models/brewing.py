"""Luồng sản xuất bia theo công đoạn (mô phỏng hệ PX Đông Mai).

Nguyên liệu → Nấu → Lên men (tank LM/CCT) → Lọc (vào tank BBT) → Chiết.
Mỗi công đoạn có bản ghi riêng, liên kết với công đoạn trước qua mã, và có
chỉ tiêu phân tích (StageIndicator). Đây là biểu diễn chi tiết, song song với
mô hình BatchExecution trừu tượng của lõi MES.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, UnicodeText, Boolean, Float, ForeignKey, Integer, Unicode, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..common import QualityStatus, UTCDateTime, new_id, utcnow
from ..database import Base


class MaterialReceipt(Base):
    """Thông tin nguyên liệu nhập (kèm số lô PM/KCS, nhà cung cấp)."""
    __tablename__ = "material_receipt"

    receipt_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    mskt: Mapped[str] = mapped_column(Unicode(255), index=True)          # mã số kiểm tra
    receipt_date: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    material_name: Mapped[str] = mapped_column(Unicode(255))
    lot_pm: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)   # số lô PM
    lot_kcs: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)  # số lô KCS
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    uom: Mapped[str] = mapped_column(Unicode(255), default="kg")
    location: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)  # nơi nhập
    note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    supplier: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    has_indicators: Mapped[bool] = mapped_column(Boolean, default=False)


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


class BrewRecord(Base):
    """Thông tin nấu (mẻ dịch nha)."""
    __tablename__ = "brew_record"
    # brew_code chỉ duy nhất TRONG 1 năm (brew_year = năm brew_date, snapshot lúc tạo).
    __table_args__ = (UniqueConstraint("brew_year", "brew_code", name="uq_brew_record_year_code"),)

    brew_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    brew_code: Mapped[str] = mapped_column(Unicode(64), index=True)   # mã nấu
    brew_year: Mapped[int] = mapped_column(Integer, index=True)
    brew_date: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    wort_type: Mapped[str] = mapped_column(Unicode(255))                            # dịch nha
    product_id: Mapped[Optional[str]] = mapped_column(ForeignKey("product.product_id"), nullable=True, index=True)  # loại bia (chọn chỉ tiêu theo nhóm)
    volume_hl: Mapped[float] = mapped_column(Float, default=0.0)              # SL nấu/hl
    original_extract: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # độ hòa tan nguyên thủy
    plato: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    seq: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # số mẻ (thứ tự trong lô LM)
    note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    # Lệnh nấu (BrewOrder) cha — bắt buộc lúc tạo qua service (create_brew_record), nhưng vẫn
    # nullable ở DB để không phá dữ liệu demo/dashboard tạo thẳng bằng ORM không qua lệnh nấu
    # nào (xem seed.py::_seed_brewing), mirror cách field này đã luôn nullable từ trước.
    brew_order_id: Mapped[Optional[str]] = mapped_column(ForeignKey("brew_order.brew_order_id"), nullable=True, index=True)
    # Work Order (Điều độ) đã "Phát mẻ" tạo ra mã nấu này — 1 WorkOrder ↔ ĐÚNG 1 mã nấu (validate
    # ở services/workorders.py::dispatch). Nullable — mã nấu tạo trực tiếp ở tab Nấu (không qua
    # Điều độ) vẫn hợp lệ như cũ, không bắt buộc phải có Work Order cha.
    work_order_id: Mapped[Optional[str]] = mapped_column(ForeignKey("work_order.wo_id"), nullable=True, index=True)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    locked_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    locked_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)


class BrewBatch(Base):
    """Một mẻ cụ thể (số mẻ từ hệ thống điều khiển nấu, VD Braumat) thuộc 1 mã nấu —
    1 mã nấu (BrewRecord) = 1 lần nấu vào 1 tank, có thể gồm nhiều mẻ; mỗi mẻ khai báo
    nguyên liệu (BrewMaterialUsage) & chỉ tiêu (QualityResult scope_type=brew_batch) riêng."""
    __tablename__ = "brew_batch"
    # Số mẻ (VD Braumat) là 1 dãy đếm DUY NHẤT toàn hệ thống (không phải riêng từng mã nấu) —
    # 2 mã nấu KHÁC NHAU không được dùng chung 1 số mẻ. Dãy số này reset lại từ đầu mỗi năm
    # (theo năm của started_at) nên khóa duy nhất phải gồm cả batch_year, không chỉ batch_code
    # không thôi (nếu không, năm sau sẽ không đánh lại số mẻ từ 1 được).
    __table_args__ = (UniqueConstraint("batch_year", "batch_code", name="uq_brew_batch_year_code"),)

    batch_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    brew_id: Mapped[str] = mapped_column(ForeignKey("brew_record.brew_id"), index=True)
    # Dây chuyền/nhà nấu (ProductionLine.kind="brewhouse") thực hiện mẻ này — bắt buộc ở tầng
    # API/UI (BrewBatchIn.line_id không Optional), nullable ở DB để không vỡ dữ liệu mẻ cũ
    # đã có sẵn trước khi thêm trường này.
    line_id: Mapped[Optional[str]] = mapped_column(ForeignKey("production_line.line_id"), nullable=True, index=True)
    batch_code: Mapped[str] = mapped_column(Unicode(64), index=True)  # số mẻ, VD "123"
    batch_year: Mapped[int] = mapped_column(Integer, index=True)  # năm của started_at — phạm vi reset số mẻ
    seq: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    # Vận hành tự bấm "Kết thúc" khi xong mẻ — started_at gán tay lúc tạo (mặc định giờ hiện
    # tại, sửa được), ended_at chỉ set qua endpoint finish (idempotent, không sửa tay).
    started_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    locked_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    locked_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    # Hold/Release theo QA (tài liệu §7.5) — riêng biệt với `locked` (chốt sổ không sửa được
    # nữa). ON_HOLD chặn sửa/xóa/chuyển bước qua _assert_unlocked() (xem routers/brewing.py)
    # nhưng vẫn mở khóa lại (unlock/lock) bình thường một khi đã RELEASED. Xem services/quality.py.
    quality_status: Mapped[str] = mapped_column(Unicode(255), default=QualityStatus.RELEASED.value)


class BrewProcessStep(Base):
    """1 bước công đoạn tự động import từ Step Protocol (Braumat) — 1 dòng cho mỗi bước
    (VD "RC1 Mash in Rice", "MT2 Heat Up", "WK2 Boiling 1") của 1 mẻ (BrewBatch). Giữ
    nguyên toàn bộ tham số gốc trong params_json (JSON: {tên tham số: {setpoint, actual}})
    để không mất dữ liệu — tên tham số PLC tùy công thức/dây chuyền, không cố định trước."""
    __tablename__ = "brew_process_step"

    step_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(ForeignKey("brew_batch.batch_id"), index=True)
    unit: Mapped[str] = mapped_column(Unicode(255), index=True)  # VD "RiceCooker", "MashTun 2"
    step_no: Mapped[int] = mapped_column(Integer)
    eop: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    name: Mapped[str] = mapped_column(Unicode(255))  # VD "RC1 Mash in Rice"
    start_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    end_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    elapsed_actual: Mapped[Optional[str]] = mapped_column(Unicode(32), nullable=True)  # "00:15:03"
    params_json: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    imported_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    imported_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)


class BrewProcessLog(Base):
    """Ghi chép nấu thủ công (khớp biểu mẫu giấy QT-KCS-QT-BM-05) cho 1 mẻ — số liệu KCS
    đo tay (pH, %Bx, thời gian từng bước) hoặc cân/định lượng thủ công (loại malt, hóa
    chất), không có trong dữ liệu tự động Braumat (xem BrewProcessStep cho phần tự động).
    Toàn bộ giá trị "Thực hiện" lưu trong manual_json (xem services/braumat_import.py::
    FORM_FIELDS cho danh sách field/nhãn đầy đủ) — tránh phải migration mỗi lần thêm field
    mới, vì biểu mẫu giấy có rất nhiều trường (~100+) và có thể còn chỉnh sửa thêm. Giá trị
    "Quy định" (spec/mục tiêu) tương ứng nằm ở Product.spec_json (theo dịch bia/công thức),
    dùng CHUNG một bộ key với manual_json để so sánh Quy định — Thực hiện — Braumat."""
    __tablename__ = "brew_process_log"

    log_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(ForeignKey("brew_batch.batch_id"), unique=True, index=True)
    braumat_order_number: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    braumat_batch_number: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    braumat_recipe: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    manual_json: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class BrewMaterialUsage(Base):
    """Nguyên liệu đã dùng cho một mẻ (BrewBatch) cụ thể — lấy thật từ tồn kho Kho phân xưởng
    (MaterialLot), trừ kho thật qua services/warehouse.py::issue() khi gán, hoàn kho qua
    undo_issue() khi xóa dòng. receipt_id giữ lại cho các dòng cũ (trước khi kết nối kho thật).
    lot_date/fifo_ok chụp lại (snapshot) NGAY LÚC GÁN — không tra sống theo lot_id vì sau khi
    issue() trừ kho, lô có thể hết (quantity=0) hoặc đã bị xóa, so sánh live sẽ sai lệch
    (mirror MaterialRequestLine.fifo_ok, xem warehouse.py::_is_oldest_workshop_lot)."""
    __tablename__ = "brew_material_usage"

    usage_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(ForeignKey("brew_batch.batch_id"), index=True)
    receipt_id: Mapped[Optional[str]] = mapped_column(ForeignKey("material_receipt.receipt_id"), nullable=True)
    lot_id: Mapped[Optional[str]] = mapped_column(ForeignKey("material_lot.lot_id"), nullable=True, index=True)
    movement_id: Mapped[Optional[str]] = mapped_column(ForeignKey("stock_movement.movement_id"), nullable=True)
    material_name: Mapped[str] = mapped_column(Unicode(255))
    lot_pm: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    lot_date: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    fifo_ok: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    uom: Mapped[str] = mapped_column(Unicode(255), default="kg")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class FermentRecord(Base):
    """Thông tin quá trình lên men (lô LM trong tank)."""
    __tablename__ = "ferment_record"
    # lm_code chỉ duy nhất TRONG 1 năm (ferment_year = năm brew_date, hoặc năm tạo nếu
    # brew_date để trống — API /ferments độc lập không bắt buộc brew_date).
    __table_args__ = (UniqueConstraint("ferment_year", "lm_code", name="uq_ferment_record_year_code"),)

    ferment_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    lm_code: Mapped[str] = mapped_column(Unicode(64), index=True)     # Lô LM
    ferment_year: Mapped[int] = mapped_column(Integer, index=True)
    brew_code: Mapped[Optional[str]] = mapped_column(Unicode(64), index=True)      # mã nấu
    brew_date: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    kt_date: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)  # ngày KT
    batch_numbers: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)  # số mẻ
    wort_type: Mapped[str] = mapped_column(Unicode(255))                           # dịch nha
    product_id: Mapped[Optional[str]] = mapped_column(ForeignKey("product.product_id"), nullable=True, index=True)  # loại bia (kế từ mẻ nấu)
    yeast_gen: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)  # đời men
    tank_lm: Mapped[str] = mapped_column(Unicode(255), index=True)                 # Tank LM
    volume_hl: Mapped[float] = mapped_column(Float, default=0.0)             # SL nấu/hl
    on_hand_cct: Mapped[float] = mapped_column(Float, default=0.0)           # đang tồn CCT/hl
    status: Mapped[str] = mapped_column(Unicode(255), default="len_men")          # len_men/cho_loc/da_loc
    ferment_days: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)  # số ngày LM (text)
    qc_approved: Mapped[bool] = mapped_column(Boolean, default=False)  # KCS đã ký xác nhận tank lên men đạt, đồng ý cho chiết/lọc
    qc_approved_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    qc_approved_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    locked_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    locked_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    quality_status: Mapped[str] = mapped_column(Unicode(255), default=QualityStatus.RELEASED.value)


class FermentBrewLink(Base):
    """Liên kết nhiều mẻ nấu (BrewRecord) vào một lô lên men/tank (FermentRecord) —
    thay cho việc gõ tay số mẻ vào FermentRecord.batch_numbers."""
    __tablename__ = "ferment_brew_link"

    link_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    ferment_id: Mapped[str] = mapped_column(ForeignKey("ferment_record.ferment_id"), index=True)
    brew_id: Mapped[str] = mapped_column(ForeignKey("brew_record.brew_id"), index=True)


class FermentProcessLog(Base):
    """1 dòng / lô LM (FermentRecord) — các trường nhập tay ở bảng thông tin đầu (Kiểu men,
    mật độ B/C/D/E/F/G/J, lưu lượng khí bs, tách men, mốc Hạ phụ...) dồn vào manual_json
    (giống BrewProcessLog.manual_json) — xem services/ferment_log.py::HEADER_FIELDS."""
    __tablename__ = "ferment_process_log"

    log_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    ferment_id: Mapped[str] = mapped_column(ForeignKey("ferment_record.ferment_id"), unique=True, index=True)
    manual_json: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)


class FermentDailyReading(Base):
    """1 dòng / 1 ngày theo dõi lên men (bảng dưới cùng biểu mẫu giấy BM 1.11 (06)) — bảng
    con riêng (không dồn vào JSON) vì cần truy vấn theo thứ tự ngày để vẽ biểu đồ. Mỗi nhóm
    trường (đo đạc/KCS/trực ca) có audit trail riêng (by/at) — tự động ghi khi có giá trị,
    KHÔNG nhập tay tên người/giờ (xem services/ferment_log.py::upsert_daily_readings)."""
    __tablename__ = "ferment_daily_reading"

    reading_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    ferment_id: Mapped[str] = mapped_column(ForeignKey("ferment_record.ferment_id"), index=True)
    day_no: Mapped[int] = mapped_column(Integer)
    reading_date: Mapped[Optional[str]] = mapped_column(Unicode(32), nullable=True)  # ISO "YYYY-MM-DD"
    nhiet_do_c: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    do_s: Mapped[Optional[float]] = mapped_column(Float, nullable=True)          # °S (Plato)
    mat_do_tb: Mapped[Optional[float]] = mapped_column(Float, nullable=True)     # 10^6/ml
    measured_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    measured_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    kcs: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)  # "dat"|"khong_dat"
    kcs_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    kcs_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    truc_ca: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    truc_ca_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    truc_ca_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)

    __table_args__ = (UniqueConstraint("ferment_id", "day_no", name="uq_ferment_daily_reading_day"),)


class FilterMasterOrder(Base):
    """Lệnh lọc lớn — số lệnh + ghi chú người lập; chứa 1..N "lệnh lọc nhỏ" (FilterOrder,
    xem master_order_id bên dưới), mỗi lệnh nhỏ tự chọn phối/không phối + tank riêng + vật
    tư riêng + thể tích dịch kế hoạch riêng. In ra 1 tờ gồm tất cả lệnh nhỏ bên trong (xem
    frontend printFilterMasterOrder)."""
    __tablename__ = "filter_master_order"
    # order_code chỉ duy nhất TRONG 1 năm — mirror BrewOrder.order_year.
    __table_args__ = (UniqueConstraint("order_year", "order_code", name="uq_filter_master_order_year_code"),)

    filter_master_order_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    order_code: Mapped[str] = mapped_column(Unicode(64), index=True)
    order_year: Mapped[int] = mapped_column(Integer, index=True)
    note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    locked_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    locked_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)


class FilterOrder(Base):
    """Lệnh lọc NHỎ — nhóm 1 (không phối) hoặc nhiều (phối) tank lên men lọc chung. Khai báo
    thể tích dịch lọc KẾ HOẠCH (planned_volume_hl, đã gồm nước bài khí) + sai số cho phép
    (volume_tolerance_hl) — có thể có NHIỀU bản ghi lọc (FilterRecord, mỗi bản ghi là 1 "mẻ
    lọc" riêng, tank BBT chọn tự do lúc tạo — xem routers/brewing.py::add_filter); sản lượng
    (v_beer_hl) của TẤT CẢ mẻ lọc thuộc lệnh được cộng dồn và so với kế hoạch để tính hoàn
    thành (xem services/filter_order.py::_is_complete). Luôn thuộc về 1 FilterMasterOrder
    (lệnh lọc lớn) — order_code do hệ thống tự sinh (không hiển thị cho người dùng gõ),
    seq là thứ tự "Lệnh lọc nhỏ #N" trong lệnh lớn."""
    __tablename__ = "filter_order"
    # order_code chỉ duy nhất TRONG 1 năm — mirror BrewOrder.order_year.
    __table_args__ = (UniqueConstraint("order_year", "order_code", name="uq_filter_order_year_code"),)

    filter_order_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    order_code: Mapped[str] = mapped_column(Unicode(64), index=True)
    order_year: Mapped[int] = mapped_column(Integer, index=True)
    master_order_id: Mapped[Optional[str]] = mapped_column(ForeignKey("filter_master_order.filter_master_order_id"), nullable=True, index=True)
    seq: Mapped[int] = mapped_column(Integer, default=1)
    blend_mode: Mapped[str] = mapped_column(Unicode(32), default="khong_phoi")  # khong_phoi/phoi
    note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    kcs_lot_no: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)  # Số lô KCS — người lập lệnh tự đánh số tay
    planned_volume_hl: Mapped[float] = mapped_column(Float, default=0.0)   # Thể tích dịch lọc kế hoạch (đã gồm nước bài khí)
    volume_tolerance_hl: Mapped[float] = mapped_column(Float, default=0.0)  # Sai số cho phép (±hl) để coi lệnh đã hoàn thành
    # Loại bia (thương hiệu) — suy tự động từ Dịch bia của (các) tank đã chọn nếu cùng 1
    # Loại bia; nếu phối nhiều tank khác Loại bia thì người lập phải tự chọn 1 trong số đó
    # (xem services/filter_order.py::_validate_tanks). FilterRecord/BottleRecord kế thừa
    # giá trị này — chỉ tiêu Lọc/Chiết tra theo đây, KHÔNG theo product_id cụ thể nữa.
    beer_type_id: Mapped[Optional[str]] = mapped_column(ForeignKey("beer_type.beer_type_id"), nullable=True, index=True)
    # Sản phẩm đích (SKU) — tuỳ chọn, khai báo 1 lần khi lập Lệnh lọc vì cùng 1 Loại bia vẫn
    # có thể cần chỉ tiêu Lọc khác nhau theo hình thức đóng gói đích (VD Legend chai lọc khác
    # Legend tươi). FilterRecord kế thừa xuống, dùng để tra chỉ tiêu Lọc (xem
    # qc_catalog.SKU_SCOPED_STAGES) — KHÔNG bắt buộc phải trùng SKU thật chọn ở Chiết sau này.
    finished_product_id: Mapped[Optional[str]] = mapped_column(ForeignKey("finished_product.finished_product_id"), nullable=True, index=True)
    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    locked_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    locked_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)


class FilterOrderTank(Base):
    """1 tank NGUỒN tham gia lệnh lọc — 'không phối' đúng 1 dòng, 'phối' >= 2 dòng. Nguồn có
    thể là tank lên men (tank_type="cct", ferment_id) HOẶC 1 tank thành phẩm/BBT ĐÃ LỌC XONG
    đang được LỌC LẠI (tank_type="bbt", source_bbt_code=mã tank BBT, source_filter_id=
    FilterRecord đại diện đang chứa nội dung tank đó — resolve lúc add_filter, để None ở
    dòng template; reason=lý do lọc lại, bắt buộc khi tank_type="bbt", xem
    services/filter_order.py::_validate_tanks). filter_id IS NULL = dòng "template" (tạo lúc
    lập lệnh, đại diện tank nguồn của cả lệnh, dùng để hiển thị cấp lệnh — xem
    services/filter_order.py::_tank_summaries). filter_id có giá trị = dòng nhân bản RIÊNG
    cho 1 FilterRecord cụ thể (tạo lúc add_filter, vì 1 lệnh có thể có nhiều bản ghi lọc/"mẻ
    lọc" cộng dồn tới thể tích kế hoạch) — kết quả lọc (giờ kết thúc/dịch nha lọc/nước bài
    khí) điền RIÊNG cho từng dòng nhân bản khi vận hành bấm "Kết thúc" (xem
    finish_filter_tank, trừ tồn vào ferment.on_hand_cct HOẶC source_filter.on_hand_bbt tuỳ
    tank_type); FilterRecord tổng hợp (sum) các dòng nhân bản CỦA CHÍNH NÓ (filter_id khớp)
    khi tính sản lượng lọc (xem _sync_filter_aggregate)."""
    __tablename__ = "filter_order_tank"

    line_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    filter_order_id: Mapped[str] = mapped_column(ForeignKey("filter_order.filter_order_id"), index=True)
    filter_id: Mapped[Optional[str]] = mapped_column(ForeignKey("filter_record.filter_id"), nullable=True, index=True)
    tank_type: Mapped[str] = mapped_column(Unicode(16), default="cct")  # cct (tank lên men) | bbt (tank thành phẩm — lọc lại)
    ferment_id: Mapped[Optional[str]] = mapped_column(ForeignKey("ferment_record.ferment_id"), nullable=True, index=True)  # bắt buộc khi tank_type="cct"
    source_bbt_code: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True, index=True)  # mã tank BBT nguồn — bắt buộc khi tank_type="bbt"
    source_filter_id: Mapped[Optional[str]] = mapped_column(ForeignKey("filter_record.filter_id"), nullable=True, index=True)  # FilterRecord đại diện của source_bbt_code, resolve lúc add_filter
    reason: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)  # Lý do lọc lại — bắt buộc khi tank_type="bbt"
    seq: Mapped[int] = mapped_column(Integer, default=1)         # 1,2,3... thứ tự tank
    # Kế hoạch dịch lọc RIÊNG của tank này, khai báo lúc lập lệnh nhỏ — FilterOrder.planned_volume_hl
    # = tổng planned_v_dich_hl của các dòng "template" (filter_id IS NULL). KHÁC với v_dich_hl bên
    # dưới (thực tế, chỉ có khi vận hành bấm "Kết thúc" — xem finish_filter_tank).
    planned_v_dich_hl: Mapped[float] = mapped_column(Float, default=0.0)
    ended_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    v_dich_hl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    nuoc_bai_khi_hl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # "Mẻ lọc số" — vận hành tự điền tay lúc "Kết thúc" (KHÔNG tự sinh/tăng dần), đếm theo dòng
    # rút dịch (khác batch_number/order_number thuộc FilterRecord) — CHO PHÉP TRÙNG giữa các mẻ
    # lọc/lệnh lọc khác nhau (không có kiểm tra unique như batch_number/order_number).
    batch_seq_no: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    # Vận hành tự đánh dấu (nút riêng, không phải lúc "Kết thúc") khi dòng này là ĐỢT RÚT CUỐI
    # của 1 mẻ lọc thật (thường là phần "vét" tank còn ít dịch, sản lượng thấp một cách bình
    # thường) — báo cáo sản lượng theo mẻ lọc số (services/filter_yield_report.py) loại các
    # dòng/nhóm này khỏi phân loại Thấp/Cao để không báo động giả cho phần vét cuối.
    is_final_batch: Mapped[bool] = mapped_column(Boolean, default=False)


class FilterOrderMaterialLine(Base):
    """Dòng vật tư dùng cho lệnh lọc (VD: bột trợ lọc/diatomite) — chọn từ Danh mục vật tư,
    tồn kho công ty/phân xưởng được chụp lại (snapshot) NGAY LÚC LẬP LỆNH, mirror
    BrewOrderMaterialLine (xem services/warehouse.py::material_fifo_detail). Có thể khai theo
    Nhóm vật tư thay thế (material_group_code) thay vì 1 material_id cụ thể — xem
    services/filter_order.py::_resolve_group_members."""
    __tablename__ = "filter_order_material_line"

    line_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    filter_order_id: Mapped[str] = mapped_column(ForeignKey("filter_order.filter_order_id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    material_id: Mapped[Optional[str]] = mapped_column(ForeignKey("material.material_id"), nullable=True, index=True)
    material_name: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    material_group_code: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    uom: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    unit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stock_company_snapshot: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stock_workshop_snapshot: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class FilterRecord(Base):
    """Thông tin lọc (từ tank LM vào tank BBT)."""
    __tablename__ = "filter_record"
    # filter_code chỉ duy nhất TRONG 1 năm (filter_year = năm filter_date, snapshot lúc tạo).
    __table_args__ = (UniqueConstraint("filter_year", "filter_code", name="uq_filter_record_year_code"),)

    filter_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    filter_code: Mapped[str] = mapped_column(Unicode(64), index=True)  # mã lọc
    filter_year: Mapped[int] = mapped_column(Integer, index=True)
    brew_code: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)    # mã nấu
    lot_loc: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)      # mã lô lọc
    filter_phoi_code: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    filter_date: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    filter_type: Mapped[str] = mapped_column(Unicode(255), default="thuong")        # thuong/phoi/ve_bbt_phoi/loc_lai (server tự set khi có nguồn BBT)
    wort_type: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)    # loại dịch nha lọc
    from_cct: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)     # lọc từ CCT (server tự điền từ lệnh lọc — 1 tank hoặc liệt kê nhiều tank nếu phối)
    ferment_id: Mapped[Optional[str]] = mapped_column(ForeignKey("ferment_record.ferment_id"), nullable=True, index=True)  # lô LM nguồn — CHỈ có khi không phối (1 tank CCT); phối/nguồn BBT để None, xem FilterOrderTank
    source_filter_id: Mapped[Optional[str]] = mapped_column(ForeignKey("filter_record.filter_id"), nullable=True, index=True)  # mẻ lọc BBT nguồn khi LỌC LẠI không phối (1 tank BBT); phối nhiều tank để None, xem FilterOrderTank.source_filter_id từng dòng
    # Lệnh lọc (Lệnh nấu-style: lập trước, chọn 1 lệnh CHƯA DÙNG khi tạo bản ghi lọc) — tank
    # nguồn (1 hoặc nhiều nếu phối) đến từ FilterOrderTank của lệnh này, không tự chọn tay.
    filter_order_id: Mapped[Optional[str]] = mapped_column(ForeignKey("filter_order.filter_order_id"), nullable=True, index=True)
    v_dich_hl: Mapped[float] = mapped_column(Float, default=0.0)              # V dịch/hl
    beer_type: Mapped[str] = mapped_column(Unicode(255))                           # loại bia lọc (tên hiển thị, tự điền từ beer_type_id)
    beer_type_id: Mapped[Optional[str]] = mapped_column(ForeignKey("beer_type.beer_type_id"), nullable=True, index=True)  # Loại bia — kế thừa từ FilterOrder.beer_type_id, dùng để tra chỉ tiêu Lọc
    finished_product_id: Mapped[Optional[str]] = mapped_column(ForeignKey("finished_product.finished_product_id"), nullable=True, index=True)  # Sản phẩm đích (SKU) — kế thừa từ FilterOrder.finished_product_id, dùng để tra chỉ tiêu Lọc
    product_id: Mapped[Optional[str]] = mapped_column(ForeignKey("product.product_id"), nullable=True, index=True)  # dịch bia cụ thể (kế từ tank LM nguồn, chỉ để tham khảo)
    # V dịch/hl và nước bài khí chưa biết lúc bắt đầu lọc — chỉ điền khi vận hành bấm "Kết
    # thúc" (xem finish_filter); v_beer_hl = v_dich_hl + nuoc_bai_khi_hl, tự tính không nhập tay.
    nuoc_bai_khi_hl: Mapped[float] = mapped_column(Float, default=0.0)     # Nước bài khí/hl
    v_beer_hl: Mapped[float] = mapped_column(Float, default=0.0)             # V bia/hl
    to_bbt: Mapped[Optional[str]] = mapped_column(Unicode(255), index=True)        # lọc cho vào (tank BBT)
    status: Mapped[str] = mapped_column(Unicode(255), default="cho_chiet")         # cho_chiet/chiet_1_phan/da_chiet_het
    on_hand_bbt: Mapped[float] = mapped_column(Float, default=0.0)           # đang tồn BBT/hl
    has_indicators: Mapped[bool] = mapped_column(Boolean, default=False)
    has_nvl: Mapped[bool] = mapped_column(Boolean, default=False)
    # Trạng thái THỰC THI của vận hành (đã lọc xong việc chưa) — khác với `status` ở trên
    # (suy ra từ tồn BBT, cho biết còn lọc/chiết tiếp được không). filter_date là mốc bắt
    # đầu sẵn có; ended_at chỉ set qua endpoint finish khi vận hành bấm "Kết thúc".
    ended_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    # KCS duyệt mẻ lọc — chỉ ký được khi đã nhập đủ chỉ tiêu lọc bắt buộc (xem approve_filter),
    # mirror FermentRecord.qc_approved.
    qc_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    qc_approved_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    qc_approved_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    locked_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    locked_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    quality_status: Mapped[str] = mapped_column(Unicode(255), default=QualityStatus.RELEASED.value)
    # Số mẻ/số lệnh do vận hành tự gõ tay (khớp phiếu giấy thực tế của nhà máy) — bắt buộc
    # nhập khi bấm "Kết thúc" (xem finish_filter_tank). Khác với filter_code (mã hệ thống tự
    # sinh) và FilterOrder.order_code (số lệnh lọc lớn/nhỏ trong hệ thống) — 2 trường này chỉ
    # để đối chiếu với chứng từ giấy. KHÔNG unique — CHO PHÉP TRÙNG cả trong cùng filter_order_id
    # lẫn giữa các filter_order_id KHÁC NHAU (thực tế số mẻ/số lệnh giấy có thể lặp lại giữa các
    # lệnh lọc, VD reset theo ca/ngày) — không kiểm tra trùng ở tầng ứng dụng nữa (xem
    # finish_filter_tank). Báo cáo sản lượng theo mẻ lọc số tự gộp các dòng cùng bộ 3 giá trị
    # (batch_number, order_number, batch_seq_no) lại thành 1 mẻ thật khi tính sản lượng (xem
    # services/filter_yield_report.py::filter_line_yield_report).
    batch_number: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True, index=True)
    order_number: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True, index=True)


class FilterMaterialUsage(Base):
    """Nguyên liệu (VD: bột trợ lọc) đã dùng thật cho 1 mẻ lọc (FilterRecord) cụ thể — lấy từ
    tồn kho Kho phân xưởng (MaterialLot), trừ kho thật qua services/warehouse.py::issue() khi
    gán, hoàn kho qua undo_issue() khi xóa dòng. Gợi ý số lượng mặc định lấy từ
    FilterOrderMaterialLine (khai báo lúc lập Lệnh lọc) — xem openFilterMaterialsModal.
    Mirror BrewMaterialUsage (batch_id -> filter_id), gồm cả lot_date/fifo_ok snapshot."""
    __tablename__ = "filter_material_usage"

    usage_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    filter_id: Mapped[str] = mapped_column(ForeignKey("filter_record.filter_id"), index=True)
    receipt_id: Mapped[Optional[str]] = mapped_column(ForeignKey("material_receipt.receipt_id"), nullable=True)
    lot_id: Mapped[Optional[str]] = mapped_column(ForeignKey("material_lot.lot_id"), nullable=True, index=True)
    movement_id: Mapped[Optional[str]] = mapped_column(ForeignKey("stock_movement.movement_id"), nullable=True)
    material_name: Mapped[str] = mapped_column(Unicode(255))
    lot_pm: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    lot_date: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    fifo_ok: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    uom: Mapped[str] = mapped_column(Unicode(255), default="kg")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class BottleMaterialUsage(Base):
    """Nguyên liệu (VD: CO2, hóa chất vệ sinh) đã dùng thật cho 1 mẻ chiết (BottleRecord) cụ
    thể — lấy từ tồn kho Kho phân xưởng (MaterialLot), trừ kho thật qua
    services/warehouse.py::issue() khi gán, hoàn kho qua undo_issue() khi xóa dòng.
    Mirror FilterMaterialUsage (filter_id -> bottle_id) — Chiết trước đây không tiêu thụ NVL,
    nay bổ sung cùng cơ chế NVL + FIFO snapshot như Nấu/Lọc."""
    __tablename__ = "bottle_material_usage"

    usage_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    bottle_id: Mapped[str] = mapped_column(ForeignKey("bottle_record.bottle_id"), index=True)
    lot_id: Mapped[Optional[str]] = mapped_column(ForeignKey("material_lot.lot_id"), nullable=True, index=True)
    movement_id: Mapped[Optional[str]] = mapped_column(ForeignKey("stock_movement.movement_id"), nullable=True)
    material_name: Mapped[str] = mapped_column(Unicode(255))
    lot_pm: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    lot_date: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    fifo_ok: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    uom: Mapped[str] = mapped_column(Unicode(255), default="kg")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class BottleRecord(Base):
    """Thông tin chiết (từ tank BBT ra dây chuyền theo ca)."""
    __tablename__ = "bottle_record"
    # bottle_code chỉ duy nhất TRONG 1 năm (bottle_year = năm bottle_date, snapshot lúc tạo).
    __table_args__ = (UniqueConstraint("bottle_year", "bottle_code", name="uq_bottle_record_year_code"),)

    bottle_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    bottle_code: Mapped[str] = mapped_column(Unicode(64), index=True)  # mã chiết
    bottle_year: Mapped[int] = mapped_column(Integer, index=True)
    filter_code: Mapped[Optional[str]] = mapped_column(Unicode(64), index=True)     # mã lọc
    filter_id: Mapped[Optional[str]] = mapped_column(ForeignKey("filter_record.filter_id"), nullable=True, index=True)  # tank BBT nguồn (khớp from_bbt lúc tạo) — dùng để trừ/hoàn on_hand_bbt
    bottle_date: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    beer_type: Mapped[str] = mapped_column(Unicode(255))                            # loại bia (tên hiển thị, tự điền từ beer_type_id)
    beer_type_id: Mapped[Optional[str]] = mapped_column(ForeignKey("beer_type.beer_type_id"), nullable=True, index=True)  # Loại bia — kế thừa từ FilterRecord nguồn, dùng để tra chỉ tiêu Chiết
    product_id: Mapped[Optional[str]] = mapped_column(ForeignKey("product.product_id"), nullable=True, index=True)  # dịch bia (kế từ tank BBT nguồn)
    finished_product_id: Mapped[Optional[str]] = mapped_column(ForeignKey("finished_product.finished_product_id"), nullable=True, index=True)  # sản phẩm đóng gói (SKU) — chọn khi chiết
    lot_no: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)       # số lô bia
    v_cap_chiet_hl: Mapped[float] = mapped_column(Float, default=0.0)         # V cấp chiết/hl
    from_bbt: Mapped[Optional[str]] = mapped_column(Unicode(255), index=True)       # chiết từ tank BBT
    line: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)        # dây chuyền
    ca1: Mapped[float] = mapped_column(Float, default=0.0)
    ca2: Mapped[float] = mapped_column(Float, default=0.0)
    ca3: Mapped[float] = mapped_column(Float, default=0.0)
    stocked: Mapped[bool] = mapped_column(Boolean, default=False)             # đã nhập kho
    approved: Mapped[bool] = mapped_column(Boolean, default=False)            # chiết duyệt
    approved_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    has_indicators: Mapped[bool] = mapped_column(Boolean, default=False)
    has_nvl: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    # Trạng thái thực thi (đã chiết xong việc chưa) — bottle_date là mốc bắt đầu sẵn có;
    # ended_at chỉ set qua endpoint finish khi vận hành bấm "Kết thúc".
    ended_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    locked_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    locked_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    quality_status: Mapped[str] = mapped_column(Unicode(255), default=QualityStatus.RELEASED.value)


class StageIndicator(Base):
    """Chỉ tiêu phân tích gắn với một bản ghi công đoạn."""
    __tablename__ = "stage_indicator"

    indicator_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    stage: Mapped[str] = mapped_column(Unicode(255), index=True)        # nau/len_men/loc/chiet
    scope_code: Mapped[str] = mapped_column(Unicode(64), index=True)   # mã nấu/lô LM/mã lọc/mã chiết
    name: Mapped[str] = mapped_column(Unicode(255))                     # tên chỉ tiêu
    unit: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    value_text: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    warning: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    analyst: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)  # NV PT
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class OpsSetting(Base):
    """Cấu hình vận hành toàn hệ thống (1 dòng duy nhất) — hiện chỉ có 2 ngưỡng dung sai thể
    tích cho phép "Làm rỗng" tank CCT/BBT khi tank vật lý đã cạn thật nhưng số liệu phần mềm
    còn lệch một khoảng nhỏ (hao hụt đo đạc/cặn/foam khiến lọc/chiết không bao giờ rút hết
    theo số liệu) — chặn không cho làm rỗng nếu phần lệch vượt ngưỡng (tránh xoá nhầm sai
    lệch lớn do lỗi nhập liệu thật). Xem routers/brewing.py::empty_ferment_cct/empty_filter_bbt."""
    __tablename__ = "ops_setting"

    setting_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    empty_cct_tolerance_hl: Mapped[float] = mapped_column(Float, default=2.0)
    empty_bbt_tolerance_hl: Mapped[float] = mapped_column(Float, default=2.0)
    # Ngưỡng số ngày tồn kho (báo cáo "Tồn kho theo tuổi") để phân loại mức cảnh báo — số
    # thực (vd 1.5 ngày) để cho phép cảnh báo sớm hơn 1 ngày tròn. Xem services/wms.py::lot_aging_report.
    aging_caution_days: Mapped[float] = mapped_column(Float, default=30.0)
    aging_warning_days: Mapped[float] = mapped_column(Float, default=60.0)
    aging_critical_days: Mapped[float] = mapped_column(Float, default=90.0)
    # Ngưỡng sản lượng (hl) để phân loại 1 mẻ lọc ĐÃ KẾT THÚC là Thấp/Bình thường/Cao — so
    # trực tiếp trên v_beer_hl của FilterRecord (không so với kế hoạch/lệnh lọc), dùng cho
    # báo cáo sản lượng lọc theo mẻ (xem services/filter_yield_report.py). <= low = Thấp
    # (cảnh báo); > low và <= high = Bình thường; > high = Cao.
    filter_yield_low_hl: Mapped[float] = mapped_column(Float, default=50.0)
    filter_yield_high_hl: Mapped[float] = mapped_column(Float, default=150.0)
    # Ngưỡng sản lượng (LÍT — khác đơn vị với 2 ngưỡng trên vì quy mô nhỏ hơn nhiều) để phân
    # loại từng DÒNG "mẻ lọc số" (1 đợt rút dịch/FilterOrderTank.batch_seq_no, đã kết thúc)
    # là Thấp/Bình thường/Cao — so trên (v_dich_hl + nuoc_bai_khi_hl) * 100 của riêng dòng đó
    # (không phải tổng cả FilterRecord). Dùng cho báo cáo "Theo mẻ lọc số" (xem
    # services/filter_yield_report.py::filter_line_yield_report). Cùng quy ước <=/> như trên.
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
