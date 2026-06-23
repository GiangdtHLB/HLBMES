"""Bộ lập lịch sản xuất theo ràng buộc (P3-2).

Xếp các work order (planned/released) lên tank lên men, tôn trọng:
- Không chồng lấn trên cùng tank.
- CIP bắt buộc giữa 2 mẻ trên cùng tank (thời gian vệ sinh).
- Cửa sổ bảo trì (slot maintenance) khóa tài nguyên.
- Kiểm tra đủ NVL theo BOM (đánh dấu material_short nếu thiếu).
Thuật toán: greedy theo (ngày kế hoạch, ưu tiên) + earliest-fit chọn tank kết thúc sớm nhất.
Quy mô lớn: thay bằng CP-SAT/OR-Tools — interface auto_schedule()/board() giữ nguyên.
"""

from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import Role, new_id, utcnow
from ..models.master import Product
from ..models.recipes import RecipeVersion
from ..models.scheduling import ScheduleSlot
from ..models.workorder import WorkOrder
from ..security import User, require_role
from . import bom

TANKS = ["FV-01", "FV-02", "FV-03", "FV-04"]   # fallback nếu chưa khai báo tank trong danh mục


def _tanks(db: Session) -> list:
    """Tank lên men lấy từ danh mục resource (ProductionLine kind='tank', active).
    Chưa khai báo → dùng hằng TANKS để hệ thống vẫn chạy."""
    from ..models.lines import ProductionLine
    rows = db.execute(select(ProductionLine).where(
        ProductionLine.kind == "tank", ProductionLine.active == True  # noqa: E712
    ).order_by(ProductionLine.code)).scalars().all()
    return [r.code for r in rows] or list(TANKS)


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt and dt.tzinfo else dt


def _earliest_start(busy: list, anchor: datetime, duration: timedelta) -> datetime:
    """Mốc bắt đầu sớm nhất ≥ anchor để [t, t+duration] không đè busy (đã sort theo start)."""
    t = anchor
    for s, e in busy:
        if t + duration <= s:
            return t
        if t < e:
            t = e
    return t


