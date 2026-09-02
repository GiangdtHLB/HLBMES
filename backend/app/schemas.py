"""Pydantic schema cho request/response (OpenAPI tự sinh — tài liệu §9.3)."""

import re
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

_UNIT_TYPE_CODE_RE = re.compile(r"^[a-z0-9_-]+$")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- Master ----
class BeerTypeIn(BaseModel):
    code: str
    name: str
    note: Optional[str] = None


class BeerTypeOut(ORMModel):
    beer_type_id: str
    code: str
    name: str
    note: Optional[str] = None


class UnitTypeCatalogIn(BaseModel):
    code: str
    name: str
    divide_by_pack_size: bool = False
    selectable: bool = True
    active: bool = True

    @field_validator("code")
    @classmethod
    def _normalize_code(cls, v: str) -> str:
        # Mã là khóa tra cứu logic nghiệp vụ (_pack_divisor/_divide_by_pack_codes so khớp CHÍNH
        # XÁC theo chuỗi) — cho gõ tiếng Việt có dấu ('Vỉ') vào đây sẽ tạo ra 1 mã khác hẳn mã
        # chuẩn ('vi') mà không có gì báo lỗi, làm vỡ toàn bộ quy đổi pack_size cho SKU trỏ vào
        # mã lạ đó (xem báo cáo lỗi 'Nhập kho thủ công' 2026-07). Tự hạ chữ thường cho tiện gõ
        # (VD "VI" -> "vi"), nhưng chặn hẳn dấu tiếng Việt/khoảng trắng — người dùng phải sửa lại
        # đúng ô "Mã", không để hệ thống đoán/slugify sai ý.
        v = v.strip().lower()
        if not v or not _UNIT_TYPE_CODE_RE.match(v):
            raise ValueError(
                "Mã loại đơn vị chỉ được dùng chữ thường a-z, số 0-9, gạch dưới/gạch ngang, "
                "không dấu, không khoảng trắng (VD: vi, keg, thung). Tên tiếng Việt có dấu nhập "
                "ở ô 'Tên hiển thị'."
            )
        return v


class UnitTypeCatalogOut(ORMModel):
    unit_type_id: str
    code: str
    name: str
    divide_by_pack_size: bool
    selectable: bool
    active: bool


class MaterialGroupIn(BaseModel):
    code: str
    name: str
    active: bool = True
    is_packaging: bool = False
    is_raw_material: bool = False


class MaterialGroupOut(ORMModel):
    group_id: str
    code: str
    name: str
    active: bool
    is_packaging: bool
    is_raw_material: bool


class MaterialAltGroupIn(BaseModel):
    code: str
    name: str
    member_material_ids: list[str] = []
    unit: str
    active: bool = True
    selection_mode: str = "single"


class MaterialAltGroupOut(ORMModel):
    group_id: str
    code: str
    name: str
    member_material_ids: list
    unit: Optional[str] = None
    active: bool
    selection_mode: str = "single"


class LotKcsUpdateIn(BaseModel):
    kcs_lot_no: Optional[str] = None
    supplier_lot: Optional[str] = None


class OpsSettingIn(BaseModel):
    empty_cct_tolerance_hl: float
    empty_bbt_tolerance_hl: float
    aging_caution_days: float = 30.0
    aging_warning_days: float = 60.0
    aging_critical_days: float = 90.0
    filter_yield_low_hl: float = 50.0
    filter_yield_high_hl: float = 150.0
    filter_line_yield_low_l: float = 500.0
    filter_line_yield_high_l: float = 2000.0
    finished_goods_restock_days: float = 7.0
    fg_days_of_stock_critical_days: float = 3.0
    fg_days_in_stock_warning_days: float = 30.0
    finished_goods_receive_max_backdate_days: float = 15.0
    fg_day_cutoff_hour: int = 0
    factory_code: Optional[str] = None
    erp_order_volume_tolerance_hl: float = 5.0


class OpsSettingOut(ORMModel):
    setting_id: str
    empty_cct_tolerance_hl: float
    empty_bbt_tolerance_hl: float
    aging_caution_days: float
    aging_warning_days: float
    aging_critical_days: float
    filter_yield_low_hl: float
    filter_yield_high_hl: float
    filter_line_yield_low_l: float
    filter_line_yield_high_l: float
    finished_goods_restock_days: float
    fg_days_of_stock_critical_days: float
    fg_days_in_stock_warning_days: float
    finished_goods_receive_max_backdate_days: float
    fg_day_cutoff_hour: int
    factory_code: Optional[str] = None
    erp_order_volume_tolerance_hl: float = 5.0
    updated_by: Optional[str] = None
    updated_at: datetime


class SupplierIn(BaseModel):
    code: str
    name: str
    address: Optional[str] = None
    contact: Optional[str] = None
    note: Optional[str] = None


class SupplierOut(ORMModel):
    supplier_id: str
    code: str
    name: str
    address: Optional[str] = None
    contact: Optional[str] = None
    note: Optional[str] = None
    active: bool


class ProductIn(BaseModel):
    code: str
    name: str
    uom: str = "L"
    description: Optional[str] = None
    ferment_days_std: Optional[float] = None   # số ngày lên men chuẩn — tính ngày sẵn sàng chiết (cho phép số thực)
    beer_type_id: Optional[str] = None   # Loại bia (thương hiệu) — dùng để tra chỉ tiêu Lọc/Chiết


class ProductOut(ORMModel):
    product_id: str
    code: str
    name: str
    uom: str
    description: Optional[str] = None
    ferment_days_std: Optional[float] = None
    beer_type_id: Optional[str] = None


class FinishedProductIn(BaseModel):
    code: str
    name: str
    uom: str = "L"
    product_id: Optional[str] = None   # dịch bia gốc (tuỳ chọn)
    beer_type_id: Optional[str] = None   # Loại bia — khai trực tiếp, không suy qua product_id
    unit_type: str = "vi"               # vi | keg — loại đơn vị tồn kho thành phẩm
    pack_size: int = 24                 # Lon/vỉ (vi) hoặc 1 (keg)
    category: Optional[str] = None     # Bia chai|Bia lon|Bia hơi|Bia tươi...
    description: Optional[str] = None
    unit_volume_l: Optional[float] = None   # dung tích 1 đơn vị đóng gói (lít) — để đối chiếu lúc kết thúc chiết
    weight_primary_kg: Optional[float] = None   # khối lượng (kg) 1 vỉ/keg NGUYÊN (đơn vị đóng gói chính)
    weight_single_kg: Optional[float] = None    # khối lượng (kg) 1 lon/chai lẻ (sau khi phân rã)


class FinishedProductOut(ORMModel):
    finished_product_id: str
    code: str
    name: str
    uom: str
    product_id: Optional[str] = None
    beer_type_id: Optional[str] = None
    unit_type: str
    pack_size: int
    category: Optional[str] = None
    description: Optional[str] = None
    unit_volume_l: Optional[float] = None
    weight_primary_kg: Optional[float] = None
    weight_single_kg: Optional[float] = None


class MonthlyPlanCellIn(BaseModel):
    month: int  # 1-12
    initial_qty: Optional[float] = None
    adjusted_qty: Optional[float] = None
    expected_production_qty: Optional[float] = None


class MonthlyPlanCellOut(BaseModel):
    month: int
    initial_qty: Optional[float] = None
    adjusted_qty: Optional[float] = None
    expected_production_qty: Optional[float] = None


class MonthlyPlanRowIn(BaseModel):
    year: int
    cells: list[MonthlyPlanCellIn]


class FinishedProductMonthlyPlanOut(BaseModel):
    finished_product_id: str
    code: str
    name: str
    category: Optional[str] = None
    months: list[MonthlyPlanCellOut]


class FinishedProductGroupIn(BaseModel):
    name: str
    product_ids: list[str] = []


class FinishedProductGroupOut(ORMModel):
    group_id: str
    name: str
    product_ids: list[str]
    created_by: Optional[str] = None
    created_at: datetime


class MaterialIn(BaseModel):
    code: str
    name: str
    uom: str = "kg"
    category: Optional[str] = None
    stock_min: Optional[float] = None
    alt_uom: Optional[str] = None
    alt_uom_ratio: Optional[float] = None


class MaterialOut(ORMModel):
    material_id: str
    code: str
    name: str
    uom: str
    category: Optional[str] = None
    stock_min: Optional[float] = None
    alt_uom: Optional[str] = None
    alt_uom_ratio: Optional[float] = None


# ---- Work Orders / Điều độ ----
class WorkOrderIn(BaseModel):
    brew_order_id: str
    wo_code: Optional[str] = None
    recipe_version_id: Optional[str] = None
    planned_qty: Optional[float] = None
    uom: Optional[str] = None
    line: Optional[str] = None
    # Dây chuyền nấu THẬT — không còn bắt buộc chọn lúc lập lệnh (bỏ theo yêu cầu 2026-08-31,
    # UI tự gán nếu Danh mục chỉ có đúng 1 dây chuyền); vẫn validate hợp lệ nếu có truyền lên.
    brewhouse_line_id: Optional[str] = None
    shift: str = "A"
    scheduled_date: Optional[date] = None
    priority: int = 5
    note: Optional[str] = None


class WoDispatchIn(BaseModel):
    """Phát mẻ — tạo `batch_count` Mẻ sản xuất (BatchExecution) liên tiếp đánh số từ
    `from_batch`, xem services/workorders.py::dispatch. Dây chuyền nấu/Recipe version KHÔNG
    còn chọn ở đây — lấy từ WorkOrder (chọn lúc lập lệnh). `tank_lm` (tùy chọn): tank lên men
    vật lý còn trống — nếu chọn, tự động gộp toàn bộ mẻ vừa phát vào 1 tank lên men mới."""
    from_batch: int
    batch_count: int = 1
    tank_lm: Optional[str] = None


# ---- Recipes ----
class RecipeIn(BaseModel):
    code: str
    name: str
    beer_type_id: str


class RecipeOut(ORMModel):
    recipe_id: str
    code: str
    name: str
    beer_type_id: str


class RecipeVersionQcItemIn(BaseModel):
    """1 chỉ tiêu chọn từ Danh mục (QCParameter) cho RecipeVersion — xem
    services/recipes.py::_resolve_qc_items."""
    param_id: str
    seq: int = 0
    mandatory: bool = True
    target_override: Optional[float] = None
    usl_override: Optional[float] = None
    lsl_override: Optional[float] = None


class RecipeVersionParamItemIn(BaseModel):
    """1 tham số chọn từ Danh mục (ProcessParameter) cho RecipeVersion — xem
    services/recipes.py::_resolve_param_items."""
    param_id: str
    seq: int = 0
    mandatory: bool = True
    phase_override: Optional[str] = None
    target_override: Optional[float] = None
    usl_override: Optional[float] = None
    lsl_override: Optional[float] = None


class RecipeVersionIn(BaseModel):
    product_id: str
    base_qty: float = 0.0
    base_uom: str = "L"
    # qc_items/param_items: nếu truyền (khác None), server resolve từ Danh mục rồi GHI ĐÈ
    # quality_checks/parameters bên dưới — không truyền thì giữ hành vi cũ (nhận thẳng
    # quality_checks/parameters tự do, tương thích ngược).
    qc_items: Optional[list[RecipeVersionQcItemIn]] = None
    param_items: Optional[list[RecipeVersionParamItemIn]] = None
    parameters: list[dict] = []
    materials: list[dict] = []
    quality_checks: list[dict] = []
    yield_steps: list[dict] = []
    procedure: list[dict] = []
    change_reason: Optional[str] = None


class RecipeVersionOut(ORMModel):
    version_id: str
    recipe_id: str
    product_id: str
    version_no: int
    state: str
    base_qty: float = 0.0
    base_uom: str = "L"
    parameters: list
    materials: list
    quality_checks: list
    yield_steps: list = []
    procedure: list = []
    change_reason: Optional[str] = None
    created_by: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    created_at: datetime
    is_used: bool = False


