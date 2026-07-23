"""Test NVL lọc (FilterMaterialUsage) — nguyên liệu thực tế dùng cho 1 mẻ lọc, trừ tồn kho
Kho phân xưởng thật qua warehouse.issue()/undo_issue(), mirror BrewMaterialUsage
(test_traceability_brew_chain.py/test_lot_record.py chỉ test đường free-text, chưa có test
riêng cho đường lot_id thật — file này lấp khoảng đó, đồng thời test cho cả Lọc)."""

import os
import tempfile

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["MES_DATABASE_URL"] = f"sqlite:///{_TMP.name}"
os.environ["MES_DEV_HEADER_AUTH"] = "0"
os.environ["MES_RL_ENABLED"] = "0"
os.environ["MES_ADMIN_PASSWORD"] = "AdminTest123"

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.brewing import FilterRecord
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


@pytest.fixture(scope="module")
def vanhanh_h(client):
    return _login(client, "vanhanh", "123456")


def _a_brew_order(client, admin_h, order_code):
    r = client.post("/api/brewing/orders", headers=admin_h, json={"order_code": order_code, "auto_from_bom": False, "planned_volume_hl": 100})
    assert r.status_code == 201, r.text
    return r.json()["brew_order_id"]


def _setup_ferment(client, admin_h, vanhanh_h, suffix):
    order_id = _a_brew_order(client, admin_h, f"LN-{suffix}")
    b = client.post("/api/brewing/brews", headers=vanhanh_h,
                    json={"brew_code": f"BR-{suffix}", "wort_type": "Dịch test", "volume_hl": 100,
                          "lm_code": f"LM-{suffix}", "tank_lm": f"T-{suffix}", "brew_order_id": order_id})
    assert b.status_code == 201, b.text
    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment = next(f for f in ferments if f["lm_code"] == f"LM-{suffix}")
    ok = client.post(f"/api/brewing/ferments/{ferment['ferment_id']}/approve", headers=admin_h)
    assert ok.status_code == 200, ok.text
    return ferment["ferment_id"]


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


def _a_filter_order(client, admin_h, order_code, ferment_ids, lines=None):
    payload = {"order_code": order_code, "blend_mode": "khong_phoi", "tank_ferment_ids": ferment_ids,
               "planned_volume_hl": 1000.0}
    if lines is not None:
        payload["lines"] = lines
    r = client.post("/api/brewing/filter-orders", headers=admin_h, json=payload)
    assert r.status_code == 201, r.text
    return r.json()["filter_order_id"]


def _lot_id_by_code(client, admin_h, lot_code):
    lots = client.get("/api/lots", headers=admin_h).json()
    return next(l for l in lots if l["lot_code"] == lot_code)


def _build_filter(client, admin_h, vanhanh_h, suffix, lines=None):
    ferment_id = _setup_ferment(client, admin_h, vanhanh_h, suffix)
    order_id = _a_filter_order(client, admin_h, f"LOC-{suffix}", [ferment_id], lines=lines)
    f = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": f"FL-{suffix}", "beer_type": "Bia test", "wort_type": "Dịch test",
                          "filter_order_id": order_id, "to_bbt": f"BBT-{suffix}"})
    assert f.status_code == 201, f.text
    return f.json()["filter_id"], order_id


def test_add_filter_material_from_workshop_lot_deducts_stock_and_sets_has_nvl(client, admin_h, vanhanh_h):
    suffix = "FMU01"
    material_id = _a_material_with_stock(client, admin_h, f"MAT-{suffix}", qty_workshop=50)
    filter_id, order_id = _build_filter(client, admin_h, vanhanh_h, suffix)

    lot = _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix}-PX")
    assert lot["quantity"] == 50

    add = client.post(f"/api/brewing/filters/{filter_id}/materials", headers=vanhanh_h,
                      json={"lot_id": lot["lot_id"], "quantity": 12, "uom": "kg"})
    assert add.status_code == 201, add.text
    usage = add.json()
    assert usage["material_name"] == f"Vật tư MAT-{suffix}"
    assert usage["lot_pm"] == f"LOT-MAT-{suffix}-PX"
    assert usage["lot_id"] == lot["lot_id"]
    assert usage["movement_id"]

    lot_after = _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix}-PX")
    assert lot_after["quantity"] == 38

    rows = client.get("/api/brewing/filters", headers=admin_h).json()
    row = next(r for r in rows if r["filter_id"] == filter_id)
    assert row["filter_order_id"] == order_id  # fix: list_filters phải trả filter_order_id

    db = SessionLocal()
    try:
        f = db.get(FilterRecord, filter_id)
        assert f.has_nvl is True
    finally:
        db.close()

    listed = client.get(f"/api/brewing/filters/{filter_id}/materials", headers=admin_h).json()
    assert len(listed) == 1 and listed[0]["usage_id"] == usage["usage_id"]


