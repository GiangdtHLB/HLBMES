"""Test kho thành phẩm quản lý theo LÔ (không phải theo từng vỉ/keg riêng lẻ — xem
docs/WMS-LOT-LEVEL-REDESIGN.md, thay hẳn Pallet/Case và cả mô hình cũ "1 dòng/vỉ"):
- Duyệt chiết luôn sinh ĐÚNG 1 dòng/lô (quantity = tổng SL nhỏ), bất kể ca1 lớn cỡ nào.
- Nhập kho thủ công (POST /wms/units) cũng chỉ sinh 1 dòng/lô.
- Xóa 1 unit mở khóa lại bottle nguồn (nếu là dòng cuối cùng chưa xóa).
- Xóa cả lô (delete-batch) chặn khi dòng đó đã "shipped".
- Barcode resolve cho vỉ/keg qua GET /wms/resolve.
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
def vanhanh_h(client):
    return _login(client, "vanhanh", "123456")


@pytest.fixture(scope="module")
def kcs_h(client):
    return _login(client, "kcs", "123456")


def _declare_pending(client, headers, stage, scope_type, scope_id):
    status = client.get(f"/api/brewing/qc-status?stage={stage}&scope_type={scope_type}&scope_id={scope_id}",
                        headers=headers).json()
    for p in status["required"]:
        if p["code"] in status["pending"]:
            lsl = p["lsl"] if p["lsl"] is not None else 0
            usl = p["usl"] if p["usl"] is not None else lsl + 10
            r = client.post("/api/brewing/qc-results", headers=headers,
                            json={"stage": stage, "scope_type": scope_type, "scope_id": scope_id,
                                  "parameter": p["code"], "value": (lsl + usl) / 2,
                                  "lower_limit": lsl, "upper_limit": usl})
            assert r.status_code == 201, r.text


def _approve_bottle_with_output(client, admin_h, vanhanh_h, kcs_h, suffix, fp_payload, ca1):
    fp = client.post("/api/finished-products", headers=admin_h, json={**fp_payload, "code": f"SKU-{suffix}"})
    assert fp.status_code == 201, fp.text
    fp_id = fp.json()["finished_product_id"]
    bottle_code = f"CH-{suffix}"
    b = client.post("/api/brewing/bottles", headers=vanhanh_h,
                    json={"bottle_code": bottle_code, "beer_type": "Bia test", "finished_product_id": fp_id})
    assert b.status_code == 201, b.text
    bottle_id = b.json()["bottle_id"]
    fin = client.post(f"/api/brewing/bottles/{bottle_id}/finish", headers=vanhanh_h, json={"ca1": ca1})
    assert fin.status_code == 200, fin.text
    _declare_pending(client, admin_h, "thanh_pham", "bottle", f"{bottle_code}__thanh_pham")
    # Duyệt nhập kho thành phẩm nay thuộc quyền Giám đốc/Phó GĐ Sản xuất (production.release_to_wms),
    # tách khỏi quality.release của KCS — dùng admin_h (bypass mọi permission) thay vì kcs_h ở đây.
    approve = client.post(f"/api/brewing/bottles/{bottle_id}/approve", headers=admin_h)
    assert approve.status_code == 200, approve.text
    return bottle_id, approve.json()


def test_approve_bottle_creates_one_row_regardless_of_ca_count(client, admin_h, vanhanh_h, kcs_h):
    """Ca 1/2/3 tính theo VỈ (đơn vị đóng gói), không phải lon rời — duyệt chiết luôn sinh
    ĐÚNG 1 dòng lô duy nhất bất kể ca1 lớn cỡ nào (xem docs/WMS-LOT-LEVEL-REDESIGN.md — trước
    đây sinh 1 dòng/vỉ, ca1=190.000 tạo ~190.000 dòng gây timeout khi duyệt trên SQL Server).
    result["count"] vẫn đúng bằng số vỉ thật (100), quantity dòng duy nhất = 100*24=2400 lon."""
    _, result = _approve_bottle_with_output(
        client, admin_h, vanhanh_h, kcs_h, "UNITVI01",
        {"name": "SKU vi test", "uom": "lon", "unit_type": "vi", "pack_size": 24}, ca1=100)
    assert result["unit_type"] == "vi"
    assert result["count"] == 100  # 100 vỉ thật, dù chỉ 1 dòng DB

    units = client.get("/api/wms/units", headers=admin_h).json()
    made = [u for u in units if u["unit_code"] in result["unit_codes"]]
    assert len(made) == 1  # ĐÚNG 1 dòng, không phải 100
    assert made[0]["quantity"] == 2400  # 100 vỉ x 24 lon/vỉ
    assert made[0]["unit_type"] == "vi"
    assert made[0]["status"] == "stored"


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


def test_approve_bottle_creates_keg_one_row(client, admin_h, vanhanh_h, kcs_h):
    _, result = _approve_bottle_with_output(
        client, admin_h, vanhanh_h, kcs_h, "UNITKEG01",
        {"name": "SKU keg test", "uom": "lít", "unit_type": "keg", "pack_size": 1}, ca1=10)
    assert result["unit_type"] == "keg"
    assert result["count"] == 10  # pack_size=1 -> 1 quantity = 1 keg

    units = client.get("/api/wms/units", headers=admin_h).json()
    made = [u for u in units if u["unit_code"] in result["unit_codes"]]
    assert len(made) == 1
    assert made[0]["unit_type"] == "keg" and made[0]["quantity"] == 10


def test_delete_unit_unlocks_source_bottle(client, admin_h, vanhanh_h, kcs_h):
    bottle_id, result = _approve_bottle_with_output(
        client, admin_h, vanhanh_h, kcs_h, "UNITDEL01",
        {"name": "SKU del test", "uom": "lon", "unit_type": "vi", "pack_size": 24}, ca1=1)
    assert result["count"] == 1
    unit_code = result["unit_codes"][0]
    units = client.get("/api/wms/units", headers=admin_h).json()
    unit_id = next(u["unit_id"] for u in units if u["unit_code"] == unit_code)

    blocked = client.delete(f"/api/brewing/bottles/{bottle_id}", headers=vanhanh_h)
    assert blocked.status_code == 409, blocked.text

    deleted = client.delete(f"/api/wms/units/{unit_id}", headers=admin_h)
    assert deleted.status_code == 204, deleted.text

    ok = client.delete(f"/api/brewing/bottles/{bottle_id}", headers=vanhanh_h)
    assert ok.status_code == 204, ok.text


def test_delete_units_batch_unlocks_source_bottle(client, admin_h, vanhanh_h, kcs_h):
    """Xóa cả lô (1 dòng duy nhất dù ca1 lớn, VD xóa nguyên lần nhập kho tự động sau khi
    duyệt chiết) phải mở khóa lại bản ghi Chiết nguồn — xem services/wms.py::delete_units."""
    bottle_id, result = _approve_bottle_with_output(
        client, admin_h, vanhanh_h, kcs_h, "UNITBATCH01",
        {"name": "SKU batch test", "uom": "lon", "unit_type": "vi", "pack_size": 24}, ca1=100)
    assert result["count"] == 100
    units = client.get("/api/wms/units", headers=admin_h).json()
    unit_ids = [u["unit_id"] for u in units if u["unit_code"] in result["unit_codes"]]
    assert len(unit_ids) == 1  # 1 dòng duy nhất đại diện 100 vỉ

    blocked = client.delete(f"/api/brewing/bottles/{bottle_id}", headers=vanhanh_h)
    assert blocked.status_code == 409, blocked.text

    deleted = client.post("/api/wms/units/delete-batch", headers=admin_h, json={"unit_ids": unit_ids})
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] == 1
    assert deleted.json()["bottles_reset"] == ["CH-UNITBATCH01"]

    remaining = client.get("/api/wms/units", headers=admin_h).json()
    assert not any(u["unit_id"] in unit_ids for u in remaining)

    ok = client.delete(f"/api/brewing/bottles/{bottle_id}", headers=vanhanh_h)
    assert ok.status_code == 204, ok.text


def test_delete_units_batch_blocked_if_shipped(client, admin_h, vanhanh_h, kcs_h):
    """Nếu dòng lô đã chuyển status="shipped" (xuất HẾT lô — không còn phần dư để tách dòng),
    không được xóa. Khác với test cũ (chặn khi CHỈ MỘT PHẦN lô đã xuất): dưới mô hình 1
    dòng/lô, xuất một phần chỉ TÁCH dòng (phần còn "stored" tách sang dòng khác, xem
    _consume_lot_rows) — dòng gốc chỉ mang status="shipped" khi bị tiêu thụ TRỌN VẸN."""
    bottle_id, result = _approve_bottle_with_output(
        client, admin_h, vanhanh_h, kcs_h, "UNITBATCH02",
        {"name": "SKU batch shipped test", "uom": "lon", "unit_type": "vi", "pack_size": 24}, ca1=2)
    assert result["count"] == 2
    units = client.get("/api/wms/units", headers=admin_h).json()
    unit_ids = [u["unit_id"] for u in units if u["unit_code"] in result["unit_codes"]]
    assert len(unit_ids) == 1

    ship_to = client.post("/api/suppliers", headers=admin_h,
                          json={"code": "DIST-BATCH02", "name": "NPP batch test"})
    assert ship_to.status_code == 201, ship_to.text
    product_name = next(u["product"] for u in units if u["unit_id"] == unit_ids[0])
    lot_code = next(u["lot_code"] for u in units if u["unit_id"] == unit_ids[0])
    # Xuất HẾT 2 vỉ (toàn bộ lô) -> dòng gốc chuyển thẳng sang "shipped" (không tách dòng).
    shipped = client.post("/api/wms/shipments", headers=admin_h,
                          json={"ship_to_id": ship_to.json()["supplier_id"],
                                "lines": [{"product_name": product_name, "lot_code": lot_code,
                                          "unit_type": "vi", "quantity": 2}]})
    assert shipped.status_code == 201, shipped.text

    blocked = client.post("/api/wms/units/delete-batch", headers=admin_h, json={"unit_ids": unit_ids})
    assert blocked.status_code == 409, blocked.text

    remaining = client.get("/api/wms/units", headers=admin_h).json()
    assert sum(1 for u in remaining if u["unit_id"] in unit_ids) == 1, "không xóa dòng đã shipped"


def test_resolve_unknown_barcode(client, admin_h):
    r = client.get("/api/wms/resolve", params={"code": "DOES-NOT-EXIST"}, headers=admin_h)
    assert r.status_code == 200, r.text
    assert r.json()["type"] == "unknown"