# ---- Formula (Công thức NVL mới — thay Recipe/RecipeVersion, xem models/formula.py) ----
class FormulaMaterialLineIn(BaseModel):
    # Đúng 1 trong 2 field — vật tư cụ thể HOẶC nhóm vật tư thay thế (validate ở
    # services/formula.py::_validate_materials, không validate ở đây để giữ thông báo lỗi
    # tiếng Việt rõ ràng theo đúng quy ước sẵn có của module này).
    material_code: Optional[str] = None
    alt_group_code: Optional[str] = None
    qty: float
    uom: str


class FormulaIn(BaseModel):
    code: str
    product_id: str
    note: Optional[str] = None
    process_reference_note: Optional[str] = None
    base_qty: float = 0.0
    base_uom: str = "L"
    materials: list[FormulaMaterialLineIn] = []


class FormulaOut(ORMModel):
    formula_id: str
    code: str
    product_id: str
    note: Optional[str] = None
    process_reference_note: Optional[str] = None
    base_qty: float = 0.0
    base_uom: str = "L"
    materials: list
    is_active: bool
    locked: bool
    locked_by: Optional[str] = None
    locked_at: Optional[datetime] = None
    created_by: Optional[str] = None
    created_at: datetime


class FormulaActivationLogOut(ORMModel):
    log_id: str
    formula_id: str
    product_id: str
    action: str
    note: Optional[str] = None
    changed_by: str
    changed_at: datetime


class TransitionIn(BaseModel):
    target: str
    reason: Optional[str] = None


class ChangeApproveIn(BaseModel):
    password: str
    change_reason: str


class YieldIn(BaseModel):
    step_key: str            # nau | len_men | loc | chiet
    step_no: int = 0
    input_qty: float = 0.0
    output_qty: float = 0.0
    uom: Optional[str] = None
    note: Optional[str] = None


# ---- Batches ----
class BatchIn(BaseModel):
    order_id: str
    recipe_version_id: str
    batch_code: Optional[str] = None
    planned_qty: Optional[float] = None
    allow_shortage: bool = False   # bỏ qua chặn thiếu tồn theo BOM
    work_order_id: Optional[str] = None   # Lệnh SX (điều độ) nguồn — hiện dây chuyền nấu/mã WO
    brewhouse_line_id: Optional[str] = None   # Dây chuyền nấu — mặc định theo Lệnh SX nếu có, chọn/sửa độc lập được


class BatchLineIn(BaseModel):
    brewhouse_line_id: Optional[str] = None   # Sửa Dây chuyền nấu sau khi mẻ đã tồn tại (bỏ chọn nếu None)


class BatchStartIn(BaseModel):
    start_at: datetime   # Sửa giờ bắt đầu mẻ trực tiếp — gọi lại được nhiều lần để sửa nếu bấm nhầm


class BatchFinishIn(BaseModel):
    end_at: Optional[datetime] = None   # None = dùng giờ hiện tại


class BatchActualQtyIn(BaseModel):
    actual_qty: float   # Nhập/sửa trực tiếp SL thực tế (VD lít dịch thực tế) — khác produce_lot


class BatchOut(ORMModel):
    batch_id: str
    batch_code: str
    batch_year: int
    order_id: str
    recipe_version_id: str
    product_id: str
    state: str
    quality_status: str
    planned_qty: float
    actual_qty: Optional[float] = None
    uom: str
    recipe_snapshot: dict
    actuals: list
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    version: int
    created_at: datetime
    ebr_locked: bool = False
    work_order_id: Optional[str] = None
    brewhouse_line_id: Optional[str] = None


class ActualIn(BaseModel):
    name: str
    param_id: Optional[str] = None     # tham số chọn từ Danh mục (ProcessParameter) qua công thức
    target: Optional[float] = None
    actual: Optional[float] = None
    unit: Optional[str] = None
    phase: Optional[str] = None
    lower: Optional[float] = None      # giới hạn lấy từ recipe_snapshot.parameters (mirror QC)
    upper: Optional[float] = None


class ConsumeIn(BaseModel):
    lot_id: str
    quantity: float
    allow_over: bool = False   # cho phép vượt định mức BOM (có phê duyệt)


# ---- Cấp phát NVL (dispense / backflush) ----
class DispenseLineIn(BaseModel):
    material_code: str
    quantity: float
    lot_id: Optional[str] = None       # None → tự chọn lô theo FEFO
    allow_over: bool = False
    reason: Optional[str] = None       # bắt buộc nếu lot_id KHÁC lô FIFO/FEFO gợi ý


class DispenseIn(BaseModel):
    lines: list[DispenseLineIn]
    note: Optional[str] = None


class BackflushIn(BaseModel):
    produced_qty: float


class AdjustActualIn(BaseModel):
    material_code: str
    new_actual: float
    reason: str


# ---- Tác vụ nền (jobs) ----
class JobIn(BaseModel):
    kind: str                          # ai_report | recall
    params: dict = {}


# ---- ISA-88 procedural ----
class PhaseStartIn(BaseModel):
    up: str
    op: str
    phase: str


class PhaseTransitionIn(BaseModel):
    target: str                        # running | held | complete | aborted
    values: dict = {}


# ---- Scheduling ----
class AutoScheduleIn(BaseModel):
    days: int = 10
    prod_hours: int = 48
    cip_hours: int = 4


# ---- WMS ----
class WmsWarehouseIn(BaseModel):
    code: str
    name: str
    address: Optional[str] = None
    load_order_sheet_type: Optional[str] = None


class WmsWarehouseUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    address: Optional[str] = None
    active: Optional[bool] = None
    load_order_sheet_type: Optional[str] = None


class WmsLocationIn(BaseModel):
    code: str
    name: str
    zone: Optional[str] = None
    kind: str = "bin"
    capacity: int = 10
    # Kho thành phẩm cha — optional ở schema để không phá các API call cũ (test/import) chưa
    # gửi trường này, nhưng UI (Danh mục vị trí kho) luôn bắt chọn khi khai báo vị trí mới.
    warehouse_id: Optional[str] = None


class WmsLocationUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    zone: Optional[str] = None
    kind: Optional[str] = None
    capacity: Optional[int] = None
    active: Optional[bool] = None
    warehouse_id: Optional[str] = None


class WmsLocationLayoutIn(BaseModel):
    # None = chưa xếp bố cục (gỡ khỏi sơ đồ) — khác WmsLocationUpdate, ở đây None LUÔN được áp
    # dụng (không bị bỏ qua) để cho phép gỡ vị trí ra khỏi lưới.
    row: Optional[int] = None
    col: Optional[int] = None


class WmsLocationSplitIn(BaseModel):
    parts: int = 4


class UnitBuildIn(BaseModel):
    finished_product_id: Optional[str] = None
    product_name: Optional[str] = None
    lot_code: Optional[str] = None
    total: float = 0            # tổng SL nhỏ (lon/keg) cần nhập — số dòng vỉ/keg tự tính từ pack_size
    pack_size: int = 24
    unit_type: str = "vi"        # vi | keg
    loc_id: Optional[str] = None  # bỏ trống -> chưa cất (xem "Cất vào vị trí"); nếu chọn, kiểm tra sức chứa
    reason: Optional[str] = None  # VD "Nhập tồn đầu" — gắn vào audit để lọc lại lịch sử
    received_at: Optional[str] = None  # bỏ trống -> hiện tại; giới hạn 15 ngày trừ khi is_opening_balance, xem _create_units()
    is_opening_balance: bool = False  # true -> chỉ admin được thực hiện, xem build_units()


class PutawayIn(BaseModel):
    loc_id: str


class UnitTransferIn(BaseModel):
    unit_ids: list[str]
    to_loc_id: str


class UnitDeleteIn(BaseModel):
    unit_ids: list[str]


class DecomposeBatchIn(BaseModel):
    product_name: str
    lot_code: Optional[str] = None
    # Loại đơn vị NGUỒN đem phân rã — mặc định "vi" để tương thích ngược, nhưng PHẢI là loại
    # có divide_by_pack_size=True trong Danh mục Loại đơn vị tồn kho (Vỉ, Két, Lốc...), xem
    # services/wms.py::decompose_batch. Không mặc định cứng "vi" ở tầng service vì 1 lô có thể
    # đồng thời có nhiều loại đơn vị (VD vừa Két vừa Chai) — phải chọn rõ loại nào.
    unit_type: str = "vi"
    # float chứ không phải int — lô đã bị chia lẻ một phần (VD sau relocate/decompose trước
    # đó) hoàn toàn có thể còn tồn dạng số lẻ (VD 0.625 vỉ); int sẽ làm FastAPI trả 422 ngay
    # cả khi người dùng nhập ĐÚNG số tối đa hiển thị trên UI (xem cùng lỗi ở RelocateBatchIn/
    # FreeIssueBatchIn bên dưới).
    count: float
    # Giới hạn phân rã trong 1 Kho thành phẩm — BẮT BUỘC nếu tài khoản bị giới hạn kho
    # (xem services/wms.py::_wh_scope_restricted), mirror ShipmentIn.warehouse_id.
    warehouse_id: Optional[str] = None


class DeleteByLotIn(BaseModel):
    product_name: str
    lot_code: Optional[str] = None
    unit_type: str
    # Dùng cho cả confirm_receipt_by_lot (Duyệt nhập kho theo lô) và delete_units_by_criteria
    # (Xóa theo lô) — BẮT BUỘC nếu tài khoản bị giới hạn kho, mirror DecomposeBatchIn.
    warehouse_id: Optional[str] = None


class UnitGroupUpdateIn(DeleteByLotIn):
    # Sửa lô vỉ/keg đã nhập kho (thủ công/tồn đầu) THEO TIÊU CHÍ nhóm, mirror DeleteByLotIn —
    # None = giữ nguyên field đó. new_lot_code đổi lot_code (khác lot_code ở DeleteByLotIn, dùng
    # để KHỚP lô hiện tại).
    new_lot_code: Optional[str] = None
    location_id: Optional[str] = None
    received_at: Optional[datetime] = None


class RelocateBatchIn(BaseModel):
    product_name: str
    lot_code: Optional[str] = None
    unit_type: str
    from_loc_id: Optional[str] = None
    to_loc_id: str
    count: float


class FreeIssueBatchIn(BaseModel):
    product_name: str
    lot_code: Optional[str] = None
    unit_type: str
    count: float
    reason: str


class ShipmentLineIn(BaseModel):
    product_name: str
    lot_code: Optional[str] = None
    unit_type: str
    quantity: int
    near_expiry_only: bool = False  # chỉ chọn vỉ/keg từ "Nhập bia cận date" (is_near_expiry=True)
    consigned_only: bool = False    # chỉ chọn vỉ/keg từ "Nhập bia gửi" (is_consigned=True)
    # normal | promo | return — RIÊNG TỪNG DÒNG (1 phiếu có thể gồm nhiều sản phẩm với loại
    # xuất khác nhau, cùng 1 nhà phân phối) — xem FinishedGoodsUnit.shipment_line_type.
    shipment_type: str = "normal"
    # Chọn đúng 1 VỊ TRÍ cụ thể để xuất (thay vì để hệ thống tự FIFO trên mọi vị trí của lô) —
    # dùng khi picker Xuất kho tách 1 lô có nhiều vị trí thành các dòng con theo vị trí (xem
    # views_ext.js renderLots). Để trống = giữ hành vi cũ (FIFO tự do trong lô/kho xuất).
    location_id: Optional[str] = None


class ShipmentIn(BaseModel):
    ship_to_id: str
    lines: list[ShipmentLineIn]
    warehouse_id: Optional[str] = None          # Kho xuất — bắt buộc nếu tài khoản bị giới hạn kho TP
    note: Optional[str] = None                 # Lý do xuất kho
    recipient_name: Optional[str] = None        # Họ tên người nhận hàng
    recipient_dept: Optional[str] = None        # Địa chỉ (bộ phận)
    driver_name: Optional[str] = None           # Lái xe
    vehicle_plate: Optional[str] = None         # Biển số xe
    vehicle_id: Optional[str] = None            # Liên kết ổn định tới Danh mục lái xe (báo cáo lượt xe)
    from_location: Optional[str] = None         # Xuất tại kho (ngăn lô)
    delivery_place: Optional[str] = None        # Địa điểm
    load_slip_id: Optional[str] = None          # Chọn từ Lệnh đóng hàng — khoá xe đó lại sau khi xuất


