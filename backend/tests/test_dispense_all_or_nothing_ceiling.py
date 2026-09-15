"""Tái hiện đúng lỗi đã sửa (audit rủi ro 2026-09-15): trước đây `consume_lot()` tự `commit()`
ngay sau MỖI lô trong 1 phiếu Cấp liệu nhiều dòng — nếu dòng SAU trong CÙNG phiếu vượt trần
định mức BOM (kiểm tra này CHỈ có ở pha THỰC THI, không có ở pha LẬP KẾ HOẠCH nên không bị chặn
sớm), dòng TRƯỚC đã trừ tồn + commit thật, trong khi dispense() báo lỗi 409 "không cấp liệu
dòng nào cả". Sau khi sửa (consume_lot(commit=False) trong _execute_plan, dispense() chỉ commit
1 lần ở cuối), phiếu phải rollback SẠCH — lô không mất đi kg nào, không có phiếu cấp liệu nào
được tạo."""

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


def test_dispense_rolls_back_fully_when_a_later_line_exceeds_bom_ceiling(client, admin_h):
    mat = client.post("/api/materials", headers=admin_h,
                      json={"code": "AON-CEIL-01", "name": "Vật tư AON ceiling", "uom": "kg"})
    assert mat.status_code == 201, mat.text
    material_id, code = mat.json()["material_id"], mat.json()["code"]

    bt = client.post("/api/beer-types", headers=admin_h,
                     json={"code": "BT-AONCEIL", "name": "Loại AON ceiling"})
    assert bt.status_code == 201, bt.text
    recipe = client.post("/api/recipes", headers=admin_h,
                         json={"code": "CT-AONCEIL", "name": "Recipe AON ceiling",
                              "beer_type_id": bt.json()["beer_type_id"]})
    assert recipe.status_code == 201, recipe.text
    prod = client.post("/api/products", headers=admin_h,
                       json={"code": "PRD-AONCEIL", "name": "Dich AON ceiling", "uom": "L",
                            "beer_type_id": bt.json()["beer_type_id"]})
    assert prod.status_code == 201, prod.text
    # Định mức 10kg, dung sai 5% -> trần = 10.5kg cho 1 mẻ.
    v = client.post(f"/api/recipes/{recipe.json()['recipe_id']}/versions", headers=admin_h,
                    json={"base_qty": 100, "base_uom": "L", "product_id": prod.json()["product_id"],
                         "materials": [{"material_code": code, "qty": 10, "uom": "kg", "tol_pct": 5}]})
    assert v.status_code == 201, v.text
    version_id = v.json()["version_id"]
    for target in ("review", "approved", "effective"):
        t = client.post(f"/api/recipes/versions/{version_id}/transition", headers=admin_h,
                        json={"target": target})
        assert t.status_code == 200, t.text

    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": version_id,
                         "planned_qty": 100, "allow_shortage": True})
    assert b.status_code == 201, b.text
    batch_id = b.json()["batch_id"]

    lot = client.post("/api/warehouse/receive", headers=admin_h, json={
        "material_id": material_id, "quantity": 20, "uom": "kg", "location": "Kho phân xưởng"})
    assert lot.status_code == 200, lot.text
    lot_id = lot.json()["lot_id"]

    # 1 phiếu, 2 dòng CÙNG vật tư: 8kg (trong trần) + 5kg (8+5=13kg > 10.5kg trần) -> pha lập kế
    # hoạch (chỉ xét đủ tồn 20kg >= 13kg) cho qua cả 2 dòng; trần BOM chỉ bị phát hiện lúc THỰC
    # THI dòng thứ 2.
    disp = client.post(f"/api/dispense/{batch_id}", headers=admin_h, json={
        "lines": [{"material_code": code, "quantity": 8}, {"material_code": code, "quantity": 5}],
    })
    assert disp.status_code == 409, disp.text
    assert "Vượt định mức BOM" in disp.json()["detail"]

    # Lô KHÔNG được trừ dù dòng 1 (8kg) tự nó nằm trong trần và đã "thực thi" trước khi dòng 2
    # bị chặn -> phải rollback sạch, không còn kg nào bị trừ oan.
    lots = {l["lot_id"]: l["quantity"] for l in client.get("/api/lots", headers=admin_h).json()}
    assert lots[lot_id] == 20.0

    # KHÔNG có phiếu cấp liệu nào được tạo (Dispense/DispenseLine đều phải rollback theo).
    hist = client.get(f"/api/dispense?batch_id={batch_id}", headers=admin_h).json()
    assert hist == []

    # Định mức↔Thực tế phải thấy Thực tế = 0 cho vật tư này (chưa cấp gì thật).
    bom = client.get(f"/api/batches/{batch_id}/bom", headers=admin_h).json()
    line = next((l for l in bom["lines"] if l["material_code"] == code), None)
    assert line is not None
    assert line["actual"] == 0.0
