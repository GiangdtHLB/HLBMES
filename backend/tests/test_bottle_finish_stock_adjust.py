"""Test: sửa Ca 1/2/3 (finish_bottle) SAU KHI mã chiết đã Duyệt (approve_bottle) phải điều
chỉnh lại đúng tồn kho thành phẩm theo chênh lệch — bug thực tế được người dùng phát hiện:
approve_bottle chỉ nhập kho ĐÚNG 1 LẦN lúc duyệt; sửa Ca sau đó (finish_bottle cho phép gọi
lại nhiều lần) trước đây không cập nhật lại số vỉ/keg đã tạo, khiến tồn kho lệch khỏi Ca
hiển thị. Xem services/wms.py::adjust_bottle_finish_stock."""

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


def _a_finished_product(client, admin_h, code, pack_size=1):
    fp = client.post("/api/finished-products", headers=admin_h,
                     json={"code": code, "name": f"SP {code}", "uom": "lon",
                           "unit_type": "vi", "pack_size": pack_size})
    assert fp.status_code == 201, fp.text
    return fp.json()["finished_product_id"], code


def _a_bottle(client, vanhanh_h, code, fp_id):
    b = client.post("/api/brewing/bottles", headers=vanhanh_h,
                    json={"bottle_code": code, "beer_type": "Bia test", "finished_product_id": fp_id})
    assert b.status_code == 201, b.text
    return b.json()


def _stored_units(client, admin_h, product_name, lot_code):
    units = client.get("/api/wms/units?status=stored", headers=admin_h).json()
    return [u for u in units if u["product"] == product_name and u["lot_code"] == lot_code]


def test_ca_is_counted_in_vi_not_lon(client, admin_h, vanhanh_h):
    """Ca 1/2/3 tính theo VỈ (đơn vị đóng gói), KHÔNG phải theo lon rời — 1 vỉ = pack_size
    lon (khai báo Danh mục Sản phẩm). Ca1=10 với pack_size=24 phải tạo ĐÚNG 10 vỉ (mỗi vỉ 24
    lon, tổng 240 lon) — không phải 10 lon rời chia thành ceil(10/24)=1 vỉ lẻ. Từ khi duyệt
    chiết chỉ tạo 1 dòng/lô (xem docs/WMS-LOT-LEVEL-REDESIGN.md), số vỉ suy ra từ
    quantity/pack_size chứ không còn bằng số dòng trả về."""
    fp_id, fp_code = _a_finished_product(client, admin_h, "SKU-ADJ-PACKSIZE", pack_size=24)
    bottle = _a_bottle(client, vanhanh_h, "CH-ADJ-PACKSIZE-01", fp_id)
    bottle_id = bottle["bottle_id"]
    lot_code = bottle["lot_no"]

    fin = client.post(f"/api/brewing/bottles/{bottle_id}/finish", headers=vanhanh_h, json={"ca1": 10})
    assert fin.status_code == 200, fin.text
    approve = client.post(f"/api/brewing/bottles/{bottle_id}/approve", headers=admin_h)
    assert approve.status_code == 200, approve.text
    assert approve.json()["count"] == 10  # đúng 10 VỈ, không phải 1 vỉ lẻ

    stored = _stored_units(client, admin_h, fp_code, lot_code)
    assert sum(u["quantity"] for u in stored) == 240  # 10 vỉ x 24 lon/vỉ

    # Sửa Ca xuống 4 vỉ sau khi đã duyệt -> tồn kho phải còn đúng 4 vỉ (96 lon), không phải
    # tính theo lon (VD hiểu nhầm "giảm 6 lon" thay vì "giảm 6 vỉ").
    fixed = client.post(f"/api/brewing/bottles/{bottle_id}/finish", headers=vanhanh_h, json={"ca1": 4})
    assert fixed.status_code == 200, fixed.text
    stored = _stored_units(client, admin_h, fp_code, lot_code)
    assert sum(u["quantity"] for u in stored) == 96


def test_edit_ca_after_approve_increases_stock(client, admin_h, vanhanh_h):
    fp_id, fp_code = _a_finished_product(client, admin_h, "SKU-ADJ-UP")
    bottle = _a_bottle(client, vanhanh_h, "CH-ADJ-UP-01", fp_id)
    bottle_id = bottle["bottle_id"]
    lot_code = bottle["lot_no"]

    fin = client.post(f"/api/brewing/bottles/{bottle_id}/finish", headers=vanhanh_h, json={"ca1": 5})
    assert fin.status_code == 200, fin.text

    approve = client.post(f"/api/brewing/bottles/{bottle_id}/approve", headers=admin_h)
    assert approve.status_code == 200, approve.text
    assert approve.json()["count"] == 5

    stored = _stored_units(client, admin_h, fp_code, lot_code)
    assert sum(u["quantity"] for u in stored) == 5

    fixed = client.post(f"/api/brewing/bottles/{bottle_id}/finish", headers=vanhanh_h, json={"ca1": 8})
    assert fixed.status_code == 200, fixed.text

    stored = _stored_units(client, admin_h, fp_code, lot_code)
    assert sum(u["quantity"] for u in stored) == 8


