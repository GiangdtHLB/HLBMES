"""Test: 1 Loại bia chỉ được đúng 1 công thức (Recipe.beer_type_id unique) — bug thực tế:
trước đây tạo được 2 Recipe cho cùng 1 product, khiến brew_order._effective_bom() có thể
chọn nhầm recipe rỗng (không version) thay vì recipe thật, làm Lệnh nấu không tự nạp
được định mức NVL từ Công thức. Recipe giờ đại diện 1 Loại bia (không còn 1 Product/dịch bia
duy nhất) — mỗi version bên trong tự gắn 1 Dịch bia riêng (VD 13oP/14oP cùng 1 Loại bia có thể
cùng nằm trong 1 Recipe, ở 2 version khác nhau) — xem models/recipes.py."""

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


def _a_beer_type(client, headers, suffix):
    r = client.post("/api/beer-types", headers=headers, json={"code": f"BT-{suffix}", "name": f"Loại {suffix}"})
    assert r.status_code == 201, r.text
    return r.json()["beer_type_id"]


def _a_product(client, headers, suffix, beer_type_id=None):
    r = client.post("/api/products", headers=headers,
                    json={"code": f"PRD-{suffix}", "name": f"Dịch test {suffix}", "uom": "L",
                          "beer_type_id": beer_type_id})
    assert r.status_code == 201, r.text
    return r.json()["product_id"]


def _an_effective_recipe_version(client, headers, beer_type_id, product_id, code, qty):
    r = client.post("/api/recipes", headers=headers,
                    json={"code": code, "name": f"Công thức {code}", "beer_type_id": beer_type_id})
    assert r.status_code == 201, r.text
    recipe = r.json()
    v = client.post(f"/api/recipes/{recipe['recipe_id']}/versions", headers=headers,
                    json={"product_id": product_id, "base_qty": 1000, "base_uom": "L",
                          "materials": [{"material_code": "MALT-PILS", "qty": qty, "uom": "kg"}]})
    assert v.status_code == 201, v.text
    version_id = v.json()["version_id"]
    for target in ("review", "approved", "effective"):
        t = client.post(f"/api/recipes/versions/{version_id}/transition", headers=headers, json={"target": target})
        assert t.status_code == 200, t.text
    return recipe["recipe_id"], version_id


def test_second_recipe_for_same_beer_type_rejected(client, admin_h):
    beer_type_id = _a_beer_type(client, admin_h, "UNIQ")
    product_id = _a_product(client, admin_h, "UNIQ", beer_type_id)

    first = client.post("/api/recipes", headers=admin_h,
                        json={"code": "REC-UNIQ01", "name": "Công thức 1", "beer_type_id": beer_type_id})
    assert first.status_code == 201, first.text

    dup = client.post("/api/recipes", headers=admin_h,
                      json={"code": "REC-UNIQ02", "name": "Công thức 2 (trùng loại bia)", "beer_type_id": beer_type_id})
    assert dup.status_code == 409, dup.text


def test_two_products_same_beer_type_get_two_versions_in_one_recipe(client, admin_h):
    """2 dịch bia (VD 13oP/14oP) cùng 1 Loại bia — tạo 2 version trong CÙNG 1 Recipe phải
    thành công, mỗi version tự gắn đúng dịch riêng của nó."""
    beer_type_id = _a_beer_type(client, admin_h, "MULTIOP")
    p13 = _a_product(client, admin_h, "MULTIOP-13", beer_type_id)
    p14 = _a_product(client, admin_h, "MULTIOP-14", beer_type_id)

    recipe_id, v13 = _an_effective_recipe_version(client, admin_h, beer_type_id, p13, "CT-MULTIOP", qty=10)
    v14 = client.post(f"/api/recipes/{recipe_id}/versions", headers=admin_h,
                      json={"product_id": p14, "base_qty": 1000, "base_uom": "L",
                            "materials": [{"material_code": "MALT-PILS", "qty": 12, "uom": "kg"}]})
    assert v14.status_code == 201, v14.text
    assert v14.json()["product_id"] == p14

    versions = client.get(f"/api/recipes/{recipe_id}/versions", headers=admin_h).json()
    assert {v["product_id"] for v in versions} == {p13, p14}


