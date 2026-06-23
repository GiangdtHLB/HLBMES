"""Downtime reason-tree + Pareto + MTBF/MTTR + 6 big losses (tài liệu §7.7).

Cây lý do (REASON_TREE) là hằng số: nhóm → mã lý do con, gắn loss_category để phân
rã 6 big losses. MTBF/MTTR suy ra từ Incident + DowntimeEvent theo thiết bị.
"""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import Role, new_id, utcnow
from ..errors import DomainError
from ..models.maintenance import Equipment, Incident
from ..models.oee_ext import DowntimeEvent
from ..security import User, require_role

# Cây lý do dừng máy nhiều cấp. loss ∈ availability|performance|quality (6 big losses).
REASON_TREE = {
    "thiet_bi": {"label": "Thiết bị", "loss": "availability", "reasons": {
        "hong_co_khi": "Hỏng cơ khí", "hong_dien": "Sự cố điện",
        "kep_chai": "Kẹt chai/lon", "ro_ri": "Rò rỉ"}},
    "van_hanh": {"label": "Vận hành", "loss": "availability", "reasons": {
        "thieu_nhan_luc": "Thiếu nhân lực", "cho_lenh": "Chờ lệnh sản xuất",
        "thao_tac_cham": "Thao tác chậm"}},
    "thieu_vat_tu": {"label": "Thiếu vật tư", "loss": "availability", "reasons": {
        "het_chai": "Hết chai/lon", "het_nhan": "Hết nhãn", "het_co2": "Hết CO2",
        "cho_dich": "Chờ dịch bia"}},
    "chuyen_doi": {"label": "Chuyển đổi / CIP", "loss": "performance", "reasons": {
        "cip": "Vệ sinh CIP", "doi_san_pham": "Đổi sản phẩm", "khoi_dong": "Khởi động/chạy thử"}},
    "toc_do": {"label": "Giảm tốc độ", "loss": "performance", "reasons": {
        "chay_cham": "Chạy dưới tốc độ", "dung_nho": "Dừng vặt (micro-stop)"}},
    "chat_luong": {"label": "Chất lượng", "loss": "quality", "reasons": {
        "loi_nhan": "Lỗi dán nhãn", "do_day_sai": "Độ đầy sai", "loi_dong_nap": "Lỗi đóng nắp"}},
}


def reason_tree() -> dict:
    return REASON_TREE


def _resolve(group: str, code: str):
    g = REASON_TREE.get(group)
    if not g:
        raise DomainError(f"Nhóm lý do không hợp lệ: {group}")
    label = g["reasons"].get(code)
    if not label:
        raise DomainError(f"Mã lý do '{code}' không thuộc nhóm '{group}'.")
    return label, g["loss"]


def record_downtime(db: Session, payload: dict, user: User) -> DowntimeEvent:
    require_role(user, Role.OPERATOR, Role.SUPERVISOR, Role.ENGINEER)
    if float(payload.get("minutes", 0) or 0) < 0:
        raise DomainError("Thời gian dừng (phút) không được âm.")
    label, loss = _resolve(payload["reason_group"], payload["reason_code"])
    ev = DowntimeEvent(
        event_id=new_id(), line=payload["line"], equipment_id=payload.get("equipment_id"),
        shift=payload.get("shift", "A"), shift_date=payload.get("shift_date") or utcnow(),
        reason_group=payload["reason_group"], reason_code=payload["reason_code"],
        reason_label=label, loss_category=loss, minutes=float(payload.get("minutes", 0) or 0),
        note=payload.get("note"), recorded_by=user.username, recorded_at=utcnow())
    db.add(ev)
    record_audit(db, entity_type="downtime", entity_id=ev.event_id, action="record", actor=user,
                 after={"line": ev.line, "reason": f"{ev.reason_group}:{ev.reason_code}",
                        "minutes": ev.minutes})
    db.commit()
    db.refresh(ev)
    return ev


def list_events(db: Session, line: str = None) -> list:
    stmt = select(DowntimeEvent).order_by(DowntimeEvent.shift_date.desc(), DowntimeEvent.recorded_at.desc())
    if line:
        stmt = stmt.where(DowntimeEvent.line == line)
    rows = db.execute(stmt).scalars().all()
    return [{"event_id": e.event_id, "line": e.line, "shift": e.shift, "shift_date": e.shift_date,
             "reason_group": e.reason_group, "reason_code": e.reason_code,
             "reason_label": e.reason_label, "loss_category": e.loss_category,
             "minutes": e.minutes, "note": e.note, "recorded_by": e.recorded_by} for e in rows]


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
        g = REASON_TREE.get(e.reason_group, {}).get("label", e.reason_group)
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
