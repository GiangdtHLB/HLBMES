"""CIP (vệ sinh thiết bị) — danh mục loại biểu mẫu/thiết bị, khai báo + nghiệm thu 1 lần vệ
sinh, và gắn TAY với mẻ/lô sản xuất (không tự động suy đoán — xem models/cip.py)."""

from datetime import datetime

from sqlalchemy import func, select, true
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import new_id, utcnow
from ..errors import DomainError, NotFoundError
from ..models.brewing import BottleRecord, BrewBatch, FermentRecord, FilterRecord
from ..models.cip import CipEquipment, CipFormType, CipLink, CipRecord
from ..models.lines import ProductionLine
from ..security import User, require_perm

# Khu vực áp dụng cho từng loại scope (mẻ nấu/lô lên men/mẻ lọc/mẻ chiết) — cùng vocabulary
# scope_type đã dùng cho Hold/Deviation (xem services/quality.py).
_AREA_BY_SCOPE = {"brew_batch": "nau", "ferment": "len_men", "filter": "loc", "bottle": "chiet"}


# ---- Danh mục loại biểu mẫu ----

def create_form_type(db: Session, payload: dict, user: User) -> CipFormType:
    require_perm(user, "master.manage")
    if db.execute(select(CipFormType).where(CipFormType.code == payload["code"])).scalar_one_or_none():
        raise DomainError(f"Mã biểu mẫu '{payload['code']}' đã tồn tại.")
    ft = CipFormType(form_type_id=new_id(), **payload)
    db.add(ft)
    db.commit()
    db.refresh(ft)
    return ft


def list_form_types(db: Session, area: str = None, active_only: bool = True) -> list:
    stmt = select(CipFormType)
    if active_only:
        stmt = stmt.where(CipFormType.active == true())
    if area:
        stmt = stmt.where(CipFormType.area == area)
    return db.execute(stmt.order_by(CipFormType.code)).scalars().all()


def update_form_type(db: Session, form_type_id: str, payload: dict, user: User) -> CipFormType:
    require_perm(user, "master.manage")
    ft = db.get(CipFormType, form_type_id)
    if not ft:
        raise NotFoundError("Loại biểu mẫu CIP không tồn tại.")
    for k, v in payload.items():
        if v is not None:
            setattr(ft, k, v)
    db.commit()
    db.refresh(ft)
    return ft


def delete_form_type(db: Session, form_type_id: str, user: User) -> None:
    require_perm(user, "master.manage")
    ft = db.get(CipFormType, form_type_id)
    if not ft:
        raise NotFoundError("Loại biểu mẫu CIP không tồn tại.")
    n = db.execute(select(func.count()).select_from(CipRecord)
                   .where(CipRecord.form_type_id == form_type_id)).scalar_one()
    if n:
        raise DomainError(f"Không thể xóa loại biểu mẫu '{ft.code}' — đang được dùng bởi {n} bản ghi CIP.")
    record_audit(db, entity_type="cip_form_type", entity_id=ft.form_type_id, action="delete",
                actor=user, before={"code": ft.code, "name": ft.name})
    db.delete(ft)
    db.commit()


# ---- Danh mục thiết bị ----

def create_equipment(db: Session, payload: dict, user: User) -> CipEquipment:
    require_perm(user, "master.manage")
    if db.execute(select(CipEquipment).where(CipEquipment.code == payload["code"])).scalar_one_or_none():
        raise DomainError(f"Mã thiết bị '{payload['code']}' đã tồn tại.")
    eq = CipEquipment(equipment_id=new_id(), **payload)
    db.add(eq)
    db.commit()
    db.refresh(eq)
    return eq


def list_equipment(db: Session, area: str = None, active_only: bool = True) -> list:
    stmt = select(CipEquipment)
    if active_only:
        stmt = stmt.where(CipEquipment.active == true())
    if area:
        stmt = stmt.where(CipEquipment.area == area)
    return db.execute(stmt.order_by(CipEquipment.code)).scalars().all()


