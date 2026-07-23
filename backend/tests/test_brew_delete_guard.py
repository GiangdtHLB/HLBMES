"""Test chặn xóa mã nấu (BrewRecord) / mẻ (BrewBatch) khi lô lên men liên kết đã được lọc —
tránh mất dấu vết truy xuất nguồn gốc (bug thực tế: xóa được mã nấu dù đã lọc xong)."""

import itertools
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


_batch_code_seq = itertools.count(650)


def _a_brew(client, admin_h, vanhanh_h, suffix, with_batch=True):
    order = client.post("/api/brewing/orders", headers=admin_h,
                        json={"order_code": f"LN-{suffix}", "auto_from_bom": False, "planned_volume_hl": 100})
    assert order.status_code == 201, order.text
    order_id = order.json()["brew_order_id"]
    b = client.post("/api/brewing/brews", headers=vanhanh_h,
                    json={"brew_code": f"BR-{suffix}", "wort_type": "Dịch test", "volume_hl": 100,
                          "lm_code": f"LM-{suffix}", "tank_lm": f"T-{suffix}", "brew_order_id": order_id})
    assert b.status_code == 201, b.text
    brew_id = b.json()["brew_id"]
    batch_id = None
    if with_batch:
        batch = client.post(f"/api/brewing/brews/{brew_id}/batches", headers=vanhanh_h,
                            json={"batch_code": str(next(_batch_code_seq))})
        assert batch.status_code == 201, batch.text
        batch_id = batch.json()["batch_id"]
    return brew_id, batch_id


def test_delete_brew_allowed_before_filtered(client, admin_h, vanhanh_h):
    brew_id, batch_id = _a_brew(client, admin_h, vanhanh_h, "DELOK01")
    deleted = client.delete(f"/api/brewing/brews/{brew_id}", headers=vanhanh_h)
    assert deleted.status_code == 204, deleted.text


def test_delete_brew_also_deletes_orphaned_ferment(client, admin_h, vanhanh_h):
    """Xóa mã nấu phải xóa LUÔN lô lên men liên kết (nếu không còn mã nấu nào khác dùng
    chung tank/lô LM đó) — nếu không, lô lên men bị bỏ mồ côi, chiếm mã lô LM vĩnh viễn
    (không tạo lại được mã nấu mới dùng cùng mã lô LM) và vận hành phải tự tay xóa riêng."""
    suffix = "DELFERM01"
    brew_id, batch_id = _a_brew(client, admin_h, vanhanh_h, suffix)
    ferments_before = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    assert any(f["lm_code"] == f"LM-{suffix}" for f in ferments_before)

    deleted = client.delete(f"/api/brewing/brews/{brew_id}", headers=vanhanh_h)
    assert deleted.status_code == 204, deleted.text

    ferments_after = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    assert not any(f["lm_code"] == f"LM-{suffix}" for f in ferments_after), \
        "Lô lên men phải bị xóa theo, không được bỏ mồ côi lại"

    # Mã lô LM được giải phóng — tạo mã nấu MỚI dùng lại đúng lm_code đó phải thành công.
    order = client.post("/api/brewing/orders", headers=admin_h,
                       json={"order_code": f"LN-{suffix}-2", "auto_from_bom": False, "planned_volume_hl": 100})
    assert order.status_code == 201, order.text
    again = client.post("/api/brewing/brews", headers=vanhanh_h,
                       json={"brew_code": f"BR-{suffix}-2", "wort_type": "Dịch test", "volume_hl": 100,
                             "lm_code": f"LM-{suffix}", "tank_lm": f"T-{suffix}",
                             "brew_order_id": order.json()["brew_order_id"]})
    assert again.status_code == 201, again.text


