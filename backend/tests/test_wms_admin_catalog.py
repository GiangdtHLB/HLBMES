"""Danh mục Vị trí kho thành phẩm (WmsLocation) — CHỈ ADMIN được tạo/sửa/xóa (xem
routers/wms.py::create_location/update_location/delete_location, require_role(user, Role.ADMIN)).
GET (đọc/liệt kê) vẫn mở cho mọi tài khoản đã đăng nhập vì Kho TP cần đọc danh sách vị trí."""

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
    # "thukho" có quyền warehouse.receive nhưng không phải admin — đúng đối tượng cần bị chặn.
    return _login(client, "thukho", "123456")


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


def test_get_endpoints_still_open_to_non_admin(client, thukho_h):
    # Đọc/liệt kê KHÔNG đổi — mọi tài khoản đã đăng nhập vẫn xem được để chọn ở các form khác.
    assert client.get("/api/wms/locations", headers=thukho_h).status_code == 200
