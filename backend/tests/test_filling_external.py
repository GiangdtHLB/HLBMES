"""Test logic thuần (không cần CSDL SQL Server thật) của báo cáo sản lượng chiết lon:
TotalCan là bộ đếm cộng dồn, shift_boundaries/ca_number phải tính đúng ranh giới 3 ca
(06-14/14-22/22-06) và làm tròn khoảng ngày ra ca trọn vẹn."""

from datetime import datetime

from app.services.filling_external import (
    aggregate_filling_values,
    ca_number,
    nearest_gap_hours,
    nearest_value,
    reliable_at_boundaries,
    shift_boundaries,
    values_at_boundaries,
)


def test_ca_number_boundaries():
    assert ca_number(datetime(2024, 3, 1, 6, 0)) == 1
    assert ca_number(datetime(2024, 3, 1, 14, 0)) == 2
    assert ca_number(datetime(2024, 3, 1, 22, 0)) == 3


def test_shift_boundaries_exact_alignment():
    d_from = datetime(2024, 3, 1, 6, 0)
    d_to = datetime(2024, 3, 1, 22, 0)
    b = shift_boundaries(d_from, d_to)
    assert b == [datetime(2024, 3, 1, 6, 0), datetime(2024, 3, 1, 14, 0), datetime(2024, 3, 1, 22, 0)]


def test_shift_boundaries_rounds_out_partial_shift():
    """Chọn giờ lẻ (không đúng ranh giới ca) phải được làm tròn ra trọn ca, không cắt nửa ca."""
    d_from = datetime(2024, 3, 1, 8, 0)   # giữa ca 1 (06-14h)
    d_to = datetime(2024, 3, 1, 20, 0)    # giữa ca 2 (14-22h)
    b = shift_boundaries(d_from, d_to)
    assert b[0] == datetime(2024, 3, 1, 6, 0)   # làm tròn về đầu ca 1
    assert b[-1] == datetime(2024, 3, 1, 22, 0)  # làm tròn ra cuối ca 2


def test_shift_boundaries_overnight_ca3():
    """Ca 3 (22h-06h) phải xuyên qua nửa đêm sang ngày hôm sau."""
    d_from = datetime(2024, 3, 1, 22, 0)
    d_to = datetime(2024, 3, 2, 6, 0)
    b = shift_boundaries(d_from, d_to)
    assert b == [datetime(2024, 3, 1, 22, 0), datetime(2024, 3, 2, 6, 0)]
    assert ca_number(b[0]) == 3


def test_shift_boundaries_multi_day():
    d_from = datetime(2024, 3, 1, 6, 0)
    d_to = datetime(2024, 3, 3, 6, 0)
    b = shift_boundaries(d_from, d_to)
    # 2 ngày trọn = 6 ca -> 7 mốc ranh giới
    assert len(b) == 7
    cas = [ca_number(x) for x in b[:-1]]
    assert cas == [1, 2, 3, 1, 2, 3]


def test_nearest_value_prefers_before_even_when_after_is_closer():
    """LOCF: dù bản ghi SAU target gần hơn về thời gian, vẫn phải lấy bản ghi TRƯỚC/TẠI target
    (không được lấy giá trị tương lai so với target)."""
    target = datetime(2024, 3, 1, 10, 0)
    before = (datetime(2024, 3, 1, 9, 0), 100.0)   # 1h trước -> phải chọn cái này
    after = (datetime(2024, 3, 1, 10, 30), 150.0)  # 30' sau, gần hơn nhưng KHÔNG được chọn
    assert nearest_value([before, after], target) == 100.0


def test_nearest_value_picks_latest_among_before_candidates():
    target = datetime(2024, 3, 1, 10, 0)
    earlier = (datetime(2024, 3, 1, 8, 0), 90.0)
    closer_before = (datetime(2024, 3, 1, 9, 50), 100.0)   # gần target nhất trong số các bản ghi <= target
    after = (datetime(2024, 3, 1, 12, 0), 150.0)
    assert nearest_value([earlier, closer_before, after], target) == 100.0


