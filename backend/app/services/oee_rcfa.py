"""RCFA (Root Cause Failure Analysis) + 5 Whys cho sự cố dừng máy (breakdown) — mirror sheet
RCFA/5Whys của file "OPI - CAN L3 (KHS 30K).xlsx". Không dùng permission string riêng — dùng
lại đúng vai trò (Role.OPERATOR/SUPERVISOR/ENGINEER) đã áp cho toàn bộ module OEE/Dừng máy ở
services/downtime.py để khỏi vênh convention trong cùng 1 phân hệ."""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import Role, new_id, utcnow
from ..errors import DomainError, NotFoundError
from ..models.oee_ext import DowntimeEvent, OeeRcfa
from ..security import User, require_role

_RECHECK_WEEKS = 12


def _as_dt(v):
    return datetime.fromisoformat(v) if isinstance(v, str) else v


def _next_rcfa_no(db: Session, year: int) -> str:
    count = db.execute(select(func.count()).select_from(OeeRcfa)
                       .where(OeeRcfa.rcfa_no.like(f"RCFA-{year}-%"))).scalar_one()
    while True:
        count += 1
        code = f"RCFA-{year}-{count:04d}"
        exists = db.execute(select(OeeRcfa.rcfa_id).where(OeeRcfa.rcfa_no == code)).scalar_one_or_none()
        if not exists:
            return code


def create_rcfa(db: Session, payload: dict, user: User) -> OeeRcfa:
    require_role(user, Role.OPERATOR, Role.SUPERVISOR, Role.ENGINEER)
    stop_at = _as_dt(payload.get("stop_at")) or utcnow()
    rec = OeeRcfa(rcfa_id=new_id(), rcfa_no=_next_rcfa_no(db, stop_at.year), line_code=payload["line_code"],
                 machine=payload["machine"], part=payload.get("part"), stop_at=stop_at,
                 duration_min=float(payload.get("duration_min", 0) or 0),
                 failure_function=payload.get("failure_function"), prior_signs=payload.get("prior_signs"),
                 technician=payload.get("technician"), repair_min=payload.get("repair_min"),
                 wait_min=payload.get("wait_min"), description=payload.get("description"),
                 replaced_parts=payload.get("replaced_parts") or [],
                 working_principle=payload.get("working_principle"),
                 failure_mechanism=payload.get("failure_mechanism"), analyst=payload.get("analyst"),
                 factor=payload.get("factor"), five_whys=payload.get("five_whys") or [],
                 category_4m1e=payload.get("category_4m1e"), corrective_action=payload.get("corrective_action"),
                 preventive_action=payload.get("preventive_action"), executor=payload.get("executor"),
                 complete_date=_as_dt(payload.get("complete_date")), checker=payload.get("checker"),
                 recheck_schedule=[{"week_offset": i, "checked": False, "checked_at": None, "note": None}
                                   for i in range(1, _RECHECK_WEEKS + 1)],
                 created_by=user.username, created_at=utcnow())
    db.add(rec)
    db.flush()
    if payload.get("downtime_event_id"):
        ev = db.get(DowntimeEvent, payload["downtime_event_id"])
        if ev:
            ev.rcfa_id = rec.rcfa_id
    record_audit(db, entity_type="oee_rcfa", entity_id=rec.rcfa_id, action="create", actor=user,
                after={"rcfa_no": rec.rcfa_no, "machine": rec.machine})
    db.commit()
    db.refresh(rec)
    return rec


_UPDATABLE = ("machine", "part", "stop_at", "duration_min", "failure_function", "prior_signs",
             "technician", "repair_min", "wait_min", "description", "replaced_parts",
             "working_principle", "failure_mechanism", "analyst", "factor", "five_whys",
             "category_4m1e", "corrective_action", "preventive_action", "executor",
             "complete_date", "checker")


def update_rcfa(db: Session, rcfa_id: str, payload: dict, user: User) -> OeeRcfa:
    require_role(user, Role.OPERATOR, Role.SUPERVISOR, Role.ENGINEER)
    rec = db.get(OeeRcfa, rcfa_id)
    if not rec:
        raise NotFoundError("RCFA không tồn tại.")
    for field in _UPDATABLE:
        if field in payload and payload[field] is not None:
            value = payload[field]
            if field in ("stop_at", "complete_date"):
                value = _as_dt(value)
            setattr(rec, field, value)
    db.commit()
    db.refresh(rec)
    return rec


def update_recheck(db: Session, rcfa_id: str, week_offset: int, checked: bool, note: str, user: User) -> OeeRcfa:
    require_role(user, Role.OPERATOR, Role.SUPERVISOR, Role.ENGINEER)
    rec = db.get(OeeRcfa, rcfa_id)
    if not rec:
        raise NotFoundError("RCFA không tồn tại.")
    if not (1 <= week_offset <= _RECHECK_WEEKS):
        raise DomainError(f"Tuần kiểm tra lặp lại phải trong khoảng 1-{_RECHECK_WEEKS}.")
    # Dựng list/dict HOÀN TOÀN MỚI (không dùng list(x)/dict(x) nông) — nếu tái dùng chung dict
    # object với giá trị đang lưu, sửa tại chỗ sẽ làm "bản cũ" mà SQLAlchemy dùng so sánh cũng
    # đổi theo (dict là mutable, list(x) chỉ copy nông), khiến is_modified() thấy cũ==mới và
    # ÂM THẦM bỏ qua cột này khi UPDATE — đã tự bắt được lỗi này khi viết test recheck.
    schedule = []
    for item in (rec.recheck_schedule or []):
        new_item = dict(item)
        if new_item.get("week_offset") == week_offset:
            new_item["checked"] = checked
            new_item["checked_at"] = utcnow().isoformat() if checked else None
            new_item["note"] = note
        schedule.append(new_item)
    rec.recheck_schedule = schedule
    db.commit()
    db.refresh(rec)
    return rec


def get_rcfa(db: Session, rcfa_id: str) -> OeeRcfa:
    rec = db.get(OeeRcfa, rcfa_id)
    if not rec:
        raise NotFoundError("RCFA không tồn tại.")
    return rec


def list_rcfa(db: Session, line_code: str = None) -> list:
    stmt = select(OeeRcfa).order_by(OeeRcfa.stop_at.desc())
    if line_code:
        stmt = stmt.where(OeeRcfa.line_code == line_code)
    rows = db.execute(stmt).scalars().all()
    return [{"rcfa_id": r.rcfa_id, "rcfa_no": r.rcfa_no, "line_code": r.line_code, "machine": r.machine,
             "part": r.part, "stop_at": r.stop_at, "duration_min": r.duration_min,
             "description": r.description, "corrective_action": r.corrective_action,
             "preventive_action": r.preventive_action, "complete_date": r.complete_date,
             "checker": r.checker, "recheck_done": sum(1 for w in (r.recheck_schedule or []) if w.get("checked")),
             "recheck_total": len(r.recheck_schedule or [])} for r in rows]