class ShipmentUpdate(BaseModel):
    """Sửa thông tin đầu phiếu xuất kho — chỉ các trường mô tả (không có ship_to_id/lines,
    không đụng tới số liệu tồn kho). Chặn sửa nếu phiếu đã được duyệt (confirmed_by)."""
    note: Optional[str] = None
    recipient_name: Optional[str] = None
    recipient_dept: Optional[str] = None
    driver_name: Optional[str] = None
    vehicle_plate: Optional[str] = None
    from_location: Optional[str] = None
    delivery_place: Optional[str] = None
    shipment_type: Optional[str] = None


class WmsTransferLineIn(BaseModel):
    """1 dòng trong phiếu điều chuyển nội bộ kho thành phẩm — mirror ShipmentLineIn nhưng KHÔNG
    có near_expiry_only/consigned_only/shipment_type (không có ý nghĩa cho luồng nội bộ, xem
    services/wms.py::create_transfer). Tên có tiền tố "Wms" để tránh trùng TransferIn (điều
    chuyển NVL Kho phân xưởng<->Kho công ty, xem services/warehouse.py) đã có sẵn ở dưới."""
    product_name: str
    lot_code: Optional[str] = None
    unit_type: str
    quantity: int
    # Vị trí kho NGUỒN của dòng này — frontend luôn gửi (đã tách picker theo từng vị trí) để
    # FIFO chỉ lấy đúng đơn vị đang ở vị trí đó, không lẫn qua vị trí khác cùng lô (xem
    # services/wms.py::create_transfer). Optional ở schema để không phá request cũ.
    location_id: Optional[str] = None


class WmsTransferIn(BaseModel):
    # Optional: bỏ trống -> đơn vị thành "chưa cất vị trí" (xem services/wms.py::create_transfer).
    to_location_id: Optional[str] = None
    lines: list[WmsTransferLineIn]
    note: Optional[str] = None
    driver_name: Optional[str] = None
    vehicle_plate: Optional[str] = None
    vehicle_id: Optional[str] = None


class WmsTransferUpdate(BaseModel):
    """Sửa thông tin đầu phiếu điều chuyển — mirror ShipmentUpdate, KHÔNG có to_location_id/lines
    (đổi vị trí đích/dòng hàng sau khi đã chuyển thật là vô nghĩa — phải Hoàn tác + lập phiếu
    mới). Chặn sửa nếu phiếu đã được duyệt (confirmed_by)."""
    note: Optional[str] = None
    driver_name: Optional[str] = None
    vehicle_plate: Optional[str] = None


class WmsTransferTripIn(BaseModel):
    """Km và số lít xăng của 1 chuyến điều chuyển — mirror ShipmentTripIn, chỉ điền được sau khi
    phiếu đã Duyệt (xem services/wms.py::update_transfer_trip)."""
    km: Optional[float] = None
    fuel_liters: Optional[float] = None


class NearExpiryEntryIn(BaseModel):
    finished_product_id: str
    quantity: int
    location_id: Optional[str] = None  # vị trí kho nhận — bỏ trống nếu chưa cất
    note: Optional[str] = None


class NearExpiryEntryUpdate(BaseModel):
    """Sửa bản khai "Nhập bia cận date" đang chờ duyệt — mọi trường tuỳ chọn (chỉ trường
    được gửi mới bị ghi đè, xem services/wms.py::update_near_expiry_entry)."""
    finished_product_id: Optional[str] = None
    quantity: Optional[int] = None
    location_id: Optional[str] = None
    note: Optional[str] = None


class ConsignedEntryIn(BaseModel):
    finished_product_id: str
    quantity: int
    location_id: str  # vị trí kho nhận — bắt buộc, không cho "chưa cất"
    vehicle_id: str    # biển số xe đã mang bia gửi về — bắt buộc
    note: Optional[str] = None


class ConsignedEntryUpdate(BaseModel):
    finished_product_id: Optional[str] = None
    quantity: Optional[int] = None
    location_id: Optional[str] = None
    vehicle_id: Optional[str] = None
    note: Optional[str] = None


class FactoryImportEntryIn(BaseModel):
    finished_product_id: str
    quantity: int
    location_id: str  # vị trí kho nhận — bắt buộc, không cho "chưa cất"
    factory_id: str    # nhà máy nguồn (Danh mục Nhà máy) — bắt buộc, dấu hiệu nhận biết nguồn gốc
    note: Optional[str] = None
    received_at: Optional[str] = None  # Ngày nhập — để trống = thời điểm khai báo


class FactoryImportEntryUpdate(BaseModel):
    finished_product_id: Optional[str] = None
    quantity: Optional[int] = None
    location_id: Optional[str] = None
    factory_id: Optional[str] = None
    note: Optional[str] = None
    received_at: Optional[str] = None


class ShipmentTripIn(BaseModel):
    """Km và số lít xăng của 1 chuyến xuất — chỉ điền được sau khi phiếu đã Duyệt (xem
    services/wms.py::update_shipment_trip)."""
    km: Optional[float] = None
    fuel_liters: Optional[float] = None


class LoadSlipHeaderUpdate(BaseModel):
    issuer_name: Optional[str] = None
    issuer_title: Optional[str] = None
    issuer_dept: Optional[str] = None
    recipient_name: Optional[str] = None
    recipient_title: Optional[str] = None
    recipient_unit: Optional[str] = None


class LoadOrderAddVehicleIn(BaseModel):
    load_slip_id: str


class LoadSlipLineIn(BaseModel):
    product_name: str
    uom: str
    quantity: float
    is_promo: bool = False
    note: Optional[str] = None
    product_code: Optional[str] = None
    finished_product_id: Optional[str] = None


class LoadSlipLinesUpdate(BaseModel):
    lines: list[LoadSlipLineIn]


class VehicleIn(BaseModel):
    plate: str
    driver_name: Optional[str] = None
    driver_short_name: Optional[str] = None
    capacity_kg: Optional[float] = None
    pallet_capacity: Optional[int] = None
    phone: Optional[str] = None
    team: Optional[str] = None


class VehicleUpdate(BaseModel):
    plate: Optional[str] = None
    driver_name: Optional[str] = None
    driver_short_name: Optional[str] = None
    capacity_kg: Optional[float] = None
    pallet_capacity: Optional[int] = None
    phone: Optional[str] = None
    team: Optional[str] = None
    active: Optional[bool] = None


# ---- Dây chuyền (line master) ----
class LineIn(BaseModel):
    code: str
    name: str
    kind: str = "line"                 # line | tank | tank_bbt | brewhouse
    area: Optional[str] = None
    ideal_rate_per_min: float = 0.0
    capacity_uom: Optional[str] = None   # đơn vị công suất (kind="line"), VD "lon/phút"
    volume: Optional[float] = None       # thể tích (kind="tank"/"tank_bbt")
    volume_uom: Optional[str] = None     # đơn vị thể tích, VD "hl"
    usable_pct: Optional[float] = None   # % khả dụng (kind="tank"/"tank_bbt")
    identification_code: Optional[str] = None  # mã nhận dạng dây chuyền (kind="line")


class LineUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    area: Optional[str] = None
    ideal_rate_per_min: Optional[float] = None
    capacity_uom: Optional[str] = None
    volume: Optional[float] = None
    volume_uom: Optional[str] = None
    usable_pct: Optional[float] = None
    identification_code: Optional[str] = None


# ---- Bao bì tuần hoàn ----
class PackagingTypeIn(BaseModel):
    code: str
    name: str
    category: str                      # vo_chai | ket_gong | keg
    material: Optional[str] = None
    volume_l: Optional[float] = Field(default=None, ge=0)
    deposit: float = Field(default=0.0, ge=0)
    on_hand: float = Field(default=0.0, ge=0)
    in_circulation: float = Field(default=0.0, ge=0)


class PackagingMoveIn(BaseModel):
    pkg_id: str
    kind: str                          # nhap | xuat | thu_hoi | loai_bo | kiem_ke
    qty: float = Field(default=0.0, ge=0)
    ref: Optional[str] = None
    note: Optional[str] = None


class EbrSignIn(BaseModel):
    password: str
    meaning: str
    reason: Optional[str] = None


class EbrLockIn(BaseModel):
    password: str
    reason: Optional[str] = None


class ProduceIn(BaseModel):
    lot_code: str
    quantity: float
    lot_type: str = "brew"


# ---- Materials / Lots ----
class LotIn(BaseModel):
    lot_code: str
    lot_year: Optional[int] = None
    material_id: Optional[str] = None
    product_id: Optional[str] = None
    lot_type: str = "material"
    supplier_lot: Optional[str] = None
    quantity: float = 0.0
    uom: str = "kg"
    expiry: Optional[datetime] = None
    location: Optional[str] = None


class LotOut(ORMModel):
    lot_id: str
    lot_code: str
    lot_year: int
    material_id: Optional[str] = None
    product_id: Optional[str] = None
    lot_type: str
    supplier_lot: Optional[str] = None
    supplier_id: Optional[str] = None
    kcs_lot_no: Optional[str] = None
    unit_price: Optional[float] = None
    quantity: float
    uom: str
    status: str
    expiry: Optional[datetime] = None
    location: Optional[str] = None
    location_id: Optional[str] = None
    workshop_location_id: Optional[str] = None
    created_at: datetime
    # Chỉ set khi lô này được TÁCH ra từ 1 lô khác lúc điều chuyển 1 phần số lượng (xem
    # GenealogyEdge relation=SPLIT, routers/materials.py::list_lots) — mã lô gốc để hiển thị
    # ngay "Tách từ lô X" ở mọi màn, không bắt người dùng phải vào Truy xuất mới thấy liên kết.
    split_from_lot_code: Optional[str] = None

    @field_validator("quantity")
    @classmethod
    def _round_quantity(cls, v: float) -> float:
        # Số lượng tồn tích luỹ sai số dấu phẩy động qua nhiều lần cộng/trừ một phần (tách lô,
        # điều chuyển, xuất từng phần...) nên hay ra dạng "15.399999999999999" — làm tròn ở tầng
        # API (không sửa giá trị đã lưu trong DB) để MỌI nơi hiển thị lô (dropdown chọn lô, bảng
        # tồn kho...) đều sạch, không phải vá lại từng màn hình một.
        return round(v, 4) if v is not None else v


class MaterialLocationIn(BaseModel):
    code: str
    name: str
    zone: Optional[str] = None
    active: bool = True
    scope: str = "cong_ty"  # "cong_ty" | "phan_xuong" | "ca_hai"


class MaterialLocationOut(ORMModel):
    loc_id: str
    code: str
    name: str
    zone: Optional[str] = None
    active: bool
    scope: str


class LotRelocateIn(BaseModel):
    location_id: str


class WorkshopLotRelocateIn(BaseModel):
    workshop_location_id: str


# ---- Quality ----
class ResultIn(BaseModel):
    scope_type: str = "batch"
    scope_id: str
    parameter: str
    sample_id: Optional[str] = None
    method: Optional[str] = None
    instrument: Optional[str] = None
    value: Optional[float] = None
    value_text: Optional[str] = None  # chỉ tiêu kiểu "text" — ghi chú tự do, không so target/USL/LSL
    ca_value: Optional[float] = None  # giá trị in trên bao bì/CA của NCC — chỉ tham khảo, không tính vào pass/fail
    unit: Optional[str] = None
    lower_limit: Optional[float] = None
    upper_limit: Optional[float] = None


class ResultOut(ORMModel):
    result_id: str
    sample_id: str
    scope_type: str
    scope_id: str
    parameter: str
    method: Optional[str] = None
    instrument: Optional[str] = None
    value: Optional[float] = None
    value_text: Optional[str] = None
    ca_value: Optional[float] = None
    unit: Optional[str] = None
    lower_limit: Optional[float] = None
    upper_limit: Optional[float] = None
    status: str
    recorded_by: Optional[str] = None
    approved_by: Optional[str] = None
    recorded_at: datetime


class HoldIn(BaseModel):
    scope_type: str = "batch"
    scope_id: str
    on_hold: bool
    reason: Optional[str] = None
    parameter: Optional[str] = None


