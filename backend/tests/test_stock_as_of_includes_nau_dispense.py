"""Tồn kho phân xưởng "tính đến ngày X" (stock_on_hand_as_of/lot_on_hand_as_of) phải trừ đúng NVL
đã cấp cho mẻ Nấu — trước đây hoàn toàn KHÔNG trừ (Cấp liệu chỉ ghi GenealogyEdge consume, không
tạo StockMovement, xem services/dispense.py::consume_lot). Mốc trừ dùng `batch.start_at` ("Ngày
cấp") chứ không phải giờ bấm nút cấp liệu thật (yêu cầu người dùng 2026-09-15: "khi xem tồn kho
phân xưởng thì phải tính tồn trừ đi lượng đã xuất, tức là ngày cấp liệu"). Cũng kiểm tra
workshop_usage_history trả đúng `supply_date` (= batch.start_at cho Nấu)."""

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

from app.common import utcnow
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


def _clear_seed_batch_9002(client, admin_h):
    batches = client.get("/api/batches", headers=admin_h).json()
    b9002 = next((b for b in batches if b.get("batch_code") == "9002"), None)
    if b9002 and b9002["state"] in ("running", "held"):
        r = client.post(f"/api/batches/{b9002['batch_id']}/transition", headers=admin_h,
                        json={"target": "cancelled"})
        assert r.status_code == 200, r.text


def test_stock_as_of_reflects_nau_dispense_at_batch_start_at(client, admin_h):
    _clear_seed_batch_9002(client, admin_h)
    now = utcnow()

    mat = client.post("/api/materials", headers=admin_h,
                      json={"code": "ASOF-NAU01", "name": "Vật tư as-of Nấu", "uom": "kg"})
    assert mat.status_code == 201, mat.text
    material_id, code = mat.json()["material_id"], mat.json()["code"]

    recv = client.post("/api/warehouse/receive", headers=admin_h, json={
        "material_id": material_id, "quantity": 100, "uom": "kg", "location": "Kho phân xưởng",
        "received_at": (now - timedelta(hours=2)).isoformat()})
    assert recv.status_code == 200, recv.text
    lot_id = recv.json()["lot_id"]

    bt = client.post("/api/beer-types", headers=admin_h, json={"code": "BT-ASOFNAU", "name": "Loại as-of Nấu"})
    assert bt.status_code == 201, bt.text
    recipe = client.post("/api/recipes", headers=admin_h,
                         json={"code": "CT-ASOFNAU", "name": "Recipe as-of Nấu",
                              "beer_type_id": bt.json()["beer_type_id"]})
    assert recipe.status_code == 201, recipe.text
    prod = client.post("/api/products", headers=admin_h,
                       json={"code": "PRD-ASOFNAU", "name": "Dich as-of Nấu", "uom": "L",
                            "beer_type_id": bt.json()["beer_type_id"]})
    assert prod.status_code == 201, prod.text
    v = client.post(f"/api/recipes/{recipe.json()['recipe_id']}/versions", headers=admin_h,
                    json={"base_qty": 100, "base_uom": "L", "product_id": prod.json()["product_id"],
                         "materials": [{"material_code": code, "qty": 30, "uom": "kg", "tol_pct": 5}]})
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

    batch_start_at = now - timedelta(hours=1)
    s = client.post(f"/api/batches/{batch_id}/start", headers=admin_h,
                    json={"start_at": batch_start_at.isoformat()})
    assert s.status_code == 200, s.text

    # Cấp liệu THẬT bấm bây giờ (giờ tạo dòng = "now"), nhưng "Ngày cấp" (mốc trừ tồn) phải là
    # batch_start_at (1 giờ trước) — KHÁC giờ bấm nút thật.
    disp = client.post(f"/api/dispense/{batch_id}", headers=admin_h,
                       json={"lines": [{"material_code": code, "quantity": 30}]})
    assert disp.status_code == 200, disp.text

    # TRƯỚC batch_start_at (giữa lúc nhận kho và lúc mẻ bắt đầu) -> CHƯA trừ, còn nguyên 100kg.
    before = (batch_start_at - timedelta(minutes=1)).isoformat()
    stock_before = client.get("/api/warehouse/stock/as-of", headers=admin_h,
                              params={"as_of": before, "location": "Kho phân xưởng"}).json()
    row_before = next(r for r in stock_before if r["material_id"] == material_id)
    assert row_before["on_hand"] == 100.0

    lots_before = client.get("/api/warehouse/stock/as-of/lots", headers=admin_h,
                             params={"as_of": before, "location": "Kho phân xưởng"}).json()
    lot_before = next(l for l in lots_before if l["lot_id"] == lot_id)
    assert lot_before["quantity"] == 100.0

    # TỪ batch_start_at trở đi -> ĐÃ trừ 30kg, còn 70kg (dù giờ bấm nút cấp liệu thật là "now",
    # muộn hơn as_of này).
    at_start = batch_start_at.isoformat()
    stock_at_start = client.get("/api/warehouse/stock/as-of", headers=admin_h,
                                params={"as_of": at_start, "location": "Kho phân xưởng"}).json()
    row_at_start = next(r for r in stock_at_start if r["material_id"] == material_id)
    assert row_at_start["on_hand"] == 70.0

    lots_at_start = client.get("/api/warehouse/stock/as-of/lots", headers=admin_h,
                               params={"as_of": at_start, "location": "Kho phân xưởng"}).json()
    lot_at_start = next(l for l in lots_at_start if l["lot_id"] == lot_id)
    assert lot_at_start["quantity"] == 70.0

    # workshop_usage_history: dòng Nấu phải có supply_date == batch.start_at (KHÁC ts == giờ bấm
    # nút thật, "now") — 2 mốc lệch nhau đúng ~1 giờ trong test này.
    from datetime import datetime
    hist = client.get("/api/warehouse/workshop-usage-history?limit=2000", headers=admin_h).json()
    nau_row = next(r for r in hist if r["stage"] == "Nấu" and r["material_name"] == "Vật tư as-of Nấu")
    supply_dt = datetime.fromisoformat(nau_row["supply_date"].replace("Z", "+00:00"))
    ts_dt = datetime.fromisoformat(nau_row["ts"].replace("Z", "+00:00"))
    assert abs((supply_dt - batch_start_at).total_seconds()) < 5
    assert (ts_dt - supply_dt).total_seconds() > 1800   # ts (giờ bấm thật) muộn hơn supply_date ~1h
