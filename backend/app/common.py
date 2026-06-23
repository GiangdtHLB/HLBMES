"""Tiện ích dùng chung: thời gian UTC, sinh ID, enum trạng thái."""

import uuid
from datetime import datetime, timezone
from enum import Enum


def utcnow() -> datetime:
    """Mọi timestamp lưu ở UTC (tài liệu §8.3)."""
    return datetime.now(timezone.utc)


def new_id() -> str:
    """UUID dạng chuỗi làm khóa nội bộ bất biến (tài liệu Phụ lục C)."""
    return str(uuid.uuid4())


class BatchState(str, Enum):
    """State machine thực thi mẻ (tài liệu §7.1)."""

    PLANNED = "planned"
    READY = "ready"
    RUNNING = "running"
    HELD = "held"
    COMPLETED = "completed"
    CLOSED = "closed"
    CANCELLED = "cancelled"


# Chuyển trạng thái hợp lệ cho BatchExecution.
BATCH_TRANSITIONS: dict[BatchState, set[BatchState]] = {
    BatchState.PLANNED: {BatchState.READY, BatchState.CANCELLED},
    BatchState.READY: {BatchState.RUNNING, BatchState.CANCELLED},
    BatchState.RUNNING: {BatchState.HELD, BatchState.COMPLETED, BatchState.CANCELLED},
    BatchState.HELD: {BatchState.RUNNING, BatchState.CANCELLED},
    BatchState.COMPLETED: {BatchState.CLOSED},
    BatchState.CLOSED: set(),
    BatchState.CANCELLED: set(),
}


class WorkOrderState(str, Enum):
    """Vòng đời lệnh sản xuất (work order) trên xưởng (tài liệu §7.1)."""

    PLANNED = "planned"          # đã lập kế hoạch, chưa phát hành
    RELEASED = "released"        # đã phát hành xuống xưởng
    IN_PROGRESS = "in_progress"  # đã dispatch (tạo mẻ), đang chạy
    COMPLETED = "completed"      # đã hoàn thành sản lượng
    CLOSED = "closed"            # đã chốt hồ sơ
    CANCELLED = "cancelled"


WORKORDER_TRANSITIONS: dict[WorkOrderState, set[WorkOrderState]] = {
    WorkOrderState.PLANNED: {WorkOrderState.RELEASED, WorkOrderState.CANCELLED},
    WorkOrderState.RELEASED: {WorkOrderState.IN_PROGRESS, WorkOrderState.CANCELLED},
    WorkOrderState.IN_PROGRESS: {WorkOrderState.COMPLETED, WorkOrderState.CANCELLED},
    WorkOrderState.COMPLETED: {WorkOrderState.CLOSED},
    WorkOrderState.CLOSED: set(),
    WorkOrderState.CANCELLED: set(),
}


class RecipeState(str, Enum):
    """Vòng đời recipe version (tài liệu §7.2)."""

    DRAFT = "draft"
    REVIEW = "review"
    APPROVED = "approved"
    EFFECTIVE = "effective"
    SUSPENDED = "suspended"   # tạm ngưng (có thể kích hoạt lại) — khác OBSOLETE (loại bỏ vĩnh viễn)
    OBSOLETE = "obsolete"


RECIPE_TRANSITIONS: dict[RecipeState, set[RecipeState]] = {
    RecipeState.DRAFT: {RecipeState.REVIEW},
    RecipeState.REVIEW: {RecipeState.APPROVED, RecipeState.DRAFT},
    RecipeState.APPROVED: {RecipeState.EFFECTIVE, RecipeState.OBSOLETE},
    RecipeState.EFFECTIVE: {RecipeState.SUSPENDED, RecipeState.OBSOLETE},
    RecipeState.SUSPENDED: {RecipeState.EFFECTIVE, RecipeState.OBSOLETE},
    RecipeState.OBSOLETE: set(),
}


class QualityStatus(str, Enum):
    """Trạng thái chất lượng/hold-release của mẻ hoặc lô (tài liệu §7.5)."""

    PENDING = "pending"   # chưa đánh giá
    ON_HOLD = "on_hold"   # đang giữ, không được tiêu thụ
    RELEASED = "released"  # đã release, được dùng/đóng gói
    REJECTED = "rejected"  # loại bỏ


class ResultStatus(str, Enum):
    PENDING = "pending"
    PASS = "pass"
    FAIL = "fail"
    INVALID = "invalid"


class DeviationState(str, Enum):
    """Workflow deviation (tài liệu §7.5)."""

    OPEN = "open"
    TRIAGE = "triage"
    INVESTIGATION = "investigation"
    DISPOSITION = "disposition"
    APPROVAL = "approval"
    CLOSED = "closed"


DEVIATION_TRANSITIONS: dict[DeviationState, set[DeviationState]] = {
    DeviationState.OPEN: {DeviationState.TRIAGE},
    DeviationState.TRIAGE: {DeviationState.INVESTIGATION},
    DeviationState.INVESTIGATION: {DeviationState.DISPOSITION},
    DeviationState.DISPOSITION: {DeviationState.APPROVAL},
    DeviationState.APPROVAL: {DeviationState.CLOSED},
    DeviationState.CLOSED: set(),
}


class LotStatus(str, Enum):
    AVAILABLE = "available"
    CONSUMED = "consumed"
    ON_HOLD = "on_hold"
    RELEASED = "released"
    SCRAPPED = "scrapped"


class GenealogyRelation(str, Enum):
    CONSUME = "consume"   # lot -> batch (nguyên liệu vào mẻ)
    PRODUCE = "produce"   # batch -> lot (mẻ tạo ra lô)
    SPLIT = "split"
    MERGE = "merge"
    TRANSFER = "transfer"


class PhaseState(str, Enum):
    """Trạng thái phase theo ISA-88 (rút gọn cho thực thi mẻ)."""

    IDLE = "idle"          # chưa chạy
    RUNNING = "running"
    HELD = "held"
    COMPLETE = "complete"
    ABORTED = "aborted"


# Chuyển trạng thái phase hợp lệ (ISA-88 procedural).
PHASE_TRANSITIONS: dict = {
    PhaseState.IDLE: {PhaseState.RUNNING},
    PhaseState.RUNNING: {PhaseState.HELD, PhaseState.COMPLETE, PhaseState.ABORTED},
    PhaseState.HELD: {PhaseState.RUNNING, PhaseState.ABORTED},
    PhaseState.COMPLETE: set(),
    PhaseState.ABORTED: set(),
}


class Role(str, Enum):
    """Vai trò tối thiểu để minh hoạ RBAC + SoD (tài liệu §7.8, §10.2)."""

    OPERATOR = "operator"
    SUPERVISOR = "supervisor"
    QA = "qa"
    ENGINEER = "engineer"   # soạn/duyệt recipe
    ADMIN = "admin"