class DeviationIn(BaseModel):
    scope_type: str = "batch"
    scope_id: str
    severity: str = "minor"
    reason: str
    parameter: Optional[str] = None
    due_date: Optional[date] = None


class DeviationOut(ORMModel):
    deviation_id: str
    deviation_code: str
    scope_type: str
    scope_id: str
    severity: str
    reason: str
    state: str
    investigation: Optional[str] = None
    disposition: Optional[str] = None
    opened_by: Optional[str] = None
    approved_by: Optional[str] = None
    opened_at: datetime
    closed_at: Optional[datetime] = None
    parameter: Optional[str] = None
    due_date: Optional[date] = None
    close_note: Optional[str] = None


class DeviationTransitionIn(BaseModel):
    target: str
    investigation: Optional[str] = None
    disposition: Optional[str] = None
    close_note: Optional[str] = None


# ---- Quality hardcore: CAPA + LIMS ----
class CapaIn(BaseModel):
    title: str
    deviation_id: Optional[str] = None
    scope_type: Optional[str] = None
    scope_id: Optional[str] = None
    capa_type: str = "corrective"     # corrective | preventive
    severity: str = "minor"
    root_cause: Optional[str] = None
    action_plan: Optional[str] = None
    owner: Optional[str] = None
    due_date: Optional[date] = None


class CapaTransitionIn(BaseModel):
    target: str
    root_cause: Optional[str] = None
    action_plan: Optional[str] = None
    effectiveness: Optional[str] = None
    effectiveness_checked_at: Optional[date] = None
    kcs_approval_note: Optional[str] = None
    close_note: Optional[str] = None


class SampleIn(BaseModel):
    scope_type: str = "batch"
    scope_id: str
    sample_code: Optional[str] = None
    stage: Optional[str] = None
    test_set: Optional[str] = None
    note: Optional[str] = None


class SampleTransitionIn(BaseModel):
    target: str   # in_test | completed


# ---- Metrics: readings + OEE ----
class ReadingIn(BaseModel):
    parameter: str
    value: float
    unit: Optional[str] = None
    ts: Optional[datetime] = None


class ReadingOut(ORMModel):
    reading_id: str
    batch_id: str
    parameter: str
    value: float
    unit: Optional[str] = None
    ts: datetime
    quality: str


class OEEIn(BaseModel):
    line: str
    shift: str = "A"
    shift_date: Optional[datetime] = None
    planned_time_min: float
    downtime_min: float = 0.0
    ideal_rate_per_min: float
    total_count: int = 0
    good_count: int = 0
    # Nhập tách SP tốt/SP lỗi (đúng cách file OPI gốc nhập "SẢN PHẨM TỐT"/"SẢN PHẨM LỖI" riêng
    # biệt) — khi có, total_count tự tính = good_count + reject_count (bỏ qua total_count nhập
    # tay để tránh lệch số).
    reject_count: Optional[int] = None
    downtime_reasons: list[dict] = []


class DowntimeIn(BaseModel):
    line: str
    reason_catalog_id: str
    equipment_id: Optional[str] = None
    shift: str = "A"
    shift_date: Optional[datetime] = None
    # Dừng từ/đến (tự tính phút) — hoặc nhập thẳng minutes nếu không rõ giờ chính xác.
    from_time: Optional[datetime] = None
    to_time: Optional[datetime] = None
    minutes: float = 0.0
    error_code: Optional[str] = None  # chỉ dùng khi lý do thuộc nhóm Breakdown
    note: Optional[str] = None


class OeeReasonCatalogIn(BaseModel):
    line_code: Optional[str] = None
    category: str
    sub_code: str
    sub_label: str
    machine_position: Optional[str] = None
    target_pct: float = 0.0
    active: bool = True
    sort_order: int = 0


class OeeReasonCatalogUpdate(BaseModel):
    sub_label: Optional[str] = None
    target_pct: Optional[float] = None
    machine_position: Optional[str] = None
    active: Optional[bool] = None
    sort_order: Optional[int] = None


class OeeRcfaIn(BaseModel):
    line_code: str
    machine: str
    part: Optional[str] = None
    stop_at: Optional[datetime] = None
    duration_min: float = 0.0
    failure_function: Optional[str] = None
    prior_signs: Optional[str] = None
    technician: Optional[str] = None
    repair_min: Optional[float] = None
    wait_min: Optional[float] = None
    description: Optional[str] = None
    replaced_parts: list[str] = []
    working_principle: Optional[str] = None
    failure_mechanism: Optional[str] = None
    analyst: Optional[str] = None
    factor: Optional[str] = None
    five_whys: list[dict] = []
    category_4m1e: Optional[str] = None
    corrective_action: Optional[str] = None
    preventive_action: Optional[str] = None
    executor: Optional[str] = None
    complete_date: Optional[datetime] = None
    checker: Optional[str] = None
    downtime_event_id: Optional[str] = None   # gắn ngược vào sự kiện dừng máy khi tạo


class OeeRcfaRecheckIn(BaseModel):
    week_offset: int
    checked: bool
    note: Optional[str] = None


class OeeMinorStopTallyIn(BaseModel):
    reason_id: str
    iso_year: int
    iso_week: int
    shift: str
    count: int = 0


class OEEOut(BaseModel):
    oee_id: str
    line: str
    shift: str
    shift_date: datetime
    planned_time_min: float
    downtime_min: float
    run_time_min: float
    ideal_rate_per_min: float
    total_count: int
    good_count: int
    reject_count: int
    downtime_reasons: list
    availability: float
    performance: float
    quality: float
    oee: float


# ---- Warehouse ----
class ReceiptIn(BaseModel):
    lot_code: Optional[str] = None  # bỏ trống -> hệ thống tự sinh mã lô tăng dần theo năm
    material_id: Optional[str] = None
    quantity: float
    uom: str = "kg"
    lot_type: str = "material"
    supplier_lot: Optional[str] = None
    supplier_id: Optional[str] = None
    unit_price: Optional[float] = None
    kcs_lot_no: Optional[str] = None  # số lô KCS — chỉ áp dụng khi tạo lô MỚI, xem receive()
    expiry: Optional[datetime] = None
    received_at: Optional[datetime] = None  # bỏ trống -> hiện tại; giới hạn trong 15 ngày gần nhất, xem receive()
    location: str = "Kho công ty"
    location_id: Optional[str] = None  # vị trí cất cụ thể — bắt buộc khi tạo lô mới tại Kho công ty, xem receive()
    reason: Optional[str] = None
    ref_doc: Optional[str] = None
    is_opening_balance: bool = False  # true -> chỉ admin được thực hiện, xem receive()


class ReceiptUpdateIn(BaseModel):
    """Sửa 1 lượt nhập kho đã ghi — CHỈ áp dụng khi lô CHƯA bị xuất/chuyển/tiêu thụ (xem
    services/warehouse.py::update_receipt). Mọi field đều tuỳ chọn — chỉ field nào được gửi
    lên mới bị ghi đè (None nghĩa là "không đổi", KHÁC với xóa giá trị hiện có)."""
    quantity: Optional[float] = None
    supplier_id: Optional[str] = None
    unit_price: Optional[float] = None
    kcs_lot_no: Optional[str] = None
    supplier_lot: Optional[str] = None
    expiry: Optional[datetime] = None
    reason: Optional[str] = None


class IssueIn(BaseModel):
    lot_id: str
    quantity: float
    mode: str = "tu_do"   # de_nghi | tu_do
    reason: Optional[str] = None
    ref_doc: Optional[str] = None


class ReturnIn(BaseModel):
    lot_id: str
    quantity: float
    reason: Optional[str] = None


class TransferIn(BaseModel):
    lot_id: str
    quantity: float
    location_to: str
    reason: Optional[str] = None


class MaterialRequestLineIn(BaseModel):
    material_id: str
    quantity: float = Field(gt=0)
    uom: str = "kg"
    preferred_lot_id: Optional[str] = None


class MaterialRequestIn(BaseModel):
    """1 phiếu đề nghị nhận kho — có thể gồm nhiều dòng vật tư khác nhau, tuỳ chọn gắn với
    1 Lệnh nấu/Lệnh lọc lớn (source_type/source_id) chỉ để tham chiếu/báo cáo."""
    lines: list[MaterialRequestLineIn] = Field(min_length=1)
    note: Optional[str] = None
    source_type: Optional[str] = None   # brew_order | filter_master_order
    source_id: Optional[str] = None


class MaterialRequestLineOut(ORMModel):
    line_id: str
    request_id: str
    seq: int
    material_id: str
    quantity: float
    uom: str
    preferred_lot_id: Optional[str] = None
    status: str
    fulfilled_lot_id: Optional[str] = None
    fulfilled_qty: Optional[float] = None
    fulfilled_by: Optional[str] = None
    fulfilled_at: Optional[datetime] = None
    reason: Optional[str] = None
    fifo_ok: Optional[bool] = None


class MaterialRequestOut(ORMModel):
    request_id: str
    request_code: str
    note: Optional[str] = None
    requested_by: Optional[str] = None
    requested_at: datetime
    source_type: Optional[str] = None
    source_id: Optional[str] = None
    source_label: Optional[str] = None
    lines: list[MaterialRequestLineOut] = []


class SourceMaterialLineOut(BaseModel):
    """1 dòng nhu cầu NVL xem trước từ Lệnh nấu/Lệnh lọc lớn — dùng để tự động điền sẵn
    phiếu đề nghị nhận kho (xem services/warehouse.py::preview_source_materials). Dòng
    Nhóm vật tư thay thế có is_group=True, material_id=None — frontend không tự nạp thẳng
    vào giỏ, phải cảnh báo thủ kho tự chọn 1 mã cụ thể trong member_material_ids."""
    material_id: Optional[str] = None
    material_code: Optional[str] = None
    material_name: Optional[str] = None
    uom: str
    quantity: float
    is_group: bool = False
    group_code: Optional[str] = None
    member_material_ids: list[str] = []


class RequestFulfillIn(BaseModel):
    lot_id: str
    quantity: float
    location_to: str = "Kho phân xưởng"


class RequestRejectIn(BaseModel):
    reason: Optional[str] = None


class RequestFulfillAllIn(BaseModel):
    location_to: str = "Kho phân xưởng"


class TransferPxRequestIn(BaseModel):
    lot_id: str
    quantity: float
    reason: Optional[str] = None


class TransferPxRejectIn(BaseModel):
    reason: Optional[str] = None


class TransferPxRequestOut(ORMModel):
    request_id: str
    request_code: str
    lot_id: str
    quantity: float
    uom: str
    reason: Optional[str] = None
    status: str
    movement_id: Optional[str] = None
    reversed: bool
    created_by: Optional[str] = None
    created_at: datetime
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    rejected_by: Optional[str] = None
    rejected_at: Optional[datetime] = None
    reject_reason: Optional[str] = None


class TransferKcPxRequestIn(BaseModel):
    lot_id: str
    quantity: float
    reason: Optional[str] = None


class TransferKcPxRejectIn(BaseModel):
    reason: Optional[str] = None


class TransferKcPxApproveIn(BaseModel):
    workshop_location_id: str


class TransferKcPxRequestOut(ORMModel):
    request_id: str
    request_code: str
    lot_id: str
    quantity: float
    uom: str
    reason: Optional[str] = None
    status: str
    movement_id: Optional[str] = None
    workshop_location_id: Optional[str] = None
    reversed: bool
    created_by: Optional[str] = None
    created_at: datetime
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    rejected_by: Optional[str] = None
    rejected_at: Optional[datetime] = None
    reject_reason: Optional[str] = None


class SangNgangRejectIn(BaseModel):
    reason: Optional[str] = None


class SangNgangUpdateIn(BaseModel):
    """Sửa 1 đề nghị "Xuất sang ngang" — CHỈ áp dụng khi CHƯA được Kho phân xưởng duyệt (xem
    services/warehouse.py::update_sang_ngang). Mọi field tuỳ chọn — chỉ field nào gửi lên mới
    bị ghi đè."""
    quantity: Optional[float] = None
    uom: Optional[str] = None
    supplier_id: Optional[str] = None
    unit_price: Optional[float] = None
    kcs_lot_no: Optional[str] = None
    supplier_lot: Optional[str] = None
    expiry: Optional[datetime] = None
    reason: Optional[str] = None


