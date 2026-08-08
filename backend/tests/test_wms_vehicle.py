"""Test danh mục xe/lái xe (wms_vehicle) — CRUD cơ bản + chặn trùng biển số."""

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
def thukho_h(client):
    return _login(client, "thukho", "123456")


@pytest.fixture(scope="module")
def kcs_h(client):
    return _login(client, "kcs", "123456")


def test_vehicle_crud(client, admin_h):
    created = client.post("/api/wms/vehicles", headers=admin_h,
                          json={"plate": "14H99999", "driver_name": "Nguyễn Văn A", "driver_short_name": "A",
                                "capacity_kg": 6400, "pallet_capacity": 7, "phone": "0900000001", "team": "TỔ 1"})
    assert created.status_code == 201, created.text
    vehicle_id = created.json()["vehicle_id"]

    rows = client.get("/api/wms/vehicles", headers=admin_h).json()
    row = next(r for r in rows if r["vehicle_id"] == vehicle_id)
    assert row["plate"] == "14H99999" and row["driver_short_name"] == "A" and row["active"] is True

    updated = client.put(f"/api/wms/vehicles/{vehicle_id}", headers=admin_h, json={"phone": "0911111111"})
    assert updated.status_code == 200, updated.text
    rows2 = client.get("/api/wms/vehicles", headers=admin_h).json()
    assert next(r for r in rows2 if r["vehicle_id"] == vehicle_id)["phone"] == "0911111111"

    deleted = client.delete(f"/api/wms/vehicles/{vehicle_id}", headers=admin_h)
    assert deleted.status_code == 204, deleted.text
    rows3 = client.get("/api/wms/vehicles", headers=admin_h).json()
    assert not any(r["vehicle_id"] == vehicle_id for r in rows3)


def test_vehicle_plate_must_be_unique(client, admin_h):
    ok = client.post("/api/wms/vehicles", headers=admin_h, json={"plate": "14H88888"})
    assert ok.status_code == 201, ok.text

    dup = client.post("/api/wms/vehicles", headers=admin_h, json={"plate": "14H88888"})
    assert dup.status_code == 409, dup.text


def test_vehicle_create_requires_admin(client, thukho_h, kcs_h):
    # Danh mục lái xe đã chuyển vào Danh mục (Master) và khóa CHỈ ADMIN được tạo/sửa/xóa (xem
    # routers/wms.py: require_role(user, Role.ADMIN)) — thủ kho (vốn có warehouse.receive)
    # không còn được tạo, giống hệt kcs.
    denied_thukho = client.post("/api/wms/vehicles", headers=thukho_h, json={"plate": "14H77777"})
    assert denied_thukho.status_code == 403, denied_thukho.text

    denied_kcs = client.post("/api/wms/vehicles", headers=kcs_h, json={"plate": "14H66666"})
    assert denied_kcs.status_code == 403, denied_kcs.text


def test_vehicle_list_is_public_to_any_authenticated_user(client, kcs_h):
    rows = client.get("/api/wms/vehicles", headers=kcs_h)
    assert rows.status_code == 200, rows.text
