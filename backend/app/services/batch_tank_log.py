"""Ghi chép lên men cho BatchTank (Mẻ SX) — mirror services/ferment_log.py (module
Nấu-Lọc-Chiết cũ, biểu mẫu giấy BM 1.11 (06) BIỂU THEO DÕI LÊN MEN).

Không có import Braumat/BrewOrder tương ứng cho pipeline mới (BatchExecution không có khái
niệm Braumat step) — auto_header_values chỉ lấy phần thật sự có sẵn ở BatchTank (số mẻ đã gộp,
tank vật lý, thể tích), khác ferment_log.py có thêm braumat_order_number/brew_order_code."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..common import new_id, utcnow
from ..errors import DomainError
from ..models.batch_pipeline import (
    BatchTank,
    BatchTankDailyReading,
    BatchTankLink,
    BatchTankProcessLog,
)
from ..models.batches import BatchExecution
from ..security import User, require_perm


def _assert_tank_unlocked(db: Session, tank_id: str) -> None:
    """Tank có thể đã bị khóa qua services/ebr.py::lock_pack_lot (cascade khi khóa hồ sơ EBR lô
    thành phẩm) — ghi chép lên men (bảng thông tin đầu + theo ngày) trước đây không kiểm tra gì
    cả, sửa được vô hạn dù đã khóa hồ sơ (yêu cầu người dùng 2026-09-01)."""
    tank = db.get(BatchTank, tank_id)
    if tank and tank.locked:
        raise DomainError("Bản ghi đã bị khóa — không thể sửa.")

# Mirror ferment_log.py::HEADER_FIELDS — cùng bộ field, cùng ý nghĩa vật lý (tank lên men).
HEADER_FIELDS = [
    ("order_number", "Order Number", "text"),
    ("batch_number", "Batch Number", "text"),
    ("kieu_men", "Kiểu men", "text"),
    ("luu_luong_khi_bs", "Lưu lượng khí bổ sung, Lít/Phút", "num"),
    ("mat_do_ml_b", "Mật độ tế bào, 10⁶/ml (B)", "num"),
    ("pct_song_c", "% tế bào sống (C)", "num"),
    ("kg_can_cap_d", "Khối lượng men cần cấp, kg (D)", "num"),
    ("mat_do_ban_dau_e", "Mật độ ban đầu, 10⁶/ml (E)", "num"),
    ("kg_cap_thuc_j", "Khối lượng men cấp thực, kg (J)", "num"),
    ("mat_do_tach_f", "Tách men — mật độ, 10⁶/ml (F)", "num"),
    ("tach_men_kg_g", "Tách men — khối lượng, kg (G)", "num"),
    ("tach_men_pct_song", "Tách men — % tế bào sống", "num"),
    ("day_full_at", "Đầy (giờ, ngày)", "text"),
    ("nguoi_lenh_day", "Người lệnh (đầy tank)", "text"),
    ("nguoi_nhan_lenh_day", "Người nhận lệnh (đầy tank)", "text"),
    ("truc_ca_day", "Trực ca (đầy tank)", "text"),
]

MANUAL_FIELD_KEYS: list[str] = [key for key, _label, _kind in HEADER_FIELDS]
LIST_FIELD_KEYS = ["ha_phu_events"]


def _load_json_dict(text: str | None) -> dict:
    try:
        return json.loads(text) if text else {}
    except ValueError:
        return {}


def get_or_create_process_log(db: Session, tank_id: str) -> BatchTankProcessLog:
    log = db.execute(
        select(BatchTankProcessLog).where(BatchTankProcessLog.tank_id == tank_id)
    ).scalar_one_or_none()
    if not log:
        log = BatchTankProcessLog(log_id=new_id(), tank_id=tank_id, updated_at=utcnow())
        db.add(log)
        db.commit()
        db.refresh(log)
    return log


def get_manual_values(log: BatchTankProcessLog) -> dict:
    stored = _load_json_dict(log.manual_json)
    return {k: stored.get(k) for k in MANUAL_FIELD_KEYS}


def get_ha_phu_events(log: BatchTankProcessLog) -> list:
    stored = _load_json_dict(log.manual_json)
    return stored.get("ha_phu_events") or []


def auto_header_values(db: Session, tank: BatchTank) -> dict:
    """Phần tự động lấy từ BatchTank có sẵn — KHÔNG lưu riêng, tính lại mỗi lần GET."""
    batch_ids = [l.batch_id for l in db.execute(
        select(BatchTankLink).where(BatchTankLink.tank_id == tank.tank_id)).scalars().all()]
    batches = db.execute(
        select(BatchExecution).where(BatchExecution.batch_id.in_(batch_ids))).scalars().all() if batch_ids else []
    return {
        "so_me": ", ".join(b.batch_code for b in batches) or None,
        "so_tank": tank.tank_lm,
        "the_tich_tank": tank.volume_hl,
    }


def update_process_log(db: Session, tank_id: str, payload: dict, user: User) -> BatchTankProcessLog:
    require_perm(user, "batch.execute")
    _assert_tank_unlocked(db, tank_id)
    log = get_or_create_process_log(db, tank_id)
    values = _load_json_dict(log.manual_json)
    if "note" in payload:
        log.note = payload["note"]
    if "ha_phu_events" in payload:
        events = payload["ha_phu_events"]
        if events is None:
            values.pop("ha_phu_events", None)
        else:
            # Đóng dấu người/lúc lưu cho từng mốc có thời điểm — mirror measured_by/measured_at
            # ở bảng theo ngày (upsert_daily_readings): ai bấm "Lưu mốc hạ phụ" thì đứng tên cho
            # MỌI mốc có "at" trong lần lưu đó (không cần xác nhận riêng của người lệnh/nhận lệnh/
            # trực ca — yêu cầu người dùng 2026-09-01, đã bỏ 3 field đó khỏi giao diện).
            now = utcnow()
            for ev in events:
                if ev.get("at") is not None:
                    ev["recorded_by"] = user.username
                    ev["recorded_at"] = now.isoformat()
                else:
                    ev.pop("recorded_by", None)
                    ev.pop("recorded_at", None)
            values["ha_phu_events"] = events
    for key, value in payload.items():
        if key in ("note", "ha_phu_events") or key not in MANUAL_FIELD_KEYS:
            continue
        if value is None:
            values.pop(key, None)
        else:
            values[key] = value
    log.manual_json = json.dumps(values, ensure_ascii=False)
    log.updated_by = user.username
    log.updated_at = utcnow()
    db.commit()
    db.refresh(log)
    return log


def get_daily_readings(db: Session, tank_id: str) -> list[BatchTankDailyReading]:
    return list(db.execute(
        select(BatchTankDailyReading)
        .where(BatchTankDailyReading.tank_id == tank_id)
        .order_by(BatchTankDailyReading.day_no)
    ).scalars().all())


def upsert_daily_readings(db: Session, tank_id: str, rows: list[dict], user: User) -> list[BatchTankDailyReading]:
    require_perm(user, "batch.execute")
    _assert_tank_unlocked(db, tank_id)
    now = utcnow()
    for row in rows:
        reading = db.execute(
            select(BatchTankDailyReading).where(
                BatchTankDailyReading.tank_id == tank_id,
                BatchTankDailyReading.day_no == row["day_no"],
            )
        ).scalar_one_or_none()
        if not reading:
            reading = BatchTankDailyReading(reading_id=new_id(), tank_id=tank_id, day_no=row["day_no"])
            db.add(reading)
        reading.reading_date = row.get("reading_date")
        reading.nhiet_do_c = row.get("nhiet_do_c")
        reading.do_s = row.get("do_s")
        reading.mat_do_tb = row.get("mat_do_tb")
        if any(v is not None for v in (reading.nhiet_do_c, reading.do_s, reading.mat_do_tb)):
            reading.measured_by = user.username
            reading.measured_at = now
        else:
            reading.measured_by = None
            reading.measured_at = None
        reading.kcs = row.get("kcs")
        if reading.kcs is not None:
            reading.kcs_by = user.username
            reading.kcs_at = now
        else:
            reading.kcs_by = None
            reading.kcs_at = None
        reading.truc_ca = row.get("truc_ca")
        if reading.truc_ca is not None:
            reading.truc_ca_by = user.username
            reading.truc_ca_at = now
        else:
            reading.truc_ca_by = None
            reading.truc_ca_at = None
    db.commit()
    return get_daily_readings(db, tank_id)
