"""Test xuất kho theo phiếu (shipment), "nơi xuất đến" nay dùng chung danh mục Nhà cung cấp
(Supplier) — không còn catalog ship_to_location riêng (xem models/wms.py, migration
9a0b1c2d3e4f_ship_to_supplier_merge):
1) create_shipment: bắt buộc ship_to_id (= supplier_id) + ít nhất 1 unit; mỗi vỉ/keg là 1 đơn
   vị tồn kho độc lập nguyên vẹn (không xuất một phần 1 vỉ/keg) — 1 phiếu có thể chọn nhiều
   unit từ nhiều sản phẩm/lô khác nhau cùng lúc. Xóa Supplier bị chặn nếu đã có phiếu xuất kho
   nào từng dùng nó (xem services/master_data.py::delete_supplier) — CRUD Supplier chung đã có
   test riêng ở test_lot_auto_code.py, ở đây chỉ test guard xóa khi đã dùng làm ship_to.
2) Bug fix approve_bottle: pack_size phải lấy từ FinishedProduct, không còn hardcode."""

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
def vanhanh_h(client):
    return _login(client, "vanhanh", "123456")


@pytest.fixture(scope="module")
def kcs_h(client):
    return _login(client, "kcs", "123456")


@pytest.fixture(scope="module")
def thukho_h(client):
    return _login(client, "thukho", "123456")


@pytest.fixture(scope="module")
def truongkho_tp_h(client):
    return _login(client, "truongkho_tp", "123456")


def _a_location(client, admin_h):
    loc = client.post("/api/wms/locations", headers=admin_h,
                      json={"code": f"LOC-{str(int(time.time() * 1000))[-8:]}", "name": "Test loc", "capacity": 50})
    assert loc.status_code == 201, loc.text
    return loc.json()["loc_id"]


def _a_ship_to(client, admin_h, code, name="NPP test"):
    """Nơi xuất đến nay dùng chung danh mục Nhà cung cấp (Supplier) — xem module docstring."""
    st = client.post("/api/suppliers", headers=admin_h, json={"code": code, "name": name})
    assert st.status_code == 201, st.text
    return st.json()["supplier_id"]


def _a_units(client, admin_h, product, lot_code, count):
    """Sinh 1 dòng LÔ (product, lot_code) với quantity=`count` (pack_size=1 nên quantity =
    số vỉ luôn) — dưới mô hình mới (docs/WMS-LOT-LEVEL-REDESIGN.md) build_units chỉ sinh
    ĐÚNG 1 dòng/lô bất kể count lớn cỡ nào (không còn N dòng độc lập như trước). "Nhập kho thủ
    công" (build_units không is_opening_balance) giờ cần Trưởng bộ phận kho duyệt trước khi
    xuất được (source="manual", xem _consume_lot_rows(block_pending_manual=True)) — helper này
    tự động duyệt luôn ngay sau khi tạo để các test khác (xuất/điều chuyển/phân rã...) không bị
    chặn oan, vì mục đích của helper chỉ là dựng sẵn tồn kho, không phải test bước duyệt đó
    (bước duyệt có test riêng, xem test_wms_receipt_approve.py)."""
    build = client.post("/api/wms/units", headers=admin_h,
                        json={"product_name": product, "lot_code": lot_code, "total": count, "pack_size": 1})
    assert build.status_code == 201, build.text
    assert len(build.json()["unit_codes"]) == 1
    code = build.json()["unit_codes"][0]
    confirm = client.post("/api/wms/units/confirm-receipt-by-lot", headers=admin_h,
                          json={"product_name": product, "lot_code": lot_code, "unit_type": "vi"})
    assert confirm.status_code == 200, confirm.text
    units = client.get("/api/wms/units", headers=admin_h).json()
    return next(u["unit_id"] for u in units if u["unit_code"] == code)


def _lot_units(client, admin_h, product, lot_code):
    """Mọi dòng hiện có của (product, lot_code) — có thể >1 dòng nếu đã bị TÁCH do xuất/điều
    chuyển MỘT PHẦN (xem services/wms.py::_consume_lot_rows)."""
    units = client.get("/api/wms/units", headers=admin_h).json()
    return [u for u in units if u["product"] == product and u["lot_code"] == lot_code]


