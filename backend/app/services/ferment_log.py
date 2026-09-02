"""Ghi chép lên men — biểu mẫu giấy BM 1.11 (06) BIỂU THEO DÕI LÊN MEN.

Không có import PDF Braumat (chưa có file mẫu cho lên men, xem HEADER_FIELDS/tab import ở
frontend) — chỉ nhập tay: (a) bảng thông tin đầu (Kiểu men, mật độ B/C/D/E/F/G/J, lưu lượng
khí bs, tách men, mốc "Hạ phụ") dồn vào FermentProcessLog.manual_json giống cách
services/braumat_import.py làm với BrewProcessLog.manual_json; (b) bảng theo ngày (nhiệt
độ/°S/mật độ tế bào/CN vận hành/KCS/trực ca) lưu ở bảng con FermentDailyReading để vẽ biểu
đồ theo services/braumat_import.py không có tương đương (không cần bảng step tự động)."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..common import new_id, utcnow
from ..models.brewing import (
    BrewBatch,
    BrewOrder,
    BrewProcessLog,
    BrewRecord,
    FermentBrewLink,
    FermentDailyReading,
    FermentProcessLog,
    FermentRecord,
)
from ..security import User, require_perm

# Mỗi field: (key, nhãn, kind). kind: "num"|"text". Không có "has_spec" như Ghi chép nấu vì
# không có Quy định (Product.spec_json) tương ứng cho các trường này.
# order_number/batch_number là nhân viên tự ghi tay — mirror BF_HEADER_FIELDS (Ghi chép nấu):
# giá trị Braumat lấy từ mẻ nấu nguồn (auto_header_values) chỉ hiện kèm làm gợi ý đối chiếu
# (không phải mọi mẻ nấu nguồn đều có import Braumat, nên không thể chỉ dựa vào giá trị này).
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

# "ha_phu_events" là 1 list (mốc "Hạ phụ" có thể lặp lại nhiều lần) — client gửi lại nguyên
# mảng khi lưu, không patch từng phần tử như các key vô hướng ở trên.
LIST_FIELD_KEYS = ["ha_phu_events"]


def _load_json_dict(text: str | None) -> dict:
    try:
        return json.loads(text) if text else {}
    except ValueError:
        return {}


def get_or_create_process_log(db: Session, ferment_id: str) -> FermentProcessLog:
    log = db.execute(
        select(FermentProcessLog).where(FermentProcessLog.ferment_id == ferment_id)
    ).scalar_one_or_none()
    if not log:
        log = FermentProcessLog(log_id=new_id(), ferment_id=ferment_id, updated_at=utcnow())
        db.add(log)
        db.commit()
        db.refresh(log)
    return log


def get_manual_values(log: FermentProcessLog) -> dict:
    """Trả về đủ mọi key HEADER_FIELDS (None nếu chưa nhập) — để FE luôn render đủ ô nhập."""
    stored = _load_json_dict(log.manual_json)
    return {k: stored.get(k) for k in MANUAL_FIELD_KEYS}


def get_ha_phu_events(log: FermentProcessLog) -> list:
    stored = _load_json_dict(log.manual_json)
    return stored.get("ha_phu_events") or []


def _braumat_fields_for_ferment(db: Session, ferment_id: str) -> tuple[str | None, str | None]:
    """Tổng hợp Order Number/Batch Number THẬT lấy từ Braumat (BrewProcessLog.
    braumat_order_number/braumat_batch_number, ghi tự động lúc import Step Protocol PDF —
    xem services/braumat_import.py::import_step_protocols) của TẤT CẢ mẻ (BrewBatch) thuộc
    TẤT CẢ mã nấu (BrewRecord) đã liên kết vào lô LM này (FermentBrewLink) — 1 lô LM có thể
    gồm nhiều mã nấu, mỗi mã nấu nhiều mẻ, mỗi mẻ tự import Braumat riêng nên có thể ra
    nhiều giá trị khác nhau — gộp thành 1 chuỗi duy nhất (cách nhau bằng dấu phẩy), bỏ
    trùng, giữ thứ tự xuất hiện."""
    brew_ids = [r[0] for r in db.execute(
        select(FermentBrewLink.brew_id).where(FermentBrewLink.ferment_id == ferment_id)).all()]
    if not brew_ids:
        return None, None
    batch_ids = [r[0] for r in db.execute(
        select(BrewBatch.batch_id).where(BrewBatch.brew_id.in_(brew_ids))).all()]
    if not batch_ids:
        return None, None
    logs = db.execute(select(BrewProcessLog).where(BrewProcessLog.batch_id.in_(batch_ids))).scalars().all()
    order_numbers: list[str] = []
    batch_numbers: list[str] = []
    for log in logs:
        if log.braumat_order_number and log.braumat_order_number not in order_numbers:
            order_numbers.append(log.braumat_order_number)
        if log.braumat_batch_number and log.braumat_batch_number not in batch_numbers:
            batch_numbers.append(log.braumat_batch_number)
    return (", ".join(order_numbers) or None), (", ".join(batch_numbers) or None)


def _brew_order_codes_for_ferment(db: Session, ferment_id: str) -> str | None:
    """Số Lệnh nấu (BrewOrder.order_code) của TẤT CẢ mã nấu (BrewRecord) đã liên kết vào lô
    LM này (FermentBrewLink) — 1 lô LM có thể gồm nhiều mã nấu, mỗi mã nấu ứng với ĐÚNG 1
    Lệnh nấu (brew_order_id, nullable với mã nấu tạo trước khi có Lệnh nấu) — gộp thành 1
    chuỗi (cách nhau dấu phẩy), bỏ trùng, giữ thứ tự xuất hiện, mirror cách gộp Braumat Order
    Number ở _braumat_fields_for_ferment."""
    brew_ids = [r[0] for r in db.execute(
        select(FermentBrewLink.brew_id).where(FermentBrewLink.ferment_id == ferment_id)).all()]
    if not brew_ids:
        return None
    brew_order_ids = [r[0] for r in db.execute(
        select(BrewRecord.brew_order_id).where(BrewRecord.brew_id.in_(brew_ids),
                                                BrewRecord.brew_order_id.isnot(None))).all()]
    if not brew_order_ids:
        return None
    codes: list[str] = []
    for order_id in brew_order_ids:
        order = db.get(BrewOrder, order_id)
        if order and order.order_code not in codes:
            codes.append(order.order_code)
    return ", ".join(codes) or None


def auto_header_values(db: Session, ferment: FermentRecord) -> dict:
    """Phần tự động lấy từ FermentRecord có sẵn — KHÔNG lưu riêng, tính lại mỗi lần GET.
    kt_date (ngày KT/kết thúc nấu) dùng để FE tính mặc định 20 ngày cho bảng theo ngày.
    braumat_order_number/braumat_batch_number lấy THẬT từ dữ liệu Braumat đã import ở các
    mẻ nấu nguồn (xem _braumat_fields_for_ferment) — không phải nhập tay. brew_order_code
    (Số Lệnh nấu) lấy từ BrewOrder qua mã nấu nguồn (xem _brew_order_codes_for_ferment)."""
    order_number, batch_number = _braumat_fields_for_ferment(db, ferment.ferment_id)
    return {
        "so_me": ferment.batch_numbers,
        "so_tank": ferment.tank_lm,
        "the_tich_tank": ferment.volume_hl,
        "the_he": ferment.yeast_gen,
        "kt_date": ferment.kt_date,
        "braumat_order_number": order_number,
        "braumat_batch_number": batch_number,
        "brew_order_code": _brew_order_codes_for_ferment(db, ferment.ferment_id),
    }


def update_process_log(db: Session, ferment_id: str, payload: dict, user: User) -> FermentProcessLog:
    require_perm(user, "batch.execute")
    log = get_or_create_process_log(db, ferment_id)
    values = _load_json_dict(log.manual_json)
    if "note" in payload:
        log.note = payload["note"]
    if "ha_phu_events" in payload:
        events = payload["ha_phu_events"]
        if events is None:
            values.pop("ha_phu_events", None)
        else:
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


def get_daily_readings(db: Session, ferment_id: str) -> list[FermentDailyReading]:
    return list(db.execute(
        select(FermentDailyReading)
        .where(FermentDailyReading.ferment_id == ferment_id)
        .order_by(FermentDailyReading.day_no)
    ).scalars().all())


def upsert_daily_readings(db: Session, ferment_id: str, rows: list[dict], user: User) -> list[FermentDailyReading]:
    """Ghi đè cả bảng theo ngày (client gửi lại toàn bộ cột đang có) — mỗi nhóm trường (đo đạc
    nhiệt độ/°S/mật độ tb, KCS, trực ca) tự ghi "by/at" khi nhóm đó có giá trị (không nhập tay
    tên người/giờ) — xoá "by/at" nếu người dùng xoá hết giá trị của nhóm đó."""
    require_perm(user, "batch.execute")
    now = utcnow()
    for row in rows:
        reading = db.execute(
            select(FermentDailyReading).where(
                FermentDailyReading.ferment_id == ferment_id,
                FermentDailyReading.day_no == row["day_no"],
            )
        ).scalar_one_or_none()
        if not reading:
            reading = FermentDailyReading(reading_id=new_id(), ferment_id=ferment_id, day_no=row["day_no"])
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
    return get_daily_readings(db, ferment_id)
