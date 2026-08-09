"""Đếm số lần dừng lắt nhắt theo tuần/ca cho từng nguyên nhân cố định — mirror sheet MS&SL
(Minor Stop & Speed Loss Weekly Report) của file "OPI - CAN L3 (KHS 30K).xlsx". Đây là bảng đếm
SỐ LẦN xảy ra (không phải phút) — khác hẳn "Dừng lắt nhắt" ở services/oee_waterfall.py (phút
RESIDUAL không giải trình được bằng lý do cụ thể nào)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..common import Role, new_id, utcnow
from ..errors import DomainError, NotFoundError
from ..models.oee_ext import OeeMinorStopTally, OeeReasonCatalog
from ..security import User, require_role


def upsert_tally(db: Session, reason_id: str, iso_year: int, iso_week: int, shift: str,
                 count: int, user: User) -> OeeMinorStopTally:
    require_role(user, Role.OPERATOR, Role.SUPERVISOR, Role.ENGINEER)
    reason = db.get(OeeReasonCatalog, reason_id)
    if not reason:
        raise NotFoundError("Lý do dừng lắt nhắt không tồn tại.")
    if reason.category != "dung_lat_nhat":
        raise DomainError(f"Lý do '{reason.sub_label}' không thuộc nhóm Dừng lắt nhắt.")
    if count < 0:
        raise DomainError("Số lần không được âm.")
    row = db.execute(select(OeeMinorStopTally).where(
        OeeMinorStopTally.reason_id == reason_id, OeeMinorStopTally.iso_year == iso_year,
        OeeMinorStopTally.iso_week == iso_week, OeeMinorStopTally.shift == shift)).scalar_one_or_none()
    if row:
        row.count = count
        row.updated_by = user.username
        row.updated_at = utcnow()
    else:
        row = OeeMinorStopTally(tally_id=new_id(), reason_id=reason_id, iso_year=iso_year,
                                iso_week=iso_week, shift=shift, count=count,
                                updated_by=user.username, updated_at=utcnow())
        db.add(row)
    db.commit()
    db.refresh(row)
    return row


def weekly_grid(db: Session, line_code: str, iso_year: int) -> dict:
    """Bảng lưới lý do × tuần (giống MS&SL) + tổng lũy kế cho 1 năm."""
    # sub_code="tong_dung" là dòng target TỔNG (dùng ở oee_waterfall.opi_summary), không phải 1
    # lý do lắt nhắt đếm được — loại khỏi lưới MS&SL.
    reasons = db.execute(select(OeeReasonCatalog).where(
        OeeReasonCatalog.line_code == line_code, OeeReasonCatalog.category == "dung_lat_nhat",
        OeeReasonCatalog.sub_code != "tong_dung", OeeReasonCatalog.active == True)  # noqa: E712
        .order_by(OeeReasonCatalog.sort_order)).scalars().all()
    tallies = db.execute(select(OeeMinorStopTally).join(
        OeeReasonCatalog, OeeMinorStopTally.reason_id == OeeReasonCatalog.reason_id).where(
        OeeReasonCatalog.line_code == line_code, OeeMinorStopTally.iso_year == iso_year)).scalars().all()
    by_reason = {}
    for t in tallies:
        by_reason.setdefault(t.reason_id, []).append(t)
    rows = []
    for r in reasons:
        entries = by_reason.get(r.reason_id, [])
        total = sum(t.count for t in entries)
        rows.append({"reason_id": r.reason_id, "sub_label": r.sub_label, "total": total,
                    "by_week": [{"iso_week": t.iso_week, "shift": t.shift, "count": t.count} for t in entries]})
    return {"line_code": line_code, "iso_year": iso_year, "rows": rows}


def weekly_pareto(db: Session, line_code: str, iso_year: int) -> dict:
    """Pareto tổng lũy kế cả năm — xếp hạng giảm dần theo tổng số lần."""
    grid = weekly_grid(db, line_code, iso_year)
    items = sorted(({"sub_label": r["sub_label"], "count": r["total"]} for r in grid["rows"]),
                   key=lambda x: x["count"], reverse=True)
    total = sum(i["count"] for i in items)
    denom = total or 1
    cum = 0
    for it in items:
        cum += it["count"]
        it["pct"] = round(it["count"] / denom * 100, 1)
        it["cum_pct"] = round(cum / denom * 100, 1)
    return {"line_code": line_code, "iso_year": iso_year, "total_count": total, "items": items}
