"""Báo cáo điện (AED) lấy trực tiếp từ CSDL SCADA/WinCC bên ngoài đã khai báo ở Tích hợp
(SqlConnection.purpose — xem SITE_PURPOSE bên dưới, mỗi nhà máy 1 token riêng để hỗ trợ NHIỀU
nhà máy cùng lúc) — bảng Energy (Recordtime, LocalID, AED, Water, Steam, CO2) join với NameSys
(LocalID -> LocalName) để lấy tên hệ thống/trạm. Chỉ đọc (SELECT).

QUAN TRỌNG — AED là bộ đếm cộng dồn (cumulative totalizer), KHÔNG phải giá trị tăng thêm mỗi
lần lấy mẫu: xác nhận bằng dữ liệu thật (VD LocalID=14 tăng dần đều ~3.17 triệu → ~3.24 triệu
qua 26 ngày), và thỉnh thoảng có mẫu lỗi/giật về 0 (SCADA glitch, không phải reset thật — các
giá trị 0 nằm rải rác giữa ngày, không phải lúc 0h). Vì vậy:
  - Sản lượng tiêu thụ trong kỳ = MAX(AED tính đến cuối kỳ) − MAX(AED tính đến trước đầu kỳ)
    (dùng MAX thay vì giá trị cuối cùng/MIN để tự loại bỏ các mẫu lỗi giật về 0). Đây đúng là
    "điện tại thời điểm đến ngày trừ điện tại thời điểm từ ngày" — date_from/date_to nhận cả
    giờ:phút (datetime) để lọc chính xác theo yêu cầu, không chỉ theo ngày.
  - Chuỗi theo ngày = lấy MAX(AED) mỗi ngày rồi lấy hiệu số ngày liền kề (kẹp về 0 nếu âm do
    mẫu lỗi), cộng dồn lên tháng nếu group_by=month. Vì MAX chạy theo kỳ chỉ tăng (không giảm),
    tổng các hiệu số ngày này LUÔN bằng đúng công thức tổng "cuối kỳ trừ đầu kỳ" ở trên (tổng
    kính, không lệch) — chuỗi ngày chỉ là cách chia nhỏ tổng đó ra để vẽ biểu đồ xu hướng.
Aggregate SQL-side (MAX/GROUP BY) vì bảng Energy có hàng triệu dòng — không kéo raw rows.

Hai nhóm LocalID (phân loại theo tên trong NameSys, không hardcode ID để không phụ thuộc dữ
liệu 1 nhà máy cụ thể):
  - "hệ thống tiêu thụ": các LocalName KHÔNG chứa "Trạm"/"Máy phát" (VD Máy nén khí, Lò hơi...)
  - "trạm/máy phát": LocalName chứa "Trạm" hoặc "Máy phát" (đo điện đầu vào/nguồn cấp)
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Date, MetaData, Table, create_engine, func, select
from sqlalchemy.orm import Session

from ..errors import DomainError
from . import integration_connection as sqlconn_svc

ENERGY_PURPOSE = "energy"
# Nhiều nhà máy (site) có thể cùng khai báo bảng Energy/NameSys ở CSDL riêng — mỗi site 1
# purpose token riêng để get_connection_by_purpose() không bị nhập nhằng giữa 2 kết nối cùng
# gán "energy" (xem services/integration_connection.py::get_connection_by_purpose — so khớp
# CHÍNH XÁC 1 token trong CSV purpose, không phải substring). "hl" giữ nguyên token "energy"
# cũ để không phá vỡ cấu hình/kết nối đã gán từ trước.
SITE_PURPOSE = {"hl": "energy", "dm": "energy_dm"}
SITE_LABELS = {"hl": "Hạ Long", "dm": "Đông Mai"}
_STATION_MARKERS = ("Trạm", "Máy phát")


def _is_station(name: str) -> bool:
    return any(m in name for m in _STATION_MARKERS)


def compute_daily_diffs(baseline: dict, daily_rows: list) -> dict:
    """Hiệu số ngày liền kề mỗi hệ, kẹp về 0 nếu âm — tránh mẫu lỗi SCADA giật giá trị AED
    về 0 (không phải reset thật) làm sản lượng tính ra âm. Tách riêng khỏi truy vấn SQL để
    unit test được thuần logic (không cần CSDL thật).
    baseline: {local_id: giá trị AED gần nhất TRƯỚC kỳ báo cáo}
    daily_rows: [(local_id, day_iso, day_max_aed), ...] đã sắp theo ngày tăng dần mỗi local_id
    Trả về {(local_id, day_iso): tiêu thụ ngày đó}."""
    daily_diff: dict = {}
    last_known: dict = dict(baseline)
    for local_id, day_iso, day_max in daily_rows:
        day_max = float(day_max or 0)
        prev = last_known.get(local_id, 0.0)
        diff = max(day_max - prev, 0.0)
        daily_diff[(local_id, day_iso)] = diff
        last_known[local_id] = max(day_max, prev)
    return daily_diff


def _get_energy_connection(db: Session, site: str = "hl"):
    purpose = SITE_PURPOSE.get(site)
    if not purpose:
        raise DomainError(f"Nhà máy không hợp lệ: '{site}' (chỉ hỗ trợ: {', '.join(SITE_PURPOSE)}).")
    conn = sqlconn_svc.get_connection_by_purpose(db, purpose)
    if not conn:
        label = SITE_LABELS.get(site, site)
        raise DomainError(
            f"Chưa có kết nối SQL nào được gán \"Dùng cho: Năng lượng — {label}\" — "
            f"vào Tích hợp › Kết nối CSDL để gán (purpose=\"{purpose}\")."
        )
    return conn


def electricity_report(db: Session, date_from: datetime, date_to: datetime, group_by: str = "day",
                       site: str = "hl") -> dict:
    conn = _get_energy_connection(db, site)
    engine = create_engine(sqlconn_svc._build_url(conn), connect_args={"timeout": 20}, pool_pre_ping=False)
    try:
        with sqlconn_svc.safe_query(conn.name):
            metadata = MetaData()
            energy_tbl = Table("Energy", metadata, autoload_with=engine)
            namesys_tbl = Table("NameSys", metadata, autoload_with=engine)
            day_col = func.cast(energy_tbl.c.Recordtime, Date)

            with engine.connect() as db_conn:
                name_rows = db_conn.execute(select(namesys_tbl)).mappings().all()
                names = {r["LocalID"]: r["LocalName"].strip() for r in name_rows}

                baseline_rows = db_conn.execute(
                    select(energy_tbl.c.LocalID, func.max(energy_tbl.c.AED))
                    .where(energy_tbl.c.Recordtime < date_from)
                    .group_by(energy_tbl.c.LocalID)
                ).all()
                baseline = {lid: float(v or 0) for lid, v in baseline_rows}

                daily_rows = db_conn.execute(
                    select(energy_tbl.c.LocalID, day_col.label("day"), func.max(energy_tbl.c.AED).label("day_max"))
                    .where(energy_tbl.c.Recordtime >= date_from, energy_tbl.c.Recordtime < date_to)
                    .group_by(energy_tbl.c.LocalID, day_col)
                    .order_by(energy_tbl.c.LocalID, day_col)
                ).all()
    finally:
        engine.dispose()

    daily_rows_iso = [
        (local_id, day_val.isoformat() if hasattr(day_val, "isoformat") else str(day_val), day_max)
        for local_id, day_val, day_max in daily_rows
    ]
    daily_diff = compute_daily_diffs(baseline, daily_rows_iso)

    def _period_key(day_iso: str) -> str:
        return day_iso[:7] if group_by == "month" else day_iso

    system_by_id: dict[int, float] = {}
    station_by_id: dict[int, float] = {}
    series_system: dict[tuple, float] = {}
    periods_set = set()

    for (local_id, day_iso), diff in daily_diff.items():
        name = names.get(local_id, str(local_id))
        period = _period_key(day_iso)
        periods_set.add(period)
        if _is_station(name):
            station_by_id[local_id] = station_by_id.get(local_id, 0.0) + diff
        else:
            system_by_id[local_id] = system_by_id.get(local_id, 0.0) + diff
            key = (period, local_id)
            series_system[key] = series_system.get(key, 0.0) + diff

    def _rows(agg: dict) -> list:
        out = [{"local_id": lid, "name": names.get(lid, str(lid)), "value": round(v, 2)}
               for lid, v in agg.items()]
        return sorted(out, key=lambda x: -x["value"])

    by_system = _rows(system_by_id)
    by_station = _rows(station_by_id)
    periods = sorted(periods_set)
    system_ids_sorted = [r["local_id"] for r in by_system]

    series = sorted(
        [{"period": p, "local_id": lid, "name": names.get(lid, str(lid)), "value": round(v, 2)}
         for (p, lid), v in series_system.items()],
        key=lambda x: (x["period"], x["local_id"]),
    )

    return {
        "date_from": date_from.isoformat(), "date_to": date_to.isoformat(), "group_by": group_by,
        "connection_name": conn.name,
        "total_system": round(sum(system_by_id.values()), 2),
        "total_station": round(sum(station_by_id.values()), 2),
        "by_system": by_system, "by_station": by_station,
        "periods": periods, "system_ids": system_ids_sorted, "series": series,
    }


def electricity_ca_report(db: Session, date_from: datetime, date_to: datetime, site: str = "hl") -> dict:
    """Điện tiêu thụ theo ca (Ca 1 06h-14h, Ca 2 14h-22h, Ca 3 22h-06h qua ngày) trong
    [date_from, date_to] — tái dùng đúng kỹ thuật "mốc ranh giới + giá trị gần nhất, fetch
    1 lần" đã xây cho báo cáo chiết lon (xem filling_external.shift_boundaries/nearest_value),
    áp dụng cho TỪNG LocalID "hệ thống tiêu thụ" (không tính trạm/máy phát — khớp với
    "TỔNG AED TIÊU THỤ TÍNH THEO HỆ THỐNG" ở báo cáo theo ngày/tháng hiện có).

    Có nhiều LocalID (không phải 1 dòng như chiết lon) nên "bản ghi trước/sau mốc gần nhất"
    phải lấy RIÊNG cho từng LocalID — dùng ROW_NUMBER() OVER (PARTITION BY LocalID ...) để
    lấy trong ĐÚNG 1 truy vấn mỗi chiều (trước/sau), không phải N truy vấn theo số LocalID."""
    from .filling_external import shift_boundaries

    conn = _get_energy_connection(db, site)
    engine = create_engine(sqlconn_svc._build_url(conn), connect_args={"timeout": 20}, pool_pre_ping=False)
    boundaries = shift_boundaries(date_from, date_to)
    try:
        with sqlconn_svc.safe_query(conn.name):
            metadata = MetaData()
            energy_tbl = Table("Energy", metadata, autoload_with=engine)
            namesys_tbl = Table("NameSys", metadata, autoload_with=engine)
            with engine.connect() as db_conn:
                name_rows = db_conn.execute(select(namesys_tbl)).mappings().all()
                names = {r["LocalID"]: r["LocalName"].strip() for r in name_rows}

                rn_before = func.row_number().over(
                    partition_by=energy_tbl.c.LocalID, order_by=energy_tbl.c.Recordtime.desc()
                ).label("rn")
                before_sq = select(
                    energy_tbl.c.LocalID, energy_tbl.c.Recordtime, energy_tbl.c.AED, rn_before
                ).where(energy_tbl.c.Recordtime <= boundaries[0]).subquery()
                before_rows = db_conn.execute(
                    select(before_sq.c.LocalID, before_sq.c.Recordtime, before_sq.c.AED)
                    .where(before_sq.c.rn == 1)
                ).all()

                rn_after = func.row_number().over(
                    partition_by=energy_tbl.c.LocalID, order_by=energy_tbl.c.Recordtime.asc()
                ).label("rn")
                after_sq = select(
                    energy_tbl.c.LocalID, energy_tbl.c.Recordtime, energy_tbl.c.AED, rn_after
                ).where(energy_tbl.c.Recordtime > boundaries[-1]).subquery()
                after_rows = db_conn.execute(
                    select(after_sq.c.LocalID, after_sq.c.Recordtime, after_sq.c.AED)
                    .where(after_sq.c.rn == 1)
                ).all()

                in_range_rows = db_conn.execute(
                    select(energy_tbl.c.LocalID, energy_tbl.c.Recordtime, energy_tbl.c.AED)
                    .where(energy_tbl.c.Recordtime > boundaries[0], energy_tbl.c.Recordtime <= boundaries[-1])
                    .order_by(energy_tbl.c.LocalID, energy_tbl.c.Recordtime)
                ).all()
    finally:
        engine.dispose()

    raw_rows = list(before_rows) + list(in_range_rows) + list(after_rows)
    result = aggregate_ca_values(raw_rows, names, boundaries)
    result.update({"date_from": date_from.isoformat(), "date_to": date_to.isoformat(),
                   "connection_name": conn.name})
    return result


def aggregate_ca_values(raw_rows: list, names: dict, boundaries: list) -> dict:
    """Phần logic thuần (không cần CSDL) của electricity_ca_report — gộp các bản ghi thô
    [(local_id, recordtime, aed), ...] (đã fetch 1 lần, gộp cả trước/trong/sau khoảng) thành
    tổng tiêu thụ theo ca, chỉ tính "hệ thống tiêu thụ" (loại trạm/máy phát). Tách riêng để
    unit test độc lập, giống compute_daily_diffs() ở trên.

    Nếu 1 LocalID có khoảng trống dữ liệu lớn quanh mốc ca (xem cảnh báo trong
    filling_external.py), LocalID đó bị BỎ QUA cho ca đó (không cộng số bịa vào tổng) và ca được
    đánh dấu "data_gap": True để biết tổng có thể bị thiếu — khác với báo cáo chiết lon/keg (1
    dòng dữ liệu duy nhất), ở đây tổng là CỘNG DỒN NHIỀU LocalID độc lập nên 1 LocalID bị gap
    không cần làm mất số của toàn bộ hệ thống khác."""
    from .filling_external import ca_number, reliable_at_boundaries, values_at_boundaries

    candidates_by_lid: dict = {}
    for lid, rt, aed in raw_rows:
        candidates_by_lid.setdefault(lid, []).append((rt, float(aed or 0)))

    system_cands = {
        lid: cands for lid, cands in candidates_by_lid.items()
        if not _is_station(names.get(lid, str(lid)))
    }
    values_by_lid = {lid: values_at_boundaries(cands, boundaries) for lid, cands in system_cands.items()}
    reliable_by_lid = {lid: reliable_at_boundaries(cands, boundaries) for lid, cands in system_cands.items()}

    n_shifts = len(boundaries) - 1
    shift_totals = [0.0] * n_shifts
    shift_gap = [False] * n_shifts
    for lid, values in values_by_lid.items():
        rel = reliable_by_lid[lid]
        for i in range(n_shifts):
            if rel[i] and rel[i + 1]:
                shift_totals[i] += max(values[i + 1] - values[i], 0.0)
            else:
                shift_gap[i] = True

    shifts = []
    for i in range(n_shifts):
        start, end = boundaries[i], boundaries[i + 1]
        shifts.append({
            "date": start.date().isoformat(), "ca": ca_number(start),
            "start": start.isoformat(), "end": end.isoformat(),
            "value": round(shift_totals[i], 2), "data_gap": shift_gap[i],
        })

    by_ca_agg: dict = {1: 0.0, 2: 0.0, 3: 0.0}
    by_ca_gap: dict = {1: False, 2: False, 3: False}
    for s in shifts:
        by_ca_agg[s["ca"]] += s["value"]
        if s["data_gap"]:
            by_ca_gap[s["ca"]] = True
    by_ca = [{"ca": k, "label": f"Ca {k}", "value": round(v, 2), "data_gap": by_ca_gap[k]}
             for k, v in sorted(by_ca_agg.items())]

    by_day_agg: dict = {}
    by_day_gap: dict = {}
    for s in shifts:
        d = s["date"]
        by_day_agg.setdefault(d, {1: 0.0, 2: 0.0, 3: 0.0})[s["ca"]] += s["value"]
        by_day_gap.setdefault(d, {1: False, 2: False, 3: False})[s["ca"]] = s["data_gap"]
    by_day = [{"date": d, "ca1": round(v[1], 2), "ca2": round(v[2], 2), "ca3": round(v[3], 2),
               "has_gap": any(by_day_gap[d].values())}
              for d, v in sorted(by_day_agg.items())]

    return {
        "total_kwh": round(sum(shift_totals), 2),
        "has_gap": any(shift_gap),
        "by_ca": by_ca, "by_day": by_day, "shifts": shifts,
    }


def data_bounds(db: Session, site: str = "hl") -> dict:
    """Ngày nhỏ nhất/lớn nhất thật có trong bảng Energy — dùng làm mặc định khoảng ngày báo
    cáo, vì dữ liệu SCADA export có thể đã dừng từ lâu (không còn cập nhật tới ngày hiện tại)."""
    conn = _get_energy_connection(db, site)
    engine = create_engine(sqlconn_svc._build_url(conn), connect_args={"timeout": 15}, pool_pre_ping=False)
    try:
        with sqlconn_svc.safe_query(conn.name):
            metadata = MetaData()
            energy_tbl = Table("Energy", metadata, autoload_with=engine)
            with engine.connect() as db_conn:
                min_dt, max_dt = db_conn.execute(
                    select(func.min(energy_tbl.c.Recordtime), func.max(energy_tbl.c.Recordtime))
                ).one()
            return {
                "min_date": min_dt.date().isoformat() if min_dt else None,
                "max_date": max_dt.date().isoformat() if max_dt else None,
            }
    finally:
        engine.dispose()
