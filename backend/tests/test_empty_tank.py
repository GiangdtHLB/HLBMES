"""Test "Làm rỗng" tank CCT (lên men) / BBT (thành phẩm chờ chiết) — buộc tồn về 0 khi tank
vật lý đã cạn thật nhưng số liệu phần mềm còn lệch một khoảng nhỏ, gated bởi ngưỡng dung sai
cấu hình ở Danh mục (services/ops_setting.py). Mirror test_filter_order.py cho phần tạo
ferment/filter."""

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
                    json={"order_code": order_code, "auto_from_bom": False, "planned_volume_hl": 100})
    assert r.status_code == 201, r.text
    return r.json()["brew_order_id"]


def _setup_ferment(client, admin_h, vanhanh_h, suffix):
    order_id = _a_brew_order(client, admin_h, f"LN-{suffix}")
    b = client.post("/api/brewing/brews", headers=vanhanh_h,
                    json={"brew_code": f"BR-{suffix}", "wort_type": "Dịch test", "volume_hl": 100,
                          "lm_code": f"LM-{suffix}", "tank_lm": f"T-{suffix}", "brew_order_id": order_id})
    assert b.status_code == 201, b.text
    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment = next(f for f in ferments if f["lm_code"] == f"LM-{suffix}")
    ok = client.post(f"/api/brewing/ferments/{ferment['ferment_id']}/approve", headers=admin_h)
    assert ok.status_code == 200, ok.text
    return ferment["ferment_id"]


def _a_filter_order(client, admin_h, order_code, ferment_ids):
    r = client.post("/api/brewing/filter-orders", headers=admin_h,
                    json={"order_code": order_code, "blend_mode": "khong_phoi", "tank_ferment_ids": ferment_ids,
                          "planned_volume_hl": 1000})
    assert r.status_code == 201, r.text
    return r.json()["filter_order_id"]


def _declare_pending(client, headers, stage, scope_type, scope_id):
    status = client.get(f"/api/brewing/qc-status?stage={stage}&scope_type={scope_type}&scope_id={scope_id}",
                        headers=headers).json()
    for p in status["required"]:
        if p["code"] in status["pending"]:
            lsl = p["lsl"] if p["lsl"] is not None else 0
            usl = p["usl"] if p["usl"] is not None else lsl + 10
            r = client.post("/api/brewing/qc-results", headers=headers,
                            json={"stage": stage, "scope_type": scope_type, "scope_id": scope_id,
                                  "parameter": p["code"], "value": (lsl + usl) / 2,
                                  "lower_limit": lsl, "upper_limit": usl})
            assert r.status_code == 201, r.text


def _ferment_on_hand_cct(client, admin_h, ferment_id):
    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    return next(f for f in ferments if f["ferment_id"] == ferment_id)["on_hand_cct"]


def _a_filter_with_bbt(client, admin_h, vanhanh_h, suffix, v_dich_hl, nuoc_bai_khi_hl):
    """Tạo 1 lô lọc (không phối), kết thúc tank duy nhất — trả về (filter_id, ferment_id)."""
    ferment_id = _setup_ferment(client, admin_h, vanhanh_h, suffix)
    order_id = _a_filter_order(client, admin_h, f"LOC-{suffix}", [ferment_id])
    f = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": f"FL-{suffix}", "beer_type": "Bia test",
                          "filter_order_id": order_id, "to_bbt": f"BBT-{suffix}"})
    assert f.status_code == 201, f.text
    filter_id = f.json()["filter_id"]
    tanks = client.get(f"/api/brewing/filters/{filter_id}/tanks", headers=admin_h).json()
    fin = client.post(f"/api/brewing/filters/{filter_id}/tanks/{tanks[0]['line_id']}/finish", headers=vanhanh_h,
                      json={"v_dich_hl": v_dich_hl, "nuoc_bai_khi_hl": nuoc_bai_khi_hl})
    assert fin.status_code == 200, fin.text
    _declare_pending(client, vanhanh_h, "loc", "filter", f"FL-{suffix}")
    approve = client.post(f"/api/brewing/filters/{filter_id}/approve", headers=admin_h)
    assert approve.status_code == 200, approve.text
    return filter_id, ferment_id


def test_ops_settings_default_and_update(client, admin_h, vanhanh_h):
    r = client.get("/api/ops-settings", headers=admin_h)
    assert r.status_code == 200, r.text
    assert r.json()["empty_cct_tolerance_hl"] == 2.0
    assert r.json()["empty_bbt_tolerance_hl"] == 2.0

    denied = client.put("/api/ops-settings", headers=vanhanh_h,
                        json={"empty_cct_tolerance_hl": 5, "empty_bbt_tolerance_hl": 5})
    assert denied.status_code == 403, denied.text

    ok = client.put("/api/ops-settings", headers=admin_h,
                    json={"empty_cct_tolerance_hl": 5, "empty_bbt_tolerance_hl": 3})
    assert ok.status_code == 200, ok.text
    assert ok.json()["empty_cct_tolerance_hl"] == 5
    assert ok.json()["empty_bbt_tolerance_hl"] == 3
    assert ok.json()["updated_by"] == "admin"

    check = client.get("/api/ops-settings", headers=admin_h)
    assert check.json()["empty_cct_tolerance_hl"] == 5

    # Reset về mặc định cho các test sau trong cùng file (module-scope client dùng chung).
    client.put("/api/ops-settings", headers=admin_h,
              json={"empty_cct_tolerance_hl": 2.0, "empty_bbt_tolerance_hl": 2.0})