def auto_schedule(db: Session, user: User, days: int = 10,
                  prod_hours: int = 48, cip_hours: int = 4) -> dict:
    require_role(user, Role.SUPERVISOR, Role.ENGINEER)
    # Sinh lại slot production/cip; giữ slot maintenance.
    for s in db.execute(select(ScheduleSlot).where(
            ScheduleSlot.kind.in_(["production", "cip"]))).scalars().all():
        db.delete(s)
    db.flush()

    now = _naive(utcnow())
    horizon = now + timedelta(days=days)
    prod = timedelta(hours=prod_hours)
    cip = timedelta(hours=cip_hours)
    tanks = _tanks(db)

    # busy theo tài nguyên: khởi tạo từ slot maintenance.
    busy = {t: [] for t in tanks}
    used = {t: False for t in tanks}      # tank đã có mẻ trước đó → cần CIP trước mẻ mới
    for m in db.execute(select(ScheduleSlot).where(ScheduleSlot.kind == "maintenance")).scalars().all():
        if m.resource in busy:
            busy[m.resource].append((_naive(m.start_at), _naive(m.end_at)))
    for t in busy:
        busy[t].sort()

    wos = db.execute(select(WorkOrder).where(
        WorkOrder.status.in_(["planned", "released"])
    ).order_by(WorkOrder.scheduled_date, WorkOrder.priority)).scalars().all()

    placed, shortages = [], 0
    for wo in wos:
        anchor = datetime.combine(wo.scheduled_date, time(6, 0)) if wo.scheduled_date else now
        anchor = max(anchor, now)
        # vật tư đủ?
        short = False
        if wo.recipe_version_id:
            rv = db.get(RecipeVersion, wo.recipe_version_id)
            if rv:
                snap = {"base_qty": rv.base_qty, "base_uom": rv.base_uom, "materials": rv.materials}
                try:
                    short = bom.availability(db, snap, wo.planned_qty)["shortage"]
                except Exception:  # noqa: BLE001
                    short = False
        # chọn tank: thử mọi tank, lấy nơi production bắt đầu sớm nhất.
        best = None
        for t in tanks:
            need = (cip + prod) if used[t] else prod
            start = _earliest_start(busy[t], anchor, need)
            prod_start = start + (cip if used[t] else timedelta())
            if best is None or prod_start < best[1]:
                best = (t, prod_start, start)
        tank, prod_start, block_start = best
        if prod_start > horizon:
            continue  # ngoài tầm nhìn → để vòng sau
        # đặt CIP (nếu tank đã dùng) + production
        if used[tank]:
            cip_end = block_start + cip
            db.add(ScheduleSlot(slot_id=new_id(), resource=tank, kind="cip",
                                status="planned", start_at=block_start, end_at=cip_end,
                                note="CIP giữa mẻ"))
            busy[tank].append((block_start, cip_end))
        prod_end = prod_start + prod
        prod_obj = db.get(Product, wo.product_id) if wo.product_id else None
        db.add(ScheduleSlot(slot_id=new_id(), resource=tank, kind="production",
                            wo_id=wo.wo_id, wo_code=wo.wo_code,
                            product=prod_obj.code if prod_obj else None,
                            status="material_short" if short else "planned",
                            start_at=prod_start, end_at=prod_end,
                            note="Thiếu NVL theo BOM" if short else None))
        busy[tank].append((prod_start, prod_end))
        busy[tank].sort()
        used[tank] = True
        if short:
            shortages += 1
        placed.append({"wo_code": wo.wo_code, "tank": tank,
                       "start": prod_start.isoformat(), "end": prod_end.isoformat()})

    record_audit(db, entity_type="schedule", entity_id="auto", action="auto_schedule",
                 actor=user, after={"placed": len(placed), "shortages": shortages})
    db.commit()
    return {"placed": len(placed), "shortages": shortages, "tanks": len(tanks), "items": placed}


def board(db: Session) -> dict:
    """Slot theo tài nguyên cho Gantt."""
    tanks = _tanks(db)
    slots = db.execute(select(ScheduleSlot).order_by(ScheduleSlot.start_at)).scalars().all()
    resources = tanks + sorted({s.resource for s in slots if s.resource not in tanks})
    by_res = {r: [] for r in resources}
    for s in slots:
        by_res.setdefault(s.resource, []).append(
            {"slot_id": s.slot_id, "kind": s.kind, "wo_code": s.wo_code, "product": s.product,
             "status": s.status, "start_at": s.start_at, "end_at": s.end_at, "note": s.note})
    span = [s for s in slots]
    return {"resources": list(by_res.keys()), "lanes": by_res,
            "from": min((_naive(s.start_at) for s in span), default=None),
            "to": max((_naive(s.end_at) for s in span), default=None),
            "count": len(slots)}


def conflicts(db: Session) -> dict:
    """Phát hiện chồng lấn trên cùng tài nguyên + thiếu NVL."""
    slots = db.execute(select(ScheduleSlot).order_by(ScheduleSlot.resource,
                                                     ScheduleSlot.start_at)).scalars().all()
    overlaps, shorts = [], []
    by_res = {}
    for s in slots:
        by_res.setdefault(s.resource, []).append(s)
        if s.status == "material_short":
            shorts.append({"resource": s.resource, "wo_code": s.wo_code})
    for res, lst in by_res.items():
        lst.sort(key=lambda x: _naive(x.start_at))
        for i in range(1, len(lst)):
            if _naive(lst[i].start_at) < _naive(lst[i - 1].end_at):
                overlaps.append({"resource": res,
                                 "a": lst[i - 1].wo_code or lst[i - 1].kind,
                                 "b": lst[i].wo_code or lst[i].kind})
    return {"overlaps": overlaps, "material_short": shorts,
            "ok": not overlaps and not shorts}