def test_add_filter_material_blocks_non_workshop_lot(client, admin_h, vanhanh_h):
    suffix = "FMU02"
    material_id = _a_material_with_stock(client, admin_h, f"MAT-{suffix}", qty_company=20)
    filter_id, _ = _build_filter(client, admin_h, vanhanh_h, suffix)

    lot = _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix}-CTY")
    blocked = client.post(f"/api/brewing/filters/{filter_id}/materials", headers=vanhanh_h,
                          json={"lot_id": lot["lot_id"], "quantity": 5})
    assert blocked.status_code == 409, blocked.text
    assert "kho phân xưởng" in blocked.json()["detail"].lower()


def test_delete_filter_material_restores_stock(client, admin_h, vanhanh_h):
    suffix = "FMU03"
    _a_material_with_stock(client, admin_h, f"MAT-{suffix}", qty_workshop=30)
    filter_id, _ = _build_filter(client, admin_h, vanhanh_h, suffix)
    lot = _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix}-PX")

    add = client.post(f"/api/brewing/filters/{filter_id}/materials", headers=vanhanh_h,
                      json={"lot_id": lot["lot_id"], "quantity": 10})
    assert add.status_code == 201, add.text
    usage_id = add.json()["usage_id"]
    assert _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix}-PX")["quantity"] == 20

    delete = client.delete(f"/api/brewing/filters/{filter_id}/materials/{usage_id}", headers=vanhanh_h)
    assert delete.status_code == 204, delete.text
    assert _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix}-PX")["quantity"] == 30

    listed = client.get(f"/api/brewing/filters/{filter_id}/materials", headers=admin_h).json()
    assert listed == []


def test_delete_filter_cascades_undo_filter_material(client, admin_h, vanhanh_h):
    suffix = "FMU04"
    _a_material_with_stock(client, admin_h, f"MAT-{suffix}", qty_workshop=15)
    filter_id, _ = _build_filter(client, admin_h, vanhanh_h, suffix)
    lot = _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix}-PX")

    add = client.post(f"/api/brewing/filters/{filter_id}/materials", headers=vanhanh_h,
                      json={"lot_id": lot["lot_id"], "quantity": 6})
    assert add.status_code == 201, add.text
    assert _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix}-PX")["quantity"] == 9

    delete = client.delete(f"/api/brewing/filters/{filter_id}", headers=vanhanh_h)
    assert delete.status_code == 204, delete.text
    assert _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix}-PX")["quantity"] == 15


def test_filter_material_suggestion_source_from_filter_order_lines(client, admin_h, vanhanh_h):
    """Không test UI (frontend đọc trực tiếp GET /filter-orders/{id} để gợi ý) — test ở đây
    xác nhận endpoint đó trả đúng lines cho modal dùng làm gợi ý số lượng."""
    suffix = "FMU05"
    material_id = _a_material_with_stock(client, admin_h, f"MAT-{suffix}", qty_workshop=40)
    filter_id, order_id = _build_filter(client, admin_h, vanhanh_h, suffix,
                                        lines=[{"material_id": material_id, "quantity": 7}])
    order = client.get(f"/api/brewing/filter-orders/{order_id}", headers=admin_h).json()
    assert len(order["lines"]) == 1
    assert order["lines"][0]["material_id"] == material_id
    assert order["lines"][0]["quantity"] == 7
