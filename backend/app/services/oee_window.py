"""OEE cho KHUNG GIỜ BẤT KỲ (giờ/ca/ngày/đang chạy) — blueprint "OEE khung giờ bất kỳ"
2026-09-20: thay vì khóa OEE vào "ca" (1 bản ghi OEERecord/ca), lưu 3 luồng sự kiện thô có
mốc thời gian rồi lọc theo [t1, t2] bất kỳ:

- downtime_event (đã có, services/downtime.py) — nuôi Availability theo THỜI GIAN.
- OeeCountEvent (sản lượng tốt, có ts) — nuôi Performance + Quality.
- OeeRejectEvent (phế phẩm, có ts) — nuôi Quality. ĐỘC LẬP với count_event, KHÔNG suy ra
  bằng (Tổng − Tốt): lúc dừng máy không có count nào (tổn thất đó thuộc Availability, không
  phải Quality), và luôn có hàng đang di chuyển giữa 2 counter (WIP) làm chênh lệch giả.

Công thức cho [t1, t2]:
  window_min = t2 - t1
  down       = Σ phần giao của downtime_event với [t1, t2]
  run_time   = window_min - down
  A = run_time / window_min
  P = (good + reject) / (run_time * ideal_rate)   — kẹp ≤ 100%
  Q = good / (good + reject)
  OEE = A × P × Q
"""

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..common import new_id, utcnow
from ..errors import DomainError
from ..models.lines import ProductionLine
from ..models.oee_ext import DowntimeEvent, OeeCountEvent, OeeRejectEvent
from ..security import User, require_role
from ..common import Role


def _overlap_minutes(ev_start: datetime, ev_end: datetime, t1: datetime, t2: datetime) -> float:
    if ev_start is None or ev_end is None:
        return 0.0
    s = max(ev_start, t1)
    e = min(ev_end, t2)
    return max((e - s).total_seconds() / 60.0, 0.0)


def compute_oee_window(db: Session, line: str, t1: datetime, t2: datetime,
                       ideal_rate_per_min: float = None) -> dict:
    if t2 <= t1:
        raise DomainError("Khung thời gian không hợp lệ — t2 phải sau t1.")
    window_min = (t2 - t1).total_seconds() / 60.0

    if ideal_rate_per_min is None:
        pl = db.execute(select(ProductionLine).where(ProductionLine.code == line)).scalar_one_or_none()
        ideal_rate_per_min = pl.ideal_rate_per_min if pl else 0.0

    # Không prefilter theo shift_date — đó chỉ là nhãn "ca nào", không đảm bảo gần với
    # start_at/end_at thật (shift_date mặc định = lúc ghi, có thể lệch xa thời điểm dừng thật
    # với dữ liệu nhập tay theo ca cũ). Lấy hết theo line rồi tính overlap CHÍNH XÁC theo
    # start_at/end_at (rơi lại shift_date+minutes cho dữ liệu cũ chưa có mốc giờ chính xác).
    events = db.execute(select(DowntimeEvent).where(DowntimeEvent.line == line)).scalars().all()
    down = 0.0
    for e in events:
        s = e.start_at or e.shift_date
        d = e.end_at or (s + timedelta(minutes=e.minutes or 0.0))
        down += _overlap_minutes(s, d, t1, t2)
    down = min(down, window_min)

    # Biên t2 lấy INCLUSIVE (<=) — input datetime-local (frontend) chỉ có độ chính xác tới
    # PHÚT, nên "ghi sự kiện" rồi "xem OEE khung kết thúc = bây giờ" trong cùng 1 phút rất dễ
    # cho ts trùng khớp đúng t2 (giây bị cắt) — dùng "<" nghiêm ngặt sẽ loại nhầm sự kiện vừa
    # ghi ra khỏi khung, gây cảm giác sai là "chưa ghi được gì".
    good = db.execute(select(func.coalesce(func.sum(OeeCountEvent.qty), 0.0)).where(
        OeeCountEvent.line == line, OeeCountEvent.ts >= t1, OeeCountEvent.ts <= t2)).scalar() or 0.0
    reject = db.execute(select(func.coalesce(func.sum(OeeRejectEvent.qty), 0.0)).where(
        OeeRejectEvent.line == line, OeeRejectEvent.ts >= t1, OeeRejectEvent.ts <= t2)).scalar() or 0.0
    total = good + reject

    run_time = max(window_min - down, 0.0)
    availability = (run_time / window_min) if window_min > 0 else 0.0
    ideal_capacity = run_time * (ideal_rate_per_min or 0.0)
    performance = min(total / ideal_capacity, 1.0) if ideal_capacity > 0 else 0.0
    quality = (good / total) if total > 0 else 0.0
    oee = availability * performance * quality

    return {"line": line, "t1": t1.isoformat(), "t2": t2.isoformat(),
            "window_min": round(window_min, 2), "downtime_min": round(down, 2),
            "run_time_min": round(run_time, 2), "ideal_rate_per_min": ideal_rate_per_min,
            "good": good, "reject": reject, "total": total,
            "availability": round(availability, 4), "performance": round(performance, 4),
            "quality": round(quality, 4), "oee": round(oee, 4)}


def record_count_event(db: Session, payload: dict, user: User) -> OeeCountEvent:
    require_role(user, Role.OPERATOR, Role.SUPERVISOR, Role.ENGINEER)
    if float(payload.get("qty", 0) or 0) < 0:
        raise DomainError("Số lượng không được âm.")
    ev = OeeCountEvent(event_id=new_id(), line=payload["line"], ts=payload.get("ts") or utcnow(),
                       qty=float(payload.get("qty", 0) or 0), source=payload.get("source", "manual"),
                       note=payload.get("note"), recorded_by=user.username, recorded_at=utcnow())
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


def record_reject_event(db: Session, payload: dict, user: User) -> OeeRejectEvent:
    require_role(user, Role.OPERATOR, Role.SUPERVISOR, Role.ENGINEER)
    if float(payload.get("qty", 0) or 0) < 0:
        raise DomainError("Số lượng không được âm.")
    ev = OeeRejectEvent(event_id=new_id(), line=payload["line"], ts=payload.get("ts") or utcnow(),
                        qty=float(payload.get("qty", 0) or 0), reason=payload.get("reason"),
                        source=payload.get("source", "manual"), recorded_by=user.username, recorded_at=utcnow())
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev
