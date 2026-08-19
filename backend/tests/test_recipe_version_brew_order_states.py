"""Test: Lệnh nấu chỉ chấp nhận RecipeVersion đang ĐÚNG trạng thái "effective" — version đã
"suspended" (tạm ngưng) hoặc "obsolete" (ngừng dùng vĩnh viễn) phải bị từ chối y hệt version
còn "draft" (xem services/brew_order.py::_validate_recipe_version_selection). Bổ sung phần
chưa được test_formula_multi_active.py/test_recipe_product_unique.py phủ tới (2 file đó chỉ
test draft/effective/wrong-product)."""

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
    r = client.post("/api/products", headers=headers,
                    json={"code": f"PRD-{suffix}", "name": f"Dịch test {suffix}", "uom": "L"})
    assert r.status_code == 201, r.text
    return r.json()["product_id"]


def _a_recipe_version(client, headers, product_id, qty=10):
    r = client.post("/api/recipes", headers=headers,
                    json={"code": f"CT-{new_id()[:8]}", "name": "Test recipe", "product_id": product_id})
    assert r.status_code == 201, r.text
    recipe = r.json()
    v = client.post(f"/api/recipes/{recipe['recipe_id']}/versions", headers=headers,
                    json={"base_qty": 1000, "base_uom": "L",
                          "materials": [{"material_code": "MALT-PILS", "qty": qty, "uom": "kg"}]})
    assert v.status_code == 201, v.text
    return v.json()["version_id"]


def _transition(client, headers, version_id, target, reason=None):
    r = client.post(f"/api/recipes/versions/{version_id}/transition", headers=headers,
                    json={"target": target, "reason": reason})
    assert r.status_code == 200, r.text


def _order_payload(product_id, version_id, code):
    return {"order_code": code, "product_id": product_id, "recipe_version_id": version_id,
            "planned_batch_count": 1, "planned_volume_hl": 100, "volume_tolerance_hl": 0,
            "auto_from_bom": True, "lines": []}


def test_brew_order_rejects_suspended_version(client, admin_h):
    product_id = _a_product(client, admin_h)
    version_id = _a_recipe_version(client, admin_h, product_id)
    for target in ("review", "approved", "effective"):
        _transition(client, admin_h, version_id, target)
    _transition(client, admin_h, version_id, "suspended", reason="Tạm ngưng để kiểm tra lại")

    r = client.post("/api/brewing/orders", headers=admin_h,
                    json=_order_payload(product_id, version_id, f"LN-SUSP-{new_id()[:6]}"))
    assert r.status_code == 409, r.text
    assert "không còn hiệu lực" in r.text


def test_brew_order_rejects_obsolete_version(client, admin_h):
    product_id = _a_product(client, admin_h)
    version_id = _a_recipe_version(client, admin_h, product_id)
    for target in ("review", "approved"):
        _transition(client, admin_h, version_id, target)
    _transition(client, admin_h, version_id, "obsolete", reason="Ngừng dùng vĩnh viễn để kiểm tra")

    r = client.post("/api/brewing/orders", headers=admin_h,
                    json=_order_payload(product_id, version_id, f"LN-OBS-{new_id()[:6]}"))
    assert r.status_code == 409, r.text
    assert "không còn hiệu lực" in r.text


def test_brew_order_accepts_reactivated_suspended_version(client, admin_h):
    """suspended -> effective là transition hợp lệ trực tiếp (không cần lại review/approve) —
    xem common.py::RECIPE_TRANSITIONS."""
    product_id = _a_product(client, admin_h)
    version_id = _a_recipe_version(client, admin_h, product_id)
    for target in ("review", "approved", "effective"):
        _transition(client, admin_h, version_id, target)
    _transition(client, admin_h, version_id, "suspended", reason="Tạm ngưng")
    _transition(client, admin_h, version_id, "effective")

    r = client.post("/api/brewing/orders", headers=admin_h,
                    json=_order_payload(product_id, version_id, f"LN-REACT-{new_id()[:6]}"))
    assert r.status_code == 201, r.text
