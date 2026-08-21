"""Điều chuyển Kho công ty → Kho phân xưởng cho 1 lô ĐANG CÓ SẴN ở Kho công ty (khác Xuất sang
ngang: không có receive() đi kèm — lô đã tồn tại từ trước). Thủ kho công ty (thukho,
warehouse.issue) tạo đề nghị — CHƯA động tồn kho; Thủ kho phân xưởng (vanhanh, warehouse.request)
duyệt mới thật sự chuyển, BẮT BUỘC chọn vị trí cất tại Phân xưởng (services/warehouse.py::
create_transfer_kcpx_request/approve_transfer_kcpx_request/reject_transfer_kcpx_request/
undo_transfer_kcpx_request). Nếu vật tư có chỉ tiêu chất lượng bắt buộc, TẠO đề nghị sẽ đưa lô
về lại ON_HOLD (dù trước đó đã qua QC) để buộc KCS duyệt lại trước khi Phân xưởng duyệt được."""

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
def kcs_h(client):
    return _login(client, "kcs", "123456")


def _create_material(client, admin_h, code):
    r = client.post("/api/materials", headers=admin_h,
                    json={"code": code, "name": f"Vật tư {code}", "uom": "kg", "category": "other"})
    assert r.status_code == 201, r.text
    return r.json()["material_id"]


def _receive_lot(client, thukho_h, lot_code, mat_id, quantity):
    r = client.post("/api/warehouse/receive", headers=thukho_h,
                    json={"lot_code": lot_code, "material_id": mat_id, "quantity": quantity, "uom": "kg"})
    assert r.status_code == 200, r.text
    return r.json()


def _get_lot(client, admin_h, lot_id):
    lots = client.get("/api/lots", headers=admin_h).json()
    return next(l for l in lots if l["lot_id"] == lot_id)


def _create_workshop_location(client, admin_h, code):
    r = client.post("/api/warehouse/locations", headers=admin_h,
                    json={"code": code, "name": f"Vị trí {code}", "scope": "phan_xuong"})
    assert r.status_code == 201, r.text
    return r.json()["loc_id"]


def test_create_does_not_move_stock(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "KCPX-01")
    recv = _receive_lot(client, thukho_h, "KCPX-LOT-01", mat_id, 100)
    r = client.post("/api/warehouse/transfer-kcpx-requests", headers=thukho_h,
                    json={"lot_id": recv["lot_id"], "quantity": 40, "reason": "test"})
    assert r.status_code == 201, r.text
    req = r.json()
    assert req["status"] == "pending"
    assert req["quantity"] == 40

    lot = _get_lot(client, admin_h, recv["lot_id"])
    assert lot["location"] == "Kho công ty"
    assert lot["quantity"] == 100
    assert lot["status"] == "available"


def test_thukho_cannot_approve_vanhanh_cannot_create(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "KCPX-02")
    recv = _receive_lot(client, thukho_h, "KCPX-LOT-02", mat_id, 50)

    # vanhanh (scope_warehouse=phan_xuong) không tạo được đề nghị cho lô đang ở Kho công ty.
    r = client.post("/api/warehouse/transfer-kcpx-requests", headers=vanhanh_h,
                    json={"lot_id": recv["lot_id"], "quantity": 10})
    assert r.status_code == 403, r.text

    r2 = client.post("/api/warehouse/transfer-kcpx-requests", headers=thukho_h,
                     json={"lot_id": recv["lot_id"], "quantity": 10})
    assert r2.status_code == 201, r2.text
    request_id = r2.json()["request_id"]

    loc_id = _create_workshop_location(client, admin_h, "KCPX-LOC-A")
    # thukho (không có warehouse.request) không tự duyệt được đề nghị của chính mình.
    r3 = client.post(f"/api/warehouse/transfer-kcpx-requests/{request_id}/approve", headers=thukho_h,
                     json={"workshop_location_id": loc_id})
    assert r3.status_code == 403, r3.text


