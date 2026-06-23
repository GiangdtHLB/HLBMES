"""Pydantic schema cho request/response (OpenAPI tự sinh — tài liệu §9.3)."""

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- Master ----
class ProductIn(BaseModel):
    code: str
    name: str
    uom: str = "L"
    description: Optional[str] = None


class ProductOut(ORMModel):
    product_id: str
    code: str
    name: str
    uom: str
    description: Optional[str] = None


class MaterialIn(BaseModel):
    code: str
    name: str
    uom: str = "kg"
    category: Optional[str] = None


class MaterialOut(ORMModel):
    material_id: str
    code: str
    name: str
    uom: str
    category: Optional[str] = None


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


class PalletBuildIn(BaseModel):
    product: Optional[str] = None
    lot_code: Optional[str] = None
    case_count: int = 1
    units_per_case: int = 24


class PutawayIn(BaseModel):
    loc_id: str


# ---- Dây chuyền (line master) ----
class LineIn(BaseModel):
    code: str
    name: str
    kind: str = "line"                 # line | tank | brewhouse
    area: Optional[str] = None
    ideal_rate_per_min: float = 0.0


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
    material_id: Optional[str] = None
    product_id: Optional[str] = None
    lot_type: str
    supplier_lot: Optional[str] = None
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


class DeviationIn(BaseModel):
    scope_type: str = "batch"
    scope_id: str
    severity: str = "minor"
    reason: str


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
    lot_code: str
    material_id: Optional[str] = None
    quantity: float
    uom: str = "kg"
    lot_type: str = "material"
    supplier_lot: Optional[str] = None
    expiry: Optional[datetime] = None
    location: str = "Kho chính"
    reason: Optional[str] = None
    ref_doc: Optional[str] = None


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
    volume_hl: float = 0.0
    original_extract: Optional[float] = None
    plato: Optional[float] = None
    note: Optional[str] = None


class FermentIn(BaseModel):
    lm_code: str
    brew_code: Optional[str] = None
    brew_date: Optional[datetime] = None
    kt_date: Optional[datetime] = None
    batch_numbers: Optional[str] = None
    wort_type: str
    yeast_gen: Optional[str] = None
    tank_lm: str
    volume_hl: float = 0.0
    on_hand_cct: float = 0.0
    status: str = "len_men"
    ferment_days: Optional[str] = None


class FilterIn(BaseModel):
    filter_code: str
    brew_code: Optional[str] = None
    lot_loc: Optional[str] = None
    filter_phoi_code: Optional[str] = None
    filter_date: Optional[datetime] = None
    filter_type: str = "thuong"
    wort_type: Optional[str] = None
    from_cct: Optional[str] = None
    v_dich_hl: float = 0.0
    beer_type: str
    v_beer_hl: float = 0.0
    to_bbt: Optional[str] = None
    status: str = "cho_chiet"
    on_hand_bbt: float = 0.0
    has_indicators: bool = False
    has_nvl: bool = False


class BottleIn(BaseModel):
    bottle_code: str
    filter_code: Optional[str] = None
    bottle_date: Optional[datetime] = None
    beer_type: str
    lot_no: Optional[str] = None
    v_cap_chiet_hl: float = 0.0
    from_bbt: Optional[str] = None
    line: Optional[str] = None
    ca1: float = 0.0
    ca2: float = 0.0
    ca3: float = 0.0
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