def update_equipment(db: Session, equipment_id: str, payload: dict, user: User) -> CipEquipment:
    require_perm(user, "master.manage")
    eq = db.get(CipEquipment, equipment_id)
    if not eq:
        raise NotFoundError("Thiết bị CIP không tồn tại.")
    for k, v in payload.items():
        if v is not None:
            setattr(eq, k, v)
    db.commit()
    db.refresh(eq)
    return eq


def delete_equipment(db: Session, equipment_id: str, user: User) -> None:
    require_perm(user, "master.manage")
    eq = db.get(CipEquipment, equipment_id)
    if not eq:
        raise NotFoundError("Thiết bị CIP không tồn tại.")
    n = db.execute(select(func.count()).select_from(CipRecord)
                   .where(CipRecord.equipment_id == equipment_id)).scalar_one()
    if n:
        raise DomainError(f"Không thể xóa thiết bị '{eq.code}' — đang được dùng bởi {n} bản ghi CIP.")
    record_audit(db, entity_type="cip_equipment", entity_id=eq.equipment_id, action="delete",
                actor=user, before={"code": eq.code, "name": eq.name})
    db.delete(eq)
    db.commit()


# ---- Bản ghi CIP ----

def _next_cip_code(db: Session, year: int) -> str:
    count = db.execute(select(func.count()).select_from(CipRecord)
                       .where(CipRecord.cip_year == year)).scalar_one()
    while True:
        count += 1
        code = f"CIP-{year}-{count:05d}"
        exists = db.execute(select(CipRecord.cip_id).where(
            CipRecord.cip_year == year, CipRecord.cip_code == code)).scalar_one_or_none()
        if not exists:
            return code


def _as_dt(v):
    return datetime.fromisoformat(v) if isinstance(v, str) else v


def create_record(db: Session, payload: dict, user: User) -> CipRecord:
    require_perm(user, "cip.manage")
    if not db.get(CipFormType, payload["form_type_id"]):
        raise NotFoundError("Loại biểu mẫu CIP không tồn tại.")
    if not db.get(CipEquipment, payload["equipment_id"]):
        raise NotFoundError("Thiết bị CIP không tồn tại.")
    started_at = _as_dt(payload["started_at"])
    rec = CipRecord(cip_id=new_id(), cip_code=_next_cip_code(db, started_at.year), cip_year=started_at.year,
                    form_type_id=payload["form_type_id"], equipment_id=payload["equipment_id"],
                    batch_number=payload["batch_number"], order_number=payload["order_number"],
                    shift=payload.get("shift"), started_at=started_at, ended_at=_as_dt(payload.get("ended_at")),
                    performed_by=payload.get("performed_by"), duty_officer=payload.get("duty_officer"),
                    steps=payload.get("steps") or [], note=payload.get("note"),
                    created_by=user.username, created_at=utcnow())
    db.add(rec)
    db.flush()
    record_audit(db, entity_type="cip_record", entity_id=rec.cip_id, action="create", actor=user,
                after={"cip_code": rec.cip_code})
    db.commit()
    db.refresh(rec)
    return rec


def update_record(db: Session, cip_id: str, payload: dict, user: User) -> CipRecord:
    require_perm(user, "cip.manage")
    rec = db.get(CipRecord, cip_id)
    if not rec:
        raise NotFoundError("Bản ghi CIP không tồn tại.")
    rec.form_type_id = payload["form_type_id"]
    rec.equipment_id = payload["equipment_id"]
    rec.batch_number = payload["batch_number"]
    rec.order_number = payload["order_number"]
    rec.shift = payload.get("shift")
    rec.started_at = _as_dt(payload["started_at"])
    rec.cip_year = rec.started_at.year
    rec.ended_at = _as_dt(payload.get("ended_at"))
    rec.performed_by = payload.get("performed_by")
    rec.duty_officer = payload.get("duty_officer")
    rec.steps = payload.get("steps") or []
    rec.note = payload.get("note")
    db.commit()
    db.refresh(rec)
    return rec


