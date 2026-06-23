"""Quality hardcore (tài liệu §7.5): SPC control chart + Western Electric rules,
CAPA workflow, COA (Certificate of Analysis), LIMS-lite sample.

SPC dùng biểu đồ cá thể I-MR: sigma ước lượng = MR-bar / 1.128 (chuẩn công nghiệp),
fallback độ lệch chuẩn mẫu khi không đủ điểm. Cp/Cpk tính theo USL/LSL của QCParameter.
"""

from statistics import mean, pstdev

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import Role, new_id, utcnow
from ..errors import DomainError, NotFoundError
from ..models.batches import BatchExecution
from ..models.quality import Deviation, QualityResult
from ..models.quality_ext import CAPA, QCParameter, Sample
from ..security import User, require_perm, require_role

# Workflow CAPA
CAPA_TRANSITIONS = {
    "open": {"investigation"},
    "investigation": {"action"},
    "action": {"verification"},
    "verification": {"closed"},
    "closed": set(),
}

_D2 = 1.128  # hệ số d2 cho moving range n=2 (biểu đồ I-MR)


# ============================== SPC ==============================

def _sigma_imr(values: list) -> float:
    """Ước lượng sigma theo I-MR (MR-bar/d2). Fallback stdev tổng thể."""
    if len(values) < 2:
        return 0.0
    mrs = [abs(values[i] - values[i - 1]) for i in range(1, len(values))]
    mr_bar = mean(mrs) if mrs else 0.0
    sigma = mr_bar / _D2 if mr_bar else 0.0
    if sigma <= 0:
        sigma = pstdev(values) if len(values) > 1 else 0.0
    return sigma


def _western_electric(values: list, cl: float, sigma: float) -> list:
    """Trả về list rule vi phạm cho từng điểm (mỗi điểm: list mã rule)."""
    n = len(values)
    flags = [[] for _ in range(n)]
    if sigma <= 0:
        return flags
    s1u, s1l = cl + sigma, cl - sigma
    s2u, s2l = cl + 2 * sigma, cl - 2 * sigma
    s3u, s3l = cl + 3 * sigma, cl - 3 * sigma
    for i, v in enumerate(values):
        # Rule 1: 1 điểm ngoài 3σ
        if v > s3u or v < s3l:
            flags[i].append("R1: ngoài 3σ")
        # Rule 2: 2/3 điểm liên tiếp ngoài 2σ cùng phía
        if i >= 2:
            w = values[i - 2:i + 1]
            if sum(1 for x in w if x > s2u) >= 2:
                flags[i].append("R2: 2/3 ngoài 2σ (trên)")
            if sum(1 for x in w if x < s2l) >= 2:
                flags[i].append("R2: 2/3 ngoài 2σ (dưới)")
        # Rule 3: 4/5 điểm liên tiếp ngoài 1σ cùng phía
        if i >= 4:
            w = values[i - 4:i + 1]
            if sum(1 for x in w if x > s1u) >= 4:
                flags[i].append("R3: 4/5 ngoài 1σ (trên)")
            if sum(1 for x in w if x < s1l) >= 4:
                flags[i].append("R3: 4/5 ngoài 1σ (dưới)")
        # Rule 4: 8 điểm liên tiếp cùng phía mean
        if i >= 7:
            w = values[i - 7:i + 1]
            if all(x > cl for x in w):
                flags[i].append("R4: 8 điểm trên CL")
            if all(x < cl for x in w):
                flags[i].append("R4: 8 điểm dưới CL")
    return flags


def spc_chart(db: Session, parameter: str, scope_type: str = None) -> dict:
    """Biểu đồ kiểm soát SPC cho một chỉ tiêu (theo tên parameter).

    Lấy chuỗi giá trị QualityResult (status != pending, có value) theo thời gian."""
    stmt = select(QualityResult).where(
        QualityResult.parameter == parameter, QualityResult.value.isnot(None)
    ).order_by(QualityResult.recorded_at)
    if scope_type:
        stmt = stmt.where(QualityResult.scope_type == scope_type)
    rows = db.execute(stmt).scalars().all()
    values = [r.value for r in rows]
    pts = []
    cl = mean(values) if values else 0.0
    sigma = _sigma_imr(values)
    flags = _western_electric(values, cl, sigma)
    for i, r in enumerate(rows):
        pts.append({"ts": r.recorded_at.isoformat() if r.recorded_at else None,
                    "value": r.value, "by": r.recorded_by, "status": r.status,
                    "violations": flags[i]})
    ucl, lcl = cl + 3 * sigma, cl - 3 * sigma
    # Capability từ QCParameter (nếu định nghĩa)
    spec = db.execute(select(QCParameter).where(QCParameter.name == parameter)).scalar_one_or_none()
    cp = cpk = usl = lsl = None
    if spec and sigma > 0 and spec.usl is not None and spec.lsl is not None:
        usl, lsl = spec.usl, spec.lsl
        cp = round((usl - lsl) / (6 * sigma), 3)
        cpk = round(min(usl - cl, cl - lsl) / (3 * sigma), 3)
    out_of_control = sum(1 for f in flags if f)
    return {"parameter": parameter, "n": len(values),
            "mean": round(cl, 4), "sigma": round(sigma, 4),
            "ucl": round(ucl, 4), "lcl": round(lcl, 4),
            "usl": usl, "lsl": lsl, "target": spec.target if spec else None,
            "unit": spec.unit if spec else (rows[0].unit if rows else None),
            "cp": cp, "cpk": cpk, "out_of_control": out_of_control,
            "in_control": out_of_control == 0, "points": pts}


