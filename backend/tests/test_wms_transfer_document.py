"""Test phiếu điều chuyển nội bộ (WmsTransfer/WmsTransferLine) — mirror phiếu xuất kho
(Shipment) nhưng đích là 1 WmsLocation (không phải Supplier) và KHÔNG làm giảm tổng tồn kho
toàn công ty: chỉ đổi FinishedGoodsUnit.location_id (status vẫn "stored"), giữ nguyên lot_code
để truy xuất nguồn gốc không đứt. Có Duyệt/Hoàn tác/km-lít xăng giống Xuất kho, khác ở chỗ Hoàn
tác trả ĐÚNG lại vị trí gốc (ghi ở WmsTransferLine.from_location_id lúc tạo phiếu)."""

import os
import tempfile
import time

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
def thukho_h(client):
    return _login(client, "thukho", "123456")


@pytest.fixture(scope="module")
def truongkho_tp_h(client):
    return _login(client, "truongkho_tp", "123456")


def _a_location(client, admin_h, capacity=50):
    loc = client.post("/api/wms/locations", headers=admin_h,
                      json={"code": f"LOC-{str(int(time.time() * 1000))[-8:]}-{id(object())}",
                            "name": "Test loc", "capacity": capacity})
    assert loc.status_code == 201, loc.text
    return loc.json()["loc_id"]


def _a_units(client, admin_h, product, lot_code, count, loc_id=None):
    """Mirror test_wms_ship_to.py::_a_units — pack_size=1 nên quantity = số vỉ luôn, product_name
    tự do (không qua Danh mục Sản phẩm) nên _pack_divisor trả về 1."""
    build = client.post("/api/wms/units", headers=admin_h,
                        json={"product_name": product, "lot_code": lot_code, "total": count, "pack_size": 1,
                              "loc_id": loc_id or _a_location(client, admin_h)})
    assert build.status_code == 201, build.text
    confirm = client.post("/api/wms/units/confirm-receipt-by-lot", headers=admin_h,
                          json={"product_name": product, "lot_code": lot_code, "unit_type": "vi"})
    assert confirm.status_code == 200, confirm.text
    units = client.get("/api/wms/units", headers=admin_h).json()
    return next(u for u in units if u["product"] == product and u["lot_code"] == lot_code)


def _total_stored_count(client, admin_h, product, lot_code):
    units = client.get("/api/wms/units", headers=admin_h).json()
    return sum(u["quantity"] for u in units if u["product"] == product and u["lot_code"] == lot_code
              and u["status"] == "stored")


def test_create_transfer_moves_stock_preserves_lot_no_stock_reduction(client, admin_h):
    loc_a = _a_location(client, admin_h)
    loc_b = _a_location(client, admin_h)
    unit = _a_units(client, admin_h, "TXDOC-SKU1", "LOT-TXDOC1", 10, loc_id=loc_a)
    assert unit["location"] is not None

    before_total = _total_stored_count(client, admin_h, "TXDOC-SKU1", "LOT-TXDOC1")
    assert before_total == 10

    created = client.post("/api/wms/transfers", headers=admin_h,
                          json={"to_location_id": loc_b,
                                "lines": [{"product_name": "TXDOC-SKU1", "lot_code": "LOT-TXDOC1",
                                          "unit_type": "vi", "quantity": 10}]})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["transfer_code"].endswith("/DC-BHL")
    assert body["fifo_ok"] is True

    # Tổng tồn kho KHÔNG đổi (không phải "xuất" — chỉ đổi vị trí).
    after_total = _total_stored_count(client, admin_h, "TXDOC-SKU1", "LOT-TXDOC1")
    assert after_total == before_total == 10

    units = client.get("/api/wms/units", headers=admin_h).json()
    moved = [u for u in units if u["product"] == "TXDOC-SKU1" and u["lot_code"] == "LOT-TXDOC1"]
    assert all(u["status"] == "stored" for u in moved)
    assert all(u["lot_code"] == "LOT-TXDOC1" for u in moved)  # mã lô giữ nguyên — truy xuất nguồn gốc không đứt

    history = client.get("/api/wms/transfers", headers=admin_h).json()
    row = next(t for t in history if t["transfer_id"] == body["transfer_id"])
    assert row["unit_count"] == 10
    assert row["lines"] == [{"product": "TXDOC-SKU1", "lot_code": "LOT-TXDOC1", "unit_type": "vi",
                             "count": 10.0, "quantity": 10.0}]
    assert row["confirmed_by"] is None


