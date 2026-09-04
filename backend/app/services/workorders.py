"""Nghiệp vụ Lệnh sản xuất (Work Order) & điều độ (tài liệu §7.1).

"Phát mẻ" (dispatch) tạo NHIỀU Mẻ sản xuất (BatchExecution) liên tiếp — đánh số từ "Từ mẻ" do
người dùng nhập (VD từ mẻ 120, số mẻ 4 -> mã mẻ 120/121/122/123), gắn work_order_id = lệnh này
(tích hợp Điều độ→Mẻ sản xuất, xem batches.py::create_batch). KHÔNG còn tạo Nấu-Lọc-Chiết
(BrewRecord/BrewBatch) như trước — `_brew_record_for_wo` chỉ còn đọc dữ liệu CŨ (WO đã dispatch
kiểu cũ trước khi có thay đổi này) để hiển thị/tương thích ngược, không tạo mới nữa."""

import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import WORKORDER_TRANSITIONS, BatchState, WorkOrderState, new_id
from ..errors import DomainError, NotFoundError
from ..models.batches import BatchExecution
from ..models.brewing import BrewOrder, BrewRecord
from ..models.lines import ProductionLine
from ..models.recipes import RecipeVersion
from ..models.workorder import WorkOrder
from ..security import User, filter_by_scope, require_perm, require_scope
from . import batch_pipeline as batch_pipeline_svc
from . import batches as batch_svc
from . import brew_order as brew_order_svc


def _next_wo_code(db: Session) -> str:
    """Mã WO tự sinh mặc định "WO-{số thứ tự tăng dần}" (VD WO-1, WO-2...) — không theo ngày/mã
    ngẫu nhiên như trước (yêu cầu người dùng 2026-09-01). Số thứ tự = max hiện có (chỉ tính các
    mã đúng dạng "WO-<số>", bỏ qua mã tự đặt tay kiểu khác) + 1."""
    codes = db.execute(select(WorkOrder.wo_code)).scalars().all()
    max_n = 0
    for code in codes:
        m = re.fullmatch(r"WO-(\d+)", code or "")
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"WO-{max_n + 1}"


def create_wo(db: Session, payload: dict, user: User) -> WorkOrder:
    require_perm(user, "wo.manage")
    require_scope(user, "lines", payload.get("line"))
    bo = db.get(BrewOrder, payload["brew_order_id"])
    if not bo:
        raise NotFoundError("Lệnh nấu không tồn tại.")
    brew_order_svc._assert_unlocked(bo)
    if brew_order_svc.is_order_complete(db, bo.brew_order_id):
        raise DomainError(f"Lệnh nấu '{bo.order_code}' đã hoàn thành — không thể lập thêm Lệnh SX (điều độ) mới.")
    # Không còn bắt buộc chọn Dây chuyền nấu lúc lập lệnh (bỏ theo yêu cầu 2026-08-31) — chỉ
    # validate hợp lệ NẾU có truyền lên (mirror batches.py::create_batch cho BatchExecution).
    brewhouse_line_id = payload.get("brewhouse_line_id")
    if brewhouse_line_id:
        line_row = db.get(ProductionLine, brewhouse_line_id)
        if not line_row or line_row.kind != "brewhouse":
            raise DomainError("Dây chuyền nấu không hợp lệ (Danh mục Dây chuyền, kind='brewhouse').")
    rv_id = payload.get("recipe_version_id")
    # Lệnh nấu có thể chưa chốt Dịch bia cụ thể (bo.product_id) — Work Order cần 1 Dịch bia
    # CỤ THỂ (WorkOrder.product_id bắt buộc, dùng thật cho Mẻ sản xuất/BOM), nên nếu Lệnh nấu
    # chưa có product_id thì bắt buộc chọn Version ngay lúc lập Work Order để suy ra Dịch bia
    # (RecipeVersion.product_id).
    product_id = bo.product_id
    if not product_id:
        if not rv_id:
            raise DomainError("Lệnh nấu này chưa xác định Dịch bia — chọn Version lúc lập lệnh điều độ.")
        rv = db.get(RecipeVersion, rv_id)
        if not rv:
            raise NotFoundError("Recipe version không tồn tại.")
        product_id = rv.product_id
    sd = payload.get("scheduled_date") or date.today()
    wo_code = payload.get("wo_code")
    if wo_code:
        if db.execute(select(WorkOrder).where(WorkOrder.wo_code == wo_code)).scalar_one_or_none():
            raise DomainError(f"Mã WO '{wo_code}' đã tồn tại — chọn mã khác.")
    else:
        wo_code = _next_wo_code(db)
    wo = WorkOrder(
        wo_id=new_id(),
        wo_code=wo_code,
        brew_order_id=bo.brew_order_id,
        product_id=product_id,
        recipe_version_id=rv_id,
        planned_qty=float(payload.get("planned_qty") or bo.planned_volume_hl),
        uom=payload.get("uom") or "hl",
        line=payload.get("line"),
        brewhouse_line_id=brewhouse_line_id,
        shift=payload.get("shift", "A"),
        scheduled_date=sd,
        priority=int(payload.get("priority", 5)),
        status=WorkOrderState.PLANNED.value,
        note=payload.get("note"),
        created_by=user.username,
    )
    db.add(wo)
    record_audit(db, entity_type="work_order", entity_id=wo.wo_id, action="create", actor=user,
                 after={"wo_code": wo.wo_code, "qty": wo.planned_qty, "line": wo.line, "shift": wo.shift})
    try:
        db.commit()
    except IntegrityError:
        # Race: 2 request cùng lúc kiểm tra "chưa trùng" rồi cùng insert (TOCTOU) — unique
        # constraint DB chặn được, nhưng nếu không bắt ở đây sẽ lộ ra 500 thô thay vì 409.
        db.rollback()
        raise DomainError(f"Mã WO '{wo_code}' đã tồn tại — chọn mã khác.") from None
    db.refresh(wo)
    return wo