def _declare_pending(client, headers, stage, scope_type, scope_id, product_id=None):
    q = f"/api/brewing/qc-status?stage={stage}&scope_type={scope_type}&scope_id={scope_id}"
    if product_id:
        q += f"&product_id={product_id}"
    status = client.get(q, headers=headers).json()
    for p in status["required"]:
        if p["code"] in status["pending"]:
            lsl = p["lsl"] if p["lsl"] is not None else 0
            usl = p["usl"] if p["usl"] is not None else lsl + 10
            r = client.post("/api/brewing/qc-results", headers=headers,
                            json={"stage": stage, "scope_type": scope_type, "scope_id": scope_id,
                                  "parameter": p["code"], "value": (lsl + usl) / 2,
                                  "lower_limit": lsl, "upper_limit": usl})
            assert r.status_code == 201, r.text


def test_create_shipment_requires_ship_to_and_units(client, admin_h):
    _a_units(client, admin_h, "SHIPTEST-SKU", "LOT-SHIPTEST", 2)

    missing_ship_to = client.post("/api/wms/shipments", headers=admin_h,
                                  json={"ship_to_id": "",
                                        "lines": [{"product_name": "SHIPTEST-SKU", "lot_code": "LOT-SHIPTEST",
                                                  "unit_type": "vi", "quantity": 1}]})
    assert missing_ship_to.status_code == 409, missing_ship_to.text

    ship_to_id = _a_ship_to(client, admin_h, "DIST-NOLINES")
    empty_units = client.post("/api/wms/shipments", headers=admin_h, json={"ship_to_id": ship_to_id, "lines": []})
    assert empty_units.status_code == 409, empty_units.text


def test_shipment_marks_units_shipped(client, admin_h):
    ship_to_id = _a_ship_to(client, admin_h, "DIST-FULL", "NPP Full")
    _a_units(client, admin_h, "FULL-SKU", "LOT-FULL", 10)

    shipped = client.post("/api/wms/shipments", headers=admin_h,
                          json={"ship_to_id": ship_to_id,
                                "lines": [{"product_name": "FULL-SKU", "lot_code": "LOT-FULL",
                                          "unit_type": "vi", "quantity": 10}]})
    assert shipped.status_code == 201, shipped.text
    assert shipped.json()["ship_to_code"] == "DIST-FULL"
    assert shipped.json()["fifo_ok"] is True  # duy nhất 1 lô của SP này -> luôn đúng FIFO

    # Xuất HẾT (10/10) -> dòng gốc chuyển thẳng "shipped" (không tách dòng — chỉ tách khi xuất
    # MỘT PHẦN, xem docs/WMS-LOT-LEVEL-REDESIGN.md).
    rows = _lot_units(client, admin_h, "FULL-SKU", "LOT-FULL")
    assert len(rows) == 1
    assert rows[0]["status"] == "shipped"
    assert rows[0]["shipped_at"] is not None
    assert rows[0]["ship_to_code"] == "DIST-FULL"

    # Xuất lại (đã hết tồn) phải báo lỗi.
    twice = client.post("/api/wms/shipments", headers=admin_h,
                        json={"ship_to_id": ship_to_id,
                              "lines": [{"product_name": "FULL-SKU", "lot_code": "LOT-FULL",
                                        "unit_type": "vi", "quantity": 1}]})
    assert twice.status_code == 409, twice.text


def test_partial_shipment_keeps_remaining_units_stored(client, admin_h):
    ship_to_id = _a_ship_to(client, admin_h, "DIST-PARTIAL", "NPP Partial")
    _a_units(client, admin_h, "PARTIAL-SKU", "LOT-PARTIAL", 10)

    shipped = client.post("/api/wms/shipments", headers=admin_h,
                          json={"ship_to_id": ship_to_id,
                                "lines": [{"product_name": "PARTIAL-SKU", "lot_code": "LOT-PARTIAL",
                                          "unit_type": "vi", "quantity": 4}]})
    assert shipped.status_code == 201, shipped.text
    assert shipped.json()["fifo_ok"] is True

    # Xuất MỘT PHẦN (4/10) -> dòng gốc bị TÁCH: 1 dòng mới "shipped" (quantity=4) + dòng gốc
    # co lại còn "stored" (quantity=6) — không còn N dòng độc lập như trước.
    rows = _lot_units(client, admin_h, "PARTIAL-SKU", "LOT-PARTIAL")
    shipped_rows = [r for r in rows if r["status"] == "shipped"]
    stored_rows = [r for r in rows if r["status"] != "shipped"]
    assert sum(r["quantity"] for r in shipped_rows) == 4
    assert sum(r["quantity"] for r in stored_rows) == 6
    for r in stored_rows:
        assert r["shipped_at"] is None
        assert r["ship_to_code"] is None

    # Vẫn tra được nơi xuất đến qua Truy xuôi cho unit đã xuất (lịch sử nằm ở genealogy edge).
    shipped_unit_code = shipped_rows[0]["unit_code"]
    fwd = client.get(f"/api/trace/forward?code={shipped_unit_code}", headers=admin_h)
    assert fwd.status_code == 200, fwd.text
    codes = {c["code"] for c in fwd.json().get("children", [])}
    assert "DIST-PARTIAL" in codes


