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


def _approved_bottle(client, admin_h, vanhanh_h, code, ca1=5):
    fp_id = _a_finished_product(client, admin_h, f"SKU-{code}")
    b = client.post("/api/brewing/bottles", headers=vanhanh_h,
                    json={"bottle_code": code, "beer_type": "Bia test", "finished_product_id": fp_id})
    assert b.status_code == 201, b.text
    bottle = b.json()
    fin = client.post(f"/api/brewing/bottles/{bottle['bottle_id']}/finish", headers=vanhanh_h,
                      json={"ca1": ca1})
    assert fin.status_code == 200, fin.text

    # Khai báo hết mọi chỉ tiêu bắt buộc (thành phẩm) đang áp dụng — khi chạy CHUNG cả bộ test
    # (không chỉ riêng file này), có thể đã có nhóm chỉ tiêu bắt buộc TOÀN CỤC (không giới hạn
    # theo finished_product_id/beer_type_id) do file khác khai báo trước đó (module-scoped DB
    # dùng chung trong 1 lượt chạy pytest); mirror cách các test khác (VD test_stage_qc.py) đã
    # xử lý — GET qc-status rồi POST qc-results cho từng chỉ tiêu còn thiếu trước khi duyệt.
    scope_id = f"{code}__thanh_pham"
    status = client.get("/api/brewing/qc-status", headers=vanhanh_h,
                        params={"stage": "thanh_pham", "scope_type": "bottle", "scope_id": scope_id,
                               "finished_product_id": fp_id}).json()
    for p in status.get("required", []):
        rec = client.post("/api/brewing/qc-results", headers=vanhanh_h,
                          json={"stage": "thanh_pham", "scope_type": "bottle", "scope_id": scope_id,
                                "parameter": p["code"], "value": 5,
                                "lower_limit": p["lsl"] or 1, "upper_limit": p["usl"] or 10})
        assert rec.status_code == 201, rec.text

    ap = client.post(f"/api/brewing/bottles/{bottle['bottle_id']}/approve", headers=admin_h)
    assert ap.status_code == 200, ap.text
    return bottle


def test_near_expiry_lookup_finds_bottle_by_datetime(client, admin_h, vanhanh_h):
    bottle = _approved_bottle(client, admin_h, vanhanh_h, "NE-LOOKUP-01")
    found = client.post("/api/wms/near-expiry/lookup", headers=admin_h,
                        json={"declared_at": bottle["bottle_date"]})
    assert found.status_code == 200, found.text
    candidates = found.json()
    assert any(c["bottle_id"] == bottle["bottle_id"] for c in candidates)


def test_near_expiry_lookup_no_match_far_in_past(client, admin_h):
    found = client.post("/api/wms/near-expiry/lookup", headers=admin_h,
                        json={"declared_at": "2000-01-01T00:00:00Z"})
    assert found.status_code == 200, found.text
    assert found.json() == []


