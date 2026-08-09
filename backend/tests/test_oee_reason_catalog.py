"""Danh mục lý do dừng máy (OeeReasonCatalog) — CRUD, guard xóa khi đang dùng, quyền
master.manage. Thay REASON_TREE hardcode cũ; seed sẵn 49 dòng cho CAN30K qua
seed._seed_oee_reason_catalog (xem test_oee_waterfall.py cho phần công thức)."""

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
def kysu_h(client):
    return _login(client, "kysu", "123456")   # có master.manage


@pytest.fixture(scope="module")
def vanhanh_h(client):
    return _login(client, "vanhanh", "123456")   # KHÔNG có master.manage


def test_seed_has_can30k_catalog(client, kysu_h):
    rows = client.get("/api/downtime/reason-catalog", params={"line_code": "CAN30K"}, headers=kysu_h).json()
    assert len(rows) == 49
    categories = {r["category"] for r in rows}
    assert categories == {"bao_tri_ngoai", "nona", "ke_hoach", "chuyen_may", "thieu_vat_tu",
                          "breakdown", "dung_lat_nhat", "sp_loi"}


def test_create_requires_master_manage(client, kysu_h, vanhanh_h):
    denied = client.post("/api/downtime/reason-catalog", headers=vanhanh_h,
                         json={"line_code": "CAN30K", "category": "ke_hoach",
                               "sub_code": "test_x", "sub_label": "Test X"})
    assert denied.status_code == 403, denied.text

    created = client.post("/api/downtime/reason-catalog", headers=kysu_h,
                          json={"line_code": "CAN30K", "category": "ke_hoach",
                                "sub_code": "test_x", "sub_label": "Test X", "target_pct": 0.01})
    assert created.status_code == 201, created.text


def test_update_and_delete_reason(client, kysu_h):
    created = client.post("/api/downtime/reason-catalog", headers=kysu_h,
                          json={"line_code": "CAN30K", "category": "sp_loi",
                                "sub_code": "test_y", "sub_label": "Test Y"})
    reason_id = created.json()["reason_id"]

    upd = client.put(f"/api/downtime/reason-catalog/{reason_id}", headers=kysu_h,
                     json={"target_pct": 0.02, "active": False})
    assert upd.status_code == 200, upd.text

    deleted = client.delete(f"/api/downtime/reason-catalog/{reason_id}", headers=kysu_h)
    assert deleted.status_code == 204, deleted.text


def test_delete_blocked_when_used(client, kysu_h, vanhanh_h):
    created = client.post("/api/downtime/reason-catalog", headers=kysu_h,
                          json={"line_code": "CAN30K", "category": "thieu_vat_tu",
                                "sub_code": "test_z", "sub_label": "Test Z"})
    reason_id = created.json()["reason_id"]

    ev = client.post("/api/downtime", headers=vanhanh_h,
                     json={"line": "CAN30K", "reason_catalog_id": reason_id, "minutes": 10})
    assert ev.status_code == 201, ev.text

    blocked = client.delete(f"/api/downtime/reason-catalog/{reason_id}", headers=kysu_h)
    assert blocked.status_code == 409, blocked.text
