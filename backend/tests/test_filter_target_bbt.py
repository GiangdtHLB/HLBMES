"""Test chặn 2 Lệnh lọc nhỏ khác nhau vô tình cùng đổ vào 1 tank BBT vật lý — kiểm tra tại
module Lọc (lúc tạo MẺ LỌC ĐẦU TIÊN của 1 lệnh, không phải lúc lập Lệnh lọc nhỏ). Mẻ lọc sau
của CÙNG 1 lệnh tự động dùng lại đúng tank đã dùng ở mẻ đầu (không cho đổi giữa chừng). Xem
services/filter_order.py::_bbt_target_blocked_by, routers/brewing.py::add_filter."""

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


def _a_filter_order(client, admin_h, vanhanh_h, suffix, planned_v_dich_hl=100.0):
    """Tạo 1 Lệnh lọc lớn với đúng 1 Lệnh lọc nhỏ (không phối, 1 tank CCT) — trả về filter_order_id."""
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


def test_first_filter_blocked_when_other_order_unfinished_owns_tank(client, admin_h, vanhanh_h):
    order1 = _a_filter_order(client, admin_h, vanhanh_h, "TGT-A1", planned_v_dich_hl=100)
    bbt_code = "BBT-TGT-SHARED-1"
    f1 = client.post("/api/brewing/filters", headers=vanhanh_h,
                     json={"filter_code": "FL-TGT-A1", "filter_order_id": order1, "to_bbt": bbt_code})
    assert f1.status_code == 201, f1.text
    # order1 chưa "Kết thúc" tank — chưa lọc xong (is_complete=False) — tank vẫn coi là bị giữ.

    order2 = _a_filter_order(client, admin_h, vanhanh_h, "TGT-B1", planned_v_dich_hl=100)
    blocked = client.post("/api/brewing/filters", headers=vanhanh_h,
                         json={"filter_code": "FL-TGT-B1", "filter_order_id": order2, "to_bbt": bbt_code})
    assert blocked.status_code == 409, blocked.text
    assert "chưa lọc xong" in blocked.json()["detail"]


def test_second_batch_of_same_order_auto_inherits_tank(client, admin_h, vanhanh_h):
    order1 = _a_filter_order(client, admin_h, vanhanh_h, "TGT-A2", planned_v_dich_hl=100)
    bbt_code = "BBT-TGT-SHARED-2"
    f1 = client.post("/api/brewing/filters", headers=vanhanh_h,
                     json={"filter_code": "FL-TGT-A2-1", "filter_order_id": order1, "to_bbt": bbt_code})
    assert f1.status_code == 201, f1.text
    tanks = client.get(f"/api/brewing/filters/{f1.json()['filter_id']}/tanks", headers=admin_h).json()
    fin = client.post(f"/api/brewing/filters/{f1.json()['filter_id']}/tanks/{tanks[0]['line_id']}/finish",
                      headers=vanhanh_h, json={"v_dich_hl": 40, "nuoc_bai_khi_hl": 0})
    assert fin.status_code == 200, fin.text  # 40/100 — chưa hoàn thành, vẫn cho lọc mẻ 2

    # Mẻ lọc thứ 2 của CÙNG lệnh, cố gửi to_bbt KHÁC — server phải bỏ qua, dùng lại tank cũ.
    f2 = client.post("/api/brewing/filters", headers=vanhanh_h,
                     json={"filter_code": "FL-TGT-A2-2", "filter_order_id": order1, "to_bbt": "BBT-TGT-WRONG"})
    assert f2.status_code == 201, f2.text
    assert f2.json()["to_bbt"] == bbt_code


