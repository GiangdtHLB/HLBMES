"""Điều chuyển kho công ty — 2 chiều:

1. Kho phân xưởng → Kho công ty: đề nghị (vanhanh, warehouse.request) → duyệt (thukho,
   warehouse.receive) mới thật sự chuyển kho — sau khi duyệt chỉ ADMIN mới hoàn tác được
   (services/warehouse.py::create_transfer_px_request/approve_transfer_px_request/
   reject_transfer_px_request/undo_transfer_px_request).
2. Kho công ty → Nhà máy khác: thukho (warehouse.issue) xuất ngay, tự do hoàn tác cho tới khi
   truongphong_kh (warehouse.transfer_approve_factory) duyệt — sau đó chỉ ADMIN mới hoàn tác
   được (services/warehouse.py::transfer_to_factory/approve_transfer_to_factory, undo_issue).

Cũng test guarded-delete cho FactoryLocation (danh mục nhà máy khác)."""

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
def thukho_h(client):
    return _login(client, "thukho", "123456")


@pytest.fixture(scope="module")
def kcs_h(client):
    return _login(client, "kcs", "123456")


@pytest.fixture(scope="module")
def truongphong_kh_h(client):
    return _login(client, "truongphong_kh", "123456")


def _create_material(client, admin_h, code):
    r = client.post("/api/materials", headers=admin_h,
                    json={"code": code, "name": f"Vật tư {code}", "uom": "kg", "category": "other"})
    assert r.status_code == 201, r.text
    return r.json()["material_id"]


def _receive_at_workshop(client, thukho_h, mat_id, lot_code, qty=50):
    """Nhập kho công ty rồi chuyển thẳng (transfer đã có sẵn) sang Kho phân xưởng."""
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": lot_code, "material_id": mat_id, "quantity": qty, "uom": "kg"})
    assert rc.status_code == 200, rc.text
    lot_id = rc.json()["lot_id"]
    tr = client.post("/api/warehouse/transfer", headers=thukho_h,
                     json={"lot_id": lot_id, "quantity": qty, "location_to": "Kho phân xưởng"})
    assert tr.status_code == 200, tr.text
    return lot_id


def _create_factory(client, admin_h, code, name):
    r = client.post("/api/factory-locations", headers=admin_h, json={"code": code, "name": name})
    assert r.status_code == 201, r.text
    return r.json()["factory_id"]


# ---- Chiều 1: Kho phân xưởng → Kho công ty ----

def test_transfer_px_request_full_flow(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "TPW-FULL")
    lot_id = _receive_at_workshop(client, thukho_h, mat_id, "LOT-TPW-FULL", qty=40)

    req = client.post("/api/warehouse/transfer-px-requests", headers=vanhanh_h,
                      json={"lot_id": lot_id, "quantity": 40, "reason": "Nhận thừa"})
    assert req.status_code == 201, req.text
    body = req.json()
    assert body["status"] == "pending"
    request_id = body["request_id"]

    # chưa động tồn kho lúc tạo — lô vẫn còn ở Kho phân xưởng
    lots = client.get("/api/lots", headers=admin_h).json()
    lot = next(l for l in lots if l["lot_id"] == lot_id)
    assert "phân xưởng" in lot["location"].lower()

    # vanhanh (chỉ có warehouse.request) không được duyệt
    denied = client.post(f"/api/warehouse/transfer-px-requests/{request_id}/approve", headers=vanhanh_h)
    assert denied.status_code == 403, denied.text

    ok = client.post(f"/api/warehouse/transfer-px-requests/{request_id}/approve", headers=thukho_h)
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "approved"

    lots = client.get("/api/lots", headers=admin_h).json()
    lot = next(l for l in lots if l["lot_id"] == lot_id)
    assert lot["location"] == "Kho công ty"

    # đã duyệt — thukho (không phải admin) không hoàn tác được
    denied_undo = client.post(f"/api/warehouse/transfer-px-requests/{request_id}/undo", headers=thukho_h)
    assert denied_undo.status_code == 403, denied_undo.text

    undo = client.post(f"/api/warehouse/transfer-px-requests/{request_id}/undo", headers=admin_h)
    assert undo.status_code == 200, undo.text
    assert undo.json()["reversed"] is True

    lots = client.get("/api/lots", headers=admin_h).json()
    lot = next(l for l in lots if l["lot_id"] == lot_id)
    assert "phân xưởng" in lot["location"].lower()

    # hoàn tác lần 2 phải bị chặn
    undo_again = client.post(f"/api/warehouse/transfer-px-requests/{request_id}/undo", headers=admin_h)
    assert undo_again.status_code == 409, undo_again.text