def test_version_rejects_product_from_other_beer_type(client, admin_h):
    beer_type_id = _a_beer_type(client, admin_h, "WRONGBT")
    other_beer_type_id = _a_beer_type(client, admin_h, "OTHERBT")
    other_product_id = _a_product(client, admin_h, "WRONGBT", other_beer_type_id)

    r = client.post("/api/recipes", headers=admin_h,
                    json={"code": "REC-WRONGBT", "name": "REC-WRONGBT", "beer_type_id": beer_type_id})
    assert r.status_code == 201, r.text

    v = client.post(f"/api/recipes/{r.json()['recipe_id']}/versions", headers=admin_h,
                    json={"product_id": other_product_id, "base_qty": 1000, "base_uom": "L"})
    assert v.status_code == 409, v.text
    assert "không thuộc Loại bia" in v.json()["detail"]


def test_brew_order_auto_loads_bom_for_products_own_recipe(client, admin_h):
    """Kiểm tra brew_order.build_lines_from_recipe_version lấy đúng RecipeVersion đang hiệu
    lực của dịch bia, không lẫn với công thức của dịch bia khác (mô phỏng đúng bug đã gặp ở
    RecipeVersion.state='effective' không loại trừ nhau — xem services/recipes.py)."""
    beer_type_id = _a_beer_type(client, admin_h, "BOMCHK")
    product_id = _a_product(client, admin_h, "BOMCHK", beer_type_id)
    _, version_id = _an_effective_recipe_version(client, admin_h, beer_type_id, product_id, "CT-BOMCHK", qty=20)

    order = client.post("/api/brewing/orders", headers=admin_h,
                        json={"order_code": "LN-BOMCHK", "product_id": product_id, "recipe_version_id": version_id,
                              "planned_batch_count": 2, "planned_volume_hl": 20,
                              "auto_from_bom": True})
    assert order.status_code == 201, order.text
    detail = client.get(f"/api/brewing/orders/{order.json()['brew_order_id']}", headers=admin_h).json()
    assert detail["lines"], "Lệnh nấu phải tự nạp được định mức NVL từ Công thức đang hiệu lực của dịch bia"
    line = detail["lines"][0]
    assert line["material_id"]
    assert "MALT" in line["material_name"].upper()
    assert line["qty_total"] == pytest.approx(40)


def test_bom_qty_not_scaled_by_planned_volume_hl(client, admin_h):
    """Công thức khai báo định mức CHO ĐÚNG 1 MẺ — Nhu cầu 1 mẻ phải bằng nguyên văn số
    lượng khai báo trong công thức (KHÔNG scale theo planned_volume_hl/base_qty), Nhu cầu
    Tổng mẻ = Nhu cầu 1 mẻ x Số mẻ kế hoạch. Trước đây bị scale sai theo tỉ lệ thể tích,
    ra số lượng/mẻ ảo (vd 0.444 kg) không khớp công thức thật."""
    beer_type_id = _a_beer_type(client, admin_h, "NOSCALE")
    product_id = _a_product(client, admin_h, "NOSCALE", beer_type_id)
    _, version_id = _an_effective_recipe_version(client, admin_h, beer_type_id, product_id, "CT-NOSCALE", qty=15)

    for planned_volume_hl in (5, 111, 1000):
        order = client.post("/api/brewing/orders", headers=admin_h,
                            json={"order_code": f"LN-NOSCALE-{planned_volume_hl}", "product_id": product_id,
                                  "recipe_version_id": version_id,
                                  "planned_batch_count": 3, "planned_volume_hl": planned_volume_hl,
                                  "auto_from_bom": True})
        assert order.status_code == 201, order.text
        detail = client.get(f"/api/brewing/orders/{order.json()['brew_order_id']}", headers=admin_h).json()
        line = detail["lines"][0]
        assert line["qty_per_batch"] == pytest.approx(15), (
            f"Nhu cầu 1 mẻ phải luôn = 15 (nguyên văn BOM), không phụ thuộc planned_volume_hl={planned_volume_hl}")
        assert line["qty_total"] == pytest.approx(45), "Nhu cầu Tổng mẻ = 15 x 3 mẻ = 45"
