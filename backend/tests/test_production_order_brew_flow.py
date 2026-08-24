"""Mã nấu (BrewRecord) tạo qua "Lệnh SX (ERP)" (ProductionOrder) thay vì "Lệnh nấu" (BrewOrder)
cũ — xem services/orders.py::mark_in_progress/recompute_status_after_finish:

1) add_brew chấp nhận production_order_id thay brew_order_id — bắt buộc đúng 1 trong 2. Lệnh SX
   (ERP) giờ chỉ chọn Loại bia lúc lập (product_id luôn None) nên phải truyền product_id trực
   tiếp trong payload (chỉ tự lấy từ Lệnh SX nếu lệnh đó đã có sẵn product_id — dữ liệu lịch sử).
   Chặn khi lệnh đã "completed".
2) Lệnh SX tự chuyển released -> in_progress khi có mã nấu đầu tiên.
3) Lệnh SX tự chuyển in_progress -> completed khi sản lượng thực tế (đo qua BrewProcessLog,
   không phải volume_hl nhập tay) đạt kế hoạch (quy đổi hl theo uom) trừ sai số CHUNG
   (ops_setting.erp_order_volume_tolerance_hl, KHÔNG còn theo từng lệnh như BrewOrder).
4) ops-settings round-trip cho field erp_order_volume_tolerance_hl mới."""

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
    return _login(client, "vanhanh", "123456")


@pytest.fixture(scope="module")
def lager_product_id(client, admin_h):
    products = client.get("/api/products", headers=admin_h).json()
    return next(p["product_id"] for p in products if p["code"] == "BIA-LAGER")


@pytest.fixture(scope="module")
def lager_beer_type_id(client, admin_h, lager_product_id):
    products = client.get("/api/products", headers=admin_h).json()
    return next(p["beer_type_id"] for p in products if p["product_id"] == lager_product_id)


def _a_brewhouse_line(client, admin_h):
    existing = client.get("/api/lines", headers=admin_h, params={"kind": "brewhouse"}).json()
    if existing:
        return existing[0]["line_id"]
    r = client.post("/api/lines", headers=admin_h,
                    json={"code": "BREW-POFLOW-01", "name": "Nhà nấu test", "kind": "brewhouse"})
    assert r.status_code == 201, r.text
    return r.json()["line_id"]


@pytest.fixture(scope="module")
def brewhouse_line_id(client, admin_h):
    return _a_brewhouse_line(client, admin_h)


def _a_production_order(client, admin_h, code, beer_type_id, planned_qty=10000, uom="L"):
    r = client.post("/api/orders", headers=admin_h, json={
        "order_code": code, "beer_type_id": beer_type_id, "planned_qty": planned_qty, "uom": uom})
    assert r.status_code == 201, r.text
    return r.json()