def test_create_transfer_requires_destination_and_lines(client, admin_h):
    _a_units(client, admin_h, "TXDOC-SKU2", "LOT-TXDOC2", 3)
    loc_b = _a_location(client, admin_h)

    no_lines = client.post("/api/wms/transfers", headers=admin_h, json={"to_location_id": loc_b, "lines": []})
    assert no_lines.status_code == 409, no_lines.text

    no_dest = client.post("/api/wms/transfers", headers=admin_h,
                          json={"to_location_id": "", "lines": [{"product_name": "TXDOC-SKU2",
                                "lot_code": "LOT-TXDOC2", "unit_type": "vi", "quantity": 1}]})
    assert no_dest.status_code in (409, 422), no_dest.text


def test_create_transfer_blocks_insufficient_stock_and_capacity(client, admin_h):
    loc_a = _a_location(client, admin_h)
    loc_small = _a_location(client, admin_h, capacity=1)
    _a_units(client, admin_h, "TXDOC-SKU3", "LOT-TXDOC3", 5, loc_id=loc_a)

    not_enough = client.post("/api/wms/transfers", headers=admin_h,
                             json={"to_location_id": loc_small,
                                   "lines": [{"product_name": "TXDOC-SKU3", "lot_code": "LOT-TXDOC3",
                                             "unit_type": "vi", "quantity": 100}]})
    assert not_enough.status_code == 409, not_enough.text

    over_capacity = client.post("/api/wms/transfers", headers=admin_h,
                                json={"to_location_id": loc_small,
                                      "lines": [{"product_name": "TXDOC-SKU3", "lot_code": "LOT-TXDOC3",
                                                "unit_type": "vi", "quantity": 5}]})
    assert over_capacity.status_code == 409, over_capacity.text
    assert "sức chứa" in over_capacity.json()["detail"]


def test_create_transfer_location_id_constrains_fifo_to_source_location(client, admin_h):
    """Cùng 1 lô nằm ở 2 vị trí kho — điều chuyển với location_id chỉ được lấy đúng đơn vị đang
    ở vị trí đó, KHÔNG lấy lẫn qua vị trí khác cùng lô (dù cùng product_name+lot_code+unit_type
    khiến _consume_lot_rows không lọc location vẫn có thể FIFO lấy đúng), xem create_transfer."""
    loc_a = _a_location(client, admin_h)
    loc_b = _a_location(client, admin_h)
    loc_dest = _a_location(client, admin_h)
    _a_units(client, admin_h, "TXDOC-SKU9", "LOT-TXDOC9", 5, loc_id=loc_a)
    _a_units(client, admin_h, "TXDOC-SKU9", "LOT-TXDOC9", 5, loc_id=loc_b)

    created = client.post("/api/wms/transfers", headers=admin_h,
                          json={"to_location_id": loc_dest,
                                "lines": [{"product_name": "TXDOC-SKU9", "lot_code": "LOT-TXDOC9",
                                          "unit_type": "vi", "quantity": 5, "location_id": loc_a}]})
    assert created.status_code == 201, created.text

    locs_by_id = {l["loc_id"]: l["code"] for l in client.get("/api/wms/locations", headers=admin_h).json()}
    units = client.get("/api/wms/units", headers=admin_h).json()
    moved = [u for u in units if u["product"] == "TXDOC-SKU9" and u["lot_code"] == "LOT-TXDOC9"]
    at_dest = sum(u["quantity"] for u in moved if u["location"] == locs_by_id[loc_dest])
    at_b = sum(u["quantity"] for u in moved if u["location"] == locs_by_id[loc_b])
    assert at_dest == 5  # 5 đơn vị từ loc_a đã sang loc_dest
    assert at_b == 5  # 5 đơn vị ở loc_b hoàn toàn không bị đụng tới