class SangNgangRequestOut(ORMModel):
    request_id: str
    request_code: str
    lot_id: str
    quantity: float
    uom: str
    reason: Optional[str] = None
    status: str
    movement_id: Optional[str] = None
    reversed: bool
    created_by: Optional[str] = None
    created_at: datetime
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    rejected_by: Optional[str] = None
    rejected_at: Optional[datetime] = None
    reject_reason: Optional[str] = None
    can_edit: bool = True


class TransferToFactoryIn(BaseModel):
    lot_id: str
    quantity: float
    factory_id: str
    reason: Optional[str] = None


class FactoryLocationIn(BaseModel):
    code: str
    name: str
    address: Optional[str] = None
    contact: Optional[str] = None
    active: bool = True


class FactoryLocationOut(ORMModel):
    factory_id: str
    code: str
    name: str
    address: Optional[str] = None
    contact: Optional[str] = None
    active: bool


class ReturnToSupplierIn(BaseModel):
    lot_id: str
    quantity: float
    reason: str


class StockMovementOut(ORMModel):
    movement_id: str
    movement_type: str
    material_id: Optional[str] = None
    lot_id: Optional[str] = None
    lot_code: Optional[str] = None
    quantity: float
    uom: str
    location_from: Optional[str] = None
    location_to: Optional[str] = None
    mode: Optional[str] = None
    reason: Optional[str] = None
    ref_doc: Optional[str] = None
    actor: Optional[str] = None
    ts: datetime
    reversed: bool
    reversal_of: Optional[str] = None
    destination_factory_id: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None


# ---- Kiểm kê định kỳ (cycle count) ----
class StockCountCreateIn(BaseModel):
    location: Optional[str] = None  # lọc theo Kho công ty/phân xưởng — None = toàn bộ
    start_date: Optional[datetime] = None  # ngày bắt đầu kiểm kê (khai báo tay, khác created_at)
    end_date: Optional[datetime] = None  # ngày kết thúc kiểm kê (khai báo tay, khác posted_at)
    note: Optional[str] = None


class StockCountLineUpdateIn(BaseModel):
    line_id: str
    counted_qty: Optional[float] = None
    note: Optional[str] = None


class StockCountLinesIn(BaseModel):
    lines: list[StockCountLineUpdateIn] = Field(min_length=1)


# ---- Energy ----
class EnergyGroupIn(BaseModel):
    code: str
    name: str
    unit: str = "kWh"


class EnergyAreaIn(BaseModel):
    code: str
    name: str


class EnergyReadingIn(BaseModel):
    day: Optional[date] = None
    group_id: str
    area_id: Optional[str] = None
    value: float
    note: Optional[str] = None


# ---- Maintenance & Calibration ----
class EquipmentIn(BaseModel):
    code: str
    name: str
    eq_type: Optional[str] = None
    system: Optional[str] = None
    location: Optional[str] = None
    status: str = "running"


class SparePartIn(BaseModel):
    code: str
    name: str
    uom: str = "cái"
    stock: float = 0.0
    stock_min: float = 0.0


class IncidentIn(BaseModel):
    equipment_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    severity: str = "minor"
    status: str = "open"
    downtime_min: float = 0.0


class MaintenancePlanIn(BaseModel):
    equipment_id: str
    plan_type: str = "bao_tri"
    scheduled_date: date
    note: Optional[str] = None
    status: str = "planned"


class CalibrationIn(BaseModel):
    equipment_id: Optional[str] = None
    name: str
    calib_type: str = "hieu_chuan_tbd"
    last_date: Optional[date] = None
    due_date: date
    interval_months: int = 12
    result: Optional[str] = None
    status: str = "valid"


# ---- Process / Yeast ----
class ChemicalUsageIn(BaseModel):
    batch_id: Optional[str] = None
    stage: str = "nau"
    chemical: str
    quantity: float
    uom: str = "kg"
    note: Optional[str] = None


class YeastLotIn(BaseModel):
    code: str
    strain: str = "W-34/70"
    generation: int = 1
    source_tank: Optional[str] = None
    source_batch_id: Optional[str] = None
    quantity: float = 0.0
    uom: str = "L"
    viability: Optional[float] = None
    vitality: Optional[float] = None
    status: str = "available"


class YeastIssueIn(BaseModel):
    batch_id: Optional[str] = None
    quantity: float


# ---- Brewing (Nấu-Lọc-Chiết chi tiết) ----
class MaterialReceiptIn(BaseModel):
    mskt: Optional[str] = None
    receipt_date: Optional[datetime] = None
    material_name: str
    lot_pm: Optional[str] = None
    lot_kcs: Optional[str] = None
    quantity: float = 0.0
    uom: str = "kg"
    location: Optional[str] = None
    note: Optional[str] = None
    supplier: Optional[str] = None
    has_indicators: bool = False


class BrewIn(BaseModel):
    brew_code: str
    brew_date: Optional[datetime] = None
    wort_type: str
    product_id: Optional[str] = None   # loại bia — quyết định nhóm chỉ tiêu áp dụng
    volume_hl: float = 0.0
    original_extract: Optional[float] = None
    plato: Optional[float] = None
    note: Optional[str] = None
    # Gán ngay vào lô lên men lúc tạo mẻ nấu — tạo mới FermentRecord nếu lm_code chưa có,
    # hoặc gộp vào lô LM đã có (1 tank có thể nhận nhiều mẻ nấu).
    tank_lm: Optional[str] = None
    lm_code: Optional[str] = None
    yeast_gen: Optional[str] = None
    # Lệnh nấu (BrewOrder) làm cha — bắt buộc (xem services/brew_order.py::create_brew_record).
    brew_order_id: Optional[str] = None


class BrewOrderMaterialLineIn(BaseModel):
    seq: Optional[int] = None
    stt_label: Optional[str] = None
    is_header: bool = False
    material_id: Optional[str] = None
    material_name: Optional[str] = None
    uom: Optional[str] = None
    qty_per_batch: Optional[float] = None
    qty_total: Optional[float] = None
    unit_price: Optional[float] = None


class MemberQtySplitIn(BaseModel):
    qty_from_company: Optional[float] = None
    qty_from_workshop: Optional[float] = None


class BrewLineQtySplitIn(BaseModel):
    """SL thực xuất người lập lệnh nấu tự sửa lại (đè lên gợi ý — xem
    services/brew_order.py::_suggest_qty_split), key trong material_qty_overrides là
    str(seq) của dòng NVL tương ứng (đúng thứ tự trong Công thức đã chọn).
    selected_material_codes: BẮT BUỘC với dòng khai định mức riêng từng thành viên (member_qty)
    — chọn những mã áp dụng cho lệnh nấu này (xem services/brew_order.py::_build_group_line/
    _validate_member_selection); None = chưa chọn (nhóm "single" sẽ bị chặn tạo lệnh).
    member_qty_splits: SL lấy Company/Workshop RIÊNG cho từng mã đã chọn của dòng member_qty
    (key = material_code) — mirror qty_from_company/qty_from_workshop ở trên nhưng áp dụng cho
    TỪNG thành viên thay vì cho cả dòng (dòng member_qty không có 1 con số Nhu cầu chung để tách)."""
    qty_from_company: Optional[float] = None
    qty_from_workshop: Optional[float] = None
    selected_material_codes: Optional[list[str]] = None
    member_qty_splits: dict[str, MemberQtySplitIn] = {}


class BrewOrderIn(BaseModel):
    """Lệnh sản xuất (nấu) — 1 dịch bia, đủ phần hành chính (Người ra lệnh/Thực hiện/Xuất
    kho/Căn cứ/Thời gian/An toàn) ngay trên chính lệnh."""
    order_code: str
    product_id: Optional[str] = None
    product_desc: Optional[str] = None
    recipe_version_id: Optional[str] = None
    planned_batch_count: int = 1
    planned_volume_hl: float = 0.0
    volume_tolerance_hl: float = 0.0
    bx_min: Optional[float] = None
    bx_max: Optional[float] = None
    tank_lm: Optional[str] = None
    batch_range_from: Optional[int] = None
    batch_range_to: Optional[int] = None
    issued_by: Optional[str] = None
    executor_unit: Optional[str] = "Phân xưởng bia Đông Mai"
    warehouse_keeper: Optional[str] = "Thủ kho"
    reference_note: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    safety_note: Optional[str] = None
    auto_from_bom: bool = True
    lines: list[BrewOrderMaterialLineIn] = []
    material_qty_overrides: dict[str, BrewLineQtySplitIn] = {}


class BrewBatchIn(BaseModel):
    batch_code: str   # số mẻ Braumat — bắt buộc số nguyên dương, duy nhất trong năm (xem add_brew_batch)
    line_id: str      # dây chuyền/nhà nấu (ProductionLine.kind="brewhouse") — bắt buộc, xem add_brew_batch
    seq: Optional[int] = None
    note: Optional[str] = None
    started_at: Optional[datetime] = None   # mặc định giờ hiện tại nếu không truyền (xem add_brew_batch)

    @field_validator("batch_code")
    @classmethod
    def _batch_code_must_be_positive_int(cls, v: str) -> str:
        v = v.strip()
        if not v.isdigit() or int(v) <= 0:
            raise ValueError("Mã mẻ phải là số nguyên dương (VD: 123).")
        return v


class BrewBatchBulkIn(BaseModel):
    """Tạo N mẻ 1 lần thuộc cùng 1 mã nấu — mã mẻ tự sinh liên tiếp, không nhập tay từng mã
    (xem services/brew_order.py::create_brew_batches_bulk). interval_minutes: khoảng cách giữa
    giờ bắt đầu 2 mẻ liên tiếp (mặc định 90 phút, mirror chu kỳ nấu thật) — KHÔNG dùng chung
    1 giờ bắt đầu cho cả loạt."""
    count: int
    line_id: str
    started_at: Optional[datetime] = None
    interval_minutes: int = 90
    note: Optional[str] = None

    @field_validator("count")
    @classmethod
    def _count_must_be_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Số mẻ phải >= 1.")
        return v


class FinishIn(BaseModel):
    """Vận hành chọn tay giờ kết thúc (mặc định giờ hiện tại nếu không truyền) — gọi lại
    được nhiều lần để sửa giờ nếu bấm nhầm, không phải hành động một chiều."""
    ended_at: Optional[datetime] = None


class BrewBatchStartIn(BaseModel):
    """Sửa giờ bắt đầu mẻ nấu — bắt buộc truyền giá trị (khác FinishIn không có mặc định
    "giờ hiện tại" vì started_at đã có giá trị từ lúc tạo mẻ, sửa là có chủ đích)."""
    started_at: datetime


class BrewBatchCodeIn(BaseModel):
    """Đổi lại Mã mẻ sau khi đã tạo (VD gõ nhầm số mẻ Braumat) — cùng ràng buộc như lúc tạo
    (số nguyên dương, duy nhất trong năm), xem routers/brewing.py::update_brew_batch_code."""
    batch_code: str

    @field_validator("batch_code")
    @classmethod
    def _batch_code_must_be_positive_int(cls, v: str) -> str:
        v = v.strip()
        if not v.isdigit() or int(v) <= 0:
            raise ValueError("Mã mẻ phải là số nguyên dương (VD: 123).")
        return v


class BrewBatchDetailsIn(BaseModel):
    """Sửa Dây chuyền/Ghi chú của 1 mẻ đã tạo — mirror BrewBatchIn.line_id/note, tách riêng
    khỏi batch_code/started_at/ended_at (đã có endpoint sửa riêng), xem routers/brewing.py::
    update_brew_batch_details. Cả 2 field tuỳ chọn (exclude_unset) — chỉ đổi field nào gửi lên."""
    line_id: Optional[str] = None
    note: Optional[str] = None


