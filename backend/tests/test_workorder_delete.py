"""Xóa Lệnh sản xuất (điều độ, WorkOrder) — chặn nếu đã có Mẻ sản xuất (BatchExecution)
dispatch từ lệnh đó, mirror quy ước chặn sửa/xóa-khi-đã-thực-hiện dùng ở mọi module lệnh
khác (xem services/workorders.py::delete_wo)."""

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
def lager_recipe_version_id(client, admin_h, lager_product_id):
    products = client.get("/api/products", headers=admin_h).json()
    beer_type_id = next(p["beer_type_id"] for p in products if p["product_id"] == lager_product_id)
    recipes = client.get("/api/recipes", headers=admin_h).json()
    recipe = next(r for r in recipes if r["beer_type_id"] == beer_type_id)
    versions = client.get(f"/api/recipes/{recipe['recipe_id']}/versions", headers=admin_h).json()
    return next(v["version_id"] for v in versions if v["state"] == "effective" and v["product_id"] == lager_product_id)


def _a_production_order(client, admin_h, code, product_id, planned_qty=10000, uom="L"):
    r = client.post("/api/orders", headers=admin_h, json={
        "order_code": code, "product_id": product_id, "planned_qty": planned_qty, "uom": uom})
    assert r.status_code == 201, r.text
    return r.json()["order_id"]


def _a_wo(client, admin_h, production_order_id, line="Nấu A"):
    r = client.post("/api/workorders", headers=admin_h, json={
        "production_order_id": production_order_id, "line": line, "shift": "A", "priority": 5})
    assert r.status_code == 201, r.text
    return r.json()["wo_id"]


def test_delete_wo_before_dispatch(client, admin_h, lager_product_id):
    order_id = _a_production_order(client, admin_h, "PO-WODEL-001", lager_product_id)
    wo_id = _a_wo(client, admin_h, order_id)

    r = client.delete(f"/api/workorders/{wo_id}", headers=admin_h)
    assert r.status_code == 204, r.text
    assert client.get(f"/api/workorders/{wo_id}", headers=admin_h).status_code == 404


def test_delete_wo_blocked_after_dispatch(client, admin_h, lager_product_id, lager_recipe_version_id):
    order_id = _a_production_order(client, admin_h, "PO-WODEL-002", lager_product_id)
    wo_id = _a_wo(client, admin_h, order_id)

    trans = client.post(f"/api/workorders/{wo_id}/transition", headers=admin_h, json={"target": "released"})
    assert trans.status_code == 200, trans.text

    dispatched = client.post(f"/api/workorders/{wo_id}/dispatch", headers=admin_h, json={
        "recipe_version_id": lager_recipe_version_id, "allow_shortage": True})
    assert dispatched.status_code == 200, dispatched.text

    blocked = client.delete(f"/api/workorders/{wo_id}", headers=admin_h)
    assert blocked.status_code == 409, blocked.text


def test_delete_wo_not_found(client, admin_h):
    r = client.delete("/api/workorders/does-not-exist", headers=admin_h)
    assert r.status_code == 404, r.text


def test_delete_wo_requires_manage_perm(client, admin_h, lager_product_id):
    vanhanh_h = _login(client, "vanhanh", "123456")
    order_id = _a_production_order(client, admin_h, "PO-WODEL-003", lager_product_id)
    wo_id = _a_wo(client, admin_h, order_id)

    r = client.delete(f"/api/workorders/{wo_id}", headers=vanhanh_h)
    assert r.status_code == 403, r.text
