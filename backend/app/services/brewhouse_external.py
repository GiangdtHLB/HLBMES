"""Realtime hệ nấu bia (nồi gạo, nồi malt, nồi lọc, nồi trung gian, nồi sôi hoa, nồi lắng xoáy,
chuyển dịch lạnh nhanh — 2 dây nấu) lấy trực tiếp từ CSDL SCADA ngoài, bảng Brewhouse_Realtime
(1 dòng/thiết bị, cột ID phân biệt — xác nhận người dùng 2026-11-01, xem EQUIPMENT_NAMES; PLC/
Braumat ghi đè liên tục). Dùng CHUNG kết nối CSDL_NL_ĐM đã khai ở Tích hợp cho máy chiết 30K
(SqlConnection.purpose="filling"): cùng 1 server/CSDL thật, chỉ khác bảng, không cần khai báo
thêm kết nối riêng. Mirror filling_external.py::filling_realtime_status() nhưng tách file riêng
vì khác domain (Nấu, không phải Chiết đóng gói). Chỉ đọc (SELECT)."""

from __future__ import annotations

from sqlalchemy import MetaData, Table, create_engine, select
from sqlalchemy.orm import Session

from ..errors import DomainError
from . import integration_connection as sqlconn_svc

BREWHOUSE_PURPOSE = "filling"
BREWHOUSE_TABLE = "Brewhouse_Realtime"

RICE_COOKER_EQUIPMENT_ID = 1

# ID (Brewhouse_Realtime) -> tên thiết bị — xác nhận người dùng 2026-11-01 (ảnh chụp Rice_Realtime
# đã đổi tên thành bảng gộp Brewhouse_Realtime, mỗi dòng 1 thiết bị). Dùng để biết TRƯỚC danh
# sách ID cần lấy ở brewhouse_overview() — tránh lấy nhầm thiết bị khác lỡ sau này được thêm vào
# cùng bảng.
EQUIPMENT_NAMES = {
    1: "Nồi gạo",
    2: "Nồi malt 1", 3: "Nồi lọc 1", 4: "Nồi trung gian 1", 5: "Nồi sôi hoa 1",
    6: "Nồi lắng xoáy 1", 7: "Chuyển dịch lạnh nhanh 1",
    8: "Nồi malt 2", 9: "Nồi lọc 2", 10: "Nồi trung gian 2", 11: "Nồi sôi hoa 2",
    12: "Nồi lắng xoáy 2", 13: "Chuyển dịch lạnh nhanh 2",
}

# EOPState (Braumat) — 1=Running, 0=Idle, 6=Hold (xác nhận người dùng 2026-10-31).
EOP_STATE_LABELS = {1: "running", 0: "idle", 6: "hold"}