_BATCH_TERMINAL_STATES = (BatchState.CLOSED.value, BatchState.CANCELLED.value)
_BATCH_ACTIVE_STATES = (BatchState.PLANNED.value, BatchState.READY.value,
                        BatchState.RUNNING.value, BatchState.HELD.value)


def _assert_all_batches_terminal(db: Session, wo: WorkOrder) -> None:
    """Chặn "Chốt" (closed) lệnh sản xuất nếu còn Mẻ sản xuất nào thuộc lệnh chưa ở trạng thái
    kết thúc (closed/cancelled) — tránh chốt nhầm hồ sơ khi việc sản xuất thực tế chưa xong."""
    open_batches = db.execute(select(BatchExecution.batch_code).where(
        BatchExecution.work_order_id == wo.wo_id,
        BatchExecution.state.notin_(_BATCH_TERMINAL_STATES))).scalars().all()
    if open_batches:
        raise DomainError(
            f"Còn {len(open_batches)} mẻ chưa kết thúc (closed/cancelled): "
            f"{', '.join(sorted(open_batches))} — không thể chốt lệnh.")


def _assert_no_active_batches(db: Session, wo: WorkOrder) -> None:
    """Chặn chuyển "Hoàn thành" (completed) nếu còn Mẻ sản xuất nào thuộc lệnh CHƯA thực sự
    chạy xong (còn planned/ready/running/held) — trước đây chỉ "Chốt" (closed) mới kiểm tra
    mẻ, nên "Hoàn thành" cho qua kể cả khi mẻ vừa dispatch còn nguyên trạng thái planned
    (test_workorder_delete.py tự lộ bug này)."""
    active = db.execute(select(BatchExecution.batch_code).where(
        BatchExecution.work_order_id == wo.wo_id,
        BatchExecution.state.in_(_BATCH_ACTIVE_STATES))).scalars().all()
    if active:
        raise DomainError(
            f"Còn {len(active)} mẻ chưa hoàn thành sản xuất (planned/ready/running/held): "
            f"{', '.join(sorted(active))} — không thể đánh dấu 'Hoàn thành'.")


