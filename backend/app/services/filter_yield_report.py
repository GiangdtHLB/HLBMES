"""Báo cáo sản lượng lọc theo mẻ — phân loại mỗi mẻ lọc (FilterRecord) ĐÃ KẾT THÚC (ended_at
khác None) thành Thấp/Bình thường/Cao dựa trên V bia/hl (v_beer_hl) so với 2 ngưỡng cấu hình
ở OpsSetting (filter_yield_low_hl/filter_yield_high_hl, xem Cài đặt vận hành). Gộp theo
ngày/tuần/tháng (group_by) trong khoảng filter_date để vận hành/QLSX xem nhanh mẻ nào đạt/chưa
đạt và cảnh báo sớm khi có mẻ Thấp."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.brewing import FermentRecord, FilterOrderTank, FilterRecord

LABEL = {"thap": "Thấp", "binh_thuong": "Bình thường", "cao": "Cao", "cuoi": "Mẻ cuối (không tính)"}


def classify_yield(v_beer_hl: float, low_hl: float, high_hl: float) -> str:
    if v_beer_hl <= low_hl:
        return "thap"
    if v_beer_hl <= high_hl:
        return "binh_thuong"
    return "cao"


def _period_key(dt: datetime, group_by: str) -> str:
    if group_by == "month":
        return dt.strftime("%Y-%m")
    if group_by == "week":
        year, week, _ = dt.isocalendar()
        return f"{year}-W{week:02d}"
    return dt.strftime("%Y-%m-%d")


def filter_yield_report(db: Session, date_from: datetime, date_to: datetime,
                        low_hl: float, high_hl: float, group_by: str = "day") -> dict:
    records = db.execute(
        select(FilterRecord)
        .where(FilterRecord.ended_at.is_not(None),
               FilterRecord.filter_date >= date_from, FilterRecord.filter_date < date_to)
        .order_by(FilterRecord.filter_date)
    ).scalars().all()

    items = []
    periods: dict[str, dict[str, int]] = {}
    for f in records:
        cls = classify_yield(f.v_beer_hl or 0.0, low_hl, high_hl)
        period = _period_key(f.filter_date, group_by)
        items.append({
            "filter_id": f.filter_id, "filter_code": f.filter_code,
            "batch_number": f.batch_number, "order_number": f.order_number,
            "filter_date": f.filter_date.isoformat(), "ended_at": f.ended_at.isoformat(),
            "v_beer_hl": f.v_beer_hl, "classification": cls, "classification_label": LABEL[cls],
            "period": period,
        })
        p = periods.setdefault(period, {"thap": 0, "binh_thuong": 0, "cao": 0, "total": 0})
        p[cls] += 1
        p["total"] += 1

    series = [{"period": p, **counts} for p, counts in sorted(periods.items())]
    low_count = sum(1 for it in items if it["classification"] == "thap")

    return {
        "date_from": date_from.isoformat(), "date_to": date_to.isoformat(), "group_by": group_by,
        "low_hl": low_hl, "high_hl": high_hl,
        "total": len(items), "low_count": low_count, "has_warning": low_count > 0,
        "series": series, "items": items,
    }


def classify_yield_l(v_l: float, low_l: float, high_l: float) -> str:
    if v_l <= low_l:
        return "thap"
    if v_l <= high_l:
        return "binh_thuong"
    return "cao"


def _join_distinct(values: list) -> str | None:
    seen = []
    for v in values:
        if v and v not in seen:
            seen.append(v)
    return " + ".join(seen) if seen else None


def filter_line_yield_report(db: Session, date_from: datetime, date_to: datetime,
                             low_l: float, high_l: float) -> dict:
    """Báo cáo theo "mẻ lọc số" (FilterOrderTank, 1 đợt rút dịch riêng — xem
    add_filter_tank_batch) đã kết thúc, kèm truy vết tank lên men/mẻ nấu/ngày vào dịch nguồn
    (chỉ có với dòng tank_type="cct"; dòng "bbt" là lọc lại từ tank thành phẩm khác nên không
    có tank lên men/mẻ nấu riêng — hiển thị mã tank BBT nguồn thay thế).

    GỘP các dòng CÙNG bộ 3 giá trị (batch_number, order_number, batch_seq_no) — vì batch_number/
    order_number KHÔNG còn kiểm tra trùng giữa các lệnh lọc khác nhau (xem finish_filter_tank),
    1 mẻ lọc thật có thể bị tách ghi nhận trên nhiều FilterOrderTank/FilterRecord khác nhau (VD
    lọc phối tách nhiều tank BBT/lệnh lọc) — phải cộng dồn thể tích các dòng đó lại thành 1 dòng
    báo cáo mới đúng sản lượng thật. Chỉ gộp khi CẢ 3 giá trị đều có (không rỗng) để tránh gộp
    nhầm các dòng chưa điền gì lại với nhau. Dòng/nhóm có is_final_batch=True (đợt rút CUỐI, xem
    toggle_final_batch) bị loại khỏi phân loại Thấp/Cao (classification="cuoi") để không báo
    động giả cho phần "vét" tank sản lượng thấp bình thường."""
    lines = db.execute(
        select(FilterOrderTank)
        .where(FilterOrderTank.ended_at.is_not(None), FilterOrderTank.filter_id.is_not(None),
               FilterOrderTank.ended_at >= date_from, FilterOrderTank.ended_at < date_to)
        .order_by(FilterOrderTank.ended_at)
    ).scalars().all()

    filter_ids = {l.filter_id for l in lines}
    filters_by_id = {f.filter_id: f for f in db.execute(
        select(FilterRecord).where(FilterRecord.filter_id.in_(filter_ids))).scalars().all()} if filter_ids else {}
    ferment_ids = {l.ferment_id for l in lines if l.ferment_id}
    ferments_by_id = {f.ferment_id: f for f in db.execute(
        select(FermentRecord).where(FermentRecord.ferment_id.in_(ferment_ids))).scalars().all()} if ferment_ids else {}

    groups: dict = {}
    order = []
    for l in lines:
        f = filters_by_id.get(l.filter_id)
        ferment = ferments_by_id.get(l.ferment_id) if l.ferment_id else None
        batch_number = f.batch_number if f else None
        order_number = f.order_number if f else None
        if batch_number and order_number and l.batch_seq_no:
            key = ("merged", batch_number, order_number, l.batch_seq_no)
        else:
            key = ("solo", l.line_id)
        g = groups.get(key)
        if not g:
            g = {"batch_seq_no": l.batch_seq_no, "filter_ids": [], "filter_codes": [],
                "beer_types": [], "filter_dates": [], "tank_lms": [], "brew_codes": [],
                "brew_dates": [], "source_bbt_codes": [], "ended_ats": [],
                "v_dich_l": 0.0, "v_daw_l": 0.0, "is_final": False}
            groups[key] = g
            order.append(key)
        g["filter_ids"].append(l.filter_id)
        g["filter_codes"].append(f.filter_code if f else None)
        g["beer_types"].append(f.beer_type if f else None)
        g["filter_dates"].append(f.filter_date if f and f.filter_date else None)
        g["tank_lms"].append(ferment.tank_lm if ferment else (f"BBT {l.source_bbt_code} (lọc lại)" if l.tank_type == "bbt" else None))
        g["brew_codes"].append(ferment.brew_code if ferment else None)
        g["brew_dates"].append(ferment.brew_date if ferment and ferment.brew_date else None)
        g["source_bbt_codes"].append(l.source_bbt_code)
        g["ended_ats"].append(l.ended_at)
        g["v_dich_l"] += (l.v_dich_hl or 0.0) * 100
        g["v_daw_l"] += (l.nuoc_bai_khi_hl or 0.0) * 100
        g["is_final"] = g["is_final"] or l.is_final_batch

    items = []
    for key in order:
        g = groups[key]
        v_l = g["v_dich_l"] + g["v_daw_l"]
        cls = "cuoi" if g["is_final"] else classify_yield_l(v_l, low_l, high_l)
        filter_dates = [d for d in g["filter_dates"] if d]
        brew_dates = [d for d in g["brew_dates"] if d]
        ended_ats = [d for d in g["ended_ats"] if d]
        items.append({
            "batch_seq_no": g["batch_seq_no"],
            "filter_id": g["filter_ids"][0], "filter_code": _join_distinct(g["filter_codes"]),
            "beer_type": _join_distinct(g["beer_types"]),
            "filter_date": min(filter_dates).isoformat() if filter_dates else None,
            "tank_lm": _join_distinct(g["tank_lms"]),
            "brew_code": _join_distinct(g["brew_codes"]),
            "brew_date": min(brew_dates).isoformat() if brew_dates else None,
            "source_bbt_code": _join_distinct(g["source_bbt_codes"]),
            "ended_at": max(ended_ats).isoformat() if ended_ats else None,
            "is_final_batch": g["is_final"],
            "v_dich_l": round(g["v_dich_l"], 1), "v_daw_l": round(g["v_daw_l"], 1),
            "v_l": round(v_l, 1), "classification": cls, "classification_label": LABEL[cls],
        })

    low_count = sum(1 for it in items if it["classification"] == "thap")
    return {
        "date_from": date_from.isoformat(), "date_to": date_to.isoformat(),
        "low_l": low_l, "high_l": high_l,
        "total": len(items), "low_count": low_count, "has_warning": low_count > 0,
        "items": items,
    }