# NewStep (Braumat) — số thứ tự bước trong quy trình nồi gạo RC1, lấy từ ảnh chụp cây quy trình
# Braumat do người dùng cung cấp (cột "Nr.", 2026-10-31). Các số 1/8/12 không có tên (ô rẽ nhánh
# "Synch" nối giữa 2 bước, không phải 1 bước thật) nên không map — hiện "Bước N" nếu gặp. Riêng
# cho equipment_id=1 (nồi gạo) — thiết bị khác có quy trình/bước khác, map riêng khi có dữ liệu.
STEP_LABELS_BY_EQUIPMENT = {
    RICE_COOKER_EQUIPMENT_ID: {
        2: "RC1 Mash in Rice",
        3: "RC1 Pulse",
        4: "RC1 Sel MashTun",
        5: "RC1 Heat Up",
        6: "RC1 Rest",
        7: "RC1 Synch 02",
        9: "RC1 Tranfer 01",
        10: "RC1 Pulse->MT",
        11: "RC1 Synch 03",
        13: "RC1 End",
    },
    # Nồi malt 1 (ID=2) — ảnh chụp cây quy trình Braumat "DN(MashTun)" do người dùng cung cấp
    # 2026-11-01. Các số 8/11/17/20/24 là mốc "Synch" rẽ nhánh, không phải bước thật nên không
    # map. CHƯA xác nhận Nồi malt 2 (ID=8) có dùng chung đúng số thứ tự này (chỉ đổi tên "MT1"->
    # "MT2") hay không — để trống, hiện "Bước N" cho tới khi xác nhận.
    2: {
        1: "MT1 Wait",
        2: "MT1 Start Check",
        3: "MT1 Wait",
        4: "MT1 Mash In Malt",
        5: "MT1 Heat Up",
        6: "MT1 Rest",
        7: "MT1 Synch 02",
        9: "MT1 Receive<RC",
        10: "MT1 Synch 03",
        12: "MT1 Rest",
        13: "MT1 Heat Up",
        14: "MT1 Rest",
        15: "MT1 Sel LT",
        16: "MT1 Synch 04",
        18: "MT1 Heat Up",
        19: "MT1 Synch 05",
        21: "MT1 Tranfer>LT",
        22: "MT1 Pulse>LT",
        23: "MT1 Synch 06",
        25: "MT1 End",
    },
    # Nồi lọc 1 (ID=3, "LauterTun 01") — ảnh chụp cây quy trình Braumat do người dùng cung cấp
    # 2026-11-01. Số 3/7/10/13/19 là mốc Synch rẽ nhánh, không map.
    3: {
        1: "LT1 Wait",
        2: "LT1 Synch 01",
        4: "LT1 Start Check",
        5: "LT1 Under Water",
        6: "LT1 Synch 02",
        8: "LT1 Receive<MT",
        9: "LT1 Synch 03",
        11: "LT1 Draw Off",
        12: "LT1 Circulate",
        14: "LT1 First Wort",
        15: "LT1 Deepcut_Water",
        16: "LT1 Recirc",
        17: "LT1 SecondWort",
        18: "LT1 Position",
        20: "LT1 Grain Out",
        21: "LT1 Pre.Position",
        22: "LT1 Close Grains",
        23: "LT1 Rinse Top",
        24: "LT1 Rinse Bottom",
        25: "LT1 Pulse>Drain",
        26: "LT1 Empty",
        27: "LT1 End",
    },
    # Nồi trung gian 1 (ID=4, "Holding Vessel 01") — ảnh chụp cây quy trình Braumat do người dùng
    # cung cấp 2026-11-01. Số 5 là mốc Synch.11, không map.
    4: {
        2: "HV1 Start Position",
        3: "HV1 Tranfer>WK1",
        4: "HV1 Pulse>Drain",
        6: "HV1 End",
    },
    # Nồi sôi hoa 1 (ID=5, "WortKettle 01") — ảnh chụp cây quy trình Braumat do người dùng cung
    # cấp 2026-11-01. Số 3/7/10/12/16/18/21 là mốc Synch, không map. Bước 14 "WK1 Boiling
    # With..." và bước 19 "WK1 Transfer->W..." bị CẮT CHỮ trong ảnh gốc — giữ nguyên dấu "..." vì
    # chưa có tên đầy đủ, nhờ người dùng bổ sung sau.
    5: {
        1: "WK1 Wait PreRun",
        2: "WK1 Fill Heat",
        4: "WK1 Heat Up",
        5: "WK1 Heat to boil",
        6: "WK1 Sample",
        8: "WK1 Boiling 1",
        9: "WK1 Boiling 2",
        11: "WK1 Boiling 2",
        13: "WK1 Boiling 3",
        14: "WK1 Boiling With...",
        15: "WK1 CheckDensity",
        17: "WK1 ReboilAdd",
        19: "WK1 Transfer->W...",
        20: "WK1 Pulse->WhP",
        22: "WK1 Drain",
        23: "WK1 End",
    },
    # Nồi lắng xoáy 1 (ID=6, "WhirlPool 01") — ảnh chụp cây quy trình Braumat do người dùng cung
    # cấp 2026-11-01. Số 1/3/5 là mốc Synch, không map. Nr=20 "End" là ký hiệu kết thúc sơ đồ
    # (không có mã EOP, khác Nr=19 "WHP1 End" là bước thật) nên cũng không map.
    6: {
        2: "WHP1 Start",
        4: "WHP1 Receive WK",
        6: "WHP1 Rest",
        7: "WHP1 HW Drain",
        8: "WHP1 PreRun",
        9: "WHP1->WC1",
        10: "WHP1->WC2",
        11: "WHP1 PushWort",
        12: "WHP1 Pulse Wait",
        13: "WHP1 Circulation",
        14: "WHP1->GrainSpent",
        15: "WHP1 Pulse",
        16: "WHP1 Pulse",
        17: "WHP1 Pulse",
        18: "WHP1 Empty",
        19: "WHP1 End",
    },
}
# Dây nấu 2 dùng CHUNG đúng số thứ tự + tên bước với dây nấu 1 cho 4 thiết bị này — xác nhận
# người dùng 2026-11-01: "các bước của nồi malt 2 giống nồi malt 1, nồi lọc 2 giống nồi lọc 1,
# nồi trung gian 2 giống nồi trung gian 1, nồi lắng xoáy 2 giống nồi lắng xoáy 1" (giữ nguyên tên
# "MT1/LT1/HV1/WHP1..." dù là thiết bị dây 2, vì người dùng nói "giống" chứ không đổi tên riêng).
# Nồi sôi hoa 2 (ID=11) cũng giống nồi sôi hoa 1 — xác nhận người dùng 2026-11-01.
STEP_LABELS_BY_EQUIPMENT[8] = STEP_LABELS_BY_EQUIPMENT[2]    # Nồi malt 2
STEP_LABELS_BY_EQUIPMENT[9] = STEP_LABELS_BY_EQUIPMENT[3]    # Nồi lọc 2
STEP_LABELS_BY_EQUIPMENT[10] = STEP_LABELS_BY_EQUIPMENT[4]   # Nồi trung gian 2
STEP_LABELS_BY_EQUIPMENT[11] = STEP_LABELS_BY_EQUIPMENT[5]   # Nồi sôi hoa 2
STEP_LABELS_BY_EQUIPMENT[12] = STEP_LABELS_BY_EQUIPMENT[6]   # Nồi lắng xoáy 2