def _set_real_actual_volume(client, admin_h, brew_id, batch_code, volume_hl, line_id, finish=True):
    b = client.post(f"/api/brewing/brews/{brew_id}/batches", headers=admin_h,
                    json={"batch_code": batch_code, "line_id": line_id})
    assert b.status_code == 201, b.text
    batch_id = b.json()["batch_id"]
    p = client.put(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/process-log", headers=admin_h,
                   json={"whp_tong_luong_dich_hl": volume_hl})
    assert p.status_code == 200, p.text
    if finish:
        f = client.post(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/finish", headers=admin_h)
        assert f.status_code == 200, f.text
    return batch_id


def test_add_brew_requires_exactly_one_order_field(client, admin_h, vanhanh_h, lager_beer_type_id):
    order = _a_production_order(client, admin_h, "PO-FLOW-001", lager_beer_type_id)

    neither = client.post("/api/brewing/brews", headers=vanhanh_h,
                          json={"brew_code": "BR-POFLOW-NEITHER", "wort_type": "Dịch test"})
    assert neither.status_code == 409, neither.text

    both = client.post("/api/brewing/brews", headers=vanhanh_h,
                       json={"brew_code": "BR-POFLOW-BOTH", "wort_type": "Dịch test",
                             "brew_order_id": "x", "production_order_id": order["order_id"]})
    assert both.status_code == 409, both.text

    bogus = client.post("/api/brewing/brews", headers=vanhanh_h,
                        json={"brew_code": "BR-POFLOW-BOGUS", "wort_type": "Dịch test",
                              "production_order_id": "does-not-exist"})
    assert bogus.status_code == 404, bogus.text


def test_add_brew_accepts_explicit_product_id_and_moves_order_in_progress(
        client, admin_h, vanhanh_h, lager_product_id, lager_beer_type_id):
    order = _a_production_order(client, admin_h, "PO-FLOW-002", lager_beer_type_id)
    assert order["status"] == "released"

    # Lệnh SX (ERP) chỉ chọn Loại bia lúc lập (product_id luôn None) — phải truyền product_id
    # trực tiếp ở đây, add_brew không còn gì để tự suy ra.
    ok = client.post("/api/brewing/brews", headers=vanhanh_h,
                     json={"brew_code": "BR-POFLOW-002", "wort_type": "Dịch test",
                           "product_id": lager_product_id,
                           "production_order_id": order["order_id"]})
    assert ok.status_code == 201, ok.text
    assert ok.json()["product_id"] == lager_product_id
    assert ok.json()["production_order_id"] == order["order_id"]
    assert ok.json()["brew_order_id"] is None

    got = client.get(f"/api/orders/{order['order_id']}", headers=admin_h).json()
    assert got["status"] == "in_progress"


def test_deleting_last_brew_reverts_order_to_released(client, admin_h, vanhanh_h, lager_beer_type_id):
    """Xóa mã nấu DUY NHẤT của 1 Lệnh SX (ERP) phải lùi status về lại "released" — khác
    BrewOrder (tự tính is_complete/is_executed sống mỗi lần xem, không có status lưu cứng),
    ProductionOrder.status là field lưu cứng nên phải tự lùi lại khi hết mã nấu, không được
    kẹt ở "in_progress" dù thực tế không còn mã nấu nào (xem services/orders.py::
    recompute_status_after_delete)."""
    order = _a_production_order(client, admin_h, "PO-FLOW-002B", lager_beer_type_id)
    ok = client.post("/api/brewing/brews", headers=vanhanh_h,
                     json={"brew_code": "BR-POFLOW-002B", "wort_type": "Dịch test",
                           "production_order_id": order["order_id"]})
    assert ok.status_code == 201, ok.text
    brew_id = ok.json()["brew_id"]
    assert client.get(f"/api/orders/{order['order_id']}", headers=admin_h).json()["status"] == "in_progress"

    d = client.delete(f"/api/brewing/brews/{brew_id}", headers=vanhanh_h)
    assert d.status_code == 204, d.text

    got = client.get(f"/api/orders/{order['order_id']}", headers=admin_h).json()
    assert got["status"] == "released"


def test_deleting_one_of_two_brews_reverts_completed_to_in_progress(
        client, admin_h, vanhanh_h, lager_beer_type_id, brewhouse_line_id):
    """Xóa 1 trong 2 mã nấu khiến sản lượng thực tế rớt dưới ngưỡng -> lùi từ "completed" về
    "in_progress" (còn mã nấu khác nên KHÔNG về "released")."""
    order = _a_production_order(client, admin_h, "PO-FLOW-002C", lager_beer_type_id, planned_qty=10000, uom="L")
    # Tạo cả 2 mã nấu TRƯỚC khi mã nào đạt ngưỡng (order còn in_progress) — nếu finish mã đầu
    # tới ngay ngưỡng hoàn thành thì add_brew mã thứ 2 sẽ bị chặn (lệnh đã "completed").
    b1 = client.post("/api/brewing/brews", headers=vanhanh_h,
                     json={"brew_code": "BR-POFLOW-002C-A", "wort_type": "Dịch test",
                           "production_order_id": order["order_id"]})
    assert b1.status_code == 201, b1.text
    b2 = client.post("/api/brewing/brews", headers=vanhanh_h,
                     json={"brew_code": "BR-POFLOW-002C-B", "wort_type": "Dịch test",
                           "production_order_id": order["order_id"]})
    assert b2.status_code == 201, b2.text
    b2_id = b2.json()["brew_id"]

    _set_real_actual_volume(client, admin_h, b1.json()["brew_id"], "701", 50, brewhouse_line_id)
    assert client.get(f"/api/orders/{order['order_id']}", headers=admin_h).json()["status"] == "in_progress"
    _set_real_actual_volume(client, admin_h, b2_id, "702", 50, brewhouse_line_id)
    assert client.get(f"/api/orders/{order['order_id']}", headers=admin_h).json()["status"] == "completed"

    d = client.delete(f"/api/brewing/brews/{b2_id}", headers=vanhanh_h)
    assert d.status_code == 204, d.text

    got = client.get(f"/api/orders/{order['order_id']}", headers=admin_h).json()
    assert got["status"] == "in_progress"


def test_add_brew_blocked_once_order_completed(client, admin_h, vanhanh_h, lager_beer_type_id, brewhouse_line_id):
    order = _a_production_order(client, admin_h, "PO-FLOW-003", lager_beer_type_id, planned_qty=9600, uom="L")
    b1 = client.post("/api/brewing/brews", headers=vanhanh_h,
                     json={"brew_code": "BR-POFLOW-003", "wort_type": "Dịch test",
                           "production_order_id": order["order_id"]})
    assert b1.status_code == 201, b1.text
    _set_real_actual_volume(client, admin_h, b1.json()["brew_id"], "601", 96, brewhouse_line_id)

    got = client.get(f"/api/orders/{order['order_id']}", headers=admin_h).json()
    assert got["status"] == "completed"

    blocked = client.post("/api/brewing/brews", headers=vanhanh_h,
                          json={"brew_code": "BR-POFLOW-003B", "wort_type": "Dịch test",
                                "production_order_id": order["order_id"]})
    assert blocked.status_code == 409, blocked.text


def test_order_not_complete_while_shortfall_exceeds_tolerance(client, admin_h, vanhanh_h, lager_beer_type_id, brewhouse_line_id):
    order = _a_production_order(client, admin_h, "PO-FLOW-004", lager_beer_type_id, planned_qty=10000, uom="L")
    b1 = client.post("/api/brewing/brews", headers=vanhanh_h,
                     json={"brew_code": "BR-POFLOW-004", "wort_type": "Dịch test",
                           "production_order_id": order["order_id"]})
    assert b1.status_code == 201, b1.text
    # Kế hoạch quy hl = 100hl, sai số mặc định 5hl -> 80hl vẫn còn thiếu quá sai số.
    _set_real_actual_volume(client, admin_h, b1.json()["brew_id"], "602", 80, brewhouse_line_id)

    got = client.get(f"/api/orders/{order['order_id']}", headers=admin_h).json()
    assert got["status"] == "in_progress"

    # Vẫn thêm được mã nấu thứ 2 vì lệnh chưa hoàn thành.
    again = client.post("/api/brewing/brews", headers=vanhanh_h,
                        json={"brew_code": "BR-POFLOW-004B", "wort_type": "Dịch test",
                              "production_order_id": order["order_id"]})
    assert again.status_code == 201, again.text


def test_multiple_brews_accumulate_volume_for_same_order(client, admin_h, vanhanh_h, lager_beer_type_id, brewhouse_line_id):
    order = _a_production_order(client, admin_h, "PO-FLOW-005", lager_beer_type_id, planned_qty=10000, uom="L")
    b1 = client.post("/api/brewing/brews", headers=vanhanh_h,
                     json={"brew_code": "BR-POFLOW-005A", "wort_type": "Dịch test",
                           "production_order_id": order["order_id"]})
    assert b1.status_code == 201, b1.text
    _set_real_actual_volume(client, admin_h, b1.json()["brew_id"], "603", 50, brewhouse_line_id)

    mid = client.get(f"/api/orders/{order['order_id']}", headers=admin_h).json()
    assert mid["status"] == "in_progress"

    b2 = client.post("/api/brewing/brews", headers=vanhanh_h,
                     json={"brew_code": "BR-POFLOW-005B", "wort_type": "Dịch test",
                           "production_order_id": order["order_id"]})
    assert b2.status_code == 201, b2.text
    _set_real_actual_volume(client, admin_h, b2.json()["brew_id"], "604", 50, brewhouse_line_id)

    done = client.get(f"/api/orders/{order['order_id']}", headers=admin_h).json()
    assert done["status"] == "completed"


def test_legacy_brew_order_path_still_works(client, admin_h, vanhanh_h, lager_product_id):
    """brew_order_id (đường đi cũ, tab Lệnh nấu lịch sử) vẫn hoạt động y hệt trước đây."""
    order = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": "LN-POFLOW-LEGACY", "product_id": lager_product_id,
        "planned_volume_hl": 100, "auto_from_bom": False})
    assert order.status_code == 201, order.text
    order_id = order.json()["brew_order_id"]

    ok = client.post("/api/brewing/brews", headers=vanhanh_h,
                     json={"brew_code": "BR-POFLOW-LEGACY", "wort_type": "Dịch test",
                           "brew_order_id": order_id})
    assert ok.status_code == 201, ok.text
    assert ok.json()["brew_order_id"] == order_id
    assert ok.json()["production_order_id"] is None


def test_ops_settings_erp_tolerance_round_trip(client, admin_h):
    current = client.get("/api/ops-settings", headers=admin_h).json()
    assert current["erp_order_volume_tolerance_hl"] == pytest.approx(5.0)

    payload = dict(current)
    payload["erp_order_volume_tolerance_hl"] = 12.5
    r = client.put("/api/ops-settings", headers=admin_h, json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["erp_order_volume_tolerance_hl"] == pytest.approx(12.5)

    refetched = client.get("/api/ops-settings", headers=admin_h).json()
    assert refetched["erp_order_volume_tolerance_hl"] == pytest.approx(12.5)
