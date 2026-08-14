"""Thác nước tổn thất OPI theo tháng + OPI/OPI NONA/Efficiency so Target — công thức trích trực
tiếp từ sheet Summary/Target/OPI Definition của file vận hành thật
"OPI - CAN L3 (KHS 30K).xlsx" (không phải OEE 3-yếu tố Availability×Performance×Quality kinh
điển ở services/performance.py — đó là chỉ số PER-SHIFT đơn giản, còn đây là thác nước tổn thất
PER-MONTH đủ 8 nhóm dùng để họp sản xuất hàng tuần).

Thác nước (mỗi bước trừ khối lượng phút của bước sau):
  A Tổng thời gian (lịch, cắt ở "hôm nay" nếu tháng chưa hết)
  − B Thời gian nghỉ (MES chưa theo dõi lễ/cuối tuần riêng — luôn 0)          = C Thời gian làm
  − D Bảo trì ngoài                                                          = E Thời gian vận hành
  − F NONA (auto: không có ca nào ghi nhận + "Đào tạo-họp" khai tay)         = G TG vận hành hiệu quả
  − H Dừng có kế hoạch − I Chuyển máy                                        = J TG sản xuất cơ bản
  − K Dừng do thiếu NVL                                                     = L TG sản xuất thực
  − M Breakdown                                                             = N TG máy chạy
  − O Dừng lắt nhắt (RESIDUAL = N − P, không có lý do riêng)                 = P TG có sản phẩm
  P = Q (SP lỗi quy đổi phút) + R (SP tốt quy đổi phút)

OPI      = 1 − (D+F+H+I+K+M+O+Q)/C                         (tính cả Bảo trì ngoài + NONA)
OPI NONA = 1 − (H+I+K+M+O+Q)/G                              (loại Bảo trì ngoài + NONA cả 2 vế)
Efficiency = R/J                                            (SP tốt quy đổi phút ÷ TG sản xuất cơ bản)
"""

import calendar
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..common import utcnow
from ..errors import DomainError
from ..models.lines import ProductionLine
from ..models.metrics import OEERecord
from ..models.oee_ext import DowntimeEvent, OeeReasonCatalog

_CATEGORIES = ["bao_tri_ngoai", "nona", "ke_hoach", "chuyen_may", "thieu_vat_tu",
              "breakdown", "dung_lat_nhat", "sp_loi"]


def _elapsed_days(start, end):
    """Số ngày đã trôi qua trong [start, end] tính tới hiện tại — 0 nếu kỳ còn ở tương lai,
    trọn vẹn nếu kỳ đã qua hẳn. Dùng chung cho tháng/quý/tuần để cắt đúng "A Tổng thời gian"."""
    now = utcnow()
    now_naive = now.replace(tzinfo=None) if now.tzinfo else now
    if now_naive < start.replace(tzinfo=None):
        return 0
    elapsed_end = min(end, now)
    return (elapsed_end.replace(tzinfo=None).date() - start.date()).days + 1


def _month_bounds(year: int, month: int):
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    days_in_month = calendar.monthrange(year, month)[1]
    end = datetime(year, month, days_in_month, 23, 59, 59, tzinfo=timezone.utc)
    return start, end, _elapsed_days(start, end)


def _quarter_bounds(year: int, quarter: int):
    start_month = (quarter - 1) * 3 + 1
    end_month = start_month + 2
    start, _, _ = _month_bounds(year, start_month)
    _, end, _ = _month_bounds(year, end_month)
    return start, end, _elapsed_days(start, end)


def _week_bounds(year: int, iso_week: int):
    """Tuần ISO (Thứ 2 → Chủ nhật). `year`/`iso_week` chuẩn hoá qua isocalendar nên iso_week có
    thể vượt số tuần thực của năm (vd 53) mà vẫn tính đúng nhờ Python tự cuộn sang năm sau."""
    start = datetime.fromisocalendar(year, iso_week, 1).replace(tzinfo=timezone.utc)
    end = start + timedelta(days=7) - timedelta(seconds=1)
    return start, end, _elapsed_days(start, end)


def _year_bounds(year: int, upto_month: int = 12):
    """Từ đầu năm tới hết tháng `upto_month` — dùng cho cột YTD."""
    start, _, _ = _month_bounds(year, 1)
    _, end, _ = _month_bounds(year, upto_month)
    return start, end, _elapsed_days(start, end)


def _line(db: Session, line_code: str) -> ProductionLine:
    line = db.execute(select(ProductionLine).where(ProductionLine.code == line_code)).scalar_one_or_none()
    if not line:
        raise DomainError(f"Dây chuyền '{line_code}' không tồn tại.")
    return line