def test_near_expiry_entry_and_shipment_filter_roundtrip(client, admin_h, vanhanh_h):
    bottle = _approved_bottle(client, admin_h, vanhanh_h, "NE-ROUND-01", ca1=5)

    entry = client.post("/api/wms/near-expiry", headers=admin_h,
                        json={"bottle_id": bottle["bottle_id"], "quantity": 3,
                              "declared_at": bottle["bottle_date"]})
    assert entry.status_code == 201, entry.text
    body = entry.json()
    assert body["count"] == 3
    product_name, lot_code = body["product_name"], body["lot_code"]

    hist = client.get("/api/wms/near-expiry", headers=admin_h).json()
    in_entries = [h for h in hist if h["direction"] == "in" and h["lot_code"] == lot_code]
    assert len(in_entries) == 1 and in_entries[0]["quantity"] == 3

    ship_to = client.post("/api/wms/ship-to", headers=admin_h,
                          json={"code": "DIST-NE-ROUND", "name": "NPP test cận date"})
    assert ship_to.status_code == 201, ship_to.text

    # Xuất đúng 3 (đúng bằng số lượng cận date hiện có) với near_expiry_only=True phải thành công.
    shipped = client.post("/api/wms/shipments", headers=admin_h,
                          json={"ship_to_id": ship_to.json()["ship_to_id"],
                                "lines": [{"product_name": product_name, "lot_code": lot_code,
                                          "unit_type": "vi", "quantity": 3, "near_expiry_only": True}]})
    assert shipped.status_code == 201, shipped.text

    hist2 = client.get("/api/wms/near-expiry", headers=admin_h).json()
    out_entries = [h for h in hist2 if h["direction"] == "out" and h["lot_code"] == lot_code]
    assert len(out_entries) == 1 and out_entries[0]["quantity"] == 3
    assert out_entries[0]["shipment_code"] == shipped.json()["shipment_code"]

    # Không còn vỉ cận date nào nữa -> xuất tiếp near_expiry_only phải báo lỗi rõ ràng.
    shipped2 = client.post("/api/wms/shipments", headers=admin_h,
                           json={"ship_to_id": ship_to.json()["ship_to_id"],
                                 "lines": [{"product_name": product_name, "lot_code": lot_code,
                                           "unit_type": "vi", "quantity": 1, "near_expiry_only": True}]})
    assert shipped2.status_code == 409
    assert "cận date" in shipped2.json()["detail"]


def test_near_expiry_shipment_without_flag_ignores_near_expiry_tag(client, admin_h, vanhanh_h):
    """Xuất KHÔNG tick near_expiry_only vẫn có thể lấy trúng đơn vị cận date (FIFO thường) —
    chỉ khi đó phiếu xuất mới tự động ghi vào lịch sử cận date (direction=out)."""
    bottle = _approved_bottle(client, admin_h, vanhanh_h, "NE-NOFLAG-01", ca1=2)
    entry = client.post("/api/wms/near-expiry", headers=admin_h,
                        json={"bottle_id": bottle["bottle_id"], "quantity": 2,
                              "declared_at": bottle["bottle_date"]})
    assert entry.status_code == 201, entry.text
    product_name, lot_code = entry.json()["product_name"], entry.json()["lot_code"]

    ship_to = client.post("/api/wms/ship-to", headers=admin_h,
                          json={"code": "DIST-NE-NOFLAG", "name": "NPP test 2"})
    assert ship_to.status_code == 201, ship_to.text
    # Tổng tồn = 2 (mẻ chiết) + 2 (cận date) = 4; xuất cả 4 không lọc cận date.
    shipped = client.post("/api/wms/shipments", headers=admin_h,
                          json={"ship_to_id": ship_to.json()["ship_to_id"],
                                "lines": [{"product_name": product_name, "lot_code": lot_code,
                                          "unit_type": "vi", "quantity": 4}]})
    assert shipped.status_code == 201, shipped.text

    hist = client.get("/api/wms/near-expiry", headers=admin_h).json()
    out_entries = [h for h in hist if h["direction"] == "out" and h["lot_code"] == lot_code]
    assert len(out_entries) == 1 and out_entries[0]["quantity"] == 2  # chỉ 2 đơn vị cận date trong lô này


