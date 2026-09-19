"""Xuất CẢ LÔ (nhiều pallet cùng lot_code) trong 1 lần, thay vì phải xuất từng pallet lẻ (yêu
cầu người dùng 2026-09-20 — nhiều pallet (SSCC riêng) cùng chung 1 Lô TP là bình thường theo
chuẩn GS1). Xem services/wms.py::list_lots/ship_lot, routers/wms.py GET/POST /wms/lots."""

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


@pytest.fixture(scope="module")
def vanhanh_h(client):
    # "vanhanh" có batch.execute nhưng KHÔNG có warehouse.issue — đúng đối tượng cần bị chặn.
    return _login(client, "vanhanh", "123456")


def _build_pallet(client, admin_h, product, lot_code, case_count, units_per_case=24):
    r = client.post("/api/wms/pallets", headers=admin_h,
                    json={"product": product, "lot_code": lot_code,
                         "case_count": case_count, "units_per_case": units_per_case})
    assert r.status_code == 201, r.text
    return r.json()


def test_list_lots_aggregates_multiple_pallets_same_lot(client, admin_h):
    lot_code = "LOT-AGG-01"
    _build_pallet(client, admin_h, "SKU-AGG", lot_code, 100, 24)
    _build_pallet(client, admin_h, "SKU-AGG", lot_code, 50, 24)

    lots = client.get("/api/wms/lots", headers=admin_h).json()
    row = next(l for l in lots if l["lot_code"] == lot_code)
    assert row["pallet_count"] == 2
    assert row["total_units"] == (100 + 50) * 24
    assert row["by_status"]["building"] == 2


def test_ship_lot_ships_all_pallets_and_reports_totals(client, admin_h):
    lot_code = "LOT-SHIPALL-01"
    p1 = _build_pallet(client, admin_h, "SKU-SHIP", lot_code, 110, 24)
    p2 = _build_pallet(client, admin_h, "SKU-SHIP", lot_code, 30, 24)

    ship = client.post(f"/api/wms/lots/{lot_code}/ship", headers=admin_h)
    assert ship.status_code == 200, ship.text
    result = ship.json()
    assert result["pallet_count"] == 2
    assert result["total_units"] == (110 + 30) * 24
    assert sorted(result["pallet_codes"]) == sorted([p1["pallet_code"], p2["pallet_code"]])

    pallets = client.get("/api/wms/pallets", headers=admin_h).json()
    made = [p for p in pallets if p["pallet_code"] in result["pallet_codes"]]
    assert all(p["status"] == "shipped" for p in made)

    # Lô đã xuất hết -> không còn xuất hiện trong danh sách chọn xuất.
    lots = client.get("/api/wms/lots", headers=admin_h).json()
    assert not any(l["lot_code"] == lot_code for l in lots)


def test_ship_lot_blocked_when_no_pallets_left(client, admin_h):
    missing = client.post("/api/wms/lots/LOT-NEVER-EXISTED/ship", headers=admin_h)
    assert missing.status_code == 404, missing.text


def test_ship_lot_only_ships_unshipped_pallets_in_lot(client, admin_h):
    """1 lô có pallet ĐÃ xuất từ trước (lẻ tay) + pallet chưa xuất — ship_lot chỉ xuất phần
    còn lại, không đụng tới pallet đã xuất rồi."""
    lot_code = "LOT-PARTIAL-01"
    p1 = _build_pallet(client, admin_h, "SKU-PARTIAL", lot_code, 40, 24)
    p2 = _build_pallet(client, admin_h, "SKU-PARTIAL", lot_code, 60, 24)
    already = client.post(f"/api/wms/pallets/{p1['pallet_id']}/ship", headers=admin_h)
    assert already.status_code == 200, already.text

    ship = client.post(f"/api/wms/lots/{lot_code}/ship", headers=admin_h)
    assert ship.status_code == 200, ship.text
    result = ship.json()
    assert result["pallet_count"] == 1
    assert result["pallet_codes"] == [p2["pallet_code"]]
    assert result["total_units"] == 60 * 24


def test_ship_lot_requires_warehouse_issue_permission(client, admin_h, vanhanh_h):
    lot_code = "LOT-PERM-01"
    _build_pallet(client, admin_h, "SKU-PERM", lot_code, 10, 24)

    forbidden = client.post(f"/api/wms/lots/{lot_code}/ship", headers=vanhanh_h)
    assert forbidden.status_code == 403, forbidden.text