def test_delete_brew_keeps_ferment_shared_by_another_brew(client, admin_h, vanhanh_h):
    """1 lô lên men có thể gộp nhiều mã nấu vào cùng tank (POST /ferments với brew_ids) —
    xóa 1 mã nấu không được xóa lô lên men nếu mã nấu KHÁC vẫn còn liên kết tới nó."""
    suffix = "DELFERMSHARE01"
    order = client.post("/api/brewing/orders", headers=admin_h,
                       json={"order_code": f"LN-{suffix}", "auto_from_bom": False, "planned_volume_hl": 200})
    assert order.status_code == 201, order.text
    order_id = order.json()["brew_order_id"]

    b1 = client.post("/api/brewing/brews", headers=vanhanh_h,
                     json={"brew_code": f"BR-{suffix}-1", "wort_type": "Dịch test", "volume_hl": 100,
                           "brew_order_id": order_id})
    assert b1.status_code == 201, b1.text
    b2 = client.post("/api/brewing/brews", headers=vanhanh_h,
                     json={"brew_code": f"BR-{suffix}-2", "wort_type": "Dịch test", "volume_hl": 100,
                           "brew_order_id": order_id})
    assert b2.status_code == 201, b2.text

    ferment = client.post("/api/brewing/ferments", headers=vanhanh_h, json={
        "lm_code": f"LM-{suffix}", "wort_type": "Dịch test", "tank_lm": f"T-{suffix}",
        "volume_hl": 200, "brew_ids": [b1.json()["brew_id"], b2.json()["brew_id"]],
    })
    assert ferment.status_code == 201, ferment.text

    deleted = client.delete(f"/api/brewing/brews/{b1.json()['brew_id']}", headers=vanhanh_h)
    assert deleted.status_code == 204, deleted.text

    ferments_after = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    assert any(f["lm_code"] == f"LM-{suffix}" for f in ferments_after), \
        "Lô lên men vẫn còn mã nấu B liên kết -> không được xóa"


def test_delete_brew_batch_allowed_before_filtered(client, admin_h, vanhanh_h):
    brew_id, batch_id = _a_brew(client, admin_h, vanhanh_h, "DELOK02")
    deleted = client.delete(f"/api/brewing/brews/{brew_id}/batches/{batch_id}", headers=vanhanh_h)
    assert deleted.status_code == 204, deleted.text


def _approve_ferment(client, admin_h, lm_code):
    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment = next(f for f in ferments if f["lm_code"] == lm_code)
    q = f"/api/brewing/qc-status?stage=len_men_phu&scope_type=ferment&scope_id={lm_code}__len_men_phu"
    status = client.get(q, headers=admin_h).json()
    for p in status["required"]:
        if p["code"] in status["pending"]:
            lsl = p["lsl"] if p["lsl"] is not None else 0
            usl = p["usl"] if p["usl"] is not None else lsl + 10
            r = client.post("/api/brewing/qc-results", headers=admin_h,
                            json={"stage": "len_men_phu", "scope_type": "ferment",
                                  "scope_id": f"{lm_code}__len_men_phu", "parameter": p["code"],
                                  "value": (lsl + usl) / 2, "lower_limit": lsl, "upper_limit": usl})
            assert r.status_code == 201, r.text
    approved = client.post(f"/api/brewing/ferments/{ferment['ferment_id']}/approve", headers=admin_h)
    assert approved.status_code == 200, approved.text
    return ferment["ferment_id"]


def _a_filter_order(client, admin_h, order_code, ferment_ids, blend_mode="khong_phoi"):
    r = client.post("/api/brewing/filter-orders", headers=admin_h,
                    json={"order_code": order_code, "blend_mode": blend_mode, "tank_ferment_ids": ferment_ids,
                          "planned_volume_hl": 1000})
    assert r.status_code == 201, r.text
    return r.json()["filter_order_id"]


def test_delete_brew_blocked_after_filtered(client, admin_h, vanhanh_h):
    suffix = "DELBLOCK01"
    brew_id, batch_id = _a_brew(client, admin_h, vanhanh_h, suffix)
    ferment_id = _approve_ferment(client, admin_h, f"LM-{suffix}")
    order_id = _a_filter_order(client, admin_h, f"LOC-{suffix}", [ferment_id])
    f = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": f"FL-{suffix}", "beer_type": "Bia test", "wort_type": "Dịch test",
                          "filter_order_id": order_id, "to_bbt": f"BBT-{suffix}"})
    assert f.status_code == 201, f.text

    blocked_brew = client.delete(f"/api/brewing/brews/{brew_id}", headers=vanhanh_h)
    assert blocked_brew.status_code == 409, blocked_brew.text

    blocked_batch = client.delete(f"/api/brewing/brews/{brew_id}/batches/{batch_id}", headers=vanhanh_h)
    assert blocked_batch.status_code == 409, blocked_batch.text