class FinishFilterTankIn(FinishIn):
    """Kết thúc lọc CHO 1 TANK trong lệnh lọc (không phối chỉ có 1 tank/dòng; phối có nhiều
    dòng, kết thúc riêng từng dòng) — Dịch nha lọc + Nước bài khí của dòng đó điền lúc này;
    FilterRecord tổng hợp (sum) các dòng để ra Sản lượng lọc (xem _sync_filter_aggregate).
    batch_number/order_number bắt buộc mỗi lần gọi (xem finish_filter_tank) — thuộc về cả
    FilterRecord (không phải riêng dòng tank này), gọi lại nhiều lần với cùng giá trị để sửa
    giờ/số liệu không bị coi là trùng."""
    v_dich_hl: Optional[float] = None
    nuoc_bai_khi_hl: Optional[float] = None
    batch_number: Optional[str] = None
    order_number: Optional[str] = None
    batch_seq_no: Optional[str] = None


class FinishBottleIn(FinishIn):
    """Kết thúc chiết — Ca 1/2/3 + V cấp chiết/hl không bắt buộc lúc tạo, điền lúc bấm
    "Kết thúc" (mirror FinishFilterTankIn/finish_filter_tank). `mismatch_reason` bắt buộc nếu
    SL ca1+ca2+ca3 (quy đổi ra hl qua FinishedProduct.unit_volume_l) lệch quá nhiều so với
    V cấp chiết/hl đã nhập — xem routers/brewing.py::finish_bottle."""
    v_cap_chiet_hl: Optional[float] = None
    ca1: Optional[float] = None
    ca2: Optional[float] = None
    ca3: Optional[float] = None
    mismatch_reason: Optional[str] = None


class FilterOrderMaterialLineIn(BaseModel):
    """1 dòng vật tư (VD: bột trợ lọc) dùng cho lệnh lọc — chọn từ Danh mục vật tư HOẶC 1
    Nhóm vật tư thay thế (alt_group_code, đúng 1 trong 2 — validate ở service), số lượng cần
    được kiểm tra ngay lúc lập lệnh (xem services/filter_order.py::create_order)."""
    material_id: Optional[str] = None
    alt_group_code: Optional[str] = None
    quantity: float
    unit_price: Optional[float] = None


class FilterOrderIn(BaseModel):
    """Lệnh lọc — lập trước, bắt buộc chọn 1 lệnh CHƯA DÙNG khi tạo bản ghi lọc
    (xem FilterIn.filter_order_id, routers/brewing.py::add_filter)."""
    order_code: str
    blend_mode: str = "khong_phoi"   # khong_phoi | phoi
    tank_ferment_ids: list[str]
    note: Optional[str] = None
    lines: list[FilterOrderMaterialLineIn] = []
    kcs_lot_no: Optional[str] = None
    planned_volume_hl: float = 0.0
    volume_tolerance_hl: float = 0.0
    # Loại bia — chỉ bắt buộc (ở tầng service) khi các tank chọn thuộc >1 Loại bia khác
    # nhau; nếu cùng 1 Loại bia (hoặc chỉ 1 tank) thì tự suy ra, bỏ qua field này.
    beer_type_id: Optional[str] = None
    # Sản phẩm đích (SKU, tuỳ chọn) — cùng 1 Loại bia vẫn có thể cần chỉ tiêu Lọc khác nhau
    # theo hình thức đóng gói đích (VD Legend chai lọc khác Legend tươi). Không tự suy ra,
    # người lập lệnh tự chọn nếu cần phân biệt.
    finished_product_id: Optional[str] = None


class FilterSubOrderTankIn(BaseModel):
    """1 tank NGUỒN trong 1 lệnh lọc nhỏ — mỗi tank tự khai báo thể tích dịch lọc kế hoạch
    RIÊNG; FilterSubOrderIn không còn planned_volume_hl tổng — tổng = cộng dồn các tank.
    tank_type="cct" (tank lên men, mặc định, bắt buộc ferment_id) hoặc "bbt" (tank thành
    phẩm ĐÃ LỌC XONG — lọc lại, bắt buộc source_bbt_code + reason). Validate chéo (field
    nào bắt buộc theo tank_type, reason không được rỗng khi bbt, v.v.) ở tầng service —
    xem services/filter_order.py::_validate_tanks."""
    tank_type: str = "cct"          # cct | bbt
    ferment_id: Optional[str] = None
    source_bbt_code: Optional[str] = None   # bắt buộc khi tank_type="bbt"
    reason: Optional[str] = None            # Lý do lọc lại — bắt buộc khi tank_type="bbt"
    planned_v_dich_hl: float


class FilterSubOrderIn(BaseModel):
    """1 "lệnh lọc nhỏ" bên trong 1 lệnh lọc lớn (FilterMasterOrderIn) — mỗi tank lên men tự
    có thể tích dịch lọc kế hoạch riêng (xem FilterSubOrderTankIn); order_code tự sinh (không
    có ở đây, xem services/filter_order.py::create_master_order)."""
    blend_mode: str = "khong_phoi"   # khong_phoi | phoi
    tanks: list[FilterSubOrderTankIn]
    lines: list[FilterOrderMaterialLineIn] = []
    kcs_lot_no: Optional[str] = None
    volume_tolerance_hl: float = 0.0
    # Loại bia — chỉ bắt buộc (ở tầng service) khi các tank chọn thuộc >1 Loại bia khác
    # nhau; nếu cùng 1 Loại bia (hoặc chỉ 1 tank) thì tự suy ra, bỏ qua field này.
    beer_type_id: Optional[str] = None
    # Sản phẩm đích (SKU, tuỳ chọn) — xem FilterOrderIn.finished_product_id.
    finished_product_id: Optional[str] = None


class FilterMasterOrderIn(BaseModel):
    """Lệnh lọc lớn — 1 số lệnh, chứa 1..N lệnh lọc nhỏ (mỗi lệnh nhỏ tự chọn phối/không
    phối + tank + vật tư + thể tích riêng); in ra 1 tờ gồm tất cả lệnh nhỏ bên trong."""
    order_code: str
    note: Optional[str] = None
    children: list[FilterSubOrderIn]


class BrewProcessLogIn(BaseModel):
    """Ghi chép nấu (Thực hiện — khớp biểu mẫu giấy QT-KCS-QT-BM-05) — PATCH-style, chỉ
    lưu field nào được gửi lên. Danh sách key hợp lệ rất dài (header + 5 công đoạn + các
    bước nhiệt độ/thời gian) nên khai báo động ở services/braumat_import.py::
    MANUAL_FIELD_KEYS thay vì liệt kê lại ở đây — extra="allow" để nhận mọi key đó,
    server lọc/validate theo MANUAL_FIELD_KEYS khi lưu (key lạ bị bỏ qua, không lỗi)."""
    model_config = ConfigDict(extra="allow")
    note: Optional[str] = None


class ProductBrewSpecIn(BaseModel):
    """Quy định công nghệ nấu theo dịch bia (Product.spec_json) — chỉ admin/master.manage
    sửa được. Key hợp lệ ở services/braumat_import.py::SPEC_FIELD_KEYS (subset của
    MANUAL_FIELD_KEYS — chỉ field có cột Quy định trên biểu mẫu giấy)."""
    model_config = ConfigDict(extra="allow")


class FermentProcessLogIn(BaseModel):
    """Ghi chép lên men (bảng thông tin đầu, biểu mẫu giấy BM 1.11 (06)) — PATCH-style, chỉ
    lưu field nào được gửi lên. Key hợp lệ ở services/ferment_log.py::MANUAL_FIELD_KEYS +
    LIST_FIELD_KEYS (riêng "ha_phu_events" là 1 list, gửi lại nguyên mảng) — extra="allow"
    để nhận mọi key đó, server lọc theo whitelist khi lưu."""
    model_config = ConfigDict(extra="allow")
    note: Optional[str] = None


class FermentDailyReadingIn(BaseModel):
    """1 dòng / 1 ngày trong bảng theo dõi lên men — xem services/ferment_log.py::
    upsert_daily_readings (upsert theo ferment_id + day_no)."""
    day_no: int
    reading_date: Optional[str] = None
    nhiet_do_c: Optional[float] = None
    do_s: Optional[float] = None
    mat_do_tb: Optional[float] = None
    kcs: Optional[str] = None  # "dat"|"khong_dat"
    truc_ca: Optional[str] = None


class FermentDailyReadingsIn(BaseModel):
    readings: list[FermentDailyReadingIn]


class SqlConnectionIn(BaseModel):
    """Khai báo kết nối CSDL SQL bên ngoài — chỉ admin sửa được. password=None khi sửa
    nghĩa là giữ nguyên mật khẩu cũ (không xoá/rỗng hoá). purpose = các module MES được
    chỉ định dùng kết nối này, dạng CSV nếu gán nhiều mục đích cùng lúc (VD
    "energy,filling_keg" — 1 CSDL vật lý có thể phục vụ nhiều báo cáo khác nhau)."""
    name: str
    host: str
    port: int = 1433
    database_name: str
    username: str
    password: Optional[str] = None
    extra_params: Optional[str] = None
    purpose: Optional[str] = None
    active: bool = True


class BrewMaterialUsageIn(BaseModel):
    lot_id: Optional[str] = None   # nguồn thật từ tồn kho Kho phân xưởng (MaterialLot) — ưu tiên nếu có
    receipt_id: Optional[str] = None
    material_name: Optional[str] = None
    lot_pm: Optional[str] = None
    quantity: float
    uom: str = "kg"


class FilterMaterialUsageIn(BaseModel):
    """NVL (VD: bột trợ lọc) dùng thật cho 1 mẻ lọc — mirror BrewMaterialUsageIn."""
    lot_id: Optional[str] = None
    receipt_id: Optional[str] = None
    material_name: Optional[str] = None
    lot_pm: Optional[str] = None
    quantity: float
    uom: str = "kg"


class BottleMaterialUsageIn(BaseModel):
    """NVL (VD: CO2, hóa chất vệ sinh) dùng thật cho 1 mẻ chiết — mirror FilterMaterialUsageIn.
    Không có receipt_id (lối dự phòng cũ) vì Chiết là tính năng NVL mới, chỉ dùng lot_id thật."""
    lot_id: Optional[str] = None
    material_name: Optional[str] = None
    lot_pm: Optional[str] = None
    quantity: float
    uom: str = "kg"


class FermentIn(BaseModel):
    lm_code: str
    brew_code: Optional[str] = None
    brew_date: Optional[datetime] = None
    kt_date: Optional[datetime] = None
    batch_numbers: Optional[str] = None
    brew_ids: list[str] = []   # các mẻ nấu (BrewRecord) thật đưa vào lô LM này — liên kết qua FermentBrewLink
    wort_type: str
    product_id: Optional[str] = None
    yeast_gen: Optional[str] = None
    tank_lm: str
    volume_hl: float = 0.0
    on_hand_cct: float = 0.0
    status: str = "len_men"
    ferment_days: Optional[str] = None


class FilterIn(BaseModel):
    filter_code: str
    lot_loc: Optional[str] = None
    filter_phoi_code: Optional[str] = None
    filter_date: Optional[datetime] = None
    filter_type: str = "thuong"
    wort_type: Optional[str] = None
    # Loại bia không còn nhập tay — server tự điền từ FilterOrder.beer_type_id (xem
    # add_filter). Field này giữ lại optional để không phá vỡ payload cũ (giá trị gửi lên
    # bị bỏ qua).
    beer_type: Optional[str] = None
    to_bbt: Optional[str] = None
    has_indicators: bool = False
    has_nvl: bool = False
    # Tank(s) nguồn không tự chọn tay nữa — bắt buộc chọn 1 Lệnh lọc CHƯA DÙNG, server tự
    # điền product_id/wort_type/brew_code/from_cct từ tank(s) của lệnh đó (xem add_filter).
    filter_order_id: str


