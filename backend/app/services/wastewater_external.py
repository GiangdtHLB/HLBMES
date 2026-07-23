"""Trạm quan trắc nước thải Hạ Long — đọc trực tiếp bảng QT_Realtime của CSDL SCADA ngoài đã
khai báo ở Tích hợp (SqlConnection.purpose="wastewater", vật lý cùng CSDL với báo cáo năng
lượng/chiết keg — 1 kết nối được gán nhiều mục đích). Bảng chỉ có 1 dòng snapshot (PLC/SCADA
ghi đè liên tục), không phải chuỗi thời gian — chỉ đọc (SELECT), không tính toán/suy diễn gì
thêm ngoài các cột có sẵn."""

from __future__ import annotations

from sqlalchemy import MetaData, Table, create_engine, select
from sqlalchemy.orm import Session

from ..errors import DomainError
from . import integration_connection as sqlconn_svc

WASTEWATER_PURPOSE = "wastewater"
WASTEWATER_TABLE = "QT_Realtime"


def _get_wastewater_connection(db: Session):
    conn = sqlconn_svc.get_connection_by_purpose(db, WASTEWATER_PURPOSE)
    if not conn:
        raise DomainError(
            "Chưa có kết nối SQL nào được gán \"Dùng cho: wastewater\" — "
            "vào Tích hợp › Kết nối CSDL để gán."
        )
    return conn


def wastewater_realtime_status(db: Session) -> dict:
    """Snapshot tức thời trạm quan trắc nước thải Hạ Long — đọc bảng QT_Realtime."""
    conn = _get_wastewater_connection(db)
    engine = create_engine(sqlconn_svc._build_url(conn), connect_args={"timeout": 10}, pool_pre_ping=False)
    try:
        with sqlconn_svc.safe_query(conn.name):
            metadata = MetaData()
            tbl = Table(WASTEWATER_TABLE, metadata, autoload_with=engine)
            with engine.connect() as db_conn:
                row = db_conn.execute(
                    select(tbl.c.PH, tbl.c.Temp, tbl.c.TSS, tbl.c.COD, tbl.c.NH4,
                           tbl.c.FlowIn, tbl.c.FlowOut, tbl.c.LastUpdate)
                    .order_by(tbl.c.LastUpdate.desc()).limit(1)
                ).first()
    finally:
        engine.dispose()

    if row is None:
        return {"available": False, "connection_name": conn.name}
    return {
        "available": True,
        "ph": float(row.PH) if row.PH is not None else None,
        "temp": float(row.Temp) if row.Temp is not None else None,
        "tss": float(row.TSS) if row.TSS is not None else None,
        "cod": float(row.COD) if row.COD is not None else None,
        "nh4": float(row.NH4) if row.NH4 is not None else None,
        "flow_in": float(row.FlowIn) if row.FlowIn is not None else None,
        "flow_out": float(row.FlowOut) if row.FlowOut is not None else None,
        "last_update": row.LastUpdate.isoformat() if row.LastUpdate else None,
        "connection_name": conn.name,
    }
