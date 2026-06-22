"""Audit trail (chỉ đọc — append-only, không có API sửa/xóa)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import verify_chain
from ..database import get_db
from ..models.audit import AuditLog
from ..schemas import AuditOut

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("/verify-chain")
def verify(db: Session = Depends(get_db)):
    """Kiểm tra toàn vẹn chuỗi hash audit (tamper-evident)."""
    return verify_chain(db)


@router.get("", response_model=list[AuditOut])
def list_audit(entity_id: str = Query(default=None), entity_type: str = Query(default=None),
               limit: int = Query(default=200, le=1000), db: Session = Depends(get_db)):
    stmt = select(AuditLog)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    stmt = stmt.order_by(AuditLog.seq.desc()).limit(limit)
    return db.execute(stmt).scalars().all()
