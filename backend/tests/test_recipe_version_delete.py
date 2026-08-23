"""Test: xóa 1 RecipeVersion riêng lẻ (VD tạo nhầm lúc test) — xem
services/master_data.py::delete_recipe_version. Khác delete_recipe (xóa cả công thức + mọi
version), API này chỉ xóa 1 version, không đụng version khác cùng công thức. Chặn nếu version
đã được tham chiếu ở lệnh nấu/lệnh SX (ERP)/work order/mẻ sản xuất (module cũ); yêu cầu quyền
master.manage."""

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


@pytest.fixture(scope="module")
def vanhanh_h(client):
    return _login(client, "vanhanh", "123456")


def _a_beer_type(client, headers):
    suffix = new_id()[:8]
    r = client.post("/api/beer-types", headers=headers, json={"code": f"BT-{suffix}", "name": f"Loại {suffix}"})
    assert r.status_code == 201, r.text
    return r.json()["beer_type_id"]


def _a_product(client, headers, beer_type_id=None):
    suffix = new_id()[:8]
    r = client.post("/api/products", headers=headers,
                    json={"code": f"PRD-{suffix}", "name": f"Dịch test {suffix}", "uom": "L",
                          "beer_type_id": beer_type_id})
    assert r.status_code == 201, r.text
    return r.json()["product_id"]


def _a_recipe(client, headers, beer_type_id):
    r = client.post("/api/recipes", headers=headers,
                    json={"code": f"CT-{new_id()[:8]}", "name": "Test recipe", "beer_type_id": beer_type_id})
    assert r.status_code == 201, r.text
    return r.json()["recipe_id"]


def _a_version(client, headers, recipe_id, product_id, qty=10):
    v = client.post(f"/api/recipes/{recipe_id}/versions", headers=headers,
                    json={"product_id": product_id, "base_qty": 1000, "base_uom": "L",
                          "materials": [{"material_code": "MALT-PILS", "qty": qty, "uom": "kg"}]})
    assert v.status_code == 201, v.text
    return v.json()["version_id"]


def _transition(client, headers, version_id, target, reason=None):
    r = client.post(f"/api/recipes/versions/{version_id}/transition", headers=headers,
                    json={"target": target, "reason": reason})
    assert r.status_code == 200, r.text


def test_delete_unused_version_succeeds(client, admin_h):
    beer_type_id = _a_beer_type(client, admin_h)
    product_id = _a_product(client, admin_h, beer_type_id)
    recipe_id = _a_recipe(client, admin_h, beer_type_id)
    v1 = _a_version(client, admin_h, recipe_id, product_id)
    v2 = _a_version(client, admin_h, recipe_id, product_id)

    d = client.delete(f"/api/recipes/versions/{v1}", headers=admin_h)
    assert d.status_code == 204, d.text

    remaining = client.get(f"/api/recipes/{recipe_id}/versions", headers=admin_h).json()
    assert [x["version_id"] for x in remaining] == [v2]


def test_delete_nonexistent_version_404(client, admin_h):
    d = client.delete(f"/api/recipes/versions/{new_id()}", headers=admin_h)
    assert d.status_code == 404, d.text


def test_delete_version_blocked_by_brew_order(client, admin_h):
    beer_type_id = _a_beer_type(client, admin_h)
    product_id = _a_product(client, admin_h, beer_type_id)
    recipe_id = _a_recipe(client, admin_h, beer_type_id)
    version_id = _a_version(client, admin_h, recipe_id, product_id)
    for target in ("review", "approved", "effective"):
        _transition(client, admin_h, version_id, target)

    bo = client.post("/api/brewing/orders", headers=admin_h,
                     json={"order_code": f"LN-VDEL-{new_id()[:6]}", "product_id": product_id,
                           "recipe_version_id": version_id, "auto_from_bom": False,
                           "planned_volume_hl": 100})
    assert bo.status_code == 201, bo.text

    d = client.delete(f"/api/recipes/versions/{version_id}", headers=admin_h)
    assert d.status_code == 409, d.text
    assert "lệnh nấu" in d.json()["detail"]


def test_delete_version_blocked_by_production_order(client, admin_h):
    beer_type_id = _a_beer_type(client, admin_h)
    product_id = _a_product(client, admin_h, beer_type_id)
    recipe_id = _a_recipe(client, admin_h, beer_type_id)
    version_id = _a_version(client, admin_h, recipe_id, product_id)
    for target in ("review", "approved", "effective"):
        _transition(client, admin_h, version_id, target)

    order = client.post("/api/orders", headers=admin_h,
                        json={"order_code": f"ORD-VDEL-{new_id()[:6]}", "product_id": product_id,
                              "recipe_version_id": version_id, "planned_qty": 1000, "uom": "L"})
    assert order.status_code == 201, order.text

    d = client.delete(f"/api/recipes/versions/{version_id}", headers=admin_h)
    assert d.status_code == 409, d.text
    assert "lệnh SX" in d.json()["detail"]


