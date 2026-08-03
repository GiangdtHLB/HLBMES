"""Xuất sang ngang: hàng cập Kho công ty (receive() thường — tăng tồn công ty, ghi StockMovement
type=receipt) nhưng đích thực sự là Kho phân xưởng. Thủ kho công ty (thukho, warehouse.receive)
tạo đề nghị — CHƯA đổi vị trí lô; Thủ kho phân xưởng (vanhanh, warehouse.request) duyệt mới thật
sự chuyển (services/warehouse.py::create_sang_ngang/approve_sang_ngang/reject_sang_ngang/
undo_sang_ngang). Nếu vật tư có chỉ tiêu chất lượng bắt buộc, phân xưởng không duyệt được cho
tới khi KCS duyệt xong (lot rời ON_HOLD)."""

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


def _get_lot_status(client, admin_h, lot_id):
    r = client.get(f"/api/lots/{lot_id}/qc-status", headers=admin_h)
    assert r.status_code == 200, r.text
    return r.json()


def test_create_sang_ngang_receipts_at_company_pending(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "SNG-01")
    r = client.post("/api/warehouse/sang-ngang", headers=thukho_h,
                    json={"lot_code": "SNG-LOT-01", "material_id": mat_id, "quantity": 100, "uom": "kg"})
    assert r.status_code == 201, r.text
    req = r.json()
    assert req["status"] == "pending"
    assert req["quantity"] == 100

    lots = client.get("/api/lots", headers=admin_h).json()
    lot = next(l for l in lots if l["lot_id"] == req["lot_id"])
    assert lot["location"] == "Kho công ty"  # chưa chuyển
    assert lot["quantity"] == 100
    assert lot["status"] == "available"


def test_vanhanh_cannot_create_thukho_cannot_approve(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "SNG-02")
    # vanhanh (scope_warehouse=phan_xuong) không tạo được — receive() chặn scope "Kho công ty".
    r = client.post("/api/warehouse/sang-ngang", headers=vanhanh_h,
                    json={"lot_code": "SNG-LOT-02", "material_id": mat_id, "quantity": 50, "uom": "kg"})
    assert r.status_code == 403, r.text

    r2 = client.post("/api/warehouse/sang-ngang", headers=thukho_h,
                     json={"lot_code": "SNG-LOT-02", "material_id": mat_id, "quantity": 50, "uom": "kg"})
    assert r2.status_code == 201, r2.text
    request_id = r2.json()["request_id"]

    # thukho (không có warehouse.request) không tự duyệt được đề nghị của chính mình.
    r3 = client.post(f"/api/warehouse/sang-ngang/{request_id}/approve", headers=thukho_h)
    assert r3.status_code == 403, r3.text


def test_approve_moves_lot_to_workshop(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "SNG-03")
    r = client.post("/api/warehouse/sang-ngang", headers=thukho_h,
                    json={"lot_code": "SNG-LOT-03", "material_id": mat_id, "quantity": 30, "uom": "kg"})
    assert r.status_code == 201, r.text
    req = r.json()

    ap = client.post(f"/api/warehouse/sang-ngang/{req['request_id']}/approve", headers=vanhanh_h)
    assert ap.status_code == 200, ap.text
    assert ap.json()["status"] == "approved"

    lots = client.get("/api/lots", headers=admin_h).json()
    moved = [l for l in lots if l["lot_code"] == "SNG-LOT-03"]
    assert any("phân xưởng" in (l["location"] or "").lower() for l in moved)
    assert not any(l["location"] == "Kho công ty" and l["quantity"] > 0 for l in moved)

    # Duyệt lần 2 phải báo lỗi (đã xử lý).
    ap2 = client.post(f"/api/warehouse/sang-ngang/{req['request_id']}/approve", headers=vanhanh_h)
    assert ap2.status_code == 409, ap2.text


def test_reject_leaves_lot_at_company(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "SNG-04")
    r = client.post("/api/warehouse/sang-ngang", headers=thukho_h,
                    json={"lot_code": "SNG-LOT-04", "material_id": mat_id, "quantity": 20, "uom": "kg"})
    req = r.json()
    rej = client.post(f"/api/warehouse/sang-ngang/{req['request_id']}/reject", headers=vanhanh_h,
                      json={"reason": "Sai vật tư"})
    assert rej.status_code == 200, rej.text
    assert rej.json()["status"] == "rejected"

    lots = client.get("/api/lots", headers=admin_h).json()
    lot = next(l for l in lots if l["lot_code"] == "SNG-LOT-04")
    assert lot["location"] == "Kho công ty"
    assert lot["quantity"] == 20