def list_qc_parameters(db: Session) -> list:
    rows = db.execute(select(QCParameter).where(QCParameter.active == True)  # noqa: E712
                      .order_by(QCParameter.code)).scalars().all()
    return [{"code": p.code, "name": p.name, "unit": p.unit, "target": p.target,
             "usl": p.usl, "lsl": p.lsl, "stage": p.stage} for p in rows]


# ============================== CAPA ==============================

def open_capa(db: Session, payload: dict, user: User) -> CAPA:
    require_perm(user, "quality.deviation")
    if payload.get("deviation_id"):
        if not db.get(Deviation, payload["deviation_id"]):
            raise NotFoundError("Deviation liên kết không tồn tại.")
    capa = CAPA(capa_id=new_id(),
                capa_code=f"CAPA-{utcnow():%Y%m%d}-{new_id()[:5].upper()}",
                deviation_id=payload.get("deviation_id"),
                title=payload["title"], capa_type=payload.get("capa_type", "corrective"),
                severity=payload.get("severity", "minor"), state="open",
                root_cause=payload.get("root_cause"), action_plan=payload.get("action_plan"),
                owner=payload.get("owner") or user.username, due_date=payload.get("due_date"),
                opened_by=user.username, opened_at=utcnow())
    db.add(capa)
    record_audit(db, entity_type="capa", entity_id=capa.capa_id, action="open", actor=user,
                 after={"code": capa.capa_code, "title": capa.title})
    db.commit()
    db.refresh(capa)
    return capa


def transition_capa(db: Session, capa_id: str, target: str, user: User, payload: dict) -> CAPA:
    capa = db.get(CAPA, capa_id)
    if not capa:
        raise NotFoundError("CAPA không tồn tại.")
    if target not in CAPA_TRANSITIONS.get(capa.state, set()):
        raise DomainError(f"Không thể chuyển CAPA từ {capa.state} sang {target}.")
    payload = payload or {}
    if target in ("verification", "closed"):
        require_role(user, Role.QA, Role.SUPERVISOR)
    if payload.get("root_cause"):
        capa.root_cause = payload["root_cause"]
    if payload.get("action_plan"):
        capa.action_plan = payload["action_plan"]
    if payload.get("effectiveness"):
        capa.effectiveness = payload["effectiveness"]
    if target == "closed":
        if not (capa.root_cause and capa.action_plan):
            raise DomainError("Phải có root cause + action plan trước khi đóng CAPA.")
        capa.closed_by = user.username
        capa.closed_at = utcnow()
    before = {"state": capa.state}
    capa.state = target
    record_audit(db, entity_type="capa", entity_id=capa.capa_id, action=f"transition:{target}",
                 actor=user, before=before, after={"state": capa.state})
    db.commit()
    db.refresh(capa)
    return capa


def list_capa(db: Session) -> list:
    rows = db.execute(select(CAPA).order_by(CAPA.opened_at.desc())).scalars().all()
    return [{"capa_code": c.capa_code, "title": c.title, "capa_type": c.capa_type,
             "severity": c.severity, "state": c.state, "deviation_id": c.deviation_id,
             "root_cause": c.root_cause, "action_plan": c.action_plan,
             "effectiveness": c.effectiveness, "owner": c.owner, "due_date": c.due_date,
             "opened_by": c.opened_by, "closed_by": c.closed_by,
             "opened_at": c.opened_at, "closed_at": c.closed_at, "capa_id": c.capa_id} for c in rows]


# ============================== COA ==============================

