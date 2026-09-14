"""Sửa/Xóa đề nghị điều chuyển kho (2 chiều: Công ty→Phân xưởng và Phân xưởng→Công ty) trong lúc
còn "pending" — yêu cầu người dùng 2026-09-14. Chiều Công ty→Phân xưởng (TransferKcPxRequest) có
thêm điều kiện: nếu vật tư cần KCS duyệt (chỉ tiêu chất lượng bắt buộc), CHỈ cho sửa/xóa khi lô
còn "Chờ KCS duyệt" (on_hold) — KCS duyệt xong rồi thì khóa lại, không sửa/xóa được nữa. Vật tư
KHÔNG cần KCS thì luôn sửa/xóa được trong lúc còn pending (không có khái niệm "chờ KCS").
Chiều Phân xưởng→Công ty (TransferPxRequest) không có điều kiện này — create_transfer_px_request
đã chặn cứng không cho tạo đề nghị với lô đang HOLD ngay từ đầu."""

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
def kcs_h(client):
    return _login(client, "kcs", "123456")


@pytest.fixture(scope="module")
def vanhanh_h(client):
    return _login(client, "vanhanh", "123456")


def _create_material(client, admin_h, code):
    r = client.post("/api/materials", headers=admin_h,
                    json={"code": code, "name": f"Vật tư {code}", "uom": "kg", "category": "other"})
    assert r.status_code == 201, r.text
    return r.json()["material_id"]


def test_update_and_cancel_transfer_px_request(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "TXEDIT-PX01")
    recv = client.post("/api/warehouse/receive", headers=thukho_h,
                       json={"lot_code": "LOT-TXEDIT-PX01", "material_id": mat_id, "quantity": 100, "uom": "kg"})
    lot_id = recv.json()["lot_id"]
    client.post("/api/warehouse/transfer", headers=thukho_h,
               json={"lot_id": lot_id, "quantity": 100, "location_to": "Kho phân xưởng"})

    req = client.post("/api/warehouse/transfer-px-requests", headers=vanhanh_h,
                      json={"lot_id": lot_id, "quantity": 40, "reason": "ban đầu"})
    assert req.status_code == 201, req.text
    request_id = req.json()["request_id"]

    upd = client.put(f"/api/warehouse/transfer-px-requests/{request_id}", headers=vanhanh_h,
                     json={"quantity": 25, "reason": "sửa lại"})
    assert upd.status_code == 200, upd.text
    assert upd.json()["quantity"] == 25
    assert upd.json()["reason"] == "sửa lại"

    over = client.put(f"/api/warehouse/transfer-px-requests/{request_id}", headers=vanhanh_h,
                      json={"quantity": 9999})
    assert over.status_code == 409, over.text

    cancel = client.delete(f"/api/warehouse/transfer-px-requests/{request_id}", headers=vanhanh_h)
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["status"] == "cancelled"

    # Đã cancelled -> sửa/xóa lại đều bị chặn.
    blocked_upd = client.put(f"/api/warehouse/transfer-px-requests/{request_id}", headers=vanhanh_h,
                             json={"quantity": 10})
    assert blocked_upd.status_code == 409, blocked_upd.text
    blocked_cancel = client.delete(f"/api/warehouse/transfer-px-requests/{request_id}", headers=vanhanh_h)
    assert blocked_cancel.status_code == 409, blocked_cancel.text


def test_update_and_cancel_transfer_px_request_blocked_after_approve(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "TXEDIT-PX02")
    recv = client.post("/api/warehouse/receive", headers=thukho_h,
                       json={"lot_code": "LOT-TXEDIT-PX02", "material_id": mat_id, "quantity": 50, "uom": "kg"})
    lot_id = recv.json()["lot_id"]
    client.post("/api/warehouse/transfer", headers=thukho_h,
               json={"lot_id": lot_id, "quantity": 50, "location_to": "Kho phân xưởng"})
    req = client.post("/api/warehouse/transfer-px-requests", headers=vanhanh_h,
                      json={"lot_id": lot_id, "quantity": 20})
    request_id = req.json()["request_id"]

    ok = client.post(f"/api/warehouse/transfer-px-requests/{request_id}/approve", headers=admin_h)
    assert ok.status_code == 200, ok.text

    upd = client.put(f"/api/warehouse/transfer-px-requests/{request_id}", headers=vanhanh_h, json={"quantity": 5})
    assert upd.status_code == 409, upd.text
    cancel = client.delete(f"/api/warehouse/transfer-px-requests/{request_id}", headers=vanhanh_h)
    assert cancel.status_code == 409, cancel.text


