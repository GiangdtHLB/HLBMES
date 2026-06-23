"""Chất lượng, deviation, hold/release (tài liệu §7.5).

- Pass/fail tính theo limit số học (không dùng text tùy ý).
- Hold/release theo vai trò QA; release bị chặn nếu còn kết quả FAIL chưa có
  deviation được xử lý.
- Deviation có workflow chuẩn.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import (
    DEVIATION_TRANSITIONS,
    DeviationState,
    LotStatus,
    QualityStatus,
    ResultStatus,
    Role,
    new_id,
    utcnow,
)
from ..errors import DomainError, NotFoundError
from ..models.batches import BatchExecution
from ..models.materials import MaterialLot
from ..models.quality import Deviation, QualityResult
from ..security import User, require_role


def _evaluate(value, lower, upper) -> str:
    if value is None:
        return ResultStatus.PENDING.value
    if lower is not None and value < lower:
        return ResultStatus.FAIL.value
    if upper is not None and value > upper:
        return ResultStatus.FAIL.value
    return ResultStatus.PASS.value


def record_result(db: Session, payload: dict, user: User) -> QualityResult:
    require_role(user, Role.QA, Role.OPERATOR)
    # Phạm vi loại test (§10.2): KCS chỉ ghi loại test được phân.
    from ..security import require_scope
    require_scope(user, "qc", payload.get("parameter"))
    scope_type = payload.get("scope_type", "batch")
    scope_id = payload["scope_id"]
    _assert_scope_exists(db, scope_type, scope_id)

    value = payload.get("value")
    lower = payload.get("lower_limit")
    upper = payload.get("upper_limit")
    status = _evaluate(value, lower, upper)
    result = QualityResult(
        result_id=new_id(),
        sample_id=payload.get("sample_id") or f"S-{new_id()[:8].upper()}",
        scope_type=scope_type,
        scope_id=scope_id,
        parameter=payload["parameter"],
        method=payload.get("method"),
        instrument=payload.get("instrument"),
        value=value,
        unit=payload.get("unit"),
        lower_limit=lower,
        upper_limit=upper,
        status=status,
        recorded_by=user.username,
        recorded_at=utcnow(),
    )
    db.add(result)

    # Kết quả FAIL tự động đưa scope về ON_HOLD (tài liệu §7.5).
    if status == ResultStatus.FAIL.value:
        _set_quality_status(db, scope_type, scope_id, QualityStatus.ON_HOLD.value)

    record_audit(db, entity_type="quality_result", entity_id=result.result_id, action="record",
                 actor=user, after={"parameter": result.parameter, "value": value, "status": status,
                                    "scope": f"{scope_type}:{scope_id}"})
    db.commit()
    db.refresh(result)
    return result


def set_hold(db: Session, scope_type: str, scope_id: str, on_hold: bool, user: User,
             reason: str = None) -> dict:
    """Đặt/huỷ hold. Release (huỷ hold) phải do QA và không còn FAIL treo."""
    _assert_scope_exists(db, scope_type, scope_id)
    if on_hold:
        require_role(user, Role.QA, Role.SUPERVISOR)
        new_status = QualityStatus.ON_HOLD.value
    else:
        # RELEASE: chỉ QA, và chặn nếu còn kết quả FAIL chưa được deviation xử lý.
        require_role(user, Role.QA)
        _assert_releasable(db, scope_type, scope_id)
        new_status = QualityStatus.RELEASED.value

    before = _set_quality_status(db, scope_type, scope_id, new_status)
    record_audit(db, entity_type=scope_type, entity_id=scope_id,
                 action="release" if not on_hold else "hold", actor=user,
                 before=before, after={"quality_status": new_status}, reason=reason)
    db.commit()
    return {"scope_type": scope_type, "scope_id": scope_id, "quality_status": new_status}


def open_deviation(db: Session, payload: dict, user: User) -> Deviation:
    require_role(user, Role.QA, Role.OPERATOR, Role.SUPERVISOR)
    scope_type = payload.get("scope_type", "batch")
    scope_id = payload["scope_id"]
    _assert_scope_exists(db, scope_type, scope_id)
    dev = Deviation(
        deviation_id=new_id(),
        deviation_code=f"DEV-{utcnow():%Y%m%d}-{new_id()[:5].upper()}",
        scope_type=scope_type,
        scope_id=scope_id,
        severity=payload.get("severity", "minor"),
        reason=payload["reason"],
        state=DeviationState.OPEN.value,
        opened_by=user.username,
        opened_at=utcnow(),
    )
    db.add(dev)
    _set_quality_status(db, scope_type, scope_id, QualityStatus.ON_HOLD.value)
    record_audit(db, entity_type="deviation", entity_id=dev.deviation_id, action="open",
                 actor=user, after={"code": dev.deviation_code, "scope": f"{scope_type}:{scope_id}"})
    db.commit()
    db.refresh(dev)
    return dev


def transition_deviation(db: Session, deviation_id: str, target: str, user: User,
                         payload: dict = None) -> Deviation:
    dev = db.get(Deviation, deviation_id)
    if not dev:
        raise NotFoundError("Deviation không tồn tại.")
    try:
        target_state = DeviationState(target)
    except ValueError:
        raise DomainError(f"Trạng thái không hợp lệ: {target}")
    current = DeviationState(dev.state)
    if target_state not in DEVIATION_TRANSITIONS[current]:
        raise DomainError(f"Không thể chuyển deviation từ {current.value} sang {target}.")

    payload = payload or {}
    if target_state in (DeviationState.DISPOSITION, DeviationState.APPROVAL, DeviationState.CLOSED):
        require_role(user, Role.QA)
    if target_state == DeviationState.INVESTIGATION:
        dev.investigation = payload.get("investigation", dev.investigation)
    if target_state == DeviationState.DISPOSITION:
        dev.disposition = payload.get("disposition", dev.disposition)
    if target_state == DeviationState.CLOSED:
        dev.approved_by = user.username
        dev.closed_at = utcnow()

    before = {"state": dev.state}
    dev.state = target_state.value
    record_audit(db, entity_type="deviation", entity_id=dev.deviation_id,
                 action=f"transition:{target}", actor=user, before=before,
                 after={"state": dev.state})
    db.commit()
    db.refresh(dev)
    return dev


# ---- helpers ----

def _assert_scope_exists(db: Session, scope_type: str, scope_id: str) -> None:
    obj = db.get(BatchExecution, scope_id) if scope_type == "batch" else db.get(MaterialLot, scope_id)
    if not obj:
        raise NotFoundError(f"{scope_type} '{scope_id}' không tồn tại.")


def _set_quality_status(db: Session, scope_type: str, scope_id: str, status: str) -> dict:
    if scope_type == "batch":
        obj = db.get(BatchExecution, scope_id)
        before = {"quality_status": obj.quality_status}
        obj.quality_status = status
    else:
        obj = db.get(MaterialLot, scope_id)
        before = {"status": obj.status}
        # Lô: ánh xạ quality status sang lot status.
        obj.status = (LotStatus.RELEASED.value if status == QualityStatus.RELEASED.value
                      else LotStatus.ON_HOLD.value if status == QualityStatus.ON_HOLD.value
                      else obj.status)
    return before


def _assert_releasable(db: Session, scope_type: str, scope_id: str) -> None:
    results = db.execute(
        select(QualityResult).where(
            QualityResult.scope_type == scope_type, QualityResult.scope_id == scope_id
        )
    ).scalars().all()
    fails = [r for r in results if r.status == ResultStatus.FAIL.value]
    if fails:
        # Còn FAIL: chỉ release được khi mọi deviation liên quan đã CLOSED.
        devs = db.execute(
            select(Deviation).where(
                Deviation.scope_type == scope_type, Deviation.scope_id == scope_id
            )
        ).scalars().all()
        open_devs = [d for d in devs if d.state != DeviationState.CLOSED.value]
        if open_devs or not devs:
            raise DomainError(
                "Không thể release: còn kết quả FAIL chưa được deviation đóng (disposition/approval)."
            )
