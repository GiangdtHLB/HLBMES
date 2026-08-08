"""Phân quyền theo Kho thành phẩm (WmsWarehouse, VD KH01 Đông Mai / KH02 Hạ Long) — dimension
`wms_warehouse` (User.wms_warehouse_scope), TÁCH BIỆT với `scope_warehouse` cũ (chỉ có ý nghĩa
cho Kho NVL cong_ty/phan_xuong, xem test_warehouse_location_scope.py). Người dùng bị giới hạn 1
kho thành phẩm không được nhập/cất/điều chuyển/xuất tại kho ngoài phạm vi, và bắt buộc chọn rõ
kho/vị trí (không được để hệ thống tự FIFO xuyên qua kho khác)."""

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
def _warehouses(client, admin_h):
    """2 kho thành phẩm (KH-A/KH-B) mỗi kho 1 vị trí — dùng chung cho mọi test trong file."""
    wh_a = client.post("/api/wms/warehouses", headers=admin_h,
                       json={"code": "WHSCOPE-A", "name": "Kho A"}).json()
    wh_b = client.post("/api/wms/warehouses", headers=admin_h,
                       json={"code": "WHSCOPE-B", "name": "Kho B"}).json()
    loc_a = client.post("/api/wms/locations", headers=admin_h,
                        json={"code": "WHSCOPE-A-LOC1", "name": "A-Loc1", "capacity": 1000,
                              "warehouse_id": wh_a["warehouse_id"]}).json()
    loc_a2 = client.post("/api/wms/locations", headers=admin_h,
                         json={"code": "WHSCOPE-A-LOC2", "name": "A-Loc2", "capacity": 1000,
                               "warehouse_id": wh_a["warehouse_id"]}).json()
    loc_b = client.post("/api/wms/locations", headers=admin_h,
                        json={"code": "WHSCOPE-B-LOC1", "name": "B-Loc1", "capacity": 1000,
                              "warehouse_id": wh_b["warehouse_id"]}).json()
    return {"wh_a": wh_a, "wh_b": wh_b, "loc_a": loc_a, "loc_a2": loc_a2, "loc_b": loc_b}


def _make_scoped_user(client, admin_h, username, wms_warehouse_scope):
    r = client.post("/api/auth/users", headers=admin_h, json={
        "username": username, "password": "Test1234", "full_name": "Test User",
        "job_title": "Test", "role": "operator", "allowed_views": "wms",
        "permissions": "warehouse.receive,warehouse.issue,wms.confirm_shipment",
        "wms_warehouse_scope": wms_warehouse_scope,
    })
    assert r.status_code == 201, r.text
    return _login(client, username, "Test1234")


def test_build_units_blocked_outside_warehouse_scope(client, admin_h, _warehouses):
    """Nhập kho thủ công (POST /wms/units) chặn nếu vị trí chọn thuộc kho ngoài phạm vi."""
    scoped_h = _make_scoped_user(client, admin_h, "wh_scope_user1", "WHSCOPE-A")

    ok = client.post("/api/wms/units", headers=scoped_h,
                     json={"product_name": "SKU-WHSCOPE-1", "lot_code": "LOT-WHSCOPE-1",
                           "total": 10, "pack_size": 24, "unit_type": "vi",
                           "loc_id": _warehouses["loc_a"]["loc_id"]})
    assert ok.status_code == 201, ok.text

    blocked = client.post("/api/wms/units", headers=scoped_h,
                          json={"product_name": "SKU-WHSCOPE-2", "lot_code": "LOT-WHSCOPE-2",
                                "total": 10, "pack_size": 24, "unit_type": "vi",
                                "loc_id": _warehouses["loc_b"]["loc_id"]})
    assert blocked.status_code == 403, blocked.text