def _category_minutes(db: Session, line_code: str, start, end) -> dict:
    rows = db.execute(
        select(DowntimeEvent.reason_group, func.sum(DowntimeEvent.minutes))
        .where(DowntimeEvent.line == line_code, DowntimeEvent.shift_date >= start, DowntimeEvent.shift_date <= end)
        .group_by(DowntimeEvent.reason_group)).all()
    return {cat: 0.0 for cat in _CATEGORIES} | {cat: float(mins or 0) for cat, mins in rows}


def _nona_manual_minutes(db: Session, line_code: str, start, end) -> float:
    """NONA khai tay (vd Đào tạo-họp) — LOẠI "khong_co_order" vì phần đó đã tính auto ở nona_auto,
    tránh đếm 2 lần nếu có thao tác viên lỡ ghi nhận thêm."""
    return float(db.execute(
        select(func.sum(DowntimeEvent.minutes))
        .where(DowntimeEvent.line == line_code, DowntimeEvent.reason_group == "nona",
               DowntimeEvent.reason_code != "khong_co_order",
               DowntimeEvent.shift_date >= start, DowntimeEvent.shift_date <= end)).scalar() or 0)


def _shift_scheduled_minutes(db: Session, line_code: str, start, end) -> float:
    """Tổng phút đã CÓ ghi nhận ca sản xuất (OEERecord) trong tháng — Ca*=8h, Kip*=12h."""
    rows = db.execute(select(OEERecord.shift).where(
        OEERecord.line == line_code, OEERecord.shift_date >= start, OEERecord.shift_date <= end)).scalars().all()
    total = 0.0
    for shift in rows:
        s = (shift or "").lower()
        if s.startswith("kip"):
            total += 12 * 60
        else:
            total += 8 * 60
    return total


def _good_reject_minutes(db: Session, line_code: str, start, end, ideal_rate_per_min: float):
    row = db.execute(select(func.sum(OEERecord.good_count), func.sum(OEERecord.total_count)).where(
        OEERecord.line == line_code, OEERecord.shift_date >= start, OEERecord.shift_date <= end)).one()
    good = float(row[0] or 0)
    total = float(row[1] or 0)
    reject = max(total - good, 0)
    rate = ideal_rate_per_min or 1.0
    return good / rate, reject / rate


def _waterfall_report_bounds(db: Session, line_code: str, start, end, elapsed_days: int, meta: dict) -> dict:
    """Lõi thác nước tổn thất dùng chung cho tháng/quý/tuần/YTD — `meta` chỉ mang theo các trường
    định danh kỳ báo cáo (year/month, hoặc year/quarter, ...) để giữ nguyên hình dạng kết quả."""
    line = _line(db, line_code)
    A = elapsed_days * 24 * 60
    B = 0.0
    C = A - B
    cat = _category_minutes(db, line_code, start, end)
    D = cat["bao_tri_ngoai"]
    E = C - D
    nona_auto = max(A - _shift_scheduled_minutes(db, line_code, start, end) - B, 0)
    F = nona_auto + _nona_manual_minutes(db, line_code, start, end)
    G = E - F
    H = cat["ke_hoach"]
    I = cat["chuyen_may"]
    J = G - H - I
    K = cat["thieu_vat_tu"]
    L = J - K
    M = cat["breakdown"]
    N = L - M
    R, Q = _good_reject_minutes(db, line_code, start, end, line.ideal_rate_per_min)
    P = Q + R
    O = max(N - P, 0)
    rows = [
        {"code": "A", "label": "Tổng thời gian", "minutes": round(A, 1)},
        {"code": "B", "label": "Thời gian nghỉ", "minutes": round(B, 1)},
        {"code": "C", "label": "Thời gian làm", "minutes": round(C, 1)},
        {"code": "D", "label": "Bảo trì ngoài", "minutes": round(D, 1)},
        {"code": "E", "label": "Thời gian vận hành", "minutes": round(E, 1)},
        {"code": "F", "label": "NONA", "minutes": round(F, 1)},
        {"code": "G", "label": "Thời gian vận hành hiệu quả", "minutes": round(G, 1)},
        {"code": "H", "label": "Dừng có kế hoạch", "minutes": round(H, 1)},
        {"code": "I", "label": "Chuyển máy", "minutes": round(I, 1)},
        {"code": "J", "label": "Thời gian sản xuất cơ bản", "minutes": round(J, 1)},
        {"code": "K", "label": "Dừng do thiếu NVL", "minutes": round(K, 1)},
        {"code": "L", "label": "Thời gian sản xuất thực", "minutes": round(L, 1)},
        {"code": "M", "label": "Breakdown", "minutes": round(M, 1)},
        {"code": "N", "label": "Thời gian máy chạy", "minutes": round(N, 1)},
        {"code": "O", "label": "Dừng lắt nhắt", "minutes": round(O, 1)},
        {"code": "P", "label": "Thời gian có sản phẩm", "minutes": round(P, 1)},
        {"code": "Q", "label": "Sản phẩm lỗi (quy đổi phút)", "minutes": round(Q, 1)},
        {"code": "R", "label": "Sản phẩm tốt (quy đổi phút)", "minutes": round(R, 1)},
    ]
    loss_minutes = {"bao_tri_ngoai": D, "nona": F, "ke_hoach": H, "chuyen_may": I,
                    "thieu_vat_tu": K, "breakdown": M, "dung_lat_nhat": O, "sp_loi": Q}
    return {"line_code": line_code, **meta, "elapsed_days": elapsed_days, "rows": rows,
            "_raw": {"A": A, "C": C, "D": D, "F": F, "G": G, "H": H, "I": I, "J": J, "K": K,
                     "M": M, "O": O, "Q": Q, "R": R, "loss_minutes": loss_minutes}}


