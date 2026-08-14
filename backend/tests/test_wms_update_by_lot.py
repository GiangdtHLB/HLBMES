"""Test PUT /api/wms/units/by-lot (update_units_by_criteria) — sửa lô vỉ/keg đã nhập kho thủ
công/tồn đầu THEO TIÊU CHÍ nhóm (product_name/lot_code/unit_type/warehouse_id), mirror
delete_units_by_criteria. Chặn khi lô đã được Trưởng bộ phận kho duyệt nhập kho."""

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


def _a_finished_product(client, admin_h, code):
    r = client.post("/api/finished-products", headers=admin_h,
                    json={"code": code, "name": code, "uom": "lon", "unit_type": "vi", "pack_size": 24})
    assert r.status_code == 201, r.text
    return r.json()["finished_product_id"]


def _a_loc(client, admin_h, code):
    r = client.post("/api/wms/locations", headers=admin_h,
                    json={"code": code, "name": f"Vị trí {code}", "capacity": 1000})
    assert r.status_code == 201, r.text
    return r.json()["loc_id"]


def _build_manual_lot(client, admin_h, fp_id, product_name, lot_code, loc_id, total=48):
    built = client.post("/api/wms/units", headers=admin_h,
                        json={"finished_product_id": fp_id, "product_name": product_name,
                              "lot_code": lot_code, "total": total, "pack_size": 24,
                              "unit_type": "vi", "reason": "Nhập kho thủ công", "loc_id": loc_id})
    assert built.status_code == 201, built.text
    return built.json()


def _lot_row(client, admin_h, product_name, lot_code):
    rows = client.get("/api/wms/units/by-lot", headers=admin_h).json()
    return next((r for r in rows if r["product_name"] == product_name and r["lot_code"] == lot_code), None)


def test_update_by_lot_edits_lot_code_location_and_date(client, admin_h):
    fp_id = _a_finished_product(client, admin_h, "SKU-UPDLOT-01")
    loc1 = _a_loc(client, admin_h, "LOC-UPDLOT-01")
    loc2 = _a_loc(client, admin_h, "LOC-UPDLOT-02")
    _build_manual_lot(client, admin_h, fp_id, "SKU-UPDLOT-01", "LOT-OLD", loc1)

    upd = client.put("/api/wms/units/by-lot", headers=admin_h,
                     json={"product_name": "SKU-UPDLOT-01", "lot_code": "LOT-OLD", "unit_type": "vi",
                           "new_lot_code": "LOT-NEW", "location_id": loc2,
                           "received_at": "2026-01-05T08:00:00"})
    assert upd.status_code == 200, upd.text
    assert upd.json()["updated"] == 1

    assert _lot_row(client, admin_h, "SKU-UPDLOT-01", "LOT-OLD") is None
    row = _lot_row(client, admin_h, "SKU-UPDLOT-01", "LOT-NEW")
    assert row is not None
    vi_loc_ids = [l["loc_id"] for l in row["vi_locations"]]
    assert vi_loc_ids == [loc2]


def test_update_by_lot_rejects_when_no_match(client, admin_h):
    fp_id = _a_finished_product(client, admin_h, "SKU-UPDLOT-02")
    resp = client.put("/api/wms/units/by-lot", headers=admin_h,
                      json={"product_name": "SKU-UPDLOT-02", "lot_code": "NOPE", "unit_type": "vi",
                            "new_lot_code": "WHATEVER"})
    assert resp.status_code == 409, resp.text


def test_update_by_lot_blocked_after_received_confirmed(client, admin_h):
    fp_id = _a_finished_product(client, admin_h, "SKU-UPDLOT-03")
    loc1 = _a_loc(client, admin_h, "LOC-UPDLOT-03")
    _build_manual_lot(client, admin_h, fp_id, "SKU-UPDLOT-03", "LOT-CONFIRMED", loc1)

    confirm = client.post("/api/wms/units/confirm-receipt-by-lot", headers=admin_h,
                          json={"product_name": "SKU-UPDLOT-03", "lot_code": "LOT-CONFIRMED", "unit_type": "vi"})
    assert confirm.status_code == 200, confirm.text

    blocked = client.put("/api/wms/units/by-lot", headers=admin_h,
                         json={"product_name": "SKU-UPDLOT-03", "lot_code": "LOT-CONFIRMED", "unit_type": "vi",
                               "new_lot_code": "LOT-SHOULD-FAIL"})
    assert blocked.status_code == 409, blocked.text
    assert "duyệt nhập kho" in blocked.json()["detail"].lower()

    # Vẫn còn nguyên lô cũ, không bị sửa.
    assert _lot_row(client, admin_h, "SKU-UPDLOT-03", "LOT-CONFIRMED") is not None