def approve_record(db: Session, cip_id: str, payload: dict, user: User) -> CipRecord:
    """Nghiệm thu — CHỈ KCS (tái dùng quyền quality.release đã dùng cho Duyệt LM/Lọc/Chiết,
    không tạo permission riêng)."""
    require_perm(user, "quality.release")
    rec = db.get(CipRecord, cip_id)
    if not rec:
        raise NotFoundError("Bản ghi CIP không tồn tại.")
    if payload["result"] not in ("dat", "khong_dat"):
        raise DomainError("Kết quả nghiệm thu phải là 'dat' hoặc 'khong_dat'.")
    rec.result = payload["result"]
    rec.checked_by = payload["checked_by"]
    if payload.get("note"):
        rec.note = payload["note"]
    rec.approved_at = utcnow()
    record_audit(db, entity_type="cip_record", entity_id=rec.cip_id, action="approve", actor=user,
                after={"result": rec.result, "checked_by": rec.checked_by})
    db.commit()
    db.refresh(rec)
    return rec


def get_record(db: Session, cip_id: str) -> CipRecord:
    rec = db.get(CipRecord, cip_id)
    if not rec:
        raise NotFoundError("Bản ghi CIP không tồn tại.")
    return rec


def list_records(db: Session, equipment_id: str = None, form_type_id: str = None,
                 area: str = None, result: str = None, limit: int = 200) -> list:
    stmt = select(CipRecord)
    if equipment_id:
        stmt = stmt.where(CipRecord.equipment_id == equipment_id)
    if form_type_id:
        stmt = stmt.where(CipRecord.form_type_id == form_type_id)
    if result:
        stmt = stmt.where(CipRecord.result == result)
    if area:
        stmt = stmt.join(CipEquipment, CipEquipment.equipment_id == CipRecord.equipment_id).where(
            CipEquipment.area == area)
    rows = db.execute(stmt.order_by(CipRecord.started_at.desc()).limit(limit)).scalars().all()
    eq_by_id = {e.equipment_id: e for e in db.execute(select(CipEquipment)).scalars().all()}
    ft_by_id = {f.form_type_id: f for f in db.execute(select(CipFormType)).scalars().all()}
    out = []
    for r in rows:
        eq = eq_by_id.get(r.equipment_id)
        ft = ft_by_id.get(r.form_type_id)
        linked_count = db.execute(select(func.count()).select_from(CipLink)
                                  .where(CipLink.cip_id == r.cip_id)).scalar_one()
        out.append({"cip_id": r.cip_id, "cip_code": r.cip_code, "form_type_code": ft.code if ft else None,
                    "form_type_name": ft.name if ft else None, "equipment_code": eq.code if eq else None,
                    "equipment_name": eq.name if eq else None, "batch_number": r.batch_number,
                    "order_number": r.order_number, "shift": r.shift, "started_at": r.started_at,
                    "ended_at": r.ended_at, "performed_by": r.performed_by, "result": r.result,
                    "checked_by": r.checked_by, "linked_count": linked_count})
    return out


# ---- Gợi ý + gắn tay với mẻ/lô sản xuất ----

def _codes_for_scope(db: Session, scope_type: str, scope_id: str) -> set:
    """Mã ProductionLine.code mà mẻ/lô này thực sự dùng — để lọc thiết bị có gắn
    production_line_id (tank/dây chuyền cụ thể); thiết bị KHÔNG gắn (dùng chung — đường ống,
    máy nghiền...) luôn hiện bất kể set này."""
    codes = set()
    if scope_type == "brew_batch":
        b = db.get(BrewBatch, scope_id)
        if b and b.line_id:
            line = db.get(ProductionLine, b.line_id)
            if line:
                codes.add(line.code)
    elif scope_type == "ferment":
        f = db.get(FermentRecord, scope_id)
        if f and f.tank_lm:
            codes.add(f.tank_lm)
    elif scope_type == "filter":
        f = db.get(FilterRecord, scope_id)
        if f:
            if f.from_cct:
                codes.add(f.from_cct)
            if f.to_bbt:
                codes.add(f.to_bbt)
    elif scope_type == "bottle":
        b = db.get(BottleRecord, scope_id)
        if b:
            if b.from_bbt:
                codes.add(b.from_bbt)
            if b.line:
                codes.add(b.line)
    return codes