def coa(db: Session, batch_id: str) -> dict:
    """Certificate of Analysis: tổng hợp QC + spec + verdict cho một mẻ."""
    batch = db.get(BatchExecution, batch_id)
    if not batch:
        raise NotFoundError("Batch không tồn tại.")
    results = db.execute(select(QualityResult).where(
        QualityResult.scope_type == "batch", QualityResult.scope_id == batch_id
    ).order_by(QualityResult.recorded_at)).scalars().all()
    checks = (batch.recipe_snapshot or {}).get("quality_checks", [])
    lines, has_fail, has_pending = [], False, False
    for r in results:
        if r.status == "fail":
            has_fail = True
        elif r.status == "pending":
            has_pending = True
        lines.append({"parameter": r.parameter, "value": r.value, "unit": r.unit,
                      "lower": r.lower_limit, "upper": r.upper_limit, "method": r.method,
                      "verdict": r.status, "by": r.recorded_by,
                      "time": r.recorded_at.isoformat() if r.recorded_at else None})
    # Kiểm tra checkpoint bắt buộc còn thiếu
    tested = {r.parameter for r in results}
    missing = [c.get("parameter") for c in checks if c.get("mandatory") and c.get("parameter") not in tested]
    # Verdict phản ánh ĐÚNG kết quả QC (không bị che bởi trạng thái hành chính của mẻ).
    if has_fail:
        verdict = "FAIL"
    elif missing or has_pending:
        verdict = "PENDING"   # chưa đủ chỉ tiêu / còn chờ kết quả
    elif batch.quality_status == "released":
        verdict = "PASS"
    else:
        verdict = "PENDING"   # các chỉ tiêu đạt nhưng mẻ chưa release
    return {"batch_code": batch.batch_code, "product_id": batch.product_id,
            "planned_qty": batch.planned_qty, "actual_qty": batch.actual_qty, "uom": batch.uom,
            "quality_status": batch.quality_status, "recipe": (batch.recipe_snapshot or {}).get("recipe_id"),
            "version_no": (batch.recipe_snapshot or {}).get("version_no"),
            "results": lines, "missing_mandatory": missing,
            "overall_verdict": verdict, "issued_at": utcnow().isoformat()}


# ============================== LIMS-lite ==============================

def register_sample(db: Session, payload: dict, user: User) -> Sample:
    require_role(user, Role.QA, Role.OPERATOR, Role.SUPERVISOR)
    s = Sample(sample_id=new_id(),
               sample_code=payload.get("sample_code") or f"SMP-{utcnow():%Y%m%d}-{new_id()[:5].upper()}",
               scope_type=payload.get("scope_type", "batch"), scope_id=payload["scope_id"],
               stage=payload.get("stage"), status="registered",
               test_set=payload.get("test_set"), registered_by=user.username,
               registered_at=utcnow(), note=payload.get("note"))
    db.add(s)
    record_audit(db, entity_type="sample", entity_id=s.sample_id, action="register", actor=user,
                 after={"code": s.sample_code, "scope": f"{s.scope_type}:{s.scope_id}"})
    db.commit()
    db.refresh(s)
    return s


def transition_sample(db: Session, sample_id: str, target: str, user: User) -> Sample:
    s = db.get(Sample, sample_id)
    if not s:
        raise NotFoundError("Mẫu không tồn tại.")
    order = {"registered": 0, "in_test": 1, "completed": 2}
    if target not in order or order[target] <= order.get(s.status, -1):
        raise DomainError(f"Không thể chuyển mẫu từ {s.status} sang {target}.")
    s.status = target
    if target == "completed":
        s.completed_at = utcnow()
    record_audit(db, entity_type="sample", entity_id=s.sample_id, action=f"sample:{target}",
                 actor=user, after={"status": target})
    db.commit()
    db.refresh(s)
    return s


def list_samples(db: Session, scope_id: str = None) -> list:
    stmt = select(Sample).order_by(Sample.registered_at.desc())
    if scope_id:
        stmt = stmt.where(Sample.scope_id == scope_id)
    rows = db.execute(stmt).scalars().all()
    out = []
    for s in rows:
        results = db.execute(select(QualityResult).where(
            QualityResult.sample_id == s.sample_code)).scalars().all()
        out.append({"sample_code": s.sample_code, "scope_type": s.scope_type, "scope_id": s.scope_id,
                    "stage": s.stage, "status": s.status, "test_set": s.test_set,
                    "registered_by": s.registered_by, "registered_at": s.registered_at,
                    "completed_at": s.completed_at, "sample_id": s.sample_id,
                    "result_count": len(results)})
    return out
