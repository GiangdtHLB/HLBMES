"""Test 2 báo cáo Nhóm C (port từ phần mềm QLSX cũ dma.biahalong.com:88 › Báo cáo sản xuất,
yêu cầu người dùng 2026-11-05) trong services/qc_stat_reports.py:
- qc_min_max_avg: KCS Thống kê Min-Max-AVG theo chỉ tiêu.
- qc_analysis_count: KCS đếm số lần phân tích theo chỉ tiêu (kèm breakdown Đạt/Không đạt/Chờ
  duyệt) và theo ngày.

Dựng trực tiếp QualityResult qua ORM (không qua workflow batch/stage thật — các hàm chỉ đọc
thẳng bảng này, không quan tâm nguồn gốc bản ghi) để kiểm soát chính xác giá trị/ngày/trạng thái
cần test, mirror test_oee_waterfall.py."""

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
from app.models.quality import QualityResult
from app.services import qc_stat_reports

PARAM = "QCSTAT Độ cồn"


@pytest.fixture(scope="module", autouse=True)
def _seeded():
    seed_mod.seed()
    yield


def _mk(db, scope_type, value, status, recorded_at, parameter=PARAM, unit="%"):
    db.add(QualityResult(result_id=new_id(), sample_id=new_id(), scope_type=scope_type,
                         scope_id="scope-x", parameter=parameter, value=value, unit=unit,
                         status=status, recorded_at=recorded_at))


@pytest.fixture(scope="module")
def seeded_results():
    db = SessionLocal()
    try:
        _mk(db, "batch", 4.8, "pass", datetime(2031, 6, 10, tzinfo=timezone.utc))
        _mk(db, "batch", 5.2, "pass", datetime(2031, 6, 11, tzinfo=timezone.utc))
        _mk(db, "batch", 4.5, "fail", datetime(2031, 6, 11, tzinfo=timezone.utc))
        _mk(db, "batch_tank", 5.0, "pending", datetime(2031, 6, 12, tzinfo=timezone.utc))
        # Ngoài khoảng/khác scope — phải KHÔNG bị tính vào kết quả lọc theo batch + 6/2031.
        _mk(db, "lot", 9.9, "pass", datetime(2031, 6, 11, tzinfo=timezone.utc))
        _mk(db, "batch", 100.0, "pass", datetime(2032, 1, 1, tzinfo=timezone.utc))
        db.commit()
    finally:
        db.close()
    db2 = SessionLocal()
    yield db2
    db2.close()


def test_qc_min_max_avg_stats_per_parameter(seeded_results):
    db = seeded_results
    r = qc_stat_reports.qc_min_max_avg(db, scope_type="batch",
                                       date_from=datetime(2031, 6, 1, tzinfo=timezone.utc),
                                       date_to=datetime(2031, 6, 30, tzinfo=timezone.utc))
    row = next(i for i in r["items"] if i["parameter"] == PARAM)
    assert row["n"] == 3   # 2 pass + 1 fail trong tháng 6/2031, scope=batch — loại bỏ lot/2032
    assert row["min"] == 4.5
    assert row["max"] == 5.2
    assert row["avg"] == round((4.8 + 5.2 + 4.5) / 3, 4)
    assert row["unit"] == "%"


def test_qc_analysis_count_breakdown_by_parameter_and_day(seeded_results):
    db = seeded_results
    r = qc_stat_reports.qc_analysis_count(db, scope_type="batch",
                                          date_from=datetime(2031, 6, 1, tzinfo=timezone.utc),
                                          date_to=datetime(2031, 6, 30, tzinfo=timezone.utc))
    row = next(i for i in r["by_parameter"] if i["parameter"] == PARAM)
    assert row["total"] == 3
    assert row["pass"] == 2
    assert row["fail"] == 1
    assert row["pending"] == 0

    by_day = {d["date"]: d["count"] for d in r["by_day"]}
    assert by_day["2031-06-10"] == 1
    assert by_day["2031-06-11"] == 2   # 1 pass + 1 fail cùng ngày, khác scope "lot" bị loại


def test_qc_analysis_count_no_filter_includes_all_scopes(seeded_results):
    db = seeded_results
    r = qc_stat_reports.qc_analysis_count(db, date_from=datetime(2031, 6, 1, tzinfo=timezone.utc),
                                          date_to=datetime(2031, 6, 30, tzinfo=timezone.utc))
    row = next(i for i in r["by_parameter"] if i["parameter"] == PARAM)
    # Không lọc scope_type -> tính CẢ "lot" trong tháng 6/2031: 3 (batch) + 1 (batch_tank) + 1 (lot) = 5.
    assert row["total"] == 5
