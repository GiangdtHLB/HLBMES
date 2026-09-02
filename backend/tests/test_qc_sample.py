"""Test lấy mẫu NHIỀU LẦN (lần 1/lần 2/...) cho CT chính/CT phụ lên men — khác cơ chế
"giá trị hiện tại" (ghi đè tại chỗ) của record_stage_result dùng cho Nấu/Lọc/Chiết. Xem
qc_catalog.MULTI_SAMPLE_STAGES/record_qc_sample/list_qc_samples."""

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


def _make_group_with_param(client, admin_h, suffix, stage="len_men_chinh"):
    p = client.post("/api/qc/parameters", headers=admin_h,
                    json={"code": f"CT_{suffix}", "name": f"Chỉ tiêu {suffix}", "lsl": 1, "usl": 10})
    assert p.status_code == 201, p.text
    param_id = p.json()["param_id"]
    g = client.post("/api/qc/groups", headers=admin_h,
                    json={"code": f"GRP_{suffix}", "name": f"Nhóm {suffix}"})
    assert g.status_code == 201, g.text
    group_id = g.json()["group_id"]
    it = client.post(f"/api/qc/groups/{group_id}/items", headers=admin_h,
                     json={"param_id": param_id, "mandatory": True})
    assert it.status_code == 201, it.text
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": stage, "group_id": group_id, "mandatory": True})
    assert link.status_code == 201, link.text
    return f"CT_{suffix}"


def _make_ferment(client, admin_h, vanhanh_h, suffix):
    order = client.post("/api/brewing/orders", headers=admin_h,
                        json={"order_code": f"LN-QCS-{suffix}", "auto_from_bom": False,
                              "planned_volume_hl": 100})
    assert order.status_code == 201, order.text
    brew = client.post("/api/brewing/brews", headers=vanhanh_h,
                       json={"brew_code": f"BR-QCS-{suffix}", "wort_type": "Dịch test", "volume_hl": 100,
                             "lm_code": f"LM-QCS-{suffix}", "tank_lm": f"T-QCS-{suffix}",
                             "brew_order_id": order.json()["brew_order_id"]})
    assert brew.status_code == 201, brew.text
    return f"LM-QCS-{suffix}"


def test_sample_rejected_for_non_multi_sample_stage(client, admin_h, vanhanh_h):
    lm_code = _make_ferment(client, admin_h, vanhanh_h, "REJECT")
    r = client.post("/api/brewing/qc-samples", headers=vanhanh_h,
                    json={"stage": "loc", "scope_type": "ferment", "scope_id": f"{lm_code}__len_men_chinh",
                          "results": [{"parameter": "X", "value": 1}]})
    assert r.status_code == 409, r.text


