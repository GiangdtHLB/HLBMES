"""Test mã xe cố định (Vehicle.vehicle_code), bắt buộc xe+vị trí khi khai báo bia gửi, xe đã
gửi hiện ở picker Xuất kho, km/lít xăng chuyến xuất (chỉ điền được sau khi duyệt), và 3 báo cáo
mới: vehicle_trip_report (lượt xe & tải trọng), consigned_summary_report (tổng hợp bia gửi),
fuel_efficiency_report (định mức nhiên liệu). Xem plan tại C:\\Users\\hoang\\.claude\\plans\\
enchanted-doodling-phoenix.md."""

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
def truongkho_tp_h(client):
    return _login(client, "truongkho_tp", "123456")


def _a_vehicle(client, admin_h, plate, capacity_kg=None):
    r = client.post("/api/wms/vehicles", headers=admin_h,
                    json={"plate": plate, "capacity_kg": capacity_kg})
    assert r.status_code == 201, r.text
    return r.json()


def _a_finished_product(client, admin_h, code, pack_size=24, weight_primary_kg=None,
                        weight_single_kg=None, unit_volume_l=0.33):
    payload = {"code": code, "name": f"SP {code}", "uom": "lon", "unit_type": "vi",
              "pack_size": pack_size, "unit_volume_l": unit_volume_l}
    if weight_primary_kg is not None:
        payload["weight_primary_kg"] = weight_primary_kg
    if weight_single_kg is not None:
        payload["weight_single_kg"] = weight_single_kg
    fp = client.post("/api/finished-products", headers=admin_h, json=payload)
    assert fp.status_code == 201, fp.text
    return fp.json()["finished_product_id"], fp.json()["code"]


def _a_ship_to(client, admin_h, code):
    st = client.post("/api/suppliers", headers=admin_h, json={"code": code, "name": f"NPP {code}"})
    assert st.status_code == 201, st.text
    return st.json()["supplier_id"]


_DEFAULT_LOC_ID = None


def _default_loc(client, admin_h):
    """Vị trí kho mặc định cho các test không quan tâm tới vị trí cụ thể — build_units nay bắt
    buộc chọn vị trí ngay lúc nhập (không còn "chưa cất" cho luồng thủ công)."""
    global _DEFAULT_LOC_ID
    if _DEFAULT_LOC_ID is None:
        r = client.post("/api/wms/locations", headers=admin_h,
                        json={"code": "VEHREPORT-DEFAULT-LOC", "name": "Vị trí mặc định test vehicle report",
                              "capacity": 1_000_000})
        assert r.status_code == 201, r.text
        _DEFAULT_LOC_ID = r.json()["loc_id"]
    return _DEFAULT_LOC_ID


def _build_and_confirm(client, admin_h, product, lot_code, total, pack_size=24, unit_type="vi", fp_id=None):
    payload = {"product_name": product, "lot_code": lot_code, "total": total,
              "pack_size": pack_size, "unit_type": unit_type, "loc_id": _default_loc(client, admin_h)}
    if fp_id:
        payload["finished_product_id"] = fp_id
    build = client.post("/api/wms/units", headers=admin_h, json=payload)
    assert build.status_code == 201, build.text
    confirm = client.post("/api/wms/units/confirm-receipt-by-lot", headers=admin_h,
                          json={"product_name": product, "lot_code": lot_code, "unit_type": unit_type})
    assert confirm.status_code == 200, confirm.text
    return build.json()["unit_codes"][0]


def test_vehicle_code_auto_generated_and_unique(client, admin_h):
    v1 = _a_vehicle(client, admin_h, "XECODE-01")
    v2 = _a_vehicle(client, admin_h, "XECODE-02")
    assert v1["vehicle_code"] and v2["vehicle_code"]
    assert v1["vehicle_code"] != v2["vehicle_code"]
    rows = client.get("/api/wms/vehicles", headers=admin_h).json()
    codes = [r["vehicle_code"] for r in rows if r["vehicle_id"] in (v1["vehicle_id"], v2["vehicle_id"])]
    assert len(set(codes)) == 2


