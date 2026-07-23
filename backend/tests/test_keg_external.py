"""Test logic thuần (không cần CSDL SQL Server thật) của báo cáo chiết keg:
aggregate_keg_values() phải cộng đúng 4 cột line (L1..L4_Good_Real) cùng dòng, chọn giá trị
gần mốc ranh giới ca nhất NHƯNG KHÔNG VƯỢT QUA mốc (LOCF), và cộng dồn đúng theo ca/theo ngày."""

from datetime import datetime

from app.services.filling_external import shift_boundaries
from app.services.keg_external import aggregate_keg_values


def test_aggregate_keg_values_sums_four_lines_same_row():
    boundaries = shift_boundaries(datetime(2024, 3, 1, 6, 0), datetime(2024, 3, 2, 6, 0))
    # moi dong: (recordtime, l1, l2, l3, l4)
    raw_rows = [
        (datetime(2024, 3, 1, 6, 0), 100.0, 50.0, 20.0, 10.0),    # tong 180
        (datetime(2024, 3, 1, 14, 0), 150.0, 70.0, 25.0, 15.0),   # tong 260
        (datetime(2024, 3, 1, 22, 0), 150.0, 90.0, 30.0, 15.0),   # tong 285
        (datetime(2024, 3, 2, 6, 0), 200.0, 100.0, 40.0, 20.0),   # tong 360
    ]
    result = aggregate_keg_values(raw_rows, boundaries)

    assert result["total_kegs"] == 180.0  # 360 - 180
    by_ca = {c["ca"]: c["value"] for c in result["by_ca"]}
    assert by_ca[1] == 80.0    # 260 - 180
    assert by_ca[2] == 25.0    # 285 - 260
    assert by_ca[3] == 75.0    # 360 - 285
    assert len(result["shifts"]) == 3
    assert result["by_day"] == [{"date": "2024-03-01", "ca1": 80, "ca2": 25, "ca3": 75, "has_gap": False}]


def test_aggregate_keg_values_uses_nearest_sample_before_boundary_not_after():
    """LOCF: bản ghi lúc 22h10 nằm SAU mốc 22h00 nên KHÔNG được dùng — mốc 22h00 phải dùng lại
    bản ghi 13h55 (gần nhất TRƯỚC mốc), nên Ca 2 (14h-22h) = 200 - 200 = 0."""
    boundaries = shift_boundaries(datetime(2024, 3, 1, 6, 0), datetime(2024, 3, 1, 22, 0))
    raw_rows = [
        (datetime(2024, 3, 1, 5, 50), 40.0, 30.0, 20.0, 10.0),   # tong 100, truoc moc 06h
        (datetime(2024, 3, 1, 13, 55), 80.0, 60.0, 40.0, 20.0),  # tong 200, truoc moc 14h
        (datetime(2024, 3, 1, 22, 10), 100.0, 80.0, 50.0, 30.0),  # tong 260, SAU moc 22h -> khong dung
    ]
    result = aggregate_keg_values(raw_rows, boundaries)
    by_ca = {c["ca"]: c["value"] for c in result["by_ca"]}
    assert by_ca[1] == 100.0  # 200 - 100
    assert by_ca[2] == 0.0    # 200 - 200 (khong co ban ghi nao truoc 22h ngoai 13h55)


def test_aggregate_keg_values_uses_nearest_sample_before_boundary():
    boundaries = shift_boundaries(datetime(2024, 3, 1, 6, 0), datetime(2024, 3, 1, 22, 0))
    raw_rows = [
        (datetime(2024, 3, 1, 5, 50), 40.0, 30.0, 20.0, 10.0),    # tong 100, gan moc 06h
        (datetime(2024, 3, 1, 13, 55), 80.0, 60.0, 40.0, 20.0),   # tong 200, gan moc 14h
        (datetime(2024, 3, 1, 21, 55), 100.0, 80.0, 50.0, 30.0),  # tong 260, gan moc 22h, truoc moc
    ]
    result = aggregate_keg_values(raw_rows, boundaries)
    by_ca = {c["ca"]: c["value"] for c in result["by_ca"]}
    assert by_ca[1] == 100.0  # 200 - 100
    assert by_ca[2] == 60.0   # 260 - 200