def test_shipment_with_multiple_lot_units(client, admin_h):
    ship_to_id = _a_ship_to(client, admin_h, "DIST-MULTI", "NPP Multi")
    _a_units(client, admin_h, "MULTI-SKU", "LOT-A", 10)
    _a_units(client, admin_h, "MULTI-SKU", "LOT-B", 10)

    shipped = client.post("/api/wms/shipments", headers=admin_h,
                          json={"ship_to_id": ship_to_id,
                                "lines": [{"product_name": "MULTI-SKU", "lot_code": "LOT-A",
                                          "unit_type": "vi", "quantity": 6},
                                         {"product_name": "MULTI-SKU", "lot_code": "LOT-B",
                                          "unit_type": "vi", "quantity": 3}]})
    assert shipped.status_code == 201, shipped.text
    # Lô A (cũ hơn) vẫn còn dư 4 vỉ sau phiếu này trong khi lô B (mới hơn) cũng bị lấy
    # -> vi phạm thứ tự FIFO dù chính A cũng có trong phiếu.
    assert shipped.json()["fifo_ok"] is False

    rows_a = _lot_units(client, admin_h, "MULTI-SKU", "LOT-A")
    rows_b = _lot_units(client, admin_h, "MULTI-SKU", "LOT-B")
    assert sum(r["quantity"] for r in rows_a if r["status"] != "shipped") == 4
    assert sum(r["quantity"] for r in rows_b if r["status"] != "shipped") == 7

    history = client.get("/api/wms/shipments", headers=admin_h).json()
    ship = next(s for s in history if s["ship_to_code"] == "DIST-MULTI")
    assert ship["unit_count"] == 9
    assert ship["fifo_ok"] is False


def test_shipment_fifo_ok_when_older_lot_fully_exhausted(client, admin_h):
    ship_to_id = _a_ship_to(client, admin_h, "DIST-FIFOOK", "NPP FifoOk")
    _a_units(client, admin_h, "FIFOOK-SKU", "LOT-A", 5)
    _a_units(client, admin_h, "FIFOOK-SKU", "LOT-B", 5)

    # Lấy HẾT lô cũ hơn (A) rồi mới lấy thêm ở lô mới hơn (B) -> đúng FIFO.
    shipped = client.post("/api/wms/shipments", headers=admin_h,
                          json={"ship_to_id": ship_to_id,
                                "lines": [{"product_name": "FIFOOK-SKU", "lot_code": "LOT-A",
                                          "unit_type": "vi", "quantity": 5},
                                         {"product_name": "FIFOOK-SKU", "lot_code": "LOT-B",
                                          "unit_type": "vi", "quantity": 2}]})
    assert shipped.status_code == 201, shipped.text
    assert shipped.json()["fifo_ok"] is True

    history = client.get("/api/wms/shipments", headers=admin_h).json()
    ship = next(s for s in history if s["ship_to_code"] == "DIST-FIFOOK")
    assert ship["fifo_ok"] is True


def test_shipment_fifo_ok_false_when_older_lot_skipped(client, admin_h):
    ship_to_id = _a_ship_to(client, admin_h, "DIST-FIFOBAD", "NPP FifoBad")
    _a_units(client, admin_h, "FIFOBAD-SKU", "LOT-A", 5)
    _a_units(client, admin_h, "FIFOBAD-SKU", "LOT-B", 5)

    # Bỏ qua lô A (cũ hơn) hoàn toàn, chỉ lấy ở B (mới hơn) -> vi phạm FIFO.
    shipped = client.post("/api/wms/shipments", headers=admin_h,
                          json={"ship_to_id": ship_to_id,
                                "lines": [{"product_name": "FIFOBAD-SKU", "lot_code": "LOT-B",
                                          "unit_type": "vi", "quantity": 2}]})
    assert shipped.status_code == 201, shipped.text
    assert shipped.json()["fifo_ok"] is False

    history = client.get("/api/wms/shipments", headers=admin_h).json()
    ship = next(s for s in history if s["ship_to_code"] == "DIST-FIFOBAD")
    assert ship["fifo_ok"] is False


