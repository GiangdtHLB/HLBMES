"""Import Step Protocol PDF (hệ điều khiển nấu Braumat) vào ghi chép nấu (BrewProcessStep).

Mỗi file PDF xuất ra từ Braumat là 1 "process cell" — có thể chứa 1 hoặc nhiều Unit
(trạm công đoạn: RiceCooker, MashTun, LauterTun, WortKettle, WK2 HOP1/2, SpentGrain,
WhirlPool...), mỗi Unit là 1 danh sách bước (step) tự động, mỗi bước có nhiều tham số
dạng (label, giá trị đặt setpoint, giá trị thực actual). File có thể trải nhiều trang
(1 unit tiếp tục sang trang sau) và nhiều unit trong cùng 1 file.

Bản PDF không mang layout dạng bảng chuẩn (pypdf trích text thuần sẽ dính liền các số
liệu không phân tách được, VD "23" + "23" -> "2323"), nên phải trích theo toạ độ
(visitor_text trả về text matrix) rồi tự dựng lại bảng theo cột x cố định của mẫu báo
cáo. Đã đối chiếu từng giá trị với 9 file Step Protocol thật (RiceCooker, MashTun,
LauterTun, WortKettle+2 vòi hoa, SpentGrain, WhirlPool, Start BH) — khớp tuyệt đối.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from io import BytesIO

import pypdf
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..common import new_id, utcnow
from ..errors import DomainError, NotFoundError
from ..models.brewing import BrewBatch, BrewProcessLog, BrewProcessStep
from ..models.master import Product
from ..security import User, require_perm

TOP_LABELS = ("Order Number", "Recipe category", "Recipe", "Batch Number", "Unit")
COL_KEYS = ("col1", "col2", "col3", "col4")


def _bin_x(x: float) -> str:
    """Phân vùng toạ độ x của báo cáo Braumat thành các 'cột' ngữ nghĩa cố định —
    vị trí này do mẫu báo cáo quy định, không đổi giữa các Unit/công thức khác nhau."""
    if x < 1500:
        return "stepno"
    if x < 2500:
        return "eop"
    if x < 7000:
        return "name"
    if x < 7800:
        return "date"
    if x < 9700:
        return "time"
    if x < 11500:
        return "elapsed"
    if x < 15500:
        return "col1"
    if x < 19500:
        return "col2"
    if x < 22500:
        return "col3"
    if x < 26500:
        return "col4"
    return "other"


def _extract_rows(page) -> list[dict]:
    """Trích các đoạn text kèm toạ độ, gom theo hàng (cùng y) rồi phân theo cột x."""
    items = []

    def visitor(text, cm, tm, font, font_size):
        if text.strip():
            items.append((round(tm[5], 1), round(tm[4], 1), text.strip()))

    page.extract_text(visitor_text=visitor)
    rows: dict[float, list[tuple[float, str]]] = {}
    for y, x, t in items:
        rows.setdefault(y, []).append((x, t))
    out = []
    for y in sorted(rows.keys()):
        binned: dict[str, list[str]] = {}
        for x, t in sorted(rows[y]):
            binned.setdefault(_bin_x(x), []).append(t)
        out.append(binned)
    return out


class _ContinuationGroup:
    """Với bước có >4 tham số, các tham số 5+ lặp lại đúng 4 cột trên nhưng KHÔNG có
    step_no/date/time — theo chu kỳ 3 hàng: nhãn -> hàng trên (giá trị đặt setpoint) ->
    hàng dưới (giá trị thực actual, cùng thời điểm với elapsed_actual/end_at của bước).
    Người dùng đã đối chiếu lại trực tiếp trên số liệu thật: giá trị THỰC TẾ của tham số
    luôn khớp với thời gian/kết thúc thực tế của bước (VD "Time RC1 [Min.]" ở hàng dưới
    ≈ elapsed_actual) — nên hàng dưới (có date/time kết thúc) mới là Thực tế, hàng trên
    là Setpoint."""

    def __init__(self):
        self.labels: dict[str, str | None] | None = None
        self.awaiting = "label"

    def feed(self, binned: dict, cur_step: dict) -> None:
        if self.awaiting == "label":
            self.labels = {c: binned.get(c, [None])[0] for c in COL_KEYS}
            self.awaiting = "row1"
        elif self.awaiting == "row1":
            for c in COL_KEYS:
                label = self.labels.get(c)
                if label and c in binned:
                    cur_step["params"].setdefault(label, {})["setpoint"] = binned[c][0]
            self.awaiting = "row2"
        else:
            for c in COL_KEYS:
                label = self.labels.get(c)
                if label and c in binned:
                    cur_step["params"].setdefault(label, {})["actual"] = binned[c][0]
            self.awaiting = "label"
            self.labels = None


def parse_step_protocol_pdf(data: bytes) -> dict:
    """Phân tích 1 file Step Protocol PDF -> {order_number, recipe_category, recipe,
    batch_number, units: {tên_unit: [step, ...]}}. Mỗi step:
    {step_no, eop, name, start, end, elapsed_actual, params: {nhãn: {setpoint, actual}}}."""
    reader = pypdf.PdfReader(BytesIO(data))
    pages_rows = [_extract_rows(page) for page in reader.pages]
    return _parse_row_stream(pages_rows)


def _parse_row_stream(pages_rows: list[list[dict]]) -> dict:
    """Lõi phân tích, tách riêng khỏi việc đọc PDF để có thể unit-test bằng các hàng
    (binned dict) dựng tay, không cần file PDF thật."""
    units: dict[str, list[dict]] = {}
    order_number = recipe_category = recipe = batch_number = None
    cur_unit = None
    cur_step = None
    primary_labels = None
    primary_stage = None  # "setpoint" | "actual" | None
    group: _ContinuationGroup | None = None

    def finalize_step():
        nonlocal cur_step
        if cur_step and cur_unit:
            units.setdefault(cur_unit, []).append(cur_step)
        cur_step = None

    for rows in pages_rows:
        for binned in rows:
            first = binned.get("stepno", [None])[0]

            if first in TOP_LABELS:
                all_txt = []
                for k in ("stepno", "eop", "name", "date", "time", "elapsed", *COL_KEYS):
                    all_txt.extend(binned.get(k, []))
                value = next((t for t in all_txt if t not in (first, ":")), None)
                if first == "Order Number":
                    order_number = value
                elif first == "Recipe category":
                    recipe_category = value
                elif first == "Recipe":
                    recipe = value
                elif first == "Batch Number":
                    batch_number = value
                elif first == "Unit":
                    finalize_step()
                    cur_unit = value
                    primary_labels = None
                    primary_stage = None
                    group = None
                continue

            if first in ("Step", "No."):
                continue
            if any("Customer" in t or "Plant" in t for t in binned.get("stepno", [])):
                continue

            if first is not None and re.fullmatch(r"\d+", first):
                finalize_step()
                cur_step = {
                    "step_no": int(first),
                    "eop": binned.get("eop", [None])[0],
                    "name": binned.get("name", [None])[0],
                    "start": f"{binned.get('date', [None])[0]} {binned.get('time', [None])[0]}",
                    "end": None, "elapsed_actual": None,
                    "params": {},
                }
                primary_labels = {c: binned.get(c, [None])[0] for c in COL_KEYS}
                primary_stage = "row1"
                group = None
                continue

            if cur_step is None:
                continue

            has_date = "date" in binned
            has_elapsed = "elapsed" in binned

            # Hàng trên (row1, không có date) = giá trị SETPOINT; hàng dưới (row2, có
            # date/time kết thúc) = giá trị THỰC TẾ — khớp với elapsed_actual/end_at của
            # bước (cùng lấy từ hàng này), đã đối chiếu số liệu thật với người dùng.
            if primary_stage == "row1" and has_elapsed and not has_date:
                for c in COL_KEYS:
                    label = primary_labels.get(c)
                    if label and c in binned:
                        cur_step["params"].setdefault(label, {})["setpoint"] = binned[c][0]
                primary_stage = "row2"
                continue

            if primary_stage == "row2" and has_date:
                cur_step["end"] = f"{binned['date'][0]} {binned.get('time', [None])[0]}"
                cur_step["elapsed_actual"] = binned.get("elapsed", [None])[0]
                for c in COL_KEYS:
                    label = primary_labels.get(c)
                    if label and c in binned:
                        cur_step["params"].setdefault(label, {})["actual"] = binned[c][0]
                primary_stage = None
                continue

            if any(k in binned for k in COL_KEYS) and not has_date and not has_elapsed:
                if group is None:
                    group = _ContinuationGroup()
                group.feed(binned, cur_step)
                continue

        finalize_step()

    finalize_step()
    return {
        "order_number": order_number, "recipe_category": recipe_category,
        "recipe": recipe, "batch_number": batch_number, "units": units,
    }


def _parse_braumat_dt(text: str | None) -> datetime | None:
    """'10.07.26 03:01:37' (DD.MM.YY HH:MM:SS) -> datetime. None nếu thiếu dữ liệu."""
    if not text or "None" in text:
        return None
    try:
        return datetime.strptime(text.strip(), "%d.%m.%y %H:%M:%S")
    except ValueError:
        return None


# ---- Gộp import nhiều file PDF vào ghi chép của 1 mẻ (BrewBatch) ----

def import_step_protocols(db: Session, batch_id: str, files: list[tuple[str, bytes]], user: User) -> dict:
    """Phân tích 1 hoặc nhiều file Step Protocol PDF và lưu thành BrewProcessStep cho mẻ
    `batch_id`. Mỗi Unit trong file được import thay thế toàn bộ (xoá step cũ của cùng
    Unit trước khi ghi lại) — cho phép import lại khi có file mới/sửa lỗi. Không bắt
    buộc Batch Number trong PDF phải trùng batch_code của mẻ (số hiệu Braumat có thể
    không đồng bộ 1:1 với mã mẻ trong MES) — chỉ chặn khi các file tải lên CHÍNH CHÚNG
    mâu thuẫn nhau (thuộc các Batch Number khác nhau, dấu hiệu nhầm mẻ)."""
    require_perm(user, "batch.execute")
    batch = db.get(BrewBatch, batch_id)
    if not batch:
        raise NotFoundError("Mẻ không tồn tại.")

    parsed_files = []
    skipped = []  # files with no unit/step data — vd trang "Process cell overview" đầu tiên
    batch_numbers_seen = set()
    for filename, data in files:
        try:
            parsed = parse_step_protocol_pdf(data)
        except Exception as e:
            raise DomainError(f"Không đọc được file '{filename}' — không đúng định dạng Step Protocol PDF ({e}).")
        if not parsed["units"]:
            skipped.append(filename)
            continue
        if parsed["batch_number"]:
            batch_numbers_seen.add(parsed["batch_number"])
        parsed_files.append((filename, parsed))

    if not parsed_files:
        raise DomainError("Không có file nào chứa dữ liệu bước công đoạn (có thể chỉ tải lên trang tổng quan).")

    if len(batch_numbers_seen) > 1:
        raise DomainError(
            f"Các file tải lên thuộc các Batch Number khác nhau ({', '.join(sorted(batch_numbers_seen))}) "
            "— có thể đã chọn nhầm file của mẻ khác."
        )

    warning = None
    imported_batch_number = next(iter(batch_numbers_seen), None)
    if imported_batch_number and imported_batch_number != batch.batch_code:
        warning = (f"Batch Number trong file ({imported_batch_number}) khác mã mẻ trong hệ thống "
                   f"({batch.batch_code}) — đã import nhưng vui lòng kiểm tra lại đúng mẻ.")

    units_imported = {}
    order_number = recipe = None
    for filename, parsed in parsed_files:
        order_number = order_number or parsed["order_number"]
        recipe = recipe or parsed["recipe"]
        for unit, steps in parsed["units"].items():
            for old in db.execute(select(BrewProcessStep).where(
                    BrewProcessStep.batch_id == batch_id, BrewProcessStep.unit == unit)).scalars().all():
                db.delete(old)
            for s in steps:
                db.add(BrewProcessStep(
                    step_id=new_id(), batch_id=batch_id, unit=unit, step_no=s["step_no"],
                    eop=s["eop"], name=s["name"],
                    start_at=_parse_braumat_dt(s["start"]), end_at=_parse_braumat_dt(s["end"]),
                    elapsed_actual=s["elapsed_actual"], params_json=json.dumps(s["params"], ensure_ascii=False),
                    imported_at=utcnow(), imported_by=user.username,
                ))
            units_imported[unit] = units_imported.get(unit, 0) + len(steps)

    log = get_or_create_process_log(db, batch_id)
    if order_number:
        log.braumat_order_number = order_number
    if recipe:
        log.braumat_recipe = recipe
    if imported_batch_number:
        log.braumat_batch_number = imported_batch_number
    db.commit()
    return {"units": units_imported, "order_number": order_number, "recipe": recipe,
            "batch_number": imported_batch_number, "warning": warning, "skipped_files": skipped}


# Thứ tự công đoạn thật của dây nấu (không phải alphabet) — dùng để sắp xếp hiển thị khi
# xem "tất cả unit". Khớp theo substring (không phân biệt hoa/thường) nên vẫn nhận đúng
# các biến thể có số hiệu nồi/dây (VD "Holding Vessel 01" và "Holding Vessel 02" — nhà máy
# có 2 dây nấu, mỗi dây có nồi trung gian riêng — vẫn giữ nguyên tên gốc kèm số hiệu để
# phân biệt khi chạy báo cáo sau này, chỉ gộp chung thứ tự hiển thị).
UNIT_ORDER_KEYWORDS = (
    "RiceCooker", "MashTun", "LauterTun", "SpentGrain", "Holding",
    "WortKettle", "HOP1", "HOP2", "Whirl",
)


def _unit_rank(unit: str | None) -> int:
    u = (unit or "").lower()
    for i, kw in enumerate(UNIT_ORDER_KEYWORDS):
        if kw.lower() in u:
            return i
    return len(UNIT_ORDER_KEYWORDS)


def list_process_steps(db: Session, batch_id: str) -> list[dict]:
    rows = db.execute(
        select(BrewProcessStep).where(BrewProcessStep.batch_id == batch_id)
        .order_by(BrewProcessStep.unit, BrewProcessStep.start_at, BrewProcessStep.step_no)
    ).scalars().all()
    out = []
    for r in rows:
        try:
            params = json.loads(r.params_json) if r.params_json else {}
        except ValueError:
            params = {}
        out.append({"step_id": r.step_id, "unit": r.unit, "step_no": r.step_no, "eop": r.eop,
                    "name": r.name, "start_at": r.start_at, "end_at": r.end_at,
                    "elapsed_actual": r.elapsed_actual, "params": params})
    out.sort(key=lambda s: (_unit_rank(s["unit"]), s["unit"] or "", s["start_at"] or datetime.min, s["step_no"]))
    return out


def _find_step(steps: list[dict], name_substr: str):
    return next((s for s in steps if name_substr.lower() in (s["name"] or "").lower()), None)


def _param(step: dict | None, label: str, kind: str = "actual"):
    if not step:
        return None
    return step["params"].get(label, {}).get(kind)


def checkpoint_summary(steps: list[dict]) -> dict:
    """Tự động rút ra các mốc quan trọng (nhiệt độ/thời gian/khối lượng) từ các bước đã
    import — chỉ mang tính tham khảo hiển thị cạnh form ghi chép tay, không lưu lại
    (tính lại từ BrewProcessStep mỗi lần xem, luôn khớp dữ liệu import mới nhất)."""
    mash_in_rice = _find_step(steps, "Mash in Rice")
    rc_heat_up = _find_step(steps, "RC1 Heat Up")
    rc_rest = _find_step(steps, "RC1 Rest")
    mt_start_check = _find_step(steps, "MT2 Start Check")
    first_wort = _find_step(steps, "First Wort")
    second_wort = _find_step(steps, "SecondWort")
    hop1 = _find_step(steps, "Hop01 Filling")
    hop2 = _find_step(steps, "Hop02 Filling")
    whirlpool_receive = _find_step(steps, "Receive WK")
    boiling_steps = [s for s in steps if "boiling" in (s["name"] or "").lower() and "without" not in s["name"].lower()]
    mt_rests = [s for s in steps if (s["name"] or "").strip().lower().startswith("mt") and
               (s["name"] or "").strip().lower().endswith("rest")]

    return {
        "rice_cooker": {
            "rice_weight_kg": _param(mash_in_rice, "Rice Weight [Kg]"),
            "mash_in_temp_c": _param(mash_in_rice, "RC Temperature [oC]"),
            "heat_up_temp_c": _param(rc_heat_up, "RC Temperature [oC]"),
            "heat_up_elapsed": rc_heat_up["elapsed_actual"] if rc_heat_up else None,
            "rest_temp_c": _param(rc_rest, "RC Temperature [oC]"),
            "rest_elapsed": rc_rest["elapsed_actual"] if rc_rest else None,
        },
        "mash_tun": {
            "malt_weight_kg": _param(mt_start_check, "Weight MT2 [kg]"),
            "rests": [{"name": s["name"], "temp_c": _param(s, "02.03TET01N [oC]"),
                      "elapsed": s["elapsed_actual"], "start_at": s["start_at"], "end_at": s["end_at"]}
                     for s in mt_rests],
        },
        "lauter_tun": {
            "first_wort_hl": _param(first_wort, "LT2 FirsWort [hl]"),
            "second_wort_hl": _param(second_wort, "LT2 SeconWort [hl]"),
            "water_sparge_hl": _param(second_wort, "LT2 WaterSparge [hl]"),
        },
        "wort_kettle": {
            "boiling_total_elapsed_min": round(sum(
                _elapsed_to_minutes(s["elapsed_actual"]) for s in boiling_steps), 1),
            "hop1_time": hop1["elapsed_actual"] if hop1 else None,
            "hop2_time": hop2["elapsed_actual"] if hop2 else None,
        },
        "whirlpool": {
            "receive_elapsed": whirlpool_receive["elapsed_actual"] if whirlpool_receive else None,
        },
    }


def _elapsed_to_minutes(elapsed: str | None) -> float:
    if not elapsed:
        return 0.0
    parts = elapsed.split(":")
    if len(parts) != 3:
        return 0.0
    h, m, s = (int(p) for p in parts)
    return h * 60 + m + s / 60


def get_or_create_process_log(db: Session, batch_id: str) -> BrewProcessLog:
    log = db.execute(select(BrewProcessLog).where(BrewProcessLog.batch_id == batch_id)).scalar_one_or_none()
    if not log:
        log = BrewProcessLog(log_id=new_id(), batch_id=batch_id, updated_at=utcnow())
        db.add(log)
        db.commit()
        db.refresh(log)
    return log


# ===== Biểu mẫu công nghệ nấu đầy đủ (khớp giấy QT-KCS-QT-BM-05) =====
# Mỗi field: (key, nhãn, kind, has_spec). kind: "num"|"text"|"bool". has_spec=True nghĩa
# là field có cặp Quy định (Product.spec_json, admin/master.manage sửa) — Thực hiện
# (BrewProcessLog.manual_json, vận hành/batch.execute sửa) — dùng CHUNG 1 key giữa 2 JSON
# blob khác nhau để dễ đối chiếu. Field has_spec=False chỉ ghi Thực hiện (không có tiêu
# chuẩn cố định, hoặc Quy định đã in thẳng trong nhãn, VD "pH (5,2 - 5,6)").
HEADER_FIELDS = [
    # batch_number/order_number/gio_bat_dau/gio_ket_thuc là do nhân viên tự ghi tay lên
    # biểu mẫu (giống bản giấy gốc) — KHÔNG lấy từ batch_code/braumat_order_number/thời
    # gian tính từ BrewProcessStep, vì nhân viên ghi trước khi import Braumat, KCS sau đó
    # đối chiếu 2 nguồn.
    ("batch_number", "Batch number", "text", False),
    ("order_number", "Order Number", "text", False),
    ("gio_bat_dau", "Bắt đầu", "text", False),
    ("gio_ket_thuc", "Kết thúc", "text", False),
    ("ka", "Ca", "text", False),
    ("truc_ca", "Trực ca", "text", False),
    ("nau_chinh", "Nấu chính", "text", False),
    ("ngay_nhap_gao", "Ngày nhập gạo", "text", False),
    ("ngay_nhap_malt", "Ngày nhập malt", "text", False),
    ("silo", "Silo", "text", False),
]

RC_FIELDS = [
    ("rc_gao_truoc_kg", "Nghiền gạo ướt — trước (kg)", "num", False),
    ("rc_gao_sau_kg", "Nghiền gạo ướt — sau (kg)", "num", False),
    ("rc_bot_gao_kg", "Bột Gạo (kg)", "num", True),
    ("rc_nuoc_hl", "Nước (hl)", "num", True),
    ("rc_ph_nuoc", "pH nước", "num", True),
    ("rc_termamyl_ml", "Termamyl SCDS (ml)", "num", True),
    ("rc_toc_do_khuay", "Tốc độ khuấy (%)", "num", False),
    ("rc_ph", "pH (khi cần thiết)", "num", False),
]
RC_TEMP_STEPS = 2  # 2 mốc nhiệt độ nồi cháo (VD 70°C nấu chín rồi 90°C giữ nhiệt)

MT_FIELDS = [
    ("mt_nghien_malt_uot_truoc_kg", "Nghiền malt ướt — trước (kg)", "num", False),
    ("mt_nghien_malt_uot_sau_kg", "Nghiền malt ướt — sau (kg)", "num", False),
    ("mt_malt_anh_kg", "Malt Anh (kg)", "num", True),
    ("mt_malt_uc_kg", "Malt Úc (kg)", "num", True),
    ("mt_malt_duc_kg", "Malt Đức (kg)", "num", True),
    ("mt_neutrase_ml", "Neutrase (ml)", "num", True),
    ("mt_ultraprime_ml", "Ultraprime (ml)", "num", True),
    ("mt_attenuazym_pro_ml", "Attenuazym Pro (ml)", "num", False),
    ("mt_cacl2_kg", "CaCl2 (kg)", "num", True),
    ("mt_caso4_kg", "CaSO4 (kg)", "num", True),
    ("mt_nuoc_hl", "Nước (hl)", "num", True),
    ("mt_ph_nuoc", "pH nước", "num", True),
    ("mt_kt_i2", "KT I2 (Đ/K)", "text", False),
    ("mt_kt_ba_malt", "KT bã malt (Đ/K)", "text", False),
]
MT_TEMP_STEPS = 5  # 5 mốc nhiệt độ nồi malt (đường cong đường hóa)

LT_FIELDS = [
    ("lt_dichcot_luong_hl", "Dịch cốt — Lượng (hl)", "num", False),
    ("lt_dichcot_bx", "Dịch cốt — %Bx", "num", False),
    ("lt_dichcot_nguoi", "Dịch cốt — Nấu chính", "text", False),
    ("lt_nuoctrang_luong_hl", "Nước tráng — Lượng (hl)", "num", False),
    ("lt_nuoctrang_bx", "Nước tráng — %Bx", "num", False),
    ("lt_nuoctrang_nguoi", "Nước tráng — Nấu chính", "text", False),
    ("lt_percent_bx_ket_thuc_loc_trang", "%Bx kết thúc lọc trong", "num", False),
    ("lt_kiem_tra_bao_muc", "Đã kiểm tra báo mức bầu xả bã", "bool", False),
]
LT_TIME_STEPS = [  # tên cố định (quy trình lọc chuẩn) — chỉ ghi Bắt đầu/Kết thúc, không có Quy định
    ("lt_chuyen", "Chuyển"),
    ("lt_quayvong1", "Quay vòng"),
    ("lt_dichcot_time", "Dịch cốt"),
    ("lt_quayvong2", "Quay vòng"),
    ("lt_trangba", "Tráng bã"),
]

WK_FIELDS = [
    ("wk_znso4_g", "ZnSO4 (g)", "num", False),
    ("wk_ph", "pH (5,2 - 5,6)", "num", False),
    ("wk_percent_bx_ket_thuc_dun_hoa", "%Bx kết thúc đun hoa", "num", False),
    ("wk_nuoc_cho_them_hl", "Nước cho thêm (hl)", "num", False),
]
WK_HOP_ROWS = [("wk_houb1", "Houb1"), ("wk_houb2", "Houb2")]

WHP_FIELDS = [
    ("whp_chuyen_gio", "Chuyển (giờ)", "text", True),
    ("whp_thoi_gian_lang_phut", "Thời gian lắng (phút)", "num", True),
    ("whp_t0_chuyen_dich", "T° chuyển dịch (°C)", "num", True),
    ("whp_oxy_lit_phut", "Oxy (lít/phút)", "num", True),
    ("whp_percent_bx", "%Bx (13,15 - 13,25)", "num", False),
    ("whp_tong_luong_dich_hl", "Tổng lượng dịch (hl)", "num", False),
    ("whp_ph", "pH", "num", False),
    ("whp_axit", "Axit", "num", False),
    ("whp_maturex_pro_added", "Đã bổ sung Maturex Pro (0,5 ml/hl)", "bool", False),
    ("whp_maturex_batdau", "Maturex — bắt đầu", "text", False),
    ("whp_maturex_ketthuc", "Maturex — kết thúc", "text", False),
    ("whp_brew_clarex_added", "Đã bổ sung Brew Clarex (0,65 ml/hl)", "bool", False),
    ("whp_clarex_batdau", "Clarex — bắt đầu", "text", False),
    ("whp_clarex_ketthuc", "Clarex — kết thúc", "text", False),
    ("whp_ht_uv_chuyen_dich", "HT UV chuyển dịch (Đ/K)", "bool", False),
]

FORM_SECTIONS = [
    {"key": "rc", "title": "Nồi cháo", "fields": RC_FIELDS, "temp_steps": RC_TEMP_STEPS},
    {"key": "mt", "title": "Nồi malt", "fields": MT_FIELDS, "temp_steps": MT_TEMP_STEPS},
    {"key": "lt", "title": "Nồi lọc bã", "fields": LT_FIELDS, "time_steps": LT_TIME_STEPS},
    {"key": "wk", "title": "Đun hoa", "fields": WK_FIELDS, "hop_rows": WK_HOP_ROWS},
    {"key": "whp", "title": "Lắng xoáy + hạ T°", "fields": WHP_FIELDS},
]


def _hop_row_keys(prefix: str) -> list[str]:
    return [f"{prefix}_hoacao_kg", f"{prefix}_hoavien_kg", f"{prefix}_rho_kg",
            f"{prefix}_batdau", f"{prefix}_giunhiet", f"{prefix}_ketthuc"]


# Toàn bộ key hợp lệ cho manual_json (Thực hiện — vận hành ghi). "note" KHÔNG nằm trong
# đây vì vẫn là cột riêng (BrewProcessLog.note), không thuộc bộ Quy định/Thực hiện.
MANUAL_FIELD_KEYS: list[str] = []
# Các key có Quy định tương ứng trong Product.spec_json (chỉ admin/master.manage sửa).
SPEC_FIELD_KEYS: list[str] = []

for _sec in FORM_SECTIONS:
    for _key, _label, _kind, _has_spec in _sec["fields"]:
        MANUAL_FIELD_KEYS.append(_key)
        if _has_spec:
            SPEC_FIELD_KEYS.append(_key)
    if "temp_steps" in _sec:
        for _i in range(1, _sec["temp_steps"] + 1):
            _base = f"{_sec['key']}_step{_i}"
            MANUAL_FIELD_KEYS += [f"{_base}_nhietdo", f"{_base}_batdau", f"{_base}_dung",
                                   f"{_base}_giunhiet", f"{_base}_ketthuc"]
            SPEC_FIELD_KEYS.append(f"{_base}_nhietdo")
    if "time_steps" in _sec:
        for _step_key, _step_label in _sec["time_steps"]:
            MANUAL_FIELD_KEYS += [f"{_step_key}_batdau", f"{_step_key}_ketthuc"]
    if "hop_rows" in _sec:
        for _row_key, _row_label in _sec["hop_rows"]:
            MANUAL_FIELD_KEYS += _hop_row_keys(_row_key)

for _key, _label, _kind, _has_spec in HEADER_FIELDS:
    MANUAL_FIELD_KEYS.append(_key)


def _load_json_dict(text: str | None) -> dict:
    try:
        return json.loads(text) if text else {}
    except ValueError:
        return {}


def get_manual_values(log: BrewProcessLog) -> dict:
    """Trả về đủ mọi key đã biết (None nếu chưa nhập) — để FE luôn render đủ ô nhập."""
    stored = _load_json_dict(log.manual_json)
    return {k: stored.get(k) for k in MANUAL_FIELD_KEYS}


def update_process_log(db: Session, batch_id: str, payload: dict, user: User) -> BrewProcessLog:
    require_perm(user, "batch.execute")
    log = get_or_create_process_log(db, batch_id)
    values = _load_json_dict(log.manual_json)
    if "note" in payload:
        log.note = payload["note"]
    for key, value in payload.items():
        if key == "note" or key not in MANUAL_FIELD_KEYS:
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


# ===== Quy định (spec) theo dịch bia — Product.spec_json, chỉ admin sửa =====

def get_spec_values(db: Session, product_id: str) -> dict:
    """Trả về đủ mọi key SPEC_FIELD_KEYS (None nếu chưa cấu hình)."""
    product = db.get(Product, product_id)
    if not product:
        raise NotFoundError("Sản phẩm không tồn tại.")
    stored = _load_json_dict(product.spec_json)
    return {k: stored.get(k) for k in SPEC_FIELD_KEYS}


def update_spec_values(db: Session, product_id: str, payload: dict, user: User) -> dict:
    require_perm(user, "master.manage")
    product = db.get(Product, product_id)
    if not product:
        raise NotFoundError("Sản phẩm không tồn tại.")
    values = _load_json_dict(product.spec_json)
    for key, value in payload.items():
        if key not in SPEC_FIELD_KEYS:
            continue
        if value is None:
            values.pop(key, None)
        else:
            values[key] = value
    product.spec_json = json.dumps(values, ensure_ascii=False)
    db.commit()
    return {k: values.get(k) for k in SPEC_FIELD_KEYS}