def test_empty_ferment_cct_blocked_if_residual_exceeds_tolerance(client, admin_h, vanhanh_h):
    ferment_id = _setup_ferment(client, admin_h, vanhanh_h, "EMPTYCCT-BLOCK")
    residual = _ferment_on_hand_cct(client, admin_h, ferment_id)
    assert residual == 100  # chưa lọc gì -> còn nguyên volume_hl, vượt xa ngưỡng mặc định 2 hl

    blocked = client.post(f"/api/brewing/ferments/{ferment_id}/empty-cct", headers=vanhanh_h)
    assert blocked.status_code == 409, blocked.text

    assert _ferment_on_hand_cct(client, admin_h, ferment_id) == residual


def test_empty_ferment_cct_succeeds_within_tolerance(client, admin_h, vanhanh_h):
    ferment_id = _setup_ferment(client, admin_h, vanhanh_h, "EMPTYCCT-OK")
    order_id = _a_filter_order(client, admin_h, "LOC-EMPTYCCT-OK", [ferment_id])
    f = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": "FL-EMPTYCCT-OK", "beer_type": "Bia test",
                          "filter_order_id": order_id, "to_bbt": "BBT-EMPTYCCT-OK"})
    assert f.status_code == 201, f.text
    filter_id = f.json()["filter_id"]
    tanks = client.get(f"/api/brewing/filters/{filter_id}/tanks", headers=admin_h).json()
    # Lọc 99 hl (còn dư 1 hl trong CCT, trong ngưỡng mặc định 2 hl) -> cạn thật do hao hụt.
    fin = client.post(f"/api/brewing/filters/{filter_id}/tanks/{tanks[0]['line_id']}/finish", headers=vanhanh_h,
                      json={"v_dich_hl": 99, "nuoc_bai_khi_hl": 0})
    assert fin.status_code == 200, fin.text
    assert _ferment_on_hand_cct(client, admin_h, ferment_id) == 1

    ok = client.post(f"/api/brewing/ferments/{ferment_id}/empty-cct", headers=vanhanh_h)
    assert ok.status_code == 200, ok.text
    assert ok.json()["on_hand_cct"] == 0
    assert _ferment_on_hand_cct(client, admin_h, ferment_id) == 0

    already_empty = client.post(f"/api/brewing/ferments/{ferment_id}/empty-cct", headers=vanhanh_h)
    assert already_empty.status_code == 409, already_empty.text


def test_empty_filter_bbt_blocked_if_residual_exceeds_tolerance(client, admin_h, vanhanh_h):
    filter_id, _ = _a_filter_with_bbt(client, admin_h, vanhanh_h, "EMPTYBBT-BLOCK", 90, 10)
    rows = client.get("/api/brewing/filters", headers=admin_h).json()
    row = next(r for r in rows if r["filter_id"] == filter_id)
    assert row["on_hand_bbt"] == 100  # chưa chiết gì -> vượt xa ngưỡng mặc định 2 hl

    blocked = client.post(f"/api/brewing/filters/{filter_id}/empty-bbt", headers=vanhanh_h)
    assert blocked.status_code == 409, blocked.text


def test_empty_filter_bbt_succeeds_within_tolerance(client, admin_h, vanhanh_h):
    filter_id, _ = _a_filter_with_bbt(client, admin_h, vanhanh_h, "EMPTYBBT-OK", 90, 10)
    bottle_code = "CH-EMPTYBBT-OK"
    b = client.post("/api/brewing/bottles", headers=vanhanh_h,
                    json={"bottle_code": bottle_code, "beer_type": "Bia test", "from_bbt": "BBT-EMPTYBBT-OK"})
    assert b.status_code == 201, b.text
    # Chiết 99/100 hl (còn dư 1 hl trong BBT, trong ngưỡng mặc định 2 hl) -> cạn thật do hao hụt.
    fin = client.post(f"/api/brewing/bottles/{b.json()['bottle_id']}/finish", headers=vanhanh_h,
                      json={"v_cap_chiet_hl": 99})
    assert fin.status_code == 200, fin.text

    rows = client.get("/api/brewing/filters", headers=admin_h).json()
    row = next(r for r in rows if r["filter_id"] == filter_id)
    assert row["on_hand_bbt"] == 1

    ok = client.post(f"/api/brewing/filters/{filter_id}/empty-bbt", headers=vanhanh_h)
    assert ok.status_code == 200, ok.text
    assert ok.json()["on_hand_bbt"] == 0

    already_empty = client.post(f"/api/brewing/filters/{filter_id}/empty-bbt", headers=vanhanh_h)
    assert already_empty.status_code == 409, already_empty.text