def test_confirm_transfer_then_trip_km_fuel(client, admin_h, thukho_h, truongkho_tp_h):
    loc_a = _a_location(client, admin_h)
    loc_b = _a_location(client, admin_h)
    _a_units(client, admin_h, "TXDOC-SKU4", "LOT-TXDOC4", 4, loc_id=loc_a)
    created = client.post("/api/wms/transfers", headers=admin_h,
                          json={"to_location_id": loc_b,
                                "lines": [{"product_name": "TXDOC-SKU4", "lot_code": "LOT-TXDOC4",
                                          "unit_type": "vi", "quantity": 4}]})
    assert created.status_code == 201, created.text
    transfer_id = created.json()["transfer_id"]

    # Chưa duyệt -> không cho điền km/lít xăng.
    blocked_trip = client.post(f"/api/wms/transfers/{transfer_id}/trip", headers=admin_h,
                               json={"km": 5, "fuel_liters": 1})
    assert blocked_trip.status_code == 409, blocked_trip.text

    denied_confirm = client.post(f"/api/wms/transfers/{transfer_id}/confirm", headers=thukho_h)
    assert denied_confirm.status_code == 403, denied_confirm.text

    confirm = client.post(f"/api/wms/transfers/{transfer_id}/confirm", headers=truongkho_tp_h)
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["confirmed_by"] == "truongkho_tp"

    twice = client.post(f"/api/wms/transfers/{transfer_id}/confirm", headers=truongkho_tp_h)
    assert twice.status_code == 409, twice.text

    trip = client.post(f"/api/wms/transfers/{transfer_id}/trip", headers=admin_h,
                       json={"km": 5, "fuel_liters": 1})
    assert trip.status_code == 200, trip.text
    assert trip.json()["km"] == 5 and trip.json()["fuel_liters"] == 1

    history = client.get("/api/wms/transfers", headers=admin_h).json()
    row = next(t for t in history if t["transfer_id"] == transfer_id)
    assert row["km"] == 5 and row["fuel_liters"] == 1 and row["confirmed_by"] == "truongkho_tp"


def test_undo_transfer_restores_original_locations(client, admin_h):
    loc_a = _a_location(client, admin_h)
    loc_b = _a_location(client, admin_h)
    _a_units(client, admin_h, "TXDOC-SKU5", "LOT-TXDOC5", 6, loc_id=loc_a)
    created = client.post("/api/wms/transfers", headers=admin_h,
                          json={"to_location_id": loc_b,
                                "lines": [{"product_name": "TXDOC-SKU5", "lot_code": "LOT-TXDOC5",
                                          "unit_type": "vi", "quantity": 6}]})
    assert created.status_code == 201, created.text
    transfer_id = created.json()["transfer_id"]

    units = client.get("/api/wms/units", headers=admin_h).json()
    moved = [u for u in units if u["product"] == "TXDOC-SKU5" and u["lot_code"] == "LOT-TXDOC5"]
    assert all(u["location"] is not None for u in moved)

    undo = client.post(f"/api/wms/transfers/{transfer_id}/undo", headers=admin_h)
    assert undo.status_code == 200, undo.text
    assert undo.json()["restored"] == 6
    assert undo.json()["skipped"] == 0

    units2 = client.get("/api/wms/units", headers=admin_h).json()
    restored = [u for u in units2 if u["product"] == "TXDOC-SKU5" and u["lot_code"] == "LOT-TXDOC5"]
    assert all(u["status"] == "stored" for u in restored)  # vẫn còn tồn kho — chỉ đổi vị trí, không mất hàng

    twice = client.post(f"/api/wms/transfers/{transfer_id}/undo", headers=admin_h)
    assert twice.status_code == 409, twice.text

    history = client.get("/api/wms/transfers", headers=admin_h).json()
    row = next(t for t in history if t["transfer_id"] == transfer_id)
    assert row["unit_count"] == 0
    assert row["lines"] == []