def test_ship_to_delete_blocked_when_used_by_shipment(client, admin_h):
    ship_to_id = _a_ship_to(client, admin_h, "DIST-REF")
    _a_units(client, admin_h, "REF-SKU", "LOT-REF", 5)
    shipped = client.post("/api/wms/shipments", headers=admin_h,
                          json={"ship_to_id": ship_to_id,
                                "lines": [{"product_name": "REF-SKU", "lot_code": "LOT-REF",
                                          "unit_type": "vi", "quantity": 2}]})
    assert shipped.status_code == 201, shipped.text

    blocked = client.delete(f"/api/suppliers/{ship_to_id}", headers=admin_h)
    assert blocked.status_code == 409, blocked.text


def test_approve_bottle_uses_finished_product_pack_size(client, admin_h, vanhanh_h, kcs_h):
    suffix = "UPCFIX01"
    fp = client.post("/api/finished-products", headers=admin_h,
                     json={"code": f"SKU-{suffix}", "name": "SKU test 20 lon", "uom": "lon", "pack_size": 20})
    assert fp.status_code == 201, fp.text
    fp_id = fp.json()["finished_product_id"]

    bottle_code = f"CH-{suffix}"
    b = client.post("/api/brewing/bottles", headers=vanhanh_h,
                    json={"bottle_code": bottle_code, "beer_type": "Bia test", "finished_product_id": fp_id})
    assert b.status_code == 201, b.text
    bottle_id = b.json()["bottle_id"]
    b_fin = client.post(f"/api/brewing/bottles/{bottle_id}/finish", headers=vanhanh_h, json={"ca1": 100})
    assert b_fin.status_code == 200, b_fin.text

    _declare_pending(client, admin_h, "thanh_pham", "bottle", f"{bottle_code}__thanh_pham")
    # Duyệt nhập kho thành phẩm nay thuộc quyền Giám đốc/Phó GĐ Sản xuất (production.release_to_wms),
    # tách khỏi quality.release của KCS — dùng admin_h (bypass mọi permission) thay vì kcs_h ở đây.
    approve = client.post(f"/api/brewing/bottles/{bottle_id}/approve", headers=admin_h)
    assert approve.status_code == 200, approve.text
    # Ca 1/2/3 tính theo VỈ — ca1=100 vỉ x 20 lon/vỉ (pack_size) = 2000 lon, dồn vào 1 dòng lô
    # duy nhất (xem docs/WMS-LOT-LEVEL-REDESIGN.md).
    assert approve.json()["count"] == 100

    units = client.get("/api/wms/units", headers=admin_h).json()
    made = [u for u in units if u["unit_code"] in approve.json()["unit_codes"]]
    assert len(made) == 1
    assert made[0]["quantity"] == 2000


def test_shipment_slip_header_fields_persist(client, admin_h):
    """Các trường in "PHIẾU XUẤT KHO" (Mẫu 02-VT) — người nhận/lái xe/biển số/địa điểm/lý do —
    phải lưu lại đúng và trả về qua GET /wms/shipments để in lại sau này. Riêng "Xuất tại kho"
    không còn nhập tay — hệ thống tự suy ra từ vị trí (WmsLocation) đang lưu các vỉ/keg được
    chọn để xuất (xem services/wms.py::create_shipment)."""
    ship_to_id = _a_ship_to(client, admin_h, "DIST-SLIP", "NPP Slip")
    unit_id = _a_units(client, admin_h, "SLIP-SKU", "LOT-SLIP", 5)
    loc_id = _a_location(client, admin_h)
    loc_code = client.get("/api/wms/locations", headers=admin_h).json()
    loc_code = next(l["code"] for l in loc_code if l["loc_id"] == loc_id)
    pa = client.post(f"/api/wms/units/{unit_id}/putaway", headers=admin_h, json={"loc_id": loc_id})
    assert pa.status_code == 200, pa.text

    shipped = client.post("/api/wms/shipments", headers=admin_h, json={
        "ship_to_id": ship_to_id,
        "lines": [{"product_name": "SLIP-SKU", "lot_code": "LOT-SLIP", "unit_type": "vi", "quantity": 5}],
        "note": "Giao hàng đại lý", "recipient_name": "Phạm Ngọc Linh",
        "recipient_dept": "Phòng kinh doanh", "driver_name": "Nguyễn Văn Lái",
        "vehicle_plate": "14C-123.45",
        "delivery_place": "Hạ Long",
    })
    assert shipped.status_code == 201, shipped.text
    assert shipped.json()["shipment_id"]

    history = client.get("/api/wms/shipments", headers=admin_h).json()
    row = next(s for s in history if s["shipment_id"] == shipped.json()["shipment_id"])
    assert row["note"] == "Giao hàng đại lý"
    assert row["recipient_name"] == "Phạm Ngọc Linh"
    assert row["recipient_dept"] == "Phòng kinh doanh"
    assert row["driver_name"] == "Nguyễn Văn Lái"
    assert row["vehicle_plate"] == "14C-123.45"
    assert row["from_location"] == f"{loc_code} - Test loc"
    assert row["delivery_place"] == "Hạ Long"


