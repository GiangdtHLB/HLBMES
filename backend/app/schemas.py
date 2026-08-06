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


class MaterialAltGroupOut(ORMModel):
    group_id: str
    code: str
    name: str
    member_material_ids: list
    unit: Optional[str] = None
    active: bool


class LotKcsUpdateIn(BaseModel):
    kcs_lot_no: Optional[str] = None


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
    factory_code: Optional[str] = None


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
    factory_code: Optional[str] = None
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
    ferment_days_std: Optional[int] = None   # số ngày lên men chuẩn — tính ngày sẵn sàng chiết
    beer_type_id: Optional[str] = None   # Loại bia (thương hiệu) — dùng để tra chỉ tiêu Lọc/Chiết


class ProductOut(ORMModel):
    product_id: str
    code: str
    name: str
    uom: str
    description: Optional[str] = None
    ferment_days_std: Optional[int] = None
    beer_type_id: Optional[str] = None


class FinishedProductIn(BaseModel):
    code: str
    name: str
    uom: str = "L"
    product_id: Optional[str] = None   # dịch bia gốc (tuỳ chọn)
    unit_type: str = "vi"               # vi | keg — loại đơn vị tồn kho thành phẩm
    pack_size: int = 24                 # Lon/vỉ (vi) hoặc 1 (keg)
    category: Optional[str] = None     # Bia chai|Bia lon|Bia hơi|Bia tươi...
    description: Optional[str] = None
    unit_volume_l: Optional[float] = None   # dung tích 1 đơn vị đóng gói (lít) — để đối chiếu lúc kết thúc chiết


class FinishedProductOut(ORMModel):
    finished_product_id: str
    code: str
    name: str
    uom: str
    product_id: Optional[str] = None
    unit_type: str
    pack_size: int
    category: Optional[str] = None
    description: Optional[str] = None
    unit_volume_l: Optional[float] = None


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


# ---- Orders ----
class OrderIn(BaseModel):
    order_code: str
    product_id: str
    planned_qty: float
    uom: str = "L"
    due_time: Optional[datetime] = None
    priority: int = 5
    source_version: Optional[str] = None


class OrderOut(ORMModel):
    order_id: str
    order_code: str
    product_id: str
    planned_qty: float
    uom: str
    due_time: Optional[datetime] = None
    priority: int
    status: str
    source_version: Optional[str] = None
    created_at: datetime


# ---- Work Orders / Điều độ ----
class WorkOrderIn(BaseModel):
    production_order_id: str
    wo_code: Optional[str] = None
    recipe_version_id: Optional[str] = None
    planned_qty: Optional[float] = None
    uom: Optional[str] = None
    line: Optional[str] = None
    shift: str = "A"
    scheduled_date: Optional[date] = None
    priority: int = 5
    note: Optional[str] = None


class WoDispatchIn(BaseModel):
    recipe_version_id: Optional[str] = None
    batch_code: Optional[str] = None
    planned_qty: Optional[float] = None
    allow_shortage: bool = False


# ---- Recipes ----
class RecipeIn(BaseModel):
    code: str
    name: str
    product_id: str


class RecipeOut(ORMModel):
    recipe_id: str
    code: str
    name: str
    product_id: str


class RecipeVersionIn(BaseModel):
    base_qty: float = 0.0
    base_uom: str = "L"
    parameters: list[dict] = []
    materials: list[dict] = []
    quality_checks: list[dict] = []
    yield_steps: list[dict] = []
    procedure: list[dict] = []
    change_reason: Optional[str] = None


class RecipeVersionOut(ORMModel):
    version_id: str
    recipe_id: str
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
    base_qty: float = 0.0
    base_uom: str = "L"
    materials: list[FormulaMaterialLineIn] = []


class FormulaOut(ORMModel):
    formula_id: str
    code: str
    product_id: str
    note: Optional[str] = None
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


class BatchOut(ORMModel):
    batch_id: str
    batch_code: str
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


class ActualIn(BaseModel):
    name: str
    target: Optional[float] = None
    actual: Optional[float] = None
    unit: Optional[str] = None
    phase: Optional[str] = None


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


class DispenseIn(BaseModel):
    lines: list[DispenseLineIn]
    note: Optional[str] = None


class BackflushIn(BaseModel):
    produced_qty: float


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
class WmsLocationIn(BaseModel):
    code: str
    name: str
    zone: Optional[str] = None
    kind: str = "bin"
    capacity: int = 10


class WmsLocationUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    zone: Optional[str] = None
    kind: Optional[str] = None
    capacity: Optional[int] = None
    active: Optional[bool] = None


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


class DeleteByLotIn(BaseModel):
    product_name: str
    lot_code: Optional[str] = None
    unit_type: str


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


class ShipmentIn(BaseModel):
    ship_to_id: str
    lines: list[ShipmentLineIn]
    note: Optional[str] = None                 # Lý do xuất kho
    recipient_name: Optional[str] = None        # Họ tên người nhận hàng
    recipient_dept: Optional[str] = None        # Địa chỉ (bộ phận)
    driver_name: Optional[str] = None           # Lái xe
    vehicle_plate: Optional[str] = None         # Biển số xe
    from_location: Optional[str] = None         # Xuất tại kho (ngăn lô)
    delivery_place: Optional[str] = None        # Địa điểm
    shipment_type: str = "normal"                # normal | promo | return — nhãn phân loại, không đổi luồng tồn kho


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
    location_id: Optional[str] = None  # vị trí kho nhận — bỏ trống nếu chưa cất
    note: Optional[str] = None