def test_delete_version_blocked_by_work_order(client, admin_h):
    from datetime import date

    from app.database import SessionLocal
    from app.models.workorder import WorkOrder

    beer_type_id = _a_beer_type(client, admin_h)
    product_id = _a_product(client, admin_h, beer_type_id)
    recipe_id = _a_recipe(client, admin_h, beer_type_id)
    version_id = _a_version(client, admin_h, recipe_id, product_id)
    order = client.post("/api/orders", headers=admin_h,
                        json={"order_code": f"ORD-VDEL2-{new_id()[:6]}", "product_id": product_id,
                              "planned_qty": 1000, "uom": "L"})
    assert order.status_code == 201, order.text
    order_id = order.json()["order_id"]

    # Giả lập version đã dispatch xuống 1 work order — tái dùng bảng có sẵn thay vì dựng toàn bộ
    # pipeline work-order/batch chỉ để test cờ chặn (mirror test_master_data_delete.py).
    db = SessionLocal()
    try:
        db.add(WorkOrder(wo_code=f"WO-VDEL-{new_id()[:6]}", production_order_id=order_id, product_id=product_id,
                         recipe_version_id=version_id, planned_qty=1000, scheduled_date=date.today()))
        db.commit()
    finally:
        db.close()

    d = client.delete(f"/api/recipes/versions/{version_id}", headers=admin_h)
    assert d.status_code == 409, d.text
    assert "work order" in d.json()["detail"]


def test_delete_version_requires_master_manage_permission(client, admin_h, vanhanh_h):
    beer_type_id = _a_beer_type(client, admin_h)
    product_id = _a_product(client, admin_h, beer_type_id)
    recipe_id = _a_recipe(client, admin_h, beer_type_id)
    version_id = _a_version(client, admin_h, recipe_id, product_id)

    d = client.delete(f"/api/recipes/versions/{version_id}", headers=vanhanh_h)
    assert d.status_code == 403, d.text


def _is_used(client, headers, recipe_id, version_id):
    versions = client.get(f"/api/recipes/{recipe_id}/versions", headers=headers).json()
    return next(v for v in versions if v["version_id"] == version_id)["is_used"]


def test_is_used_flag_false_for_unreferenced_version(client, admin_h):
    """Cờ is_used trả về từ GET /recipes/{id}/versions — dùng để ẩn nút "Xóa version" trên UI
    thay vì hiện rồi bấm mới báo lỗi (xem services/master_data.py::used_recipe_version_ids)."""
    beer_type_id = _a_beer_type(client, admin_h)
    product_id = _a_product(client, admin_h, beer_type_id)
    recipe_id = _a_recipe(client, admin_h, beer_type_id)
    version_id = _a_version(client, admin_h, recipe_id, product_id)

    assert _is_used(client, admin_h, recipe_id, version_id) is False


def test_is_used_flag_true_when_referenced_by_brew_order(client, admin_h):
    beer_type_id = _a_beer_type(client, admin_h)
    product_id = _a_product(client, admin_h, beer_type_id)
    recipe_id = _a_recipe(client, admin_h, beer_type_id)
    version_id = _a_version(client, admin_h, recipe_id, product_id)
    for target in ("review", "approved", "effective"):
        _transition(client, admin_h, version_id, target)

    bo = client.post("/api/brewing/orders", headers=admin_h,
                     json={"order_code": f"LN-ISUSED-{new_id()[:6]}", "product_id": product_id,
                           "recipe_version_id": version_id, "auto_from_bom": False,
                           "planned_volume_hl": 100})
    assert bo.status_code == 201, bo.text

    assert _is_used(client, admin_h, recipe_id, version_id) is True


def test_is_used_flag_true_when_referenced_by_production_order(client, admin_h):
    beer_type_id = _a_beer_type(client, admin_h)
    product_id = _a_product(client, admin_h, beer_type_id)
    recipe_id = _a_recipe(client, admin_h, beer_type_id)
    version_id = _a_version(client, admin_h, recipe_id, product_id)
    for target in ("review", "approved", "effective"):
        _transition(client, admin_h, version_id, target)

    order = client.post("/api/orders", headers=admin_h,
                        json={"order_code": f"ORD-ISUSED-{new_id()[:6]}", "product_id": product_id,
                              "recipe_version_id": version_id, "planned_qty": 1000, "uom": "L"})
    assert order.status_code == 201, order.text

    assert _is_used(client, admin_h, recipe_id, version_id) is True
