"""Kho thành phẩm (WmsWarehouse) — cấp cha mới của WmsLocation, để biết 1 lô đang ở KHO nào,
VỊ TRÍ nào trong kho đó (trước đây chỉ có "vị trí" phẳng, không có khái niệm kho)."""

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


def test_create_warehouse_and_duplicate_code_rejected(client, admin_h):
    created = client.post("/api/wms/warehouses", headers=admin_h,
                          json={"code": "WH-TEST1", "name": "Kho test 1", "address": "Đông Mai"})
    assert created.status_code == 201, created.text
    warehouse_id = created.json()["warehouse_id"]

    dup = client.post("/api/wms/warehouses", headers=admin_h,
                      json={"code": "WH-TEST1", "name": "Kho trùng mã"})
    assert dup.status_code == 409, dup.text

    listed = client.get("/api/wms/warehouses", headers=admin_h).json()
    row = next(w for w in listed if w["warehouse_id"] == warehouse_id)
    assert row["code"] == "WH-TEST1" and row["name"] == "Kho test 1" and row["location_count"] == 0


def test_location_belongs_to_warehouse_and_surfaces_in_list(client, admin_h):
    wh = client.post("/api/wms/warehouses", headers=admin_h,
                     json={"code": "WH-TEST2", "name": "Kho test 2"}).json()
    loc = client.post("/api/wms/locations", headers=admin_h,
                      json={"code": "LOC-WHTEST2-A1", "name": "Khu A1", "capacity": 20,
                            "warehouse_id": wh["warehouse_id"]})
    assert loc.status_code == 201, loc.text

    locations = client.get("/api/wms/locations", headers=admin_h).json()
    row = next(l for l in locations if l["code"] == "LOC-WHTEST2-A1")
    assert row["warehouse_id"] == wh["warehouse_id"]
    assert row["warehouse_code"] == "WH-TEST2" and row["warehouse_name"] == "Kho test 2"

    warehouses = client.get("/api/wms/warehouses", headers=admin_h).json()
    wh_row = next(w for w in warehouses if w["warehouse_id"] == wh["warehouse_id"])
    assert wh_row["location_count"] == 1


def test_location_created_without_warehouse_id_still_works(client, admin_h):
    """Không bắt buộc ở tầng API/schema (giữ tương thích test/import cũ chưa gửi trường này) —
    chỉ UI Danh mục vị trí kho bắt chọn khi khai báo vị trí mới."""
    loc = client.post("/api/wms/locations", headers=admin_h,
                      json={"code": "LOC-NOWH-1", "name": "Không có kho cha", "capacity": 5})
    assert loc.status_code == 201, loc.text
    locations = client.get("/api/wms/locations", headers=admin_h).json()
    row = next(l for l in locations if l["code"] == "LOC-NOWH-1")
    assert row["warehouse_id"] is None
    assert row["warehouse_code"] is None


def test_delete_warehouse_blocked_when_locations_reference_it(client, admin_h):
    wh = client.post("/api/wms/warehouses", headers=admin_h,
                     json={"code": "WH-TEST3", "name": "Kho test 3"}).json()
    client.post("/api/wms/locations", headers=admin_h,
               json={"code": "LOC-WHTEST3-A1", "name": "Khu A1", "warehouse_id": wh["warehouse_id"]})

    blocked = client.delete(f"/api/wms/warehouses/{wh['warehouse_id']}", headers=admin_h)
    assert blocked.status_code == 409, blocked.text

    empty_wh = client.post("/api/wms/warehouses", headers=admin_h,
                           json={"code": "WH-TEST4", "name": "Kho rỗng"}).json()
    ok = client.delete(f"/api/wms/warehouses/{empty_wh['warehouse_id']}", headers=admin_h)
    assert ok.status_code == 204, ok.text


def test_update_warehouse(client, admin_h):
    wh = client.post("/api/wms/warehouses", headers=admin_h,
                     json={"code": "WH-TEST5", "name": "Kho test 5"}).json()
    updated = client.put(f"/api/wms/warehouses/{wh['warehouse_id']}", headers=admin_h,
                         json={"name": "Kho test 5 (đổi tên)", "address": "Hạ Long"})
    assert updated.status_code == 200, updated.text

    listed = client.get("/api/wms/warehouses", headers=admin_h).json()
    row = next(w for w in listed if w["warehouse_id"] == wh["warehouse_id"])
    assert row["name"] == "Kho test 5 (đổi tên)"
