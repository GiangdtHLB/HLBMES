"""Xóa Lệnh sản xuất (điều độ, WorkOrder) — chặn nếu đã "Phát mẻ" tạo mã nấu thật (BrewRecord)
từ lệnh đó, mirror quy ước chặn sửa/xóa-khi-đã-thực-hiện dùng ở mọi module lệnh khác (xem
services/workorders.py::delete_wo)."""

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
def lager_product_id(client, admin_h):
    products = client.get("/api/products", headers=admin_h).json()
    return next(p["product_id"] for p in products if p["code"] == "BIA-LAGER")


@pytest.fixture(scope="module")
def lager_beer_type_id(client, admin_h, lager_product_id):
    products = client.get("/api/products", headers=admin_h).json()
    return next(p["beer_type_id"] for p in products if p["product_id"] == lager_product_id)


@pytest.fixture(scope="module")
def lager_recipe_version_id(client, admin_h, lager_product_id, lager_beer_type_id):
    recipes = client.get("/api/recipes", headers=admin_h).json()
    recipe = next(r for r in recipes if r["beer_type_id"] == lager_beer_type_id)
    versions = client.get(f"/api/recipes/{recipe['recipe_id']}/versions", headers=admin_h).json()
    return next(v["version_id"] for v in versions if v["state"] == "effective" and v["product_id"] == lager_product_id)


def _a_brew_order(client, admin_h, code, product_id, recipe_version_id, planned_volume_hl=100):
    r = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": code, "product_id": product_id, "recipe_version_id": recipe_version_id,
        "planned_volume_hl": planned_volume_hl, "auto_from_bom": False})
    assert r.status_code == 201, r.text
    return r.json()["brew_order_id"]


def _a_wo(client, admin_h, brew_order_id, brewhouse_line_id, line="Nấu A", recipe_version_id=None):
    r = client.post("/api/workorders", headers=admin_h, json={
        "brew_order_id": brew_order_id, "line": line, "brewhouse_line_id": brewhouse_line_id,
        "shift": "A", "priority": 5, "recipe_version_id": recipe_version_id})
    assert r.status_code == 201, r.text
    return r.json()["wo_id"]


@pytest.fixture(scope="module")
def brewhouse_line_id(client, admin_h):
    r = client.post("/api/lines", headers=admin_h,
                    json={"code": "BREW-WODEL-01", "name": "Nhà nấu test wodel", "kind": "brewhouse"})
    assert r.status_code == 201, r.text
    return r.json()["line_id"]


def test_delete_wo_before_dispatch(client, admin_h, lager_product_id, lager_recipe_version_id, brewhouse_line_id):
    brew_order_id = _a_brew_order(client, admin_h, "LN-WODEL-001", lager_product_id, lager_recipe_version_id)
    wo_id = _a_wo(client, admin_h, brew_order_id, brewhouse_line_id, recipe_version_id=lager_recipe_version_id)

    r = client.delete(f"/api/workorders/{wo_id}", headers=admin_h)
    assert r.status_code == 204, r.text
    assert client.get(f"/api/workorders/{wo_id}", headers=admin_h).status_code == 404


def test_delete_wo_blocked_after_dispatch(client, admin_h, lager_product_id, lager_recipe_version_id, brewhouse_line_id):
    brew_order_id = _a_brew_order(client, admin_h, "LN-WODEL-002", lager_product_id, lager_recipe_version_id)
    wo_id = _a_wo(client, admin_h, brew_order_id, brewhouse_line_id, recipe_version_id=lager_recipe_version_id)

    trans = client.post(f"/api/workorders/{wo_id}/transition", headers=admin_h, json={"target": "released"})
    assert trans.status_code == 200, trans.text

    # from_batch tránh 9001/9002 — seed.py dùng 2 mã đó cho mẻ demo (batch_code giờ unique theo
    # năm, 2026-09-02), trùng sẽ bị chặn 409 "Mã mẻ đã tồn tại".
    dispatched = client.post(f"/api/workorders/{wo_id}/dispatch", headers=admin_h,
                             json={"from_batch": 9501, "batch_count": 1})
    assert dispatched.status_code == 200, dispatched.text

    blocked = client.delete(f"/api/workorders/{wo_id}", headers=admin_h)
    assert blocked.status_code == 409, blocked.text


def test_delete_wo_not_found(client, admin_h):
    r = client.delete("/api/workorders/does-not-exist", headers=admin_h)
    assert r.status_code == 404, r.text


def test_delete_wo_requires_manage_perm(client, admin_h, lager_product_id, lager_recipe_version_id, brewhouse_line_id):
    vanhanh_h = _login(client, "vanhanh", "123456")
    brew_order_id = _a_brew_order(client, admin_h, "LN-WODEL-003", lager_product_id, lager_recipe_version_id)
    wo_id = _a_wo(client, admin_h, brew_order_id, brewhouse_line_id, recipe_version_id=lager_recipe_version_id)

    r = client.delete(f"/api/workorders/{wo_id}", headers=vanhanh_h)
    assert r.status_code == 403, r.text


def test_close_wo_blocked_while_batches_not_terminal(
        client, admin_h, lager_product_id, lager_recipe_version_id, brewhouse_line_id):
    """"Chốt" (closed) lệnh sản xuất phải chặn nếu còn Mẻ sản xuất nào thuộc lệnh chưa ở
    trạng thái kết thúc (closed/cancelled) — xem services/workorders.py::_assert_all_batches_terminal."""
    brew_order_id = _a_brew_order(client, admin_h, "LN-WODEL-004", lager_product_id, lager_recipe_version_id)
    wo_id = _a_wo(client, admin_h, brew_order_id, brewhouse_line_id, recipe_version_id=lager_recipe_version_id)
    trans = client.post(f"/api/workorders/{wo_id}/transition", headers=admin_h, json={"target": "released"})
    assert trans.status_code == 200, trans.text

    dispatched = client.post(f"/api/workorders/{wo_id}/dispatch", headers=admin_h,
                             json={"from_batch": 9101, "batch_count": 2})
    assert dispatched.status_code == 200, dispatched.text
    batch_ids = dispatched.json()["batch_ids"]

    complete_wo = client.post(f"/api/workorders/{wo_id}/transition", headers=admin_h,
                              json={"target": "completed"})
    assert complete_wo.status_code == 200, complete_wo.text

    # Cả 2 mẻ vẫn "planned" -> chặn chốt lệnh.
    blocked = client.post(f"/api/workorders/{wo_id}/transition", headers=admin_h, json={"target": "closed"})
    assert blocked.status_code == 409, blocked.text
    assert "chưa kết thúc" in blocked.json()["detail"]

    # Hủy mẻ thứ nhất -> vẫn còn mẻ thứ 2 chưa xong -> vẫn chặn.
    cancel1 = client.post(f"/api/batches/{batch_ids[0]}/transition", headers=admin_h,
                          json={"target": "cancelled"})
    assert cancel1.status_code == 200, cancel1.text
    still_blocked = client.post(f"/api/workorders/{wo_id}/transition", headers=admin_h, json={"target": "closed"})
    assert still_blocked.status_code == 409, still_blocked.text

    # Hủy nốt mẻ thứ 2 -> cả 2 mẻ đã kết thúc -> chốt lệnh được.
    cancel2 = client.post(f"/api/batches/{batch_ids[1]}/transition", headers=admin_h,
                          json={"target": "cancelled"})
    assert cancel2.status_code == 200, cancel2.text
    closed = client.post(f"/api/workorders/{wo_id}/transition", headers=admin_h, json={"target": "closed"})
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed"