def test_approve_requires_valid_workshop_location(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "KCPX-03")
    recv = _receive_lot(client, thukho_h, "KCPX-LOT-03", mat_id, 30)
    r = client.post("/api/warehouse/transfer-kcpx-requests", headers=thukho_h,
                    json={"lot_id": recv["lot_id"], "quantity": 30})
    request_id = r.json()["request_id"]

    # Thiếu field bắt buộc -> lỗi validate payload.
    missing = client.post(f"/api/warehouse/transfer-kcpx-requests/{request_id}/approve", headers=vanhanh_h,
                          json={})
    assert missing.status_code == 422, missing.text

    # loc_id không tồn tại -> DomainError rõ ràng.
    invalid = client.post(f"/api/warehouse/transfer-kcpx-requests/{request_id}/approve", headers=vanhanh_h,
                          json={"workshop_location_id": "khong-ton-tai"})
    assert invalid.status_code == 409, invalid.text
    assert "vị trí" in invalid.json()["detail"].lower()


def test_approve_moves_lot_to_workshop_with_location(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "KCPX-04")
    recv = _receive_lot(client, thukho_h, "KCPX-LOT-04", mat_id, 25)
    r = client.post("/api/warehouse/transfer-kcpx-requests", headers=thukho_h,
                    json={"lot_id": recv["lot_id"], "quantity": 25})
    request_id = r.json()["request_id"]
    loc_id = _create_workshop_location(client, admin_h, "KCPX-LOC-B")

    ap = client.post(f"/api/warehouse/transfer-kcpx-requests/{request_id}/approve", headers=vanhanh_h,
                     json={"workshop_location_id": loc_id})
    assert ap.status_code == 200, ap.text
    body = ap.json()
    assert body["status"] == "approved"
    assert body["workshop_location_id"] == loc_id

    lot = _get_lot(client, admin_h, recv["lot_id"])
    assert "phân xưởng" in lot["location"].lower()
    assert lot.get("location_id") is None

    # Duyệt lần 2 phải báo lỗi (đã xử lý).
    ap2 = client.post(f"/api/warehouse/transfer-kcpx-requests/{request_id}/approve", headers=vanhanh_h,
                      json={"workshop_location_id": loc_id})
    assert ap2.status_code == 409, ap2.text


def test_reject_leaves_lot_unchanged(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "KCPX-05")
    recv = _receive_lot(client, thukho_h, "KCPX-LOT-05", mat_id, 20)
    r = client.post("/api/warehouse/transfer-kcpx-requests", headers=thukho_h,
                    json={"lot_id": recv["lot_id"], "quantity": 20})
    request_id = r.json()["request_id"]

    rej = client.post(f"/api/warehouse/transfer-kcpx-requests/{request_id}/reject", headers=vanhanh_h,
                      json={"reason": "Sai vật tư"})
    assert rej.status_code == 200, rej.text
    assert rej.json()["status"] == "rejected"

    lot = _get_lot(client, admin_h, recv["lot_id"])
    assert lot["location"] == "Kho công ty"
    assert lot["quantity"] == 20
    assert lot["status"] == "available"


def test_undo_after_approve_admin_only(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "KCPX-06")
    recv = _receive_lot(client, thukho_h, "KCPX-LOT-06", mat_id, 15)
    r = client.post("/api/warehouse/transfer-kcpx-requests", headers=thukho_h,
                    json={"lot_id": recv["lot_id"], "quantity": 15})
    request_id = r.json()["request_id"]
    loc_id = _create_workshop_location(client, admin_h, "KCPX-LOC-C")
    client.post(f"/api/warehouse/transfer-kcpx-requests/{request_id}/approve", headers=vanhanh_h,
               json={"workshop_location_id": loc_id})

    u1 = client.post(f"/api/warehouse/transfer-kcpx-requests/{request_id}/undo", headers=vanhanh_h)
    assert u1.status_code == 403, u1.text

    u2 = client.post(f"/api/warehouse/transfer-kcpx-requests/{request_id}/undo", headers=admin_h)
    assert u2.status_code == 200, u2.text
    assert u2.json()["status"] == "pending"
    assert u2.json()["workshop_location_id"] is None

    lot = _get_lot(client, admin_h, recv["lot_id"])
    assert lot["location"] == "Kho công ty"
    assert lot["quantity"] == 15


