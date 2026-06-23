"""EBR — Hồ sơ mẻ điện tử (tài liệu §7.6).

Lắp ráp dossier step-by-step từ dữ liệu sẵn có (audit, genealogy, QC, deviation,
readings, hóa chất, BOM). E-signature yêu cầu re-authentication; khóa hồ sơ tạo
snapshot bất biến có content_hash. Sau khóa, mẻ không cho sửa (chỉ amendment).
"""

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import new_id, utcnow
from ..errors import DomainError, PermissionError_
from ..models.audit import AuditLog
from ..models.auth import User as UserModel
from ..models.batches import BatchExecution
from ..models.orders import ProductionOrder
from ..models.process import ChemicalUsage
from ..models.quality import Deviation, QualityResult
from ..models.signature import EBRSnapshot, Signature
from ..security import User, require_perm, verify_password
from . import bom, genealogy


def assemble(db: Session, batch: BatchExecution) -> dict:
    snap = batch.recipe_snapshot or {}
    order = db.get(ProductionOrder, batch.order_id)

    # Các bước thực thi (chronological) từ audit của mẻ + kết quả QC.
    steps = []
    for a in db.execute(select(AuditLog).where(AuditLog.entity_id == batch.batch_id)
                        .order_by(AuditLog.seq)).scalars().all():
        if a.action.startswith("ebr_"):   # ký/khóa là meta hồ sơ, không tính vào lõi hash
            continue
        steps.append({"seq": a.seq, "time": (a.ts.replace(tzinfo=None) if a.ts.tzinfo else a.ts).isoformat(),
                      "action": a.action, "by": a.actor, "role": a.actor_role, "reason": a.reason,
                      "detail": a.after})
    qc = [{"parameter": r.parameter, "value": r.value, "unit": r.unit, "status": r.status,
           "lower": r.lower_limit, "upper": r.upper_limit, "by": r.recorded_by,
           "time": r.recorded_at.isoformat()}
          for r in db.execute(select(QualityResult).where(
              QualityResult.scope_type == "batch", QualityResult.scope_id == batch.batch_id)
              .order_by(QualityResult.recorded_at)).scalars().all()]
    deviations = [{"code": d.deviation_code, "severity": d.severity, "reason": d.reason,
                   "state": d.state, "by": d.opened_by, "disposition": d.disposition}
                  for d in db.execute(select(Deviation).where(
                      Deviation.scope_type == "batch", Deviation.scope_id == batch.batch_id)).scalars().all()]
    chemicals = [{"stage": c.stage, "chemical": c.chemical, "quantity": c.quantity,
                  "uom": c.uom, "time": c.ts.isoformat()}
                 for c in db.execute(select(ChemicalUsage).where(
                     ChemicalUsage.batch_id == batch.batch_id)).scalars().all()]
    materials = bom.compare_batch(db, batch)
    genealogy_tree = genealogy.trace_backward(db, "batch", batch.batch_id)

    # Phần lõi dùng để hash (bất biến) — không gồm chữ ký/thời điểm sinh.
    core = {
        "batch_code": batch.batch_code,
        "order_code": order.order_code if order else None,
        "work_order_id": batch.work_order_id,
        "product_id": batch.product_id,
        "recipe": {"recipe_id": snap.get("recipe_id"), "version_no": snap.get("version_no"),
                   "base_qty": snap.get("base_qty"), "base_uom": snap.get("base_uom")},
        "planned_qty": batch.planned_qty, "actual_qty": batch.actual_qty, "uom": batch.uom,
        "state": batch.state, "quality_status": batch.quality_status,
        "start_at": batch.start_at.isoformat() if batch.start_at else None,
        "end_at": batch.end_at.isoformat() if batch.end_at else None,
        "steps": steps, "quality": qc, "deviations": deviations, "chemicals": chemicals,
        "materials": materials,
    }
    signatures = [{"meaning": s.meaning, "by": s.signed_by, "role": s.role, "reason": s.reason,
                   "hash": s.content_hash, "time": s.signed_at.isoformat()}
                  for s in db.execute(select(Signature).where(
                      Signature.scope_type == "ebr", Signature.scope_id == batch.batch_id)
                      .order_by(Signature.signed_at)).scalars().all()]
    snapshot = db.execute(select(EBRSnapshot).where(
        EBRSnapshot.batch_id == batch.batch_id).order_by(EBRSnapshot.snapshot_version.desc())
    ).scalars().first()
    return {
        "core": core, "genealogy": genealogy_tree, "signatures": signatures,
        "locked": bool(batch.ebr_locked),
        "snapshot": ({"version": snapshot.snapshot_version, "hash": snapshot.content_hash,
                      "locked_by": snapshot.locked_by, "locked_at": snapshot.locked_at.isoformat()}
                     if snapshot else None),
        "current_hash": _hash(core),
        "generated_at": utcnow().isoformat(),
    }


def _hash(core: dict) -> str:
    return hashlib.sha256(json.dumps(core, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _reauth(db: Session, user: User, password: str) -> UserModel:
    u = db.execute(select(UserModel).where(UserModel.username == user.username)).scalar_one_or_none()
    if not u or not verify_password(password or "", u.password_hash):
        raise PermissionError_("Xác thực lại thất bại: mật khẩu không đúng (yêu cầu cho chữ ký điện tử).")
    return u


def sign(db: Session, batch: BatchExecution, user: User, password: str, meaning: str, reason: str) -> dict:
    require_perm(user, "ebr.sign")
    _reauth(db, user, password)
    if not meaning:
        raise DomainError("Phải nêu ý nghĩa chữ ký.")
    core_hash = _hash(assemble(db, batch)["core"])
    sig = Signature(sig_id=new_id(), scope_type="ebr", scope_id=batch.batch_id, meaning=meaning,
                    signed_by=user.username, role=user.role, reason=reason, content_hash=core_hash,
                    signed_at=utcnow())
    db.add(sig)
    record_audit(db, entity_type="batch", entity_id=batch.batch_id, action="ebr_sign",
                 actor=user, after={"meaning": meaning, "hash": core_hash[:12]}, reason=reason)
    db.commit()
    return {"signed": True, "meaning": meaning, "hash": core_hash}


def lock(db: Session, batch: BatchExecution, user: User, password: str, reason: str) -> dict:
    require_perm(user, "ebr.approve")
    _reauth(db, user, password)
    if batch.ebr_locked:
        raise DomainError("Hồ sơ mẻ đã được khóa trước đó.")
    dossier = assemble(db, batch)
    core = dossier["core"]
    core_hash = _hash(core)
    last = db.execute(select(EBRSnapshot).where(EBRSnapshot.batch_id == batch.batch_id)
                      .order_by(EBRSnapshot.snapshot_version.desc())).scalars().first()
    ver = (last.snapshot_version + 1) if last else 1
    db.add(EBRSnapshot(snap_id=new_id(), batch_id=batch.batch_id, snapshot_version=ver,
                       content_hash=core_hash, content=core, locked_by=user.username, locked_at=utcnow()))
    batch.ebr_locked = True
    record_audit(db, entity_type="batch", entity_id=batch.batch_id, action="ebr_lock",
                 actor=user, after={"version": ver, "hash": core_hash[:12]}, reason=reason)
    db.commit()
    return {"locked": True, "snapshot_version": ver, "hash": core_hash}
