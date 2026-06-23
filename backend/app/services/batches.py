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
    new_id,
    utcnow,
)
from ..errors import DomainError, NotFoundError
from ..models.batches import BatchExecution
from ..models.materials import MaterialLot
from ..models.orders import ProductionOrder
from ..models.quality import QualityResult
from ..models.recipes import RecipeVersion
from ..security import User, require_role
from . import bom, genealogy


def create_batch(db: Session, order_id: str, recipe_version_id: str, user: User,
                 batch_code: str = None, planned_qty: float = None,
                 allow_shortage: bool = False, work_order_id: str = None) -> BatchExecution:
    require_role(user, Role.SUPERVISOR, Role.ENGINEER)
    order = db.get(ProductionOrder, order_id)
    if not order:
        raise NotFoundError("Production order không tồn tại.")
    rv = db.get(RecipeVersion, recipe_version_id)
    if not rv:
        raise NotFoundError("Recipe version không tồn tại.")
    if rv.state != "effective":
        # Chỉ recipe đã effective mới được dùng để chạy mẻ (tài liệu §7.1, §7.2).
        raise DomainError("Chỉ được dùng recipe version ở trạng thái 'effective' để tạo mẻ.")

    qty = planned_qty if planned_qty is not None else order.planned_qty
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
        "snapshot_at": utcnow().isoformat(),
    }
    # Kiểm tra tồn kho theo BOM trước khi tạo mẻ (tài liệu §7.1: material availability).
    avail = bom.availability(db, snapshot, qty)
    if avail["shortage"] and not allow_shortage:
        shorts = [f"{r['material_code']} thiếu {r['short']} {r['uom'] or ''} "
                  f"(cần {r['required']}, tồn {r['available']})"
                  for r in avail["rows"] if not r["ok"]]
        raise DomainError("Không đủ tồn kho theo định mức: " + "; ".join(shorts)
                          + ". Bỏ qua bằng allow_shortage nếu chấp nhận.")

    code = batch_code or f"B-{utcnow():%Y%m%d}-{new_id()[:6].upper()}"
    batch = BatchExecution(
        batch_id=new_id(),
        batch_code=code,
        order_id=order_id,
        work_order_id=work_order_id,
        recipe_version_id=recipe_version_id,
        product_id=order.product_id,
        state=BatchState.PLANNED.value,
        quality_status=QualityStatus.PENDING.value,
        planned_qty=qty,
        uom=order.uom,
        recipe_snapshot=snapshot,
        actuals=[],
        created_at=utcnow(),
    )
    db.add(batch)
    if order.status == "released":
        order.status = "in_progress"
    record_audit(db, entity_type="batch", entity_id=batch.batch_id, action="create",
                 actor=user, after={"batch_code": code, "recipe_version": rv.version_no})
    db.commit()
    db.refresh(batch)
    return batch


def _assert_not_locked(batch: BatchExecution) -> None:
    if batch.ebr_locked:
        raise DomainError("Hồ sơ mẻ (EBR) đã khóa — không thể thay đổi; chỉ tạo amendment.")


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

    before = {"state": batch.state}
    batch.state = target_state.value
    if target_state == BatchState.RUNNING and batch.start_at is None:
        batch.start_at = utcnow()
    if target_state == BatchState.COMPLETED:
        batch.end_at = utcnow()
    batch.version += 1
    record_audit(db, entity_type="batch", entity_id=batch.batch_id,
                 action=f"transition:{target}", actor=user, before=before,
                 after={"state": batch.state}, reason=reason)
    db.commit()
    db.refresh(batch)
    return batch


def record_actual(db: Session, batch_id: str, actual: dict, user: User) -> BatchExecution:
    batch = _get(db, batch_id)
    _assert_not_locked(batch)
    if batch.state not in (BatchState.RUNNING.value, BatchState.HELD.value):
        raise DomainError("Chỉ ghi actual khi mẻ đang running/held.")
    entry = {
        "name": actual.get("name"),
        "target": actual.get("target"),
        "actual": actual.get("actual"),
        "unit": actual.get("unit"),
        "phase": actual.get("phase"),
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
        already = bom.actual_consumed(db, batch.batch_id).get(code, 0.0)
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
    """Không close mẻ nếu chưa release chất lượng hoặc QC bắt buộc chưa pass
    (tài liệu §7.5: checkpoint bắt buộc ngăn release/đóng hồ sơ)."""
    if batch.quality_status != QualityStatus.RELEASED.value:
        raise DomainError("Không thể close: mẻ chưa được release chất lượng.")
    required = [c.get("parameter") for c in batch.recipe_snapshot.get("quality_checks", [])
                if c.get("mandatory")]
    if required:
        results = db.execute(
            select(QualityResult).where(
                QualityResult.scope_type == "batch", QualityResult.scope_id == batch.batch_id
            )
        ).scalars().all()
        passed = {r.parameter for r in results if r.status == "pass"}
        missing = [p for p in required if p not in passed]
        if missing:
            raise DomainError(f"Còn checkpoint QC bắt buộc chưa pass: {missing}")


def _get(db: Session, batch_id: str) -> BatchExecution:
    batch = db.get(BatchExecution, batch_id)
    if not batch:
        raise NotFoundError("Batch không tồn tại.")
    return batch
