"""Test NVL dùng cho Lô lọc (BatchFilterLotMaterialUsage, mới) — mirror test_filter_material_usage.py
(module Nấu-Lọc-Chiết cũ) cho pipeline "Mẻ SX", CỘNG THÊM enforcement mới: chọn lô KHÁC lô FIFO
cũ nhất bắt buộc ghi lý do (áp dụng cho CẢ BatchFilterLotMaterialUsage lẫn BatchPackLotMaterialUsage
đã có sẵn — yêu cầu người dùng 2026-09-01).
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


def _a_workshop_lot(client, admin_h, material_id, lot_code, qty):
    r = client.post("/api/warehouse/receive", headers=admin_h,
                    json={"lot_code": lot_code, "material_id": material_id,
                          "quantity": qty, "uom": "kg", "location": "Kho phân xưởng"})
    assert r.status_code == 200, r.text
    return r


def _lot_id_by_code(client, admin_h, lot_code):
    lots = client.get("/api/lots", headers=admin_h).json()
    return next(l for l in lots if l["lot_code"] == lot_code)


def _make_batch_tank(client, admin_h, batch_code, tank_code):
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(x for x in vers if x["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                          "batch_code": batch_code, "planned_qty": 1000, "allow_shortage": True})
    assert b.status_code == 201, b.text
    batch_id = b.json()["batch_id"]
    for target in ("ready", "running"):
        r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": target})
        assert r.status_code == 200, r.text
    aq = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": 1000})
    assert aq.status_code == 200, aq.text
    fin = client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={})
    assert fin.status_code == 200, fin.text
    r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "completed"})
    assert r.status_code == 200, r.text
    t = client.post("/api/batch-tanks", headers=admin_h,
                    json={"batch_ids": [batch_id], "tank_code": tank_code})
    assert t.status_code == 201, t.text
    return t.json()


def _make_filter_lot(client, admin_h, suffix):
    # batch_code giờ bắt buộc số nguyên (2026-09-02) — bỏ trống để tự sinh, suffix (không phải
    # số) chỉ dùng cho tank_code (tự do định dạng).
    tank = _make_batch_tank(client, admin_h, None, f"TANK-{suffix}")
    order = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": f"LOC-{suffix}",
        "sources": [{"source_type": "tank", "source_tank_id": tank["tank_id"], "planned_v_dich_hl": 900}],
    })
    assert order.status_code == 201, order.text
    bbt = client.post("/api/lines", headers=admin_h,
                      json={"code": f"BBT-{suffix}", "name": f"Tank thành phẩm {suffix}", "kind": "tank_bbt"})
    assert bbt.status_code == 201, bbt.text
    fl = client.post(f"/api/batch-filter-orders/{order.json()['order_id']}/filter-lots", headers=admin_h,
                     json={"filter_lot_code": f"FLOT-{suffix}", "to_bbt": bbt.json()["code"]})
    assert fl.status_code == 201, fl.text
    return fl.json()["filter_lot_id"]


def test_add_filter_lot_material_from_workshop_lot_deducts_stock(client, admin_h):
    suffix = "FLMU01"
    material_id = _a_material_with_stock(client, admin_h, f"MAT-{suffix}", qty_workshop=50)
    filter_lot_id = _make_filter_lot(client, admin_h, suffix)
    lot = _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix}-PX")

    add = client.post(f"/api/batch-filter-lots/{filter_lot_id}/materials", headers=admin_h,
                      json={"lot_id": lot["lot_id"], "quantity": 12, "uom": "kg"})
    assert add.status_code == 201, add.text
    usage = add.json()
    assert usage["material_name"] == f"Vật tư MAT-{suffix}"
    assert usage["lot_pm"] == f"LOT-MAT-{suffix}-PX"
    assert usage["fifo_ok"] is True
    assert usage["movement_id"]

    assert _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix}-PX")["quantity"] == 38

    listed = client.get(f"/api/batch-filter-lots/{filter_lot_id}/materials", headers=admin_h).json()
    assert len(listed) == 1 and listed[0]["usage_id"] == usage["usage_id"]

    delete = client.delete(f"/api/batch-filter-lots/materials/{usage['usage_id']}", headers=admin_h)
    assert delete.status_code == 204, delete.text
    assert _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix}-PX")["quantity"] == 50


def test_add_filter_lot_material_blocks_non_workshop_lot(client, admin_h):
    suffix = "FLMU02"
    _a_material_with_stock(client, admin_h, f"MAT-{suffix}", qty_company=20)
    filter_lot_id = _make_filter_lot(client, admin_h, suffix)
    lot = _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix}-CTY")

    blocked = client.post(f"/api/batch-filter-lots/{filter_lot_id}/materials", headers=admin_h,
                          json={"lot_id": lot["lot_id"], "quantity": 5})
    assert blocked.status_code == 409, blocked.text
    assert "kho phân xưởng" in blocked.json()["detail"].lower()


def test_add_filter_lot_material_non_fifo_requires_reason(client, admin_h):
    """Chọn lô KHÁC lô cũ nhất (FIFO) — chặn nếu không ghi lý do, cho qua nếu có lý do, và
    fifo_ok/reason phải lưu đúng."""
    suffix = "FLMU03"
    material_id = _a_material_with_stock(client, admin_h, f"MAT-{suffix}", qty_workshop=10)
    _a_workshop_lot(client, admin_h, material_id, f"LOT-{suffix}-NEWER", 20)
    filter_lot_id = _make_filter_lot(client, admin_h, suffix)
    newer_lot = _lot_id_by_code(client, admin_h, f"LOT-{suffix}-NEWER")

    no_reason = client.post(f"/api/batch-filter-lots/{filter_lot_id}/materials", headers=admin_h,
                            json={"lot_id": newer_lot["lot_id"], "quantity": 5})
    assert no_reason.status_code == 409, no_reason.text
    assert "fifo" in no_reason.json()["detail"].lower()

    with_reason = client.post(f"/api/batch-filter-lots/{filter_lot_id}/materials", headers=admin_h,
                              json={"lot_id": newer_lot["lot_id"], "quantity": 5, "reason": "Lô cũ đã hết chỗ chứa"})
    assert with_reason.status_code == 201, with_reason.text
    usage = with_reason.json()
    assert usage["fifo_ok"] is False
    assert usage["reason"] == "Lô cũ đã hết chỗ chứa"


def test_add_pack_lot_material_non_fifo_requires_reason(client, admin_h):
    """Cùng enforcement FIFO+lý do áp dụng cho NVL lô thành phẩm (chiết) đã có sẵn từ trước."""
    suffix = "PLMU-FIFO"
    material_id = _a_material_with_stock(client, admin_h, f"MAT-{suffix}", qty_workshop=10)
    _a_workshop_lot(client, admin_h, material_id, f"LOT-{suffix}-NEWER", 20)
    filter_lot_id = _make_filter_lot(client, admin_h, suffix)
    src = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()[0]
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    fin = client.put(f"/api/batch-filter-lots/batches/{batches[0]['batch_link_id']}/finish", headers=admin_h,
                     json={"draws": [{"source_link_id": src["link_id"], "dich_nha_hl": 900}], "nuoc_bai_khi_hl": 0})
    assert fin.status_code == 200, fin.text
    appr = client.post(f"/api/batch-filter-lots/{filter_lot_id}/approve", headers=admin_h)
    assert appr.status_code == 200, appr.text
    to_bbt = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()["to_bbt"]
    pack = client.post("/api/batch-pack-lots", headers=admin_h,
                       json={"from_bbt": to_bbt, "qty": 200, "pack_lot_code": f"PKG-{suffix}", "lot_no": f"LOT-{suffix}"})
    assert pack.status_code == 201, pack.text
    pack_lot_id = pack.json()["pack_lot_id"]
    newer_lot = _lot_id_by_code(client, admin_h, f"LOT-{suffix}-NEWER")

    no_reason = client.post(f"/api/batch-pack-lots/{pack_lot_id}/materials", headers=admin_h,
                            json={"lot_id": newer_lot["lot_id"], "quantity": 3})
    assert no_reason.status_code == 409, no_reason.text
    assert "fifo" in no_reason.json()["detail"].lower()

    with_reason = client.post(f"/api/batch-pack-lots/{pack_lot_id}/materials", headers=admin_h,
                              json={"lot_id": newer_lot["lot_id"], "quantity": 3, "reason": "Lô cũ để dành mẻ khác"})
    assert with_reason.status_code == 201, with_reason.text
    usage = with_reason.json()
    assert usage["fifo_ok"] is False
    assert usage["reason"] == "Lô cũ để dành mẻ khác"
