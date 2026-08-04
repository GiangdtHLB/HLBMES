"""Test tính năng "Bia gửi" (ConsignedEntry) — mirror y hệt bia cận date nhưng cho trường hợp
xe đã xuất phiếu đi giao trong ngày nhưng giao không hết, mang phần dư về gửi lại kho:
- Khai báo trực tiếp Sản phẩm + SL, tự sinh 1 lô gửi riêng (không gộp với tồn thường của SKU).
- Xuất kho picker ưu tiên bia gửi TRƯỚC CẢ bia cận date.
- Hoàn tác / chặn hoàn tác sau khi đã xuất / không hoàn tác được dòng direction=out.
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


def _a_finished_product(client, admin_h, code):
    fp = client.post("/api/finished-products", headers=admin_h,
                     json={"code": code, "name": f"SP {code}", "uom": "lon",
                           "unit_type": "vi", "pack_size": 1})
    assert fp.status_code == 201, fp.text
    return fp.json()["finished_product_id"]


def _declare_consigned(client, admin_h, fp_id, quantity, location_id=None, note=None):
    payload = {"finished_product_id": fp_id, "quantity": quantity}
    if location_id is not None:
        payload["location_id"] = location_id
    if note is not None:
        payload["note"] = note
    entry = client.post("/api/wms/consigned", headers=admin_h, json=payload)
    assert entry.status_code == 201, entry.text
    return entry.json()


def _approve_consigned(client, admin_h, entry_id):
    r = client.post(f"/api/wms/consigned/{entry_id}/approve", headers=admin_h)
    assert r.status_code == 200, r.text
    return r.json()


def _declare_and_approve_consigned(client, admin_h, fp_id, quantity, location_id=None, note=None):
    """Khai báo CHƯA tăng tồn kho ngay (xem NearExpiryEntry/ConsignedEntry.approved_by) — hầu
    hết các test dưới đây chỉ quan tâm tới hành vi SAU khi đã có tồn kho thật, nên helper này
    khai báo + duyệt luôn 1 lượt (mirror _declare_consigned nhưng approve ngay)."""
    body = _declare_consigned(client, admin_h, fp_id, quantity, location_id, note)
    hist = client.get("/api/wms/consigned", headers=admin_h).json()
    entry_id = next(h["entry_id"] for h in hist if h["direction"] == "in" and h["lot_code"] == body["lot_code"])
    _approve_consigned(client, admin_h, entry_id)
    return body


def test_consigned_declare_rejects_nonpositive_quantity(client, admin_h):
    fp_id = _a_finished_product(client, admin_h, "SKU-GS-ZEROQTY")
    bad = client.post("/api/wms/consigned", headers=admin_h,
                      json={"finished_product_id": fp_id, "quantity": 0})
    assert bad.status_code == 409, bad.text


def test_consigned_declare_pending_then_approve_increases_stock(client, admin_h):
    """Khai báo (direction="in") CHƯA tăng tồn kho ngay — chỉ ghi bản khai chờ duyệt. Trưởng bộ
    phận kho duyệt mới thực sự tạo tồn kho; sau khi duyệt thì khoá, không sửa/hoàn tác được."""
    fp_id = _a_finished_product(client, admin_h, "SKU-GS-PENDING")
    body = _declare_consigned(client, admin_h, fp_id, 4)
    lot_code = body["lot_code"]
    hist = client.get("/api/wms/consigned", headers=admin_h).json()
    row = next(h for h in hist if h["direction"] == "in" and h["lot_code"] == lot_code)
    assert row["approved_by"] is None
    assert row["can_edit"] is True and row["can_approve"] is True and row["can_undo"] is True

    by_lot = client.get("/api/wms/units/by-lot", headers=admin_h).json()
    assert not any(g["lot_code"] == lot_code for g in by_lot)

    _approve_consigned(client, admin_h, row["entry_id"])
    hist2 = client.get("/api/wms/consigned", headers=admin_h).json()
    row2 = next(h for h in hist2 if h["entry_id"] == row["entry_id"])
    assert row2["approved_by"] == "admin"
    assert row2["can_edit"] is False and row2["can_approve"] is False and row2["can_undo"] is False

    edit_after = client.put(f"/api/wms/consigned/{row['entry_id']}", headers=admin_h, json={"quantity": 9})
    assert edit_after.status_code == 409
    undo_after = client.post(f"/api/wms/consigned/{row['entry_id']}/undo", headers=admin_h)
    assert undo_after.status_code == 409


def test_consigned_declare_generates_dedicated_lot_and_shipment_roundtrip(client, admin_h):
    fp_id = _a_finished_product(client, admin_h, "SKU-GS-ROUND")
    body = _declare_and_approve_consigned(client, admin_h, fp_id, 4, note="Xe giao không hết, mang về gửi")
    assert body["count"] == 4
    product_name, lot_code = body["product_name"], body["lot_code"]
    assert lot_code.startswith("GUI")

    hist = client.get("/api/wms/consigned", headers=admin_h).json()
    in_entries = [h for h in hist if h["direction"] == "in" and h["lot_code"] == lot_code]
    assert len(in_entries) == 1
    assert in_entries[0]["quantity"] == 4
    assert in_entries[0]["finished_product_id"] == fp_id

    ship_to = client.post("/api/suppliers", headers=admin_h,
                          json={"code": "DIST-GS-ROUND", "name": "NPP test bia gửi"})
    assert ship_to.status_code == 201, ship_to.text

    # Xuất một phần (3/4) với consigned_only=True phải thành công (cho phép xuất một phần lô).
    shipped = client.post("/api/wms/shipments", headers=admin_h,
                          json={"ship_to_id": ship_to.json()["supplier_id"],
                                "lines": [{"product_name": product_name, "lot_code": lot_code,
                                          "unit_type": "vi", "quantity": 3, "consigned_only": True}]})
    assert shipped.status_code == 201, shipped.text

    hist2 = client.get("/api/wms/consigned", headers=admin_h).json()
    out_entries = [h for h in hist2 if h["direction"] == "out" and h["lot_code"] == lot_code]
    assert len(out_entries) == 1 and out_entries[0]["quantity"] == 3
    assert out_entries[0]["shipment_code"] == shipped.json()["shipment_code"]

    # Không còn bia gửi nào nữa (chỉ còn 1) -> xuất 2 với consigned_only phải báo lỗi rõ ràng.
    shipped2 = client.post("/api/wms/shipments", headers=admin_h,
                           json={"ship_to_id": ship_to.json()["supplier_id"],
                                 "lines": [{"product_name": product_name, "lot_code": lot_code,
                                           "unit_type": "vi", "quantity": 2, "consigned_only": True}]})
    assert shipped2.status_code == 409
    assert "bia gửi" in shipped2.json()["detail"]


def test_consigned_lot_never_merges_with_regular_stock(client, admin_h):
    fp_id = _a_finished_product(client, admin_h, "SKU-GS-SEPARATE")
    fp = client.get("/api/finished-products", headers=admin_h).json()
    code = next(f["code"] for f in fp if f["finished_product_id"] == fp_id)

    regular_lot = "LOT-REGULAR-GS-SEPARATE"
    built = client.post("/api/wms/units", headers=admin_h,
                        json={"finished_product_id": fp_id, "product_name": code,
                              "lot_code": regular_lot, "total": 5, "pack_size": 1,
                              "unit_type": "vi", "reason": "Nhập kho thủ công"})
    assert built.status_code == 201, built.text

    gs_body = _declare_and_approve_consigned(client, admin_h, fp_id, 3)
    assert gs_body["lot_code"] != regular_lot

    by_lot = client.get("/api/wms/units/by-lot", headers=admin_h).json()
    lots_for_product = {g["lot_code"] for g in by_lot if g["product_name"] == code}
    assert regular_lot in lots_for_product
    assert gs_body["lot_code"] in lots_for_product
    assert len(lots_for_product) == 2


def test_consigned_prioritized_ahead_of_near_expiry_in_lot_summaries(client, admin_h):
    """Xuất kho picker phải ưu tiên bia gửi TRƯỚC bia cận date — kiểm ở tầng dữ liệu: cả 2 lô
    đều mang cờ riêng biệt (consigned_count/near_expiry_count), không lẫn lộn nhau."""
    fp_id = _a_finished_product(client, admin_h, "SKU-GS-VS-NE")
    ne_entry = client.post("/api/wms/near-expiry", headers=admin_h,
                           json={"finished_product_id": fp_id, "quantity": 2})
    assert ne_entry.status_code == 201, ne_entry.text
    ne_hist = client.get("/api/wms/near-expiry", headers=admin_h).json()
    ne_row = next(h for h in ne_hist if h["direction"] == "in" and h["lot_code"] == ne_entry.json()["lot_code"])
    approve_ne = client.post(f"/api/wms/near-expiry/{ne_row['entry_id']}/approve", headers=admin_h)
    assert approve_ne.status_code == 200, approve_ne.text
    gs_body = _declare_and_approve_consigned(client, admin_h, fp_id, 2)

    by_lot = client.get("/api/wms/units/by-lot", headers=admin_h).json()
    ne_group = next(g for g in by_lot if g["lot_code"] == ne_entry.json()["lot_code"])
    gs_group = next(g for g in by_lot if g["lot_code"] == gs_body["lot_code"])
    assert ne_group.get("vi_near_expiry_count", 0) == 2
    assert ne_group.get("vi_consigned_count", 0) == 0
    assert gs_group.get("vi_consigned_count", 0) == 2
    assert gs_group.get("vi_near_expiry_count", 0) == 0


def test_consigned_undo_removes_pending_declaration(client, admin_h):
    """Hủy CHỈ áp dụng khi đang chờ duyệt — chưa có FinishedGoodsUnit nào được tạo, hủy chỉ
    đánh dấu reversed (mirror test_near_expiry_undo_removes_pending_declaration)."""
    fp_id = _a_finished_product(client, admin_h, "SKU-GS-UNDO")
    body = _declare_consigned(client, admin_h, fp_id, 2)
    lot_code = body["lot_code"]

    hist = client.get("/api/wms/consigned", headers=admin_h).json()
    row = next(h for h in hist if h["direction"] == "in" and h["lot_code"] == lot_code)
    assert row["can_undo"] is True
    assert row["reversed"] is False

    undo = client.post(f"/api/wms/consigned/{row['entry_id']}/undo", headers=admin_h)
    assert undo.status_code == 200, undo.text

    hist2 = client.get("/api/wms/consigned", headers=admin_h).json()
    row2 = next(h for h in hist2 if h["entry_id"] == row["entry_id"])
    assert row2["reversed"] is True
    assert row2["can_undo"] is False

    approve_after_undo = client.post(f"/api/wms/consigned/{row['entry_id']}/approve", headers=admin_h)
    assert approve_after_undo.status_code == 409

    redo = client.post(f"/api/wms/consigned/{row['entry_id']}/undo", headers=admin_h)
    assert redo.status_code == 409


def test_consigned_undo_blocked_after_approved(client, admin_h):
    fp_id = _a_finished_product(client, admin_h, "SKU-GS-UNDO-APPROVED")
    body = _declare_consigned(client, admin_h, fp_id, 1)
    lot_code = body["lot_code"]
    hist = client.get("/api/wms/consigned", headers=admin_h).json()
    row = next(h for h in hist if h["direction"] == "in" and h["lot_code"] == lot_code)
    _approve_consigned(client, admin_h, row["entry_id"])

    undo = client.post(f"/api/wms/consigned/{row['entry_id']}/undo", headers=admin_h)
    assert undo.status_code == 409
    assert "duyệt" in undo.json()["detail"]


def test_consigned_undo_rejects_out_direction(client, admin_h):
    fp_id = _a_finished_product(client, admin_h, "SKU-GS-UNDO-OUTDIR")
    body = _declare_and_approve_consigned(client, admin_h, fp_id, 1)
    lot_code, product_name = body["lot_code"], body["product_name"]

    ship_to = client.post("/api/suppliers", headers=admin_h,
                          json={"code": "DIST-GS-UNDO-OUTDIR", "name": "NPP test undo outdir"})
    assert ship_to.status_code == 201, ship_to.text
    shipped = client.post("/api/wms/shipments", headers=admin_h,
                          json={"ship_to_id": ship_to.json()["supplier_id"],
                                "lines": [{"product_name": product_name, "lot_code": lot_code,
                                          "unit_type": "vi", "quantity": 1, "consigned_only": True}]})
    assert shipped.status_code == 201, shipped.text

    hist = client.get("/api/wms/consigned", headers=admin_h).json()
    out_row = next(h for h in hist if h["direction"] == "out" and h["lot_code"] == lot_code)
    assert out_row["can_undo"] is False
    undo = client.post(f"/api/wms/consigned/{out_row['entry_id']}/undo", headers=admin_h)
    assert undo.status_code == 409


def test_shipment_line_rejects_both_near_expiry_and_consigned_flags(client, admin_h):
    fp_id = _a_finished_product(client, admin_h, "SKU-GS-BOTHFLAGS")
    body = _declare_and_approve_consigned(client, admin_h, fp_id, 1)
    lot_code, product_name = body["lot_code"], body["product_name"]

    ship_to = client.post("/api/suppliers", headers=admin_h,
                          json={"code": "DIST-GS-BOTHFLAGS", "name": "NPP test both flags"})
    assert ship_to.status_code == 201, ship_to.text
    shipped = client.post("/api/wms/shipments", headers=admin_h,
                          json={"ship_to_id": ship_to.json()["supplier_id"],
                                "lines": [{"product_name": product_name, "lot_code": lot_code,
                                          "unit_type": "vi", "quantity": 1,
                                          "near_expiry_only": True, "consigned_only": True}]})
    assert shipped.status_code == 409
