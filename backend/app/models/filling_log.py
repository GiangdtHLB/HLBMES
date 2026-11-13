"""Log tự động trạng thái máy chiết lon 30K (đang chiết thường / đang CIP) — ghi vào CSDL CỦA
PHẦN MỀM, khác hẳn filling_external.py (chỉ ĐỌC CSDL SCADA ngoài, không model/migration). Phục
vụ biểu đồ "Trạng thái máy chiết 30K theo thời gian" — yêu cầu người dùng 2026-11-13. Cơ chế
mở/đóng dòng: xem services/filling_log.py (mirror brewhouse_log.py, 1 "thiết bị" duy nhất nên
không cần equipment_id/ba_year/ba_order_no/ba_batch_no như BrewhouseStepLog).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Float, Integer, Unicode
from sqlalchemy.orm import Mapped, mapped_column

from ..common import UTCDateTime, new_id, utcnow
from ..database import Base


class FillingStatusLog(Base):
    """1 dòng = 1 lần máy chiết 30K ở MỘT trạng thái (1=đang chiết bình thường, 2=đang CIP), từ
    lúc vào trạng thái tới lúc rời (đóng khi trạng thái đổi / máy dừng hẳn) — xem
    services/filling_log.py::process_tick(). ended_at=NULL nghĩa là đang ở trạng thái đó (dòng
    đang mở, tối đa 1 dòng mở cho máy này).

    status: 2 nếu (Clean_Flushing=true HOẶC RinsReturnGasChannel=true) — "Đang CIP máy" (tính
    TRƯỚC machine_running, vì CIP có thể chạy độc lập ngoài giờ chiết); 1 nếu MachineRunning=true
    và cả 2 cờ CIP đều false ("đang chiết" bình thường); 3 nếu cả 3 cờ đều false ("máy dừng hẳn")
    — yêu cầu người dùng 2026-11-13, bổ sung cùng ngày ("các khe hở phải liền mạch") để LUÔN có
    đúng 1 trạng thái tại mọi thời điểm, không còn khoảng trống trên biểu đồ như khi chỉ có 2
    trạng thái 1/2 (lúc đó máy dừng không mở dòng nào)."""

    __tablename__ = "filling_status_log"

    log_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    status: Mapped[int] = mapped_column(Integer, index=True)
    machine_running: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    clean_flushing: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    rins_return_gas_channel: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True, index=True)
    duration_minutes: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # True nếu dòng bị ĐÓNG sau 1 khoảng gián đoạn ghi log bất thường (tác vụ nền treo/chết, mất
    # kết nối SCADA kéo dài...) — mirror BrewhouseStepLog.data_gap, xem
    # services/filling_log.py::GAP_THRESHOLD_SECONDS.
    data_gap: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
