"""Downtime dừng máy: danh mục lý do theo dây chuyền (OeeReasonCatalog, thay REASON_TREE
hardcode cũ) + ghi sự kiện + Pareto + MTBF/MTTR + 6 big losses (tài liệu §7.7).

OeeReasonCatalog khớp đúng 8 nhóm tổn thất OPI thật của nhà máy (xem file vận hành gốc
"OPI - CAN L3 (KHS 30K).xlsx", services/oee_waterfall.py giải thích công thức đầy đủ) — mỗi
DowntimeEvent gắn reason_catalog_id, còn reason_group/reason_code/reason_label/loss_category
được SAO CHÉP LẠI vào sự kiện tại thời điểm ghi để Pareto/big_losses/MTBF cũ (đọc thẳng các cột
này) không cần sửa. loss_category (availability/performance/quality) suy từ category theo
_CATEGORY_LOSS bên dưới — mirror đúng phân loại 6 Big Losses kinh điển của TPM.
"""

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import Role, new_id, utcnow
from ..errors import DomainError, NotFoundError
from ..models.maintenance import Equipment, Incident
from ..models.oee_ext import DowntimeEvent, OeeMinorStopTally, OeeReasonCatalog
from ..security import User, require_perm, require_role

# category (OeeReasonCatalog) -> nhóm 6 Big Losses kinh điển (availability/performance/quality)
_CATEGORY_LOSS = {
    "bao_tri_ngoai": "availability", "nona": "availability", "ke_hoach": "availability",
    "chuyen_may": "availability", "thieu_vat_tu": "availability", "breakdown": "availability",
    "dung_lat_nhat": "performance", "sp_loi": "quality",
}

CATEGORY_LABELS = {
    "bao_tri_ngoai": "Bảo trì ngoài", "nona": "NONA", "ke_hoach": "Dừng có kế hoạch",
    "chuyen_may": "Chuyển máy", "thieu_vat_tu": "Dừng nguyên vật liệu",
    "breakdown": "Breakdown", "dung_lat_nhat": "Dừng lắt nhắt", "sp_loi": "Sản phẩm lỗi",
}


def list_reason_catalog(db: Session, line_code: str = None, category: str = None,
                        active_only: bool = True) -> list:
    stmt = select(OeeReasonCatalog)
    if line_code:
        stmt = stmt.where((OeeReasonCatalog.line_code == line_code) | (OeeReasonCatalog.line_code.is_(None)))
    if category:
        stmt = stmt.where(OeeReasonCatalog.category == category)
    if active_only:
        stmt = stmt.where(OeeReasonCatalog.active == True)  # noqa: E712
    stmt = stmt.order_by(OeeReasonCatalog.category, OeeReasonCatalog.sort_order)
    rows = db.execute(stmt).scalars().all()
    return [{"reason_id": r.reason_id, "line_code": r.line_code, "category": r.category,
             "category_label": CATEGORY_LABELS.get(r.category, r.category), "sub_code": r.sub_code,
             "sub_label": r.sub_label, "machine_position": r.machine_position,
             "target_pct": r.target_pct, "active": r.active, "sort_order": r.sort_order} for r in rows]


def reason_tree(db: Session, line_code: str = None) -> dict:
    """Cây lý do nhóm theo category — tương thích cách hiển thị cascading select cũ."""
    rows = list_reason_catalog(db, line_code=line_code)
    tree = {}
    for r in rows:
        g = tree.setdefault(r["category"], {"label": r["category_label"],
                                            "loss": _CATEGORY_LOSS.get(r["category"], "availability"),
                                            "reasons": {}})
        g["reasons"][r["sub_code"]] = r["sub_label"]
    return tree


def create_reason(db: Session, payload: dict, user: User) -> OeeReasonCatalog:
    require_perm(user, "master.manage")
    if payload["category"] not in _CATEGORY_LOSS:
        raise DomainError(f"Nhóm lý do không hợp lệ: {payload['category']}")
    row = OeeReasonCatalog(reason_id=new_id(), line_code=payload.get("line_code"),
                           category=payload["category"], sub_code=payload["sub_code"],
                           sub_label=payload["sub_label"], machine_position=payload.get("machine_position"),
                           target_pct=float(payload.get("target_pct", 0) or 0),
                           active=payload.get("active", True), sort_order=int(payload.get("sort_order", 0) or 0))
    db.add(row)
    record_audit(db, entity_type="oee_reason_catalog", entity_id=row.reason_id, action="create",
                actor=user, after={"category": row.category, "sub_code": row.sub_code})
    db.commit()
    db.refresh(row)
    return row