def test_near_expiry_undo_removes_units(client, admin_h, vanhanh_h):
    bottle = _approved_bottle(client, admin_h, vanhanh_h, "NE-UNDO-01", ca1=3)
    entry = client.post("/api/wms/near-expiry", headers=admin_h,
                        json={"bottle_id": bottle["bottle_id"], "quantity": 2,
                              "declared_at": bottle["bottle_date"]})
    assert entry.status_code == 201, entry.text
    product_name, lot_code = entry.json()["product_name"], entry.json()["lot_code"]

    hist = client.get("/api/wms/near-expiry", headers=admin_h).json()
    row = next(h for h in hist if h["direction"] == "in" and h["lot_code"] == lot_code)
    assert row["can_undo"] is True
    assert row["reversed"] is False

    undo = client.post(f"/api/wms/near-expiry/{row['entry_id']}/undo", headers=admin_h)
    assert undo.status_code == 200, undo.text
    assert undo.json()["removed"] == 2

    hist2 = client.get("/api/wms/near-expiry", headers=admin_h).json()
    row2 = next(h for h in hist2 if h["entry_id"] == row["entry_id"])
    assert row2["reversed"] is True
    assert row2["can_undo"] is False

    # Không còn vỉ cận date nào (đã bị xoá) -> xuất near_expiry_only phải báo lỗi.
    ship_to = client.post("/api/wms/ship-to", headers=admin_h,
                          json={"code": "DIST-NE-UNDO", "name": "NPP test undo"})
    assert ship_to.status_code == 201, ship_to.text
    shipped = client.post("/api/wms/shipments", headers=admin_h,
                          json={"ship_to_id": ship_to.json()["ship_to_id"],
                                "lines": [{"product_name": product_name, "lot_code": lot_code,
                                          "unit_type": "vi", "quantity": 1, "near_expiry_only": True}]})
    assert shipped.status_code == 409

    # Hoàn tác lần 2 phải báo lỗi (đã hoàn tác trước đó).
    redo = client.post(f"/api/wms/near-expiry/{row['entry_id']}/undo", headers=admin_h)
    assert redo.status_code == 409


def test_near_expiry_undo_blocked_after_shipped(client, admin_h, vanhanh_h):
    bottle = _approved_bottle(client, admin_h, vanhanh_h, "NE-UNDO-SHIPPED-01", ca1=1)
    entry = client.post("/api/wms/near-expiry", headers=admin_h,
                        json={"bottle_id": bottle["bottle_id"], "quantity": 1,
                              "declared_at": bottle["bottle_date"]})
    assert entry.status_code == 201, entry.text
    product_name, lot_code = entry.json()["product_name"], entry.json()["lot_code"]

    ship_to = client.post("/api/wms/ship-to", headers=admin_h,
                          json={"code": "DIST-NE-UNDO-SHIPPED", "name": "NPP test undo shipped"})
    assert ship_to.status_code == 201, ship_to.text
    shipped = client.post("/api/wms/shipments", headers=admin_h,
                          json={"ship_to_id": ship_to.json()["ship_to_id"],
                                "lines": [{"product_name": product_name, "lot_code": lot_code,
                                          "unit_type": "vi", "quantity": 1, "near_expiry_only": True}]})
    assert shipped.status_code == 201, shipped.text

    hist = client.get("/api/wms/near-expiry", headers=admin_h).json()
    row = next(h for h in hist if h["direction"] == "in" and h["lot_code"] == lot_code)
    undo = client.post(f"/api/wms/near-expiry/{row['entry_id']}/undo", headers=admin_h)
    assert undo.status_code == 409
    assert "xuất" in undo.json()["detail"]


def test_near_expiry_undo_rejects_out_direction(client, admin_h, vanhanh_h):
    bottle = _approved_bottle(client, admin_h, vanhanh_h, "NE-UNDO-OUTDIR-01", ca1=1)
    entry = client.post("/api/wms/near-expiry", headers=admin_h,
                        json={"bottle_id": bottle["bottle_id"], "quantity": 1,
                              "declared_at": bottle["bottle_date"]})
    assert entry.status_code == 201, entry.text
    product_name, lot_code = entry.json()["product_name"], entry.json()["lot_code"]

    ship_to = client.post("/api/wms/ship-to", headers=admin_h,
                          json={"code": "DIST-NE-UNDO-OUTDIR", "name": "NPP test undo outdir"})
    assert ship_to.status_code == 201, ship_to.text
    shipped = client.post("/api/wms/shipments", headers=admin_h,
                          json={"ship_to_id": ship_to.json()["ship_to_id"],
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
