"""Báo cáo sản lượng chiết (lon) lấy trực tiếp từ CSDL SCADA ngoài đã khai báo ở Tích hợp
(SqlConnection.purpose="filling") — bảng 30K_Report (Recordtime, TotalCanBySum, ...) của
dây chuyền chiết lon "30K". Chỉ đọc (SELECT).

TotalCanBySum là số lon lũy kế (cumulative totalizer, giống AED bên báo cáo năng lượng) — theo
xác nhận thực tế, đây mới là cột lũy kế đúng (TotalCan không tăng đều/đứng yên trong nhiều
giai đoạn dù dây chuyền vẫn chạy). Sản lượng trong 1 khoảng = giá trị lũy kế tại mốc cuối khoảng
trừ giá trị lũy kế tại mốc đầu khoảng.

Dữ liệu nguồn ghi khá dày (~5 phút/bản ghi) nhưng vẫn gần như không bao giờ trùng đúng giờ ranh
giới ca (06:00/14:00/22:00). Theo yêu cầu: nếu không có bản ghi đúng giờ đó, lấy bản ghi GẦN
NHẤT nhưng KHÔNG VƯỢT QUA mốc giờ đó (last-observation-carried-forward — CHỈ lấy bản ghi ở
TƯƠNG LAI khi hoàn toàn không có bản ghi nào trước mốc) — xem `nearest_value()`. Đây là ngữ
nghĩa đúng cho bộ đếm cộng dồn: giá trị "tại thời điểm T" luôn là giá trị lần đọc gần nhất
TRƯỚC T, không thể biết trước giá trị tương lai — nếu lấy bản ghi SAU mốc sẽ tính nhầm sản
lượng phát sinh sau ranh giới ca vào ca hiện tại. Vẫn kẹp hiệu số về 0 để phòng ngừa mẫu lỗi.

CẢNH BÁO KHOẢNG TRỐNG DỮ LIỆU LỚN — nếu CSDL nguồn từng ngừng ghi trong thời gian dài (VD nhiều
tháng, do PLC/lịch sử SCADA gián đoạn), LOCF sẽ phải "băng qua" khoảng trống đó, lấy 1 bản ghi
từ rất lâu trước mốc ranh giới làm giá trị so sánh — hiệu số ra sẽ SAI LỆCH RẤT LỚN (bộ đếm đã
tăng bao nhiêu trong suốt khoảng trống, ta không hề biết) chứ không phải sản lượng thật của ca
đó. `reliable_at_boundaries()` phát hiện trường hợp này: nếu bản ghi LOCF được chọn cách mốc
ranh giới quá `MAX_GAP_HOURS`, mốc đó được đánh dấu KHÔNG đáng tin — mọi ca dùng mốc đó phải trả
giá trị `None` (không đoán số) kèm cờ `data_gap`/`has_gap`, thay vì hiển thị 1 con số khổng lồ
vô nghĩa cho người dùng.

HIỆU NĂNG — chỉ fetch dữ liệu ĐÚNG 3 LẦN cho toàn bộ khoảng báo cáo (bản ghi trước mốc đầu +
mọi bản ghi nằm trong khoảng + bản ghi sau mốc cuối), rồi chọn "gần nhất" cho từng mốc ca hoàn
toàn trong Python. KHÔNG truy vấn riêng cho từng mốc ca — với khoảng ngày dài có hàng chục/trăm
mốc ca, mỗi truy vấn riêng là 1 round-trip mạng tới CSDL ngoài (thường qua WAN, độ trễ cao), làm
báo cáo chậm hẳn so với các báo cáo khác (VD năng lượng chỉ có 2 truy vấn tổng hợp).

Báo cáo theo 3 ca cố định mỗi ngày: Ca 1 06:00–14:00, Ca 2 14:00–22:00, Ca 3 22:00–06:00
(qua ngày hôm sau). Khoảng ngày người dùng chọn được LÀM TRÒN RA ranh giới ca gần nhất (không
cắt nửa ca) — vì báo cáo ca sản xuất luôn tính theo ca trọn vẹn, không theo phút lẻ.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import MetaData, Table, create_engine, func, select
from sqlalchemy.orm import Session

from ..errors import DomainError
from . import integration_connection as sqlconn_svc

FILLING_PURPOSE = "filling"
FILLING_TABLE = "30K_Report"
SHIFT_ANCHOR_HOUR = 6   # Ca 1 bắt đầu 06:00
SHIFT_LENGTH_HOURS = 8
MAX_GAP_HOURS = 48  # quá ngưỡng này, coi bản ghi LOCF là không đáng tin (xem cảnh báo ở đầu file)


def _get_filling_connection(db: Session):
    conn = sqlconn_svc.get_connection_by_purpose(db, FILLING_PURPOSE)
    if not conn:
        raise DomainError(
            "Chưa có kết nối SQL nào được gán \"Dùng cho: Chiết (đóng gói)\" — "
            "vào Tích hợp › Kết nối CSDL để gán."
        )
    return conn


def ca_number(dt: datetime) -> int:
    """Ca 1: 06h-14h, Ca 2: 14h-22h, Ca 3: 22h-06h — xác định theo giờ bắt đầu ca."""
    h = dt.hour
    if h == SHIFT_ANCHOR_HOUR:
        return 1
    if h == SHIFT_ANCHOR_HOUR + SHIFT_LENGTH_HOURS:
        return 2
    return 3


def shift_boundaries(date_from: datetime, date_to: datetime) -> list:
    """Danh sách mốc ranh giới ca (datetime) bao trọn [date_from, date_to] — mốc đầu <=
    date_from, mốc cuối >= date_to, cách nhau đúng 8 tiếng, neo tại giờ SHIFT_ANCHOR_HOUR.
    Thuần logic (không cần CSDL) để unit test độc lập."""
    anchor = date_from.replace(hour=SHIFT_ANCHOR_HOUR, minute=0, second=0, microsecond=0)
    while anchor > date_from:
        anchor -= timedelta(hours=SHIFT_LENGTH_HOURS)
    while anchor + timedelta(hours=SHIFT_LENGTH_HOURS) <= date_from:
        anchor += timedelta(hours=SHIFT_LENGTH_HOURS)
    boundaries = [anchor]
    cur = anchor
    while cur < date_to:
        cur += timedelta(hours=SHIFT_LENGTH_HOURS)
        boundaries.append(cur)
    return boundaries


def _nearest_candidate(candidates: list, target: datetime):
    """Chọn bản ghi (recordtime, value) đại diện cho thời điểm target theo đúng luật LOCF —
    logic dùng chung cho cả `nearest_value()` lẫn `nearest_gap_hours()`. Trả None nếu không có
    candidate hợp lệ nào."""
    valid = [c for c in candidates if c is not None]
    if not valid:
        return None
    before = [c for c in valid if c[0] <= target]
    if before:
        return max(before, key=lambda c: c[0])
    return min(valid, key=lambda c: c[0])


def nearest_value(candidates: list, target: datetime) -> float:
    """Chọn giá trị bộ đếm TẠI thời điểm target, trong candidates=[(recordtime, value)|None, ...].
    Ưu tiên bản ghi GẦN NHẤT nhưng KHÔNG VƯỢT QUA target (last-observation-carried-forward) —
    đúng ngữ nghĩa bộ đếm cộng dồn: giá trị bộ đếm tại 1 thời điểm luôn bằng giá trị lần đọc
    gần nhất TRƯỚC đó (không thể lấy bản ghi ở TƯƠNG LAI so với target, vì như vậy sẽ tính
    nhầm sản lượng phát sinh SAU mốc ranh giới ca vào ca hiện tại). Chỉ khi HOÀN TOÀN không có
    bản ghi nào <= target (VD target rơi trước cả bản ghi đầu tiên trong toàn bộ dữ liệu), mới
    lấy bản ghi gần nhất SAU target làm phương án dự phòng.
    Thuần logic (không cần CSDL) để unit test độc lập."""
    chosen = _nearest_candidate(candidates, target)
    if chosen is None:
        return 0.0
    return float(chosen[1] or 0)


def nearest_gap_hours(candidates: list, target: datetime):
    """Khoảng cách thời gian (giờ) giữa target và bản ghi mà `nearest_value()` sẽ chọn — dùng
    để phát hiện khi LOCF phải "băng qua" một khoảng trống dữ liệu quá lớn (xem cảnh báo ở đầu
    file). Trả None nếu không có candidate hợp lệ nào (khác với gap lớn — nghĩa là hoàn toàn
    không có dữ liệu, không phải dữ liệu ở quá xa)."""
    chosen = _nearest_candidate(candidates, target)
    if chosen is None:
        return None
    return abs((target - chosen[0]).total_seconds()) / 3600


def values_at_boundaries(candidates: list, boundaries: list) -> list:
    """Với candidates=[(recordtime, value), ...] đã gom sẵn (1 lượt fetch duy nhất), chọn giá
    trị gần nhất cho TỪNG mốc ranh giới ca. Thuần logic, không cần CSDL, để unit test độc lập."""
    return [nearest_value(candidates, b) for b in boundaries]


def reliable_at_boundaries(candidates: list, boundaries: list, max_gap_hours: float = MAX_GAP_HOURS) -> list:
    """Với mỗi mốc trong boundaries, True nếu bản ghi LOCF được chọn cách mốc đó không quá
    max_gap_hours giờ. False nghĩa là phải băng qua 1 khoảng trống dữ liệu lớn — hiệu số dùng
    giá trị tại mốc này KHÔNG đáng tin (xem cảnh báo ở đầu file). Không có candidate nào (gap=
    None) vẫn coi là "đáng tin" — đó là trường hợp hoàn toàn thiếu dữ liệu đã có xử lý riêng
    (trả về 0), khác với trường hợp có dữ liệu nhưng ở quá xa mốc."""
    gaps = [nearest_gap_hours(candidates, b) for b in boundaries]
    return [g is None or g <= max_gap_hours for g in gaps]


def filling_report(db: Session, date_from: datetime, date_to: datetime) -> dict:
    conn = _get_filling_connection(db)
    engine = create_engine(sqlconn_svc._build_url(conn), connect_args={"timeout": 20}, pool_pre_ping=False)
    boundaries = shift_boundaries(date_from, date_to)
    try:
        with sqlconn_svc.safe_query(conn.name):
            metadata = MetaData()
            tbl = Table(FILLING_TABLE, metadata, autoload_with=engine)
            with engine.connect() as db_conn:
                before_first = db_conn.execute(
                    select(tbl.c.Recordtime, tbl.c.TotalCanBySum)
                    .where(tbl.c.Recordtime <= boundaries[0])
                    .order_by(tbl.c.Recordtime.desc()).limit(1)
                ).first()
                in_range = db_conn.execute(
                    select(tbl.c.Recordtime, tbl.c.TotalCanBySum)
                    .where(tbl.c.Recordtime > boundaries[0], tbl.c.Recordtime <= boundaries[-1])
                    .order_by(tbl.c.Recordtime)
                ).all()
                after_last = db_conn.execute(
                    select(tbl.c.Recordtime, tbl.c.TotalCanBySum)
                    .where(tbl.c.Recordtime > boundaries[-1])
                    .order_by(tbl.c.Recordtime.asc()).limit(1)
                ).first()
    finally:
        engine.dispose()

    candidates = [r for r in ([before_first] + list(in_range) + [after_last]) if r is not None]
    result = aggregate_filling_values(candidates, boundaries)
    result.update({"date_from": date_from.isoformat(), "date_to": date_to.isoformat(),
                   "connection_name": conn.name})
    return result


def aggregate_filling_values(candidates: list, boundaries: list) -> dict:
    """Phần logic thuần (không cần CSDL) của filling_report — candidates=[(recordtime, value),
    ...] đã fetch 1 lần (gộp cả trước/trong/sau khoảng). Tách riêng để unit test độc lập, giống
    aggregate_ca_values()/aggregate_keg_values() ở energy_external.py/keg_external.py.

    Mỗi ca chỉ tính được khi CẢ 2 mốc đầu/cuối ca đều "đáng tin" (xem `reliable_at_boundaries`)
    — nếu không, "cans" trả về None kèm cờ "data_gap": True thay vì 1 con số bịa (xem cảnh báo
    khoảng trống dữ liệu ở đầu file). total_cans/by_ca/by_day CỘNG TỪ CÁC CA (bỏ qua ca có gap)
    thay vì trừ trực tiếp 2 đầu mút — nhờ vậy 1 mốc bị gap chỉ làm mất đúng ca liên quan, không
    làm sai lệch toàn bộ khoảng báo cáo."""
    values = values_at_boundaries(candidates, boundaries)
    reliable = reliable_at_boundaries(candidates, boundaries)

    shifts = []
    for i in range(len(boundaries) - 1):
        start, end = boundaries[i], boundaries[i + 1]
        ok = reliable[i] and reliable[i + 1]
        cans = round(max(values[i + 1] - values[i], 0.0)) if ok else None
        shifts.append({
            "date": start.date().isoformat(), "ca": ca_number(start),
            "start": start.isoformat(), "end": end.isoformat(),
            "cans": cans, "data_gap": not ok,
        })

    by_ca_agg: dict = {1: 0.0, 2: 0.0, 3: 0.0}
    by_ca_gap: dict = {1: False, 2: False, 3: False}
    for s in shifts:
        if s["cans"] is not None:
            by_ca_agg[s["ca"]] += s["cans"]
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
        if s["cans"] is not None:
            by_day_agg[d][s["ca"]] = s["cans"]
        by_day_gap[d][s["ca"]] = s["data_gap"]
    by_day = [{"date": d, "ca1": v[1], "ca2": v[2], "ca3": v[3], "has_gap": any(by_day_gap[d].values())}
              for d, v in sorted(by_day_agg.items())]

    total_cans = sum(s["cans"] for s in shifts if s["cans"] is not None)
    has_gap = any(s["data_gap"] for s in shifts)

    return {
        "total_cans": round(total_cans),
        "has_gap": has_gap,
        "by_ca": by_ca, "by_day": by_day, "shifts": shifts,
    }


REALTIME_TABLE = "30K_Realtime"


def filling_realtime_status(db: Session) -> dict:
    """Trạng thái realtime máy chiết lon 30K — đọc bảng 30K_Realtime (snapshot 1 dòng, PLC/SCADA
    ghi đè liên tục) qua cùng kết nối purpose="filling". Khác với filling_report() ở trên (báo
    cáo sản lượng theo ca, tính từ 30K_Report) — bảng này chỉ có giá trị tức thời hiện tại,
    không phải chuỗi thời gian, nên không cần LOCF/shift boundary như filling_report()."""
    conn = _get_filling_connection(db)
    engine = create_engine(sqlconn_svc._build_url(conn), connect_args={"timeout": 10}, pool_pre_ping=False)
    try:
        with sqlconn_svc.safe_query(conn.name):
            metadata = MetaData()
            tbl = Table(REALTIME_TABLE, metadata, autoload_with=engine)
            with engine.connect() as db_conn:
                row = db_conn.execute(
                    select(tbl.c.MachineRunning, tbl.c.Production_Flow, tbl.c.TotalProduct,
                           tbl.c.TotalCan, tbl.c.LastUpdate, tbl.c.MachineSpeed)
                    .order_by(tbl.c.LastUpdate.desc()).limit(1)
                ).first()
    finally:
        engine.dispose()

    if row is None:
        return {"available": False, "connection_name": conn.name}
    return {
        "available": True,
        "machine_running": bool(row.MachineRunning),
        "production_flow": float(row.Production_Flow) if row.Production_Flow is not None else None,
        "machine_speed": float(row.MachineSpeed) if row.MachineSpeed is not None else None,
        "total_product": float(row.TotalProduct) if row.TotalProduct is not None else None,
        "total_can": int(row.TotalCan) if row.TotalCan is not None else None,
        "last_update": row.LastUpdate.isoformat() if row.LastUpdate else None,
        "connection_name": conn.name,
    }


def data_bounds(db: Session) -> dict:
    """Ngày nhỏ nhất/lớn nhất thật có trong bảng 30K_Report — dùng làm mặc định khoảng
    ngày báo cáo, vì dữ liệu SCADA export có thể đã dừng từ lâu (không còn cập nhật tới hiện tại)."""
    conn = _get_filling_connection(db)
    engine = create_engine(sqlconn_svc._build_url(conn), connect_args={"timeout": 15}, pool_pre_ping=False)
    try:
        with sqlconn_svc.safe_query(conn.name):
            metadata = MetaData()
            tbl = Table(FILLING_TABLE, metadata, autoload_with=engine)
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
