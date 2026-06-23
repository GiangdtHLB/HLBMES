"""Hiệu suất (yield) theo công đoạn + cumulative yield/loss (tài liệu §7.2).

step_yield = output/input × 100. cumulative = tích các bước. loss = 100 − cumulative.
Cảnh báo khi yield thực một bước < warn_pct (fallback expected_pct) trong yield_steps.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import Role, new_id, utcnow
from ..errors import DomainError, NotFoundError
from ..models.batches import BatchExecution
from ..models.recipe_ext import BatchYieldActual
from ..security import User, require_role


def step_yield(input_qty, output_qty) -> float:
    if not input_qty or input_qty <= 0:
        return 0.0
    return round(output_qty / input_qty * 100.0, 2)


def record_yield(db: Session, batch_id: str, payload: dict, user: User) -> dict:
    require_role(user, Role.OPERATOR, Role.SUPERVISOR, Role.ENGINEER)
    batch = db.get(BatchExecution, batch_id)
    if not batch:
        raise NotFoundError("Batch không tồn tại.")
    if batch.ebr_locked:
        raise DomainError("Hồ sơ mẻ (EBR) đã khóa — không ghi yield.")
    if not payload.get("step_key"):
        raise DomainError("Thiếu step_key (nau|len_men|loc|chiet).")
    steps = (batch.recipe_snapshot or {}).get("yield_steps") or []
    meta = next((s for s in steps if s.get("step_key") == payload.get("step_key")), {})
    row = BatchYieldActual(
        yield_id=new_id(), batch_id=batch_id,
        step_key=payload["step_key"], step_no=meta.get("step_no", payload.get("step_no", 0)),
        input_qty=float(payload.get("input_qty", 0.0) or 0.0),
        output_qty=float(payload.get("output_qty", 0.0) or 0.0),
        uom=payload.get("uom", batch.uom), expected_pct=meta.get("expected_pct"),
        note=payload.get("note"), recorded_by=user.username, recorded_at=utcnow())
    db.add(row)
    record_audit(db, entity_type="batch", entity_id=batch_id, action="record_yield",
                 actor=user, after={"step": row.step_key, "in": row.input_qty,
                                    "out": row.output_qty, "pct": step_yield(row.input_qty, row.output_qty)})
    db.commit()
    return yield_report(db, batch_id)


def yield_report(db: Session, batch_id: str) -> dict:
    batch = db.get(BatchExecution, batch_id)
    if not batch:
        raise NotFoundError("Batch không tồn tại.")
    snap_steps = {s["step_key"]: s for s in (batch.recipe_snapshot or {}).get("yield_steps", [])}
    rows = db.execute(select(BatchYieldActual).where(BatchYieldActual.batch_id == batch_id)
                      .order_by(BatchYieldActual.step_no, BatchYieldActual.recorded_at)).scalars().all()
    cum = 1.0
    out, overall_warn = [], False
    for r in rows:
        pct = step_yield(r.input_qty, r.output_qty)
        cum *= (pct / 100.0)
        meta = snap_steps.get(r.step_key, {})
        warn_th = meta.get("warn_pct", meta.get("expected_pct"))
        warn = warn_th is not None and pct < warn_th
        overall_warn = overall_warn or warn
        out.append({"step_key": r.step_key, "label": meta.get("label", r.step_key),
                    "step_no": r.step_no, "input_qty": r.input_qty, "output_qty": r.output_qty,
                    "uom": r.uom, "step_pct": pct, "expected_pct": meta.get("expected_pct"),
                    "warn_pct": warn_th, "cumulative_pct": round(cum * 100.0, 2),
                    "warn": warn, "recorded_by": r.recorded_by})
    overall = round(cum * 100.0, 2) if rows else None
    # Hiệu suất kỳ vọng tổng (tích các expected_pct của các bước có khai báo)
    exp_cum = 1.0
    has_exp = False
    for s in (batch.recipe_snapshot or {}).get("yield_steps", []):
        if s.get("expected_pct") is not None:
            exp_cum *= s["expected_pct"] / 100.0
            has_exp = True
    return {"batch_id": batch_id, "batch_code": batch.batch_code,
            "steps": out, "overall_yield_pct": overall,
            "overall_loss_pct": round(100.0 - overall, 2) if overall is not None else None,
            "expected_overall_pct": round(exp_cum * 100.0, 2) if has_exp else None,
            "warn": overall_warn,
            "plan_steps": (batch.recipe_snapshot or {}).get("yield_steps", [])}
