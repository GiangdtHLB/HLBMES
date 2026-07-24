"""Báo cáo sản lượng chiết KEG lấy trực tiếp từ CSDL SCADA ngoài đã khai báo ở Tích hợp
(SqlConnection.purpose="filling_keg") — bảng Donggoi (Recordtime, L1_Good_Real..L4_Good_Real)
của 4 dây chiết keg. Chỉ đọc (SELECT).

Bảng Donggoi có 3 bộ cột số keg khác nhau (GoodKeg_M1..M4 theo máy, GoodKeg_Line1..4 theo dây
chuyền, L1_Good_Real..L4_Good_Real theo dây chuyền) — theo xác nhận thực tế, CHỈ
L1_Good_Real..L4_Good_Real là bộ đếm lũy kế đúng cho 4 line chiết (GoodKeg_Line1..4 có dấu
hiệu bị reset định kỳ, giá trị giảm giữa 2 lần lấy mẫu — không dùng được cho tính lũy kế).

Sản lượng trong 1 khoảng = tổng (giá trị lũy kế mỗi line tại mốc cuối khoảng trừ giá trị lũy kế
tại mốc đầu khoảng), cộng dồn cả 4 line. Vì cả 4 cột nằm cùng 1 dòng (đọc đồng thời tại cùng
Recordtime), chỉ cần chọn ĐÚNG 1 dòng gần mốc ranh giới ca nhất rồi cộng cả 4 cột của dòng đó —
không cần xử lý riêng từng line như báo cáo điện (nhiều LocalID trên nhiều dòng khác nhau).

Tái dùng đúng kỹ thuật "mốc ranh giới ca + giá trị gần nhất, fetch 1 lần" đã xây cho báo cáo
chiết lon (xem filling_external.shift_boundaries/nearest_value)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import MetaData, Table, create_engine, select
from sqlalchemy.orm import Session

from ..errors import DomainError
from . import integration_connection as sqlconn_svc

KEG_PURPOSE = "filling_keg"
KEG_TABLE = "Donggoi"
KEG_LINE_COLUMNS = ["L1_Good_Real", "L2_Good_Real", "L3_Good_Real", "L4_Good_Real"]


def _get_keg_connection(db: Session):
    conn = sqlconn_svc.get_connection_by_purpose(db, KEG_PURPOSE)
    if not conn:
        raise DomainError(
            "Chưa có kết nối SQL nào được gán \"Dùng cho: Chiết (keg)\" — "
            "vào Tích hợp › Kết nối CSDL để gán."
        )
    return conn


LINE_LABELS = {"L1_Good_Real": "Line 1", "L2_Good_Real": "Line 2",
               "L3_Good_Real": "Line 3", "L4_Good_Real": "Line 4"}


def aggregate_keg_values(raw_rows: list, boundaries: list) -> dict:
    """Phần logic thuần (không cần CSDL) — raw_rows=[(recordtime, l1, l2, l3, l4), ...] (đã
    fetch 1 lần, gộp cả trước/trong/sau khoảng). Mỗi dòng cộng 4 cột line thành 1 giá trị lũy
    kế tổng tại thời điểm đó, rồi chọn giá trị gần mỗi mốc ranh giới ca nhất (LOCF — không vượt
    mốc). Tách riêng để unit test độc lập, giống aggregate_ca_values() ở energy_external.py.

    Ngoài tổng chung (by_ca/by_day/shifts), còn tính riêng theo TỪNG LINE (by_line) — vì 4 cột
    L1..L4 nằm cùng dòng/cùng Recordtime, mốc được chọn (gần nhất, không vượt mốc) giống hệt
    nhau cho cả 4 line và tổng — chỉ khác giá trị đọc tại mốc đó.

    Nếu 1 mốc ca rơi vào khoảng trống dữ liệu lớn (xem cảnh báo trong filling_external.py), ca
    đó trả "kegs": None kèm cờ "data_gap": True (áp dụng như nhau cho cả tổng lẫn từng line, vì
    cùng chia sẻ đúng 1 tập Recordtime) thay vì hiển thị số bịa."""
    from .filling_external import ca_number, reliable_at_boundaries, values_at_boundaries

    n_shifts = len(boundaries) - 1

    candidates = [(r[0], sum(v or 0 for v in r[1:])) for r in raw_rows]
    values = values_at_boundaries(candidates, boundaries)
    reliable = reliable_at_boundaries(candidates, boundaries)

    shifts = []
    for i in range(n_shifts):
        start, end = boundaries[i], boundaries[i + 1]
        ok = reliable[i] and reliable[i + 1]
        kegs = round(max(values[i + 1] - values[i], 0.0)) if ok else None
        shifts.append({
            "date": start.date().isoformat(), "ca": ca_number(start),
            "start": start.isoformat(), "end": end.isoformat(),
            "kegs": kegs, "data_gap": not ok,
        })

    by_ca_agg: dict = {1: 0.0, 2: 0.0, 3: 0.0}
    by_ca_gap: dict = {1: False, 2: False, 3: False}
    for s in shifts:
        if s["kegs"] is not None:
            by_ca_agg[s["ca"]] += s["kegs"]
        if s["data_gap"]:
            by_ca_gap[s["ca"]] = True
    by_ca = [{"ca": k, "label": f"Ca {k}", "value": round(v), "data_gap": by_ca_gap[k]}
             for k, v in sorted(by_ca_agg.items())]

    by_day_agg: dict = {}
    by_day_gap: dict = {}
    for s in shifts:
        d = s["date"]
        by_day_agg.setdefault(d, {1: 0, 2: 0, 3: 0})
        by_day_gap.setdefault(d, {1: False, 2: False, 3: False})
        if s["kegs"] is not None:
            by_day_agg[d][s["ca"]] = s["kegs"]
        by_day_gap[d][s["ca"]] = s["data_gap"]
    by_day = [{"date": d, "ca1": v[1], "ca2": v[2], "ca3": v[3], "has_gap": any(by_day_gap[d].values())}
              for d, v in sorted(by_day_agg.items())]

    total_kegs = sum(s["kegs"] for s in shifts if s["kegs"] is not None)
    has_gap = any(s["data_gap"] for s in shifts)

    by_line = []
    for col_idx, col_name in enumerate(KEG_LINE_COLUMNS, start=1):
        line_candidates = [(r[0], r[col_idx]) for r in raw_rows]
        line_values = values_at_boundaries(line_candidates, boundaries)
        ca_agg: dict = {1: 0.0, 2: 0.0, 3: 0.0}
        for i in range(n_shifts):
            if not (reliable[i] and reliable[i + 1]):
                continue
            start = boundaries[i]
            kegs = max(line_values[i + 1] - line_values[i], 0.0)
            ca_agg[ca_number(start)] += kegs
        by_line.append({
            "line": col_name, "label": LINE_LABELS.get(col_name, col_name),
            "ca1": round(ca_agg[1]), "ca2": round(ca_agg[2]), "ca3": round(ca_agg[3]),
            "total": round(sum(ca_agg.values())), "has_gap": has_gap,
        })

    return {
        "total_kegs": round(total_kegs),
        "has_gap": has_gap,
        "by_ca": by_ca, "by_day": by_day, "shifts": shifts, "by_line": by_line,
    }


def keg_report(db: Session, date_from: datetime, date_to: datetime) -> dict:
    from .filling_external import shift_boundaries

    conn = _get_keg_connection(db)
    engine = create_engine(sqlconn_svc._build_url(conn), connect_args={"timeout": 4}, pool_pre_ping=False)
    boundaries = shift_boundaries(date_from, date_to)
    try:
        with sqlconn_svc.safe_query(conn.name):
            metadata = MetaData()
            tbl = Table(KEG_TABLE, metadata, autoload_with=engine)
            cols = [tbl.c.Recordtime] + [tbl.c[c] for c in KEG_LINE_COLUMNS]
            with engine.connect() as db_conn:
                before_first = db_conn.execute(
                    select(*cols).where(tbl.c.Recordtime <= boundaries[0])
                    .order_by(tbl.c.Recordtime.desc()).limit(1)
                ).first()
                in_range = db_conn.execute(
                    select(*cols)
                    .where(tbl.c.Recordtime > boundaries[0], tbl.c.Recordtime <= boundaries[-1])
                    .order_by(tbl.c.Recordtime)
                ).all()
                after_last = db_conn.execute(
                    select(*cols).where(tbl.c.Recordtime > boundaries[-1])
                    .order_by(tbl.c.Recordtime.asc()).limit(1)
                ).first()
    finally:
        engine.dispose()

    raw_rows = [r for r in ([before_first] + list(in_range) + [after_last]) if r is not None]
    result = aggregate_keg_values(raw_rows, boundaries)
    result.update({"date_from": date_from.isoformat(), "date_to": date_to.isoformat(),
                   "connection_name": conn.name})
    return result


def data_bounds(db: Session) -> dict:
    """Ngày nhỏ nhất/lớn nhất thật có trong bảng Donggoi — dùng làm mặc định khoảng ngày báo
    cáo, vì dữ liệu SCADA export có thể đã dừng từ lâu (không còn cập nhật tới hiện tại)."""
    from sqlalchemy import func

    conn = _get_keg_connection(db)
    engine = create_engine(sqlconn_svc._build_url(conn), connect_args={"timeout": 4}, pool_pre_ping=False)
    try:
        with sqlconn_svc.safe_query(conn.name):
            metadata = MetaData()
            tbl = Table(KEG_TABLE, metadata, autoload_with=engine)
            with engine.connect() as db_conn:
                min_dt, max_dt = db_conn.execute(
                    select(func.min(tbl.c.Recordtime), func.max(tbl.c.Recordtime))
                ).one()
            return {
                "min_date": min_dt.date().isoformat() if min_dt else None,
                "max_date": max_dt.date().isoformat() if max_dt else None,
            }
    finally:
        engine.dispose()