def test_transfer_px_request_reject(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "TPW-REJ")
    lot_id = _receive_at_workshop(client, thukho_h, mat_id, "LOT-TPW-REJ", qty=10)

    req = client.post("/api/warehouse/transfer-px-requests", headers=vanhanh_h,
                      json={"lot_id": lot_id, "quantity": 10}).json()
    r = client.post(f"/api/warehouse/transfer-px-requests/{req['request_id']}/reject",
                    headers=thukho_h, json={"reason": "Sai số lượng"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"

    lots = client.get("/api/lots", headers=admin_h).json()
    lot = next(l for l in lots if l["lot_id"] == lot_id)
    assert "phân xưởng" in lot["location"].lower()   # tồn kho không đổi


def test_transfer_px_request_blocked_when_not_at_workshop(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "TPW-NOTWS")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "LOT-TPW-NOTWS", "material_id": mat_id, "quantity": 5, "uom": "kg"})
    lot_id = rc.json()["lot_id"]
    r = client.post("/api/warehouse/transfer-px-requests", headers=vanhanh_h,
                    json={"lot_id": lot_id, "quantity": 5})
    assert r.status_code == 409, r.text


def test_transfer_px_request_requires_perm(client, admin_h, thukho_h, kcs_h):
    mat_id = _create_material(client, admin_h, "TPW-PERM")
    lot_id = _receive_at_workshop(client, thukho_h, mat_id, "LOT-TPW-PERM", qty=5)
    r = client.post("/api/warehouse/transfer-px-requests", headers=kcs_h,
                    json={"lot_id": lot_id, "quantity": 5})
    assert r.status_code == 403, r.text


# ---- Chiều 2: Kho công ty → Nhà máy khác ----

def test_transfer_to_factory_full_flow(client, admin_h, thukho_h, truongphong_kh_h):
    factory_id = _create_factory(client, admin_h, "NM-01", "Nhà máy Đông Mai 2")
    mat_id = _create_material(client, admin_h, "CTNM-FULL")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "LOT-CTNM-FULL", "material_id": mat_id, "quantity": 60, "uom": "kg"})
    lot_id = rc.json()["lot_id"]

    r = client.post("/api/warehouse/transfer-to-factory", headers=thukho_h,
                    json={"lot_id": lot_id, "quantity": 60, "factory_id": factory_id, "reason": "Hỗ trợ NM khác"})
    assert r.status_code == 200, r.text
    movement_id = r.json()["movement_id"]

    lot = client.get("/api/lots", headers=admin_h).json()
    lot = next(l for l in lot if l["lot_id"] == lot_id)
    assert lot["quantity"] == 0

    # chưa duyệt — thukho tự hoàn tác được
    undo1 = client.post(f"/api/warehouse/movements/{movement_id}/undo-issue", headers=thukho_h)
    assert undo1.status_code == 200, undo1.text
    lot = client.get("/api/lots", headers=admin_h).json()
    lot = next(l for l in lot if l["lot_id"] == lot_id)
    assert lot["quantity"] == 60

    # điều chuyển lần 2 rồi để truongphong_kh duyệt
    r2 = client.post("/api/warehouse/transfer-to-factory", headers=thukho_h,
                     json={"lot_id": lot_id, "quantity": 60, "factory_id": factory_id})
    movement_id2 = r2.json()["movement_id"]

    denied_approve = client.post(f"/api/warehouse/movements/{movement_id2}/approve-factory", headers=thukho_h)
    assert denied_approve.status_code == 403, denied_approve.text

    approve = client.post(f"/api/warehouse/movements/{movement_id2}/approve-factory", headers=truongphong_kh_h)
    assert approve.status_code == 200, approve.text
    assert approve.json()["approved_by"] == "truongphong_kh"

    # đã duyệt — thukho không hoàn tác được nữa, chỉ admin
    denied_undo = client.post(f"/api/warehouse/movements/{movement_id2}/undo-issue", headers=thukho_h)
    assert denied_undo.status_code == 403, denied_undo.text

    undo2 = client.post(f"/api/warehouse/movements/{movement_id2}/undo-issue", headers=admin_h)
    assert undo2.status_code == 200, undo2.text
    lot = client.get("/api/lots", headers=admin_h).json()
    lot = next(l for l in lot if l["lot_id"] == lot_id)
    assert lot["quantity"] == 60


