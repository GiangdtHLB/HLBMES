"""Test: Lệnh nấu tách SL thực xuất theo 2 nguồn (Kho công ty / Kho phân xưởng) — cột mới
"SL lấy tại Kho công ty" / "SL lấy tại Kho phân xưởng" trên preview "Xem NVL" + persist vào
BrewOrderMaterialLine.qty_from_company/qty_from_workshop khi tạo/sửa lệnh nấu (xem
services/brew_order.py::_suggest_qty_split, _apply_qty_split_override).

Nguyên tắc gợi ý: ưu tiên dùng hết tồn đang có tại Kho phân xưởng (tối đa bằng đúng Nhu cầu
Tổng mẻ), phần còn thiếu lấy tại Kho công ty. Người lập lệnh nấu có thể sửa lại qua
material_qty_overrides (key = str(seq) của dòng NVL trong Công thức) — override đè lên gợi ý,
chỉ áp field nào thực sự có giá trị (không None)."""

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


def _a_material_with_stock(client, admin_h, code, qty_company=0, qty_workshop=0):
    m = client.post("/api/materials", headers=admin_h, json={"code": code, "name": f"Vật tư {code}", "uom": "kg"})
    assert m.status_code == 201, m.text
    material_id = m.json()["material_id"]
    if qty_company:
        r = client.post("/api/warehouse/receive", headers=admin_h,
                        json={"lot_code": f"LOT-{code}-CTY", "material_id": material_id,
                              "quantity": qty_company, "uom": "kg", "location": "Kho công ty"})
        assert r.status_code == 200, r.text
    if qty_workshop:
        r = client.post("/api/warehouse/receive", headers=admin_h,
                        json={"lot_code": f"LOT-{code}-PX", "material_id": material_id,
                              "quantity": qty_workshop, "uom": "kg", "location": "Kho phân xưởng"})
        assert r.status_code == 200, r.text
    return material_id


def _a_product(client, headers):
    suffix = new_id()[:8]
    bt = client.post("/api/beer-types", headers=headers, json={"code": f"BT-{suffix}", "name": f"Loại {suffix}"})
    assert bt.status_code == 201, bt.text
    r = client.post("/api/products", headers=headers,
                    json={"code": f"PRD-{suffix}", "name": f"Dịch test {suffix}", "uom": "L",
                          "beer_type_id": bt.json()["beer_type_id"]})
    assert r.status_code == 201, r.text
    return r.json()["product_id"]


def _activate_recipe_version(client, headers, version_id):
    """Mirror seed.py's admin/ENG/QA transition chain — admin bỏ qua role+SoD (xem
    security.py::require_role/enforce_sod) nên chỉ cần gọi transition thẳng 3 bước, không cần
    chữ ký điện tử (change-approve) cho mục đích test thuần logic BOM."""
    for target in ("review", "approved", "effective"):
        r = client.post(f"/api/recipes/versions/{version_id}/transition", headers=headers, json={"target": target})
        assert r.status_code == 200, r.text


def _a_recipe_version(client, headers, product_id, material_code, qty):
    products = client.get("/api/products", headers=headers).json()
    beer_type_id = next(p["beer_type_id"] for p in products if p["product_id"] == product_id)
    r = client.post("/api/recipes", headers=headers,
                    json={"code": f"CT-{new_id()[:8]}", "name": "Test recipe", "beer_type_id": beer_type_id})
    assert r.status_code == 201, r.text
    recipe = r.json()
    v = client.post(f"/api/recipes/{recipe['recipe_id']}/versions", headers=headers,
                    json={"product_id": product_id, "base_qty": 1000, "base_uom": "L",
                          "materials": [{"material_code": material_code, "qty": qty, "uom": "kg"}]})
    assert v.status_code == 201, v.text
    version = v.json()
    _activate_recipe_version(client, headers, version["version_id"])
    return version


def _create_order(client, admin_h, product_id, recipe_version_id, batch_count=2, overrides=None):
    r = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": f"LN-QS-{new_id()[:8]}", "product_id": product_id, "recipe_version_id": recipe_version_id,
        "planned_batch_count": batch_count, "planned_volume_hl": 100, "volume_tolerance_hl": 0,
        "auto_from_bom": True, "lines": [],
        "material_qty_overrides": overrides or {},
    })
    assert r.status_code == 201, r.text
    return r.json()["brew_order_id"]


def test_preview_suggests_split_using_workshop_stock_first(client, admin_h):
    mat_code = f"MAT-QS1-{new_id()[:6]}"
    material_id = _a_material_with_stock(client, admin_h, mat_code, qty_company=1000, qty_workshop=15)
    product_id = _a_product(client, admin_h)
    version = _a_recipe_version(client, admin_h, product_id, mat_code, qty=10)  # 10kg/mẻ

    preview = client.get("/api/brewing/orders/bom-preview", headers=admin_h,
                         params={"recipe_version_id": version["version_id"], "planned_batch_count": 2,
                                 "planned_volume_hl": 100}).json()
    line = next(l for l in preview if not l["is_header"])
    assert line["qty_total"] == pytest.approx(20)  # 10kg x 2 mẻ
    # Tồn phân xưởng (15) < nhu cầu (20) -> lấy hết 15 tại phân xưởng, 5 còn thiếu lấy công ty.
    assert line["qty_from_workshop"] == pytest.approx(15)
    assert line["qty_from_company"] == pytest.approx(5)
    assert material_id  # tránh unused


