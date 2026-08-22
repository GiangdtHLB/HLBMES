"""Test: nhiều công thức/dịch bia cùng hiệu lực đồng thời (services/formula.py) + chọn ĐÚNG 1
RecipeVersion đang effective khi lập Lệnh nấu (services/brew_order.py::
_validate_recipe_version_selection, build_lines_from_recipe_version) — 1 Loại bia có đúng 1
Recipe (models/recipes.py, unique beer_type_id), mỗi RecipeVersion bên trong tự gắn 1 Dịch bia
riêng (product_id) và nhiều version của CÙNG 1 dịch có thể cùng ở trạng thái "effective" đồng
thời, người lập lệnh phải tự chọn đúng 1 version."""

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
from app.common import new_id


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


def _a_product(client, headers):
    suffix = new_id()[:8]
    bt = client.post("/api/beer-types", headers=headers, json={"code": f"BT-{suffix}", "name": f"Loại {suffix}"})
    assert bt.status_code == 201, bt.text
    r = client.post("/api/products", headers=headers,
                    json={"code": f"PRD-{suffix}", "name": f"Dịch test {suffix}", "uom": "L",
                          "beer_type_id": bt.json()["beer_type_id"]})
    assert r.status_code == 201, r.text
    return r.json()["product_id"]


def _a_formula(client, headers, product_id, qty=10):
    payload = {"code": f"CT-{new_id()[:8]}", "product_id": product_id, "base_qty": 1000, "base_uom": "L",
               "materials": [{"material_code": "MALT-PILS", "qty": qty, "uom": "kg"}]}
    r = client.post("/api/formulas", headers=headers, json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _a_recipe(client, headers, product_id):
    products = client.get("/api/products", headers=headers).json()
    beer_type_id = next(p["beer_type_id"] for p in products if p["product_id"] == product_id)
    r = client.post("/api/recipes", headers=headers,
                    json={"code": f"CT-{new_id()[:8]}", "name": "Test recipe", "beer_type_id": beer_type_id})
    assert r.status_code == 201, r.text
    return r.json()


def _a_recipe_version(client, headers, recipe_id, product_id, qty=10):
    r = client.post(f"/api/recipes/{recipe_id}/versions", headers=headers,
                    json={"product_id": product_id, "base_qty": 1000, "base_uom": "L",
                          "materials": [{"material_code": "MALT-PILS", "qty": qty, "uom": "kg"}]})
    assert r.status_code == 201, r.text
    return r.json()


def _activate_recipe_version(client, headers, version_id):
    for target in ("review", "approved", "effective"):
        r = client.post(f"/api/recipes/versions/{version_id}/transition", headers=headers, json={"target": target})
        assert r.status_code == 200, r.text


def test_two_formulas_same_product_both_stay_active(client, admin_h):
    product_id = _a_product(client, admin_h)
    f1 = _a_formula(client, admin_h, product_id, qty=10)
    f2 = _a_formula(client, admin_h, product_id, qty=20)

    client.post(f"/api/formulas/{f1['formula_id']}/activate", headers=admin_h)
    client.post(f"/api/formulas/{f2['formula_id']}/activate", headers=admin_h)

    f1_after = client.get(f"/api/formulas/{f1['formula_id']}", headers=admin_h).json()
    f2_after = client.get(f"/api/formulas/{f2['formula_id']}", headers=admin_h).json()
    assert f1_after["is_active"] is True
    assert f2_after["is_active"] is True


def test_two_recipe_versions_same_product_both_stay_effective(client, admin_h):
    product_id = _a_product(client, admin_h)
    recipe = _a_recipe(client, admin_h, product_id)
    v1 = _a_recipe_version(client, admin_h, recipe["recipe_id"], product_id, qty=10)
    v2 = _a_recipe_version(client, admin_h, recipe["recipe_id"], product_id, qty=20)
    _activate_recipe_version(client, admin_h, v1["version_id"])
    _activate_recipe_version(client, admin_h, v2["version_id"])

    v1_after = client.get(f"/api/recipes/versions/{v1['version_id']}", headers=admin_h).json()
    v2_after = client.get(f"/api/recipes/versions/{v2['version_id']}", headers=admin_h).json()
    assert v1_after["state"] == "effective"
    assert v2_after["state"] == "effective"


def test_brew_order_missing_recipe_version_id_with_product_id_rejected(client, admin_h):
    product_id = _a_product(client, admin_h)

    r = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": f"LN-NOFRM-{new_id()[:6]}", "product_id": product_id,
        "planned_batch_count": 1, "planned_volume_hl": 100, "volume_tolerance_hl": 0,
        "auto_from_bom": True, "lines": [],
    })
    assert r.status_code == 409, r.text
    assert "Chọn công thức" in r.text


def test_brew_order_correct_recipe_version_id_loads_bom_from_that_version(client, admin_h):
    product_id = _a_product(client, admin_h)
    recipe = _a_recipe(client, admin_h, product_id)
    v1 = _a_recipe_version(client, admin_h, recipe["recipe_id"], product_id, qty=10)
    v2 = _a_recipe_version(client, admin_h, recipe["recipe_id"], product_id, qty=999)
    _activate_recipe_version(client, admin_h, v1["version_id"])
    _activate_recipe_version(client, admin_h, v2["version_id"])

    order = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": f"LN-PICKFRM-{new_id()[:6]}", "product_id": product_id,
        "recipe_version_id": v1["version_id"],
        "planned_batch_count": 2, "planned_volume_hl": 100, "volume_tolerance_hl": 0,
        "auto_from_bom": True, "lines": [],
    })
    assert order.status_code == 201, order.text
    detail = client.get(f"/api/brewing/orders/{order.json()['brew_order_id']}", headers=admin_h).json()
    line = next(l for l in detail["lines"] if not l["is_header"])
    # v1 khai 10 kg/mẻ — phải nạp đúng từ v1, KHÔNG lẫn với v2 (999 kg/mẻ).
    assert line["qty_per_batch"] == pytest.approx(10)
    assert line["qty_total"] == pytest.approx(20)


def test_brew_order_recipe_version_id_wrong_product_rejected(client, admin_h):
    product_a = _a_product(client, admin_h)
    product_b = _a_product(client, admin_h)
    recipe_b = _a_recipe(client, admin_h, product_b)
    v_b = _a_recipe_version(client, admin_h, recipe_b["recipe_id"], product_b)
    _activate_recipe_version(client, admin_h, v_b["version_id"])

    r = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": f"LN-WRONGPRD-{new_id()[:6]}", "product_id": product_a,
        "recipe_version_id": v_b["version_id"],
        "planned_batch_count": 1, "planned_volume_hl": 100, "volume_tolerance_hl": 0,
        "auto_from_bom": True, "lines": [],
    })
    assert r.status_code == 409, r.text
    assert "không thuộc Dịch bia" in r.text


def test_brew_order_recipe_version_id_not_effective_rejected(client, admin_h):
    product_id = _a_product(client, admin_h)
    recipe = _a_recipe(client, admin_h, product_id)
    v = _a_recipe_version(client, admin_h, recipe["recipe_id"], product_id)
    # KHÔNG activate — vẫn ở trạng thái draft.

    r = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": f"LN-INACTIVE-{new_id()[:6]}", "product_id": product_id,
        "recipe_version_id": v["version_id"],
        "planned_batch_count": 1, "planned_volume_hl": 100, "volume_tolerance_hl": 0,
        "auto_from_bom": True, "lines": [],
    })
    assert r.status_code == 409, r.text
    assert "không còn hiệu lực" in r.text
