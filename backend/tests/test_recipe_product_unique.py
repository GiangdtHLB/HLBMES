"""Test: 1 dịch bia chỉ được đúng 1 công thức (Recipe.product_id unique) — bug thực tế:
trước đây tạo được 2 Recipe cho cùng 1 product, khiến brew_order._effective_bom() có thể
chọn nhầm recipe rỗng (không version) thay vì recipe thật, làm Lệnh nấu không tự nạp
được định mức NVL từ Công thức."""

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


def _a_product(client, headers, suffix):
    r = client.post("/api/products", headers=headers,
                    json={"code": f"PRD-{suffix}", "name": f"Dịch test {suffix}", "uom": "L"})
    assert r.status_code == 201, r.text
    return r.json()["product_id"]


def test_second_recipe_for_same_product_rejected(client, admin_h):
    product_id = _a_product(client, admin_h, "UNIQ")

    first = client.post("/api/recipes", headers=admin_h,
                        json={"code": "REC-UNIQ01", "name": "Công thức 1", "product_id": product_id})
    assert first.status_code == 201, first.text

    dup = client.post("/api/recipes", headers=admin_h,
                      json={"code": "REC-UNIQ02", "name": "Công thức 2 (trùng dịch bia)", "product_id": product_id})
    assert dup.status_code == 409, dup.text


def test_brew_order_auto_loads_bom_for_products_own_recipe(client, admin_h):
    """Kiểm tra brew_order.build_lines_from_bom lấy đúng recipe hiệu lực của dịch bia,
    không lẫn với recipe của dịch bia khác (mô phỏng đúng bug đã gặp)."""
    product_id = _a_product(client, admin_h, "BOMCHK")

    r = client.post("/api/recipes", headers=admin_h,
                    json={"code": "REC-BOMCHK", "name": "BOM check", "product_id": product_id})
    assert r.status_code == 201, r.text
    recipe_id = r.json()["recipe_id"]
    v = client.post(f"/api/recipes/{recipe_id}/versions", headers=admin_h,
                    json={"base_qty": 1000, "base_uom": "L",
                          "materials": [{"material_code": "MALT-PILS", "qty": 20, "uom": "kg", "tol_pct": 0}]})
    assert v.status_code == 201, v.text
    version_id = v.json()["version_id"]
    assert client.post(f"/api/recipes/versions/{version_id}/transition", headers=admin_h,
                       json={"target": "review"}).status_code == 200
    approved = client.post(f"/api/recipes/versions/{version_id}/transition", headers=admin_h,
                           json={"target": "approved"})
    assert approved.status_code == 200, approved.text
    effective = client.post(f"/api/recipes/versions/{version_id}/transition", headers=admin_h,
                            json={"target": "effective"})
    assert effective.status_code == 200, effective.text

    order = client.post("/api/brewing/orders", headers=admin_h,
                        json={"order_code": "LN-BOMCHK", "product_id": product_id,
                              "planned_batch_count": 2, "planned_volume_hl": 20,
                              "auto_from_bom": True})
    assert order.status_code == 201, order.text
    detail = client.get(f"/api/brewing/orders/{order.json()['brew_order_id']}", headers=admin_h).json()
    assert detail["lines"], "Lệnh nấu phải tự nạp được định mức NVL từ Công thức hiệu lực của dịch bia"
    line = detail["lines"][0]
    assert line["material_id"]
    assert "MALT" in line["material_name"].upper()
    assert line["qty_total"] == pytest.approx(40)