def test_undo_transfer_admin_only_after_confirm(client, admin_h, thukho_h, truongkho_tp_h):
    loc_a = _a_location(client, admin_h)
    loc_b = _a_location(client, admin_h)
    _a_units(client, admin_h, "TXDOC-SKU6", "LOT-TXDOC6", 2, loc_id=loc_a)
    created = client.post("/api/wms/transfers", headers=admin_h,
                          json={"to_location_id": loc_b,
                                "lines": [{"product_name": "TXDOC-SKU6", "lot_code": "LOT-TXDOC6",
                                          "unit_type": "vi", "quantity": 2}]})
    transfer_id = created.json()["transfer_id"]
    confirm = client.post(f"/api/wms/transfers/{transfer_id}/confirm", headers=truongkho_tp_h)
    assert confirm.status_code == 200, confirm.text

    denied = client.post(f"/api/wms/transfers/{transfer_id}/undo", headers=thukho_h)
    assert denied.status_code == 403, denied.text

    ok = client.post(f"/api/wms/transfers/{transfer_id}/undo", headers=admin_h)
    assert ok.status_code == 200, ok.text


def test_undo_transfer_skips_units_touched_by_later_operation(client, admin_h):
    """Đơn vị đã bị 1 phiếu điều chuyển KHÁC "chạm" vào sau đó thì Hoàn tác phiếu đầu không được
    trả lại (tránh sai vị trí) — báo "skipped" thay vì âm thầm trả nhầm."""
    loc_a = _a_location(client, admin_h)
    loc_b = _a_location(client, admin_h)
    loc_c = _a_location(client, admin_h)
    _a_units(client, admin_h, "TXDOC-SKU7", "LOT-TXDOC7", 3, loc_id=loc_a)

    first = client.post("/api/wms/transfers", headers=admin_h,
                        json={"to_location_id": loc_b,
                              "lines": [{"product_name": "TXDOC-SKU7", "lot_code": "LOT-TXDOC7",
                                        "unit_type": "vi", "quantity": 3}]})
    assert first.status_code == 201, first.text
    first_id = first.json()["transfer_id"]

    second = client.post("/api/wms/transfers", headers=admin_h,
                         json={"to_location_id": loc_c,
                               "lines": [{"product_name": "TXDOC-SKU7", "lot_code": "LOT-TXDOC7",
                                         "unit_type": "vi", "quantity": 3}]})
    assert second.status_code == 201, second.text

    undo_first = client.post(f"/api/wms/transfers/{first_id}/undo", headers=admin_h)
    assert undo_first.status_code == 409, undo_first.text
    assert "thay đổi" in undo_first.json()["detail"] or "hoàn tác trước đó" in undo_first.json()["detail"]


def test_update_transfer_note_blocked_after_confirm(client, admin_h, truongkho_tp_h):
    loc_a = _a_location(client, admin_h)
    loc_b = _a_location(client, admin_h)
    _a_units(client, admin_h, "TXDOC-SKU8", "LOT-TXDOC8", 1, loc_id=loc_a)
    created = client.post("/api/wms/transfers", headers=admin_h,
                          json={"to_location_id": loc_b,
                                "lines": [{"product_name": "TXDOC-SKU8", "lot_code": "LOT-TXDOC8",
                                          "unit_type": "vi", "quantity": 1}],
                                "driver_name": "Nguyễn Văn A", "vehicle_plate": "14C-99999"})
    transfer_id = created.json()["transfer_id"]

    edit = client.put(f"/api/wms/transfers/{transfer_id}", headers=admin_h,
                      json={"note": "Sửa lại ghi chú"})
    assert edit.status_code == 200, edit.text

    confirm = client.post(f"/api/wms/transfers/{transfer_id}/confirm", headers=truongkho_tp_h)
    assert confirm.status_code == 200, confirm.text

    edit_after = client.put(f"/api/wms/transfers/{transfer_id}", headers=admin_h,
                            json={"note": "Không được sửa nữa"})
    assert edit_after.status_code == 409, edit_after.text

    history = client.get("/api/wms/transfers", headers=admin_h).json()
    row = next(t for t in history if t["transfer_id"] == transfer_id)
    assert row["driver_name"] == "Nguyễn Văn A" and row["vehicle_plate"] == "14C-99999"
    assert row["note"] == "Sửa lại ghi chú"