def test_qc_required_material_rehold_on_create_blocks_until_kcs_release(client, admin_h, thukho_h, vanhanh_h, kcs_h):
    mat_id = _create_material(client, admin_h, "KCPX-QC-01")
    p = client.post("/api/qc/parameters", headers=admin_h,
                    json={"code": "KCPX_QC_PARAM", "name": "Độ ẩm", "unit": "%", "lsl": 3, "usl": 6})
    assert p.status_code == 201, p.text
    param_id = p.json()["param_id"]
    g = client.post("/api/qc/groups", headers=admin_h,
                    json={"code": "KCPX-GRP-01", "name": "Chỉ tiêu điều chuyển kcpx test"})
    assert g.status_code == 201, g.text
    group_id = g.json()["group_id"]
    it = client.post(f"/api/qc/groups/{group_id}/items", headers=admin_h,
                     json={"param_id": param_id, "mandatory": True})
    assert it.status_code == 201, it.text
    link = client.post(f"/api/materials/{mat_id}/qc-groups", headers=admin_h,
                       json={"group_id": group_id, "mandatory": True})
    assert link.status_code == 201, link.text

    # Nhận hàng -> HOLD ngay (vật tư có chỉ tiêu bắt buộc) -> KCS duyệt lần đầu -> released.
    recv = _receive_lot(client, thukho_h, "KCPX-LOT-QC-01", mat_id, 60)
    lot = _get_lot(client, admin_h, recv["lot_id"])
    assert lot["status"] == "on_hold"
    rec = client.post("/api/quality/results", headers=thukho_h,
                      json={"scope_type": "lot", "scope_id": lot["lot_id"], "parameter": "KCPX_QC_PARAM",
                            "value": 4.5, "lower_limit": 3, "upper_limit": 6})
    assert rec.status_code == 201, rec.text
    rel = client.post("/api/quality/hold", headers=kcs_h,
                      json={"scope_type": "lot", "scope_id": lot["lot_id"], "on_hold": False})
    assert rel.status_code == 200, rel.text
    lot = _get_lot(client, admin_h, recv["lot_id"])
    assert lot["status"] != "on_hold"

    # Tạo đề nghị điều chuyển CT->PX cho lô ĐÃ được duyệt trước đó -> vẫn bị đưa lại về HOLD.
    r = client.post("/api/warehouse/transfer-kcpx-requests", headers=thukho_h,
                    json={"lot_id": recv["lot_id"], "quantity": 60})
    assert r.status_code == 201, r.text
    request_id = r.json()["request_id"]
    lot = _get_lot(client, admin_h, recv["lot_id"])
    assert lot["status"] == "on_hold"

    # Phân xưởng chưa duyệt được vì lô đang chờ KCS duyệt lại.
    loc_id = _create_workshop_location(client, admin_h, "KCPX-LOC-QC")
    blocked = client.post(f"/api/warehouse/transfer-kcpx-requests/{request_id}/approve", headers=vanhanh_h,
                          json={"workshop_location_id": loc_id})
    assert blocked.status_code == 409, blocked.text
    assert "KCS" in blocked.json()["detail"]

    # KCS duyệt (release) lại -> Phân xưởng duyệt được.
    rel2 = client.post("/api/quality/hold", headers=kcs_h,
                       json={"scope_type": "lot", "scope_id": lot["lot_id"], "on_hold": False})
    assert rel2.status_code == 200, rel2.text
    ap = client.post(f"/api/warehouse/transfer-kcpx-requests/{request_id}/approve", headers=vanhanh_h,
                     json={"workshop_location_id": loc_id})
    assert ap.status_code == 200, ap.text
    assert ap.json()["status"] == "approved"