def test_multiple_samples_kept_as_history_and_latest_wins(client, admin_h, vanhanh_h):
    param_code = _make_group_with_param(client, admin_h, "SAMPLE1", stage="len_men_chinh")
    lm_code = _make_ferment(client, admin_h, vanhanh_h, "SAMPLE1")
    scope_id = f"{lm_code}__len_men_chinh"

    # Lần 1: FAIL (20 vượt usl=10), ngày giờ sớm hơn
    r1 = client.post("/api/brewing/qc-samples", headers=vanhanh_h,
                     json={"stage": "len_men_chinh", "scope_type": "ferment", "scope_id": scope_id,
                           "sampled_at": "2026-07-10T08:00:00+00:00",
                           "results": [{"parameter": param_code, "value": 20, "lower_limit": 1, "upper_limit": 10}]})
    assert r1.status_code == 201, r1.text
    assert r1.json()["results"][0]["status"] == "fail"

    status_after_1 = client.get("/api/brewing/qc-status", headers=admin_h,
                                params={"stage": "len_men_chinh", "scope_type": "ferment", "scope_id": scope_id}).json()
    assert status_after_1["has_fail"] is True
    assert status_after_1["can_release"] is False

    # Lần 2: PASS (5 trong khoảng), ngày giờ MUỘN hơn lần 1
    r2 = client.post("/api/brewing/qc-samples", headers=vanhanh_h,
                     json={"stage": "len_men_chinh", "scope_type": "ferment", "scope_id": scope_id,
                           "sampled_at": "2026-07-11T08:00:00+00:00",
                           "results": [{"parameter": param_code, "value": 5, "lower_limit": 1, "upper_limit": 10}]})
    assert r2.status_code == 201, r2.text
    assert r2.json()["results"][0]["status"] == "pass"

    status_after_2 = client.get("/api/brewing/qc-status", headers=admin_h,
                                params={"stage": "len_men_chinh", "scope_type": "ferment", "scope_id": scope_id}).json()
    # Lần mới nhất PASS -> không còn bị chặn bởi FAIL cũ (chỉ theo lần mới nhất)
    assert status_after_2["has_fail"] is False
    assert status_after_2["can_release"] is True
    assert len(status_after_2["recorded"]) == 1  # dedup theo chỉ tiêu, không lặp cả 2 dòng lịch sử

    hist = client.get("/api/brewing/qc-samples", headers=admin_h,
                      params={"scope_type": "ferment", "scope_id": scope_id}).json()
    assert len(hist["items"]) == 2  # cả 2 lần vẫn còn trong lịch sử, không bị mất
    # Mới nhất trước
    assert hist["items"][0]["results"][0]["value"] == 5
    assert hist["items"][1]["results"][0]["value"] == 20


def test_sample_history_out_of_order_backfill_still_resolves_by_sampled_at(client, admin_h, vanhanh_h):
    """Ghi lần 2 (ngày giờ SAU) trước, rồi ghi bổ sung lần 1 (ngày giờ TRƯỚC) sau — hệ thống vẫn
    phải chọn đúng theo mốc sampled_at, không phải thứ tự gọi API."""
    param_code = _make_group_with_param(client, admin_h, "SAMPLE2", stage="len_men_phu")
    lm_code = _make_ferment(client, admin_h, vanhanh_h, "SAMPLE2")
    scope_id = f"{lm_code}__len_men_phu"

    r_later = client.post("/api/brewing/qc-samples", headers=vanhanh_h,
                          json={"stage": "len_men_phu", "scope_type": "ferment", "scope_id": scope_id,
                                "sampled_at": "2026-07-12T08:00:00+00:00",
                                "results": [{"parameter": param_code, "value": 5, "lower_limit": 1, "upper_limit": 10}]})
    assert r_later.status_code == 201, r_later.text

    r_earlier = client.post("/api/brewing/qc-samples", headers=vanhanh_h,
                            json={"stage": "len_men_phu", "scope_type": "ferment", "scope_id": scope_id,
                                  "sampled_at": "2026-07-11T08:00:00+00:00",
                                  "results": [{"parameter": param_code, "value": 20, "lower_limit": 1, "upper_limit": 10}]})
    assert r_earlier.status_code == 201, r_earlier.text

    status = client.get("/api/brewing/qc-status", headers=admin_h,
                        params={"stage": "len_men_phu", "scope_type": "ferment", "scope_id": scope_id}).json()
    # Mốc lấy mẫu mới nhất vẫn là lần "sampled_at" 07-12 (value=5, PASS), dù nó được ghi TRƯỚC
    assert status["recorded"][0]["value"] == 5
    assert status["has_fail"] is False
    assert status["can_release"] is True


