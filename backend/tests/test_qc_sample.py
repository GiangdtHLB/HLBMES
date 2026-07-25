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
