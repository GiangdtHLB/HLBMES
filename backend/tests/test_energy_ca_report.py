"""Test logic thuần (không cần CSDL SQL Server thật) của báo cáo điện theo ca:
aggregate_ca_values() phải gộp đúng nhiều LocalID (loại trạm/máy phát), chọn giá trị AED gần
mốc ranh giới ca nhất NHƯNG KHÔNG VƯỢT QUA mốc (LOCF), và cộng dồn đúng theo ca/theo ngày."""

from datetime import datetime

from app.services.energy_external import aggregate_ca_values
from app.services.filling_external import shift_boundaries


def _names():
    return {1: "May nen khi", 2: "Lo hoi", 10: "Trạm 560 KVA"}


def test_aggregate_ca_values_sums_across_local_ids_excluding_station():
    boundaries = shift_boundaries(datetime(2024, 3, 1, 6, 0), datetime(2024, 3, 2, 6, 0))
    raw_rows = [
        # LocalID 1: tang 100 -> 250 -> 400 -> 600 qua cac moc ca
        (1, datetime(2024, 3, 1, 6, 0), 100.0),
        (1, datetime(2024, 3, 1, 14, 0), 250.0),
        (1, datetime(2024, 3, 1, 22, 0), 400.0),
        (1, datetime(2024, 3, 2, 6, 0), 600.0),
        # LocalID 2: tang 10 -> 20 -> 20 -> 30 (ca 2 khong tieu thu)
        (2, datetime(2024, 3, 1, 6, 0), 10.0),
        (2, datetime(2024, 3, 1, 14, 0), 20.0),
        (2, datetime(2024, 3, 1, 22, 0), 20.0),
        (2, datetime(2024, 3, 2, 6, 0), 30.0),
        # LocalID 10 la tram dien (station) -> phai bi loai khoi tong tieu thu
        (10, datetime(2024, 3, 1, 6, 0), 5000.0),
        (10, datetime(2024, 3, 2, 6, 0), 9000.0),
    ]
    result = aggregate_ca_values(raw_rows, _names(), boundaries)

    assert result["total_kwh"] == 520.0  # 160 (ca1) + 150 (ca2) + 210 (ca3)
    by_ca = {c["ca"]: c["value"] for c in result["by_ca"]}
    assert by_ca[1] == 160.0   # (250-100) + (20-10)
    assert by_ca[2] == 150.0   # (400-250) + (20-20)
    assert by_ca[3] == 210.0   # (600-400) + (30-20)
    assert len(result["shifts"]) == 3
    assert result["by_day"] == [{"date": "2024-03-01", "ca1": 160.0, "ca2": 150.0, "ca3": 210.0, "has_gap": False}]


def test_aggregate_ca_values_uses_nearest_sample_before_boundary_not_after():
    """LOCF: bản ghi lúc 22h10 nằm SAU mốc 22h00 nên KHÔNG được dùng cho mốc này — dù gần hơn
    về mặt thời gian so với bản ghi 13h55. Mốc 22h00 phải dùng bản ghi 13h55 (gần nhất TRƯỚC
    mốc), nên Ca 2 (14h-22h) = 200 - 200 = 0 (không tăng thêm, vì không có bản ghi nào mới
    trước 22h ngoài chính bản ghi đã dùng cho mốc 14h)."""
    boundaries = shift_boundaries(datetime(2024, 3, 1, 6, 0), datetime(2024, 3, 1, 22, 0))
    raw_rows = [
        (1, datetime(2024, 3, 1, 5, 50), 100.0),   # gan moc 06h nhat (truoc moc)
        (1, datetime(2024, 3, 1, 13, 55), 200.0),  # gan moc 14h nhat (truoc moc)
        (1, datetime(2024, 3, 1, 22, 10), 260.0),  # SAU moc 22h -> khong duoc dung cho moc nay
    ]
    result = aggregate_ca_values(raw_rows, _names(), boundaries)
    by_ca = {c["ca"]: c["value"] for c in result["by_ca"]}
    assert by_ca[1] == 100.0
    assert by_ca[2] == 0.0


def test_aggregate_ca_values_uses_nearest_sample_when_no_exact_boundary_hit():
    """Khi bản ghi gần mốc nhất nằm TRƯỚC mốc (không phải sau), LOCF chọn đúng bản ghi đó."""
    boundaries = shift_boundaries(datetime(2024, 3, 1, 6, 0), datetime(2024, 3, 1, 22, 0))
    raw_rows = [
        (1, datetime(2024, 3, 1, 5, 50), 100.0),   # gan moc 06h nhat
        (1, datetime(2024, 3, 1, 13, 55), 200.0),  # gan moc 14h nhat
        (1, datetime(2024, 3, 1, 21, 55), 260.0),  # gan moc 22h nhat, truoc moc
    ]
    result = aggregate_ca_values(raw_rows, _names(), boundaries)
    by_ca = {c["ca"]: c["value"] for c in result["by_ca"]}
    assert by_ca[1] == 100.0
    assert by_ca[2] == 60.0


def test_aggregate_ca_values_empty_input_returns_zero():
    boundaries = shift_boundaries(datetime(2024, 3, 1, 6, 0), datetime(2024, 3, 1, 22, 0))
    result = aggregate_ca_values([], _names(), boundaries)
    assert result["total_kwh"] == 0.0
    assert all(c["value"] == 0.0 for c in result["by_ca"])


def test_aggregate_ca_values_flags_gap_without_poisoning_other_local_ids():
    """1 LocalID có khoảng trống dữ liệu lớn (hồi phục dữ liệu ngay TRONG ca 1) chỉ làm ca 1
    của riêng LocalID đó bị loại (không cộng số bịa) — ca 2 của cùng LocalID vẫn tính được vì cả
    2 mốc 14h/22h đều gần dữ liệu thật. LocalID khác không gap vẫn tính bình thường cho cả 2 ca
    — khác với báo cáo chiết lon/keg (1 nguồn dữ liệu duy nhất), ở đây nhiều hệ thống độc lập
    nên 1 hệ gặp gap không cần làm mất số toàn bộ."""
    boundaries = shift_boundaries(datetime(2024, 3, 1, 6, 0), datetime(2024, 3, 1, 22, 0))
    raw_rows = [
        # LocalID 1: gap du lieu that hon 1 nam, "song lai" luc 13h55 (TRONG ca 1, truoc moc 14h)
        (1, datetime(2023, 1, 1, 0, 0), 1000.0),
        (1, datetime(2024, 3, 1, 13, 55), 1200.0),
        (1, datetime(2024, 3, 1, 21, 55), 1300.0),
        # LocalID 2: du lieu binh thuong, khong gap
        (2, datetime(2024, 3, 1, 5, 50), 10.0),
        (2, datetime(2024, 3, 1, 13, 55), 20.0),
        (2, datetime(2024, 3, 1, 21, 55), 35.0),
    ]
    result = aggregate_ca_values(raw_rows, _names(), boundaries)
    by_ca = {c["ca"]: c for c in result["by_ca"]}

    assert by_ca[1]["value"] == 10.0  # chi LocalID 2 dong gop (20-10); LocalID 1 bi loai vi moc 06h gap
    assert by_ca[1]["data_gap"] is True
    assert by_ca[2]["value"] == 115.0  # ca 2: LocalID 1 (1300-1200=100, moc 14h/22h deu gan) + LocalID 2 (35-20=15)
    assert by_ca[2]["data_gap"] is False
    assert result["has_gap"] is True