def test_transfer_to_factory_blocked_when_at_workshop(client, admin_h, thukho_h):
    factory_id = _create_factory(client, admin_h, "NM-02", "Nhà máy khác 2")
    mat_id = _create_material(client, admin_h, "CTNM-WS")
    lot_id = _receive_at_workshop(client, thukho_h, mat_id, "LOT-CTNM-WS", qty=10)
    r = client.post("/api/warehouse/transfer-to-factory", headers=thukho_h,
                    json={"lot_id": lot_id, "quantity": 10, "factory_id": factory_id})
    assert r.status_code == 409, r.text


def test_transfer_to_factory_requires_perm(client, admin_h, kcs_h):
    factory_id = _create_factory(client, admin_h, "NM-03", "Nhà máy khác 3")
    mat_id = _create_material(client, admin_h, "CTNM-PERM")
    rc = client.post("/api/warehouse/receive", headers=admin_h,
                     json={"lot_code": "LOT-CTNM-PERM", "material_id": mat_id, "quantity": 5, "uom": "kg"})
    lot_id = rc.json()["lot_id"]
    r = client.post("/api/warehouse/transfer-to-factory", headers=kcs_h,
                    json={"lot_id": lot_id, "quantity": 5, "factory_id": factory_id})
    assert r.status_code == 403, r.text


def test_approve_transfer_to_factory_requires_perm(client, admin_h, thukho_h):
    factory_id = _create_factory(client, admin_h, "NM-04", "Nhà máy khác 4")
    mat_id = _create_material(client, admin_h, "CTNM-APPROVEPERM")
    rc = client.post("/api/warehouse/receive", headers=admin_h,
                     json={"lot_code": "LOT-CTNM-APPROVEPERM", "material_id": mat_id, "quantity": 5, "uom": "kg"})
    lot_id = rc.json()["lot_id"]
    r = client.post("/api/warehouse/transfer-to-factory", headers=thukho_h,
                    json={"lot_id": lot_id, "quantity": 5, "factory_id": factory_id})
    movement_id = r.json()["movement_id"]
    denied = client.post(f"/api/warehouse/movements/{movement_id}/approve-factory", headers=thukho_h)
    assert denied.status_code == 403, denied.text


# ---- Danh mục Nhà máy khác: CRUD + guarded delete ----

def test_factory_location_crud_and_guarded_delete(client, admin_h, thukho_h):
    factory_id = _create_factory(client, admin_h, "NM-CRUD", "Nhà máy CRUD test")

    upd = client.put(f"/api/factory-locations/{factory_id}", headers=admin_h,
                     json={"code": "NM-CRUD", "name": "Nhà máy CRUD test (sửa)", "active": True})
    assert upd.status_code == 200, upd.text
    assert upd.json()["name"] == "Nhà máy CRUD test (sửa)"

    # chưa dùng — xóa được
    delok = client.delete(f"/api/factory-locations/{factory_id}", headers=admin_h)
    assert delok.status_code == 204, delok.text

    # tạo lại + dùng trong 1 giao dịch điều chuyển → chặn xóa
    factory_id2 = _create_factory(client, admin_h, "NM-CRUD2", "Nhà máy CRUD test 2")
    mat_id = _create_material(client, admin_h, "CTNM-CRUDDEL")
    rc = client.post("/api/warehouse/receive", headers=admin_h,
                     json={"lot_code": "LOT-CTNM-CRUDDEL", "material_id": mat_id, "quantity": 5, "uom": "kg"})
    lot_id = rc.json()["lot_id"]
    client.post("/api/warehouse/transfer-to-factory", headers=thukho_h,
               json={"lot_id": lot_id, "quantity": 5, "factory_id": factory_id2})

    delblocked = client.delete(f"/api/factory-locations/{factory_id2}", headers=admin_h)
    assert delblocked.status_code == 409, delblocked.text
