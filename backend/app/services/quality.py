"""Chất lượng, deviation, hold/release (tài liệu §7.5).

- Pass/fail tính theo limit số học (không dùng text tùy ý).
- Hold/release theo vai trò QA; release bị chặn nếu còn kết quả FAIL chưa có
  deviation được xử lý.
- Deviation có workflow chuẩn.
"""

from sqlalchemy import func, select
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
from ..models.brewing import BottleRecord, BrewBatch, FermentRecord, FilterRecord
from ..models.materials import MaterialLot
from ..models.quality import Deviation, QualityResult
from ..security import User, require_role

# Scope theo công đoạn sản xuất (Nấu/Lên men/Lọc/Chiết) — scope_id là PK thật của bản ghi,
# KHÁC quy ước scope_id ghép chuỗi (VD "{lm_code}__len_men_phu") mà qc_catalog.py dùng để khai
# báo chỉ tiêu theo từng công đoạn con; 2 hệ thống dùng chung bảng QualityResult/Deviation
# nhưng scope_id không bao giờ trùng nhau (PK ngẫu nhiên vs chuỗi ghép có "__") nên không xung
# đột. Xem routers/quality.py (Hold/Release, Mở deviation) và app.js VIEWS.quality.
_STAGE_MODELS = {
    "brew_batch": BrewBatch,
    "ferment": FermentRecord,
    "filter": FilterRecord,
    "bottle": BottleRecord,
}


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
    value_text = payload.get("value_text")
    lower = payload.get("lower_limit")
    upper = payload.get("upper_limit")
    # Chỉ tiêu kiểu "text" (value_text có nội dung) — ghi chú tự do, không so target/USL/LSL,
    # không tính pass/fail (khác hẳn numeric/pass_fail — xem QCParameter.value_type).
    if value_text:
        status = ResultStatus.PASS.value
        value, lower, upper = None, None, None
    else:
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
        value_text=value_text,
        ca_value=payload.get("ca_value"),
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
                 actor=user, after={"parameter": result.parameter, "value": value, "ca_value": result.ca_value,
                                    "status": status, "scope": f"{scope_type}:{scope_id}"})
    db.commit()
    db.refresh(result)
    return result


def set_hold(db: Session, scope_type: str, scope_id: str, on_hold: bool, user: User,
             reason: str = None, parameter: str = None) -> dict:
    """Đặt/huỷ hold. Release (huỷ hold) phải do QA và không còn FAIL treo. `parameter` (mã chỉ
    tiêu người dùng chọn từ panel "Chỉ tiêu của phạm vi này") không có cột riêng trên model —
    lưu vào audit log để hiện lại ở Lịch sử Hold/Release (xem frontend/app.js::holdHistory)."""
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
                 before=before, after={"quality_status": new_status, "parameter": parameter}, reason=reason)
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
        parameter=payload.get("parameter"),
        state=DeviationState.OPEN.value,
        opened_by=user.username,
        opened_at=utcnow(),
    )
    db.add(dev)
    _set_quality_status(db, scope_type, scope_id, QualityStatus.ON_HOLD.value)
    record_audit(db, entity_type="deviation", entity_id=dev.deviation_id, action="open",
                 actor=user, after={"code": dev.deviation_code, "scope": f"{scope_type}:{scope_id}",
                                    "parameter": dev.parameter})
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

def _get_scope_obj(db: Session, scope_type: str, scope_id: str):
    if scope_type == "batch":
        return db.get(BatchExecution, scope_id)
    if scope_type == "lot":
        return db.get(MaterialLot, scope_id)
    model = _STAGE_MODELS.get(scope_type)
    if model is None:
        raise DomainError(f"Phạm vi không hợp lệ: {scope_type}")
    return db.get(model, scope_id)


def _assert_scope_exists(db: Session, scope_type: str, scope_id: str) -> None:
    if not _get_scope_obj(db, scope_type, scope_id):
        raise NotFoundError(f"{scope_type} '{scope_id}' không tồn tại.")