def _ship_for_vehicle(client, admin_h, fp_id, code, quantity, vehicle_id, pack_size=24):
    """Tạo 1 lô tồn kho + xuất hết qua `vehicle_id` — create_consigned_entry giờ bắt buộc phải
    có Shipment thật của xe chứa đúng sản phẩm/số lượng này trong khoảng cho phép. `quantity` là
    số vỉ; total (đơn vị nhỏ nhất) = quantity * pack_size (khớp fp.pack_size mặc định 24 của
    _a_finished_product)."""
    lot_code = f"LOT-SHIP-{code}"
    _build_and_confirm(client, admin_h, code, lot_code, total=quantity * pack_size, pack_size=pack_size,
                       unit_type="vi", fp_id=fp_id)
    ship_to_id = _a_ship_to(client, admin_h, f"DIST-SHIP-{code}")
    shipped = client.post("/api/wms/shipments", headers=admin_h,
                          json={"ship_to_id": ship_to_id,
                                "lines": [{"product_name": code, "lot_code": lot_code,
                                          "unit_type": "vi", "quantity": quantity}],
                                "vehicle_id": vehicle_id})
    assert shipped.status_code == 201, shipped.text


def test_consigned_entry_stores_vehicle_and_surfaces_in_lot_summary(client, admin_h):
    fp_id, code = _a_finished_product(client, admin_h, "SKU-GSVEH")
    loc = client.post("/api/wms/locations", headers=admin_h,
                      json={"code": "LOC-GSVEH", "name": "Vị trí test", "capacity": 100})
    assert loc.status_code == 201, loc.text
    loc_id = loc.json()["loc_id"]
    vehicle = _a_vehicle(client, admin_h, "GSVEH-PLATE-01")
    _ship_for_vehicle(client, admin_h, fp_id, code, 2, vehicle["vehicle_id"])

    entry = client.post("/api/wms/consigned", headers=admin_h,
                        json={"finished_product_id": fp_id, "quantity": 2,
                              "location_id": loc_id, "vehicle_id": vehicle["vehicle_id"]})
    assert entry.status_code == 201, entry.text
    lot_code = entry.json()["lot_code"]

    hist = client.get("/api/wms/consigned", headers=admin_h).json()
    row = next(h for h in hist if h["direction"] == "in" and h["lot_code"] == lot_code)
    assert row["vehicle_plate"] == "GSVEH-PLATE-01"
    assert row["vehicle_code"] == vehicle["vehicle_code"]

    approve = client.post(f"/api/wms/consigned/{row['entry_id']}/approve", headers=admin_h)
    assert approve.status_code == 200, approve.text

    by_lot = client.get("/api/wms/units/by-lot", headers=admin_h).json()
    group = next(g for g in by_lot if g["lot_code"] == lot_code)
    assert group["consigned_vehicle_plate"] == "GSVEH-PLATE-01"
    assert group["consigned_vehicle_code"] == vehicle["vehicle_code"]