def test_putaway_blocked_outside_warehouse_scope(client, admin_h, _warehouses):
    """Cất vào vị trí (POST /wms/units/{id}/putaway) chặn nếu vị trí đích thuộc kho ngoài phạm vi,
    cho phép nếu đích cùng kho (dù khác vị trí) — xem services/wms.py::_assert_wh_scope."""
    scoped_h = _make_scoped_user(client, admin_h, "wh_scope_user2", "WHSCOPE-A")
    build = client.post("/api/wms/units", headers=admin_h,
                        json={"product_name": "SKU-WHSCOPE-PUT", "lot_code": "LOT-WHSCOPE-PUT",
                              "total": 10, "pack_size": 24, "unit_type": "vi",
                              "loc_id": _warehouses["loc_a"]["loc_id"]})
    assert build.status_code == 201, build.text
    unit_code = build.json()["unit_codes"][0]
    unit_id = next(u["unit_id"] for u in client.get("/api/wms/units", headers=admin_h).json()
                   if u["unit_code"] == unit_code)

    blocked = client.post(f"/api/wms/units/{unit_id}/putaway", headers=scoped_h,
                          json={"loc_id": _warehouses["loc_b"]["loc_id"]})
    assert blocked.status_code == 403, blocked.text

    ok = client.post(f"/api/wms/units/{unit_id}/putaway", headers=scoped_h,
                     json={"loc_id": _warehouses["loc_a2"]["loc_id"]})
    assert ok.status_code == 200, ok.text


def test_create_shipment_requires_warehouse_when_restricted_and_blocks_out_of_scope(
        client, admin_h, _warehouses):
    """Xuất kho: tài khoản bị giới hạn kho phải chọn warehouse_id (không thì 409 — FIFO tự do
    toàn công ty sẽ xuyên qua kho ngoài phạm vi); chọn kho ngoài phạm vi bị chặn 403; chọn đúng
    kho trong phạm vi thành công."""
    scoped_h = _make_scoped_user(client, admin_h, "wh_scope_user3", "WHSCOPE-A")
    build = client.post("/api/wms/units", headers=admin_h,
                        json={"product_name": "SKU-WHSCOPE-SHIP", "lot_code": "LOT-WHSCOPE-SHIP",
                              "total": 10, "pack_size": 24, "unit_type": "vi",
                              "loc_id": _warehouses["loc_a"]["loc_id"]})
    assert build.status_code == 201, build.text
    confirm = client.post("/api/wms/units/confirm-receipt-by-lot", headers=admin_h,
                          json={"product_name": "SKU-WHSCOPE-SHIP", "lot_code": "LOT-WHSCOPE-SHIP",
                                "unit_type": "vi"})
    assert confirm.status_code == 200, confirm.text

    st = client.post("/api/suppliers", headers=admin_h,
                     json={"code": "DIST-WHSCOPE", "name": "NPP whscope test"})
    assert st.status_code == 201, st.text
    ship_to_id = st.json()["supplier_id"]
    line = [{"product_name": "SKU-WHSCOPE-SHIP", "lot_code": "LOT-WHSCOPE-SHIP",
            "unit_type": "vi", "quantity": 1}]

    missing_wh = client.post("/api/wms/shipments", headers=scoped_h,
                             json={"ship_to_id": ship_to_id, "lines": line})
    assert missing_wh.status_code == 409, missing_wh.text

    wrong_wh = client.post("/api/wms/shipments", headers=scoped_h,
                           json={"ship_to_id": ship_to_id, "lines": line,
                                 "warehouse_id": _warehouses["wh_b"]["warehouse_id"]})
    assert wrong_wh.status_code == 403, wrong_wh.text

    ok = client.post("/api/wms/shipments", headers=scoped_h,
                     json={"ship_to_id": ship_to_id, "lines": line,
                           "warehouse_id": _warehouses["wh_a"]["warehouse_id"]})
    assert ok.status_code == 201, ok.text


