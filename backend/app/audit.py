"""Ghi audit append-only (tài liệu §10.3). Gọi trong cùng transaction với
thay đổi nghiệp vụ để bản ghi audit và dữ liệu nhất quán."""

import hashlib
import json
import threading
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .common import new_id, utcnow
from .models.audit import AuditLog
from .security import User

# Tuần tự hoá ghi audit để bảo vệ tính toàn vẹn chuỗi hash (seq + prev_hash).
# - Postgres: pg_advisory_xact_lock (giữ tới hết transaction) — chuẩn cho production.
# - SQL Server: sp_getapplock @LockOwner='Transaction' (tự nhả khi commit/rollback).
# - SQLite/đơn tiến trình: khoá Python serialize giữa các thread của uvicorn.
_AUDIT_LOCK = threading.Lock()
_PG_ADVISORY_KEY = 920145         # hằng tuỳ ý, riêng cho audit chain
_LOCK_RESOURCE = "mes_audit_chain"  # tên resource cho sp_getapplock (MSSQL)


def _acquire_db_lock(db: Session) -> None:
    from .database import engine
    name = engine.dialect.name
    if name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _PG_ADVISORY_KEY})
    elif name == "mssql":
        # Khoá ứng dụng phạm vi transaction trên SQL Server — tuần tự hoá ghi audit
        # an toàn khi nhiều worker/replica cùng ghi.
        db.execute(
            text("EXEC sp_getapplock @Resource=:r, @LockMode='Exclusive', "
                 "@LockOwner='Transaction', @LockTimeout=10000"),
            {"r": _LOCK_RESOURCE},
        )


def _ts_str(ts) -> str:
    # Chuẩn hóa về UTC naive để hash ổn định giữa lúc ghi (tz-aware) và lúc đọc (SQLite naive).
    return (ts.replace(tzinfo=None) if ts.tzinfo else ts).isoformat()


def _entry_hash(prev_hash: str, fields: dict) -> str:
    payload = (prev_hash or "") + "|" + json.dumps(fields, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def record_audit(
    db: Session,
    *,
    entity_type: str,
    entity_id: str,
    action: str,
    actor: User,
    before: Optional[dict] = None,
    after: Optional[dict] = None,
    reason: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> AuditLog:
    # Khoá DB ở mức transaction (Postgres) để các giao dịch ghi audit không chen seq.
    _acquire_db_lock(db)
    with _AUDIT_LOCK:
        # Lấy bản ghi cuối theo seq (autoflush khiến bản ghi pending cùng transaction hiện ra).
        last = db.execute(select(AuditLog).order_by(AuditLog.seq.desc()).limit(1)).scalar_one_or_none()
        next_seq = (last.seq + 1) if last else 1
        prev_hash = last.entry_hash if last else ""
        ts = utcnow()
        fields = {"seq": next_seq, "entity_type": entity_type, "entity_id": entity_id,
                  "action": action, "actor": actor.username, "actor_role": actor.role,
                  "reason": reason, "before": before, "after": after,
                  "correlation_id": correlation_id, "ts": _ts_str(ts)}
        entry = AuditLog(
            audit_id=new_id(), seq=next_seq, entity_type=entity_type, entity_id=entity_id,
            action=action, actor=actor.username, actor_role=actor.role, reason=reason,
            before=before, after=after, correlation_id=correlation_id, ts=ts,
            prev_hash=prev_hash or None, entry_hash=_entry_hash(prev_hash, fields),
        )
        db.add(entry)
        db.flush()   # phát INSERT trong khoá → seq trùng (nếu có) lỗi ngay tại đây
    return entry


def verify_chain(db: Session) -> dict:
    """Kiểm tra toàn vẹn chuỗi audit (tamper-evident)."""
    rows = db.execute(select(AuditLog).order_by(AuditLog.seq)).scalars().all()
    prev = ""
    for r in rows:
        fields = {"seq": r.seq, "entity_type": r.entity_type, "entity_id": r.entity_id,
                  "action": r.action, "actor": r.actor, "actor_role": r.actor_role,
                  "reason": r.reason, "before": r.before, "after": r.after,
                  "correlation_id": r.correlation_id, "ts": _ts_str(r.ts)}
        expected = _entry_hash(prev, fields)
        if r.entry_hash != expected or (r.prev_hash or "") != (prev or ""):
            return {"intact": False, "broken_at_seq": r.seq, "count": len(rows)}
        prev = r.entry_hash
    return {"intact": True, "count": len(rows)}
