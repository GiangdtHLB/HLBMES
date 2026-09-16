"""batch_dispense_summary() (bảng Định mức↔Thực tế ở "Cấp liệu cho mẻ") phải hiện đúng "Mã lô"
cho vật tư tiêu thụ qua endpoint "Tiêu thụ lô" (POST /batches/{id}/consume) trực tiếp — KHÔNG chỉ
vật tư đi qua dispense()/backflush()/adjust_actual (DispenseLine). Bug thực tế đã gặp (yêu cầu
người dùng 2026-09-15): vật tư 2NC14 "có mã lô nhưng khi đưa vào cấp liệu lại không hiện mã lô
ra, thực tế có trừ đúng mã lô đó" — vì lot_info trước đây CHỈ đọc từ DispenseLine, rỗng hoàn toàn
với đường /consume trực tiếp dù GenealogyEdge(relation=consume) đã ghi đúng lô."""

import os
import tempfile
from datetime import timedelta

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["MES_DATABASE_URL"] = f"sqlite:///{_TMP.name}"
os.environ["MES_DEV_HEADER_AUTH"] = "0"
os.environ["MES_RL_ENABLED"] = "0"
os.environ["MES_ADMIN_PASSWORD"] = "AdminTest123"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import seed as seed_mod
from app.common import utcnow


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


def _clear_seed_batch_9002(client, admin_h):
    """seed.py cố tình để mẻ demo "9002" ở trạng thái "running, chưa cấp liệu lần nào" — với điều
    kiện cấp liệu mới (2026-09-15, _assert_dispensable), mẻ test tạo SAU 9002 sẽ bị chặn oan."""
    batches = client.get("/api/batches", headers=admin_h).json()
    b9002 = next((b for b in batches if b.get("batch_code") == "9002"), None)
    if b9002 and b9002["state"] in ("running", "held"):
        r = client.post(f"/api/batches/{b9002['batch_id']}/transition", headers=admin_h,
                        json={"target": "cancelled"})
        assert r.status_code == 200, r.text


def test_summary_shows_lot_code_for_direct_consume(client, admin_h):
    _clear_seed_batch_9002(client, admin_h)

    mat = client.post("/api/materials", headers=admin_h,
                      json={"code": "SUM-CONS01", "name": "Vật tư summary consume", "uom": "kg"})
    assert mat.status_code == 201, mat.text
    material_id, code = mat.json()["material_id"], mat.json()["code"]

    lot = client.post("/api/warehouse/receive", headers=admin_h, json={
        "material_id": material_id, "quantity": 20, "uom": "kg", "location": "Kho phân xưởng"})
    assert lot.status_code == 200, lot.text
    lot_code = lot.json()["lot_code"] if "lot_code" in lot.json() else None
    lot_id = lot.json()["lot_id"]
    if not lot_code:
        lot_code = next(l["lot_code"] for l in client.get("/api/lots", headers=admin_h).json()
                        if l["lot_id"] == lot_id)

    bt = client.post("/api/beer-types", headers=admin_h,
                     json={"code": "BT-SUMCONS", "name": "Loại SUM consume"})
    assert bt.status_code == 201, bt.text
    recipe = client.post("/api/recipes", headers=admin_h,
                         json={"code": "CT-SUMCONS", "name": "Recipe SUM consume",
                              "beer_type_id": bt.json()["beer_type_id"]})
    assert recipe.status_code == 201, recipe.text
    prod = client.post("/api/products", headers=admin_h,
                       json={"code": "PRD-SUMCONS", "name": "Dich SUM consume", "uom": "L",
                            "beer_type_id": bt.json()["beer_type_id"]})
    assert prod.status_code == 201, prod.text
    v = client.post(f"/api/recipes/{recipe.json()['recipe_id']}/versions", headers=admin_h,
                    json={"base_qty": 100, "base_uom": "L", "product_id": prod.json()["product_id"],
                         "materials": [{"material_code": code, "qty": 5, "uom": "kg", "tol_pct": 5}]})
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
    for target in ("ready", "running"):
        t = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": target})
        assert t.status_code == 200, t.text

    r = client.post(f"/api/batches/{batch_id}/consume", headers=admin_h,
                    json={"lot_id": lot_id, "quantity": 5})
    assert r.status_code == 200, r.text

    summary = client.get(f"/api/dispense/{batch_id}/summary", headers=admin_h)
    assert summary.status_code == 200, summary.text
    row = next(l for l in summary.json() if l["material_code"] == code)
    assert row["actual"] == 5.0
    assert row["lot_codes"] == [lot_code]
    assert row["fifo_ok"] is None   # không đi qua dispense() -> không suy đoán được FIFO
