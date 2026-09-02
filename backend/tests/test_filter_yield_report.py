"""Test báo cáo sản lượng lọc theo mẻ (GET /api/reports/filter-yield-report) — phân loại
Thấp/Bình thường/Cao theo ngưỡng OpsSetting.filter_yield_low_hl/high_hl, và test lưu 2 ngưỡng
này qua PUT /api/ops-settings. Xem services/filter_yield_report.py."""

import os
import tempfile

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["MES_DATABASE_URL"] = f"sqlite:///{_TMP.name}"
os.environ["MES_DEV_HEADER_AUTH"] = "0"
os.environ["MES_RL_ENABLED"] = "0"
os.environ["MES_ADMIN_PASSWORD"] = "AdminTest123"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import seed as seed_mod


@pytest.fixture(scope="module", autouse=True)
def _seeded():
    seed_mod.seed()
    yield


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture(scope="module")
def admin_h(client):
    return _login(client, "admin", "AdminTest123")


@pytest.fixture(scope="module")
def vanhanh_h(client):
    return _login(client, "vanhanh", "123456")


def _a_brew_order(client, admin_h, order_code):
    r = client.post("/api/brewing/orders", headers=admin_h,
                    json={"order_code": order_code, "auto_from_bom": False, "planned_volume_hl": 200})
    assert r.status_code == 201, r.text
    return r.json()["brew_order_id"]


def _setup_ferment(client, admin_h, vanhanh_h, suffix):
    order_id = _a_brew_order(client, admin_h, f"LN-{suffix}")
    b = client.post("/api/brewing/brews", headers=vanhanh_h,
                    json={"brew_code": f"BR-{suffix}", "wort_type": "Dịch test", "volume_hl": 200,
                          "lm_code": f"LM-{suffix}", "tank_lm": f"T-{suffix}", "brew_order_id": order_id})
    assert b.status_code == 201, b.text
    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment = next(f for f in ferments if f["lm_code"] == f"LM-{suffix}")
    ok = client.post(f"/api/brewing/ferments/{ferment['ferment_id']}/approve", headers=admin_h)
    assert ok.status_code == 200, ok.text
    return ferment["ferment_id"]


def _a_filter_order(client, admin_h, vanhanh_h, suffix, planned_v_dich_hl=200.0):
    ferment_id = _setup_ferment(client, admin_h, vanhanh_h, suffix)
    order = client.post("/api/brewing/filter-master-orders", headers=admin_h,
                       json={"order_code": f"LOC-{suffix}",
                             "children": [{"blend_mode": "khong_phoi",
                                          "tanks": [{"tank_type": "cct", "ferment_id": ferment_id,
                                                    "planned_v_dich_hl": planned_v_dich_hl}]}]})
    assert order.status_code == 201, order.text
    master = client.get(f"/api/brewing/filter-master-orders/{order.json()['filter_master_order_id']}",
                        headers=admin_h).json()
    return master["children"][0]["filter_order_id"]


def _finish_one_mẻ(client, admin_h, vanhanh_h, suffix, v_dich_hl, nuoc_bai_khi_hl=0.0):
    order_id = _a_filter_order(client, admin_h, vanhanh_h, suffix)
    r = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": f"FL-{suffix}", "filter_order_id": order_id, "to_bbt": f"BBT-{suffix}"})
    assert r.status_code == 201, r.text
    filter_id = r.json()["filter_id"]
    tanks = client.get(f"/api/brewing/filters/{filter_id}/tanks", headers=admin_h).json()
    line_id = tanks[0]["line_id"]
    fin = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line_id}/finish", headers=vanhanh_h,
                      json={"v_dich_hl": v_dich_hl, "nuoc_bai_khi_hl": nuoc_bai_khi_hl,
                            "batch_number": f"B-{suffix}", "order_number": f"O-{suffix}", "batch_seq_no": "1"})
    assert fin.status_code == 200, fin.text
    return filter_id


