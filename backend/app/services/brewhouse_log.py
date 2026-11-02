"""Tự động ghi log mỗi bước chạy của hệ nấu bia (nồi gạo + 2 dây nấu) vào CSDL CỦA PHẦN MỀM —
khác brewhouse_external.py (chỉ ĐỌC CSDL SCADA ngoài, không ghi gì). Phục vụ báo cáo "mỗi nồi
chạy hết bao nhiêu phút, giá trị tại mỗi lần chuyển bước" theo oder/batch/year — yêu cầu người
dùng 2026-11-01:
    "khi trạng thái chuyển từ Idle sang 1 trạng thái khác thì bắt đầu log... Trong quá trình
    khác Idle, ví dụ từ bước 1 sang bước 2, bạn sẽ tự nhớ số liệu tại bước 1, khi bắt đầu sang
    bước 2 thì sẽ tự động log lại các giá trị tại thời điểm chuyển bước... Mục tiêu là chạy ra
    báo cáo. Với cùng oder, batch, year thì mỗi nồi hết bao nhiêu phút, các giá trị tại thời
    điểm chuyển bước thế nào."

Cơ chế — xem poll_loop(): 1 tác vụ nền asyncio khởi động cùng app (main.py lifespan), định kỳ
đọc brewhouse_overview() rồi so với dòng log ĐANG MỞ (ended_at IS NULL) của từng thiết bị:
- Idle -> khác Idle: MỞ dòng log mới (bắt đầu 1 lần chạy, ghi bước/tên bước/oder/batch/year/
  thời gian đặt + toàn bộ giá trị hiển thị tại thời điểm bắt đầu).
- Đang chạy (khác Idle), bước đổi HOẶC oder/batch/year đổi (coi là 1 lần chạy khác dù không về
  Idle — hiếm nhưng để chắc): ĐÓNG dòng đang mở (ended_at=now, duration_minutes=now-started_at,
  end_snapshot=giá trị đọc được) RỒI MỞ dòng mới cho bước kế — dùng CHUNG 1 lần đọc nên giá trị
  đó vừa là "cuối bước cũ" vừa là "đầu bước mới", đúng yêu cầu "giá trị tại thời điểm chuyển
  bước".
- Đang chạy, bước/oder/batch/year KHÔNG đổi: bỏ qua (giữa bước, chưa có gì để log).
- Về lại Idle: ĐÓNG dòng đang mở (kết thúc lần chạy đó), không mở dòng mới.
- Thiết bị lỗi kết nối/không có trong overview: bỏ qua tick đó (KHÔNG coi là Idle) — tránh
  đóng/mở log sai do mất kết nối SCADA tạm thời.

Chỉ chạy đúng 1 instance trong tiến trình (asyncio task, không phải multiprocessing) — nếu sau
này triển khai nhiều worker process (vd gunicorn -w N) phải gom poller về 1 worker riêng hoặc
thêm khóa (advisory lock), nếu không N tiến trình sẽ cùng ghi log trùng lặp."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from ..common import utcnow
from ..database import SessionLocal
from ..errors import DomainError
from ..logging_config import get_logger
from ..models.brewhouse_log import BrewhouseStepLog
from . import brewhouse_external

log = get_logger("mes.brewhouse_log")

# 1 giây — yêu cầu người dùng 2026-11-01 ("thay đổi bước là log ngay"), tránh bỏ lỡ bước chạy
# ngắn giữa 2 lượt poll. Không làm tăng số lần GHI DB tương ứng (process_tick chỉ ghi khi phát
# hiện bước/oder/batch thực sự đổi, các tick "chưa đổi gì" chỉ đọc rồi bỏ qua) — chỉ tăng số lần
# ĐỌC SCADA (CSDL_NL_ĐM qua WAN) lên ~86.400 lượt/ngày (từ ~4.300 lượt/ngày lúc 20s), chạy 24/7
# kể cả ngoài giờ sản xuất.
POLL_INTERVAL_SECONDS = 1

# Khoảng cách tối đa (giây) giữa 2 lượt đọc THÀNH CÔNG liên tiếp trước khi coi là "có gián đoạn
# ghi log" (tác vụ nền treo/chết rồi tự khởi động lại, mất kết nối SCADA kéo dài...) — gấp 10 lần
# POLL_INTERVAL_SECONDS (tối thiểu 10s) để không báo nhầm do 1 lượt đơn lẻ chạy chậm (SQL Server
# qua WAN đôi lúc có độ trễ). Khi vượt ngưỡng này, dòng log bị ĐÓNG/MỞ ngay sau đó sẽ bị đánh dấu
# data_gap=True (xem BrewhouseStepLog.data_gap) — sự cố thực tế 2026-11-02: tác vụ chết 2+ tiếng,
# lúc khởi động lại sẽ đóng dòng đang mở với duration_minutes SAI (tính cả khoảng chết) nếu không
# có cờ này để báo cáo loại trừ.
GAP_THRESHOLD_SECONDS = max(POLL_INTERVAL_SECONDS * 10, 10)

# Mốc thời gian lượt đọc THÀNH CÔNG gần nhất (module-level, chỉ 1 instance poll_loop — xem cảnh
# báo multi-worker ở docstring module) — dùng để tính gap_seconds truyền vào process_tick().
_last_tick_ok_at: Optional[datetime] = None


def _get_open_row(db: Session, equipment_id: int) -> Optional[BrewhouseStepLog]:
    return db.execute(
        select(BrewhouseStepLog)
        .where(BrewhouseStepLog.equipment_id == equipment_id, BrewhouseStepLog.ended_at.is_(None))
        .order_by(BrewhouseStepLog.started_at.desc())
    ).scalars().first()


def _s(v) -> Optional[str]:
    """Ép về str (hoặc None) — CSDL SCADA trả BA_ONo/BA_BNo có thể là số (int/Decimal) tuỳ
    driver, trong khi cột lưu log là Unicode. Nếu không ép kiểu nhất quán ở CẢ 2 phía so sánh,
    lần đọc sau (giá trị thô, có thể là số) sẽ luôn lệch kiểu với giá trị đã lưu (luôn là str
    sau khi ghi xuống CSDL) -> batch_changed sai thành True ở MỌI lượt, đóng/mở log liên tục dù
    oder/batch không hề đổi (lỗi thực tế gặp khi kiểm thử 2026-11-01)."""
    return None if v is None else str(v)


def _open_step(equipment_id: int, status: dict, now: datetime, data_gap: bool = False) -> BrewhouseStepLog:
    return BrewhouseStepLog(
        equipment_id=equipment_id,
        equipment_name=brewhouse_external.EQUIPMENT_NAMES.get(equipment_id, f"Thiết bị {equipment_id}"),
        ba_year=status.get("ba_year"),
        ba_order_no=_s(status.get("ba_order_no")),
        ba_batch_no=_s(status.get("ba_batch_no")),
        step_no=status.get("step_no"),
        step_name=status.get("step"),
        eop_state_label=status.get("eop_state_label"),
        started_at=now,
        step_minutes_setpoint=status.get("step_minutes_setpoint"),
        start_snapshot=status,
        # Nếu tick này đến sau 1 khoảng gián đoạn dài — bước này có thể đã THẬT SỰ bắt đầu từ lúc
        # nào đó TRONG khoảng gián đoạn, không phải đúng lúc `now` — đánh dấu để báo cáo loại trừ.
        data_gap=data_gap,
    )


def _close_step(row: BrewhouseStepLog, status: dict, now: datetime, data_gap: bool = False) -> None:
    row.ended_at = now
    row.duration_minutes = round((now - row.started_at).total_seconds() / 60.0, 2)
    row.end_snapshot = status
    # Giữ True nếu dòng NÀY đã bị đánh dấu từ lúc MỞ (started_at cũng không đáng tin) — không ghi
    # đè về False chỉ vì tick đóng dòng lần này không phải là tick có gián đoạn.
    if data_gap:
        row.data_gap = True


def _batch_key(status: dict) -> tuple:
    return (status.get("ba_year"), _s(status.get("ba_order_no")), _s(status.get("ba_batch_no")))


def process_tick(db: Session, overview: dict, gap_seconds: float = 0.0) -> None:
    """Xử lý 1 lượt đọc brewhouse_overview() — mở/đóng dòng log theo logic ở docstring module.
    `gap_seconds`: khoảng cách (giây) kể từ lượt đọc THÀNH CÔNG trước đó (do poll_loop() tính) —
    vượt GAP_THRESHOLD_SECONDS thì mọi dòng mở/đóng Ở TICK NÀY bị đánh dấu data_gap=True (xem
    _open_step()/_close_step())."""
    now = utcnow()
    is_gap = gap_seconds > GAP_THRESHOLD_SECONDS
    equipment = overview.get("equipment") or {}
    for equipment_id in brewhouse_external.EQUIPMENT_NAMES:
        status = equipment.get(equipment_id)
        if not status or not status.get("available", True):
            continue  # mất kết nối/thiếu dữ liệu thiết bị này — bỏ qua tick, không coi là Idle

        open_row = _get_open_row(db, equipment_id)
        is_idle = status.get("eop_state_label") == "idle"

        if is_idle:
            if open_row is not None:
                _close_step(open_row, status, now, data_gap=is_gap)
            continue

        if open_row is None:
            db.add(_open_step(equipment_id, status, now, data_gap=is_gap))
            continue

        step_changed = open_row.step_no != status.get("step_no")
        batch_changed = (open_row.ba_year, open_row.ba_order_no, open_row.ba_batch_no) != _batch_key(status)
        if step_changed or batch_changed:
            _close_step(open_row, status, now, data_gap=is_gap)
            db.add(_open_step(equipment_id, status, now, data_gap=is_gap))
        # else: vẫn giữa bước cũ, không có gì để log


def _tick_once(state: dict) -> None:
    """Thân 1 lượt poll. TOÀN BỘ thân hàm là I/O ĐỒNG BỘ (chặn luồng gọi nó): đọc SCADA qua ODBC/
    WAN (brewhouse_overview tạo engine + autoload_with = nhiều round-trip, đo thực tế trên prod
    2026-11-01: ~0,24s/lượt, đỉnh 0,49s, tệ nhất 4s = timeout ODBC) rồi SELECT/INSERT/UPDATE trên
    CSDL app. Vì vậy poll_loop() PHẢI gọi nó qua asyncio.to_thread — xem lý do ở đó.
    `state` giữ cờ cảnh báo giữa các lượt (dict thay vì biến cục bộ để dùng được qua nhiều lượt).

    KHÔNG tự nuốt lỗi ngoài 3 nhánh dưới: lỗi lọt ra (vd chính db.rollback()/db.close() ném tiếp
    khi kết nối đã hỏng) sẽ nổi lên poll_loop() và được bắt+ghi log ở đó — xem sự cố 2026-11-02."""
    global _last_tick_ok_at
    db = SessionLocal()
    try:
        overview = brewhouse_external.brewhouse_overview(db)
        if overview.get("available"):
            tick_time = utcnow()
            gap_seconds = (tick_time - _last_tick_ok_at).total_seconds() if _last_tick_ok_at else 0.0
            process_tick(db, overview, gap_seconds=gap_seconds)
            db.commit()
            _last_tick_ok_at = tick_time
            if gap_seconds > GAP_THRESHOLD_SECONDS:
                log.warning(
                    "brewhouse_log: phát hiện gián đoạn ghi log %.0fs (> %ss) — các dòng "
                    "log mở/đóng ở lượt này đã bị đánh dấu data_gap, báo cáo sẽ loại trừ",
                    gap_seconds, GAP_THRESHOLD_SECONDS,
                )
        if state.get("warned_no_connection"):
            # Ghi cả lúc HỒI PHỤC: trước đây chỉ log lúc hỏng rồi im lặng, nên nhìn log không
            # biết sự cố kéo dài bao lâu hay đã hết chưa (sự cố 2026-11-02 mất 2+ tiếng mới lộ).
            log.warning("brewhouse_log: đã kết nối lại được CSDL hệ nấu — ghi log tiếp tục bình thường")
        state["warned_no_connection"] = False
    except DomainError as e:
        # CHÚ Ý: nhánh này gom 2 việc khác hẳn nhau, vì integration_connection.safe_query() bọc
        # MỌI SQLAlchemyError (timeout/mất WAN/login hỏng) thành DomainError giống hệt lỗi "chưa
        # khai báo kết nối": (a) chưa gán kết nối CSDL_NL_ĐM (vd môi trường dev), (b) SCADA tạm
        # thời không đọc được. Vì vậy phải IN KÈM nội dung lỗi — thông báo cũ chỉ nói "chưa có
        # kết nối" khiến sự cố mạng 2026-11-02 bị hiểu nhầm thành lỗi cấu hình.
        db.rollback()
        if not state.get("warned_no_connection"):
            log.warning("brewhouse_log: không đọc được CSDL hệ nấu — tạm dừng ghi log, sẽ tự thử lại. Lý do: %s", e)
            state["warned_no_connection"] = True
    except Exception:
        db.rollback()
        log.exception("brewhouse_log: lượt đọc/ghi log thất bại — bỏ qua, thử lại lượt sau")
    finally:
        db.close()


def _flag_open_rows_on_start() -> None:
    """Đánh dấu data_gap cho MỌI dòng còn đang mở lúc vòng lặp bắt đầu — chạy 1 lần mỗi lần
    poll_loop() khởi động (kể cả khi supervisor khởi động lại sau sự cố).

    Vì sao cần: _last_tick_ok_at là biến MODULE, tiến trình mới luôn bắt đầu bằng None nên
    gap_seconds=0 ở lượt đầu -> is_gap=False. Tức cơ chế data_gap của process_tick() CHỈ phát hiện
    được gián đoạn khi tiến trình vẫn sống; đúng kịch bản nó sinh ra để chặn (tác vụ chết rồi
    app khởi động lại) thì lại không bắt được. Sự cố 2026-11-02: tác vụ chết 06:03, tới lúc
    deploy còn 11 dòng mở từ 3 tiếng trước — nếu không đánh dấu, chúng sẽ bị đóng với
    duration_minutes ~3 tiếng (toàn bộ khoảng chết) và lọt thẳng vào báo cáo năng suất.

    Đánh dấu TẤT CẢ dòng đang mở, không cố phân biệt "khởi động lại sạch" (deploy ~15s) với "chết
    âm thầm": tiến trình mới không có cách nào biết giữa chừng đã xảy ra gì. Đánh dấu thừa thì
    mất vài bước khỏi thống kê năng suất; đánh dấu thiếu thì đưa số giờ ảo vào báo cáo công suất
    — sai lệch nguy hiểm hơn nhiều."""
    db = SessionLocal()
    try:
        rows = db.execute(
            select(BrewhouseStepLog).where(
                BrewhouseStepLog.ended_at.is_(None),
                BrewhouseStepLog.data_gap == false(),   # == false(), KHÔNG .is_(False) — xem DEPLOY-CONTRACT §2
            )
        ).scalars().all()
        if rows:
            for r in rows:
                r.data_gap = True
            db.commit()
            log.warning(
                "brewhouse_log: khởi động lại khi còn %d dòng log đang mở (cũ nhất từ %s) — đã đánh "
                "dấu data_gap vì không biết đã gián đoạn bao lâu, báo cáo năng suất sẽ loại trừ",
                len(rows), min(r.started_at for r in rows).isoformat(),
            )
    except Exception:
        db.rollback()
        log.exception("brewhouse_log: không đánh dấu được dòng log đang mở lúc khởi động — bỏ qua")
    finally:
        db.close()


async def poll_loop(interval_seconds: int = POLL_INTERVAL_SECONDS) -> None:
    """Vòng lặp nền — khởi động cùng app (xem main.py lifespan), chạy tới khi bị cancel lúc tắt app.

    Hai điều BẮT BUỘC giữ, mỗi điều ứng với một sự cố thật:

    1. Chạy mỗi lượt trong LUỒNG RIÊNG (asyncio.to_thread), KHÔNG gọi thẳng _tick_once() ở đây:
       thân lượt poll là I/O đồng bộ ~0,24s (đỉnh 0,49s; 4s nếu WAN tới SCADA trục trặc — timeout
       ODBC). Gọi thẳng trong coroutine này sẽ chặn event loop chừng đó mỗi giây — ~25% thời
       gian, 24/7 — làm TOÀN BỘ request của app trễ theo (uvicorn nhận/định tuyến request trên
       chính event loop đó). Đo A/B 2026-11-01: gọi thẳng max 250ms, qua to_thread max 1,8ms.
       An toàn vì mỗi lượt tự mở/đóng Session riêng, không chia sẻ trạng thái.

    2. BẮT MỌI lỗi của lượt ngay tại đây. Lỗi lọt ra khỏi _tick_once() (kể cả db.rollback()/
       db.close() ném tiếp khi kết nối đã hỏng) sẽ làm asyncio Task chết ÂM THẦM — không có gì
       await lại để lộ traceback. Sự cố 2026-11-02: tác vụ chết lúc 06:03, SCADA vẫn chạy 11
       thiết bị và đã đổi bước nhưng không dòng log nào được ghi suốt 3 tiếng, không một dòng log
       lỗi. Dùng CHUNG với run_poll_loop_supervised() làm lớp bảo vệ thứ 2.
    """
    state: dict = {"warned_no_connection": False}
    await asyncio.to_thread(_flag_open_rows_on_start)
    while True:
        try:
            await asyncio.to_thread(_tick_once, state)
        except asyncio.CancelledError:
            raise  # tắt app bình thường
        except Exception:
            log.exception("brewhouse_log: lượt poll thất bại nặng (lỗi ngoài dự kiến) — bỏ qua, thử lại lượt sau")
        await asyncio.sleep(interval_seconds)


async def run_poll_loop_supervised(interval_seconds: int = POLL_INTERVAL_SECONDS) -> None:
    """Bọc ngoài poll_loop() — nếu vòng lặp vẫn chết vì lý do ngoài dự kiến (chưa lường hết trong
    poll_loop(), hoặc lỗi mới phát sinh sau này), TỰ KHỞI ĐỘNG LẠI ngay sau khi ghi log CRITICAL,
    thay vì để tác vụ nền chết âm thầm cho tới khi ai đó phát hiện qua đối chiếu thủ công (sự cố
    2026-11-02, xem poll_loop()). main.py (lifespan) gọi hàm NÀY thay vì gọi thẳng poll_loop()."""
    while True:
        try:
            await poll_loop(interval_seconds)
            return  # poll_loop() chỉ return khi vòng while True bên trong thoát bất thường — không nên xảy ra
        except asyncio.CancelledError:
            raise  # tắt app bình thường — để main.py xử lý, không phải sự cố cần khởi động lại
        except Exception:
            log.critical(
                "brewhouse_log: TÁC VỤ GHI LOG CHẾT NGOÀI DỰ KIẾN — tự khởi động lại sau %ss",
                interval_seconds, exc_info=True,
            )
            await asyncio.sleep(interval_seconds)


def _row_to_out(row: BrewhouseStepLog) -> dict:
    return {
        "log_id": row.log_id,
        "equipment_id": row.equipment_id,
        "equipment_name": row.equipment_name,
        "ba_year": row.ba_year,
        "ba_order_no": row.ba_order_no,
        "ba_batch_no": row.ba_batch_no,
        "step_no": row.step_no,
        "step_name": row.step_name,
        "eop_state_label": row.eop_state_label,
        "started_at": row.started_at,
        "ended_at": row.ended_at,
        "duration_minutes": row.duration_minutes,
        "step_minutes_setpoint": row.step_minutes_setpoint,
        "start_snapshot": row.start_snapshot,
        "end_snapshot": row.end_snapshot,
        "data_gap": row.data_gap,
    }


def step_log_report(db: Session, ba_year: int = None, ba_order_no: str = None,
                    ba_batch_no: str = None, equipment_id: int = None, days: int = 3650) -> dict:
    """BC log từng bước (chi tiết) + tổng phút mỗi thiết bị theo oder/batch/year (yêu cầu người
    dùng 2026-11-01). Lọc theo oder/batch/year để xem đúng 1 mẻ nấu chạy qua từng nồi hết bao
    lâu, hoặc bỏ trống để xem toàn bộ trong khoảng `days` ngày gần nhất."""
    since = utcnow() - timedelta(days=days)
    stmt = select(BrewhouseStepLog).where(BrewhouseStepLog.started_at >= since)
    if ba_year is not None:
        stmt = stmt.where(BrewhouseStepLog.ba_year == ba_year)
    if ba_order_no:
        stmt = stmt.where(BrewhouseStepLog.ba_order_no == ba_order_no)
    if ba_batch_no:
        stmt = stmt.where(BrewhouseStepLog.ba_batch_no == ba_batch_no)
    if equipment_id is not None:
        stmt = stmt.where(BrewhouseStepLog.equipment_id == equipment_id)
    rows = db.execute(
        stmt.order_by(BrewhouseStepLog.equipment_id, BrewhouseStepLog.started_at)
    ).scalars().all()

    # Tổng thời gian mỗi nồi = TỪ LÚC KHÁC IDLE (started_at của bước ĐẦU TIÊN) ĐẾN LÚC KẾT THÚC
    # BƯỚC CUỐI CÙNG (ended_at của bước cuối, hoặc hiện tại nếu còn đang chạy) — KHÔNG phải tổng
    # cộng duration_minutes của riêng các bước đã đóng, vì cách đó bỏ sót thời gian của bước
    # ĐANG chạy dở (yêu cầu người dùng 2026-11-01: "thời gian của từng nồi... là tổng thời gian
    # từ lúc nồi đó khác Idle đến lúc kết thúc bước cuối cùng").
    summary_map: dict[tuple, dict] = {}
    for r in rows:
        key = (r.equipment_id, r.ba_year, r.ba_order_no, r.ba_batch_no)
        s = summary_map.get(key)
        if s is None:
            s = summary_map[key] = {
                "equipment_id": r.equipment_id, "equipment_name": r.equipment_name,
                "ba_year": r.ba_year, "ba_order_no": r.ba_order_no, "ba_batch_no": r.ba_batch_no,
                "step_count": 0, "started_at": r.started_at, "ended_at": r.ended_at, "still_running": False,
                "data_gap": False,
            }
        s["step_count"] += 1
        s["started_at"] = min(s["started_at"], r.started_at)
        if r.data_gap:
            # 1 bước bất kỳ trong nhóm này bị gián đoạn ghi log -> total_minutes cộng gộp của CẢ
            # NHÓM cũng không còn đáng tin (xem GAP_THRESHOLD_SECONDS) — đánh dấu để báo cáo loại
            # trừ khỏi tính trung bình/nút thắt cổ chai, vẫn hiện số (có badge cảnh báo) để tham khảo.
            s["data_gap"] = True
        if r.ended_at is None:
            s["still_running"] = True
        elif not s["still_running"]:
            s["ended_at"] = max(s["ended_at"], r.ended_at) if s["ended_at"] else r.ended_at
    now = utcnow()
    for s in summary_map.values():
        end_reference = now if s["still_running"] else s["ended_at"]
        s["total_minutes"] = round((end_reference - s["started_at"]).total_seconds() / 60.0, 2)
        if s["still_running"]:
            s["ended_at"] = None

    return {"steps": [_row_to_out(r) for r in rows], "summary": list(summary_map.values())}


# Chuỗi vai trò nồi theo ĐÚNG thứ tự quy trình nấu (bất kể dây 1 hay dây 2 — mỗi vai trò map
# tới 1 trong 2 ID tuỳ mẻ chạy dây nào, xem brewhouse_external.EQUIPMENT_NAMES). Nồi gạo dùng
# chung cho cả 2 dây nên chỉ có 1 ID.
# KHÔNG đưa "Chuyển dịch lạnh nhanh" (ID 7/13) vào chuỗi — thiết bị này chạy SONG SONG với Nồi
# lắng xoáy (cùng lúc, không phải bước tuần tự kế tiếp), nên không tính là 1 mắt xích riêng
# trong tổng thời gian cả mẻ/nút thắt cổ chai — yêu cầu người dùng 2026-11-01.
ROLE_CHAIN = [
    ("Nồi gạo", (brewhouse_external.RICE_COOKER_EQUIPMENT_ID,)),
    ("Nồi malt", (2, 8)),
    ("Nồi lọc", (3, 9)),
    ("Nồi trung gian", (4, 10)),
    ("Nồi sôi hoa", (5, 11)),
    ("Nồi lắng xoáy", (6, 12)),
]
WHIRLPOOL_ROLE = "Nồi lắng xoáy"


def _brew_cycle_items(db: Session, ba_year: int = None, ba_order_no: str = None,
                      ba_batch_no: str = None, days: int = 3650) -> list[dict]:
    """1 mẻ/phần tử: mốc Nồi gạo bắt đầu + tổng thời gian TỪNG NỒI trong chuỗi (xem ROLE_CHAIN).
    Dùng chung cho brew_cycle_report() (xem từng mẻ) và phần ghép cặp 2 mẻ liên tiếp bên dưới."""
    since = utcnow() - timedelta(days=days)
    stmt = select(BrewhouseStepLog).where(
        BrewhouseStepLog.equipment_id == brewhouse_external.RICE_COOKER_EQUIPMENT_ID,
        BrewhouseStepLog.started_at >= since,
    )
    if ba_year is not None:
        stmt = stmt.where(BrewhouseStepLog.ba_year == ba_year)
    if ba_order_no:
        stmt = stmt.where(BrewhouseStepLog.ba_order_no == ba_order_no)
    if ba_batch_no:
        stmt = stmt.where(BrewhouseStepLog.ba_batch_no == ba_batch_no)
    rice_rows = db.execute(stmt.order_by(BrewhouseStepLog.started_at)).scalars().all()

    # Nồi gạo dùng CHUNG cho cả 2 dây — 1 mẻ có thể có NHIỀU dòng log nồi gạo (nhiều bước), lấy
    # started_at SỚM NHẤT của mỗi oder/batch/year làm mốc "bắt đầu vào nguyên liệu".
    batch_rice_start: dict[tuple, datetime] = {}
    for r in rice_rows:
        key = (r.ba_year, r.ba_order_no, r.ba_batch_no)
        if key not in batch_rice_start or r.started_at < batch_rice_start[key]:
            batch_rice_start[key] = r.started_at

    now = utcnow()
    items = []
    for (year, order_no, batch_no), rice_started_at in batch_rice_start.items():
        all_rows = db.execute(
            select(BrewhouseStepLog).where(
                BrewhouseStepLog.ba_year == year, BrewhouseStepLog.ba_order_no == order_no,
                BrewhouseStepLog.ba_batch_no == batch_no,
            ).order_by(BrewhouseStepLog.started_at)
        ).scalars().all()

        # Gộp theo equipment_id: tổng thời gian mỗi nồi = từ lúc khác Idle (started_at bước đầu)
        # tới lúc kết thúc bước cuối (hoặc hiện tại nếu còn đang chạy) — mirror step_log_report().
        by_equipment: dict[int, dict] = {}
        for r in all_rows:
            e = by_equipment.get(r.equipment_id)
            if e is None:
                e = by_equipment[r.equipment_id] = {
                    "equipment_name": r.equipment_name, "started_at": r.started_at,
                    "ended_at": r.ended_at, "still_running": False, "data_gap": False,
                }
            e["started_at"] = min(e["started_at"], r.started_at)
            if r.data_gap:
                e["data_gap"] = True  # xem ghi chú tương tự ở step_log_report() summary_map
            if r.ended_at is None:
                e["still_running"] = True
            elif not e["still_running"]:
                e["ended_at"] = max(e["ended_at"], r.ended_at) if e["ended_at"] else r.ended_at

        vessels = []
        whirlpool_ended_at = None
        whirlpool_data_gap = False
        stage = "chua_toi_lang_xoay"
        for role_label, equip_ids in ROLE_CHAIN:
            eq_id = next((i for i in equip_ids if i in by_equipment), None)
            if eq_id is None:
                vessels.append({"role": role_label, "equipment_name": None,
                                "total_minutes": None, "still_running": False, "data_gap": False})
                continue
            e = by_equipment[eq_id]
            end_reference = now if e["still_running"] else e["ended_at"]
            total_minutes = round((end_reference - e["started_at"]).total_seconds() / 60.0, 2)
            vessels.append({"role": role_label, "equipment_name": e["equipment_name"],
                            "total_minutes": total_minutes, "still_running": e["still_running"],
                            "data_gap": e["data_gap"]})
            if role_label == WHIRLPOOL_ROLE:
                whirlpool_ended_at = None if e["still_running"] else e["ended_at"]
                whirlpool_data_gap = e["data_gap"]
                stage = "dang_lang_xoay" if e["still_running"] else "da_xong"

        # Tổng thời gian cả mẻ = Nồi lắng xoáy kết thúc - Nồi gạo bắt đầu (cùng oder/batch/year)
        # — yêu cầu người dùng 2026-11-01. Chưa xong (chưa tới/đang lắng xoáy) thì tính tạm tới
        # hiện tại, kèm cờ still_running để frontend gắn badge "đang chạy" (mirror cách tính mỗi
        # nồi ở trên, không phải tổng thật cho tới khi lắng xoáy kết thúc).
        cycle_still_running = stage != "da_xong"
        cycle_end_reference = now if cycle_still_running else whirlpool_ended_at
        cycle_minutes = round((cycle_end_reference - rice_started_at).total_seconds() / 60.0, 2)
        # Mốc bắt đầu (Nồi gạo) HOẶC kết thúc (Nồi lắng xoáy) bị gián đoạn ghi log -> tổng thời
        # gian cả mẻ cũng không đáng tin, dù 2 nồi ở giữa (chưa đổi dây) không gián đoạn.
        cycle_data_gap = vessels[0]["data_gap"] or whirlpool_data_gap

        items.append({
            "ba_year": year, "ba_order_no": order_no, "ba_batch_no": batch_no,
            "rice_started_at": rice_started_at,
            "whirlpool_ended_at": whirlpool_ended_at,
            "stage": stage,
            "vessels": vessels,
            "cycle_minutes": cycle_minutes,
            "cycle_still_running": cycle_still_running,
            "cycle_data_gap": cycle_data_gap,
        })
    return items


def brew_cycle_report(db: Session, ba_year: int = None, ba_order_no: str = None,
                      ba_batch_no: str = None, days: int = 3650) -> dict:
    """BC chu kỳ TOÀN BỘ hệ nấu: từ lúc Nồi gạo (vào nguyên liệu) BẮT ĐẦU tới lúc Nồi lắng xoáy
    (dây 1 hoặc dây 2, tuỳ mẻ chạy dây nào) KẾT THÚC, cùng 1 oder/batch/year, kèm tổng thời gian
    TỪNG NỒI trong cả chuỗi — yêu cầu người dùng 2026-11-01: "chỉ cần 2 thời gian là thời gian
    bắt đầu nồi gạo và thời điểm kết thúc nồi lắng xoáy, còn các cột còn lại thể hiện tổng thời
    gian mỗi nồi". Kèm BC sản lượng lý thuyết/ngày theo TỪNG MẺ RIÊNG (không ghép cặp 2 mẻ) —
    yêu cầu người dùng 2026-11-01 (sửa lại yêu cầu trước đó, lúc đầu hiểu nhầm là ghép cặp):
    "không phải 2 mẻ liên tiếp mà là theo từng mẻ 1, trừ nồi gạo ra, còn các nồi khác sẽ thời
    gian sẽ chia 2, do có 2 dây nấu". Lý do chia 2: mỗi nồi khác nồi gạo có 2 thiết bị vật lý
    (1/dây — xem ROLE_CHAIN), mỗi thiết bị chỉ xử lý 1 trong 2 mẻ xen kẽ, nên thời gian 1 mẻ
    chiếm dụng 1 thiết bị quy đổi ra "trên cả 2 dây" chỉ bằng 1 nửa; nồi gạo dùng chung 1 thiết
    bị cho mọi mẻ nên giữ nguyên. Báo cáo RIÊNG với step_log_report() (báo cáo đó là chi tiết
    từng BƯỚC)."""
    items = _brew_cycle_items(db, ba_year, ba_order_no, ba_batch_no, days)

    items_asc = sorted(items, key=lambda x: x["rice_started_at"])
    throughput = []
    for it in items_asc:
        vessel_adj = []
        for v in it["vessels"]:
            # Chỉ dùng thời gian ĐÃ XONG VÀ ĐÁNG TIN (không dùng số phút của bước đang chạy dở,
            # cũng không dùng số bị đánh dấu data_gap — cả 2 đều không phải tổng thật, lấy vào sẽ
            # làm sản lượng/ngày bị thổi phồng/bóp méo sai — xem GAP_THRESHOLD_SECONDS).
            if v["still_running"] or v["total_minutes"] is None or v["data_gap"]:
                adj = None
            elif v["role"] == "Nồi gạo":
                adj = v["total_minutes"]
            else:
                adj = round(v["total_minutes"] / 2.0, 2)
            vessel_adj.append({"role": v["role"], "adj_minutes": adj})
        # Chỉ tính nút thắt cổ chai/số mẻ-ngày khi có ĐỦ thời gian của TẤT CẢ các nồi trong chuỗi
        # — thiếu bất kỳ nồi nào (chưa đủ dữ liệu/mẻ đang chạy dở) thì để "—", không tính từ dữ
        # liệu không đầy đủ (yêu cầu người dùng 2026-11-01).
        has_all = all(v["adj_minutes"] is not None for v in vessel_adj)
        max_minutes = max(v["adj_minutes"] for v in vessel_adj) if has_all else None
        throughput.append({
            "batch": {"ba_year": it["ba_year"], "ba_order_no": it["ba_order_no"], "ba_batch_no": it["ba_batch_no"]},
            "vessels": vessel_adj,
            "max_minutes": max_minutes,
            "batches_per_day": round((24 * 60) / max_minutes, 2) if max_minutes else None,
        })
    throughput.reverse()  # mới nhất lên đầu, mirror thứ tự items bên dưới

    items.sort(key=lambda x: x["rice_started_at"], reverse=True)
    return {"items": items, "throughput": throughput, "roles": [role_label for role_label, _ in ROLE_CHAIN]}