def suggest_for_scope(db: Session, scope_type: str, scope_id: str, limit_per_equipment: int = 5) -> list:
    area = _AREA_BY_SCOPE.get(scope_type)
    if not area:
        raise DomainError(f"Loại đối tượng không hỗ trợ gợi ý CIP: {scope_type}")
    codes = _codes_for_scope(db, scope_type, scope_id)
    equipment_rows = db.execute(select(CipEquipment).where(
        CipEquipment.area == area, CipEquipment.active == true())).scalars().all()
    line_by_id = {l.line_id: l for l in db.execute(select(ProductionLine)).scalars().all()}
    out = []
    for eq in equipment_rows:
        if eq.production_line_id:
            line = line_by_id.get(eq.production_line_id)
            if not line or line.code not in codes:
                continue  # thiết bị gắn tank/dây chuyền cụ thể nhưng KHÔNG khớp mã mẻ này dùng
        recs = db.execute(select(CipRecord).where(CipRecord.equipment_id == eq.equipment_id)
                          .order_by(CipRecord.started_at.desc()).limit(limit_per_equipment)).scalars().all()
        rec_out = []
        for r in recs:
            linked_count = db.execute(select(func.count()).select_from(CipLink)
                                      .where(CipLink.cip_id == r.cip_id)).scalar_one()
            rec_out.append({"cip_id": r.cip_id, "cip_code": r.cip_code, "batch_number": r.batch_number,
                            "order_number": r.order_number, "started_at": r.started_at,
                            "ended_at": r.ended_at, "result": r.result, "linked_count": linked_count})
        out.append({"equipment_id": eq.equipment_id, "equipment_code": eq.code, "equipment_name": eq.name,
                    "records": rec_out})
    return out


def link_records(db: Session, scope_type: str, scope_id: str, cip_ids: list, user: User) -> list:
    require_perm(user, "cip.manage")
    created = []
    for cip_id in cip_ids:
        if not db.get(CipRecord, cip_id):
            raise NotFoundError(f"Không tìm thấy bản ghi CIP {cip_id}.")
        existing = db.execute(select(CipLink).where(
            CipLink.cip_id == cip_id, CipLink.scope_type == scope_type,
            CipLink.scope_id == scope_id)).scalar_one_or_none()
        if existing:
            continue
        link = CipLink(link_id=new_id(), cip_id=cip_id, scope_type=scope_type, scope_id=scope_id,
                       created_by=user.username, created_at=utcnow())
        db.add(link)
        created.append(link)
    db.commit()
    return created


def unlink(db: Session, link_id: str, user: User) -> None:
    require_perm(user, "cip.manage")
    link = db.get(CipLink, link_id)
    if not link:
        raise NotFoundError("Liên kết CIP không tồn tại.")
    db.delete(link)
    db.commit()


def links_for(db: Session, scope_type: str, scope_id: str) -> list:
    rows = db.execute(select(CipLink).where(
        CipLink.scope_type == scope_type, CipLink.scope_id == scope_id)).scalars().all()
    out = []
    for link in rows:
        r = db.get(CipRecord, link.cip_id)
        if not r:
            continue
        eq = db.get(CipEquipment, r.equipment_id)
        ft = db.get(CipFormType, r.form_type_id)
        out.append({"link_id": link.link_id, "cip_id": r.cip_id, "cip_code": r.cip_code,
                    "equipment_name": eq.name if eq else None, "form_type_name": ft.name if ft else None,
                    "batch_number": r.batch_number, "order_number": r.order_number,
                    "started_at": r.started_at, "ended_at": r.ended_at, "result": r.result,
                    "checked_by": r.checked_by})
    return out