def test_nearest_value_falls_back_to_after_when_no_record_before_target():
    """Chỉ khi HOÀN TOÀN không có bản ghi nào <= target (VD target trước cả bản ghi đầu tiên)
    mới lấy bản ghi gần nhất SAU target làm phương án dự phòng."""
    target = datetime(2024, 3, 1, 10, 0)
    after = (datetime(2024, 3, 1, 11, 0), 200.0)
    assert nearest_value([None, after], target) == 200.0
    assert nearest_value([None, None], target) == 0.0


def test_nearest_value_large_gap_still_prefers_before():
    """Mô phỏng khoảng trống nhiều ngày không có bản ghi — vẫn phải ưu tiên bản ghi TRƯỚC target
    dù bản ghi SAU gần hơn về thời gian (đây chính là ca thực tế: dữ liệu SCADA ngừng ghi, mốc
    cuối ca rơi vào khoảng trống — không được "mượn" số liệu tương lai)."""
    target = datetime(2024, 3, 5, 6, 0)
    before = (datetime(2024, 2, 28, 23, 58), 500.0)   # ~5.1 ngày trước
    after = (datetime(2024, 3, 6, 9, 0), 700.0)        # ~1.1 ngày sau, gần hơn nhưng KHÔNG được chọn
    assert nearest_value([before, after], target) == 500.0


def test_values_at_boundaries_uses_one_shared_candidate_set():
    """Mô phỏng 1 lượt fetch duy nhất (before_first + in_range + after_last) rồi chọn giá trị
    (LOCF: gần nhất nhưng không vượt quá) cho từng mốc ca — thay cho việc truy vấn riêng mỗi
    mốc (chậm vì nhiều round-trip). Mốc cuối vẫn có bản ghi trước đó (21h00) nên KHÔNG dùng
    tới after_last — after_last chỉ là phương án dự phòng khi không có bản ghi nào trước mốc."""
    boundaries = [
        datetime(2024, 3, 1, 6, 0), datetime(2024, 3, 1, 14, 0),
        datetime(2024, 3, 1, 22, 0), datetime(2024, 3, 2, 6, 0),
    ]
    candidates = [
        (datetime(2024, 3, 1, 5, 0), 100.0),    # before_first
        (datetime(2024, 3, 1, 13, 50), 150.0),  # trong khoảng, <= moc Ca1->Ca2
        (datetime(2024, 3, 1, 21, 0), 300.0),   # trong khoảng, <= moc Ca2->Ca3 và cũng <= moc cuối
        (datetime(2024, 3, 2, 7, 0), 500.0),    # after_last — sau tất cả các mốc, không được dùng
    ]
    values = values_at_boundaries(candidates, boundaries)
    # moc 06h -> 100 (05h00). moc 14h -> 150 (13h50). moc 22h -> 300 (21h00).
    # moc 02/06h: ban ghi <= moc nay gan nhat van la 300 (21h00 hom truoc) vi khong co ban ghi nao
    # khac trong khoang 21h00 -> 02/06h00; KHONG duoc "muon" 500 (07h00, sau moc).
    assert values == [100.0, 150.0, 300.0, 300.0]


def test_values_at_boundaries_falls_back_to_after_when_report_window_precedes_all_data():
    """Nếu toàn bộ dữ liệu thật đều nằm SAU mốc báo cáo (VD báo cáo 1 ngày rất cũ, dây chuyền
    mới lắp gần đây), mọi mốc đều không có bản ghi nào trước đó — khi đó mới dùng bản ghi gần
    nhất SAU mốc làm phương án dự phòng."""
    boundaries = [datetime(2024, 3, 1, 6, 0), datetime(2024, 3, 1, 14, 0)]
    candidates = [(datetime(2024, 3, 5, 0, 0), 900.0)]  # du lieu that chi bat dau sau ca nay
    values = values_at_boundaries(candidates, boundaries)
    assert values == [900.0, 900.0]