def test_create_shipment_with_vehicle_id_and_trip_km_fuel(client, admin_h, truongkho_tp_h):
    fp_id, code = _a_finished_product(client, admin_h, "SKU-TRIPVEH", weight_primary_kg=5,
                                      weight_single_kg=0.3, unit_volume_l=0.33)
    _build_and_confirm(client, admin_h, code, "LOT-TRIPVEH", total=24, pack_size=24)
    ship_to_id = _a_ship_to(client, admin_h, "DIST-TRIPVEH")
    vehicle = _a_vehicle(client, admin_h, "TRIPVEH-PLATE")

    shipped = client.post("/api/wms/shipments", headers=admin_h,
                          json={"ship_to_id": ship_to_id,
                                "lines": [{"product_name": code, "lot_code": "LOT-TRIPVEH",
                                          "unit_type": "vi", "quantity": 1}],
                                "vehicle_id": vehicle["vehicle_id"]})
    assert shipped.status_code == 201, shipped.text
    shipment_id = shipped.json()["shipment_id"]

    hist = client.get("/api/wms/shipments", headers=admin_h).json()
    row = next(s for s in hist if s["shipment_id"] == shipment_id)
    assert row["vehicle_code"] == vehicle["vehicle_code"]
    assert row["km"] is None and row["fuel_liters"] is None

    # Chưa duyệt -> không cho điền km/lít xăng.
    blocked = client.post(f"/api/wms/shipments/{shipment_id}/trip", headers=admin_h,
                          json={"km": 50, "fuel_liters": 8})
    assert blocked.status_code == 409, blocked.text

    confirm = client.post(f"/api/wms/shipments/{shipment_id}/confirm", headers=truongkho_tp_h)
    assert confirm.status_code == 200, confirm.text

    trip = client.post(f"/api/wms/shipments/{shipment_id}/trip", headers=admin_h,
                       json={"km": 50, "fuel_liters": 8})
    assert trip.status_code == 200, trip.text
    assert trip.json()["km"] == 50 and trip.json()["fuel_liters"] == 8

    hist2 = client.get("/api/wms/shipments", headers=admin_h).json()
    row2 = next(s for s in hist2 if s["shipment_id"] == shipment_id)
    assert row2["km"] == 50 and row2["fuel_liters"] == 8

    # Sửa lại số liệu (không khoá, cho sửa nhiều lần).
    trip2 = client.post(f"/api/wms/shipments/{shipment_id}/trip", headers=admin_h,
                        json={"km": 55, "fuel_liters": 9})
    assert trip2.status_code == 200, trip2.text
    assert trip2.json()["km"] == 55


def test_vehicle_trip_report_weight_and_over_capacity(client, admin_h, truongkho_tp_h):
    """1 xe, 2 chuyến: chuyến 1 (1 vỉ nguyên, 5kg/vỉ) không vượt tải (capacity=6kg); chuyến 2
    (24 lon đã phân rã, 0.3kg/lon = 7.2kg) vượt tải capacity=6kg -> over_capacity_trip_count=1."""
    fp_id, code = _a_finished_product(client, admin_h, "SKU-WEIGHTCALC", weight_primary_kg=5,
                                      weight_single_kg=0.3)
    vehicle = _a_vehicle(client, admin_h, "WEIGHTCALC-PLATE", capacity_kg=6)
    ship_to_id = _a_ship_to(client, admin_h, "DIST-WEIGHTCALC")

    # Chuyến 1: 1 vỉ nguyên (chưa phân rã) -> weight = 1 * weight_primary_kg = 5kg.
    _build_and_confirm(client, admin_h, code, "LOT-WEIGHT-A", total=24, pack_size=24, unit_type="vi", fp_id=fp_id)
    ship1 = client.post("/api/wms/shipments", headers=admin_h,
                       json={"ship_to_id": ship_to_id,
                             "lines": [{"product_name": code, "lot_code": "LOT-WEIGHT-A",
                                       "unit_type": "vi", "quantity": 1}],
                             "vehicle_id": vehicle["vehicle_id"]})
    assert ship1.status_code == 201, ship1.text

    # Chuyến 2: 1 vỉ khác, phân rã ra lon rồi xuất theo lon -> weight = 24 * weight_single_kg = 7.2kg.
    _build_and_confirm(client, admin_h, code, "LOT-WEIGHT-B", total=24, pack_size=24, unit_type="vi", fp_id=fp_id)
    decomp = client.post("/api/wms/units/decompose-batch", headers=admin_h,
                         json={"product_name": code, "lot_code": "LOT-WEIGHT-B", "count": 1})
    assert decomp.status_code == 201, decomp.text
    ship2 = client.post("/api/wms/shipments", headers=admin_h,
                       json={"ship_to_id": ship_to_id,
                             "lines": [{"product_name": code, "lot_code": "LOT-WEIGHT-B",
                                       "unit_type": "lon", "quantity": 24}],
                             "vehicle_id": vehicle["vehicle_id"]})
    assert ship2.status_code == 201, ship2.text

    report = client.get("/api/reports/vehicle-trip-report", headers=admin_h)
    assert report.status_code == 200, report.text
    row = next(r for r in report.json()["rows"] if r["vehicle_id"] == vehicle["vehicle_id"])
    assert row["trip_count"] == 2
    assert row["total_kg"] == pytest.approx(12.2, abs=0.01)
    assert row["avg_kg_per_trip"] == pytest.approx(6.1, abs=0.01)
    assert row["over_capacity_trip_count"] == 1


