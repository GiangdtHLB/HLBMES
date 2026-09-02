"""Test "Ghi actual" (tham số quy trình) cho Mẻ sản xuất (BatchExecution) — tham số/target/
giới hạn lấy từ recipe_snapshot.parameters (đã đóng băng từ RecipeVersionParamItem chọn từ
Danh mục tham số ProcessParameter, xem services/recipes.py::_resolve_param_items), mirror cách
tính pass/fail của chỉ tiêu QC. Xem services/batches.py::record_actual.
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


def _batch_running_with_param(client, admin_h, suffix):
    """Tạo 1 mẻ (running) từ 1 recipe version có 1 tham số chọn từ Danh mục (ProcessParameter)
    — trả về (batch_id, param dict lấy từ recipe_snapshot.parameters)."""
    param = client.post("/api/process-params/parameters", headers=admin_h,
                        json={"code": f"TEMP-{suffix}", "name": f"Nhiệt độ lên men {suffix}",
                             "unit": "°C", "target": 18, "usl": 22, "lsl": 14, "phase": "len_men"})
    assert param.status_code == 201, param.text
    param_id = param.json()["param_id"]

    bt = client.post("/api/beer-types", headers=admin_h,
                     json={"code": f"BT-ACT-{suffix}", "name": f"Loại test {suffix}"})
    assert bt.status_code == 201, bt.text
    recipe = client.post("/api/recipes", headers=admin_h,
                        json={"code": f"CT-ACT-{suffix}", "name": "Test recipe actual",
                             "beer_type_id": bt.json()["beer_type_id"]})
    assert recipe.status_code == 201, recipe.text
    product = client.post("/api/products", headers=admin_h,
                         json={"code": f"PRD-ACT-{suffix}", "name": f"Dịch test {suffix}", "uom": "L",
                              "beer_type_id": bt.json()["beer_type_id"]})
    assert product.status_code == 201, product.text
    v = client.post(f"/api/recipes/{recipe.json()['recipe_id']}/versions", headers=admin_h,
                    json={"base_qty": 100, "base_uom": "L", "product_id": product.json()["product_id"],
                         "param_items": [{"param_id": param_id}]})
    assert v.status_code == 201, v.text
    version_id = v.json()["version_id"]
    for target in ("review", "approved", "effective"):
        t = client.post(f"/api/recipes/versions/{version_id}/transition", headers=admin_h, json={"target": target})
        assert t.status_code == 200, t.text

    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": version_id,
                         "planned_qty": 100, "allow_shortage": True})   # batch_code: để tự sinh (giờ bắt buộc số nguyên)
    assert b.status_code == 201, b.text
    batch_id = b.json()["batch_id"]
    snap_param = b.json()["recipe_snapshot"]["parameters"][0]
    assert snap_param["param_id"] == param_id
    assert snap_param["target"] == 18 and snap_param["lower"] == 14 and snap_param["upper"] == 22

    for target in ("ready", "running"):
        t = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": target})
        assert t.status_code == 200, t.text
    return batch_id, snap_param


def test_record_actual_within_range_passes(client, admin_h):
    batch_id, p = _batch_running_with_param(client, admin_h, "PASS01")
    r = client.post(f"/api/batches/{batch_id}/actuals", headers=admin_h, json={
        "name": p["name"], "param_id": p["param_id"], "target": p["target"],
        "actual": 18.5, "unit": p["unit"], "phase": p["phase"], "lower": p["lower"], "upper": p["upper"],
    })
    assert r.status_code == 200, r.text
    entry = r.json()["actuals"][-1]
    assert entry["status"] == "pass" and entry["actual"] == 18.5 and entry["param_id"] == p["param_id"]


def test_record_actual_outside_range_fails(client, admin_h):
    batch_id, p = _batch_running_with_param(client, admin_h, "FAIL01")
    r = client.post(f"/api/batches/{batch_id}/actuals", headers=admin_h, json={
        "name": p["name"], "param_id": p["param_id"], "target": p["target"],
        "actual": 25.0, "unit": p["unit"], "phase": p["phase"], "lower": p["lower"], "upper": p["upper"],
    })
    assert r.status_code == 200, r.text
    entry = r.json()["actuals"][-1]
    assert entry["status"] == "fail"


def test_record_actual_without_value_has_no_status(client, admin_h):
    batch_id, p = _batch_running_with_param(client, admin_h, "NOVAL01")
    r = client.post(f"/api/batches/{batch_id}/actuals", headers=admin_h, json={
        "name": p["name"], "param_id": p["param_id"], "lower": p["lower"], "upper": p["upper"],
    })
    assert r.status_code == 200, r.text
    entry = r.json()["actuals"][-1]
    assert entry["status"] is None and entry["actual"] is None
