"""Phân quyền theo địa điểm kho (Kho công ty ↔ Kho phân xưởng):

1) Thủ kho (scope_warehouse="cong_ty") thao tác được Kho công ty nhưng bị chặn (403) khi
   thao tác trực tiếp tại Kho phân xưởng — và ngược lại cho tài khoản scope "phan_xuong".
2) transfer() chỉ cho phép nếu user có phạm vi ở ít nhất 1 trong 2 đầu — chặn khi cả 2 đầu
   đều ngoài phạm vi (vd dùng tài khoản Kho công ty để chuyển thẳng giữa 2 lô cùng đang ở
   Kho phân xưởng).
3) Copy quyền (admin): sao chép toàn bộ vai trò/quyền/4 chiều scope từ 1 tài khoản sang
   tài khoản khác.
"""

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


def _create_material(client, admin_h, code):
    r = client.post("/api/materials", headers=admin_h,
                    json={"code": code, "name": f"Vật tư {code}", "uom": "kg", "category": "other"})
    assert r.status_code == 201, r.text
    return r.json()["material_id"]


def _make_user(client, admin_h, username, perms, scope_warehouse):
    r = client.post("/api/auth/users", headers=admin_h, json={
        "username": username, "password": "Test1234", "full_name": "Test User",
        "job_title": "Test", "role": "operator", "allowed_views": "dashboard",
        "permissions": perms, "scope_warehouse": scope_warehouse,
    })
    assert r.status_code == 201, r.text
    return _login(client, username, "Test1234")


def test_thukho_cong_ty_scope_blocks_receive_at_workshop(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "WHSCOPE-1")
    ok = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "WHSC-OK-1", "material_id": mat_id, "quantity": 10,
                           "uom": "kg", "location": "Kho công ty"})
    assert ok.status_code == 200, ok.text

    blocked = client.post("/api/warehouse/receive", headers=thukho_h,
                          json={"lot_code": "WHSC-BLOCK-1", "material_id": mat_id, "quantity": 10,
                                "uom": "kg", "location": "Kho phân xưởng"})
    assert blocked.status_code == 403, blocked.text


def test_workshop_scoped_user_blocked_at_company_allowed_at_workshop(client, admin_h):
    px_h = _make_user(client, admin_h, "test_px_user", "warehouse.receive,warehouse.issue", "phan_xuong")
    mat_id = _create_material(client, admin_h, "WHSCOPE-2")

    ok = client.post("/api/warehouse/receive", headers=px_h,
                     json={"lot_code": "WHSC-OK-2", "material_id": mat_id, "quantity": 5,
                           "uom": "kg", "location": "Kho phân xưởng"})
    assert ok.status_code == 200, ok.text

    blocked = client.post("/api/warehouse/receive", headers=px_h,
                          json={"lot_code": "WHSC-BLOCK-2", "material_id": mat_id, "quantity": 5,
                                "uom": "kg", "location": "Kho công ty"})
    assert blocked.status_code == 403, blocked.text


def test_transfer_blocked_when_neither_end_in_scope(client, admin_h, thukho_h):
    """thukho (scope cong_ty) không được chuyển thẳng giữa 2 vị trí đều đang ở Kho phân
    xưởng — cả 2 đầu đều ngoài phạm vi của thukho."""
    px_h = _make_user(client, admin_h, "test_px_user2", "warehouse.receive,warehouse.issue", "phan_xuong")
    mat_id = _create_material(client, admin_h, "WHSCOPE-3")
    lot = client.post("/api/warehouse/receive", headers=px_h,
                      json={"lot_code": "WHSC-3", "material_id": mat_id, "quantity": 8,
                            "uom": "kg", "location": "Kho phân xưởng"})
    assert lot.status_code == 200, lot.text
    lot_id = lot.json()["lot_id"]

    blocked = client.post("/api/warehouse/transfer", headers=thukho_h,
                          json={"lot_id": lot_id, "quantity": 8, "location_to": "Kho phân xưởng - Khu B"})
    assert blocked.status_code == 403, blocked.text


def test_copy_permissions_admin_only_and_overwrites_target(client, admin_h, thukho_h):
    dst_h = _make_user(client, admin_h, "test_copy_dst", "", "*")

    forbidden = client.post("/api/auth/users/test_copy_dst/copy-permissions", headers=thukho_h,
                            json={"source_username": "thukho"})
    assert forbidden.status_code == 403, forbidden.text

    ok = client.post("/api/auth/users/test_copy_dst/copy-permissions", headers=admin_h,
                     json={"source_username": "thukho"})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["scope_warehouse"] == "cong_ty"
    assert "warehouse.receive" in body["permissions"]
    assert "warehouse.issue" in body["permissions"]

    users = client.get("/api/auth/users", headers=admin_h).json()
    dst = next(u for u in users if u["username"] == "test_copy_dst")
    assert dst["scope_warehouse"] == "cong_ty"
    assert dst["role"] == "operator"

    same_user = client.post("/api/auth/users/test_copy_dst/copy-permissions", headers=admin_h,
                            json={"source_username": "test_copy_dst"})
    assert same_user.status_code == 409, same_user.text
