"""Danh mục dây chuyền (master) — thêm/sửa/ngừng để theo dõi OEE theo line."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import new_id
from ..database import get_db
from ..errors import NotFoundError, PermissionError_
from ..models.lines import ProductionLine
from ..schemas import LineIn
from ..security import User, get_current_user, require_perm

router = APIRouter(prefix="/api/lines", tags=["lines"])


@router.get("")
def list_lines(active_only: bool = False, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    stmt = select(ProductionLine).order_by(ProductionLine.code)
    if active_only:
        stmt = stmt.where(ProductionLine.active == True)  # noqa: E712
    return [{"line_id": l.line_id, "code": l.code, "name": l.name, "area": l.area,
             "ideal_rate_per_min": l.ideal_rate_per_min, "active": l.active}
            for l in db.execute(stmt).scalars().all()]


@router.post("", status_code=201)
def create_line(payload: LineIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "master.manage")
    if db.execute(select(ProductionLine).where(ProductionLine.code == payload.code)).scalar_one_or_none():
        raise PermissionError_(f"Dây chuyền '{payload.code}' đã tồn tại.")
    line = ProductionLine(line_id=new_id(), **payload.model_dump())
    db.add(line)
    record_audit(db, entity_type="line", entity_id=line.line_id, action="create", actor=user,
                 after={"code": line.code, "name": line.name})
    db.commit()
    return {"line_id": line.line_id, "code": line.code}


@router.post("/{line_id}/toggle")
def toggle_line(line_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "master.manage")
    line = db.get(ProductionLine, line_id)
    if not line:
        raise NotFoundError("Dây chuyền không tồn tại.")
    line.active = not line.active
    record_audit(db, entity_type="line", entity_id=line_id, action="toggle", actor=user,
                 after={"active": line.active})
    db.commit()
    return {"line_id": line_id, "active": line.active}
