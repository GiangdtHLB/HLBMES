"""Thực thi thủ tục ISA-88: hợp nhất định nghĩa procedure (snapshot) với log chạy
phase (BatchPhaseRun) + state machine theo ISA-88.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import PHASE_TRANSITIONS, PhaseState, Role, new_id, utcnow
from ..errors import DomainError, NotFoundError
from ..models.batches import BatchExecution
from ..models.isa88 import BatchPhaseRun
from ..models.recipes import RecipeVersion
from ..security import User, require_role


def _get_batch(db: Session, batch_id: str) -> BatchExecution:
    b = db.get(BatchExecution, batch_id)
    if not b:
        raise NotFoundError("Batch không tồn tại.")
    return b


def recipe_procedure(db: Session, version_id: str) -> dict:
    rv = db.get(RecipeVersion, version_id)
    if not rv:
        raise NotFoundError("Recipe version không tồn tại.")
    return {"version_id": rv.version_id, "version_no": rv.version_no,
            "procedure": rv.procedure or []}


def _find_phase(procedure: list, up: str, op: str, phase: str):
    for u in procedure:
        if u.get("name") != up:
            continue
        for o in u.get("operations", []):
            if o.get("name") != op:
                continue
            for p in o.get("phases", []):
                if p.get("name") == phase:
                    return u, o, p
    return None, None, None


def status(db: Session, batch_id: str) -> dict:
    """Cây thủ tục (từ snapshot) + trạng thái phase (từ run gần nhất)."""
    batch = _get_batch(db, batch_id)
    proc = (batch.recipe_snapshot or {}).get("procedure") or []
    runs = db.execute(select(BatchPhaseRun).where(BatchPhaseRun.batch_id == batch_id)
                      .order_by(BatchPhaseRun.started_at)).scalars().all()
    latest = {}
    for r in runs:
        latest[(r.up_name, r.op_name, r.phase_name)] = r
    ups = []
    done = total = 0
    for u in proc:
        ops = []
        for o in u.get("operations", []):
            phases = []
            for p in o.get("phases", []):
                total += 1
                run = latest.get((u["name"], o["name"], p["name"]))
                st = run.state if run else PhaseState.IDLE.value
                if st == PhaseState.COMPLETE.value:
                    done += 1
                phases.append({"phase": p["name"], "params": p.get("params", []),
                               "duration_min": p.get("duration_min"),
                               "state": st, "run_id": run.run_id if run else None,
                               "operator": run.operator if run else None,
                               "started_at": run.started_at if run else None,
                               "ended_at": run.ended_at if run else None})
            ops.append({"operation": o["name"], "phases": phases})
        ups.append({"unit_procedure": u["name"], "unit_class": u.get("unit_class"), "operations": ops})
    pct = round(done / total * 100, 1) if total else 0.0
    return {"batch_id": batch_id, "batch_code": batch.batch_code,
            "completion_pct": pct, "phases_total": total, "phases_done": done,
            "unit_procedures": ups}


def start_phase(db: Session, batch_id: str, up: str, op: str, phase: str, user: User) -> dict:
    require_role(user, Role.OPERATOR, Role.SUPERVISOR, Role.ENGINEER)
    batch = _get_batch(db, batch_id)
    if batch.ebr_locked:
        raise DomainError("Hồ sơ mẻ (EBR) đã khóa — không chạy phase.")
    proc = (batch.recipe_snapshot or {}).get("procedure") or []
    u, o, p = _find_phase(proc, up, op, phase)
    if not p:
        raise DomainError(f"Phase không có trong thủ tục: {up}/{op}/{phase}.")
    # Không cho chạy lại phase đã complete; không cho 2 run active cùng phase.
    existing = db.execute(select(BatchPhaseRun).where(
        BatchPhaseRun.batch_id == batch_id, BatchPhaseRun.up_name == up,
        BatchPhaseRun.op_name == op, BatchPhaseRun.phase_name == phase
    ).order_by(BatchPhaseRun.started_at.desc())).scalars().first()
    if existing and existing.state in (PhaseState.RUNNING.value, PhaseState.HELD.value):
        raise DomainError("Phase đang chạy/giữ — không thể start lại.")
    if existing and existing.state == PhaseState.COMPLETE.value:
        raise DomainError("Phase đã hoàn thành.")
    seq = (db.execute(select(BatchPhaseRun).where(BatchPhaseRun.batch_id == batch_id)).scalars().all())
    run = BatchPhaseRun(run_id=new_id(), batch_id=batch_id, seq=len(seq) + 1,
                        unit_class=u.get("unit_class"), up_name=up, op_name=op, phase_name=phase,
                        state=PhaseState.RUNNING.value, params={"params": p.get("params", []),
                        "duration_min": p.get("duration_min")},
                        operator=user.username, started_at=utcnow())
    db.add(run)
    record_audit(db, entity_type="batch", entity_id=batch_id, action="isa88:start_phase",
                 actor=user, after={"up": up, "op": op, "phase": phase})
    db.commit()
    db.refresh(run)
    return {"run_id": run.run_id, "state": run.state}


def transition_phase(db: Session, run_id: str, target: str, user: User, values: dict = None) -> dict:
    require_role(user, Role.OPERATOR, Role.SUPERVISOR, Role.ENGINEER)
    run = db.get(BatchPhaseRun, run_id)
    if not run:
        raise NotFoundError("Phase run không tồn tại.")
    try:
        tgt = PhaseState(target)
    except ValueError:
        raise DomainError(f"Trạng thái phase không hợp lệ: {target}")
    cur = PhaseState(run.state)
    if tgt not in PHASE_TRANSITIONS[cur]:
        raise DomainError(f"Không thể chuyển phase {cur.value} → {target}.")
    if values:
        run.values = {**(run.values or {}), **values}
    run.state = tgt.value
    if tgt in (PhaseState.COMPLETE, PhaseState.ABORTED):
        run.ended_at = utcnow()
    record_audit(db, entity_type="batch", entity_id=run.batch_id,
                 action=f"isa88:phase:{target}", actor=user,
                 after={"phase": f"{run.up_name}/{run.op_name}/{run.phase_name}"})
    db.commit()
    db.refresh(run)
    return {"run_id": run.run_id, "state": run.state}