def test_undo_shipment_restores_units_and_blocks_twice(client, admin_h):
    ship_to_id = _a_ship_to(client, admin_h, "DIST-UNDO", "NPP Undo")
    unit_id = _a_units(client, admin_h, "UNDO-SKU", "LOT-UNDO", 5)

    shipped = client.post("/api/wms/shipments", headers=admin_h,
                          json={"ship_to_id": ship_to_id,
                                "lines": [{"product_name": "UNDO-SKU", "lot_code": "LOT-UNDO",
                                          "unit_type": "vi", "quantity": 5}]})
    assert shipped.status_code == 201, shipped.text
    shipment_id = shipped.json()["shipment_id"]

    units_after_ship = client.get("/api/wms/units", headers=admin_h).json()
    assert next(u for u in units_after_ship if u["unit_id"] == unit_id)["status"] == "shipped"

    undone = client.post(f"/api/wms/shipments/{shipment_id}/undo", headers=admin_h)
    assert undone.status_code == 200, undone.text
    assert undone.json()["restored"] == 5

    units_after_undo = client.get("/api/wms/units", headers=admin_h).json()
    row = next(u for u in units_after_undo if u["unit_id"] == unit_id)
    assert row["status"] == "stored"
    assert row["shipped_at"] is None

    # Hoàn tác lần 2 phải báo lỗi (không còn unit nào tham chiếu phiếu này nữa).
    twice = client.post(f"/api/wms/shipments/{shipment_id}/undo", headers=admin_h)
    assert twice.status_code == 409, twice.text

    history = client.get("/api/wms/shipments", headers=admin_h).json()
    row = next(s for s in history if s["shipment_id"] == shipment_id)
    assert row["unit_count"] == 0
    assert row["lines"] == []

    # Xuất lại được bình thường sau khi đã hoàn tác (tồn đã về "stored").
    reshipped = client.post("/api/wms/shipments", headers=admin_h,
                            json={"ship_to_id": ship_to_id,
                                  "lines": [{"product_name": "UNDO-SKU", "lot_code": "LOT-UNDO",
                                            "unit_type": "vi", "quantity": 5}]})
    assert reshipped.status_code == 201, reshipped.text


def test_undo_shipment_not_found(client, admin_h):
    r = client.post("/api/wms/shipments/does-not-exist/undo", headers=admin_h)
    assert r.status_code == 404, r.text


def test_confirm_shipment_blocks_undo_except_admin(client, admin_h, thukho_h, truongkho_tp_h):
    ship_to_id = _a_ship_to(client, admin_h, "DIST-CONFIRM", "NPP Confirm")
    _a_units(client, admin_h, "CONFIRM-SKU", "LOT-CONFIRM", 5)

    shipped = client.post("/api/wms/shipments", headers=admin_h,
                          json={"ship_to_id": ship_to_id,
                                "lines": [{"product_name": "CONFIRM-SKU", "lot_code": "LOT-CONFIRM",
                                          "unit_type": "vi", "quantity": 5}]})
    assert shipped.status_code == 201, shipped.text
    shipment_id = shipped.json()["shipment_id"]

    # trước khi xác nhận, thủ kho vẫn hoàn tác được bình thường
    denied_confirm = client.post(f"/api/wms/shipments/{shipment_id}/confirm", headers=thukho_h)
    assert denied_confirm.status_code == 403, denied_confirm.text

    confirm = client.post(f"/api/wms/shipments/{shipment_id}/confirm", headers=truongkho_tp_h)
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["confirmed_by"] == "truongkho_tp"

    # xác nhận 2 lần phải báo lỗi
    twice = client.post(f"/api/wms/shipments/{shipment_id}/confirm", headers=truongkho_tp_h)
    assert twice.status_code == 409, twice.text

    history = client.get("/api/wms/shipments", headers=admin_h).json()
    row = next(s for s in history if s["shipment_id"] == shipment_id)
    assert row["confirmed_by"] == "truongkho_tp"

    # đã xác nhận — không phải admin thì không hoàn tác được nữa
    denied_undo = client.post(f"/api/wms/shipments/{shipment_id}/undo", headers=thukho_h)
    assert denied_undo.status_code == 403, denied_undo.text

    undo = client.post(f"/api/wms/shipments/{shipment_id}/undo", headers=admin_h)
    assert undo.status_code == 200, undo.text
    assert undo.json()["restored"] == 5