class BottleIn(BaseModel):
    bottle_code: str
    filter_code: Optional[str] = None
    bottle_date: Optional[datetime] = None
    # Loại bia không còn nhập tay — server tự điền từ FilterRecord.beer_type_id nguồn (xem
    # add_bottle). Field này giữ lại optional để không phá vỡ payload cũ (giá trị gửi lên
    # bị bỏ qua).
    beer_type: Optional[str] = None
    finished_product_id: Optional[str] = None   # sản phẩm đóng gói (SKU) — chọn khi chiết
    lot_no: Optional[str] = None
    # V cấp chiết/hl và Ca 1/2/3 chưa biết lúc bắt đầu chiết — chỉ điền khi vận hành bấm
    # "Kết thúc" (xem FinishBottleIn/finish_bottle), mirror FilterIn không có v_dich_hl.
    from_bbt: Optional[str] = None
    line: Optional[str] = None
    stocked: bool = False
    approved: bool = False
    has_indicators: bool = False
    has_nvl: bool = False
    note: Optional[str] = None


class StageIndicatorIn(BaseModel):
    stage: str
    scope_code: str
    name: str
    unit: Optional[str] = None
    value: Optional[float] = None
    value_text: Optional[str] = None
    warning: Optional[str] = None


# ---- Danh mục chỉ tiêu chất lượng NVL ----
class QcParameterIn(BaseModel):
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    unit: Optional[str] = None
    target: Optional[float] = None
    usl: Optional[float] = None
    lsl: Optional[float] = None
    stage: Optional[str] = None
    method: Optional[str] = None
    note: Optional[str] = None
    active: bool = True
    value_type: str = "numeric"


class QcParameterOut(ORMModel):
    param_id: str
    code: str
    name: str
    unit: Optional[str] = None
    target: Optional[float] = None
    usl: Optional[float] = None
    lsl: Optional[float] = None
    stage: Optional[str] = None
    method: Optional[str] = None
    note: Optional[str] = None
    active: bool
    value_type: str


class QcGroupIn(BaseModel):
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    note: Optional[str] = None
    active: bool = True


class QcGroupOut(ORMModel):
    group_id: str
    code: str
    name: str
    note: Optional[str] = None
    active: bool


class QcGroupItemIn(BaseModel):
    param_id: str
    seq: int = 0
    mandatory: bool = True
    target_override: Optional[float] = None
    usl_override: Optional[float] = None
    lsl_override: Optional[float] = None


class QcGroupItemOut(ORMModel):
    item_id: str
    group_id: str
    param_id: str
    seq: int
    mandatory: bool
    target_override: Optional[float] = None
    usl_override: Optional[float] = None
    lsl_override: Optional[float] = None
    param_code: Optional[str] = None
    param_name: Optional[str] = None
    param_unit: Optional[str] = None


class QcGroupCopyItemsIn(BaseModel):
    source_group_id: str = Field(min_length=1)


# ---- Danh mục tham số quy trình (setpoint công nghệ) ----
class ProcessParameterIn(BaseModel):
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    unit: Optional[str] = None
    target: Optional[float] = None
    usl: Optional[float] = None
    lsl: Optional[float] = None
    phase: Optional[str] = None
    note: Optional[str] = None
    active: bool = True


class ProcessParameterOut(ORMModel):
    param_id: str
    code: str
    name: str
    unit: Optional[str] = None
    target: Optional[float] = None
    usl: Optional[float] = None
    lsl: Optional[float] = None
    phase: Optional[str] = None
    note: Optional[str] = None
    active: bool


class ProcessParameterGroupIn(BaseModel):
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    note: Optional[str] = None
    active: bool = True


class ProcessParameterGroupOut(ORMModel):
    group_id: str
    code: str
    name: str
    note: Optional[str] = None
    active: bool


class ProcessParameterGroupItemIn(BaseModel):
    param_id: str
    seq: int = 0
    mandatory: bool = True
    target_override: Optional[float] = None
    usl_override: Optional[float] = None
    lsl_override: Optional[float] = None


class ProcessParameterGroupItemOut(ORMModel):
    item_id: str
    group_id: str
    param_id: str
    seq: int
    mandatory: bool
    target_override: Optional[float] = None
    usl_override: Optional[float] = None
    lsl_override: Optional[float] = None
    param_code: Optional[str] = None
    param_name: Optional[str] = None
    param_unit: Optional[str] = None


class ProcessParameterGroupCopyItemsIn(BaseModel):
    source_group_id: str = Field(min_length=1)


class MaterialQcGroupIn(BaseModel):
    group_id: str
    mandatory: bool = True


class MaterialQcGroupOut(ORMModel):
    link_id: str
    material_id: str
    group_id: str
    mandatory: bool
    active: bool
    group_code: Optional[str] = None
    group_name: Optional[str] = None


class StageQcGroupIn(BaseModel):
    stage: str = Field(min_length=1)   # nau|len_men_chinh|len_men_phu|loc|thanh_pham
    group_id: str
    # product_id (Dịch bia) CHỈ dùng cho stage nau|len_men_chinh|len_men_phu; beer_type_id
    # (Loại bia) CHỈ dùng cho stage loc|thanh_pham — loại trừ lẫn nhau, service validate
    # theo đúng stage (xem services/qc_catalog.py::PRODUCT_SCOPED_STAGES). Để trống field
    # tương ứng = áp dụng mọi dịch bia/loại bia.
    product_id: Optional[str] = None
    beer_type_id: Optional[str] = None
    finished_product_id: Optional[str] = None   # sản phẩm đóng gói (thường dùng với stage=thanh_pham) — để trống = áp dụng mọi sản phẩm
    mandatory: bool = True


class StageQcResultIn(BaseModel):
    stage: str = Field(min_length=1)
    scope_type: str = Field(min_length=1)   # brew|ferment|filter|bottle
    scope_id: str = Field(min_length=1)
    parameter: str = Field(min_length=1)
    value: Optional[float] = None
    value_text: Optional[str] = None
    unit: Optional[str] = None
    lower_limit: Optional[float] = None
    upper_limit: Optional[float] = None


class QcSampleResultIn(BaseModel):
    parameter: str = Field(min_length=1)
    value: Optional[float] = None
    value_text: Optional[str] = None
    unit: Optional[str] = None
    lower_limit: Optional[float] = None
    upper_limit: Optional[float] = None


class QcSampleIn(BaseModel):
    # Lấy mẫu NHIỀU LẦN (lần 1/lần 2/...) — chỉ hỗ trợ len_men_chinh/len_men_phu, xem
    # qc_catalog.MULTI_SAMPLE_STAGES. Mỗi lần gọi LUÔN thêm 1 bản ghi mới (không ghi đè).
    stage: str = Field(min_length=1)
    scope_type: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)
    sampled_at: Optional[datetime] = None   # ngày giờ lấy mẫu do người dùng khai — mặc định "bây giờ"
    results: list[QcSampleResultIn] = Field(min_length=1)


# ---- CIP (vệ sinh thiết bị) ----
class CipStepIn(BaseModel):
    # Bảng bước linh hoạt — thêm/bớt dòng tự do, không hard-code theo từng loại biểu mẫu.
    # 4 trường đầu là TIÊU CHUẨN (khai báo 1 lần ở Khai báo biểu mẫu, khoá khi tạo bản ghi
    # CIP thật). 4 trường *_actual là THỰC TẾ — người vận hành tự nhập khi thực hiện.
    step_no: Optional[str] = None
    content: str = ""
    time_spec: Optional[str] = None
    temp: Optional[str] = None
    concentration: Optional[str] = None
    # Đánh dấu cột không áp dụng cho bước này (vd VS thô không có tiêu chí nồng độ) — phân
    # biệt với "áp dụng nhưng chưa điền" (time_spec/temp/concentration = null). Khai báo ở
    # Khai báo biểu mẫu, khoá ô Thực tế tương ứng ở Khai báo CIP khi True.
    time_na: bool = False
    temp_na: bool = False
    conc_na: bool = False
    check_result: Optional[str] = None
    time_actual: Optional[str] = None
    temp_actual: Optional[str] = None
    conc_actual: Optional[str] = None
    check_actual: Optional[str] = None
    performed_by: Optional[str] = None
    note: Optional[str] = None


class CipFormTypeIn(BaseModel):
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    area: str = Field(min_length=1)  # nau | len_men | loc | chiet | kho_tp
    kind: str = "full"  # full | light (vd tráng nước DAW)
    # Đơn vị của từng cột thông số — khai báo 1 lần cho cả biểu mẫu (khớp đúng cột giấy gốc).
    time_unit: str = "phút"
    temp_unit: str = "°C"
    conc_unit: str = "%"
    # Bảng bước MẪU khai báo trước theo đúng biểu mẫu giấy gốc — khi tạo 1 lần CIP mới,
    # chọn form_type sẽ tự điền bảng bước từ đây (vẫn sửa/thêm/bớt được, không khoá cứng).
    default_steps: list[CipStepIn] = []


class CipCopyStepsIn(BaseModel):
    target_form_type_id: str = Field(min_length=1)


class CipFormTypeOut(ORMModel):
    form_type_id: str
    code: str
    name: str
    area: str
    kind: str
    time_unit: str
    temp_unit: str
    conc_unit: str
    default_steps: list
    active: bool


class CipEquipmentIn(BaseModel):
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    area: str = Field(min_length=1)
    production_line_id: Optional[str] = None


class CipEquipmentOut(ORMModel):
    equipment_id: str
    code: str
    name: str
    area: str
    production_line_id: Optional[str] = None
    active: bool


class CipRecordIn(BaseModel):
    form_type_id: str = Field(min_length=1)
    equipment_id: str = Field(min_length=1)
    batch_number: str = Field(min_length=1)  # đối chiếu Batch Number bên Braumat
    order_number: str = Field(min_length=1)  # đối chiếu Order Number bên Braumat
    shift: Optional[str] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    performed_by: Optional[str] = None
    duty_officer: Optional[str] = None
    steps: list[CipStepIn] = []
    note: Optional[str] = None


class CipApproveIn(BaseModel):
    result: str = Field(min_length=1)  # dat | khong_dat
    checked_by: str = Field(min_length=1)
    note: Optional[str] = None


class CipRecordOut(ORMModel):
    cip_id: str
    cip_code: str
    form_type_id: str
    equipment_id: str
    batch_number: str
    order_number: str
    shift: Optional[str] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    performed_by: Optional[str] = None
    duty_officer: Optional[str] = None
    steps: list
    result: Optional[str] = None
    note: Optional[str] = None
    checked_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    created_by: Optional[str] = None
    created_at: datetime


class CipLinkIn(BaseModel):
    scope_type: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)
    cip_ids: list[str] = Field(min_length=1)


# ---- Audit ----
class AuditOut(ORMModel):
    audit_id: str
    seq: int
    entity_type: str
    entity_id: str
    action: str
    actor: str
    actor_role: Optional[str] = None
    reason: Optional[str] = None
    before: Optional[Any] = None
    after: Optional[Any] = None
    correlation_id: Optional[str] = None
    ts: datetime


# ---- Batch pipeline (blueprint mới cho Mẻ sản xuất: tank/lô lọc/lô thành phẩm) ----
class BatchFilterOrderSourceIn(BaseModel):
    source_type: str = "tank"    # tank | filter_lot (lọc lại)
    source_tank_id: Optional[str] = None
    source_filter_lot_id: Optional[str] = None
    reason: Optional[str] = None
    planned_v_dich_hl: float = 0.0


class BatchFilterOrderCreateIn(BaseModel):
    sources: list[BatchFilterOrderSourceIn] = Field(min_length=1)
    order_code: str = Field(min_length=1)
    blend_mode: Optional[str] = None    # tự suy từ số nguồn nếu bỏ trống
    volume_tolerance_hl: float = 0.0
    beer_type_id: Optional[str] = None
    finished_product_id: Optional[str] = None
    kcs_lot_no: Optional[str] = None
    note: Optional[str] = None


class BatchFilterOrderOut(BaseModel):
    order_id: str
    order_code: str
    order_year: int
    blend_mode: str
    planned_volume_hl: float = 0.0
    volume_tolerance_hl: float = 0.0
    beer_type_id: Optional[str] = None
    finished_product_id: Optional[str] = None
    kcs_lot_no: Optional[str] = None
    note: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime
    locked: bool = False
    lot_count: int = 0
    actual_volume_hl: float = 0.0
    is_complete: bool = False
    consumed_downstream: bool = False
    status: str = "planned"
    status_label: str = ""
    tank_lm_names: list[str] = []