def transition(db: Session, wo_id: str, target: str, user: User, reason: str = None) -> WorkOrder:
    require_perm(user, "wo.manage")
    wo = _get(db, wo_id)
    require_scope(user, "lines", wo.line)
    brew_order_svc._assert_unlocked(db.get(BrewOrder, wo.brew_order_id))
    try:
        target_state = WorkOrderState(target)
    except ValueError:
        raise DomainError(f"Trạng thái không hợp lệ: {target}")
    current = WorkOrderState(wo.status)
    if target_state not in WORKORDER_TRANSITIONS[current]:
        raise DomainError(f"Không thể chuyển lệnh từ {current.value} sang {target}.")
    if target_state == WorkOrderState.IN_PROGRESS:
        # "in_progress" đúng ra chỉ nên đạt được qua dispatch() (Phát mẻ) — endpoint transition
        # công khai vẫn cho phép released->in_progress theo WORKORDER_TRANSITIONS, nên chặn ở
        # đây nếu chưa từng Phát mẻ (chưa có Mẻ sản xuất nào), tránh bỏ qua toàn bộ bước dispatch.
        if not db.execute(select(BatchExecution.batch_id).where(
                BatchExecution.work_order_id == wo.wo_id)).first():
            raise DomainError("Lệnh chưa 'Phát mẻ' — dùng nút Phát mẻ, không chuyển 'Đang chạy' thủ công.")
    if target_state == WorkOrderState.COMPLETED:
        _assert_no_active_batches(db, wo)
    if target_state == WorkOrderState.CLOSED:
        _assert_all_batches_terminal(db, wo)
    before = {"status": wo.status}
    wo.status = target_state.value
    record_audit(db, entity_type="work_order", entity_id=wo.wo_id, action=f"transition:{target}",
                 actor=user, before=before, after={"status": wo.status}, reason=reason)
    db.commit()
    db.refresh(wo)
    return wo


def _brew_record_for_wo(db: Session, wo_id: str):
    return db.execute(select(BrewRecord).where(BrewRecord.work_order_id == wo_id)).scalar_one_or_none()


def _split_planned_qty(planned_qty: float | None, batch_count: int) -> list:
    """Chia SL kế hoạch cho `batch_count` mẻ sao cho TỔNG đúng bằng `planned_qty` (không lệch
    do làm tròn từng phần như `round(planned_qty / batch_count, 3)` trước đây) — quy về đơn vị
    nguyên "phần nghìn" rồi chia dư nguyên, phần dư được gán cho các mẻ ĐẦU tiên."""
    if not planned_qty:
        return [None] * batch_count
    total_milli = round(planned_qty * 1000)
    base, rem = divmod(total_milli, batch_count)
    return [(base + (1 if i < rem else 0)) / 1000 for i in range(batch_count)]