def test_ops_settings_persist_filter_yield_thresholds(client, admin_h):
    r = client.put("/api/ops-settings", headers=admin_h,
                  json={"empty_cct_tolerance_hl": 2.0, "empty_bbt_tolerance_hl": 2.0,
                        "aging_caution_days": 30, "aging_warning_days": 60, "aging_critical_days": 90,
                        "filter_yield_low_hl": 40.0, "filter_yield_high_hl": 120.0})
    assert r.status_code == 200, r.text
    assert r.json()["filter_yield_low_hl"] == 40.0
    assert r.json()["filter_yield_high_hl"] == 120.0

    g = client.get("/api/ops-settings", headers=admin_h)
    assert g.json()["filter_yield_low_hl"] == 40.0
    assert g.json()["filter_yield_high_hl"] == 120.0

    # trả lại ngưỡng mặc định 50/150 để không ảnh hưởng các test khác trong cùng module.
    back = client.put("/api/ops-settings", headers=admin_h,
                      json={"empty_cct_tolerance_hl": 2.0, "empty_bbt_tolerance_hl": 2.0,
                            "aging_caution_days": 30, "aging_warning_days": 60, "aging_critical_days": 90,
                            "filter_yield_low_hl": 50.0, "filter_yield_high_hl": 150.0})
    assert back.status_code == 200, back.text


