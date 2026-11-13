"""Tự động ghi log trạng thái máy chiết lon 30K (đang chiết / đang CIP / máy dừng) vào CSDL CỦA
PHẦN MỀM — khác filling_external.py (chỉ ĐỌC CSDL SCADA ngoài, không ghi gì). Phục vụ biểu đồ
"Trạng thái máy chiết 30K theo thời gian" (thêm, KHÔNG thay, biểu đồ "BC dây chuyền chiết" hiện
có — vẫn giữ nguyên theo ca xác nhận từ BatchPackLot) — yêu cầu người dùng 2026-11-13:
    "cách tính máy chạy running và (Tráng nước nóng hoặc Đuổi CO2 đang chạy) thì là Đang CIP
    máy, trạng thái bằng 2, Nếu chỉ có trạng thái máy đang Running và (Tráng nước nóng và Đuổi
    CO2 đang dừng) thì trạng thái máy là 1 ... trên biểu đồ dây chuyền 30k thể hiện như vậy."
    Bổ sung 2026-11-13 (sau khi xem demo thấy có khoảng trống giữa các thanh): "các khe hở phải
    liền mạch, nếu Trạng thái máy là dừng và cả đuổi CO2 và đuổi nước nóng đều dừng thì là trạng
    thái 3, máy dừng, để 1 màu khác" — LUÔN có đúng 1 trạng thái tại mọi thời điểm (1/2/3, xem
    _status_of()), không còn "không trạng thái nào" nữa, nên biểu đồ không còn khoảng trống (trừ
    lúc data_gap thật — tác vụ nền treo/mất kết nối SCADA, lúc đó không log được gì nên đành vẫn
    có khoảng trống, nhưng đây là tình huống hiếm và biểu thị đúng bản chất "không có số liệu").

Cơ chế — mirror chính xác brewhouse_log.py (xem đó để biết lý do từng quyết định: chạy qua
asyncio.to_thread, bắt lỗi tại _tick_once, tự khởi động lại qua run_poll_loop_supervised, đánh
dấu data_gap cho dòng còn mở lúc khởi động...), nhưng ĐƠN GIẢN HƠN vì chỉ có 1 "thiết bị" (máy
chiết 30K), không cần vòng lặp nhiều equipment_id/theo dõi oder-batch-year-step:
- status (1/2/3, xem _status_of()) ĐỔI so với dòng đang mở (hoặc chưa có dòng mở): ĐÓNG dòng cũ
  (nếu có) RỒI MỞ dòng mới cho status hiện tại — LUÔN mở 1 dòng mới ngay, không còn nhánh "đóng
  mà không mở" (đó là nguyên nhân gây khoảng trống trước khi có trạng thái 3).
- status KHÔNG đổi: bỏ qua (giữa chừng, chưa có gì để log).
- Không đọc được SCADA (available=False/lỗi kết nối): bỏ qua tick đó (KHÔNG coi là trạng thái gì
  cả) — tránh đóng/mở log sai do mất kết nối SCADA tạm thời.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from ..common import utcnow
from ..database import SessionLocal
from ..errors import DomainError
from ..logging_config import get_logger
from ..models.filling_log import FillingStatusLog
from . import filling_external

log = get_logger("mes.filling_log")

POLL_INTERVAL_SECONDS = 1  # mirror brewhouse_log.py — đổi trạng thái là log ngay, không bỏ lỡ
GAP_THRESHOLD_SECONDS = max(POLL_INTERVAL_SECONDS * 10, 120)  # mirror brewhouse_log.py

STATUS_RUNNING = 1  # đang chiết bình thường
STATUS_CIP = 2  # đang CIP máy (tráng nước nóng hoặc đuổi CO2)
STATUS_STOPPED = 3  # máy dừng hẳn (không chiết, không CIP)

_last_tick_ok_at: Optional[datetime] = None


def _status_of(status: dict) -> int:
    """LUÔN trả về 1/2/3 (không còn None) — yêu cầu người dùng 2026-11-13 ("các khe hở phải
    liền mạch"): CIP (tráng nước nóng/đuổi CO2) được tính kể cả khi máy chính KHÔNG chạy (vd CIP
    độc lập ngoài giờ chiết) nên kiểm tra CIP TRƯỚC machine_running. Chỉ khi cả 3 cờ đều tắt mới
    là "máy dừng" (trạng thái 3)."""
    if status.get("clean_flushing") or status.get("rins_return_gas_channel"):
        return STATUS_CIP
    if status.get("machine_running"):
        return STATUS_RUNNING
    return STATUS_STOPPED


def _get_open_row(db: Session) -> Optional[FillingStatusLog]:
    return db.execute(
        select(FillingStatusLog)
        .where(FillingStatusLog.ended_at.is_(None))
        .order_by(FillingStatusLog.started_at.desc())
    ).scalars().first()


def _open_row(status: dict, new_status: int, now: datetime, data_gap: bool = False) -> FillingStatusLog:
    return FillingStatusLog(
        status=new_status,
        machine_running=status.get("machine_running"),
        clean_flushing=status.get("clean_flushing"),
        rins_return_gas_channel=status.get("rins_return_gas_channel"),
        started_at=now,
        data_gap=data_gap,
    )


def _close_row(row: FillingStatusLog, now: datetime, data_gap: bool = False) -> None:
    row.ended_at = now
    row.duration_minutes = round((now - row.started_at).total_seconds() / 60.0, 2)
    if data_gap:
        row.data_gap = True


def process_tick(db: Session, status: dict, gap_seconds: float = 0.0) -> None:
    """Xử lý 1 lượt đọc filling_external.filling_realtime_status() — mở/đóng dòng log theo logic
    ở docstring module. `gap_seconds`: mirror brewhouse_log.py::process_tick()."""
    now = utcnow()
    is_gap = gap_seconds > GAP_THRESHOLD_SECONDS
    open_row = _get_open_row(db)
    new_status = _status_of(status)

    if open_row is None:
        db.add(_open_row(status, new_status, now, data_gap=is_gap))
        return

    if open_row.status != new_status:
        _close_row(open_row, now, data_gap=is_gap)
        db.add(_open_row(status, new_status, now, data_gap=is_gap))
    # else: vẫn giữa trạng thái cũ, không có gì để log


def _tick_once(state: dict) -> None:
    """Thân 1 lượt poll — mirror brewhouse_log.py::_tick_once() (xem đó để biết lý do PHẢI gọi
    qua asyncio.to_thread và PHẢI bắt mọi lỗi ngay tại đây)."""
    global _last_tick_ok_at
    db = SessionLocal()
    try:
        status = filling_external.filling_realtime_status(db)
        if status.get("available"):
            tick_time = utcnow()
            gap_seconds = (tick_time - _last_tick_ok_at).total_seconds() if _last_tick_ok_at else 0.0
            process_tick(db, status, gap_seconds=gap_seconds)
            db.commit()
            _last_tick_ok_at = tick_time
            if gap_seconds > GAP_THRESHOLD_SECONDS:
                log.warning(
                    "filling_log: phát hiện gián đoạn ghi log %.0fs (> %ss) — dòng log mở/đóng "
                    "ở lượt này đã bị đánh dấu data_gap, báo cáo sẽ loại trừ",
                    gap_seconds, GAP_THRESHOLD_SECONDS,
                )
        if state.get("warned_no_connection"):
            log.warning("filling_log: đã kết nối lại được CSDL máy chiết 30K — ghi log tiếp tục bình thường")
        state["warned_no_connection"] = False
    except DomainError as e:
        db.rollback()
        if not state.get("warned_no_connection"):
            log.warning("filling_log: không đọc được CSDL máy chiết 30K — tạm dừng ghi log, sẽ tự thử lại. Lý do: %s", e)
            state["warned_no_connection"] = True
    except Exception:
        db.rollback()
        log.exception("filling_log: lượt đọc/ghi log thất bại — bỏ qua, thử lại lượt sau")
    finally:
        db.close()


def _flag_open_rows_on_start() -> None:
    """Mirror brewhouse_log.py::_flag_open_rows_on_start() — đánh dấu data_gap cho dòng còn
    đang mở lúc poll_loop() khởi động (kể cả supervisor khởi động lại sau sự cố), vì tiến trình
    mới không biết đã gián đoạn bao lâu."""
    db = SessionLocal()
    try:
        rows = db.execute(
            select(FillingStatusLog).where(
                FillingStatusLog.ended_at.is_(None),
                FillingStatusLog.data_gap == false(),
            )
        ).scalars().all()
        if rows:
            for r in rows:
                r.data_gap = True
            db.commit()
            log.warning(
                "filling_log: khởi động lại khi còn %d dòng log đang mở (cũ nhất từ %s) — đã đánh "
                "dấu data_gap vì không biết đã gián đoạn bao lâu",
                len(rows), min(r.started_at for r in rows).isoformat(),
            )
    except Exception:
        db.rollback()
        log.exception("filling_log: không đánh dấu được dòng log đang mở lúc khởi động — bỏ qua")
    finally:
        db.close()


async def poll_loop(interval_seconds: int = POLL_INTERVAL_SECONDS) -> None:
    """Vòng lặp nền — khởi động cùng app (xem main.py lifespan). Mirror brewhouse_log.py::
    poll_loop() (xem đó để biết lý do BẮT BUỘC chạy qua asyncio.to_thread và bắt mọi lỗi tại
    đây)."""
    state: dict = {"warned_no_connection": False}
    await asyncio.to_thread(_flag_open_rows_on_start)
    while True:
        try:
            await asyncio.to_thread(_tick_once, state)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("filling_log: lượt poll thất bại nặng (lỗi ngoài dự kiến) — bỏ qua, thử lại lượt sau")
        await asyncio.sleep(interval_seconds)


async def run_poll_loop_supervised(interval_seconds: int = POLL_INTERVAL_SECONDS) -> None:
    """Bọc ngoài poll_loop() — tự khởi động lại nếu chết vì lý do ngoài dự kiến, mirror
    brewhouse_log.py::run_poll_loop_supervised()."""
    while True:
        try:
            await poll_loop(interval_seconds)
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            log.critical(
                "filling_log: TÁC VỤ GHI LOG CHẾT NGOÀI DỰ KIẾN — tự khởi động lại sau %ss",
                interval_seconds, exc_info=True,
            )
            await asyncio.sleep(interval_seconds)


def filling_status_log_report(db: Session, days: int = 30, date_from_str: str = None,
                              date_to_str: str = None) -> dict:
    """BC "Trạng thái máy chiết 30K theo thời gian" — chỉ có dữ liệu TỪ LÚC tác vụ ghi log này
    được bật (không có lịch sử trước đó, SCADA 30K_Realtime chỉ lưu 1 dòng snapshot, không phải
    chuỗi thời gian — yêu cầu người dùng 2026-11-13 đã xác nhận chấp nhận phạm vi này). Trả về
    `segments` (status=1/2, dùng để vẽ Gantt 2 màu) — mirror cấu trúc pack_line_gantt_report để
    frontend dùng chung 1 hàm vẽ."""
    from ..common import utcnow as _utcnow
    if date_from_str and date_to_str:
        from datetime import date, timedelta as _td
        from .dashboard import _vn_day_start_utc
        date_from = _vn_day_start_utc(date.fromisoformat(date_from_str))
        date_to = _vn_day_start_utc(date.fromisoformat(date_to_str) + _td(days=1))
    else:
        date_to = _utcnow()
        from datetime import timedelta as _td
        date_from = date_to - _td(days=days)

    rows = db.execute(
        select(FillingStatusLog)
        .where(FillingStatusLog.started_at >= date_from, FillingStatusLog.started_at < date_to,
               FillingStatusLog.data_gap == false())
        .order_by(FillingStatusLog.started_at)
    ).scalars().all()

    now = _utcnow()
    segments = []
    for r in rows:
        end_at = r.ended_at or now  # còn đang mở (status hiện tại) -> vẽ tới "bây giờ"
        if end_at <= r.started_at:
            continue
        segments.append({
            "status": r.status, "start_at": r.started_at.isoformat(), "end_at": end_at.isoformat(),
            "still_open": r.ended_at is None,
        })

    def _hours(target_status):
        seconds = sum(
            (datetime.fromisoformat(s["end_at"]) - datetime.fromisoformat(s["start_at"])).total_seconds()
            for s in segments if s["status"] == target_status)
        return round(seconds / 3600, 1)

    return {
        "from": date_from.isoformat(), "to": date_to.isoformat(),
        "segments": segments,
        "running_hours": _hours(STATUS_RUNNING),
        "cip_hours": _hours(STATUS_CIP),
        "stopped_hours": _hours(STATUS_STOPPED),
    }