def test_update_and_cancel_transfer_kcpx_request_no_qc_required(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "TXEDIT-KCPX01")
    recv = client.post("/api/warehouse/receive", headers=thukho_h,
                       json={"lot_code": "LOT-TXEDIT-KCPX01", "material_id": mat_id, "quantity": 80, "uom": "kg"})
    lot_id = recv.json()["lot_id"]
    assert recv.json()["status"] == "available"  # không cần KCS -> không HOLD

    req = client.post("/api/warehouse/transfer-kcpx-requests", headers=thukho_h,
                      json={"lot_id": lot_id, "quantity": 30})
    assert req.status_code == 201, req.text
    request_id = req.json()["request_id"]

    upd = client.put(f"/api/warehouse/transfer-kcpx-requests/{request_id}", headers=thukho_h,
                     json={"quantity": 15, "reason": "giảm bớt"})
    assert upd.status_code == 200, upd.text
    assert upd.json()["quantity"] == 15

    cancel = client.delete(f"/api/warehouse/transfer-kcpx-requests/{request_id}", headers=thukho_h)
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["status"] == "cancelled"


def test_transfer_kcpx_request_edit_blocked_after_kcs_release(client, admin_h, thukho_h, kcs_h):
    """Vật tư CẦN KCS duyệt: tạo đề nghị -> lô bị đưa về HOLD -> sửa/xóa vẫn cho phép (còn "Chờ
    KCS duyệt") -> KCS duyệt xong -> sửa/xóa bị chặn (409), dù đề nghị VẪN đang "pending"."""
    mat = client.post("/api/materials", headers=admin_h,
                      json={"code": "TXEDIT-KCPX02", "name": "Cần KCS", "uom": "kg", "category": "other"})
    mat_id = mat.json()["material_id"]
    grp = client.post("/api/qc/groups", headers=admin_h, json={"code": "GRP-TXEDIT-KCPX02", "name": "Nhóm test"})
    assert grp.status_code == 201, grp.text
    p = client.post("/api/qc/parameters", headers=admin_h,
                    json={"code": "TXEDIT_PARAM", "name": "Độ ẩm", "unit": "%", "lsl": 3, "usl": 6})
    assert p.status_code == 201, p.text
    link = client.post(f"/api/qc/groups/{grp.json()['group_id']}/items", headers=admin_h,
                       json={"param_id": p.json()["param_id"], "mandatory": True})
    assert link.status_code == 201, link.text
    assign = client.post(f"/api/materials/{mat_id}/qc-groups", headers=admin_h,
                        json={"group_id": grp.json()["group_id"], "mandatory": True})
    assert assign.status_code == 201, assign.text

    recv = client.post("/api/warehouse/receive", headers=thukho_h,
                       json={"lot_code": "LOT-TXEDIT-KCPX02", "material_id": mat_id, "quantity": 60, "uom": "kg"})
    assert recv.status_code == 200, recv.text
    lot_id = recv.json()["lot_id"]
    assert recv.json()["status"] == "on_hold"

    req = client.post("/api/warehouse/transfer-kcpx-requests", headers=thukho_h,
                      json={"lot_id": lot_id, "quantity": 20})
    assert req.status_code == 201, req.text
    request_id = req.json()["request_id"]

    # Lô còn "Chờ KCS duyệt" -> sửa vẫn được.
    upd_ok = client.put(f"/api/warehouse/transfer-kcpx-requests/{request_id}", headers=thukho_h,
                        json={"quantity": 18})
    assert upd_ok.status_code == 200, upd_ok.text

    # KCS khai báo + duyệt xong.
    rec = client.post("/api/quality/results", headers=thukho_h,
                      json={"scope_type": "lot", "scope_id": lot_id, "parameter": "TXEDIT_PARAM",
                            "value": 4.5, "lower_limit": 3, "upper_limit": 6})
    assert rec.status_code == 201, rec.text
    rel = client.post("/api/quality/hold", headers=kcs_h,
                      json={"scope_type": "lot", "scope_id": lot_id, "on_hold": False})
    assert rel.status_code == 200, rel.text

    # Đề nghị VẪN đang "pending" nhưng lô đã KCS duyệt xong -> sửa/xóa bị chặn.
    upd_blocked = client.put(f"/api/warehouse/transfer-kcpx-requests/{request_id}", headers=thukho_h,
                             json={"quantity": 10})
    assert upd_blocked.status_code == 409, upd_blocked.text
    cancel_blocked = client.delete(f"/api/warehouse/transfer-kcpx-requests/{request_id}", headers=thukho_h)
    assert cancel_blocked.status_code == 409, cancel_blocked.text