def waterfall_report(db: Session, line_code: str, year: int, month: int) -> dict:
    start, end, elapsed_days = _month_bounds(year, month)
    return _waterfall_report_bounds(db, line_code, start, end, elapsed_days, {"year": year, "month": month})


def _opi_summary_bounds(db: Session, line_code: str, start, end, elapsed_days: int, meta: dict) -> dict:
    wf = _waterfall_report_bounds(db, line_code, start, end, elapsed_days, meta)
    r = wf["_raw"]
    total_loss = r["D"] + r["F"] + r["H"] + r["I"] + r["K"] + r["M"] + r["O"] + r["Q"]
    opi = 1 - (total_loss / r["C"]) if r["C"] else 0.0
    loss_nona = r["H"] + r["I"] + r["K"] + r["M"] + r["O"] + r["Q"]
    opi_nona = 1 - (loss_nona / r["G"]) if r["G"] else 0.0
    efficiency = (r["R"] / r["J"]) if r["J"] else 0.0

    targets = {cat: 0.0 for cat in _CATEGORIES}
    for row in db.execute(select(OeeReasonCatalog.category, func.sum(OeeReasonCatalog.target_pct))
                          .where((OeeReasonCatalog.line_code == line_code) | (OeeReasonCatalog.line_code.is_(None)))
                          .group_by(OeeReasonCatalog.category)).all():
        targets[row[0]] = float(row[1] or 0)
    target_total_loss = sum(targets.values())
    target_opi = 1 - target_total_loss
    target_loss_nona = sum(v for k, v in targets.items() if k not in ("bao_tri_ngoai", "nona"))
    target_denom = 1 - targets["bao_tri_ngoai"] - targets["nona"]
    target_opi_nona = 1 - (target_loss_nona / target_denom) if target_denom else 0.0

    by_category = []
    for cat in _CATEGORIES:
        actual_min = r["loss_minutes"][cat]
        by_category.append({
            "category": cat, "label": {
                "bao_tri_ngoai": "Bảo trì ngoài", "nona": "NONA", "ke_hoach": "Dừng có kế hoạch",
                "chuyen_may": "Chuyển máy", "thieu_vat_tu": "Dừng nguyên vật liệu",
                "breakdown": "Breakdown", "dung_lat_nhat": "Dừng lắt nhắt", "sp_loi": "Sản phẩm lỗi",
            }[cat],
            "actual_pct": round(actual_min / r["C"], 4) if r["C"] else 0.0,
            "target_pct": round(targets[cat], 4), "actual_minutes": round(actual_min, 1)})

    return {"line_code": line_code, **meta,
            "opi": round(opi, 4), "opi_target": round(target_opi, 4),
            "opi_nona": round(opi_nona, 4), "opi_nona_target": round(target_opi_nona, 4),
            "efficiency": round(efficiency, 4), "efficiency_target": 0.92,
            "by_category": by_category, "waterfall": wf["rows"]}


def opi_summary(db: Session, line_code: str, year: int, month: int) -> dict:
    start, end, elapsed_days = _month_bounds(year, month)
    return _opi_summary_bounds(db, line_code, start, end, elapsed_days, {"year": year, "month": month})
