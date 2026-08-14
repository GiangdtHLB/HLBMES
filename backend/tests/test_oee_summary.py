"""services/oee_summary.py — xu hướng OPI theo tháng/quý/tuần + Pareto tổn thất theo
tháng/quý cho tab "Summary" OEE. Không cần khớp số liệu Excel gốc — chỉ cần đúng công thức và
đúng hình dạng dữ liệu trả về (đủ 12 tháng/4 quý/13 tuần, sắp Pareto giảm dần)."""

import os
import tempfile
from datetime import datetime, timezone

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["MES_DATABASE_URL"] = f"sqlite:///{_TMP.name}"
os.environ["MES_DEV_HEADER_AUTH"] = "0"
os.environ["MES_RL_ENABLED"] = "0"
os.environ["MES_ADMIN_PASSWORD"] = "AdminTest123"

import pytest

from app.main import app  # noqa: F401
from app import seed as seed_mod
from app.database import SessionLocal
from app.common import new_id
from app.models.lines import ProductionLine
from app.models.metrics import OEERecord
from app.models.oee_ext import DowntimeEvent, OeeReasonCatalog
from app.services import oee_summary
from app.services import oee_waterfall


@pytest.fixture(scope="module", autouse=True)
def _seeded():
    seed_mod.seed()
    yield


LINE = "SUM-TEST-LINE"


@pytest.fixture(scope="module")
def setup_line():
    db = SessionLocal()
    try:
        db.add(ProductionLine(line_id=new_id(), code=LINE, name="Dây chuyền test summary",
                              kind="line", area="chiet", ideal_rate_per_min=100, active=True))
        rows = [
            ("ke_hoach", "cip", "CIP", "Trạm chiết", 0.05),
            ("ke_hoach", "sample", "Lấy mẫu", None, 0.02),
            ("breakdown", "chiet", "Lỗi chiết", "Chiết", 0.02),
            ("breakdown", "dolon", "Lỗi dỡ lon", "Dỡ lon", 0.01),
            ("dung_lat_nhat", "tong_dung", "Tổng dừng", None, 0.03),
        ]
        for cat, code, label, pos, target in rows:
            db.add(OeeReasonCatalog(reason_id=new_id(), line_code=LINE, category=cat, sub_code=code,
                                    sub_label=label, machine_position=pos, target_pct=target, active=True))
        db.commit()
        return {r.sub_code: r for r in db.query(OeeReasonCatalog).filter(OeeReasonCatalog.line_code == LINE).all()}
    finally:
        db.close()


def _add_shift(db, dt, good=900, total=1000):
    db.add(OEERecord(oee_id=new_id(), line=LINE, shift="Ca1", shift_date=dt,
                     planned_time_min=480, downtime_min=0, ideal_rate_per_min=100,
                     total_count=total, good_count=good, downtime_reasons=[]))


def _add_event(db, dt, reason, minutes):
    db.add(DowntimeEvent(event_id=new_id(), line=LINE, shift="Ca1", shift_date=dt,
                         reason_group=reason.category, reason_code=reason.sub_code,
                         reason_catalog_id=reason.reason_id, reason_label=reason.sub_label,
                         loss_category="availability", minutes=minutes,
                         recorded_by="test", recorded_at=dt))


def test_monthly_trend_covers_all_12_months_and_matches_populated_month(setup_line):
    reasons = setup_line
    db = SessionLocal()
    try:
        jan = datetime(2025, 1, 15, tzinfo=timezone.utc)
        _add_shift(db, jan)
        _add_event(db, jan, reasons["cip"], 30)
        _add_event(db, jan, reasons["chiet"], 15)
        _add_event(db, jan, reasons["dolon"], 5)
        db.commit()

        trend = oee_summary.monthly_trend(db, LINE, 2025)
        assert len(trend) == 12
        assert [p["label"] for p in trend] == [f"T{m}" for m in range(1, 13)]

        jan_point = trend[0]
        assert jan_point["planned_pct"] > 0  # ke_hoach (CIP) có phút dừng trong tháng 1
        assert jan_point["breakdown_pct"] > 0
        feb_point = trend[1]
        assert feb_point["planned_pct"] == 0  # tháng 2 chưa có dữ liệu
    finally:
        db.close()


def test_quarterly_and_weekly_trend_shapes(setup_line):
    db = SessionLocal()
    try:
        q = oee_summary.quarterly_trend(db, LINE, 2025)
        assert len(q) == 4
        assert [p["label"] for p in q] == ["Q1", "Q2", "Q3", "Q4"]

        w = oee_summary.weekly_trend(db, LINE)
        assert len(w) == 13
    finally:
        db.close()


def test_category_breakdown_pareto_order_and_machine_position(setup_line):
    reasons = setup_line
    db = SessionLocal()
    try:
        mar = datetime(2025, 3, 10, tzinfo=timezone.utc)
        _add_shift(db, mar)
        _add_event(db, mar, reasons["chiet"], 40)
        _add_event(db, mar, reasons["dolon"], 5)
        _add_event(db, mar, reasons["cip"], 100)
        _add_event(db, mar, reasons["sample"], 10)
        db.commit()

        start, end, _ = oee_waterfall._month_bounds(2025, 3)

        breakdown = oee_summary.category_breakdown(db, LINE, start, end, "breakdown", by_machine_position=True)
        assert [b["label"] for b in breakdown] == ["Chiết", "Dỡ lon"]
        assert breakdown[0]["minutes"] == 40

        planned = oee_summary.category_breakdown(db, LINE, start, end, "ke_hoach")
        assert [b["label"] for b in planned] == ["CIP", "Lấy mẫu"]
        assert planned[0]["minutes"] == 100

        bundle = oee_summary.period_breakdowns(db, LINE, start, end)
        assert set(bundle.keys()) == {"planned_downtime", "breakdown", "minor_stop"}
    finally:
        db.close()


def test_summary_dashboard_bundle_shape(setup_line):
    db = SessionLocal()
    try:
        result = oee_summary.summary_dashboard(db, LINE, 2025, 3)
        assert result["quarter"] == 1
        assert len(result["monthly"]) == 12
        assert len(result["quarterly"]) == 4
        assert len(result["weekly"]) == 13
        assert "breakdown" in result["last_month_breakdowns"]
        assert "breakdown" in result["this_quarter_breakdowns"]
    finally:
        db.close()
