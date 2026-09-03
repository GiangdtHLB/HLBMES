"""Test kho thành phẩm quản lý theo LÔ (không phải theo từng vỉ/keg riêng lẻ — xem
docs/WMS-LOT-LEVEL-REDESIGN.md, thay hẳn Pallet/Case và cả mô hình cũ "1 dòng/vỉ"):
- Nhập kho thủ công (POST /wms/units) chỉ sinh 1 dòng/lô.
- Barcode resolve cho vỉ/keg qua GET /wms/resolve.

Trước đây còn test "duyệt chiết sinh 1 dòng/lô" + "xóa unit mở khóa lại bottle nguồn" qua
approve_bottle — approve_bottle đã tháo khỏi WMS (routers/brewing.py, không còn tạo
FinishedGoodsUnit), coverage tương ứng nay ở tests/test_batch_pack_lot_wms.py (Lô thành phẩm
là nơi thay thế duy nhất tạo hàng nhập kho từ sản xuất)."""

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
def kcs_h(client):
    return _login(client, "kcs", "123456")


def test_build_units_manual_entry_creates_one_row(client, admin_h):
    """"Nhập kho thủ công" (POST /wms/units) cũng chỉ sinh 1 dòng/lô (dùng chung _create_units
    với duyệt chiết) — pack_size chỉ còn ý nghĩa quy đổi ở tầng đọc, không tách dòng nữa."""
    loc = client.post("/api/wms/locations", headers=admin_h,
                      json={"code": "LOC-MANUALPARTIAL", "name": "Vị trí manual partial", "capacity": 100})
    assert loc.status_code == 201, loc.text
    build = client.post("/api/wms/units", headers=admin_h,
                        json={"product_name": "SKU-MANUALPARTIAL", "lot_code": "LOT-MANUALPARTIAL",
                              "total": 100, "pack_size": 24, "unit_type": "vi",
                              "loc_id": loc.json()["loc_id"]})
    assert build.status_code == 201, build.text
    assert len(build.json()["unit_codes"]) == 1
    units = client.get("/api/wms/units", headers=admin_h).json()
    made = [u for u in units if u["unit_code"] in build.json()["unit_codes"]]
    assert [u["quantity"] for u in made] == [100]


def test_delete_units_batch_blocked_if_shipped(client, admin_h):
    """Nếu dòng lô đã chuyển status="shipped" (xuất HẾT lô — không còn phần dư để tách dòng),
    không được xóa. Dùng "Nhập kho thủ công" (source=manual) thay vì chuỗi chiết cũ đã tháo
    khỏi WMS — cần Trưởng bộ phận kho duyệt nhập (confirm-receipt-by-lot) trước khi xuất được
    (source=manual bị block_pending_manual chặn, khác source=chiet — xem
    services/wms.py::confirm_receipt_by_lot)."""
    fp = client.post("/api/finished-products", headers=admin_h,
                     json={"code": "SKU-BATCH02", "name": "SKU batch shipped test", "uom": "lon",
                           "unit_type": "vi", "pack_size": 24})
    assert fp.status_code == 201, fp.text
    loc = client.post("/api/wms/locations", headers=admin_h,
                      json={"code": "LOC-BATCH02", "name": "Vị trí batch shipped test", "capacity": 100})
    assert loc.status_code == 201, loc.text
    build = client.post("/api/wms/units", headers=admin_h,
                        json={"finished_product_id": fp.json()["finished_product_id"],
                              "product_name": "SKU-BATCH02", "lot_code": "LOT-BATCH02",
                              "total": 48, "pack_size": 24, "unit_type": "vi", "loc_id": loc.json()["loc_id"]})
    assert build.status_code == 201, build.text
    unit_code = build.json()["unit_codes"][0]
    units = client.get("/api/wms/units", headers=admin_h).json()
    unit = next(u for u in units if u["unit_code"] == unit_code)
    unit_ids = [unit["unit_id"]]

    confirm = client.post("/api/wms/units/confirm-receipt-by-lot", headers=admin_h,
                          json={"product_name": "SKU-BATCH02", "lot_code": "LOT-BATCH02", "unit_type": "vi"})
    assert confirm.status_code == 200, confirm.text

    ship_to = client.post("/api/suppliers", headers=admin_h,
                          json={"code": "DIST-BATCH02", "name": "NPP batch test"})
    assert ship_to.status_code == 201, ship_to.text
    # Xuất HẾT 2 vỉ (toàn bộ lô) -> dòng gốc chuyển thẳng sang "shipped" (không tách dòng).
    shipped = client.post("/api/wms/shipments", headers=admin_h,
                          json={"ship_to_id": ship_to.json()["supplier_id"],
                                "lines": [{"product_name": "SKU-BATCH02", "lot_code": "LOT-BATCH02",
                                          "unit_type": "vi", "quantity": 2}]})
    assert shipped.status_code == 201, shipped.text

    remaining_before = client.get("/api/wms/units", headers=admin_h).json()
    assert next(u for u in remaining_before if u["unit_id"] == unit_ids[0])["status"] == "shipped"

    blocked = client.post("/api/wms/units/delete-batch", headers=admin_h, json={"unit_ids": unit_ids})
    assert blocked.status_code == 409, blocked.text

    remaining = client.get("/api/wms/units", headers=admin_h).json()
    assert sum(1 for u in remaining if u["unit_id"] in unit_ids) == 1, "không xóa dòng đã shipped"


def test_resolve_unknown_barcode(client, admin_h):
    r = client.get("/api/wms/resolve", params={"code": "DOES-NOT-EXIST"}, headers=admin_h)
    assert r.status_code == 200, r.text
    assert r.json()["type"] == "unknown"