class BatchFilterOrderSourceOut(BaseModel):
    link_id: str
    order_id: str
    source_type: str
    source_tank_id: Optional[str] = None
    source_filter_lot_id: Optional[str] = None
    source_label: str
    reason: Optional[str] = None
    planned_v_dich_hl: float = 0.0
    seq: int


class FilterLotFromOrderIn(BaseModel):
    filter_lot_code: str = Field(min_length=1)
    to_bbt: str = Field(min_length=1)
    note: Optional[str] = None


class BatchTankMergeIn(BaseModel):
    batch_ids: list[str] = Field(min_length=1)
    # Không bắt buộc nữa — bỏ trống thì tự sinh theo số thứ tự Lệnh SX (điều độ) của các mẻ đang
    # gộp (xem services/batch_pipeline.py::_auto_tank_code, yêu cầu người dùng 2026-09-01: lô lên
    # men không cần mã riêng, coi là 1 thể thống nhất với điều độ/tank vật lý sinh ra nó).
    tank_code: Optional[str] = None
    tank_lm: Optional[str] = None
    note: Optional[str] = None


class BatchTankEditIn(BaseModel):
    """Sửa 1 BatchTank đã tồn tại (gõ nhầm mã/tank vật lý lúc gộp) — chỉ nhận field THỰC SỰ có
    trong request (exclude_unset ở router), không truyền thì giữ nguyên (2026-09-02, audit
    module "Mẻ sản xuất")."""
    tank_code: Optional[str] = None
    tank_lm: Optional[str] = None
    note: Optional[str] = None


class BatchTankOut(ORMModel):
    tank_id: str
    tank_code: str
    tank_year: int
    tank_lm: Optional[str] = None
    product_id: Optional[str] = None
    volume_hl: float = 0.0
    on_hand: float = 0.0
    status: str
    status_label: str = ""
    note: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime
    locked: bool = False
    quality_status: str
    vao_dich_start: Optional[datetime] = None
    vao_dich_end: Optional[datetime] = None
    ferment_days_std: Optional[float] = None
    days_elapsed: Optional[int] = None
    ready_date: Optional[datetime] = None


class BatchFilterLotSourceIn(BaseModel):
    source_type: str = "tank"    # tank | filter_lot (lọc lại)
    source_tank_id: Optional[str] = None
    source_filter_lot_id: Optional[str] = None
    reason: Optional[str] = None


class BatchFilterLotDrawIn(BaseModel):
    sources: list[BatchFilterLotSourceIn] = Field(min_length=1)
    filter_lot_code: str = Field(min_length=1)
    to_bbt: str = Field(min_length=1)
    beer_type_id: Optional[str] = None
    finished_product_id: Optional[str] = None
    note: Optional[str] = None


class BatchFilterLotEditIn(BaseModel):
    """Sửa 1 BatchFilterLot đã tồn tại (gõ nhầm mã lúc tạo) — mirror BatchTankEditIn. Không có
    `to_bbt` — xem services/batch_pipeline.py::update_filter_lot vì sao."""
    filter_lot_code: Optional[str] = None
    note: Optional[str] = None


class BatchFilterLotOut(ORMModel):
    filter_lot_id: str
    filter_lot_code: str
    filter_lot_year: int
    order_id: Optional[str] = None
    to_bbt: Optional[str] = None
    product_id: Optional[str] = None
    beer_type_id: Optional[str] = None
    finished_product_id: Optional[str] = None
    v_dich_hl: float = 0.0
    nuoc_bai_khi_hl: float = 0.0
    volume_hl: float = 0.0
    on_hand: float = 0.0
    status: str
    status_label: str = ""
    note: Optional[str] = None
    ended_at: Optional[datetime] = None
    qc_approved: bool = False
    qc_approved_by: Optional[str] = None
    qc_approved_at: Optional[datetime] = None
    created_by: Optional[str] = None
    created_at: datetime
    locked: bool = False
    quality_status: str


class BatchFilterLotSourceOut(ORMModel):
    link_id: str
    filter_lot_id: str
    source_type: str
    source_tank_id: Optional[str] = None
    source_filter_lot_id: Optional[str] = None
    source_label: str = ""
    reason: Optional[str] = None
    seq: int


class BatchFilterLotBatchDrawOut(ORMModel):
    source_link_id: str
    dich_nha_hl: Optional[float] = None


class BatchFilterLotBatchOut(ORMModel):
    batch_link_id: str
    filter_lot_id: str
    batch_seq_no: Optional[str] = None
    nuoc_bai_khi_hl: Optional[float] = None
    is_final_batch: bool = False
    ended_at: Optional[datetime] = None
    created_at: datetime
    draws: list[BatchFilterLotBatchDrawOut] = []


class FilterLotBatchDrawIn(BaseModel):
    source_link_id: str
    dich_nha_hl: float = Field(ge=0)


class FinishFilterLotBatchIn(BaseModel):
    draws: list[FilterLotBatchDrawIn]
    nuoc_bai_khi_hl: float = Field(ge=0, default=0.0)
    batch_seq_no: Optional[str] = None
    # Bắt đầu/Kết thúc — tuỳ chọn, sửa lại giờ thực tế qua popup "Sửa" (mirror created_at/ended_at
    # đã có sẵn); không truyền thì giữ nguyên created_at, ended_at mặc định = giờ hiện tại (hành
    # vi cũ), yêu cầu người dùng 2026-09-01.
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None


class BatchTankProcessLogIn(BaseModel):
    """Ghi chép lên men (bảng thông tin đầu) — PATCH-style, chỉ lưu field nào được gửi lên.
    Key hợp lệ ở services/batch_tank_log.py::MANUAL_FIELD_KEYS + LIST_FIELD_KEYS — extra="allow"
    để nhận mọi key đó, server lọc theo whitelist khi lưu."""
    model_config = ConfigDict(extra="allow")
    note: Optional[str] = None


class BatchTankDailyReadingIn(BaseModel):
    day_no: int
    reading_date: Optional[str] = None
    nhiet_do_c: Optional[float] = None
    do_s: Optional[float] = None
    mat_do_tb: Optional[float] = None
    kcs: Optional[str] = None
    truc_ca: Optional[str] = None


class BatchTankDailyReadingsIn(BaseModel):
    readings: list[BatchTankDailyReadingIn]


class BatchPackLotSplitIn(BaseModel):
    qty: float = Field(gt=0)   # Số lượng cấp chiết, đơn vị LÍT (khác on_hand lô lọc, đơn vị hl)
    pack_lot_code: str = Field(min_length=1)
    finished_product_id: Optional[str] = None
    lot_no: str = Field(min_length=1)   # số lô bia in trên bao bì — bắt buộc, khác mã lô TP (nội bộ)
    line: Optional[str] = None
    from_bbt: Optional[str] = None
    pack_date: Optional[datetime] = None
    note: Optional[str] = None


class BatchPackLotCreateIn(BaseModel):
    """Tạo lô thành phẩm chọn "Tank BBT nào đi chiết" (mirror BottleIn.from_bbt) — server tự
    tìm lô lọc nguồn tương ứng, không cần người dùng tự chọn lô lọc. Xem
    services/batch_pipeline.py::create_pack_lot_from_bbt."""
    from_bbt: str = Field(min_length=1)
    qty: float = Field(gt=0)   # Số lượng cấp chiết, đơn vị LÍT (khác on_hand lô lọc, đơn vị hl)
    pack_lot_code: str = Field(min_length=1)
    finished_product_id: Optional[str] = None
    lot_no: str = Field(min_length=1)   # số lô bia in trên bao bì — bắt buộc, khác mã lô TP (nội bộ)
    line: Optional[str] = None
    pack_date: Optional[datetime] = None
    note: Optional[str] = None


class BatchPackLotQtyIn(BaseModel):
    qty: float = Field(gt=0)   # Số lượng cấp chiết, đơn vị LÍT


class BatchPackLotOut(ORMModel):
    pack_lot_id: str
    pack_lot_code: str
    pack_lot_year: int
    filter_lot_id: str
    qty: float = 0.0   # Số lượng cấp chiết, đơn vị LÍT (khác on_hand lô lọc, đơn vị hl)
    finished_product_id: Optional[str] = None
    lot_no: Optional[str] = None
    line: Optional[str] = None
    from_bbt: Optional[str] = None
    pack_date: Optional[datetime] = None
    note: Optional[str] = None
    ca1_qty: Optional[float] = None
    ca1_start_at: Optional[datetime] = None
    ca1_end_at: Optional[datetime] = None
    ca2_qty: Optional[float] = None
    ca2_start_at: Optional[datetime] = None
    ca2_end_at: Optional[datetime] = None
    ca3_qty: Optional[float] = None
    ca3_start_at: Optional[datetime] = None
    ca3_end_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None   # tính từ ca1/2/3 (computed property) — xem models/batch_pipeline.py
    approved: bool = False
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    stocked: bool = False
    stocked_by: Optional[str] = None
    stocked_at: Optional[datetime] = None
    created_by: Optional[str] = None
    created_at: datetime
    locked: bool = False
    quality_status: str
    status: str = "dang_chiet"
    status_label: str = ""


class BatchPackLotPackDateIn(BaseModel):
    pack_date: datetime


class BatchPackLotShiftsIn(BaseModel):
    """SL chiết theo ca 1/2/3 + giờ bắt đầu/kết thúc từng ca — mirror FinishBottleIn.ca1/ca2/ca3
    (module Nấu-Lọc-Chiết cũ), sửa được nhiều lần (không phải finish 1 lần như module cũ vì
    BatchPackLot đã trừ on_hand ngay lúc tạo, không cần bước "Kết thúc" riêng). ca*_qty >= 0
    (Field, không phải chỉ check ở service) — trước đây không ràng buộc gì (2026-09-02, audit
    module "Mẻ sản xuất")."""
    ca1_qty: Optional[float] = Field(default=None, ge=0)
    ca1_start_at: Optional[datetime] = None
    ca1_end_at: Optional[datetime] = None
    ca2_qty: Optional[float] = Field(default=None, ge=0)
    ca2_start_at: Optional[datetime] = None
    ca2_end_at: Optional[datetime] = None
    ca3_qty: Optional[float] = Field(default=None, ge=0)
    ca3_start_at: Optional[datetime] = None
    ca3_end_at: Optional[datetime] = None


class BatchPackLotMaterialUsageIn(BaseModel):
    """NVL (VD CO2, hóa chất vệ sinh) dùng thật cho 1 lô thành phẩm — mirror BottleMaterialUsageIn."""
    lot_id: Optional[str] = None
    material_name: Optional[str] = None
    lot_pm: Optional[str] = None
    quantity: float
    uom: str = "kg"
    reason: Optional[str] = None   # bắt buộc nếu chọn lô KHÁC lô FIFO cũ nhất — xem add_pack_lot_material


class BatchPackLotMaterialUsageOut(ORMModel):
    usage_id: str
    pack_lot_id: str
    lot_id: Optional[str] = None
    movement_id: Optional[str] = None
    material_name: Optional[str] = None
    lot_pm: Optional[str] = None
    lot_date: Optional[datetime] = None
    fifo_ok: Optional[bool] = None
    reason: Optional[str] = None
    quantity: float = 0.0
    uom: str = "kg"
    created_at: datetime


class BatchFilterLotMaterialUsageIn(BaseModel):
    """NVL (VD bột trợ lọc/diatomite) dùng thật cho 1 lô lọc — mirror BatchPackLotMaterialUsageIn."""
    lot_id: Optional[str] = None
    material_name: Optional[str] = None
    lot_pm: Optional[str] = None
    quantity: float
    uom: str = "kg"
    reason: Optional[str] = None   # bắt buộc nếu chọn lô KHÁC lô FIFO cũ nhất — xem add_filter_lot_material


class BatchFilterLotMaterialUsageOut(ORMModel):
    usage_id: str
    filter_lot_id: str
    lot_id: Optional[str] = None
    movement_id: Optional[str] = None
    material_name: Optional[str] = None
    lot_pm: Optional[str] = None
    lot_date: Optional[datetime] = None
    fifo_ok: Optional[bool] = None
    reason: Optional[str] = None
    quantity: float = 0.0
    uom: str = "kg"
    created_at: datetime