def test_merge_duplicate_qc_samples_unifies_fragmented_rounds(client, admin_h, vanhanh_h):
    """merge_duplicate_qc_samples phải gộp các "lần lấy mẫu" bị TÁCH VỤN (bug frontend cũ — cho
    submit từng chỉ tiêu một, mỗi lần sinh 1 sample_id riêng dù CÙNG sampled_at/recorded_by —
    đã sửa frontend, nhưng dữ liệu cũ vẫn cần gộp lại, yêu cầu người dùng 2026-09-02: "lần 1
    cũng phải gom lại"). 2 dòng khác sample_id nhưng cùng (scope, sampled_at, recorded_by) và
    KHÁC mã chỉ tiêu -> gộp về 1 sample_id. Idempotent — gọi lại lần 2 không gộp thêm gì."""
    code_a = _make_group_with_param(client, admin_h, "MERGEA", stage="len_men_phu")
    code_b = _make_group_with_param(client, admin_h, "MERGEB", stage="len_men_phu")
    lm_code = _make_ferment(client, admin_h, vanhanh_h, "MERGE1")
    scope_id = f"{lm_code}__len_men_phu"
    sampled_at = "2026-07-15T08:21:00+00:00"

    r1 = client.post("/api/brewing/qc-samples", headers=vanhanh_h,
                     json={"stage": "len_men_phu", "scope_type": "ferment", "scope_id": scope_id,
                           "sampled_at": sampled_at,
                           "results": [{"parameter": code_a, "value": 5, "lower_limit": 1, "upper_limit": 10}]})
    assert r1.status_code == 201, r1.text
    r2 = client.post("/api/brewing/qc-samples", headers=vanhanh_h,
                     json={"stage": "len_men_phu", "scope_type": "ferment", "scope_id": scope_id,
                           "sampled_at": sampled_at,
                           "results": [{"parameter": code_b, "value": 6, "lower_limit": 1, "upper_limit": 10}]})
    assert r2.status_code == 201, r2.text

    before = client.get("/api/brewing/qc-samples", headers=admin_h,
                        params={"scope_type": "ferment", "scope_id": scope_id}).json()
    assert len(before["items"]) == 2   # tách vụn thành 2 "lần" riêng — đúng bug đã báo

    from app.database import SessionLocal
    from app.services.qc_catalog import merge_duplicate_qc_samples
    db = SessionLocal()
    result = merge_duplicate_qc_samples(db)
    db.close()
    assert result["merged_groups"] == 1
    assert result["merged_rows"] == 1

    after = client.get("/api/brewing/qc-samples", headers=admin_h,
                       params={"scope_type": "ferment", "scope_id": scope_id}).json()
    assert len(after["items"]) == 1
    merged_params = {r["parameter"] for r in after["items"][0]["results"]}
    assert merged_params == {code_a, code_b}

    db2 = SessionLocal()
    result2 = merge_duplicate_qc_samples(db2)
    db2.close()
    assert result2["merged_groups"] == 0   # idempotent


def test_merge_duplicate_qc_samples_skips_conflicting_duplicate_parameter(client, admin_h, vanhanh_h):
    """2 dòng khác sample_id, cùng (scope, sampled_at, recorded_by) NHƯNG cùng mã chỉ tiêu (VD
    sửa lại giá trị trùng giờ) — KHÔNG tự ý gộp (có thể là 2 lần đo thật khác nhau, không phải
    do bug tách vụn)."""
    code = _make_group_with_param(client, admin_h, "NOMERGE1", stage="len_men_phu")
    lm_code = _make_ferment(client, admin_h, vanhanh_h, "NOMERGE1")
    scope_id = f"{lm_code}__len_men_phu"
    sampled_at = "2026-07-16T09:00:00+00:00"

    for v in (5, 7):
        r = client.post("/api/brewing/qc-samples", headers=vanhanh_h,
                        json={"stage": "len_men_phu", "scope_type": "ferment", "scope_id": scope_id,
                              "sampled_at": sampled_at,
                              "results": [{"parameter": code, "value": v, "lower_limit": 1, "upper_limit": 10}]})
        assert r.status_code == 201, r.text

    from app.database import SessionLocal
    from app.services.qc_catalog import merge_duplicate_qc_samples
    db = SessionLocal()
    result = merge_duplicate_qc_samples(db)
    db.close()

    after = client.get("/api/brewing/qc-samples", headers=admin_h,
                       params={"scope_type": "ferment", "scope_id": scope_id}).json()
    assert len(after["items"]) == 2   # vẫn giữ nguyên 2 dòng riêng — không gộp nhầm


