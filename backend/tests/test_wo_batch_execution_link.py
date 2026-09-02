"""Test liên kết Lệnh SX (điều độ, WorkOrder) ↔ Mẻ sản xuất (BatchExecution) qua work_order_id
— "Tạo mẻ" (Mẻ sản xuất) chọn 1 Lệnh SX sẽ tự điền Dây chuyền nấu theo lệnh đó (vẫn chọn/sửa độc
lập được), và rollup của Lệnh SX (batches/actual_qty/completion_pct) tính theo CHÍNH các mẻ này
— KHÔNG còn qua Nấu-Lọc-Chiết (BrewRecord/BrewBatch, xem test_workorder_dispatch_real_flow.py).
Xem services/workorders.py::rollup, services/batches.py::create_batch.
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
def lager_product_id(client, admin_h):
    products = client.get("/api/products", headers=admin_h).json()
    return next(p["product_id"] for p in products if p["code"] == "BIA-LAGER")


@pytest.fixture(scope="module")
def lager_recipe_version_id(client, admin_h, lager_product_id):
    recipes = client.get("/api/recipes", headers=admin_h).json()
    products = client.get("/api/products", headers=admin_h).json()
    lager = next(p for p in products if p["product_id"] == lager_product_id)
    recipe = next(r for r in recipes if r["beer_type_id"] == lager["beer_type_id"])
    versions = client.get(f"/api/recipes/{recipe['recipe_id']}/versions", headers=admin_h).json()
    return next(v["version_id"] for v in versions if v["state"] == "effective")


@pytest.fixture(scope="module")
def brewhouse_line_id(client, admin_h):
    r = client.post("/api/lines", headers=admin_h,
                    json={"code": "BREW-WOLINK-01", "name": "Nhà nấu test wolink", "kind": "brewhouse"})
    assert r.status_code == 201, r.text
    return r.json()["line_id"]


@pytest.fixture(scope="module")
def other_brewhouse_line_id(client, admin_h):
    r = client.post("/api/lines", headers=admin_h,
                    json={"code": "BREW-WOLINK-02", "name": "Nhà nấu test wolink 2", "kind": "brewhouse"})
    assert r.status_code == 201, r.text
    return r.json()["line_id"]


def _a_brew_order(client, admin_h, code, product_id, recipe_version_id, planned_volume_hl=100):
    r = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": code, "product_id": product_id, "recipe_version_id": recipe_version_id,
        "planned_volume_hl": planned_volume_hl, "auto_from_bom": False})
    assert r.status_code == 201, r.text
    return r.json()["brew_order_id"]


def _a_wo(client, admin_h, brew_order_id, recipe_version_id, brewhouse_line_id, line="Nấu A"):
    r = client.post("/api/workorders", headers=admin_h, json={
        "brew_order_id": brew_order_id, "line": line, "brewhouse_line_id": brewhouse_line_id,
        "shift": "A", "priority": 5,
        "recipe_version_id": recipe_version_id, "planned_qty": 100, "uom": "hl"})
    assert r.status_code == 201, r.text
    return r.json()["wo_id"]


def test_batch_linked_to_wo_inherits_line_and_counts_in_rollup(
        client, admin_h, lager_product_id, lager_recipe_version_id, brewhouse_line_id):
    brew_order_id = _a_brew_order(client, admin_h, "LN-WOLINK-001", lager_product_id, lager_recipe_version_id)
    wo_id = _a_wo(client, admin_h, brew_order_id, lager_recipe_version_id, brewhouse_line_id)

    b = client.post("/api/batches", headers=admin_h, json={
        "order_id": brew_order_id, "recipe_version_id": lager_recipe_version_id,
        "batch_code": "1", "planned_qty": 50, "allow_shortage": True,
        "work_order_id": wo_id})
    assert b.status_code == 201, b.text
    body = b.json()
    assert body["work_order_id"] == wo_id
    assert body["brewhouse_line_id"] == brewhouse_line_id   # tự điền theo Lệnh SX

    wo = client.get(f"/api/workorders/{wo_id}", headers=admin_h).json()
    assert wo["rollup"]["batches"] == 1
    assert wo["rollup"]["batch_list"][0]["batch_code"] == "1"

    board = client.get("/api/workorders", headers=admin_h).json()
    row = next(w for w in board if w["wo_id"] == wo_id)
    assert row["batches"] == 1


def test_batch_line_can_be_set_independently_of_work_order(
        client, admin_h, lager_product_id, lager_recipe_version_id,
        brewhouse_line_id, other_brewhouse_line_id):
    brew_order_id = _a_brew_order(client, admin_h, "LN-WOLINK-002", lager_product_id, lager_recipe_version_id)
    wo_id = _a_wo(client, admin_h, brew_order_id, lager_recipe_version_id, brewhouse_line_id)

    # Chọn Lệnh SX NHƯNG override Dây chuyền nấu khác với lệnh đó -> vẫn được, dùng đúng dây
    # chuyền được chỉ định thay vì tự điền theo Lệnh SX.
    b = client.post("/api/batches", headers=admin_h, json={
        "order_id": brew_order_id, "recipe_version_id": lager_recipe_version_id,
        "batch_code": "2", "planned_qty": 50, "allow_shortage": True,
        "work_order_id": wo_id, "brewhouse_line_id": other_brewhouse_line_id})
    assert b.status_code == 201, b.text
    assert b.json()["brewhouse_line_id"] == other_brewhouse_line_id


def test_batch_line_settable_without_any_work_order(
        client, admin_h, lager_product_id, lager_recipe_version_id, brewhouse_line_id):
    brew_order_id = _a_brew_order(client, admin_h, "LN-WOLINK-003", lager_product_id, lager_recipe_version_id)
    b = client.post("/api/batches", headers=admin_h, json={
        "order_id": brew_order_id, "recipe_version_id": lager_recipe_version_id,
        "batch_code": "3", "planned_qty": 50, "allow_shortage": True,
        "brewhouse_line_id": brewhouse_line_id})
    assert b.status_code == 201, b.text
    assert b.json()["work_order_id"] is None
    assert b.json()["brewhouse_line_id"] == brewhouse_line_id


def test_batch_rejects_invalid_line_and_mismatched_work_order(
        client, admin_h, lager_product_id, lager_recipe_version_id, brewhouse_line_id):
    brew_order_id_1 = _a_brew_order(client, admin_h, "LN-WOLINK-004A", lager_product_id, lager_recipe_version_id)
    brew_order_id_2 = _a_brew_order(client, admin_h, "LN-WOLINK-004B", lager_product_id, lager_recipe_version_id)
    wo_id = _a_wo(client, admin_h, brew_order_id_1, lager_recipe_version_id, brewhouse_line_id)

    mismatched = client.post("/api/batches", headers=admin_h, json={
        "order_id": brew_order_id_2, "recipe_version_id": lager_recipe_version_id,
        "batch_code": "4", "planned_qty": 50, "allow_shortage": True,
        "work_order_id": wo_id})
    assert mismatched.status_code == 409, mismatched.text

    bad_line = client.post("/api/batches", headers=admin_h, json={
        "order_id": brew_order_id_1, "recipe_version_id": lager_recipe_version_id,
        "batch_code": "5", "planned_qty": 50, "allow_shortage": True,
        "brewhouse_line_id": "nonexistent-line"})
    assert bad_line.status_code == 409, bad_line.text


def test_batch_brewhouse_line_editable_after_creation(
        client, admin_h, lager_product_id, lager_recipe_version_id,
        brewhouse_line_id, other_brewhouse_line_id):
    """Dây chuyền nấu của 1 mẻ đã tồn tại (kể cả mẻ tự kế thừa từ Work Order, chưa hề được người
    dùng tự chọn) vẫn sửa lại được sau — xem services/batches.py::set_brewhouse_line."""
    brew_order_id = _a_brew_order(client, admin_h, "LN-WOLINK-005", lager_product_id, lager_recipe_version_id)
    b = client.post("/api/batches", headers=admin_h, json={
        "order_id": brew_order_id, "recipe_version_id": lager_recipe_version_id,
        "batch_code": "6", "planned_qty": 50, "allow_shortage": True}).json()
    assert b["brewhouse_line_id"] is None

    r = client.post(f"/api/batches/{b['batch_id']}/brewhouse-line", headers=admin_h,
                    json={"brewhouse_line_id": brewhouse_line_id})
    assert r.status_code == 200, r.text
    assert r.json()["brewhouse_line_id"] == brewhouse_line_id

    r2 = client.post(f"/api/batches/{b['batch_id']}/brewhouse-line", headers=admin_h,
                     json={"brewhouse_line_id": other_brewhouse_line_id})
    assert r2.status_code == 200, r2.text
    assert r2.json()["brewhouse_line_id"] == other_brewhouse_line_id

    cleared = client.post(f"/api/batches/{b['batch_id']}/brewhouse-line", headers=admin_h,
                          json={"brewhouse_line_id": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["brewhouse_line_id"] is None

    bad = client.post(f"/api/batches/{b['batch_id']}/brewhouse-line", headers=admin_h,
                      json={"brewhouse_line_id": "nonexistent-line"})
    assert bad.status_code == 409, bad.text
