"""Test tính năng "Nhập từ nhà máy khác" (FactoryImportEntry) — bia thực tế do 1 nhà máy khác
(Danh mục Nhà máy) sản xuất, chỉ nhận lại vào kho này để lưu/xuất tiếp:
- Khai báo (direction="in" duy nhất, không có "out") CHƯA tăng tồn kho ngay — chỉ ghi bản khai
  chờ duyệt (mirror NearExpiryEntry/ConsignedEntry).
- Duyệt mới thực sự tạo FinishedGoodsUnit is_factory_import=True + tăng tồn kho, dùng CHUNG lot
  code tự sinh với "Nhập kho thủ công" (không tách dòng riêng như bia gửi/cận date).
- Sau khi vào kho, lô này KHÔNG có is_near_expiry/is_consigned — không được ưu tiên xuất, không
  tách dòng riêng ở Xuất kho picker.
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


_DEFAULT_LOC_ID = None
_DEFAULT_FACTORY_ID = None


def _default_loc(client, admin_h):
    global _DEFAULT_LOC_ID
    if _DEFAULT_LOC_ID is None:
        r = client.post("/api/wms/locations", headers=admin_h,
                        json={"code": "LOC-NMK-DEFAULT", "name": "Vị trí test nhập NM khác", "capacity": 1000})
        assert r.status_code == 201, r.text
        _DEFAULT_LOC_ID = r.json()["loc_id"]
    return _DEFAULT_LOC_ID


def _default_factory(client, admin_h):
    global _DEFAULT_FACTORY_ID
    if _DEFAULT_FACTORY_ID is None:
        r = client.post("/api/factory-locations", headers=admin_h,
                        json={"code": "NM-NMK-DEFAULT", "name": "Nhà máy test nhập NM khác"})
        assert r.status_code == 201, r.text
        _DEFAULT_FACTORY_ID = r.json()["factory_id"]
    return _DEFAULT_FACTORY_ID


def _declare(client, admin_h, fp_id, quantity, location_id=None, factory_id=None, note=None):
    payload = {"finished_product_id": fp_id, "quantity": quantity,
              "location_id": location_id or _default_loc(client, admin_h),
              "factory_id": factory_id or _default_factory(client, admin_h)}
    if note is not None:
        payload["note"] = note
    entry = client.post("/api/wms/factory-import", headers=admin_h, json=payload)
    assert entry.status_code == 201, entry.text
    return entry.json()


def _approve(client, admin_h, entry_id):
    r = client.post(f"/api/wms/factory-import/{entry_id}/approve", headers=admin_h)
    assert r.status_code == 200, r.text
    return r.json()


def _declare_and_approve(client, admin_h, fp_id, quantity, location_id=None, factory_id=None, note=None):
    body = _declare(client, admin_h, fp_id, quantity, location_id, factory_id, note)
    hist = client.get("/api/wms/factory-import", headers=admin_h).json()
    row = next(h for h in hist if h["entry_id"] == body["entry_id"])
    _approve(client, admin_h, row["entry_id"])
    return body


def test_factory_import_declare_rejects_nonpositive_quantity(client, admin_h):
    fp_id = _a_finished_product(client, admin_h, "SKU-NMK-ZEROQTY")
    bad = client.post("/api/wms/factory-import", headers=admin_h,
                      json={"finished_product_id": fp_id, "quantity": 0,
                            "location_id": _default_loc(client, admin_h),
                            "factory_id": _default_factory(client, admin_h)})
    assert bad.status_code == 409, bad.text


def test_factory_import_declare_requires_location_and_factory(client, admin_h):
    fp_id = _a_finished_product(client, admin_h, "SKU-NMK-REQUIRED")
    missing_loc = client.post("/api/wms/factory-import", headers=admin_h,
                              json={"finished_product_id": fp_id, "quantity": 1,
                                    "factory_id": _default_factory(client, admin_h)})
    assert missing_loc.status_code == 422, missing_loc.text
    missing_factory = client.post("/api/wms/factory-import", headers=admin_h,
                                  json={"finished_product_id": fp_id, "quantity": 1,
                                        "location_id": _default_loc(client, admin_h)})
    assert missing_factory.status_code == 422, missing_factory.text


def test_factory_import_declare_pending_then_approve_increases_stock(client, admin_h):
    """Khai báo CHƯA tăng tồn kho ngay — chỉ ghi bản khai chờ duyệt. Duyệt mới thực sự tạo tồn
    kho; sau khi duyệt thì khoá, không sửa/hoàn tác được."""
    fp_id = _a_finished_product(client, admin_h, "SKU-NMK-PENDING")
    body = _declare(client, admin_h, fp_id, 4, note="Khai báo test")
    entry_id = body["entry_id"]
    assert body["count"] == 4

    hist = client.get("/api/wms/factory-import", headers=admin_h).json()
    row = next(h for h in hist if h["entry_id"] == entry_id)
    assert row["approved_by"] is None
    assert row["lot_code"] is None
    assert row["can_edit"] is True and row["can_approve"] is True and row["can_undo"] is True

    by_lot_before = client.get("/api/wms/units/by-lot", headers=admin_h).json()
    assert not any(g["product_name"] == "SKU-NMK-PENDING" for g in by_lot_before)

    approved = _approve(client, admin_h, entry_id)
    assert approved["count"] == 4

    hist2 = client.get("/api/wms/factory-import", headers=admin_h).json()
    row2 = next(h for h in hist2 if h["entry_id"] == entry_id)
    assert row2["approved_by"] == "admin"
    assert row2["lot_code"]
    assert row2["can_edit"] is False and row2["can_approve"] is False and row2["can_undo"] is False

    by_lot = client.get("/api/wms/units/by-lot", headers=admin_h).json()
    group = next(g for g in by_lot if g["lot_code"] == row2["lot_code"])
    assert group["vi_count"] == 4

    edit_after = client.put(f"/api/wms/factory-import/{entry_id}", headers=admin_h, json={"quantity": 9})
    assert edit_after.status_code == 409
    undo_after = client.post(f"/api/wms/factory-import/{entry_id}/undo", headers=admin_h)
    assert undo_after.status_code == 409


def test_factory_import_uses_regular_lot_code_not_dedicated_prefix(client, admin_h):
    """Khác bia gửi/cận date (tự sinh lô riêng GUI.../CD...) — Nhập từ nhà máy khác dùng CHUNG
    generator lô với "Nhập kho thủ công" (_next_wms_lot_code) để hàng không bị tách dòng riêng
    ở Xuất kho."""
    fp_id = _a_finished_product(client, admin_h, "SKU-NMK-LOTCODE")
    body = _declare_and_approve(client, admin_h, fp_id, 2)
    hist = client.get("/api/wms/factory-import", headers=admin_h).json()
    row = next(h for h in hist if h["entry_id"] == body["entry_id"])
    assert not row["lot_code"].startswith("GUI")
    assert not row["lot_code"].startswith("CD")
    import re
    assert re.match(r"^\d{4}-\d+$", row["lot_code"]), row["lot_code"]


def test_factory_import_stock_has_no_near_expiry_or_consigned_flags(client, admin_h):
    """Sau khi duyệt, lô này phải HOÀN TOÀN giống bia thường ở tầng picker Xuất kho — không
    được đếm vào near_expiry_count/consigned_count (những cờ dành riêng cho các luồng khác)."""
    fp_id = _a_finished_product(client, admin_h, "SKU-NMK-NOFLAGS")
    body = _declare_and_approve(client, admin_h, fp_id, 3)
    hist = client.get("/api/wms/factory-import", headers=admin_h).json()
    row = next(h for h in hist if h["entry_id"] == body["entry_id"])

    by_lot = client.get("/api/wms/units/by-lot", headers=admin_h).json()
    group = next(g for g in by_lot if g["lot_code"] == row["lot_code"])
    assert group.get("vi_near_expiry_count", 0) == 0
    assert group.get("vi_consigned_count", 0) == 0
    assert group.get("consigned_vehicle_plate") is None


def test_factory_import_records_factory_source_on_entry(client, admin_h):
    """Nhà máy nguồn là "dấu hiệu" ghi lại nguồn gốc — vẫn phải đọc được trên bản khai đã duyệt
    dù không xuất hiện ở bất kỳ đâu trong luồng Xuất kho."""
    fp_id = _a_finished_product(client, admin_h, "SKU-NMK-FACTORY")
    fl = client.post("/api/factory-locations", headers=admin_h,
                     json={"code": "NM-HL-TEST", "name": "Nhà máy Hạ Long test"})
    assert fl.status_code == 201, fl.text
    factory_id = fl.json()["factory_id"]
    body = _declare_and_approve(client, admin_h, fp_id, 1, factory_id=factory_id)
    hist = client.get("/api/wms/factory-import", headers=admin_h).json()
    row = next(h for h in hist if h["entry_id"] == body["entry_id"])
    assert row["factory_id"] == factory_id
    assert row["factory_name"] == "Nhà máy Hạ Long test"


def test_factory_import_undo_removes_pending_declaration(client, admin_h):
    fp_id = _a_finished_product(client, admin_h, "SKU-NMK-UNDO")
    body = _declare(client, admin_h, fp_id, 2)
    entry_id = body["entry_id"]

    hist = client.get("/api/wms/factory-import", headers=admin_h).json()
    row = next(h for h in hist if h["entry_id"] == entry_id)
    assert row["can_undo"] is True
    assert row["reversed"] is False

    undo = client.post(f"/api/wms/factory-import/{entry_id}/undo", headers=admin_h)
    assert undo.status_code == 200, undo.text

    hist2 = client.get("/api/wms/factory-import", headers=admin_h).json()
    row2 = next(h for h in hist2 if h["entry_id"] == entry_id)
    assert row2["reversed"] is True
    assert row2["can_undo"] is False

    approve_after_undo = client.post(f"/api/wms/factory-import/{entry_id}/approve", headers=admin_h)
    assert approve_after_undo.status_code == 409

    redo = client.post(f"/api/wms/factory-import/{entry_id}/undo", headers=admin_h)
    assert redo.status_code == 409


def test_factory_import_undo_blocked_after_approved(client, admin_h):
    fp_id = _a_finished_product(client, admin_h, "SKU-NMK-UNDO-APPROVED")
    body = _declare_and_approve(client, admin_h, fp_id, 1)
    undo = client.post(f"/api/wms/factory-import/{body['entry_id']}/undo", headers=admin_h)
    assert undo.status_code == 409
    assert "duyệt" in undo.json()["detail"]


def test_factory_import_update_pending_entry(client, admin_h):
    fp_id = _a_finished_product(client, admin_h, "SKU-NMK-EDIT")
    body = _declare(client, admin_h, fp_id, 2, note="Ghi chú cũ")
    entry_id = body["entry_id"]

    upd = client.put(f"/api/wms/factory-import/{entry_id}", headers=admin_h, json={"quantity": 5, "note": "Sửa lại"})
    assert upd.status_code == 200, upd.text

    hist = client.get("/api/wms/factory-import", headers=admin_h).json()
    row = next(h for h in hist if h["entry_id"] == entry_id)
    assert row["quantity"] == 5
    assert row["note"] == "Sửa lại"