def _set_quality_status(db: Session, scope_type: str, scope_id: str, status: str) -> dict:
    obj = _get_scope_obj(db, scope_type, scope_id)
    if scope_type == "lot":
        before = {"status": obj.status}
        # Lô: ánh xạ quality status sang lot status.
        obj.status = (LotStatus.RELEASED.value if status == QualityStatus.RELEASED.value
                      else LotStatus.ON_HOLD.value if status == QualityStatus.ON_HOLD.value
                      else obj.status)
    else:
        before = {"quality_status": obj.quality_status}
        obj.quality_status = status
    if status == QualityStatus.ON_HOLD.value:
        _cascade_hold_siblings(db, scope_type, obj)
    return before


# Hold 1 mẻ nấu (brew_batch) hoặc mẻ lọc (filter) phải kéo cả lô nấu (BrewRecord)/lô lọc
# (FilterOrder) chứa nó vào diện hold — người vận hành mở khóa lô lọc/lô nấu và thấy MỌI mẻ
# trong đó đang bị giữ, không chỉ mẻ vừa fail. CHỈ áp dụng chiều hold: release 1 mẻ KHÔNG tự
# release cả lô — mỗi mẻ anh chị em vẫn phải tự qua được _assert_releasable của chính nó (an
# toàn hơn, tránh 1 lần release vô tình mở khóa luôn các mẻ khác còn FAIL treo).
def _cascade_hold_siblings(db: Session, scope_type: str, obj) -> None:
    if scope_type == "brew_batch":
        siblings = db.execute(select(BrewBatch).where(
            BrewBatch.brew_id == obj.brew_id, BrewBatch.batch_id != obj.batch_id)).scalars().all()
    elif scope_type == "filter" and obj.filter_order_id:
        siblings = db.execute(select(FilterRecord).where(
            FilterRecord.filter_order_id == obj.filter_order_id,
            FilterRecord.filter_id != obj.filter_id)).scalars().all()
    else:
        return
    for sib in siblings:
        sib.quality_status = QualityStatus.ON_HOLD.value


def latest_results_by_param(db: Session, scope_type: str, scope_id: str) -> dict[str, QualityResult]:
    """Chỉ giữ giá trị MỚI NHẤT đã khai báo cho mỗi chỉ tiêu — khai báo lại 1 chỉ tiêu (sửa giá
    trị nhập nhầm) không được để giá trị FAIL cũ (đã bị đè) tiếp tục tính là đang treo.
    Sắp theo coalesce(sampled_at, recorded_at): các stage lấy mẫu NHIỀU LẦN (len_men_chinh/
    len_men_phu, xem qc_catalog.record_qc_sample) có nhiều dòng/chỉ tiêu với sampled_at do
    người dùng khai (có thể lùi ngày) — phải chọn đúng theo mốc lấy mẫu THỰC TẾ, không phải
    thứ tự lưu vào DB. Mọi nơi khác chỉ có 1 dòng/chỉ tiêu (ghi đè tại chỗ) và sampled_at luôn
    NULL nên coalesce rơi về recorded_at y hệt hành vi cũ."""
    results = db.execute(
        select(QualityResult).where(
            QualityResult.scope_type == scope_type, QualityResult.scope_id == scope_id
        ).order_by(func.coalesce(QualityResult.sampled_at, QualityResult.recorded_at))
    ).scalars().all()
    return {r.parameter: r for r in results}


def _assert_releasable(db: Session, scope_type: str, scope_id: str) -> None:
    from . import qc_catalog
    missing = qc_catalog.missing_mandatory_params(db, scope_type, scope_id)
    if missing:
        raise DomainError(
            f"Không thể release: còn chỉ tiêu bắt buộc chưa khai báo: {', '.join(missing)}."
        )

    if scope_type == "lot":
        # Tạm thời (theo yêu cầu 2026-08-01): duyệt chỉ tiêu NVL không chặn khi có chỉ tiêu
        # FAIL — màn hình Kho NVL không có luồng mở/đóng deviation cho lô NVL nên yêu cầu
        # "mọi FAIL phải có deviation CLOSED" bên dưới sẽ chặn cứng không lối ra. Chỉ cần
        # khai báo đủ chỉ tiêu bắt buộc (đã kiểm tra ở trên) là cho duyệt qua.
        return

    latest_by_param = latest_results_by_param(db, scope_type, scope_id)
    fails = [r for r in latest_by_param.values() if r.status == ResultStatus.FAIL.value]
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
