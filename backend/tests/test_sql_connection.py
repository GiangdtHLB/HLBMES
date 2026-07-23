"""Test khai báo + test kết nối CSDL SQL bên ngoài (Tích hợp > Kết nối CSDL).

Chỉ admin (require_role ADMIN, giống API Key/Webhook) mới CRUD được. Mật khẩu không
bao giờ trả về thô qua API — chỉ cờ password_set. test_connection() với host không
tồn tại phải trả ok=False kèm thông báo lỗi (không raise exception ra ngoài)."""

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


def test_create_list_never_returns_raw_password(client, admin_h):
    resp = client.post("/api/integration/connections", headers=admin_h, json={
        "name": "Kho ERP", "host": "10.0.0.5", "port": 1433, "database_name": "ERP_PROD",
        "username": "sa", "password": "SuperSecret123",
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Kho ERP"
    assert body["password_set"] is True
    assert "password" not in body
    connection_id = body["connection_id"]

    get_resp = client.get("/api/integration/connections", headers=admin_h)
    assert get_resp.status_code == 200, get_resp.text
    rows = get_resp.json()
    found = next(r for r in rows if r["connection_id"] == connection_id)
    assert found["password_set"] is True
    assert "password" not in found


def test_update_blank_password_keeps_old_one(client, admin_h):
    create = client.post("/api/integration/connections", headers=admin_h, json={
        "name": "Kho WMS", "host": "10.0.0.6", "port": 1433, "database_name": "WMS",
        "username": "sa", "password": "InitialPass",
    })
    connection_id = create.json()["connection_id"]

    update = client.put(f"/api/integration/connections/{connection_id}", headers=admin_h, json={
        "name": "Kho WMS (đổi tên)", "host": "10.0.0.6", "port": 1433, "database_name": "WMS",
        "username": "sa", "password": None,
    })
    assert update.status_code == 200, update.text
    body = update.json()
    assert body["name"] == "Kho WMS (đổi tên)"
    assert body["password_set"] is True  # vẫn còn mật khẩu cũ, không bị xoá


def test_non_admin_forbidden(client):
    vanhanh_h = _login(client, "vanhanh", "123456")
    resp = client.get("/api/integration/connections", headers=vanhanh_h)
    assert resp.status_code == 403, resp.text
    resp2 = client.post("/api/integration/connections", headers=vanhanh_h,
                        json={"name": "x", "host": "h", "database_name": "d", "username": "u"})
    assert resp2.status_code == 403, resp2.text


def test_test_connection_unreachable_host_returns_ok_false(client, admin_h):
    create = client.post("/api/integration/connections", headers=admin_h, json={
        "name": "Không tồn tại", "host": "this-host-does-not-exist.invalid", "port": 1433,
        "database_name": "X", "username": "sa", "password": "x",
    })
    connection_id = create.json()["connection_id"]

    test_resp = client.post(f"/api/integration/connections/{connection_id}/test", headers=admin_h)
    assert test_resp.status_code == 200, test_resp.text
    body = test_resp.json()
    assert body["ok"] is False
    assert body["message"]

    get_resp = client.get("/api/integration/connections", headers=admin_h)
    row = next(r for r in get_resp.json() if r["connection_id"] == connection_id)
    assert row["last_test_ok"] is False
    assert row["last_tested_at"] is not None


def test_delete_connection(client, admin_h):
    create = client.post("/api/integration/connections", headers=admin_h, json={
        "name": "Sẽ xoá", "host": "h", "port": 1433, "database_name": "d", "username": "u", "password": "p",
    })
    connection_id = create.json()["connection_id"]

    del_resp = client.delete(f"/api/integration/connections/{connection_id}", headers=admin_h)
    assert del_resp.status_code == 204, del_resp.text

    get_resp = client.get("/api/integration/connections", headers=admin_h)
    assert connection_id not in [r["connection_id"] for r in get_resp.json()]
