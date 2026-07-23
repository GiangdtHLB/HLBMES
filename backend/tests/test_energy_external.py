"""Test logic thuần (không cần CSDL SQL Server thật) của báo cáo điện SCADA ngoài:
AED là bộ đếm cộng dồn, compute_daily_diffs phải cho hiệu số đúng và kẹp về 0 khi có
mẫu lỗi SCADA giật giá trị AED về thấp hơn (không phải reset thật)."""

from app.services.energy_external import _is_station, compute_daily_diffs


def test_compute_daily_diffs_normal_increments():
    baseline = {1: 100.0}
    daily_rows = [(1, "2024-03-01", 150.0), (1, "2024-03-02", 210.0), (1, "2024-03-03", 300.0)]
    out = compute_daily_diffs(baseline, daily_rows)
    assert out[(1, "2024-03-01")] == 50.0
    assert out[(1, "2024-03-02")] == 60.0
    assert out[(1, "2024-03-03")] == 90.0


def test_compute_daily_diffs_clamps_glitch_dip_to_zero():
    """Một ngày day_max thấp hơn mức đã biết (do mẫu lỗi SCADA) không được trừ ra số âm."""
    baseline = {1: 100.0}
    daily_rows = [(1, "2024-03-01", 150.0), (1, "2024-03-02", 0.0), (1, "2024-03-03", 200.0)]
    out = compute_daily_diffs(baseline, daily_rows)
    assert out[(1, "2024-03-01")] == 50.0
    assert out[(1, "2024-03-02")] == 0.0  # kẹp về 0, không phải -150
    # last_known vẫn giữ mốc 150 (không tụt xuống 0), nên ngày 3 = 200-150=50
    assert out[(1, "2024-03-03")] == 50.0


def test_compute_daily_diffs_no_baseline_uses_first_reading_as_start():
    baseline = {}
    daily_rows = [(1, "2024-03-01", 20.0), (1, "2024-03-02", 35.0)]
    out = compute_daily_diffs(baseline, daily_rows)
    assert out[(1, "2024-03-01")] == 20.0
    assert out[(1, "2024-03-02")] == 15.0


def test_compute_daily_diffs_independent_per_local_id():
    baseline = {1: 100.0, 2: 5.0}
    daily_rows = [(1, "2024-03-01", 120.0), (2, "2024-03-01", 8.0)]
    out = compute_daily_diffs(baseline, daily_rows)
    assert out[(1, "2024-03-01")] == 20.0
    assert out[(2, "2024-03-01")] == 3.0


def test_is_station_classification():
    assert _is_station("Trạm 560 KVA")
    assert _is_station("Máy phát điện")
    assert not _is_station("Máy nén khí")
    assert not _is_station("Lò hơi")