def test_blocked_when_order_complete_but_not_chiet_het(client, admin_h, vanhanh_h):
    """Regression đúng bug gốc (FL-97699/FL-25455 thật đã xảy ra): lệnh đã lọc XONG
    (is_complete=True) nhưng chưa chiết hết (on_hand_bbt>0) vẫn phải chặn lệnh khác."""
    order1 = _a_filter_order(client, admin_h, vanhanh_h, "TGT-A3", planned_v_dich_hl=50)
    bbt_code = "BBT-TGT-SHARED-3"
    f1 = client.post("/api/brewing/filters", headers=vanhanh_h,
                     json={"filter_code": "FL-TGT-A3", "filter_order_id": order1, "to_bbt": bbt_code})
    assert f1.status_code == 201, f1.text
    tanks = client.get(f"/api/brewing/filters/{f1.json()['filter_id']}/tanks", headers=admin_h).json()
    fin = client.post(f"/api/brewing/filters/{f1.json()['filter_id']}/tanks/{tanks[0]['line_id']}/finish",
                      headers=vanhanh_h, json={"v_dich_hl": 50, "nuoc_bai_khi_hl": 0})
    assert fin.status_code == 200, fin.text  # 50/50 -> is_complete=True, nhưng chưa chiết gì.

    order2 = _a_filter_order(client, admin_h, vanhanh_h, "TGT-B3", planned_v_dich_hl=50)
    blocked = client.post("/api/brewing/filters", headers=vanhanh_h,
                         json={"filter_code": "FL-TGT-B3", "filter_order_id": order2, "to_bbt": bbt_code})
    assert blocked.status_code == 409, blocked.text
    assert "chưa chiết hết" in blocked.json()["detail"]


def test_tank_free_again_after_fully_chiet_het(client, admin_h, vanhanh_h):
    order1 = _a_filter_order(client, admin_h, vanhanh_h, "TGT-A4", planned_v_dich_hl=50)
    bbt_code = "BBT-TGT-SHARED-4"
    f1 = client.post("/api/brewing/filters", headers=vanhanh_h,
                     json={"filter_code": "FL-TGT-A4", "filter_order_id": order1, "to_bbt": bbt_code})
    assert f1.status_code == 201, f1.text
    filter_id = f1.json()["filter_id"]
    tanks = client.get(f"/api/brewing/filters/{filter_id}/tanks", headers=admin_h).json()
    fin = client.post(f"/api/brewing/filters/{filter_id}/tanks/{tanks[0]['line_id']}/finish",
                      headers=vanhanh_h, json={"v_dich_hl": 50, "nuoc_bai_khi_hl": 0})
    assert fin.status_code == 200, fin.text
    _declare_pending(client, vanhanh_h, "loc", "filter", "FL-TGT-A4")
    approve = client.post(f"/api/brewing/filters/{filter_id}/approve", headers=admin_h)
    assert approve.status_code == 200, approve.text

    # Trước khi chiết hết — vẫn còn bị chặn (mirror test trên).
    order2 = _a_filter_order(client, admin_h, vanhanh_h, "TGT-B4", planned_v_dich_hl=50)
    still_blocked = client.post("/api/brewing/filters", headers=vanhanh_h,
                               json={"filter_code": "FL-TGT-B4-early", "filter_order_id": order2, "to_bbt": bbt_code})
    assert still_blocked.status_code == 409, still_blocked.text

    bottle = client.post("/api/brewing/bottles", headers=vanhanh_h,
                         json={"bottle_code": "CH-TGT-A4", "from_bbt": bbt_code})
    assert bottle.status_code == 201, bottle.text
    fin_bottle = client.post(f"/api/brewing/bottles/{bottle.json()['bottle_id']}/finish", headers=vanhanh_h,
                             json={"v_cap_chiet_hl": 50, "ca1": 50})
    assert fin_bottle.status_code == 200, fin_bottle.text

    source_after = next(r for r in client.get("/api/brewing/filters", headers=admin_h).json()
                       if r["filter_id"] == filter_id)
    assert source_after["on_hand_bbt"] == 0

    now_ok = client.post("/api/brewing/filters", headers=vanhanh_h,
                        json={"filter_code": "FL-TGT-B4", "filter_order_id": order2, "to_bbt": bbt_code})
    assert now_ok.status_code == 201, now_ok.text
