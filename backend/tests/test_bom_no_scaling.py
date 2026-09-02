"""Test: định mức BOM (Định mức↔Thực tế/Kiểm tra tồn/Cấp liệu) cho 1 Mẻ sản xuất LUÔN là số
công thức đã khai cho "1 mẻ" (RecipeVersion.materials[].qty), KHÔNG scale theo tỉ lệ
batch.planned_qty / RecipeVersion.base_qty — mirror đúng cách "Lệnh nấu" tính "Nhu cầu 1 mẻ"
(services/brew_order.py::_build_group_line, không nhân hệ số nào).

Trước đây bom.py::factor_for nhân trực tiếp planned_qty (luôn đơn vị "hl", xem
services/batches.py::create_batch) với base_qty (thường khai bằng "L") mà KHÔNG quy đổi đơn vị
— vừa sai đơn vị vừa sai triết lý (planned_qty của 1 mẻ cụ thể không nên ảnh hưởng định mức/mẻ,
"mẻ" vốn đã là 1 đơn vị chuẩn theo công thức). Test này cố tình dùng base_qty (L) và planned_qty
(hl) LỆCH XA nhau (không phải cùng 1 con số như test_dispense_suggest.py/test_dispense_adjust.py
— vô tình che mất bug vì luôn planned_qty == base_qty, factor luôn = 1) để khẳng định định mức
KHÔNG đổi dù planned_qty là bao nhiêu.
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


def _new_material(client, admin_h, suffix):
    r = client.post("/api/materials", headers=admin_h,
                    json={"code": f"NOSC-{suffix}", "name": f"Vật tư no-scale {suffix}", "uom": "kg"})
    assert r.status_code == 201, r.text
    return r.json()["material_id"], r.json()["code"]


def _recipe_version(client, admin_h, suffix, material_code, qty, base_qty):
    bt = client.post("/api/beer-types", headers=admin_h,
                     json={"code": f"BT-NOSC-{suffix}", "name": f"Loại no-scale {suffix}"})
    assert bt.status_code == 201, bt.text
    r = client.post("/api/recipes", headers=admin_h,
                    json={"code": f"CT-NOSC-{suffix}", "name": "Test recipe no scaling",
                         "beer_type_id": bt.json()["beer_type_id"]})
    assert r.status_code == 201, r.text
    recipe_id = r.json()["recipe_id"]
    prod = client.post("/api/products", headers=admin_h,
                       json={"code": f"PRD-NOSC-{suffix}", "name": f"Dịch no-scale {suffix}", "uom": "L",
                            "beer_type_id": bt.json()["beer_type_id"]})
    assert prod.status_code == 201, prod.text
    # base_qty khai bằng L (quy mô chuẩn công thức, VD 50.000 L) — CỐ Ý khác đơn vị + khác con
    # số xa với planned_qty của mẻ (luôn "hl") để lộ rõ bug quy đổi/scale cũ nếu còn tồn tại.
    v = client.post(f"/api/recipes/{recipe_id}/versions", headers=admin_h,
                    json={"base_qty": base_qty, "base_uom": "L", "product_id": prod.json()["product_id"],
                         "materials": [{"material_code": material_code, "qty": qty, "uom": "kg", "tol_pct": 5}]})
    assert v.status_code == 201, v.text
    version_id = v.json()["version_id"]
    for target in ("review", "approved", "effective"):
        t = client.post(f"/api/recipes/versions/{version_id}/transition", headers=admin_h,
                        json={"target": target})
        assert t.status_code == 200, t.text
    return version_id


def _new_batch(client, admin_h, version_id, planned_qty, suffix, allow_shortage=True):
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": version_id,
                         "planned_qty": planned_qty,   # batch_code: để tự sinh (giờ bắt buộc số nguyên)
                         "allow_shortage": allow_shortage})
    assert b.status_code == 201, b.text
    return b.json()["batch_id"]


def test_bom_line_unaffected_by_planned_qty_vs_base_qty_mismatch(client, admin_h):
    """base_qty = 50.000 L (quy mô chuẩn), 2 mẻ planned_qty (hl) khác hẳn nhau (200hl và 1000hl,
    cũng khác hẳn 50.000) -> định mức "10kg" của công thức PHẢI giữ nguyên ở cả 2 mẻ, không
    bị chia/nhân theo planned_qty."""
    material_id, code = _new_material(client, admin_h, "BOM01")
    version_id = _recipe_version(client, admin_h, "BOM01", code, qty=10, base_qty=50000)

    batch_small = _new_batch(client, admin_h, version_id, planned_qty=200, suffix="BOM01A")
    batch_big = _new_batch(client, admin_h, version_id, planned_qty=1000, suffix="BOM01B")

    bom_small = client.get(f"/api/batches/{batch_small}/bom", headers=admin_h).json()
    bom_big = client.get(f"/api/batches/{batch_big}/bom", headers=admin_h).json()
    assert bom_small["lines"][0]["planned"] == 10.0
    assert bom_big["lines"][0]["planned"] == 10.0


def test_availability_check_unaffected_by_planned_qty(client, admin_h):
    material_id, code = _new_material(client, admin_h, "AVAIL01")
    version_id = _recipe_version(client, admin_h, "AVAIL01", code, qty=10, base_qty=50000)

    avail = client.get(
        f"/api/batches/availability?recipe_version_id={version_id}&planned_qty=200",
        headers=admin_h).json()
    assert avail["rows"][0]["required"] == 10.0

    avail2 = client.get(
        f"/api/batches/availability?recipe_version_id={version_id}&planned_qty=1000",
        headers=admin_h).json()
    assert avail2["rows"][0]["required"] == 10.0


def test_ceiling_and_actual_consumed_unaffected_by_planned_qty(client, admin_h):
    """Ngưỡng "vượt định mức BOM" khi Consume phải luôn là 10kg (+dung sai), không lệ thuộc
    planned_qty=200 (hl) của mẻ so với base_qty=50.000 (L) — trước đây do lỗi quy đổi đơn vị,
    hệ số ra 200/50000=0.004 khiến ngưỡng chỉ còn 0.042kg thay vì đúng 10.5kg (10kg +5% dung sai)."""
    material_id, code = _new_material(client, admin_h, "CEIL01")
    version_id = _recipe_version(client, admin_h, "CEIL01", code, qty=10, base_qty=50000)
    batch_id = _new_batch(client, admin_h, version_id, planned_qty=200, suffix="CEIL01")

    lot = client.post("/api/warehouse/receive", headers=admin_h, json={
        "material_id": material_id, "quantity": 50, "uom": "kg", "location": "Kho phân xưởng"})
    assert lot.status_code == 200, lot.text
    lot_id = lot.json()["lot_id"]

    ok = client.post(f"/api/batches/{batch_id}/consume", headers=admin_h,
                     json={"lot_id": lot_id, "quantity": 10.5})
    assert ok.status_code == 200, ok.text   # đúng bằng ngưỡng (10kg +5% dung sai) -> vẫn cho phép

    over = client.post(f"/api/batches/{batch_id}/consume", headers=admin_h,
                       json={"lot_id": lot_id, "quantity": 1})
    assert over.status_code == 409, over.text   # vượt ngưỡng thật -> chặn
    assert "Vượt định mức" in over.json()["detail"]
