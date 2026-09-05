"""Danh mục "Tham số quy trình" (setpoint công nghệ, VD nhiệt độ đường hóa/lên men) — mirror
đúng cấu trúc/hành vi của services/qc_catalog.py (nhóm chỉ tiêu chất lượng) nhưng cho tham số
vận hành. Recipe chọn tham số từ đây thay vì gõ tay tên (xem models/recipes.py::
RecipeVersionParamItem, services/recipes.py)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import new_id
from ..errors import DomainError, NotFoundError
from ..models.quality_ext import ProcessParameter, ProcessParameterGroup, ProcessParameterGroupItem, ProcessPhase
from ..models.recipes import RecipeVersionParamItem
from ..security import User, require_perm


# ---- Công đoạn ----

def list_phases(db: Session, active_only: bool = False) -> list[ProcessPhase]:
    stmt = select(ProcessPhase).order_by(ProcessPhase.code)
    if active_only:
        stmt = stmt.where(ProcessPhase.active == True)  # noqa: E712
    return db.execute(stmt).scalars().all()


def create_phase(db: Session, payload: dict, user: User) -> ProcessPhase:
    require_perm(user, "master.manage")
    if db.execute(select(ProcessPhase).where(ProcessPhase.code == payload["code"])).scalar_one_or_none():
        raise DomainError(f"Mã công đoạn '{payload['code']}' đã tồn tại.")
    ph = ProcessPhase(phase_id=new_id(), **payload)
    db.add(ph)
    record_audit(db, entity_type="process_phase", entity_id=ph.phase_id, action="create",
                 actor=user, after={"code": ph.code, "name": ph.name})
    db.commit()
    db.refresh(ph)
    return ph


def update_phase(db: Session, phase_id: str, payload: dict, user: User) -> ProcessPhase:
    require_perm(user, "master.manage")
    ph = db.get(ProcessPhase, phase_id)
    if not ph:
        raise NotFoundError("Công đoạn không tồn tại.")
    before = {"code": ph.code, "name": ph.name, "active": ph.active}
    for k, v in payload.items():
        setattr(ph, k, v)
    record_audit(db, entity_type="process_phase", entity_id=ph.phase_id, action="update",
                 actor=user, before=before, after=payload)
    db.commit()
    db.refresh(ph)
    return ph


def delete_phase(db: Session, phase_id: str, user: User) -> None:
    """Chỉ xóa được khi công đoạn CHƯA được dùng làm phase mặc định của 1 Tham số quy trình
    hoặc phase_override của 1 tham số trong Recipe — mirror master_data.py::
    delete_material_group (chặn xóa "mồ côi" dữ liệu đang tham chiếu theo code)."""
    require_perm(user, "master.manage")
    ph = db.get(ProcessPhase, phase_id)
    if not ph:
        raise NotFoundError("Công đoạn không tồn tại.")
    used_param = db.execute(select(ProcessParameter).where(ProcessParameter.phase == ph.code)).first()
    used_override = db.execute(
        select(RecipeVersionParamItem).where(RecipeVersionParamItem.phase_override == ph.code)).first()
    if used_param or used_override:
        raise DomainError(f"Không thể xóa — công đoạn '{ph.code}' đang được dùng ở ít nhất 1 tham số quy trình hoặc công thức. Hãy đổi công đoạn ở đó trước.")
    record_audit(db, entity_type="process_phase", entity_id=phase_id, action="delete", actor=user,
                 before={"code": ph.code, "name": ph.name})
    db.delete(ph)
    db.commit()


# ---- Tham số ----

def list_parameters(db: Session, active_only: bool = True) -> list:
    stmt = select(ProcessParameter).order_by(ProcessParameter.code)
    if active_only:
        stmt = stmt.where(ProcessParameter.active == True)  # noqa: E712
    rows = db.execute(stmt).scalars().all()
    return [{"param_id": p.param_id, "code": p.code, "name": p.name, "unit": p.unit,
             "target": p.target, "usl": p.usl, "lsl": p.lsl, "phase": p.phase,
             "note": p.note, "active": p.active} for p in rows]


def create_parameter(db: Session, payload: dict, user: User) -> ProcessParameter:
    require_perm(user, "master.manage")
    if db.execute(select(ProcessParameter).where(ProcessParameter.code == payload["code"])).scalar_one_or_none():
        raise DomainError(f"Mã tham số '{payload['code']}' đã tồn tại.")
    p = ProcessParameter(param_id=new_id(), **payload)
    db.add(p)
    record_audit(db, entity_type="process_parameter", entity_id=p.param_id, action="create",
                 actor=user, after={"code": p.code, "name": p.name})
    db.commit()
    db.refresh(p)
    return p


def update_parameter(db: Session, param_id: str, payload: dict, user: User) -> ProcessParameter:
    require_perm(user, "master.manage")
    p = db.get(ProcessParameter, param_id)
    if not p:
        raise NotFoundError("Tham số không tồn tại.")
    before = {"code": p.code, "name": p.name, "usl": p.usl, "lsl": p.lsl, "active": p.active}
    for k, v in payload.items():
        setattr(p, k, v)
    record_audit(db, entity_type="process_parameter", entity_id=p.param_id, action="update",
                 actor=user, before=before, after=payload)
    db.commit()
    db.refresh(p)
    return p


def delete_parameter(db: Session, param_id: str, user: User) -> None:
    """Chỉ xóa được khi tham số CHƯA được gán vào bất kỳ Nhóm tham số nào
    (ProcessParameterGroupItem) — tránh xóa "mồ côi" 1 tham số đang dùng ở Recipe qua nhóm
    chứa nó."""
    require_perm(user, "master.manage")
    p = db.get(ProcessParameter, param_id)
    if not p:
        raise NotFoundError("Tham số không tồn tại.")
    used = db.execute(select(ProcessParameterGroupItem).where(
        ProcessParameterGroupItem.param_id == param_id)).first()
    if used:
        raise DomainError(f"Không thể xóa — tham số '{p.code}' đang được gán vào ít nhất 1 nhóm tham số. Hãy gỡ gán trước.")
    record_audit(db, entity_type="process_parameter", entity_id=param_id, action="delete", actor=user,
                 before={"code": p.code, "name": p.name})
    db.delete(p)
    db.commit()


# ---- Nhóm tham số ----

def list_groups(db: Session) -> list[ProcessParameterGroup]:
    return db.execute(select(ProcessParameterGroup).order_by(ProcessParameterGroup.code)).scalars().all()


def create_group(db: Session, payload: dict, user: User) -> ProcessParameterGroup:
    require_perm(user, "master.manage")
    if db.execute(select(ProcessParameterGroup).where(ProcessParameterGroup.code == payload["code"])).scalar_one_or_none():
        raise DomainError(f"Mã nhóm tham số '{payload['code']}' đã tồn tại.")
    g = ProcessParameterGroup(group_id=new_id(), **payload)
    db.add(g)
    record_audit(db, entity_type="process_parameter_group", entity_id=g.group_id, action="create",
                 actor=user, after={"code": g.code, "name": g.name})
    db.commit()
    db.refresh(g)
    return g


def update_group(db: Session, group_id: str, payload: dict, user: User) -> ProcessParameterGroup:
    require_perm(user, "master.manage")
    g = db.get(ProcessParameterGroup, group_id)
    if not g:
        raise NotFoundError("Nhóm tham số không tồn tại.")
    before = {"code": g.code, "name": g.name, "note": g.note, "active": g.active}
    for k, v in payload.items():
        setattr(g, k, v)
    record_audit(db, entity_type="process_parameter_group", entity_id=g.group_id, action="update",
                 actor=user, before=before, after=payload)
    db.commit()
    db.refresh(g)
    return g


def delete_group(db: Session, group_id: str, user: User) -> None:
    """Xóa kèm các tham số trong nhóm (ProcessParameterGroupItem) vì chỉ có ý nghĩa gắn với
    nhóm này — không cần chặn theo dùng-ở-đâu-khác như QCParameterGroup (chưa có "gán nhóm
    tham số cho công đoạn" như StageQcGroup, chỉ Recipe tham chiếu THẲNG param_id, không qua
    group_id — xem models/recipes.py::RecipeVersionParamItem)."""
    require_perm(user, "master.manage")
    g = db.get(ProcessParameterGroup, group_id)
    if not g:
        raise NotFoundError("Nhóm tham số không tồn tại.")
    for item in db.execute(select(ProcessParameterGroupItem).where(
            ProcessParameterGroupItem.group_id == group_id)).scalars().all():
        db.delete(item)
    record_audit(db, entity_type="process_parameter_group", entity_id=group_id, action="delete", actor=user,
                 before={"code": g.code, "name": g.name})
    db.delete(g)
    db.commit()


# ---- Tham số trong nhóm ----

def _item_out(db: Session, item: ProcessParameterGroupItem) -> dict:
    param = db.get(ProcessParameter, item.param_id)
    return {
        "item_id": item.item_id, "group_id": item.group_id, "param_id": item.param_id,
        "seq": item.seq, "mandatory": item.mandatory,
        "target_override": item.target_override, "usl_override": item.usl_override,
        "lsl_override": item.lsl_override, "phase_override": item.phase_override,
        "param_code": param.code if param else None,
        "param_name": param.name if param else None,
        "param_unit": param.unit if param else None,
    }


def list_items(db: Session, group_id: str) -> list[dict]:
    items = db.execute(
        select(ProcessParameterGroupItem).where(ProcessParameterGroupItem.group_id == group_id)
        .order_by(ProcessParameterGroupItem.seq)
    ).scalars().all()
    return [_item_out(db, it) for it in items]


def add_item(db: Session, group_id: str, payload: dict, user: User) -> dict:
    require_perm(user, "master.manage")
    if not db.get(ProcessParameterGroup, group_id):
        raise NotFoundError("Nhóm tham số không tồn tại.")
    if not db.get(ProcessParameter, payload["param_id"]):
        raise NotFoundError("Tham số không tồn tại.")
    item = ProcessParameterGroupItem(item_id=new_id(), group_id=group_id, **payload)
    db.add(item)
    record_audit(db, entity_type="process_parameter_group_item", entity_id=item.item_id, action="create",
                 actor=user, after={"group_id": group_id, "param_id": payload["param_id"]})
    db.commit()
    db.refresh(item)
    return _item_out(db, item)


def copy_items(db: Session, target_group_id: str, source_group_id: str, user: User) -> list[dict]:
    """Copy toàn bộ tham số (kèm min/max/bắt buộc riêng của nhóm nguồn) sang nhóm đích — chỉ
    cho phép khi nhóm đích đang RỖNG, mirror qc_catalog.py::copy_items."""
    require_perm(user, "master.manage")
    if not db.get(ProcessParameterGroup, target_group_id):
        raise NotFoundError("Nhóm tham số đích không tồn tại.")
    source = db.get(ProcessParameterGroup, source_group_id)
    if not source:
        raise NotFoundError("Nhóm tham số nguồn không tồn tại.")
    if source_group_id == target_group_id:
        raise DomainError("Nhóm nguồn và nhóm đích phải khác nhau.")

    target_has_items = db.execute(
        select(ProcessParameterGroupItem.item_id).where(
            ProcessParameterGroupItem.group_id == target_group_id).limit(1)
    ).first()
    if target_has_items:
        raise DomainError("Nhóm đích đã có tham số — chỉ có thể copy vào nhóm đang rỗng.")
    source_items = db.execute(
        select(ProcessParameterGroupItem).where(ProcessParameterGroupItem.group_id == source_group_id)
        .order_by(ProcessParameterGroupItem.seq)
    ).scalars().all()

    for it in source_items:
        db.add(ProcessParameterGroupItem(
            item_id=new_id(), group_id=target_group_id, param_id=it.param_id, seq=it.seq,
            mandatory=it.mandatory, target_override=it.target_override,
            usl_override=it.usl_override, lsl_override=it.lsl_override,
            phase_override=it.phase_override,
        ))
    record_audit(db, entity_type="process_parameter_group", entity_id=target_group_id, action="copy_items",
                 actor=user, after={"source_group_id": source_group_id, "copied": len(source_items)})
    db.commit()
    return list_items(db, target_group_id)


def update_item(db: Session, item_id: str, payload: dict, user: User) -> dict:
    require_perm(user, "master.manage")
    item = db.get(ProcessParameterGroupItem, item_id)
    if not item:
        raise NotFoundError("Tham số trong nhóm không tồn tại.")
    for k, v in payload.items():
        setattr(item, k, v)
    record_audit(db, entity_type="process_parameter_group_item", entity_id=item.item_id, action="update",
                 actor=user, after=payload)
    db.commit()
    db.refresh(item)
    return _item_out(db, item)


def delete_item(db: Session, item_id: str, user: User) -> None:
    require_perm(user, "master.manage")
    item = db.get(ProcessParameterGroupItem, item_id)
    if not item:
        raise NotFoundError("Tham số trong nhóm không tồn tại.")
    db.delete(item)
    record_audit(db, entity_type="process_parameter_group_item", entity_id=item_id, action="delete", actor=user)
    db.commit()
