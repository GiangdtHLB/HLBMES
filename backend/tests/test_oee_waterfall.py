"""Thác nước tổn thất OPI theo tháng (services/oee_waterfall.py) — dựng OEERecord +
DowntimeEvent giả cho 1 dây chuyền test, so khớp công thức A→R + OPI/OPI NONA/Efficiency với
số tính tay. Không cần khớp số liệu thật trong file Excel gốc — chỉ cần đúng công thức."""

import os
import tempfile
from datetime import datetime, timezone

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["MES_DATABASE_URL"] = f"sqlite:///{_TMP.name}"
os.environ["MES_DEV_HEADER_AUTH"] = "0"
os.environ["MES_RL_ENABLED"] = "0"
os.environ["MES_ADMIN_PASSWORD"] = "AdminTest123"

import pytest

from app.main import app  # noqa: F401 — đảm bảo models đã đăng ký trước khi tạo bảng
from app import seed as seed_mod
from app.database import SessionLocal
from app.common import new_id
from app.models.lines import ProductionLine
from app.models.metrics import OEERecord
from app.models.oee_ext import DowntimeEvent, OeeReasonCatalog
from app.services import oee_waterfall


@pytest.fixture(scope="module", autouse=True)
def _seeded():
    seed_mod.seed()
    yield


LINE = "WF-TEST-LINE"


@pytest.fixture(scope="module")
def setup_line():
    db = SessionLocal()
    try:
        db.add(ProductionLine(line_id=new_id(), code=LINE, name="Dây chuyền test waterfall",
                              kind="line", area="chiet", ideal_rate_per_min=100, active=True))
        # Danh mục lý do riêng cho line test — target nhỏ, dễ tính tay.
        rows = [
            ("bao_tri_ngoai", "bt", "Bảo trì ngoài", 0.01),
            ("nona", "dao_tao", "Đào tạo-họp", 0.02),
            ("ke_hoach", "cip", "CIP", 0.05),
            ("chuyen_may", "cm", "Chuyển máy", 0.01),
            ("thieu_vat_tu", "vt", "Thiếu vật tư", 0.01),
            ("breakdown", "bd", "Breakdown", 0.02),
            ("dung_lat_nhat", "tong_dung", "Tổng dừng", 0.03),
            ("sp_loi", "sl", "SP lỗi", 0.01),
        ]
        for cat, code, label, target in rows:
            db.add(OeeReasonCatalog(reason_id=new_id(), line_code=LINE, category=cat, sub_code=code,
                                    sub_label=label, target_pct=target, active=True))
        db.commit()
        reasons = {r.category: r.reason_id for r in
                  db.query(OeeReasonCatalog).filter(OeeReasonCatalog.line_code == LINE).all()}
        return reasons
    finally:
        db.close()


def test_waterfall_and_opi_formula(setup_line):
    reasons = setup_line
    db = SessionLocal()
    try:
        year, month = 2025, 1  # tháng đã qua hẳn — elapsed_days = 31 cố định, không phụ thuộc "hôm nay"
        start = datetime(year, month, 1, tzinfo=timezone.utc)

        # 1 ca ghi nhận (đúng 8h = 480 phút theo shift="Ca1") với SP tốt/lỗi.
        db.add(OEERecord(oee_id=new_id(), line=LINE, shift="Ca1", shift_date=start,
                         planned_time_min=480, downtime_min=0, ideal_rate_per_min=100,
                         total_count=1000, good_count=900, downtime_reasons=[]))
        # Sự kiện dừng máy — mỗi category 1 sự kiện, số phút khác nhau để dễ truy vết.
        events = [("bao_tri_ngoai", 10), ("nona", 5), ("ke_hoach", 20), ("chuyen_may", 8),
                 ("thieu_vat_tu", 6), ("breakdown", 12)]
        for cat, mins in events:
            db.add(DowntimeEvent(event_id=new_id(), line=LINE, shift="Ca1", shift_date=start,
                                 reason_group=cat, reason_code="x",
                                 reason_catalog_id=reasons[cat], reason_label=cat,
                                 loss_category="availability", minutes=mins,
                                 recorded_by="test", recorded_at=start))
        db.commit()

        wf = oee_waterfall.waterfall_report(db, LINE, year, month)
        r = {row["code"]: row["minutes"] for row in wf["rows"]}

        A = 31 * 24 * 60
        assert r["A"] == A
        assert r["D"] == 10
        # F = nona_auto (A - 480 phút ca đã ghi) + 5 (nona thủ công)
        assert r["F"] == pytest.approx(A - 480 + 5, abs=0.5)
        assert r["H"] == 20
        assert r["I"] == 8
        assert r["K"] == 6
        assert r["M"] == 12
        # R (SP tốt quy đổi phút) = 900/100 = 9 ; Q (SP lỗi) = (1000-900)/100 = 1
        assert r["R"] == pytest.approx(9.0)
        assert r["Q"] == pytest.approx(1.0)

        summ = oee_waterfall.opi_summary(db, LINE, year, month)
        C = A
        total_loss = 10 + r["F"] + 20 + 8 + 6 + 12 + r["O"] + 1
        expected_opi = 1 - total_loss / C
        assert summ["opi"] == pytest.approx(round(expected_opi, 4), abs=1e-3)

        # Target: tổng 8 category = 0.01+0.02+0.05+0.01+0.01+0.02+0.03+0.01 = 0.16 → OPI target=0.84
        assert summ["opi_target"] == pytest.approx(0.84, abs=1e-6)
        target_denom = 1 - 0.01 - 0.02
        target_loss_nona = 0.05 + 0.01 + 0.01 + 0.02 + 0.03 + 0.01
        expected_opi_nona_target = 1 - target_loss_nona / target_denom
        assert summ["opi_nona_target"] == pytest.approx(round(expected_opi_nona_target, 4), abs=1e-3)
    finally:
        db.close()


def test_opi_zero_when_no_data():
    """Không có ca nào ghi nhận trong tháng → NONA-auto nuốt hết thời gian → OPI = 0 (đúng
    logic thác nước: không chạy gì thì hiệu suất bằng 0, không phải chia-cho-0/lỗi)."""
    db = SessionLocal()
    try:
        summ = oee_waterfall.opi_summary(db, "CAN30K", 2020, 1)
        assert summ["opi"] == 0.0
    finally:
        db.close()
