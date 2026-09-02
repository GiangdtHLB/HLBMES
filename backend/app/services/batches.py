"""Thực thi mẻ (tài liệu §7.1, §4.2).

- Tạo batch chỉ từ recipe version EFFECTIVE, và SNAPSHOT recipe vào batch.
- State machine có kiểm soát; mọi chuyển trạng thái được audit.
- Consume lot -> tạo genealogy edge + trừ tồn; produce lot -> tạo lô output + edge.
- Không cho close khi chưa release chất lượng hoặc còn QC bắt buộc chưa đạt.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import (
    BATCH_TRANSITIONS,
    BatchState,
    GenealogyRelation,
    LotStatus,
    QualityStatus,
    Role,
    WorkOrderState,
    new_id,
    utcnow,
)
from ..errors import DomainError, NotFoundError
from ..models.batch_pipeline import BatchTank, BatchTankLink
from ..models.batches import BatchExecution
from ..models.brewing import BrewOrder
from ..models.isa88 import BatchPhaseRun
from ..models.lines import ProductionLine
from ..models.materials import GenealogyEdge, MaterialLot
from ..models.materials_ext import Dispense, DispenseLine
from ..models.metrics import ProcessReading
from ..models.quality import QualityResult
from ..models.recipe_ext import BatchYieldActual
from ..models.recipes import RecipeVersion
from ..models.workorder import WorkOrder
from ..security import User, require_role
from . import bom, genealogy, qc_catalog


def create_batch(db: Session, order_id: str, recipe_version_id: str, user: User,
                 batch_code: str = None, planned_qty: float = None,
                 allow_shortage: bool = False, work_order_id: str = None,
                 brewhouse_line_id: str = None) -> BatchExecution:
    require_role(user, Role.SUPERVISOR, Role.ENGINEER)
    order = db.get(BrewOrder, order_id)
    if not order:
        raise NotFoundError("Lệnh nấu không tồn tại.")
    wo = None
    if work_order_id:
        wo = db.get(WorkOrder, work_order_id)
        if not wo:
            raise NotFoundError("Lệnh SX (điều độ) không tồn tại.")
        if wo.brew_order_id != order_id:
            raise DomainError(f"Lệnh SX '{wo.wo_code}' không thuộc Lệnh nấu đã chọn.")
    # Dây chuyền nấu: mặc định lấy theo Lệnh SX đã chọn (nếu có), nhưng chọn/sửa độc lập được
    # ngay ở "Tạo mẻ" — chỉ cần validate khi người dùng THẬT SỰ chỉ định (khác wo.brewhouse_line_id).
    if not brewhouse_line_id and wo:
        brewhouse_line_id = wo.brewhouse_line_id
    if brewhouse_line_id:
        line_row = db.get(ProductionLine, brewhouse_line_id)
        if not line_row or line_row.kind != "brewhouse":
            raise DomainError("Chọn Dây chuyền nấu hợp lệ (Danh mục Dây chuyền, kind='brewhouse').")
    rv = db.get(RecipeVersion, recipe_version_id)
    if not rv:
        raise NotFoundError("Recipe version không tồn tại.")
    if rv.state != "effective":
        # Chỉ recipe đã effective mới được dùng để chạy mẻ (tài liệu §7.1, §7.2).
        raise DomainError("Chỉ được dùng recipe version ở trạng thái 'effective' để tạo mẻ.")

    qty = planned_qty if planned_qty is not None else order.planned_volume_hl
    if qty is None or qty <= 0:
        raise DomainError("SL kế hoạch của mẻ phải > 0.")
    snapshot = {
        "recipe_id": rv.recipe_id,
        "version_no": rv.version_no,
        "base_qty": rv.base_qty,
        "base_uom": rv.base_uom,
        "parameters": rv.parameters,
        "materials": rv.materials,
        "quality_checks": rv.quality_checks,
        "yield_steps": getattr(rv, "yield_steps", []) or [],
        "procedure": getattr(rv, "procedure", []) or [],
        "snapshot_at": utcnow().isoformat(),
    }
    # Kiểm tra tồn kho theo BOM trước khi tạo mẻ (tài liệu §7.1: material availability).
    avail = bom.availability(db, snapshot, qty, brew_order_id=order_id)
    if avail["shortage"] and not allow_shortage:
        shorts = [f"{r['material_code']} thiếu {r['short']} {r['uom'] or ''} "
                  f"(cần {r['required']}, tồn {r['available']})"
                  for r in avail["rows"] if not r["ok"]]
        raise DomainError("Không đủ tồn kho theo định mức: " + "; ".join(shorts)
                          + ". Bỏ qua bằng allow_shortage nếu chấp nhận.")

    # Mã mẻ Braumat: BẮT BUỘC số nguyên dương + unique THEO NĂM (batch_year), reset lại mỗi năm
    # (mirror brew_code/lm_code/filter_code/bottle_code — yêu cầu người dùng 2026-09-02: "Ép
    # định dạng số nguyên cho mẻ từ giờ trở đi và khi hết năm thì sẽ tự tính lại từ đầu"). Dữ
    # liệu cũ (trước ràng buộc này) có thể còn mã dạng chữ — KHÔNG bị ép sửa lại, chỉ áp dụng
    # validate này cho bản ghi tạo MỚI.
    batch_year = utcnow().year
    if batch_code:
        if not batch_code.isdigit() or int(batch_code) <= 0:
            raise DomainError("Mã mẻ Braumat phải là số nguyên dương (VD 1, 2, 15).")
        if db.execute(select(BatchExecution).where(
            BatchExecution.batch_code == batch_code, BatchExecution.batch_year == batch_year,
        )).scalar_one_or_none():
            raise DomainError(f"Mã mẻ Braumat '{batch_code}' đã tồn tại trong năm {batch_year}.")
        code = batch_code
    else:
        # Tự sinh số kế tiếp TRONG NĂM HIỆN TẠI (mirror create_brew_batches_bulk module cũ) —
        # chỉ xét mã của batch_year hiện tại, năm mới bắt đầu lại từ 1.
        existing_codes = [row[0] for row in db.execute(
            select(BatchExecution.batch_code).where(BatchExecution.batch_year == batch_year)
        ).all()]
        code = str(max((int(c) for c in existing_codes if c.isdigit()), default=0) + 1)
    batch = BatchExecution(
        batch_id=new_id(),
        batch_code=code,
        batch_year=batch_year,
        order_id=order_id,
        work_order_id=work_order_id,
        brewhouse_line_id=brewhouse_line_id,
        recipe_version_id=recipe_version_id,
        # Dịch bia thật của mẻ lấy từ chính RecipeVersion đã chọn để tạo mẻ này (luôn có, đã
        # validate ở trên) — Lệnh nấu có thể chưa chốt product_id cụ thể.
        product_id=rv.product_id,
        state=BatchState.PLANNED.value,
        quality_status=QualityStatus.PENDING.value,
        planned_qty=qty,
        uom="hl",
        recipe_snapshot=snapshot,
        actuals=[],
        created_at=utcnow(),
    )
    db.add(batch)
    record_audit(db, entity_type="batch", entity_id=batch.batch_id, action="create",
                 actor=user, after={"batch_code": code, "recipe_version": rv.version_no})
    db.commit()
    db.refresh(batch)
    return batch


def _assert_not_locked(batch: BatchExecution) -> None:
    if batch.ebr_locked:
        raise DomainError("Hồ sơ mẻ (EBR) đã khóa — không thể thay đổi; chỉ tạo amendment.")


def set_brewhouse_line(db: Session, batch_id: str, brewhouse_line_id: str, user: User) -> BatchExecution:
    """Chọn/sửa Dây chuyền nấu của 1 mẻ đã tồn tại — độc lập với lúc tạo mẻ (kể cả mẻ tạo qua
    "Phát mẻ", nơi giá trị này chỉ tự kế thừa từ Work Order chứ người dùng chưa hề chọn, xem
    services/workorders.py::dispatch). Cho phép bỏ chọn (truyền None) — mirror validate ở
    create_batch, chỉ chặn khi có giá trị nhưng không hợp lệ."""
    require_role(user, Role.SUPERVISOR, Role.ENGINEER)
    batch = _get(db, batch_id)
    _assert_not_locked(batch)
    if brewhouse_line_id:
        line_row = db.get(ProductionLine, brewhouse_line_id)
        if not line_row or line_row.kind != "brewhouse":
            raise DomainError("Chọn Dây chuyền nấu hợp lệ (Danh mục Dây chuyền, kind='brewhouse').")
    before = {"brewhouse_line_id": batch.brewhouse_line_id}
    batch.brewhouse_line_id = brewhouse_line_id
    record_audit(db, entity_type="batch", entity_id=batch.batch_id, action="set_brewhouse_line",
                 actor=user, before=before, after={"brewhouse_line_id": brewhouse_line_id})
    db.commit()
    db.refresh(batch)
    return batch


def set_start_at(db: Session, batch_id: str, start_at, user: User) -> BatchExecution:
    """Sửa giờ bắt đầu mẻ trực tiếp — độc lập với transition() (vốn chỉ tự set = utcnow() lúc
    chuyển sang running, không cho sửa lại) — gọi lại được nhiều lần để sửa nếu bấm nhầm,
    mirror routers/brewing.py::update_brew_batch_start (module Nấu-Lọc-Chiết cũ)."""
    require_role(user, Role.OPERATOR, Role.SUPERVISOR, Role.ENGINEER)
    batch = _get(db, batch_id)
    _assert_not_locked(batch)
    before = {"start_at": batch.start_at.isoformat() if batch.start_at else None}
    batch.start_at = start_at
    record_audit(db, entity_type="batch", entity_id=batch.batch_id, action="set_start_at",
                 actor=user, before=before, after={"start_at": start_at.isoformat()})
    db.commit()
    db.refresh(batch)
    return batch


def set_end_at(db: Session, batch_id: str, end_at, user: User) -> BatchExecution:
    """Sửa giờ kết thúc mẻ trực tiếp — gọi lại được nhiều lần để sửa nếu bấm nhầm, mirror
    routers/brewing.py::finish_brew_batch (module cũ)."""
    require_role(user, Role.OPERATOR, Role.SUPERVISOR, Role.ENGINEER)
    batch = _get(db, batch_id)
    _assert_not_locked(batch)
    before = {"end_at": batch.end_at.isoformat() if batch.end_at else None}
    batch.end_at = end_at
    record_audit(db, entity_type="batch", entity_id=batch.batch_id, action="set_end_at",
                 actor=user, before=before, after={"end_at": end_at.isoformat()})
    db.commit()
    db.refresh(batch)
    return batch


def set_actual_qty(db: Session, batch_id: str, actual_qty: float, user: User) -> BatchExecution:
    """Nhập/sửa trực tiếp SL thực tế (VD lít/hl dịch thực tế thu được) — KHÁC produce_lot (không
    bắt buộc tạo lô output/genealogy edge mỗi lần); chỉ ghi nhận con số tổng dùng để đối chiếu
    KH/TT và khi gộp mẻ vào tank lên men (xem services/batch_pipeline.py::merge_batches_into_tank,
    vốn đã đọc thẳng batch.actual_qty theo đúng cách này).

    Mẻ có thể đã được gộp vào 1 tank lên men TỪ TRƯỚC khi có SL thực tế (gộp lúc còn "planned" —
    mirror thực tế nấu nhiều mẻ liên tiếp cùng đổ 1 tank, xem merge_batches_into_tank), nên tank
    không tính on_hand theo tổng cố định lúc gộp mà CỘNG DỒN theo actual_qty của từng mẻ — ở đây
    khi actual_qty được ghi/sửa, cộng thêm đúng phần CHÊNH LỆCH (mirror on_hand giảm theo DELTA ở
    finish_filter_tank/finish_bottle) vào on_hand/volume_hl của tank đang gộp (nếu có)."""
    require_role(user, Role.OPERATOR, Role.SUPERVISOR, Role.ENGINEER)
    batch = _get(db, batch_id)
    _assert_not_locked(batch)
    if actual_qty < 0:
        raise DomainError("SL thực tế phải >= 0.")
    before = {"actual_qty": batch.actual_qty}
    delta = actual_qty - (batch.actual_qty or 0.0)
    batch.actual_qty = actual_qty
    if delta:
        link = db.execute(select(BatchTankLink).where(BatchTankLink.batch_id == batch_id)).scalar_one_or_none()
        if link:
            tank = db.get(BatchTank, link.tank_id)
            if tank:
                from . import batch_pipeline as batch_pipeline_svc
                # Tank có thể đã bị khóa qua services/ebr.py::lock_pack_lot (cascade xuống cả
                # cây genealogy khi khóa hồ sơ EBR lô thành phẩm) dù chính mẻ này (batch) chưa
                # chắc "ebr_locked" — kiểm tra riêng cả tank, không chỉ _assert_not_locked(batch)
                # ở trên (yêu cầu người dùng 2026-09-01).
                batch_pipeline_svc._assert_unlocked(tank)
                new_on_hand = round(tank.on_hand + delta, 3)
                if delta > 0:
                    batch_pipeline_svc._assert_within_capacity(
                        new_on_hand, batch_pipeline_svc.usable_capacity_for_code(db, tank.tank_lm, "tank"),
                        tank.tank_lm, "tank lên men")
                tank.on_hand = new_on_hand
                tank.volume_hl = round(tank.volume_hl + delta, 3)
    record_audit(db, entity_type="batch", entity_id=batch.batch_id, action="set_actual_qty",
                 actor=user, before=before, after={"actual_qty": actual_qty})
    db.commit()
    db.refresh(batch)
    return batch


def transition(db: Session, batch_id: str, target: str, user: User, reason: str = None) -> BatchExecution:
    batch = _get(db, batch_id)
    _assert_not_locked(batch)
    try:
        target_state = BatchState(target)
    except ValueError:
        raise DomainError(f"Trạng thái không hợp lệ: {target}")
    current = BatchState(batch.state)
    if target_state not in BATCH_TRANSITIONS[current]:
        raise DomainError(f"Không thể chuyển mẻ từ {current.value} sang {target}.")

    require_role(user, Role.OPERATOR, Role.SUPERVISOR, Role.ENGINEER)

    if target_state == BatchState.CLOSED:
        _assert_closeable(db, batch)

    if target_state == BatchState.COMPLETED:
        missing = []
        if batch.start_at is None:
            missing.append("thời gian bắt đầu")
        if batch.end_at is None:
            missing.append("thời gian kết thúc")
        if batch.actual_qty is None:
            missing.append("SL thực tế")
        if missing:
            raise DomainError(f"Cần nhập {', '.join(missing)} trước khi hoàn thành mẻ.")

    before = {"state": batch.state}
    batch.state = target_state.value
    if target_state == BatchState.RUNNING and batch.start_at is None:
        batch.start_at = utcnow()
    batch.version += 1
    record_audit(db, entity_type="batch", entity_id=batch.batch_id,
                 action=f"transition:{target}", actor=user, before=before,
                 after={"state": batch.state}, reason=reason)
    if target_state in (BatchState.COMPLETED, BatchState.CANCELLED) and batch.work_order_id:
        _auto_complete_work_order(db, batch.work_order_id, user)
    db.commit()
    db.refresh(batch)
    return batch


def _auto_complete_work_order(db: Session, work_order_id: str, user: User) -> None:
    """Khi TẤT CẢ mẻ (BatchExecution) thuộc 1 Lệnh SX (Điều độ) đều đã hoàn thành/đóng, tự động
    chuyển Lệnh SX đó sang "completed" — không bắt người dùng vào Điều độ bấm tay riêng (yêu cầu
    người dùng 2026-09-01, đối xứng với dispatch() tự chuyển released->in_progress). Mẻ đã hủy
    (cancelled) không tính là "chưa xong" — chỉ chặn tự hoàn thành nếu còn mẻ thật sự dở dang
    (planned/ready/running/held); vẫn cần ít nhất 1 mẻ không bị hủy. Chỉ tự chuyển khi Lệnh SX
    đang "in_progress" (đúng WORKORDER_TRANSITIONS — đã completed/closed/cancelled thì bỏ qua)."""
    wo = db.get(WorkOrder, work_order_id)
    if not wo or wo.status != WorkOrderState.IN_PROGRESS.value:
        return
    siblings = db.execute(select(BatchExecution).where(
        BatchExecution.work_order_id == work_order_id)).scalars().all()
    unresolved = [b for b in siblings if b.state not in (
        BatchState.COMPLETED.value, BatchState.CLOSED.value, BatchState.CANCELLED.value)]
    resolved_done = [b for b in siblings if b.state in (BatchState.COMPLETED.value, BatchState.CLOSED.value)]
    if unresolved or not resolved_done:
        return
    before = {"status": wo.status}
    wo.status = WorkOrderState.COMPLETED.value
    record_audit(db, entity_type="work_order", entity_id=wo.wo_id, action="auto_complete",
                 actor=user, before=before, after={"status": wo.status},
                 reason="Tự động hoàn thành — mọi mẻ trong lệnh đã hoàn thành/đóng")


def record_actual(db: Session, batch_id: str, actual: dict, user: User) -> BatchExecution:
    """Ghi 1 giá trị thực tế cho tham số quy trình — tham số/target/giới hạn lấy từ
    recipe_snapshot.parameters (đã đóng băng từ RecipeVersionParamItem lúc tạo mẻ, xem
    services/recipes.py::_resolve_param_items), mirror cách record_result (quality.py) nhận
    lower_limit/upper_limit do client gửi kèm (đã lấy từ server trước đó) để tính pass/fail,
    không tự tra lại danh mục ở đây."""
    batch = _get(db, batch_id)
    _assert_not_locked(batch)
    if batch.state != BatchState.RUNNING.value:
        raise DomainError("Chỉ ghi actual khi mẻ đang running.")
    value = actual.get("actual")
    lower, upper = actual.get("lower"), actual.get("upper")
    status = None
    if value is not None:
        status = "fail" if ((lower is not None and value < lower) or
                            (upper is not None and value > upper)) else "pass"
    entry = {
        "name": actual.get("name"),
        "param_id": actual.get("param_id"),
        "target": actual.get("target"),
        "actual": value,
        "unit": actual.get("unit"),
        "phase": actual.get("phase"),
        "lower": lower,
        "upper": upper,
        "status": status,
        "recorded_by": user.username,
        "recorded_at": utcnow().isoformat(),
    }
    batch.actuals = list(batch.actuals) + [entry]
    batch.version += 1
    record_audit(db, entity_type="batch", entity_id=batch.batch_id, action="record_actual",
                 actor=user, after=entry)
    db.commit()
    db.refresh(batch)
    return batch


def consume_lot(db: Session, batch_id: str, lot_id: str, quantity: float, user: User,
                allow_over: bool = False) -> dict:
    """Tiêu thụ một lô nguyên liệu vào mẻ: trừ tồn + tạo genealogy edge.

    Chặn vượt định mức BOM (định mức scale × (1+dung sai)) trừ khi allow_over."""
    require_role(user, Role.OPERATOR, Role.SUPERVISOR, Role.ENGINEER)
    batch = _get(db, batch_id)
    _assert_not_locked(batch)
    lot = db.get(MaterialLot, lot_id)
    if not lot:
        raise NotFoundError("Lô vật tư không tồn tại.")
    if lot.status == LotStatus.ON_HOLD.value:
        raise DomainError(f"Lô {lot.lot_code} đang ON HOLD, không được tiêu thụ.")
    if quantity <= 0 or quantity > lot.quantity:
        raise DomainError(f"Số lượng tiêu thụ không hợp lệ (tồn {lot.quantity} {lot.uom}).")

    # Chặn vượt định mức BOM (tài liệu §7.4).
    code = bom.material_code_for_lot(db, lot)
    ceil = bom.ceiling_for_material(db, batch, code)
    if ceil and not allow_over:
        ceiling, planned = ceil
        # Nếu mã này thuộc 1 Nhóm vật tư thay thế dùng CHUNG định mức (không member_qty riêng),
        # "đã dùng" phải cộng dồn thực tế của MỌI mã thành viên trong nhóm — ngưỡng vốn tính
        # chung cho cả nhóm, không phải riêng mã này (xem bom.py::actual_consumed_for_match).
        already = bom.actual_consumed_for_match(db, batch, code)
        if round(already + quantity, 3) > ceiling:
            raise DomainError(
                f"Vượt định mức BOM cho {code}: đã dùng {round(already,3)}, thêm {quantity} "
                f"> ngưỡng {ceiling} (định mức {planned} + dung sai). "
                f"Bỏ qua bằng allow_over nếu có phê duyệt.")

    lot.quantity = round(lot.quantity - quantity, 6)
    if lot.quantity <= 1e-9:
        lot.quantity = 0.0
        lot.status = LotStatus.CONSUMED.value
    genealogy.add_edge(db, from_type="lot", from_id=lot.lot_id, to_type="batch",
                       to_id=batch.batch_id, relation=GenealogyRelation.CONSUME.value,
                       quantity=quantity, uom=lot.uom, source_event="consume_lot")
    record_audit(db, entity_type="batch", entity_id=batch.batch_id, action="consume_lot",
                 actor=user, after={"lot_code": lot.lot_code, "quantity": quantity, "uom": lot.uom})
    db.commit()
    return {"batch_id": batch.batch_id, "lot_id": lot.lot_id, "remaining": lot.quantity}


def produce_lot(db: Session, batch_id: str, lot_code: str, quantity: float, lot_type: str,
                user: User) -> MaterialLot:
    """Mẻ sinh ra lô output (brew/bright/package): tạo lô + genealogy edge."""
    require_role(user, Role.OPERATOR, Role.SUPERVISOR, Role.ENGINEER)
    batch = _get(db, batch_id)
    _assert_not_locked(batch)
    lot = MaterialLot(
        lot_id=new_id(),
        lot_code=lot_code,
        lot_year=utcnow().year,
        product_id=batch.product_id,
        lot_type=lot_type,
        quantity=quantity,
        uom=batch.uom,
        status=LotStatus.ON_HOLD.value,  # lô mới mặc định hold tới khi release
        created_at=utcnow(),
    )
    db.add(lot)
    genealogy.add_edge(db, from_type="batch", from_id=batch.batch_id, to_type="lot",
                       to_id=lot.lot_id, relation=GenealogyRelation.PRODUCE.value,
                       quantity=quantity, uom=batch.uom, source_event="produce_lot")
    if batch.actual_qty is None:
        batch.actual_qty = quantity
    else:
        batch.actual_qty += quantity
    record_audit(db, entity_type="lot", entity_id=lot.lot_id, action="produce",
                 actor=user, after={"lot_code": lot_code, "quantity": quantity, "batch": batch.batch_code})
    db.commit()
    db.refresh(lot)
    return lot


def _assert_closeable(db: Session, batch: BatchExecution) -> None:
    """Không close mẻ nếu chưa release chất lượng hoặc QC bắt buộc (theo StageQcGroup,
    stage "nau", scope_type "batch") chưa pass (tài liệu §7.5: checkpoint bắt buộc ngăn
    release/đóng hồ sơ)."""
    if batch.quality_status != QualityStatus.RELEASED.value:
        raise DomainError("Không thể close: mẻ chưa được release chất lượng.")
    status = qc_catalog.stage_qc_status(db, "nau", "batch", batch.batch_id, product_id=batch.product_id)
    if not status["can_release"]:
        if status["pending"]:
            raise DomainError(f"Còn chỉ tiêu QC bắt buộc chưa khai báo: {status['pending']}")
        raise DomainError("Còn chỉ tiêu QC bắt buộc FAIL, chưa thể đóng mẻ.")


def delete_batch(db: Session, batch_id: str, user: User) -> None:
    """Xóa hẳn 1 mẻ sản xuất — mirror delete_brew_batch (module Nấu-Lọc-Chiết cũ): chỉ cho xóa
    khi hồ sơ chưa khóa (ebr_locked) VÀ mẻ chưa được gộp vào tank lên men nào (pipeline "Mẻ SX"
    mới — services/batch_pipeline.py::merge_batches_into_tank tạo genealogy edge thẳng từ
    batch, không qua lô NVL nên phải tự kiểm BatchTankLink riêng, không suy được qua genealogy
    của MaterialLot).

    consume_lot/dispense/backflush đều tạo genealogy edge (from_type="lot", to_type="batch")
    khi trừ tồn — hoàn lại đúng bằng cách cộng lại quantity trên edge, không cần phân biệt mẻ
    tiêu thụ qua đường nào. produce_lot tạo lô output (edge from_type="batch", to_type="lot") —
    chặn xóa nếu lô đó đã bị tiêu thụ tiếp ở nơi khác (ảnh hưởng truy xuất nguồn gốc), ngược lại
    xóa luôn lô output đó cùng mẻ."""
    require_role(user, Role.SUPERVISOR, Role.ENGINEER)
    batch = _get(db, batch_id)
    _assert_not_locked(batch)
    if db.execute(select(BatchTankLink.link_id).where(BatchTankLink.batch_id == batch_id)).first():
        raise DomainError(f"Mẻ '{batch.batch_code}' đã được gộp vào tank lên men — không thể xóa (ảnh hưởng truy xuất nguồn gốc).")

    consumed_edges = db.execute(select(GenealogyEdge).where(
        GenealogyEdge.to_type == "batch", GenealogyEdge.to_id == batch_id,
        GenealogyEdge.from_type == "lot")).scalars().all()
    for edge in consumed_edges:
        lot = db.get(MaterialLot, edge.from_id)
        if lot and edge.quantity:
            lot.quantity = round(lot.quantity + edge.quantity, 6)
            if lot.status == LotStatus.CONSUMED.value:
                lot.status = LotStatus.AVAILABLE.value

    produced_edges = db.execute(select(GenealogyEdge).where(
        GenealogyEdge.from_type == "batch", GenealogyEdge.from_id == batch_id,
        GenealogyEdge.to_type == "lot")).scalars().all()
    for edge in produced_edges:
        if db.execute(select(GenealogyEdge.edge_id).where(
                GenealogyEdge.from_type == "lot", GenealogyEdge.from_id == edge.to_id)).first():
            raise DomainError(
                f"Lô '{edge.to_id}' do mẻ '{batch.batch_code}' sản xuất đã được dùng tiếp ở nơi khác "
                "— không thể xóa (ảnh hưởng truy xuất nguồn gốc).")
    for edge in produced_edges:
        lot = db.get(MaterialLot, edge.to_id)
        if lot:
            db.delete(lot)

    for r in db.execute(select(QualityResult).where(
            QualityResult.scope_type == "batch", QualityResult.scope_id == batch_id)).scalars().all():
        db.delete(r)
    for pr in db.execute(select(BatchPhaseRun).where(BatchPhaseRun.batch_id == batch_id)).scalars().all():
        db.delete(pr)
    for ya in db.execute(select(BatchYieldActual).where(BatchYieldActual.batch_id == batch_id)).scalars().all():
        db.delete(ya)
    for rd in db.execute(select(ProcessReading).where(ProcessReading.batch_id == batch_id)).scalars().all():
        db.delete(rd)
    for disp in db.execute(select(Dispense).where(Dispense.batch_id == batch_id)).scalars().all():
        for dl in db.execute(select(DispenseLine).where(
                DispenseLine.dispense_id == disp.dispense_id)).scalars().all():
            db.delete(dl)
        db.delete(disp)

    db.flush()
    genealogy.delete_edges_for(db, "batch", batch_id)
    record_audit(db, entity_type="batch", entity_id=batch_id, action="delete", actor=user,
                before={"batch_code": batch.batch_code, "state": batch.state})
    db.delete(batch)
    db.commit()


def _get(db: Session, batch_id: str) -> BatchExecution:
    batch = db.get(BatchExecution, batch_id)
    if not batch:
        raise NotFoundError("Batch không tồn tại.")
    return batch
