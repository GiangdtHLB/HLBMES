"""Test 4 tính năng mới: (1) cảnh báo tồn tối thiểu (Material.stock_min/low_stock), (2)
kiểm kê định kỳ (StockCount/StockCountLine đối chiếu tồn hệ thống vs thực tế), (3) nhập bia
cận date (tự nhận lô chiết theo ngày giờ + lịch sử riêng + xuất kho lọc theo cận date), (4)
cảnh báo cần xử lý gộp trên Dashboard (QC hold + CAPA quá hạn + hiệu chuẩn sắp/đã quá hạn).
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


@pytest.fixture(scope="module")
def thukho_h(client):
    return _login(client, "thukho", "123456")


@pytest.fixture(scope="module")
def vanhanh_h(client):
    return _login(client, "vanhanh", "123456")


@pytest.fixture(scope="module")
def quandoc_h(client):
    return _login(client, "quandoc", "123456")


def _create_material(client, admin_h, code, stock_min=None):
    payload = {"code": code, "name": f"Vật tư {code}", "uom": "kg", "category": "other"}
    if stock_min is not None:
        payload["stock_min"] = stock_min
    r = client.post("/api/materials", headers=admin_h, json=payload)
    assert r.status_code == 201, r.text
    return r.json()["material_id"]


def _stock_row(client, admin_h, material_id):
    rows = client.get("/api/warehouse/stock", headers=admin_h).json()
    return next(r for r in rows if r["material_id"] == material_id)


# ---- 1. Cảnh báo tồn tối thiểu ----

def test_low_stock_flag_toggles_with_on_hand(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "STKMIN-01", stock_min=50)

    r = client.post("/api/warehouse/receive", headers=thukho_h,
                    json={"material_id": mat_id, "quantity": 30, "uom": "kg"})
    assert r.status_code == 200, r.text
    row = _stock_row(client, admin_h, mat_id)
    assert row["stock_min"] == 50
    assert row["low_stock"] is True

    r2 = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"material_id": mat_id, "quantity": 30, "uom": "kg"})
    assert r2.status_code == 200, r2.text
    row2 = _stock_row(client, admin_h, mat_id)
    assert row2["on_hand"] == 60
    assert row2["low_stock"] is False


def test_no_stock_min_never_flags_low_stock(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "STKMIN-NONE")
    r = client.post("/api/warehouse/receive", headers=thukho_h,
                    json={"material_id": mat_id, "quantity": 1, "uom": "kg"})
    assert r.status_code == 200, r.text
    row = _stock_row(client, admin_h, mat_id)
    assert row["stock_min"] is None
    assert row["low_stock"] is False


# ---- 2. Kiểm kê định kỳ ----

def test_cycle_count_reconciles_variance(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "KK-MAT-01")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "KK-LOT-01", "material_id": mat_id, "quantity": 100, "uom": "kg"})
    assert rc.status_code == 200, rc.text
    lot_id = rc.json()["lot_id"]

    created = client.post("/api/warehouse/counts", headers=admin_h, json={"note": "Kiểm kê test"})
    assert created.status_code == 200, created.text
    count = created.json()
    assert count["status"] == "draft"
    line = next(l for l in count["lines"] if l["lot_id"] == lot_id)
    assert line["system_qty"] == 100
    assert line["counted_qty"] is None

    updated = client.put(f"/api/warehouse/counts/{count['count_id']}/lines", headers=admin_h,
                         json={"lines": [{"line_id": line["line_id"], "counted_qty": 92}]})
    assert updated.status_code == 200, updated.text
    updated_line = next(l for l in updated.json()["lines"] if l["line_id"] == line["line_id"])
    assert updated_line["counted_qty"] == 92
    assert updated_line["variance"] == -8

    posted = client.post(f"/api/warehouse/counts/{count['count_id']}/post", headers=admin_h)
    assert posted.status_code == 200, posted.text
    assert posted.json()["status"] == "posted"

    row = _stock_row(client, admin_h, mat_id)
    assert row["on_hand"] == 92

    moves = client.get("/api/warehouse/movements?movement_type=adjust", headers=admin_h).json()
    match = next(m for m in moves if m["lot_id"] == lot_id)
    assert match["quantity"] == 8

    # Không sửa/chốt lại được phiếu đã posted.
    reedit = client.put(f"/api/warehouse/counts/{count['count_id']}/lines", headers=admin_h,
                        json={"lines": [{"line_id": line["line_id"], "counted_qty": 50}]})
    assert reedit.status_code == 409
    repost = client.post(f"/api/warehouse/counts/{count['count_id']}/post", headers=admin_h)
    assert repost.status_code == 409


def test_cycle_count_no_variance_creates_no_adjust_movement(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "KK-MAT-NOVAR")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "KK-LOT-NOVAR", "material_id": mat_id, "quantity": 10, "uom": "kg"})
    assert rc.status_code == 200, rc.text
    lot_id = rc.json()["lot_id"]

    created = client.post("/api/warehouse/counts", headers=admin_h, json={}).json()
    line = next(l for l in created["lines"] if l["lot_id"] == lot_id)
    client.put(f"/api/warehouse/counts/{created['count_id']}/lines", headers=admin_h,
              json={"lines": [{"line_id": line["line_id"], "counted_qty": 10}]})
    posted = client.post(f"/api/warehouse/counts/{created['count_id']}/post", headers=admin_h)
    assert posted.status_code == 200, posted.text

    moves = client.get("/api/warehouse/movements?movement_type=adjust", headers=admin_h).json()
    assert not any(m["lot_id"] == lot_id for m in moves)


def test_vanhanh_can_count_workshop_but_not_company_warehouse(client, admin_h, thukho_h, vanhanh_h):
    """Kiểm kê định kỳ tách theo kho: vanhanh (Kho phân xưởng, scope_warehouse="phan_xuong")
    được tự tạo/kiểm kê phiếu CHO KHO PHÂN XƯỞNG (không cần nhờ thukho), nhưng vẫn bị chặn nếu
    cố tạo phiếu cho Kho công ty — _assert_location_scope (services/warehouse.py) khoá theo
    scope_warehouse của user, warehouse.receive chỉ mở khoá HÀNH ĐỘNG, không mở khoá ĐỊA ĐIỂM."""
    mat_id = _create_material(client, admin_h, "KK-PX-MAT")
    rc = client.post("/api/warehouse/receive", headers=admin_h,
                     json={"lot_code": "KK-PX-LOT", "material_id": mat_id, "quantity": 20, "uom": "kg",
                           "location": "Kho phân xưởng"})
    assert rc.status_code == 200, rc.text

    ok = client.post("/api/warehouse/counts", headers=vanhanh_h, json={"location": "Kho phân xưởng"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["location"] == "Kho phân xưởng"

    denied = client.post("/api/warehouse/counts", headers=vanhanh_h, json={"location": "Kho công ty"})
    assert denied.status_code == 403, denied.text


def _posted_count_with_variance(client, admin_h, thukho_h, tag, on_hand=100, counted=92):
    mat_id = _create_material(client, admin_h, f"KK-MAT-{tag}")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": f"KK-LOT-{tag}", "material_id": mat_id, "quantity": on_hand, "uom": "kg"})
    assert rc.status_code == 200, rc.text
    lot_id = rc.json()["lot_id"]
    count = client.post("/api/warehouse/counts", headers=admin_h, json={}).json()
    line = next(l for l in count["lines"] if l["lot_id"] == lot_id)
    client.put(f"/api/warehouse/counts/{count['count_id']}/lines", headers=admin_h,
              json={"lines": [{"line_id": line["line_id"], "counted_qty": counted}]})
    posted = client.post(f"/api/warehouse/counts/{count['count_id']}/post", headers=admin_h)
    assert posted.status_code == 200, posted.text
    return posted.json()["count_id"], mat_id, lot_id


def test_stock_count_approve_requires_supervisor_role_or_above(client, admin_h, thukho_h):
    count_id, mat_id, lot_id = _posted_count_with_variance(client, admin_h, thukho_h, "APPR-PERM")

    denied = client.post(f"/api/warehouse/counts/{count_id}/approve", headers=thukho_h)
    assert denied.status_code == 403, denied.text

    ok = client.post(f"/api/warehouse/counts/{count_id}/approve", headers=admin_h)
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["approved_by"] == "admin"
    assert body["approved_at"] is not None
    assert body["can_undo"] is False
    assert body["can_approve"] is False

    twice = client.post(f"/api/warehouse/counts/{count_id}/approve", headers=admin_h)
    assert twice.status_code == 409, twice.text


def test_stock_count_approve_gated_by_configurable_permission(client, admin_h, thukho_h, quandoc_h):
    """Duyệt kiểm kê giờ gate theo quyền warehouse.count_approve (admin có thể cấp/thu hồi qua
    Tài khoản) thay vì role cứng — quandoc (Quản đốc phân xưởng sản xuất) được seed sẵn quyền
    này nên duyệt được, dù không phải admin; thukho (không có quyền) vẫn bị chặn."""
    count_id, mat_id, lot_id = _posted_count_with_variance(client, admin_h, thukho_h, "APPR-CONFIGPERM")

    denied = client.post(f"/api/warehouse/counts/{count_id}/approve", headers=thukho_h)
    assert denied.status_code == 403, denied.text

    ok = client.post(f"/api/warehouse/counts/{count_id}/approve", headers=quandoc_h)
    assert ok.status_code == 200, ok.text
    assert ok.json()["approved_by"] == "quandoc"


def test_stock_count_create_with_period_dates(client, admin_h, thukho_h):
    """Ngày bắt đầu/kết thúc kỳ kiểm kê (khai báo tay) khác created_at/posted_at (mốc thao
    tác hệ thống) — round-trip qua create_count/list_counts/get_count."""
    mat_id = _create_material(client, admin_h, "KK-PERIOD-MAT")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "KK-PERIOD-LOT", "material_id": mat_id, "quantity": 10, "uom": "kg"})
    assert rc.status_code == 200, rc.text

    created = client.post("/api/warehouse/counts", headers=admin_h,
                          json={"start_date": "2026-08-01T00:00:00Z", "end_date": "2026-08-02T00:00:00Z"})
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["start_date"] is not None
    assert body["end_date"] is not None

    fetched = client.get(f"/api/warehouse/counts/{body['count_id']}", headers=admin_h).json()
    assert fetched["start_date"] is not None
    assert fetched["end_date"] is not None

    listed = client.get("/api/warehouse/counts", headers=admin_h).json()
    row = next(c for c in listed if c["count_id"] == body["count_id"])
    assert row["start_date"] is not None
    assert row["end_date"] is not None


def test_stock_count_undo_restores_quantity_and_reopens_draft(client, admin_h, thukho_h):
    count_id, mat_id, lot_id = _posted_count_with_variance(client, admin_h, thukho_h, "UNDO", on_hand=100, counted=92)
    row = _stock_row(client, admin_h, mat_id)
    assert row["on_hand"] == 92

    undone = client.post(f"/api/warehouse/counts/{count_id}/undo", headers=admin_h)
    assert undone.status_code == 200, undone.text
    body = undone.json()
    assert body["status"] == "draft"
    assert body["posted_by"] is None
    assert body["posted_at"] is None

    row2 = _stock_row(client, admin_h, mat_id)
    assert row2["on_hand"] == 100

    # Có thể chốt lại sau khi hoàn tác (phiếu đã về draft, số liệu đếm vẫn còn nguyên).
    repost = client.post(f"/api/warehouse/counts/{count_id}/post", headers=admin_h)
    assert repost.status_code == 200, repost.text
    row3 = _stock_row(client, admin_h, mat_id)
    assert row3["on_hand"] == 92


def test_stock_count_undo_blocked_after_approved(client, admin_h, thukho_h):
    count_id, mat_id, lot_id = _posted_count_with_variance(client, admin_h, thukho_h, "UNDO-BLOCKED")
    approved = client.post(f"/api/warehouse/counts/{count_id}/approve", headers=admin_h)
    assert approved.status_code == 200, approved.text

    undo = client.post(f"/api/warehouse/counts/{count_id}/undo", headers=admin_h)
    assert undo.status_code == 409, undo.text


def test_stock_count_undo_and_approve_require_posted_status(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "KK-MAT-DRAFTGATE")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "KK-LOT-DRAFTGATE", "material_id": mat_id, "quantity": 10, "uom": "kg"})
    assert rc.status_code == 200, rc.text
    count = client.post("/api/warehouse/counts", headers=admin_h, json={}).json()

    undo = client.post(f"/api/warehouse/counts/{count['count_id']}/undo", headers=admin_h)
    assert undo.status_code == 409, undo.text
    approve = client.post(f"/api/warehouse/counts/{count['count_id']}/approve", headers=admin_h)
    assert approve.status_code == 409, approve.text


# ---- 3. Nhập bia cận date ----

def _a_finished_product(client, admin_h, code):
    fp = client.post("/api/finished-products", headers=admin_h,
                     json={"code": code, "name": f"SP {code}", "uom": "lon",
                           "unit_type": "vi", "pack_size": 1})
    assert fp.status_code == 201, fp.text
    return fp.json()["finished_product_id"]


def _declare_near_expiry(client, admin_h, fp_id, quantity, location_id=None, note=None):
    payload = {"finished_product_id": fp_id, "quantity": quantity}
    if location_id is not None:
        payload["location_id"] = location_id
    if note is not None:
        payload["note"] = note
    entry = client.post("/api/wms/near-expiry", headers=admin_h, json=payload)
    assert entry.status_code == 201, entry.text
    return entry.json()


def _approve_near_expiry(client, admin_h, entry_id):
    r = client.post(f"/api/wms/near-expiry/{entry_id}/approve", headers=admin_h)
    assert r.status_code == 200, r.text
    return r.json()


def test_near_expiry_declare_rejects_nonpositive_quantity(client, admin_h):
    fp_id = _a_finished_product(client, admin_h, "SKU-NE-ZEROQTY")
    bad = client.post("/api/wms/near-expiry", headers=admin_h,
                      json={"finished_product_id": fp_id, "quantity": 0})
    assert bad.status_code == 409, bad.text


def test_near_expiry_declare_pending_then_approve_increases_stock(client, admin_h):
    """Khai báo (direction="in") CHƯA tăng tồn kho ngay — chỉ ghi bản khai chờ duyệt (đã tự
    sinh sẵn lot_code riêng). Trưởng bộ phận kho duyệt (approve) mới thực sự tạo tồn kho."""
    fp_id = _a_finished_product(client, admin_h, "SKU-NE-PENDING")
    body = _declare_near_expiry(client, admin_h, fp_id, 3, note="Khai báo test")
    assert body["count"] == 3
    lot_code = body["lot_code"]
    assert lot_code  # tự sinh, không trống

    hist = client.get("/api/wms/near-expiry", headers=admin_h).json()
    row = next(h for h in hist if h["direction"] == "in" and h["lot_code"] == lot_code)
    assert row["quantity"] == 3
    assert row["finished_product_id"] == fp_id
    assert row["note"] == "Khai báo test"
    assert row["approved_by"] is None
    assert row["can_edit"] is True and row["can_approve"] is True and row["can_undo"] is True

    # Chưa duyệt -> chưa có tồn kho thật (không xuất hiện ở by-lot).
    by_lot = client.get("/api/wms/units/by-lot", headers=admin_h).json()
    assert not any(g["lot_code"] == lot_code for g in by_lot)

    approved = _approve_near_expiry(client, admin_h, row["entry_id"])
    assert approved["count"] == 3

    hist2 = client.get("/api/wms/near-expiry", headers=admin_h).json()
    row2 = next(h for h in hist2 if h["entry_id"] == row["entry_id"])
    assert row2["approved_by"] == "admin"
    assert row2["can_edit"] is False and row2["can_approve"] is False and row2["can_undo"] is False

    # Đã duyệt -> giờ mới có tồn kho thật, không sửa/hoàn tác được nữa.
    edit_after = client.put(f"/api/wms/near-expiry/{row['entry_id']}", headers=admin_h, json={"quantity": 5})
    assert edit_after.status_code == 409
    undo_after = client.post(f"/api/wms/near-expiry/{row['entry_id']}/undo", headers=admin_h)
    assert undo_after.status_code == 409


def test_near_expiry_declare_generates_dedicated_lot_and_shipment_roundtrip(client, admin_h):
    """Khai báo trực tiếp Sản phẩm + Số lượng (không cần chọn lô chiết gốc) phải tự sinh 1 lô
    cận date riêng, tách biệt khỏi mọi lô sản xuất thật — sau khi duyệt mới xuất được."""
    fp_id = _a_finished_product(client, admin_h, "SKU-NE-ROUND")
    body = _declare_near_expiry(client, admin_h, fp_id, 3, note="Khai báo test")
    product_name, lot_code = body["product_name"], body["lot_code"]
    hist0 = client.get("/api/wms/near-expiry", headers=admin_h).json()
    entry_id = next(h["entry_id"] for h in hist0 if h["direction"] == "in" and h["lot_code"] == lot_code)
    _approve_near_expiry(client, admin_h, entry_id)

    hist = client.get("/api/wms/near-expiry", headers=admin_h).json()
    in_entries = [h for h in hist if h["direction"] == "in" and h["lot_code"] == lot_code]
    assert len(in_entries) == 1
    assert in_entries[0]["quantity"] == 3
    assert in_entries[0]["finished_product_id"] == fp_id
    assert in_entries[0]["note"] == "Khai báo test"

    ship_to = client.post("/api/suppliers", headers=admin_h,
                          json={"code": "DIST-NE-ROUND", "name": "NPP test cận date"})
    assert ship_to.status_code == 201, ship_to.text

    # Xuất một phần (2/3) với near_expiry_only=True phải thành công (cho phép xuất một phần lô).
    shipped = client.post("/api/wms/shipments", headers=admin_h,
                          json={"ship_to_id": ship_to.json()["supplier_id"],
                                "lines": [{"product_name": product_name, "lot_code": lot_code,
                                          "unit_type": "vi", "quantity": 2, "near_expiry_only": True}]})
    assert shipped.status_code == 201, shipped.text

    hist2 = client.get("/api/wms/near-expiry", headers=admin_h).json()
    out_entries = [h for h in hist2 if h["direction"] == "out" and h["lot_code"] == lot_code]
    assert len(out_entries) == 1 and out_entries[0]["quantity"] == 2
    assert out_entries[0]["shipment_code"] == shipped.json()["shipment_code"]

    # Xuất tiếp phần còn lại (1) vẫn còn cận date -> thành công (phần còn lại của lô).
    shipped2 = client.post("/api/wms/shipments", headers=admin_h,
                           json={"ship_to_id": ship_to.json()["supplier_id"],
                                 "lines": [{"product_name": product_name, "lot_code": lot_code,
                                           "unit_type": "vi", "quantity": 1, "near_expiry_only": True}]})
    assert shipped2.status_code == 201, shipped2.text

    # Không còn vỉ cận date nào nữa -> xuất tiếp near_expiry_only phải báo lỗi rõ ràng.
    shipped3 = client.post("/api/wms/shipments", headers=admin_h,
                           json={"ship_to_id": ship_to.json()["supplier_id"],
                                 "lines": [{"product_name": product_name, "lot_code": lot_code,
                                           "unit_type": "vi", "quantity": 1, "near_expiry_only": True}]})
    assert shipped3.status_code == 409
    assert "cận date" in shipped3.json()["detail"]


def test_near_expiry_lot_never_merges_with_regular_stock(client, admin_h):
    """Yêu cầu cốt lõi: lô cận date PHẢI hiện thành dòng RIÊNG ở Xuất kho, không gộp chung với
    tồn thường của cùng 1 sản phẩm — vì lot_code tự sinh không bao giờ trùng lô sản xuất thật."""
    fp_id = _a_finished_product(client, admin_h, "SKU-NE-SEPARATE")
    fp = client.get("/api/finished-products", headers=admin_h).json()
    code = next(f["code"] for f in fp if f["finished_product_id"] == fp_id)

    loc = client.post("/api/wms/locations", headers=admin_h,
                      json={"code": "NE-SEPARATE-LOC", "name": "Vị trí test near-expiry", "capacity": 100})
    assert loc.status_code == 201, loc.text
    regular_lot = "LOT-REGULAR-SEPARATE"
    built = client.post("/api/wms/units", headers=admin_h,
                        json={"finished_product_id": fp_id, "product_name": code,
                              "lot_code": regular_lot, "total": 5, "pack_size": 1,
                              "unit_type": "vi", "reason": "Nhập kho thủ công",
                              "loc_id": loc.json()["loc_id"]})
    assert built.status_code == 201, built.text

    ne_body = _declare_near_expiry(client, admin_h, fp_id, 3)
    assert ne_body["lot_code"] != regular_lot
    hist0 = client.get("/api/wms/near-expiry", headers=admin_h).json()
    entry_id = next(h["entry_id"] for h in hist0 if h["direction"] == "in" and h["lot_code"] == ne_body["lot_code"])
    _approve_near_expiry(client, admin_h, entry_id)

    by_lot = client.get("/api/wms/units/by-lot", headers=admin_h).json()
    lots_for_product = {g["lot_code"] for g in by_lot if g["product_name"] == code}
    assert regular_lot in lots_for_product
    assert ne_body["lot_code"] in lots_for_product
    assert len(lots_for_product) == 2  # 2 dòng riêng biệt, không gộp


def test_near_expiry_undo_removes_pending_declaration(client, admin_h):
    """Hủy CHỈ áp dụng khi đang chờ duyệt — vì lúc đó chưa có FinishedGoodsUnit nào được tạo,
    hủy chỉ đơn giản đánh dấu reversed (không có gì để xoá khỏi tồn kho)."""
    fp_id = _a_finished_product(client, admin_h, "SKU-NE-UNDO")
    body = _declare_near_expiry(client, admin_h, fp_id, 2)
    lot_code = body["lot_code"]

    hist = client.get("/api/wms/near-expiry", headers=admin_h).json()
    row = next(h for h in hist if h["direction"] == "in" and h["lot_code"] == lot_code)
    assert row["can_undo"] is True
    assert row["reversed"] is False

    undo = client.post(f"/api/wms/near-expiry/{row['entry_id']}/undo", headers=admin_h)
    assert undo.status_code == 200, undo.text

    hist2 = client.get("/api/wms/near-expiry", headers=admin_h).json()
    row2 = next(h for h in hist2 if h["entry_id"] == row["entry_id"])
    assert row2["reversed"] is True
    assert row2["can_undo"] is False

    # Đã hủy -> không duyệt được nữa.
    approve_after_undo = client.post(f"/api/wms/near-expiry/{row['entry_id']}/approve", headers=admin_h)
    assert approve_after_undo.status_code == 409

    # Hoàn tác lần 2 phải báo lỗi (đã hoàn tác trước đó).
    redo = client.post(f"/api/wms/near-expiry/{row['entry_id']}/undo", headers=admin_h)
    assert redo.status_code == 409


def test_near_expiry_undo_blocked_after_approved(client, admin_h):
    fp_id = _a_finished_product(client, admin_h, "SKU-NE-UNDO-APPROVED")
    body = _declare_near_expiry(client, admin_h, fp_id, 1)
    lot_code = body["lot_code"]
    hist = client.get("/api/wms/near-expiry", headers=admin_h).json()
    row = next(h for h in hist if h["direction"] == "in" and h["lot_code"] == lot_code)
    _approve_near_expiry(client, admin_h, row["entry_id"])

    undo = client.post(f"/api/wms/near-expiry/{row['entry_id']}/undo", headers=admin_h)
    assert undo.status_code == 409
    assert "duyệt" in undo.json()["detail"]


def test_near_expiry_undo_rejects_out_direction(client, admin_h):
    fp_id = _a_finished_product(client, admin_h, "SKU-NE-UNDO-OUTDIR")
    body = _declare_near_expiry(client, admin_h, fp_id, 1)
    lot_code, product_name = body["lot_code"], body["product_name"]
    hist0 = client.get("/api/wms/near-expiry", headers=admin_h).json()
    entry_id = next(h["entry_id"] for h in hist0 if h["direction"] == "in" and h["lot_code"] == lot_code)
    _approve_near_expiry(client, admin_h, entry_id)

    ship_to = client.post("/api/suppliers", headers=admin_h,
                          json={"code": "DIST-NE-UNDO-OUTDIR", "name": "NPP test undo outdir"})
    assert ship_to.status_code == 201, ship_to.text
    shipped = client.post("/api/wms/shipments", headers=admin_h,
                          json={"ship_to_id": ship_to.json()["supplier_id"],
                                "lines": [{"product_name": product_name, "lot_code": lot_code,
                                          "unit_type": "vi", "quantity": 1, "near_expiry_only": True}]})
    assert shipped.status_code == 201, shipped.text

    hist = client.get("/api/wms/near-expiry", headers=admin_h).json()
    out_row = next(h for h in hist if h["direction"] == "out" and h["lot_code"] == lot_code)
    assert out_row["can_undo"] is False
    undo = client.post(f"/api/wms/near-expiry/{out_row['entry_id']}/undo", headers=admin_h)
    assert undo.status_code == 409


# ---- 4. Cảnh báo QC (dashboard) ----

def test_qc_attention_alerts_on_hold_only(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "ALERT-MAT-HOLD")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "ALERT-LOT-HOLD", "material_id": mat_id, "quantity": 20, "uom": "kg"})
    assert rc.status_code == 200, rc.text
    lot_id = rc.json()["lot_id"]

    hold = client.post("/api/quality/hold", headers=admin_h,
                       json={"scope_type": "lot", "scope_id": lot_id, "on_hold": True})
    assert hold.status_code == 200, hold.text

    alerts = client.get("/api/reports/qc-attention-alerts", headers=admin_h)
    assert alerts.status_code == 200, alerts.text
    body = alerts.json()
    row = next(it for it in body["items"] if it["scope_id"] == lot_id)
    assert row["reasons"] == ["on_hold"]
    assert row["fail_param_count"] == 0
    assert "capa_overdue" not in body and "calib_due" not in body


def test_qc_attention_alerts_open_deviation_without_hold(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "ALERT-MAT-DEV")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "ALERT-LOT-DEV", "material_id": mat_id, "quantity": 5, "uom": "kg"})
    assert rc.status_code == 200, rc.text
    lot_id = rc.json()["lot_id"]

    dev = client.post("/api/quality/deviations", headers=admin_h,
                      json={"scope_type": "lot", "scope_id": lot_id, "reason": "Nghi ngờ nhiễm tạp chất"})
    assert dev.status_code == 201, dev.text
    # open_deviation() tự động hold kèm theo — release lại ngay (không có kết quả FAIL nào nên
    # được phép) để mô phỏng đúng tình huống "deviation mở nhưng lô không còn hold".
    release = client.post("/api/quality/hold", headers=admin_h,
                          json={"scope_type": "lot", "scope_id": lot_id, "on_hold": False})
    assert release.status_code == 200, release.text

    alerts = client.get("/api/reports/qc-attention-alerts", headers=admin_h).json()
    row = next(it for it in alerts["items"] if it["scope_id"] == lot_id)
    assert row["reasons"] == ["deviation"]
    assert row["deviation_count"] == 1


def test_qc_attention_alerts_merges_hold_and_deviation_into_one_row(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "ALERT-MAT-BOTH")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "ALERT-LOT-BOTH", "material_id": mat_id, "quantity": 8, "uom": "kg"})
    assert rc.status_code == 200, rc.text
    lot_id = rc.json()["lot_id"]

    client.post("/api/quality/hold", headers=admin_h,
               json={"scope_type": "lot", "scope_id": lot_id, "on_hold": True})
    client.post("/api/quality/deviations", headers=admin_h,
               json={"scope_type": "lot", "scope_id": lot_id, "reason": "Test merge"})

    alerts = client.get("/api/reports/qc-attention-alerts", headers=admin_h).json()
    rows = [it for it in alerts["items"] if it["scope_id"] == lot_id]
    assert len(rows) == 1
    assert sorted(rows[0]["reasons"]) == ["deviation", "on_hold"]


def test_qc_attention_alerts_counts_fail_params(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "ALERT-MAT-FAIL")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "ALERT-LOT-FAIL", "material_id": mat_id, "quantity": 12, "uom": "kg"})
    assert rc.status_code == 200, rc.text
    lot_id = rc.json()["lot_id"]

    # Kết quả FAIL đầu tiên (ngoài giới hạn) tự động đưa lô về on_hold.
    fail1 = client.post("/api/quality/results", headers=admin_h,
                        json={"scope_type": "lot", "scope_id": lot_id, "parameter": "do_am",
                              "value": 99, "lower_limit": 0, "upper_limit": 10})
    assert fail1.status_code == 201, fail1.text
    fail2 = client.post("/api/quality/results", headers=admin_h,
                        json={"scope_type": "lot", "scope_id": lot_id, "parameter": "tap_chat",
                              "value": 99, "lower_limit": 0, "upper_limit": 10})
    assert fail2.status_code == 201, fail2.text
    # Khai báo lại "do_am" với giá trị đạt — chỉ tính giá trị MỚI NHẤT, không còn tính là fail.
    fix = client.post("/api/quality/results", headers=admin_h,
                      json={"scope_type": "lot", "scope_id": lot_id, "parameter": "do_am",
                            "value": 5, "lower_limit": 0, "upper_limit": 10})
    assert fix.status_code == 201, fix.text

    alerts = client.get("/api/reports/qc-attention-alerts", headers=admin_h).json()
    row = next(it for it in alerts["items"] if it["scope_id"] == lot_id)
    assert row["fail_param_count"] == 1