def update_reason(db: Session, reason_id: str, payload: dict, user: User) -> OeeReasonCatalog:
    require_perm(user, "master.manage")
    row = db.get(OeeReasonCatalog, reason_id)
    if not row:
        raise NotFoundError("Lý do dừng máy không tồn tại.")
    for field in ("sub_label", "target_pct", "machine_position", "active", "sort_order"):
        if field in payload and payload[field] is not None:
            setattr(row, field, payload[field])
    db.commit()
    db.refresh(row)
    return row


def delete_reason(db: Session, reason_id: str, user: User) -> None:
    require_perm(user, "master.manage")
    row = db.get(OeeReasonCatalog, reason_id)
    if not row:
        raise NotFoundError("Lý do dừng máy không tồn tại.")
    used_events = db.execute(select(func.count(DowntimeEvent.event_id))
                             .where(DowntimeEvent.reason_catalog_id == reason_id)).scalar() or 0
    used_tally = db.execute(select(func.count(OeeMinorStopTally.tally_id))
                            .where(OeeMinorStopTally.reason_id == reason_id)).scalar() or 0
    if used_events or used_tally:
        raise DomainError(f"Không thể xóa lý do '{row.sub_label}' — đang được dùng bởi "
                          f"{used_events} sự kiện dừng máy, {used_tally} bản ghi dừng lắt nhắt.")
    db.delete(row)
    record_audit(db, entity_type="oee_reason_catalog", entity_id=reason_id, action="delete",
                actor=user, before={"category": row.category, "sub_code": row.sub_code})
    db.commit()


def record_downtime(db: Session, payload: dict, user: User) -> DowntimeEvent:
    require_role(user, Role.OPERATOR, Role.SUPERVISOR, Role.ENGINEER)
    reason = db.get(OeeReasonCatalog, payload["reason_catalog_id"])
    if not reason:
        raise NotFoundError("Lý do dừng máy không tồn tại.")

    from_time, to_time = payload.get("from_time"), payload.get("to_time")
    if from_time and to_time:
        minutes = (to_time - from_time).total_seconds() / 60.0
    else:
        minutes = float(payload.get("minutes", 0) or 0)
    if minutes < 0:
        raise DomainError("Thời gian dừng (phút) không được âm.")

    ev = DowntimeEvent(
        event_id=new_id(), line=payload["line"], equipment_id=payload.get("equipment_id"),
        shift=payload.get("shift", "A"), shift_date=payload.get("shift_date") or utcnow(),
        reason_group=reason.category, reason_code=reason.sub_code, reason_label=reason.sub_label,
        reason_catalog_id=reason.reason_id, loss_category=_CATEGORY_LOSS.get(reason.category, "availability"),
        minutes=minutes, start_at=from_time, end_at=to_time,
        error_code=payload.get("error_code") if reason.category == "breakdown" else None,
        note=payload.get("note"), recorded_by=user.username, recorded_at=utcnow())
    db.add(ev)
    record_audit(db, entity_type="downtime", entity_id=ev.event_id, action="record", actor=user,
                 after={"line": ev.line, "reason": f"{ev.reason_group}:{ev.reason_code}",
                        "minutes": ev.minutes})
    db.commit()
    db.refresh(ev)
    return ev


def list_events(db: Session, line: str = None, limit: int = None) -> list:
    stmt = select(DowntimeEvent).order_by(DowntimeEvent.shift_date.desc(), DowntimeEvent.recorded_at.desc())
    if line:
        stmt = stmt.where(DowntimeEvent.line == line)
    if limit:
        stmt = stmt.limit(limit)
    rows = db.execute(stmt).scalars().all()
    return [{"event_id": e.event_id, "line": e.line, "shift": e.shift, "shift_date": e.shift_date,
             "reason_group": e.reason_group, "reason_code": e.reason_code,
             "reason_label": e.reason_label, "loss_category": e.loss_category,
             "minutes": e.minutes, "start_at": e.start_at, "end_at": e.end_at,
             "error_code": e.error_code, "rcfa_id": e.rcfa_id,
             "note": e.note, "recorded_by": e.recorded_by} for e in rows]


def pareto(db: Session, line: str = None) -> dict:
    """Pareto thời gian dừng theo lý do (group:code) — giảm dần + % tích lũy."""
    stmt = select(DowntimeEvent)
    if line:
        stmt = stmt.where(DowntimeEvent.line == line)
    rows = db.execute(stmt).scalars().all()
    agg = {}
    for e in rows:
        key = f"{e.reason_group}:{e.reason_code}"
        if key not in agg:
            agg[key] = {"reason_group": e.reason_group, "reason_code": e.reason_code,
                        "label": e.reason_label or e.reason_code,
                        "loss_category": e.loss_category, "minutes": 0.0, "count": 0}
        agg[key]["minutes"] += e.minutes
        agg[key]["count"] += 1
    items = sorted(agg.values(), key=lambda x: x["minutes"], reverse=True)
    total = sum(i["minutes"] for i in items)
    denom = total or 1.0           # tránh chia 0; KHÔNG dùng làm total báo cáo
    cum = 0.0
    for it in items:
        raw = it["minutes"]
        cum += raw                 # tích lũy giá trị GỐC (không cộng dồn số đã làm tròn)
        it["pct"] = round(raw / denom * 100, 1)
        it["cum_pct"] = round(cum / denom * 100, 1)
        it["minutes"] = round(raw, 1)
    return {"total_minutes": round(total, 1), "items": items}