def _get_brewhouse_connection(db: Session):
    conn = sqlconn_svc.get_connection_by_purpose(db, BREWHOUSE_PURPOSE)
    if not conn:
        raise DomainError(
            "Chưa có kết nối SQL nào được gán \"Dùng cho: Chiết (đóng gói)\" — "
            "vào Tích hợp › Kết nối CSDL để gán (CSDL_NL_ĐM — dùng chung cho realtime hệ nấu)."
        )
    return conn


def _row_to_status(row, equipment_id: int) -> dict:
    eop_state = int(row.EOPState) if row.EOPState is not None else None
    step_no = int(row.NewStep) if row.NewStep is not None else None
    step_labels = STEP_LABELS_BY_EQUIPMENT.get(equipment_id, {})
    return {
        "available": True,
        "equipment_id": equipment_id,
        "step_no": step_no,
        "step": step_labels.get(step_no, f"Bước {step_no}" if step_no is not None else None),
        "ba_year": int(row.BA_Year) if row.BA_Year is not None else None,
        "ba_order_no": row.BA_ONo,
        "ba_batch_no": row.BA_BNo,
        "eop_state": eop_state,
        "eop_state_label": EOP_STATE_LABELS.get(eop_state),
        "temp_actual": float(row.S_0201TET) if row.S_0201TET is not None else None,
        "temp_setpoint": float(row.SPTemp) if row.SPTemp is not None else None,
        "volume_hl": float(row.Volume) if row.Volume is not None else None,
        # Thời gian đã chạy trong bước hiện tại (phút, StTime_AV) và thời gian ĐẶT cho bước đó
        # (phút, SpTime) — 2 cột riêng, đơn vị phút sẵn trong CSDL nguồn (xác nhận người dùng
        # 2026-10-31 + 2026-11-01).
        "step_minutes": float(row.StTime_AV) if row.StTime_AV is not None else None,
        "step_minutes_setpoint": float(row.SpTime) if row.SpTime is not None else None,
    }


def brewhouse_equipment_realtime_status(db: Session, equipment_id: int = RICE_COOKER_EQUIPMENT_ID) -> dict:
    """Trạng thái tức thời 1 thiết bị hệ nấu (lọc theo ID trong Brewhouse_Realtime)."""
    conn = _get_brewhouse_connection(db)
    engine = create_engine(sqlconn_svc._build_url(conn), connect_args={"timeout": 4}, pool_pre_ping=False)
    try:
        with sqlconn_svc.safe_query(conn.name):
            metadata = MetaData()
            tbl = Table(BREWHOUSE_TABLE, metadata, autoload_with=engine)
            with engine.connect() as db_conn:
                row = db_conn.execute(
                    select(tbl.c.NewStep, tbl.c.BA_Year, tbl.c.BA_ONo, tbl.c.BA_BNo, tbl.c.EOPState,
                           tbl.c.S_0201TET, tbl.c.SPTemp, tbl.c.Volume, tbl.c.StTime_AV, tbl.c.SpTime)
                    .where(tbl.c.ID == equipment_id)
                    .limit(1)
                ).first()
    finally:
        engine.dispose()

    if row is None:
        return {"available": False, "connection_name": conn.name}
    return {**_row_to_status(row, equipment_id), "connection_name": conn.name}


def brewhouse_overview(db: Session) -> dict:
    """Trạng thái tức thời TOÀN BỘ thiết bị hệ nấu trong 1 lượt — 1 kết nối/1 câu query duy nhất
    (WHERE ID IN đúng danh sách EQUIPMENT_NAMES) thay vì gọi riêng từng thiết bị — tránh dội 13
    round-trip WAN mỗi 15 giây cho trang Realtime (hiệu năng, mirror lý do filling_report() gộp
    3 lần fetch thay vì fetch riêng từng mốc ca)."""
    conn = _get_brewhouse_connection(db)
    engine = create_engine(sqlconn_svc._build_url(conn), connect_args={"timeout": 4}, pool_pre_ping=False)
    try:
        with sqlconn_svc.safe_query(conn.name):
            metadata = MetaData()
            tbl = Table(BREWHOUSE_TABLE, metadata, autoload_with=engine)
            with engine.connect() as db_conn:
                rows = db_conn.execute(
                    select(tbl.c.ID, tbl.c.NewStep, tbl.c.BA_Year, tbl.c.BA_ONo, tbl.c.BA_BNo,
                           tbl.c.EOPState, tbl.c.S_0201TET, tbl.c.SPTemp, tbl.c.Volume, tbl.c.StTime_AV,
                           tbl.c.SpTime)
                    .where(tbl.c.ID.in_(EQUIPMENT_NAMES.keys()))
                ).all()
    finally:
        engine.dispose()

    equipment = {int(r.ID): _row_to_status(r, int(r.ID)) for r in rows}
    return {"available": bool(equipment), "equipment": equipment, "connection_name": conn.name}


def rice_cooker_realtime_status(db: Session) -> dict:
    """Nồi gạo (ID=1) — giữ tên hàm cũ, mirror chung qua equipment_id."""
    return brewhouse_equipment_realtime_status(db, RICE_COOKER_EQUIPMENT_ID)
