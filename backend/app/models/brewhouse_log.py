"""Log tự động từng bước chạy của hệ nấu bia (nồi gạo + 2 dây nấu) — ghi vào CSDL CỦA PHẦN MỀM,
khác hẳn brewhouse_external.py (chỉ ĐỌC CSDL SCADA ngoài, không model/migration). Phục vụ báo
cáo "mỗi nồi chạy hết bao nhiêu phút, giá trị tại mỗi lần chuyển bước" theo oder/batch/year —
yêu cầu người dùng 2026-11-01. Cơ chế mở/đóng dòng: xem services/brewhouse_log.py.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, Float, Index, Integer, Unicode
from sqlalchemy.orm import Mapped, mapped_column

from ..common import UTCDateTime, new_id, utcnow
from ..database import Base


class BrewhouseStepLog(Base):
    """1 dòng = 1 lần thiết bị hệ nấu ở MỘT bước, từ lúc vào bước tới lúc rời bước (đóng khi
    bước đổi / oder-batch-year đổi / về Idle) — xem services/brewhouse_log.py::process_tick().
    ended_at=NULL nghĩa là bước đang chạy (dòng đang mở, tối đa 1 dòng mở/thiết bị).

    duration_minutes đo bằng đồng hồ hệ thống (now - started_at) chứ KHÔNG dùng StTime_AV của
    CSDL SCADA, vì tới lúc ta phát hiện ra đã sang bước mới thì PLC đã ghi đè StTime_AV về gần 0
    cho bước mới — không còn giữ số phút thật của bước vừa xong.

    start_snapshot/end_snapshot lưu nguyên dict trạng thái (brewhouse_external._row_to_status())
    tại 2 thời điểm vào/ra bước — dùng JSON để không phải thêm cột + migration mỗi khi
    brewhouse_external.py có thêm field hiển thị mới (vd thêm cảm biến ở nồi khác)."""

    __tablename__ = "brewhouse_step_log"

    log_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    equipment_id: Mapped[int] = mapped_column(Integer, index=True)
    equipment_name: Mapped[str] = mapped_column(Unicode(255))
    ba_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    ba_order_no: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True, index=True)
    ba_batch_no: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True, index=True)
    step_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    step_name: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    eop_state_label: Mapped[Optional[str]] = mapped_column(Unicode(32), nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True, index=True)
    duration_minutes: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Thời gian đặt (SpTime, phút) ghi nhận lúc bắt đầu bước — tham chiếu để so với duration_minutes thực tế.
    step_minutes_setpoint: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    start_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    end_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # True nếu dòng bị ĐÓNG sau 1 khoảng gián đoạn ghi log bất thường (tác vụ nền bị treo/chết,
    # mất kết nối SCADA kéo dài...) — xem services/brewhouse_log.py::GAP_THRESHOLD_SECONDS. Khi
    # đó started_at/ended_at/duration_minutes KHÔNG đáng tin (bước thật có thể đã xong từ lâu
    # trong lúc gián đoạn, trước khi đọc lại được) — báo cáo phải LOẠI các dòng này khỏi mọi tính
    # trung bình/nút thắt cổ chai, không xoá vì vẫn có giá trị tham khảo "có chạy nhưng không đo
    # được chính xác" — sự cố thực tế 2026-11-02 (poller chết 2+ tiếng, không ai biết).
    data_gap: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    __table_args__ = (
        Index("ix_brewhouse_step_log_batch", "ba_year", "ba_order_no", "ba_batch_no", "equipment_id"),
    )