def pareto_by_category(db: Session, line: str = None) -> dict:
    """Pareto theo 8 nhóm tổn thất OPI (category) — mirror bảng Pareto chính trong sheet Summary."""
    stmt = select(DowntimeEvent)
    if line:
        stmt = stmt.where(DowntimeEvent.line == line)
    rows = db.execute(stmt).scalars().all()
    agg = {}
    for e in rows:
        key = e.reason_group
        if key not in agg:
            agg[key] = {"category": key, "label": CATEGORY_LABELS.get(key, key), "minutes": 0.0, "count": 0}
        agg[key]["minutes"] += e.minutes
        agg[key]["count"] += 1
    items = sorted(agg.values(), key=lambda x: x["minutes"], reverse=True)
    total = sum(i["minutes"] for i in items)
    denom = total or 1.0
    cum = 0.0
    for it in items:
        raw = it["minutes"]
        cum += raw
        it["pct"] = round(raw / denom * 100, 1)
        it["cum_pct"] = round(cum / denom * 100, 1)
        it["minutes"] = round(raw, 1)
    return {"total_minutes": round(total, 1), "items": items}


def big_losses(db: Session, line: str = None) -> dict:
    """Phân rã 6 big losses theo loss_category (availability/performance/quality)."""
    stmt = select(DowntimeEvent)
    if line:
        stmt = stmt.where(DowntimeEvent.line == line)
    rows = db.execute(stmt).scalars().all()
    cats = {"availability": 0.0, "performance": 0.0, "quality": 0.0}
    by_group = {}
    for e in rows:
        cats[e.loss_category] = cats.get(e.loss_category, 0.0) + e.minutes
        g = CATEGORY_LABELS.get(e.reason_group, e.reason_group)
        by_group[g] = round(by_group.get(g, 0.0) + e.minutes, 1)
    return {"by_category": {k: round(v, 1) for k, v in cats.items()},
            "by_group": by_group, "total_minutes": round(sum(cats.values()), 1)}


def mtbf_mttr(db: Session, days: int = 30) -> dict:
    """MTBF/MTTR theo thiết bị từ Incident (cửa sổ `days` ngày).

    MTTR = tổng thời gian sửa / số lần hỏng. MTBF = (thời gian vận hành − dừng)/số lần hỏng.
    availability = (window − downtime)/window.
    """
    window_min = days * 24 * 60
    cutoff = utcnow() - timedelta(days=days)

    def _after_cutoff(ts) -> bool:
        if ts is None:
            return False
        c = cutoff.replace(tzinfo=None) if ts.tzinfo is None else cutoff
        return ts >= c

    eqs = db.execute(select(Equipment)).scalars().all()
    incidents = [i for i in db.execute(select(Incident)).scalars().all()
                 if _after_cutoff(i.reported_at)]
    events = [e for e in db.execute(select(DowntimeEvent)).scalars().all()
              if _after_cutoff(e.shift_date)]
    by_eq, dt_by_eq = {}, {}
    for inc in incidents:
        by_eq.setdefault(inc.equipment_id, []).append(inc)
    for e in events:
        dt_by_eq.setdefault(e.equipment_id, []).append(e)
    out = []
    for eq in eqs:
        incs = by_eq.get(eq.equipment_id, [])
        failures = len(incs)
        repair = sum(i.downtime_min or 0 for i in incs)
        # cộng thêm downtime_event gắn equipment (trong cùng cửa sổ)
        downtime = repair + sum(e.minutes for e in dt_by_eq.get(eq.equipment_id, []))
        if failures == 0:
            out.append({"equipment_code": eq.code, "name": eq.name, "failures": 0,
                        "mtbf_hours": None, "mttr_min": None,
                        "availability_pct": 100.0, "downtime_min": round(downtime, 1)})
            continue
        mttr = repair / failures
        uptime = max(window_min - downtime, 0)
        mtbf = uptime / failures
        out.append({"equipment_code": eq.code, "name": eq.name, "failures": failures,
                    "mtbf_hours": round(mtbf / 60.0, 1), "mttr_min": round(mttr, 1),
                    "availability_pct": round(uptime / window_min * 100, 1),
                    "downtime_min": round(downtime, 1)})
    out.sort(key=lambda x: (x["failures"], x["downtime_min"]), reverse=True)
    return {"window_days": days, "equipment": out}
