"""Test: định mức BOM của 1 Mẻ sản xuất (BatchExecution) cho dòng "Nhóm vật tư thay thế" khai
kiểu member_qty (mỗi thành viên 1 định mức riêng, VD "Malt Pilsner HOẶC Malt Vienna") phải chỉ
tính đúng thành viên ĐÃ CHỌN cho Lệnh nấu (BrewOrder) mà mẻ đó gắn vào — KHÔNG cộng dồn với
thành viên khác công thức có khai nhưng lệnh KHÔNG chọn.

Trước đây services/bom.py::_expand_materials luôn tách TOÀN BỘ member_qty thành từng dòng BOM
độc lập, bất kể Lệnh nấu đã chọn thành viên nào lúc lập (BrewOrderMaterialLine.member_qty_snapshot)
— khiến "Cấp liệu"/"Định mức↔Thực tế" hiện cả thành viên KHÔNG áp dụng cho lệnh đó. Xem
services/bom.py::_selected_codes_for_group, services/brew_order.py::_build_group_line.
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


def _material_id(client, admin_h, code):
    materials = client.get("/api/materials", headers=admin_h).json()
    return next(m["material_id"] for m in materials if m["code"] == code)


@pytest.fixture(scope="module")
def malt_pils_id(client, admin_h):
    return _material_id(client, admin_h, "MALT-PILS")


@pytest.fixture(scope="module")
def malt_vienna_id(client, admin_h):
    return _material_id(client, admin_h, "MALT-VIENNA")


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
def group(client, admin_h, malt_pils_id, malt_vienna_id):
    r = client.post("/api/material-alt-groups", headers=admin_h, json={
        "code": "SELGRP-01", "name": "Malt Pilsner/Vienna (chọn 1)",
        "member_material_ids": [malt_pils_id, malt_vienna_id], "unit": "kg", "selection_mode": "single"})
    assert r.status_code == 201, r.text
    return r.json()


def _recipe_version_member_qty(client, admin_h, lager_product_id, group_code):
    recipes = client.get("/api/recipes", headers=admin_h).json()
    products = client.get("/api/products", headers=admin_h).json()
    lager = next(p for p in products if p["product_id"] == lager_product_id)
    recipe_id = next(r["recipe_id"] for r in recipes if r["beer_type_id"] == lager["beer_type_id"])
    v = client.post(f"/api/recipes/{recipe_id}/versions", headers=admin_h,
                    json={"product_id": lager_product_id, "base_qty": 1000, "base_uom": "L",
                         "materials": [{"alt_group_code": group_code, "uom": "kg",
                                       "member_qty": [{"material_code": "MALT-PILS", "qty": 20},
                                                     {"material_code": "MALT-VIENNA", "qty": 30}]}]})
    assert v.status_code == 201, v.text
    version_id = v.json()["version_id"]
    for target in ("review", "approved", "effective"):
        t = client.post(f"/api/recipes/versions/{version_id}/transition", headers=admin_h,
                        json={"target": target})
        assert t.status_code == 200, t.text
    return version_id


def _brew_order_with_selection(client, admin_h, lager_product_id, recipe_version_id, selected_codes):
    r = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": f"LN-SELBOM-{new_id()[:6]}", "product_id": lager_product_id,
        "recipe_version_id": recipe_version_id,
        "planned_batch_count": 1, "planned_volume_hl": 100, "volume_tolerance_hl": 0,
        "auto_from_bom": True, "lines": [],
        "material_qty_overrides": {"0": {"selected_material_codes": selected_codes}},
    })
    assert r.status_code == 201, r.text
    return r.json()["brew_order_id"]


def test_batch_bom_only_shows_member_selected_by_its_brew_order(
        client, admin_h, lager_product_id, group, malt_pils_id, malt_vienna_id):
    version_id = _recipe_version_member_qty(client, admin_h, lager_product_id, group["code"])
    brew_order_id = _brew_order_with_selection(client, admin_h, lager_product_id, version_id, ["MALT-PILS"])

    b = client.post("/api/batches", headers=admin_h, json={
        "order_id": brew_order_id, "recipe_version_id": version_id,
        "planned_qty": 100, "allow_shortage": True})   # batch_code: để tự sinh (giờ bắt buộc số nguyên)
    assert b.status_code == 201, b.text
    batch_id = b.json()["batch_id"]

    bom = client.get(f"/api/batches/{batch_id}/bom", headers=admin_h).json()
    assert len(bom["lines"]) == 1
    assert bom["lines"][0]["material_code"] == "MALT-PILS"
    assert bom["lines"][0]["planned"] == 20.0

    # MALT-VIENNA không thuộc lựa chọn của Lệnh nấu này -> không bị giới hạn bởi dòng BOM đó
    # (ceiling_for_material trả None -> không chặn khi tiêu thụ, khác cách xử lý cũ).
    lot = client.post("/api/warehouse/receive", headers=admin_h, json={
        "material_id": malt_vienna_id, "quantity": 100, "uom": "kg", "location": "Kho phân xưởng"})
    assert lot.status_code == 200, lot.text
    consume = client.post(f"/api/batches/{batch_id}/consume", headers=admin_h,
                          json={"lot_id": lot.json()["lot_id"], "quantity": 50})
    assert consume.status_code == 200, consume.text


def test_batch_bom_shows_different_member_for_different_brew_order(
        client, admin_h, lager_product_id, group, malt_pils_id, malt_vienna_id):
    """2 Lệnh nấu cùng công thức nhưng chọn thành viên KHÁC nhau -> 2 mẻ tương ứng phải hiện
    đúng thành viên của LỆNH của chính nó, không lẫn nhau."""
    version_id = _recipe_version_member_qty(client, admin_h, lager_product_id, group["code"])
    order_pils = _brew_order_with_selection(client, admin_h, lager_product_id, version_id, ["MALT-PILS"])
    order_vienna = _brew_order_with_selection(client, admin_h, lager_product_id, version_id, ["MALT-VIENNA"])

    b1 = client.post("/api/batches", headers=admin_h, json={
        "order_id": order_pils, "recipe_version_id": version_id,
        "planned_qty": 100, "allow_shortage": True}).json()
    b2 = client.post("/api/batches", headers=admin_h, json={
        "order_id": order_vienna, "recipe_version_id": version_id,
        "planned_qty": 100, "allow_shortage": True}).json()

    bom1 = client.get(f"/api/batches/{b1['batch_id']}/bom", headers=admin_h).json()
    bom2 = client.get(f"/api/batches/{b2['batch_id']}/bom", headers=admin_h).json()
    assert bom1["lines"][0]["material_code"] == "MALT-PILS"
    assert bom2["lines"][0]["material_code"] == "MALT-VIENNA"


def test_availability_preview_respects_order_selection_when_order_id_given(
        client, admin_h, lager_product_id, group):
    version_id = _recipe_version_member_qty(client, admin_h, lager_product_id, group["code"])
    brew_order_id = _brew_order_with_selection(client, admin_h, lager_product_id, version_id, ["MALT-VIENNA"])

    with_order = client.get(
        f"/api/batches/availability?recipe_version_id={version_id}&planned_qty=100&order_id={brew_order_id}",
        headers=admin_h).json()
    assert len(with_order["rows"]) == 1
    assert with_order["rows"][0]["material_code"] == "MALT-VIENNA"

    # Không truyền order_id -> xem trước KHÔNG lọc gì (giữ nguyên toàn bộ thành viên khả dụng).
    without_order = client.get(
        f"/api/batches/availability?recipe_version_id={version_id}&planned_qty=100",
        headers=admin_h).json()
    assert {r["material_code"] for r in without_order["rows"]} == {"MALT-PILS", "MALT-VIENNA"}