def test_edit_ca_after_approve_decreases_stock(client, admin_h, vanhanh_h):
    fp_id, fp_code = _a_finished_product(client, admin_h, "SKU-ADJ-DOWN")
    bottle = _a_bottle(client, vanhanh_h, "CH-ADJ-DOWN-01", fp_id)
    bottle_id = bottle["bottle_id"]
    lot_code = bottle["lot_no"]

    fin = client.post(f"/api/brewing/bottles/{bottle_id}/finish", headers=vanhanh_h, json={"ca1": 10})
    assert fin.status_code == 200, fin.text
    approve = client.post(f"/api/brewing/bottles/{bottle_id}/approve", headers=admin_h)
    assert approve.status_code == 200, approve.text
    assert approve.json()["count"] == 10

    fixed = client.post(f"/api/brewing/bottles/{bottle_id}/finish", headers=vanhanh_h, json={"ca1": 4})
    assert fixed.status_code == 200, fixed.text

    stored = _stored_units(client, admin_h, fp_code, lot_code)
    assert sum(u["quantity"] for u in stored) == 4


def test_edit_ca_after_approve_decreases_stock_past_sqlite_variable_limit(client, admin_h, vanhanh_h):
    """Giảm tồn kho phải xóa hơn 999 dòng finished_goods_unit trong 1 lượt (SQLite giới hạn
    số biến/câu lệnh ~999) — hồi quy cho lỗi thực tế gặp khi dọn dữ liệu Ca 1/2/3 nhập nhầm
    (VD gõ dư số 0) tạo ra hàng chục nghìn đơn vị thừa."""
    fp_id, fp_code = _a_finished_product(client, admin_h, "SKU-ADJ-BIGCHUNK")
    bottle = _a_bottle(client, vanhanh_h, "CH-ADJ-BIGCHUNK-01", fp_id)
    bottle_id = bottle["bottle_id"]
    lot_code = bottle["lot_no"]

    fin = client.post(f"/api/brewing/bottles/{bottle_id}/finish", headers=vanhanh_h, json={"ca1": 1500})
    assert fin.status_code == 200, fin.text
    approve = client.post(f"/api/brewing/bottles/{bottle_id}/approve", headers=admin_h)
    assert approve.status_code == 200, approve.text
    assert approve.json()["count"] == 1500

    fixed = client.post(f"/api/brewing/bottles/{bottle_id}/finish", headers=vanhanh_h, json={"ca1": 1})
    assert fixed.status_code == 200, fixed.text

    stored = _stored_units(client, admin_h, fp_code, lot_code)
    assert sum(u["quantity"] for u in stored) == 1


def test_edit_ca_after_approve_blocked_if_already_shipped(client, admin_h, vanhanh_h):
    fp_id, fp_code = _a_finished_product(client, admin_h, "SKU-ADJ-BLOCK")
    bottle = _a_bottle(client, vanhanh_h, "CH-ADJ-BLOCK-01", fp_id)
    bottle_id = bottle["bottle_id"]
    lot_code = bottle["lot_no"]

    fin = client.post(f"/api/brewing/bottles/{bottle_id}/finish", headers=vanhanh_h, json={"ca1": 10})
    assert fin.status_code == 200, fin.text
    approve = client.post(f"/api/brewing/bottles/{bottle_id}/approve", headers=admin_h)
    assert approve.status_code == 200, approve.text

    ship_to = client.post("/api/suppliers", headers=admin_h,
                          json={"code": "DIST-ADJ-BLOCK", "name": "NPP test"})
    assert ship_to.status_code == 201, ship_to.text
    shipped = client.post("/api/wms/shipments", headers=admin_h,
                          json={"ship_to_id": ship_to.json()["supplier_id"],
                                "lines": [{"product_name": fp_code, "lot_code": lot_code,
                                          "unit_type": "vi", "quantity": 3}]})
    assert shipped.status_code == 201, shipped.text

    # Còn 7 "stored" — sửa Ca xuống 2 (cần giảm 8) vượt quá tồn "stored" hiện có -> phải chặn.
    blocked = client.post(f"/api/brewing/bottles/{bottle_id}/finish", headers=vanhanh_h, json={"ca1": 2})
    assert blocked.status_code == 409, blocked.text

    rows = client.get("/api/brewing/bottles", headers=admin_h).json()
    row = next(r for r in rows if r["bottle_code"] == "CH-ADJ-BLOCK-01")
    assert row["ca1"] == 10  # không bị thay đổi vì request thất bại (rollback)

    stored = _stored_units(client, admin_h, fp_code, lot_code)
    assert sum(u["quantity"] for u in stored) == 7