class ConsignedEntryUpdate(BaseModel):
    finished_product_id: Optional[str] = None
    quantity: Optional[int] = None
    location_id: Optional[str] = None
    note: Optional[str] = None


class LoadSlipHeaderUpdate(BaseModel):
    issuer_name: Optional[str] = None
    issuer_title: Optional[str] = None
    issuer_dept: Optional[str] = None
    recipient_name: Optional[str] = None
    recipient_title: Optional[str] = None
    recipient_unit: Optional[str] = None


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
    identification_code: Optional[str] = None  # mã nhận dạng dây chuyền (kind="line")


class LineUpdate(BaseModel):
    name: Optional[str] = None
    area: Optional[str] = None
    ideal_rate_per_min: Optional[float] = None
    capacity_uom: Optional[str] = None
    volume: Optional[float] = None
    volume_uom: Optional[str] = None
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
    created_at: datetime


# ---- Quality ----
class ResultIn(BaseModel):
    scope_type: str = "batch"
    scope_id: str
    parameter: str
    sample_id: Optional[str] = None
    method: Optional[str] = None
    instrument: Optional[str] = None
    value: Optional[float] = None
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


class DeviationTransitionIn(BaseModel):
    target: str
    investigation: Optional[str] = None
    disposition: Optional[str] = None


# ---- Quality hardcore: CAPA + LIMS ----
class CapaIn(BaseModel):
    title: str
    deviation_id: Optional[str] = None
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
    downtime_reasons: list[dict] = []


class DowntimeIn(BaseModel):
    line: str
    reason_group: str
    reason_code: str
    minutes: float = 0.0
    equipment_id: Optional[str] = None
    shift: str = "A"
    shift_date: Optional[datetime] = None
    note: Optional[str] = None


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


class SangNgangRejectIn(BaseModel):
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
    brew_order_id: str   # bắt buộc — mỗi mã nấu phải ứng với đúng 1 Lệnh nấu (xem services/brew_order.py)


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


class BrewOrderIn(BaseModel):
    """Lệnh nấu nhỏ (1 dịch bia) — dùng cho API cũ /brewing/orders (tạo lệnh nhỏ đứng độc
    lập, master_order_id=None) VÀ làm khuôn field dùng chung bên trong BrewSubOrderIn (xem
    bên dưới) khi tạo qua Lệnh nấu lớn. Các trường hành chính chung của cả tờ (issued_by/
    executor_unit/warehouse_keeper/reference_note/start_date/end_date/safety_note) đã chuyển
    sang BrewMasterOrderIn — không còn ở đây."""
    order_code: str
    product_id: Optional[str] = None
    product_desc: Optional[str] = None
    planned_batch_count: int = 1
    planned_volume_hl: float = 0.0
    volume_tolerance_hl: float = 0.0
    bx_min: Optional[float] = None
    bx_max: Optional[float] = None
    tank_lm: Optional[str] = None
    batch_range_from: Optional[int] = None
    batch_range_to: Optional[int] = None
    auto_from_bom: bool = True
    lines: list[BrewOrderMaterialLineIn] = []


class BrewSubOrderIn(BaseModel):
    """1 "lệnh nấu nhỏ" bên trong 1 lệnh nấu lớn (BrewMasterOrderIn) — mỗi lệnh nhỏ ứng với
    đúng 1 dịch bia. order_code tự sinh (SUB-...), không nhận từ client (xem
    services/brew_order.py::_insert_children)."""
    product_id: Optional[str] = None
    product_desc: Optional[str] = None
    planned_batch_count: int = 1
    planned_volume_hl: float = 0.0
    volume_tolerance_hl: float = 0.0
    bx_min: Optional[float] = None
    bx_max: Optional[float] = None
    tank_lm: Optional[str] = None
    batch_range_from: Optional[int] = None
    batch_range_to: Optional[int] = None
    auto_from_bom: bool = True
    lines: list[BrewOrderMaterialLineIn] = []


class BrewMasterOrderIn(BaseModel):
    """Lệnh nấu lớn — 1 số lệnh + phần hành chính (Người ra lệnh/Thực hiện/Xuất kho/Căn cứ/
    Thời gian/An toàn) chung cho cả tờ; chứa 1..N lệnh nấu nhỏ (mỗi lệnh nhỏ 1 dịch bia riêng,
    xem services/brew_order.py::create_master_order)."""
    order_code: str
    issued_by: Optional[str] = None
    executor_unit: Optional[str] = "Phân xưởng bia Đông Mai"
    warehouse_keeper: Optional[str] = "Thủ kho"
    reference_note: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    safety_note: Optional[str] = None
    children: list[BrewSubOrderIn]


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


class FinishIn(BaseModel):
    """Vận hành chọn tay giờ kết thúc (mặc định giờ hiện tại nếu không truyền) — gọi lại
    được nhiều lần để sửa giờ nếu bấm nhầm, không phải hành động một chiều."""
    ended_at: Optional[datetime] = None


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
    unit: Optional[str] = None
    lower_limit: Optional[float] = None
    upper_limit: Optional[float] = None


class QcSampleResultIn(BaseModel):
    parameter: str = Field(min_length=1)
    value: Optional[float] = None
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
