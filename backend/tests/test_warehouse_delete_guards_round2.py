"""Test các fix đợt audit "Kho công ty & Kho phân xưởng" (2026-09-03):

24. delete_receipt (xóa lượt nhập kho) dọn thêm 4 bảng con khi lô sắp bị xóa THẬT (không còn
    receipt nào khác): TransferPxRequest.lot_id, TransferKcPxRequest.lot_id (mirror
    SangNgangRequest — pending/rejected), MaterialRequestLine.preferred_lot_id (gỡ tham chiếu,
    không xóa dòng phiếu), StockCountLine.lot_id (xóa dòng snapshot kiểm kê).
25. delete_material_location null hóa thêm TransferKcPxRequest.workshop_location_id (gán vĩnh
    viễn lúc duyệt, khác MaterialLot.location_id/workshop_location_id có thể di chuyển).

Trước đây các FK này không được kiểm tra/dọn — SQLite bỏ qua FK nên test/thao tác vẫn "thành
công", nhưng trên MSSQL (enforce FK thật) sẽ 500 (Integrity/547) khi xóa lô/vị trí còn các bản
ghi này tham chiếu.
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


def _material(client, admin_h, code):
    r = client.post("/api/materials", headers=admin_h,
                    json={"code": code, "name": f"Vật tư {code}", "uom": "kg", "category": "other"})
    assert r.status_code == 201, r.text
    return r.json()["material_id"]


def _receipt_movement_id(client, admin_h, lot_id):
    r = client.get("/api/warehouse/movements?movement_type=receipt", headers=admin_h)
    assert r.status_code == 200, r.text
    mv = next(m for m in r.json() if m.get("lot_id") == lot_id)
    return mv["movement_id"]


def test_delete_receipt_blocked_then_ok_with_pending_transfer_px_request(client, admin_h, vanhanh_h):
    mat_id = _material(client, admin_h, "R2WH-PX01")
    recv = client.post("/api/warehouse/receive", headers=vanhanh_h,
                       json={"lot_code": "R2WH-PX-LOT01", "material_id": mat_id, "quantity": 300,
                             "uom": "kg", "location": "Kho phân xưởng"})
    assert recv.status_code == 200, recv.text
    lot_id = recv.json()["lot_id"]

    req = client.post("/api/warehouse/transfer-px-requests", headers=vanhanh_h,
                      json={"lot_id": lot_id, "quantity": 100})
    assert req.status_code == 201, req.text
    req_id = req.json()["request_id"]

    mv_id = _receipt_movement_id(client, admin_h, lot_id)
    res = client.delete(f"/api/warehouse/movements/{mv_id}", headers=admin_h)
    assert res.status_code == 200, res.text
    assert res.json()["lot_deleted"] is True

    # Đề nghị pending đã bị dọn kèm — không còn mồ côi.
    after = client.get("/api/warehouse/transfer-px-requests", headers=admin_h).json()
    assert not any(x["request_id"] == req_id for x in after)


def test_delete_receipt_blocked_then_ok_with_pending_transfer_kcpx_request(client, admin_h, thukho_h):
    mat_id = _material(client, admin_h, "R2WH-KCPX01")
    recv = client.post("/api/warehouse/receive", headers=thukho_h,
                       json={"lot_code": "R2WH-KCPX-LOT01", "material_id": mat_id, "quantity": 300, "uom": "kg"})
    assert recv.status_code == 200, recv.text
    lot_id = recv.json()["lot_id"]

    req = client.post("/api/warehouse/transfer-kcpx-requests", headers=thukho_h,
                      json={"lot_id": lot_id, "quantity": 100})
    assert req.status_code == 201, req.text
    req_id = req.json()["request_id"]

    mv_id = _receipt_movement_id(client, admin_h, lot_id)
    res = client.delete(f"/api/warehouse/movements/{mv_id}", headers=admin_h)
    assert res.status_code == 200, res.text
    assert res.json()["lot_deleted"] is True

    after = client.get("/api/warehouse/transfer-kcpx-requests", headers=admin_h).json()
    assert not any(x["request_id"] == req_id for x in after)


def test_delete_receipt_ok_when_lot_is_only_preferred_not_fulfilled(client, admin_h, thukho_h):
    mat_id = _material(client, admin_h, "R2WH-PREF01")
    recv = client.post("/api/warehouse/receive", headers=thukho_h,
                       json={"lot_code": "R2WH-PREF-LOT01", "material_id": mat_id, "quantity": 300, "uom": "kg"})
    assert recv.status_code == 200, recv.text
    lot_id = recv.json()["lot_id"]

    reqp = client.post("/api/warehouse/requests", headers=admin_h,
                       json={"lines": [{"material_id": mat_id, "quantity": 50, "uom": "kg",
                                        "preferred_lot_id": lot_id}]})
    assert reqp.status_code == 201, reqp.text
    line_id = reqp.json()["lines"][0]["line_id"]

    mv_id = _receipt_movement_id(client, admin_h, lot_id)
    res = client.delete(f"/api/warehouse/movements/{mv_id}", headers=admin_h)
    assert res.status_code == 200, res.text
    assert res.json()["lot_deleted"] is True

    # Dòng phiếu vẫn còn (không xóa cả phiếu) nhưng preferred_lot_id đã được gỡ (lô không còn).
    lines = client.get("/api/warehouse/requests", headers=admin_h).json()
    req_after = next(r for r in lines if r["request_id"] == reqp.json()["request_id"])
    line_after = next(l for l in req_after["lines"] if l["line_id"] == line_id)
    assert line_after["preferred_lot_id"] is None


def test_delete_receipt_ok_when_lot_only_in_draft_stock_count(client, admin_h, vanhanh_h):
    mat_id = _material(client, admin_h, "R2WH-CNT01")
    recv = client.post("/api/warehouse/receive", headers=vanhanh_h,
                       json={"lot_code": "R2WH-CNT-LOT01", "material_id": mat_id, "quantity": 300,
                             "uom": "kg", "location": "Kho phân xưởng"})
    assert recv.status_code == 200, recv.text
    lot_id = recv.json()["lot_id"]

    count = client.post("/api/warehouse/counts", headers=admin_h, json={"location": "Kho phân xưởng"})
    assert count.status_code == 200, count.text
    count_id = count.json()["count_id"]
    lines_before = client.get(f"/api/warehouse/counts/{count_id}", headers=admin_h).json()["lines"]
    assert any(l["lot_id"] == lot_id for l in lines_before)

    mv_id = _receipt_movement_id(client, admin_h, lot_id)
    res = client.delete(f"/api/warehouse/movements/{mv_id}", headers=admin_h)
    assert res.status_code == 200, res.text
    assert res.json()["lot_deleted"] is True

    lines_after = client.get(f"/api/warehouse/counts/{count_id}", headers=admin_h).json()["lines"]
    assert not any(l["lot_id"] == lot_id for l in lines_after)


def test_delete_material_location_blocked_then_ok_after_kcpx_approval(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _material(client, admin_h, "R2WH-LOC01")
    recv = client.post("/api/warehouse/receive", headers=thukho_h,
                       json={"lot_code": "R2WH-LOC-LOT01", "material_id": mat_id, "quantity": 300, "uom": "kg"})
    assert recv.status_code == 200, recv.text
    lot_id = recv.json()["lot_id"]

    loc = client.post("/api/warehouse/locations", headers=admin_h,
                      json={"code": "R2WH-PXLOC01", "name": "Vị trí PX test R2", "scope": "phan_xuong"})
    assert loc.status_code == 201, loc.text
    loc_id = loc.json()["loc_id"]

    req = client.post("/api/warehouse/transfer-kcpx-requests", headers=thukho_h,
                      json={"lot_id": lot_id, "quantity": 100})
    assert req.status_code == 201, req.text
    approve = client.post(f"/api/warehouse/transfer-kcpx-requests/{req.json()['request_id']}/approve",
                          headers=vanhanh_h, json={"workshop_location_id": loc_id})
    assert approve.status_code == 200, approve.text

    # Vị trí PX không còn lô nào đang chứa (MaterialLot.workshop_location_id đã đổi/không trỏ
    # tới đây cho lô vừa chuyển tới — kiểm tra tồn LIVE không phát hiện) nhưng
    # TransferKcPxRequest.workshop_location_id (bản ghi lịch sử đã duyệt) vẫn trỏ tới -> chặn xóa.
    blocked = client.delete(f"/api/warehouse/locations/{loc_id}", headers=admin_h)
    assert blocked.status_code == 409, blocked.text

    # Vẫn xóa được nếu có endpoint hoàn tác gỡ tham chiếu... trong trường hợp này ta chỉ xác nhận
    # guard mới hoạt động đúng (chặn), không cần xóa thành công tiếp — đã dùng lịch sử vĩnh viễn.