def dispatch(db: Session, wo_id: str, user: User, from_batch: int, batch_count: int = 1,
             tank_lm: str = None) -> dict:
    """Điều độ: "Phát mẻ" — tạo `batch_count` Mẻ sản xuất (BatchExecution) liên tiếp, đánh số
    từ `from_batch` (VD từ mẻ 120, số mẻ 4 -> mã mẻ 120/121/122/123), mỗi mẻ gắn work_order_id
    = lệnh này + kế thừa Lệnh nấu/Recipe version/Dây chuyền nấu đã chọn sẵn ở Work Order (xem
    create_wo — Dây chuyền nấu ở WO không còn bắt buộc, có thể rỗng, khi đó mẻ tạo ra cũng
    không có Dây chuyền nấu, tự chọn sau ở tab Mẻ sản xuất nếu cần). SL kế hoạch của lệnh chia
    đều cho các mẻ. Kiểm tra TRƯỚC (all-or-nothing) mọi mã mẻ trong dải chưa tồn tại — không
    tạo mẻ nào nếu có mã trùng.

    Nếu truyền `tank_lm` (tank lên men vật lý còn trống, Danh mục ProductionLine kind="tank"),
    TỰ ĐỘNG gộp toàn bộ mẻ VỪA TẠO ở lần Phát mẻ này vào 1 BatchTank mới (mirror
    batch_pipeline.py::merge_batches_into_tank) — không cần thao tác "Gộp mẻ nấu vào tank lên
    men" riêng ở tab Tank lên men nữa. Mã tank tự sinh duy nhất theo (wo_code, from_batch)."""
    require_perm(user, "wo.dispatch")
    wo = _get(db, wo_id)
    require_scope(user, "lines", wo.line)
    brew_order_svc._assert_unlocked(db.get(BrewOrder, wo.brew_order_id))
    if wo.status not in (WorkOrderState.RELEASED.value, WorkOrderState.IN_PROGRESS.value):
        raise DomainError("Chỉ dispatch lệnh đã 'released' (hoặc đang chạy).")
    if not wo.recipe_version_id:
        raise DomainError(f"Lệnh {wo.wo_code} chưa gắn Recipe version — sửa lại lệnh để chọn trước khi Phát mẻ.")
    if batch_count < 1:
        raise DomainError("Số mẻ phải >= 1.")
    if from_batch < 1:
        raise DomainError("Từ mẻ phải là số nguyên dương.")
    codes = [str(from_batch + i) for i in range(batch_count)]
    dup = db.execute(select(BatchExecution.batch_code).where(
        BatchExecution.batch_code.in_(codes))).scalars().all()
    if dup:
        raise DomainError(f"Mã mẻ đã tồn tại: {', '.join(sorted(dup))} — chọn số Từ mẻ khác.")
    qtys = _split_planned_qty(wo.planned_qty, batch_count)
    created = [batch_svc.create_batch(db, wo.brew_order_id, wo.recipe_version_id, user,
                                      batch_code=code, planned_qty=qty, allow_shortage=True,
                                      work_order_id=wo.wo_id, brewhouse_line_id=wo.brewhouse_line_id)
              for code, qty in zip(codes, qtys)]
    tank_out = None
    if tank_lm:
        # Không truyền tank_code — merge_batches_into_tank tự sinh theo số thứ tự Lệnh SX (điều
        # độ) của các mẻ này (bỏ tiền tố "WO-", xem batch_pipeline.py::_auto_tank_code) — lô lên
        # men không cần mã riêng (yêu cầu người dùng 2026-09-01).
        tank_out = batch_pipeline_svc.merge_batches_into_tank(
            db, [b.batch_id for b in created],
            {"tank_lm": tank_lm, "note": f"Tự động gộp khi Phát mẻ (Lệnh {wo.wo_code})"}, user)
    if wo.status == WorkOrderState.RELEASED.value:
        wo.status = WorkOrderState.IN_PROGRESS.value
    record_audit(db, entity_type="work_order", entity_id=wo.wo_id, action="dispatch", actor=user,
                 after={"from_batch": from_batch, "batch_count": batch_count,
                        "batch_codes": [b.batch_code for b in created],
                        "tank_id": tank_out["tank_id"] if tank_out else None})
    db.commit()
    return {"wo_id": wo.wo_id, "wo_status": wo.status,
            "batch_ids": [b.batch_id for b in created], "batch_codes": [b.batch_code for b in created],
            "tank_id": tank_out["tank_id"] if tank_out else None,
            "tank_code": tank_out["tank_code"] if tank_out else None}


def rollup(db: Session, wo: WorkOrder) -> dict:
    """Planned vs actual: gộp theo Mẻ sản xuất (BatchExecution) liên kết TRỰC TIẾP qua
    work_order_id (tạo qua "Tạo mẻ" ở tab Mẻ sản xuất, chọn đúng Lệnh SX này) — KHÔNG còn qua
    Nấu-Lọc-Chiết (BrewRecord/BrewBatch, xem dispatch()/_brew_record_for_wo). brew_id/brew_code
    (mã nấu cũ, nếu đã "Phát mẻ" ít nhất 1 lần) vẫn trả riêng để dispatch() biết tái sử dụng mã
    nấu cũ khi phát mẻ tiếp — KHÔNG tính vào batches/actual_qty/completion_pct nữa."""
    batch_rows = db.execute(select(BatchExecution).where(
        BatchExecution.work_order_id == wo.wo_id)).scalars().all()
    actual = sum(b.actual_qty or 0.0 for b in batch_rows)
    pct = round(actual / wo.planned_qty * 100, 1) if wo.planned_qty else 0.0
    brew = _brew_record_for_wo(db, wo.wo_id)
    return {"batches": len(batch_rows), "actual_qty": round(actual, 3), "completion_pct": pct,
            "batch_list": [{"batch_id": b.batch_id, "batch_code": b.batch_code, "state": b.state,
                            "start_at": b.start_at, "end_at": b.end_at} for b in batch_rows],
            "brew_id": brew.brew_id if brew else None, "brew_code": brew.brew_code if brew else None}