def test_consigned_summary_report_aggregates_by_product(client, admin_h):
    fp_id, code = _a_finished_product(client, admin_h, "SKU-GSSUM")
    loc = client.post("/api/wms/locations", headers=admin_h,
                      json={"code": "LOC-GSSUM", "name": "Vị trí gộp", "capacity": 100}).json()
    vehicle = _a_vehicle(client, admin_h, "GSSUM-PLATE")
    _ship_for_vehicle(client, admin_h, fp_id, code, 5, vehicle["vehicle_id"])

    for qty in (2, 3):
        entry = client.post("/api/wms/consigned", headers=admin_h,
                            json={"finished_product_id": fp_id, "quantity": qty,
                                  "location_id": loc["loc_id"], "vehicle_id": vehicle["vehicle_id"]})
        assert entry.status_code == 201, entry.text

    report = client.get("/api/reports/consigned-summary-report", headers=admin_h)
    assert report.status_code == 200, report.text
    row = next(r for r in report.json()["rows"] if r["product_name"] == code)
    assert row["total_quantity"] == 5
    assert row["entry_count"] == 2


def test_fuel_efficiency_report_only_includes_shipments_with_km_and_fuel(client, admin_h, truongkho_tp_h):
    fp_id, code = _a_finished_product(client, admin_h, "SKU-FUELCALC", unit_volume_l=0.33)
    vehicle = _a_vehicle(client, admin_h, "FUELCALC-PLATE")
    ship_to_id = _a_ship_to(client, admin_h, "DIST-FUELCALC")

    _build_and_confirm(client, admin_h, code, "LOT-FUEL-DONE", total=24, pack_size=24, fp_id=fp_id)
    ship_done = client.post("/api/wms/shipments", headers=admin_h,
                            json={"ship_to_id": ship_to_id,
                                  "lines": [{"product_name": code, "lot_code": "LOT-FUEL-DONE",
                                            "unit_type": "vi", "quantity": 1}],
                                  "vehicle_id": vehicle["vehicle_id"]})
    assert ship_done.status_code == 201, ship_done.text
    sid_done = ship_done.json()["shipment_id"]
    client.post(f"/api/wms/shipments/{sid_done}/confirm", headers=truongkho_tp_h)
    trip = client.post(f"/api/wms/shipments/{sid_done}/trip", headers=admin_h,
                       json={"km": 40, "fuel_liters": 5})
    assert trip.status_code == 200, trip.text

    # Phiếu thứ 2: đã duyệt nhưng CHƯA điền km/lít xăng -> không xuất hiện trong báo cáo.
    _build_and_confirm(client, admin_h, code, "LOT-FUEL-NOKM", total=24, pack_size=24)
    ship_nokm = client.post("/api/wms/shipments", headers=admin_h,
                            json={"ship_to_id": ship_to_id,
                                  "lines": [{"product_name": code, "lot_code": "LOT-FUEL-NOKM",
                                            "unit_type": "vi", "quantity": 1}],
                                  "vehicle_id": vehicle["vehicle_id"]})
    assert ship_nokm.status_code == 201, ship_nokm.text
    client.post(f"/api/wms/shipments/{ship_nokm.json()['shipment_id']}/confirm", headers=truongkho_tp_h)

    report = client.get("/api/reports/fuel-efficiency-report", headers=admin_h)
    assert report.status_code == 200, report.text
    codes = {r["shipment_code"] for r in report.json()["rows"]}
    assert ship_done.json()["shipment_code"] in codes
    assert ship_nokm.json()["shipment_code"] not in codes

    row = next(r for r in report.json()["rows"] if r["shipment_code"] == ship_done.json()["shipment_code"])
    # 24 lon x 0.33L = 7.92L bia; 5L xăng / 7.92L bia; 40km / 5L xăng.
    assert row["liters_beer"] == pytest.approx(7.92, abs=0.01)
    assert row["l_fuel_per_l_beer"] == pytest.approx(5 / 7.92, abs=0.001)
    assert row["km_per_l_fuel"] == pytest.approx(8.0, abs=0.01)
