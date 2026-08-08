"""Danh mục Kho thành phẩm/Vị trí kho/Lái xe đã chuyển từ tab Kho TP (WMS) sang Danh mục
(Master) và khóa CHỈ ADMIN được tạo/sửa/xóa (trước đây bất kỳ ai có quyền warehouse.receive —
nhiều vai trò thủ kho — đều làm được, không có gate nào). GET (đọc/liệt kê) vẫn mở cho mọi tài
khoản đã đăng nhập vì các form khác (Nhập kho, Xuất kho...) cần đọc danh sách để chọn."""

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
    # "thukho" có quyền warehouse.receive (trước đây đủ để tạo/sửa/xóa 3 danh mục này) nhưng
    # không phải admin — đúng đối tượng cần bị chặn sau thay đổi này.
    return _login(client, "thukho", "123456")


def test_warehouse_crud_admin_only(client, admin_h, thukho_h):
    denied_create = client.post("/api/wms/warehouses", headers=thukho_h,
                                json={"code": "WH-ADMONLY-1", "name": "Kho chặn thukho"})
    assert denied_create.status_code == 403, denied_create.text

    created = client.post("/api/wms/warehouses", headers=admin_h,
                          json={"code": "WH-ADMONLY-1", "name": "Kho admin tạo"})
    assert created.status_code == 201, created.text
    warehouse_id = created.json()["warehouse_id"]

    denied_update = client.put(f"/api/wms/warehouses/{warehouse_id}", headers=thukho_h,
                               json={"name": "Đổi tên trái phép"})
    assert denied_update.status_code == 403, denied_update.text

    denied_delete = client.delete(f"/api/wms/warehouses/{warehouse_id}", headers=thukho_h)
    assert denied_delete.status_code == 403, denied_delete.text

    ok_update = client.put(f"/api/wms/warehouses/{warehouse_id}", headers=admin_h,
                           json={"name": "Kho admin đã sửa"})
    assert ok_update.status_code == 200, ok_update.text

    ok_delete = client.delete(f"/api/wms/warehouses/{warehouse_id}", headers=admin_h)
    assert ok_delete.status_code == 204, ok_delete.text


def test_location_crud_admin_only(client, admin_h, thukho_h):
    denied_create = client.post("/api/wms/locations", headers=thukho_h,
                                json={"code": "LOC-ADMONLY-1", "name": "Vị trí chặn thukho"})
    assert denied_create.status_code == 403, denied_create.text

    created = client.post("/api/wms/locations", headers=admin_h,
                          json={"code": "LOC-ADMONLY-1", "name": "Vị trí admin tạo"})
    assert created.status_code == 201, created.text
    loc_id = created.json()["loc_id"]

    denied_update = client.put(f"/api/wms/locations/{loc_id}", headers=thukho_h,
                               json={"name": "Đổi tên trái phép"})
    assert denied_update.status_code == 403, denied_update.text

    denied_delete = client.delete(f"/api/wms/locations/{loc_id}", headers=thukho_h)
    assert denied_delete.status_code == 403, denied_delete.text

    ok_update = client.put(f"/api/wms/locations/{loc_id}", headers=admin_h,
                           json={"name": "Vị trí admin đã sửa"})
    assert ok_update.status_code == 200, ok_update.text

    ok_delete = client.delete(f"/api/wms/locations/{loc_id}", headers=admin_h)
    assert ok_delete.status_code == 204, ok_delete.text


def test_vehicle_crud_admin_only(client, admin_h, thukho_h):
    denied_create = client.post("/api/wms/vehicles", headers=thukho_h, json={"plate": "14K-ADMONLY1"})
    assert denied_create.status_code == 403, denied_create.text

    created = client.post("/api/wms/vehicles", headers=admin_h, json={"plate": "14K-ADMONLY1"})
    assert created.status_code == 201, created.text
    vehicle_id = created.json()["vehicle_id"]

    denied_update = client.put(f"/api/wms/vehicles/{vehicle_id}", headers=thukho_h, json={"phone": "0900000000"})
    assert denied_update.status_code == 403, denied_update.text

    denied_delete = client.delete(f"/api/wms/vehicles/{vehicle_id}", headers=thukho_h)
    assert denied_delete.status_code == 403, denied_delete.text

    ok_update = client.put(f"/api/wms/vehicles/{vehicle_id}", headers=admin_h, json={"phone": "0900000000"})
    assert ok_update.status_code == 200, ok_update.text

    ok_delete = client.delete(f"/api/wms/vehicles/{vehicle_id}", headers=admin_h)
    assert ok_delete.status_code == 204, ok_delete.text


def test_get_endpoints_still_open_to_non_admin(client, thukho_h):
    # Đọc/liệt kê KHÔNG đổi — mọi tài khoản đã đăng nhập vẫn xem được để chọn ở các form khác.
    assert client.get("/api/wms/warehouses", headers=thukho_h).status_code == 200
    assert client.get("/api/wms/locations", headers=thukho_h).status_code == 200
    assert client.get("/api/wms/vehicles", headers=thukho_h).status_code == 200