def test_create_transfer_requires_location_when_restricted_and_blocks_out_of_scope(
        client, admin_h, _warehouses):
    """Điều chuyển: đích (to_location_id) ngoài phạm vi bị chặn 403; nguồn (line.location_id)
    bắt buộc khi bị giới hạn kho, thiếu thì 409; chọn vị trí nguồn ngoài phạm vi bị chặn 403."""
    scoped_h = _make_scoped_user(client, admin_h, "wh_scope_user4", "WHSCOPE-A")
    build = client.post("/api/wms/units", headers=admin_h,
                        json={"product_name": "SKU-WHSCOPE-XFER", "lot_code": "LOT-WHSCOPE-XFER",
                              "total": 10, "pack_size": 24, "unit_type": "vi",
                              "loc_id": _warehouses["loc_a"]["loc_id"]})
    assert build.status_code == 201, build.text
    confirm = client.post("/api/wms/units/confirm-receipt-by-lot", headers=admin_h,
                          json={"product_name": "SKU-WHSCOPE-XFER", "lot_code": "LOT-WHSCOPE-XFER",
                                "unit_type": "vi"})
    assert confirm.status_code == 200, confirm.text
    line = [{"product_name": "SKU-WHSCOPE-XFER", "lot_code": "LOT-WHSCOPE-XFER",
            "unit_type": "vi", "quantity": 1}]

    blocked_dest = client.post("/api/wms/transfers", headers=scoped_h,
                               json={"to_location_id": _warehouses["loc_b"]["loc_id"], "lines": line})
    assert blocked_dest.status_code == 403, blocked_dest.text

    missing_source_loc = client.post("/api/wms/transfers", headers=scoped_h,
                                     json={"to_location_id": _warehouses["loc_a2"]["loc_id"], "lines": line})
    assert missing_source_loc.status_code == 409, missing_source_loc.text

    line_with_wrong_source = [{**line[0], "location_id": _warehouses["loc_b"]["loc_id"]}]
    blocked_source = client.post("/api/wms/transfers", headers=scoped_h,
                                 json={"to_location_id": _warehouses["loc_a2"]["loc_id"],
                                       "lines": line_with_wrong_source})
    assert blocked_source.status_code == 403, blocked_source.text

    line_with_source = [{**line[0], "location_id": _warehouses["loc_a"]["loc_id"]}]
    ok = client.post("/api/wms/transfers", headers=scoped_h,
                     json={"to_location_id": _warehouses["loc_a2"]["loc_id"], "lines": line_with_source})
    assert ok.status_code == 201, ok.text


def test_admin_and_unrestricted_user_bypass_warehouse_scope(client, admin_h, _warehouses):
    """Admin và tài khoản scope="*" (mặc định) không bị ảnh hưởng bởi phân quyền kho mới — mọi
    thao tác trên bất kỳ kho nào vẫn hoạt động như trước khi có tính năng này."""
    unrestricted_h = _make_scoped_user(client, admin_h, "wh_scope_user5", "*")
    ok_a = client.post("/api/wms/units", headers=unrestricted_h,
                       json={"product_name": "SKU-WHSCOPE-FREE", "lot_code": "LOT-WHSCOPE-FREE-A",
                             "total": 5, "pack_size": 24, "unit_type": "vi",
                             "loc_id": _warehouses["loc_a"]["loc_id"]})
    assert ok_a.status_code == 201, ok_a.text
    ok_b = client.post("/api/wms/units", headers=unrestricted_h,
                       json={"product_name": "SKU-WHSCOPE-FREE", "lot_code": "LOT-WHSCOPE-FREE-B",
                             "total": 5, "pack_size": 24, "unit_type": "vi",
                             "loc_id": _warehouses["loc_b"]["loc_id"]})
    assert ok_b.status_code == 201, ok_b.text

    admin_ok = client.post("/api/wms/units", headers=admin_h,
                           json={"product_name": "SKU-WHSCOPE-FREE", "lot_code": "LOT-WHSCOPE-FREE-C",
                                 "total": 5, "pack_size": 24, "unit_type": "vi",
                                 "loc_id": _warehouses["loc_b"]["loc_id"]})
    assert admin_ok.status_code == 201, admin_ok.text