def test_nearest_gap_hours_reports_distance_to_chosen_record():
    target = datetime(2024, 3, 1, 10, 0)
    before = (datetime(2024, 3, 1, 8, 0), 100.0)
    assert nearest_gap_hours([before], target) == 2.0


def test_nearest_gap_hours_none_when_no_candidates():
    target = datetime(2024, 3, 1, 10, 0)
    assert nearest_gap_hours([None, None], target) is None


def test_reliable_at_boundaries_flags_large_data_gap():
    """Mô phỏng đúng sự cố thật gặp phải: CSDL nguồn ngừng ghi hơn 1 năm rồi mới ghi lại — mốc
    rơi ngay sau lúc dữ liệu "sống lại" phải được đánh dấu KHÔNG đáng tin vì bản ghi LOCF gần
    nhất cách quá xa (thay vì âm thầm dùng nó, cho ra hiệu số khổng lồ vô nghĩa)."""
    boundaries = [datetime(2024, 3, 1, 6, 0), datetime(2024, 3, 1, 14, 0), datetime(2024, 3, 1, 22, 0)]
    candidates = [
        (datetime(2023, 1, 1, 0, 0), 1000.0),    # ban ghi hon 1 nam truoc, cach xa moc 06h/14h
        (datetime(2024, 3, 1, 14, 49), 5000.0),  # du lieu "song lai", ngay sau moc 14h
        (datetime(2024, 3, 1, 21, 55), 5200.0),  # gan moc 22h, dang tin
    ]
    reliable = reliable_at_boundaries(candidates, boundaries, max_gap_hours=48)
    assert reliable == [False, False, True]


def test_reliable_at_boundaries_true_within_gap_threshold():
    boundaries = [datetime(2024, 3, 1, 6, 0)]
    candidates = [(datetime(2024, 2, 28, 12, 0), 100.0)]  # cach moc dung 42h, trong nguong 48h
    reliable = reliable_at_boundaries(candidates, boundaries, max_gap_hours=48)
    assert reliable == [True]


def test_aggregate_filling_values_nulls_shift_across_large_data_gap():
    """Ca có 1 trong 2 mốc rơi vào khoảng trống dữ liệu lớn phải trả "cans": None kèm
    "data_gap": True — không được cộng dồn số bịa vào total/by_ca/by_day."""
    boundaries = shift_boundaries(datetime(2024, 3, 1, 6, 0), datetime(2024, 3, 1, 22, 0))
    candidates = [
        (datetime(2023, 1, 1, 0, 0), 1000.0),   # rat xa moc 06h -> khong dang tin
        (datetime(2024, 3, 1, 13, 55), 5000.0),  # "song lai" TRONG ca 1, gan moc 14h
        (datetime(2024, 3, 1, 21, 55), 5200.0),  # gan moc 22h, dang tin
    ]
    result = aggregate_filling_values(candidates, boundaries)

    assert result["shifts"][0]["cans"] is None
    assert result["shifts"][0]["data_gap"] is True
    assert result["shifts"][1]["cans"] == 200  # 5200 - 5000, ca dung ca 2 moc dang tin
    assert result["shifts"][1]["data_gap"] is False

    by_ca = {c["ca"]: c for c in result["by_ca"]}
    assert by_ca[1]["data_gap"] is True
    assert by_ca[2]["value"] == 200
    assert by_ca[2]["data_gap"] is False

    assert result["has_gap"] is True
    assert result["total_cans"] == 200  # chi cong ca dang tin, khong "muon" so tu ca bi gap


def test_aggregate_filling_values_no_gap_matches_direct_diff():
    boundaries = shift_boundaries(datetime(2024, 3, 1, 6, 0), datetime(2024, 3, 1, 22, 0))
    candidates = [
        (datetime(2024, 3, 1, 6, 0), 100.0),
        (datetime(2024, 3, 1, 14, 0), 250.0),
        (datetime(2024, 3, 1, 22, 0), 400.0),
    ]
    result = aggregate_filling_values(candidates, boundaries)
    assert result["has_gap"] is False
    assert result["total_cans"] == 300  # 400 - 100
    assert all(not s["data_gap"] for s in result["shifts"])