def board(db: Session, date_from: date = None, date_to: date = None, line: str = None,
          user: User = None) -> list:
    """Bảng điều độ: danh sách lệnh + planned/actual, lọc theo ngày/line.

    Nếu truyền `user`, lọc thêm theo phạm vi (scope) line của tài khoản (§10.2)."""
    stmt = select(WorkOrder)
    if date_from:
        stmt = stmt.where(WorkOrder.scheduled_date >= date_from)
    if date_to:
        stmt = stmt.where(WorkOrder.scheduled_date <= date_to)
    if line:
        stmt = stmt.where(WorkOrder.line == line)
    wos = db.execute(stmt.order_by(WorkOrder.scheduled_date, WorkOrder.shift,
                                   WorkOrder.priority)).scalars().all()
    out = []
    for wo in wos:
        r = rollup(db, wo)
        batch_states = [b["state"] for b in r["batch_list"]]
        can_complete = not any(s in _BATCH_ACTIVE_STATES for s in batch_states)
        can_close = all(s in _BATCH_TERMINAL_STATES for s in batch_states)
        out.append({"wo_id": wo.wo_id, "wo_code": wo.wo_code, "product_id": wo.product_id,
                    "brew_order_id": wo.brew_order_id, "recipe_version_id": wo.recipe_version_id,
                    "planned_qty": wo.planned_qty, "uom": wo.uom, "line": wo.line, "shift": wo.shift,
                    "brewhouse_line_id": wo.brewhouse_line_id,
                    "scheduled_date": wo.scheduled_date, "priority": wo.priority, "status": wo.status,
                    "note": wo.note, "actual_qty": r["actual_qty"], "completion_pct": r["completion_pct"],
                    "batches": r["batches"], "brew_id": r["brew_id"], "brew_code": r["brew_code"],
                    "can_complete": can_complete, "can_close": can_close})
    if user is not None:
        out = filter_by_scope(user, out, "lines", "line")
    return out


def _get(db: Session, wo_id: str) -> WorkOrder:
    wo = db.get(WorkOrder, wo_id)
    if not wo:
        raise NotFoundError("Lệnh sản xuất không tồn tại.")
    return wo


def delete_wo(db: Session, wo_id: str, user: User) -> None:
    """Xóa Lệnh sản xuất (điều độ) — chặn nếu đã "Phát mẻ" tạo Mẻ sản xuất (BatchExecution,
    xem dispatch()) HOẶC mã nấu thật kiểu cũ (BrewRecord, WO dispatch trước khi có thay đổi
    này) từ lệnh này, mirror quy ước chặn sửa/xóa-khi-đã-thực-hiện dùng ở mọi module lệnh khác
    (brew_order.py/filter_order.py/orders.py::_assert_not_executed)."""
    require_perm(user, "wo.manage")
    wo = _get(db, wo_id)
    require_scope(user, "lines", wo.line)
    brew_order_svc._assert_unlocked(db.get(BrewOrder, wo.brew_order_id))
    if db.execute(select(BatchExecution.batch_id).where(
            BatchExecution.work_order_id == wo.wo_id)).first():
        raise DomainError(f"Lệnh {wo.wo_code} đã có Mẻ sản xuất — không thể xóa.")
    if db.execute(select(BrewRecord.brew_id).where(BrewRecord.work_order_id == wo.wo_id)).first():
        raise DomainError(f"Lệnh {wo.wo_code} đã có mã nấu — không thể xóa.")
    record_audit(db, entity_type="work_order", entity_id=wo.wo_id, action="delete",
                 actor=user, before={"wo_code": wo.wo_code})
    db.delete(wo)
    db.commit()