def test_undo_after_approve_admin_only(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "SNG-05")
    r = client.post("/api/warehouse/sang-ngang", headers=thukho_h,
                    json={"lot_code": "SNG-LOT-05", "material_id": mat_id, "quantity": 40, "uom": "kg"})
    req = r.json()
    client.post(f"/api/warehouse/sang-ngang/{req['request_id']}/approve", headers=vanhanh_h)

    # vanhanh (không phải admin) không hoàn tác được sau khi đã duyệt.
    u1 = client.post(f"/api/warehouse/sang-ngang/{req['request_id']}/undo", headers=vanhanh_h)
    assert u1.status_code == 403, u1.text

    u2 = client.post(f"/api/warehouse/sang-ngang/{req['request_id']}/undo", headers=admin_h)
    assert u2.status_code == 200, u2.text
    assert u2.json()["status"] == "pending"

    lots = client.get("/api/lots", headers=admin_h).json()
    lot = next(l for l in lots if l["lot_code"] == "SNG-LOT-05")
    assert lot["location"] == "Kho công ty"
    assert lot["quantity"] == 40


def test_qc_required_material_blocks_approve_until_kcs_release(client, admin_h, thukho_h, vanhanh_h, kcs_h):
    mat_id = _create_material(client, admin_h, "SNG-QC-01")
    p = client.post("/api/qc/parameters", headers=admin_h,
                    json={"code": "SNG_QC_PARAM", "name": "Độ ẩm", "unit": "%", "lsl": 3, "usl": 6})
    assert p.status_code == 201, p.text
    param_id = p.json()["param_id"]
    g = client.post("/api/qc/groups", headers=admin_h,
                    json={"code": "SNG-GRP-01", "name": "Chỉ tiêu sang ngang test"})
    assert g.status_code == 201, g.text
    group_id = g.json()["group_id"]
    it = client.post(f"/api/qc/groups/{group_id}/items", headers=admin_h,
                     json={"param_id": param_id, "mandatory": True})
    assert it.status_code == 201, it.text
    link = client.post(f"/api/materials/{mat_id}/qc-groups", headers=admin_h,
                       json={"group_id": group_id, "mandatory": True})
    assert link.status_code == 201, link.text

    r = client.post("/api/warehouse/sang-ngang", headers=thukho_h,
                    json={"lot_code": "SNG-LOT-QC-01", "material_id": mat_id, "quantity": 60, "uom": "kg"})
    assert r.status_code == 201, r.text
    req = r.json()
    lots = client.get("/api/lots", headers=admin_h).json()
    lot = next(l for l in lots if l["lot_id"] == req["lot_id"])
    assert lot["status"] == "on_hold"

    # Phân xưởng chưa duyệt được vì lô đang chờ KCS.
    blocked = client.post(f"/api/warehouse/sang-ngang/{req['request_id']}/approve", headers=vanhanh_h)
    assert blocked.status_code == 409, blocked.text
    assert "KCS" in blocked.json()["detail"]

    # KCS khai báo + duyệt (release) chỉ tiêu (dùng thukho để ghi kết quả — scope_qc="*" — mirror
    # test_material_qc.py: kcs chỉ được phân scope_qc cho vài param cụ thể, không phải param test).
    rec = client.post("/api/quality/results", headers=thukho_h,
                      json={"scope_type": "lot", "scope_id": lot["lot_id"], "parameter": "SNG_QC_PARAM",
                            "value": 4.5, "lower_limit": 3, "upper_limit": 6})
    assert rec.status_code == 201, rec.text
    rel = client.post("/api/quality/hold", headers=kcs_h,
                      json={"scope_type": "lot", "scope_id": lot["lot_id"], "on_hold": False})
    assert rel.status_code == 200, rel.text

    ap = client.post(f"/api/warehouse/sang-ngang/{req['request_id']}/approve", headers=vanhanh_h)
    assert ap.status_code == 200, ap.text
    assert ap.json()["status"] == "approved"