def test_aggregate_keg_values_handles_null_columns():
    boundaries = shift_boundaries(datetime(2024, 3, 1, 6, 0), datetime(2024, 3, 1, 22, 0))
    raw_rows = [
        (datetime(2024, 3, 1, 6, 0), 100.0, None, 20.0, None),   # tong 120 (None -> 0)
        (datetime(2024, 3, 1, 14, 0), 150.0, None, 25.0, None),  # tong 175
        (datetime(2024, 3, 1, 22, 0), 180.0, None, 30.0, None),  # tong 210
    ]
    result = aggregate_keg_values(raw_rows, boundaries)
    assert result["total_kegs"] == 90.0  # 210 - 120


def test_aggregate_keg_values_empty_input_returns_zero():
    boundaries = shift_boundaries(datetime(2024, 3, 1, 6, 0), datetime(2024, 3, 1, 22, 0))
    result = aggregate_keg_values([], boundaries)
    assert result["total_kegs"] == 0.0
    assert all(c["value"] == 0.0 for c in result["by_ca"])
    assert all(l["total"] == 0 for l in result["by_line"])


def test_aggregate_keg_values_computes_per_line_breakdown():
    """Báo cáo theo từng line — mỗi line có ca1/ca2/ca3/tổng riêng, tổng các line phải khớp
    đúng total_kegs chung."""
    boundaries = shift_boundaries(datetime(2024, 3, 1, 6, 0), datetime(2024, 3, 2, 6, 0))
    raw_rows = [
        (datetime(2024, 3, 1, 6, 0), 100.0, 50.0, 20.0, 10.0),
        (datetime(2024, 3, 1, 14, 0), 150.0, 70.0, 25.0, 15.0),
        (datetime(2024, 3, 1, 22, 0), 150.0, 90.0, 30.0, 15.0),
        (datetime(2024, 3, 2, 6, 0), 200.0, 100.0, 40.0, 20.0),
    ]
    result = aggregate_keg_values(raw_rows, boundaries)
    by_line = {l["line"]: l for l in result["by_line"]}

    assert by_line["L1_Good_Real"]["label"] == "Line 1"
    assert by_line["L1_Good_Real"]["ca1"] == 50   # 150-100
    assert by_line["L1_Good_Real"]["ca2"] == 0    # 150-150
    assert by_line["L1_Good_Real"]["ca3"] == 50   # 200-150
    assert by_line["L1_Good_Real"]["total"] == 100

    assert by_line["L2_Good_Real"]["ca1"] == 20   # 70-50
    assert by_line["L2_Good_Real"]["ca2"] == 20   # 90-70
    assert by_line["L2_Good_Real"]["ca3"] == 10   # 100-90
    assert by_line["L2_Good_Real"]["total"] == 50

    assert by_line["L3_Good_Real"]["total"] == 20  # 40-20
    assert by_line["L4_Good_Real"]["total"] == 10  # 20-10

    # tong 4 line phai khop dung total_kegs chung (180)
    assert sum(l["total"] for l in result["by_line"]) == result["total_kegs"]


def test_aggregate_keg_values_nulls_shift_across_large_data_gap():
    """Mo phong su co gap du lieu that (CSDL ngung ghi hon 1 nam) — moc roi vao gap phai tra
    "kegs": None kem "data_gap": True, khong duoc cong so bia vao total/by_ca/by_line."""
    boundaries = shift_boundaries(datetime(2024, 3, 1, 6, 0), datetime(2024, 3, 1, 22, 0))
    raw_rows = [
        (datetime(2023, 1, 1, 0, 0), 100.0, 50.0, 20.0, 10.0),      # qua xa moc 06h/14h
        (datetime(2024, 3, 1, 13, 55), 500.0, 250.0, 100.0, 50.0),  # "song lai" TRONG ca 1, gan moc 14h
        (datetime(2024, 3, 1, 21, 55), 520.0, 260.0, 110.0, 55.0),  # gan moc 22h, dang tin
    ]
    result = aggregate_keg_values(raw_rows, boundaries)

    assert result["shifts"][0]["kegs"] is None
    assert result["shifts"][0]["data_gap"] is True
    assert result["shifts"][1]["kegs"] == 45  # (520+260+110+55) - (500+250+100+50) = 45
    assert result["shifts"][1]["data_gap"] is False
    assert result["has_gap"] is True
    assert result["total_kegs"] == 45

    by_line = {l["line"]: l for l in result["by_line"]}
    assert by_line["L1_Good_Real"]["ca1"] == 0     # ca gap -> khong cong
    assert by_line["L1_Good_Real"]["ca2"] == 20    # 520-500
    assert by_line["L1_Good_Real"]["has_gap"] is True