def test_workshop_location_crud_and_delete_guard(client, admin_h, thukho_h, vanhanh_h):
    r = client.post("/api/warehouse/locations", headers=admin_h,
                    json={"code": "KCPX-LOC-CRUD", "name": "Vị trí test CRUD", "zone": "Khu 1",
                          "scope": "phan_xuong"})
    assert r.status_code == 201, r.text
    loc = r.json()
    assert loc["scope"] == "phan_xuong"

    lst = client.get("/api/warehouse/locations", headers=admin_h).json()
    assert any(l["loc_id"] == loc["loc_id"] for l in lst)

    upd = client.put(f"/api/warehouse/locations/{loc['loc_id']}", headers=admin_h,
                     json={"code": "KCPX-LOC-CRUD", "name": "Đã đổi tên", "active": True, "scope": "phan_xuong"})
    assert upd.status_code == 200, upd.text
    assert upd.json()["name"] == "Đã đổi tên"

    # scope không hợp lệ -> báo lỗi rõ ràng.
    bad_scope = client.post("/api/warehouse/locations", headers=admin_h,
                            json={"code": "KCPX-LOC-BADSCOPE", "name": "x", "scope": "khong_hop_le"})
    assert bad_scope.status_code == 409, bad_scope.text

    # Gán 1 lô vào vị trí này (qua điều chuyển thật) -> không xóa được.
    mat_id = _create_material(client, admin_h, "KCPX-07")
    recv = _receive_lot(client, thukho_h, "KCPX-LOT-07", mat_id, 5)
    reqr = client.post("/api/warehouse/transfer-kcpx-requests", headers=thukho_h,
                       json={"lot_id": recv["lot_id"], "quantity": 5})
    client.post(f"/api/warehouse/transfer-kcpx-requests/{reqr.json()['request_id']}/approve", headers=vanhanh_h,
               json={"workshop_location_id": loc["loc_id"]})

    dele = client.delete(f"/api/warehouse/locations/{loc['loc_id']}", headers=admin_h)
    assert dele.status_code == 409, dele.text


def test_relocate_lot_workshop(client, admin_h, thukho_h, vanhanh_h):
    """Gán/đổi vị trí kho phân xưởng cho 1 lô đang ở Kho phân xưởng — mirror relocate_lot (Kho
    công ty), qua endpoint riêng /lots/{id}/relocate-workshop."""
    mat_id = _create_material(client, admin_h, "KCPX-08")
    recv = _receive_lot(client, thukho_h, "KCPX-LOT-08", mat_id, 12)
    reqr = client.post("/api/warehouse/transfer-kcpx-requests", headers=thukho_h,
                       json={"lot_id": recv["lot_id"], "quantity": 12})
    loc_a = _create_workshop_location(client, admin_h, "KCPX-LOC-D")
    loc_b = _create_workshop_location(client, admin_h, "KCPX-LOC-E")
    ap = client.post(f"/api/warehouse/transfer-kcpx-requests/{reqr.json()['request_id']}/approve",
                     headers=vanhanh_h, json={"workshop_location_id": loc_a})
    assert ap.status_code == 200, ap.text
    lot_id = recv["lot_id"]  # chuyển NGUYÊN lô (quantity == tồn) -> giữ nguyên lot_id

    # Đổi sang vị trí khác trong Kho phân xưởng.
    rel = client.post(f"/api/warehouse/lots/{lot_id}/relocate-workshop", headers=vanhanh_h,
                      json={"workshop_location_id": loc_b})
    assert rel.status_code == 200, rel.text
    assert rel.json()["workshop_location_id"] == loc_b

    lot = _get_lot(client, admin_h, lot_id)
    assert lot["workshop_location_id"] == loc_b

    # thukho (scope kho công ty) không đổi được vị trí lô đang ở Kho phân xưởng.
    forbidden = client.post(f"/api/warehouse/lots/{lot_id}/relocate-workshop", headers=thukho_h,
                            json={"workshop_location_id": loc_a})
    assert forbidden.status_code == 403, forbidden.text

    # Không dùng được endpoint relocate (Kho công ty) cho lô đang ở Kho phân xưởng.
    wrong_endpoint = client.post(f"/api/warehouse/lots/{lot_id}/relocate", headers=vanhanh_h,
                                 json={"location_id": loc_a})
    assert wrong_endpoint.status_code == 409, wrong_endpoint.text