def test_preview_all_from_workshop_when_stock_covers_full_demand(client, admin_h):
    mat_code = f"MAT-QS2-{new_id()[:6]}"
    _a_material_with_stock(client, admin_h, mat_code, qty_company=1000, qty_workshop=100)
    product_id = _a_product(client, admin_h)
    version = _a_recipe_version(client, admin_h, product_id, mat_code, qty=10)

    preview = client.get("/api/brewing/orders/bom-preview", headers=admin_h,
                         params={"recipe_version_id": version["version_id"], "planned_batch_count": 2,
                                 "planned_volume_hl": 100}).json()
    line = next(l for l in preview if not l["is_header"])
    # Tồn phân xưởng (100) > nhu cầu (20) -> KHÔNG gợi ý lấy dư, chỉ lấy đúng 20, công ty = 0.
    assert line["qty_from_workshop"] == pytest.approx(20)
    assert line["qty_from_company"] == pytest.approx(0)


def test_preview_all_from_company_when_no_workshop_stock(client, admin_h):
    mat_code = f"MAT-QS3-{new_id()[:6]}"
    _a_material_with_stock(client, admin_h, mat_code, qty_company=1000, qty_workshop=0)
    product_id = _a_product(client, admin_h)
    version = _a_recipe_version(client, admin_h, product_id, mat_code, qty=10)

    preview = client.get("/api/brewing/orders/bom-preview", headers=admin_h,
                         params={"recipe_version_id": version["version_id"], "planned_batch_count": 2,
                                 "planned_volume_hl": 100}).json()
    line = next(l for l in preview if not l["is_header"])
    assert line["qty_from_workshop"] == pytest.approx(0)
    assert line["qty_from_company"] == pytest.approx(20)


def test_create_order_persists_suggested_split_when_no_override(client, admin_h):
    mat_code = f"MAT-QS4-{new_id()[:6]}"
    _a_material_with_stock(client, admin_h, mat_code, qty_company=1000, qty_workshop=15)
    product_id = _a_product(client, admin_h)
    version = _a_recipe_version(client, admin_h, product_id, mat_code, qty=10)

    order_id = _create_order(client, admin_h, product_id, version["version_id"], batch_count=2)
    detail = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    line = next(l for l in detail["lines"] if not l["is_header"])
    assert line["qty_from_workshop"] == pytest.approx(15)
    assert line["qty_from_company"] == pytest.approx(5)


def test_create_order_override_replaces_suggestion(client, admin_h):
    mat_code = f"MAT-QS5-{new_id()[:6]}"
    _a_material_with_stock(client, admin_h, mat_code, qty_company=1000, qty_workshop=15)
    product_id = _a_product(client, admin_h)
    version = _a_recipe_version(client, admin_h, product_id, mat_code, qty=10)

    # seq=0 (dòng NVL duy nhất trong công thức) — người lập tự sửa lại thành lấy hết ở công ty.
    order_id = _create_order(client, admin_h, product_id, version["version_id"], batch_count=2,
                             overrides={"0": {"qty_from_company": 20, "qty_from_workshop": 0}})
    detail = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    line = next(l for l in detail["lines"] if not l["is_header"])
    assert line["qty_from_company"] == pytest.approx(20)
    assert line["qty_from_workshop"] == pytest.approx(0)


def test_create_order_partial_override_keeps_other_field_as_suggestion(client, admin_h):
    mat_code = f"MAT-QS6-{new_id()[:6]}"
    _a_material_with_stock(client, admin_h, mat_code, qty_company=1000, qty_workshop=15)
    product_id = _a_product(client, admin_h)
    version = _a_recipe_version(client, admin_h, product_id, mat_code, qty=10)

    # Chỉ sửa qty_from_company, để qty_from_workshop null -> vẫn giữ gợi ý (15).
    order_id = _create_order(client, admin_h, product_id, version["version_id"], batch_count=2,
                             overrides={"0": {"qty_from_company": 8}})
    detail = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    line = next(l for l in detail["lines"] if not l["is_header"])
    assert line["qty_from_company"] == pytest.approx(8)
    assert line["qty_from_workshop"] == pytest.approx(15)  # gợi ý gốc, không bị override đụng tới


def test_update_order_applies_new_override(client, admin_h):
    mat_code = f"MAT-QS7-{new_id()[:6]}"
    _a_material_with_stock(client, admin_h, mat_code, qty_company=1000, qty_workshop=15)
    product_id = _a_product(client, admin_h)
    version = _a_recipe_version(client, admin_h, product_id, mat_code, qty=10)

    order_id = _create_order(client, admin_h, product_id, version["version_id"], batch_count=2)
    r = client.put(f"/api/brewing/orders/{order_id}", headers=admin_h, json={
        "order_code": f"LN-QS-UPD-{new_id()[:6]}", "product_id": product_id, "recipe_version_id": version["version_id"],
        "planned_batch_count": 2, "planned_volume_hl": 100, "volume_tolerance_hl": 0,
        "auto_from_bom": True, "lines": [],
        "material_qty_overrides": {"0": {"qty_from_company": 20, "qty_from_workshop": 0}},
    })
    assert r.status_code == 200, r.text
    detail = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    line = next(l for l in detail["lines"] if not l["is_header"])
    assert line["qty_from_company"] == pytest.approx(20)
    assert line["qty_from_workshop"] == pytest.approx(0)