def test_filter_yield_report_classifies_and_groups(client, admin_h, vanhanh_h):
    # Mặc định 50/150hl: 30hl -> Thấp, 100hl -> Bình thường, 200hl -> Cao.
    low_id = _finish_one_mẻ(client, admin_h, vanhanh_h, "YLD-LOW", 28, 2)     # v_beer_hl=30
    mid_id = _finish_one_mẻ(client, admin_h, vanhanh_h, "YLD-MID", 95, 5)    # v_beer_hl=100
    high_id = _finish_one_mẻ(client, admin_h, vanhanh_h, "YLD-HIGH", 190, 10)  # v_beer_hl=200

    r = client.get("/api/reports/filter-yield-report", headers=admin_h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["low_hl"] == 50.0
    assert data["high_hl"] == 150.0
    assert data["has_warning"] is True

    by_id = {it["filter_id"]: it for it in data["items"]}
    assert by_id[low_id]["classification"] == "thap"
    assert by_id[mid_id]["classification"] == "binh_thuong"
    assert by_id[high_id]["classification"] == "cao"
    assert data["low_count"] >= 1

    # nhóm theo tuần/tháng vẫn chạy được, không lỗi.
    for gb in ("week", "month"):
        rg = client.get(f"/api/reports/filter-yield-report?group_by={gb}", headers=admin_h)
        assert rg.status_code == 200, rg.text
        assert rg.json()["group_by"] == gb
        assert sum(p["total"] for p in rg.json()["series"]) == rg.json()["total"]


def test_filter_yield_report_excludes_unfinished(client, admin_h, vanhanh_h):
    order_id = _a_filter_order(client, admin_h, vanhanh_h, "YLD-UNFIN")
    r = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": "FL-YLD-UNFIN", "filter_order_id": order_id, "to_bbt": "BBT-YLD-UNFIN"})
    assert r.status_code == 201, r.text
    filter_id = r.json()["filter_id"]

    rep = client.get("/api/reports/filter-yield-report", headers=admin_h)
    ids = {it["filter_id"] for it in rep.json()["items"]}
    assert filter_id not in ids


def test_ops_settings_persist_filter_line_yield_thresholds(client, admin_h):
    r = client.put("/api/ops-settings", headers=admin_h,
                  json={"empty_cct_tolerance_hl": 2.0, "empty_bbt_tolerance_hl": 2.0,
                        "aging_caution_days": 30, "aging_warning_days": 60, "aging_critical_days": 90,
                        "filter_yield_low_hl": 50.0, "filter_yield_high_hl": 150.0,
                        "filter_line_yield_low_l": 400.0, "filter_line_yield_high_l": 1500.0})
    assert r.status_code == 200, r.text
    assert r.json()["filter_line_yield_low_l"] == 400.0
    assert r.json()["filter_line_yield_high_l"] == 1500.0

    g = client.get("/api/ops-settings", headers=admin_h)
    assert g.json()["filter_line_yield_low_l"] == 400.0
    assert g.json()["filter_line_yield_high_l"] == 1500.0

    # trả lại ngưỡng mặc định 500/2000 để không ảnh hưởng các test khác trong cùng module.
    back = client.put("/api/ops-settings", headers=admin_h,
                      json={"empty_cct_tolerance_hl": 2.0, "empty_bbt_tolerance_hl": 2.0,
                            "aging_caution_days": 30, "aging_warning_days": 60, "aging_critical_days": 90,
                            "filter_yield_low_hl": 50.0, "filter_yield_high_hl": 150.0,
                            "filter_line_yield_low_l": 500.0, "filter_line_yield_high_l": 2000.0})
    assert back.status_code == 200, back.text


def test_filter_line_yield_report_classifies_with_lineage(client, admin_h, vanhanh_h):
    # Mặc định 500/2000 lít: 300L -> Thấp, 800L -> Bình thường, 2500L -> Cao.
    low_filter_id = _finish_one_mẻ(client, admin_h, vanhanh_h, "LYLD-LOW", 3, 0)     # 300L
    mid_filter_id = _finish_one_mẻ(client, admin_h, vanhanh_h, "LYLD-MID", 8, 0)     # 800L
    high_filter_id = _finish_one_mẻ(client, admin_h, vanhanh_h, "LYLD-HIGH", 25, 0)  # 2500L

    r = client.get("/api/reports/filter-line-yield-report", headers=admin_h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["low_l"] == 500.0
    assert data["high_l"] == 2000.0
    assert data["has_warning"] is True

    by_filter = {it["filter_id"]: it for it in data["items"]}
    low_it, mid_it, high_it = by_filter[low_filter_id], by_filter[mid_filter_id], by_filter[high_filter_id]
    assert low_it["classification"] == "thap"
    assert low_it["v_l"] == 300.0
    assert mid_it["classification"] == "binh_thuong"
    assert mid_it["v_l"] == 800.0
    assert high_it["classification"] == "cao"
    assert high_it["v_l"] == 2500.0

    # Truy vết tank lên men/mẻ nấu/ngày vào dịch — khớp với _setup_ferment(suffix="LYLD-LOW").
    assert low_it["tank_lm"] == "T-LYLD-LOW"
    assert low_it["brew_code"] == "BR-LYLD-LOW"
    assert low_it["brew_date"] is not None
    assert low_it["batch_seq_no"] == "1"

    # Ngày lọc, loại dịch bia, và tách V dịch bia/V nước DAW theo yêu cầu bổ sung — beer_type có
    # thể rỗng ở test này vì _a_filter_order không khai báo Loại bia cụ thể, chỉ cần có mặt field.
    assert low_it["filter_date"] is not None
    assert "beer_type" in low_it
    assert low_it["v_dich_l"] == 300.0
    assert low_it["v_daw_l"] == 0.0


def test_filter_line_yield_report_excludes_unfinished(client, admin_h, vanhanh_h):
    order_id = _a_filter_order(client, admin_h, vanhanh_h, "LYLD-UNFIN")
    r = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": "FL-LYLD-UNFIN", "filter_order_id": order_id, "to_bbt": "BBT-LYLD-UNFIN"})
    assert r.status_code == 201, r.text
    filter_id = r.json()["filter_id"]

    rep = client.get("/api/reports/filter-line-yield-report", headers=admin_h)
    ids = {it["filter_id"] for it in rep.json()["items"]}
    assert filter_id not in ids


def test_finish_filter_tank_allows_reused_batch_order_number_across_lenh_loc(client, admin_h, vanhanh_h):
    # Trước đây bị chặn 409 khi 2 lệnh lọc KHÁC NHAU dùng cùng batch_number/order_number — nay
    # cho phép trùng tự do (thực tế số mẻ/số lệnh giấy có thể lặp lại giữa các lệnh lọc khác nhau).
    order_a = _a_filter_order(client, admin_h, vanhanh_h, "REUSE-A")
    fa = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": "FL-REUSE-A", "filter_order_id": order_a, "to_bbt": "BBT-REUSE-A"})
    assert fa.status_code == 201, fa.text
    tanks_a = client.get(f"/api/brewing/filters/{fa.json()['filter_id']}/tanks", headers=admin_h).json()
    fin_a = client.post(f"/api/brewing/filters/{fa.json()['filter_id']}/tanks/{tanks_a[0]['line_id']}/finish",
                       headers=vanhanh_h, json={"v_dich_hl": 10, "nuoc_bai_khi_hl": 0,
                                                 "batch_number": "B-SAME", "order_number": "O-SAME", "batch_seq_no": "1"})
    assert fin_a.status_code == 200, fin_a.text

    order_b = _a_filter_order(client, admin_h, vanhanh_h, "REUSE-B")
    fb = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": "FL-REUSE-B", "filter_order_id": order_b, "to_bbt": "BBT-REUSE-B"})
    assert fb.status_code == 201, fb.text
    tanks_b = client.get(f"/api/brewing/filters/{fb.json()['filter_id']}/tanks", headers=admin_h).json()
    fin_b = client.post(f"/api/brewing/filters/{fb.json()['filter_id']}/tanks/{tanks_b[0]['line_id']}/finish",
                       headers=vanhanh_h, json={"v_dich_hl": 20, "nuoc_bai_khi_hl": 0,
                                                 "batch_number": "B-SAME", "order_number": "O-SAME", "batch_seq_no": "1"})
    assert fin_b.status_code == 200, fin_b.text


def test_filter_line_yield_report_merges_same_batch_across_different_lenh_loc(client, admin_h, vanhanh_h):
    # 2 lệnh lọc HOÀN TOÀN khác nhau, nhưng cùng bộ 3 (batch_number, order_number, batch_seq_no)
    # — thực tế đây là 1 mẻ giấy thật bị tách ghi nhận qua 2 lệnh lọc khác nhau, báo cáo phải
    # gộp lại thành 1 dòng, cộng dồn thể tích.
    order_a = _a_filter_order(client, admin_h, vanhanh_h, "MERGE-A")
    fa = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": "FL-MERGE-A", "filter_order_id": order_a, "to_bbt": "BBT-MERGE-A"})
    assert fa.status_code == 201, fa.text
    filter_id_a = fa.json()["filter_id"]
    tanks_a = client.get(f"/api/brewing/filters/{filter_id_a}/tanks", headers=admin_h).json()
    fin_a = client.post(f"/api/brewing/filters/{filter_id_a}/tanks/{tanks_a[0]['line_id']}/finish",
                       headers=vanhanh_h, json={"v_dich_hl": 3, "nuoc_bai_khi_hl": 0,
                                                 "batch_number": "B-MERGE-X", "order_number": "O-MERGE-X",
                                                 "batch_seq_no": "9"})
    assert fin_a.status_code == 200, fin_a.text

    order_b = _a_filter_order(client, admin_h, vanhanh_h, "MERGE-B")
    fb = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": "FL-MERGE-B", "filter_order_id": order_b, "to_bbt": "BBT-MERGE-B"})
    assert fb.status_code == 201, fb.text
    filter_id_b = fb.json()["filter_id"]
    tanks_b = client.get(f"/api/brewing/filters/{filter_id_b}/tanks", headers=admin_h).json()
    fin_b = client.post(f"/api/brewing/filters/{filter_id_b}/tanks/{tanks_b[0]['line_id']}/finish",
                       headers=vanhanh_h, json={"v_dich_hl": 2, "nuoc_bai_khi_hl": 0,
                                                 "batch_number": "B-MERGE-X", "order_number": "O-MERGE-X",
                                                 "batch_seq_no": "9"})
    assert fin_b.status_code == 200, fin_b.text

    rep = client.get("/api/reports/filter-line-yield-report", headers=admin_h)
    assert rep.status_code == 200, rep.text
    items = [it for it in rep.json()["items"] if it["batch_seq_no"] == "9" and "MERGE" in (it["filter_code"] or "")]
    assert len(items) == 1, f"Kỳ vọng 2 dòng bị gộp thành 1, có {len(items)}: {items}"
    merged = items[0]
    assert merged["v_l"] == 500.0  # (3+2)hl * 100 = 500L
    assert merged["filter_code"] == "FL-MERGE-A + FL-MERGE-B"


def test_final_batch_toggle_excludes_from_classification(client, admin_h, vanhanh_h):
    order_id = _a_filter_order(client, admin_h, vanhanh_h, "FINALBATCH")
    r = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": "FL-FINALBATCH", "filter_order_id": order_id, "to_bbt": "BBT-FINALBATCH"})
    assert r.status_code == 201, r.text
    filter_id = r.json()["filter_id"]
    tanks = client.get(f"/api/brewing/filters/{filter_id}/tanks", headers=admin_h).json()
    line_id = tanks[0]["line_id"]
    fin = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line_id}/finish", headers=vanhanh_h,
                      json={"v_dich_hl": 1, "nuoc_bai_khi_hl": 0,  # 100L -> Thấp (mặc định ≤500L)
                            "batch_number": "B-FINALBATCH", "order_number": "O-FINALBATCH", "batch_seq_no": "1"})
    assert fin.status_code == 200, fin.text

    rep1 = client.get("/api/reports/filter-line-yield-report", headers=admin_h)
    it1 = next(it for it in rep1.json()["items"] if it["filter_code"] == "FL-FINALBATCH")
    assert it1["classification"] == "thap"

    toggle = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line_id}/toggle-final", headers=vanhanh_h)
    assert toggle.status_code == 200, toggle.text
    assert toggle.json()["is_final_batch"] is True

    rep2 = client.get("/api/reports/filter-line-yield-report", headers=admin_h)
    it2 = next(it for it in rep2.json()["items"] if it["filter_code"] == "FL-FINALBATCH")
    assert it2["classification"] == "cuoi"
    assert it2["classification_label"] == "Mẻ cuối (không tính)"
    assert rep2.json()["low_count"] < rep1.json()["low_count"], "mẻ cuối phải bị loại khỏi đếm Thấp"

    # Bỏ đánh dấu lại để không ảnh hưởng test khác trong cùng module.
    toggle2 = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line_id}/toggle-final", headers=vanhanh_h)
    assert toggle2.json()["is_final_batch"] is False


def test_filter_line_yield_report_still_works_via_old_pipeline(client, admin_h, vanhanh_h):
    """GET /api/reports/filter-line-yield-report (services/filter_yield_report.py, theo
    FilterOrderTank module Nấu-Lọc-Chiết cũ) không đổi — chỉ Dashboard widget "Sản lượng lọc
    thấp" (GET /api/reports/low-yield-filter-alerts) đã đổi nguồn sang pipeline "Mẻ sản xuất"
    mới (BatchFilterLotBatch, xem test_dashboard_summary.py::
    test_low_yield_filter_alerts_source_from_new_batch_pipeline), theo yêu cầu người dùng
    2026-09-02: "Sản lượng lọc thấp thì lấy theo mẻ của Lọc"."""
    low_filter_id = _finish_one_mẻ(client, admin_h, vanhanh_h, "OLDLOW", 2, 0)  # 200L -> Thấp
    rep = client.get("/api/reports/filter-line-yield-report", headers=admin_h)
    assert rep.status_code == 200, rep.text
    ids = {it["filter_id"] for it in rep.json()["items"]}
    assert low_filter_id in ids