def test_merge_duplicate_qc_samples_clusters_by_time_proximity(client, admin_h, vanhanh_h):
    """Bug thực tế đã gặp: mỗi lần bấm lưu dở dang tự làm mới ô "Ngày giờ lấy mẫu" (không giữ
    nguyên) -> sampled_at giữa các dòng CHỈ lệch vài trăm mili-giây, không hề GIỐNG HỆT nhau —
    merge_duplicate_qc_samples phải gộp cụm submit dồn dập (cách nhau ≤ tolerance_seconds) chứ
    không chỉ đúng khi sampled_at trùng khớp tuyệt đối. 1 lần lấy mẫu THẬT sự khác (cách xa,
    ngoài tolerance) không được gộp lẫn vào."""
    code_a = _make_group_with_param(client, admin_h, "CLUSTERA", stage="len_men_chinh")
    code_b = _make_group_with_param(client, admin_h, "CLUSTERB", stage="len_men_chinh")
    lm_code = _make_ferment(client, admin_h, vanhanh_h, "CLUSTER1")
    scope_id = f"{lm_code}__len_men_chinh"

    # Cụm 1: 2 dòng cách nhau 0.3s (mô phỏng submit dồn dập) -> phải gộp thành 1 lần.
    r1 = client.post("/api/brewing/qc-samples", headers=vanhanh_h,
                     json={"stage": "len_men_chinh", "scope_type": "ferment", "scope_id": scope_id,
                           "sampled_at": "2026-08-01T09:00:00.100000+00:00",
                           "results": [{"parameter": code_a, "value": 5, "lower_limit": 1, "upper_limit": 10}]})
    assert r1.status_code == 201, r1.text
    r2 = client.post("/api/brewing/qc-samples", headers=vanhanh_h,
                     json={"stage": "len_men_chinh", "scope_type": "ferment", "scope_id": scope_id,
                           "sampled_at": "2026-08-01T09:00:00.400000+00:00",
                           "results": [{"parameter": code_b, "value": 6, "lower_limit": 1, "upper_limit": 10}]})
    assert r2.status_code == 201, r2.text

    # Lần lấy mẫu THẬT khác, 1 giờ sau, cùng 2 chỉ tiêu -> phải giữ RIÊNG, không gộp lẫn cụm 1.
    r3 = client.post("/api/brewing/qc-samples", headers=vanhanh_h,
                     json={"stage": "len_men_chinh", "scope_type": "ferment", "scope_id": scope_id,
                           "sampled_at": "2026-08-01T10:00:00+00:00",
                           "results": [{"parameter": code_a, "value": 5.5, "lower_limit": 1, "upper_limit": 10},
                                      {"parameter": code_b, "value": 6.5, "lower_limit": 1, "upper_limit": 10}]})
    assert r3.status_code == 201, r3.text

    before = client.get("/api/brewing/qc-samples", headers=admin_h,
                        params={"scope_type": "ferment", "scope_id": scope_id}).json()
    assert len(before["items"]) == 3

    from app.database import SessionLocal
    from app.services.qc_catalog import merge_duplicate_qc_samples
    db = SessionLocal()
    result = merge_duplicate_qc_samples(db)
    db.close()
    assert result["merged_groups"] == 1
    assert result["merged_rows"] == 1

    after = client.get("/api/brewing/qc-samples", headers=admin_h,
                       params={"scope_type": "ferment", "scope_id": scope_id}).json()
    assert len(after["items"]) == 2   # cụm dồn dập gộp thành 1 + lần thật riêng biệt = 2
    sizes = sorted(len(it["results"]) for it in after["items"])
    assert sizes == [2, 2]
