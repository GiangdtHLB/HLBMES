"""Test mã lô (lot_code) tự sinh tăng dần theo năm + nhà cung cấp + số lô KCS.

Phủ: bỏ trống lot_code -> tự sinh "{year}-00001" tăng dần; vẫn cộng dồn đúng khi
nhập cùng vật tư + cùng mã lô thủ công; KHÔNG còn cộng nhầm vào lô của vật tư khác
dù trùng lot_code (bug thực tế đã sửa trong services/warehouse.py::receive) — xem
routers/warehouse.py::receive + models/materials.py::MaterialLot.lot_year.
"""

import os
import tempfile
from datetime import datetime, timedelta, timezone

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["MES_DATABASE_URL"] = f"sqlite:///{_TMP.name}"
os.environ["MES_DEV_HEADER_AUTH"] = "0"
os.environ["MES_RL_ENABLED"] = "0"
os.environ["MES_ADMIN_PASSWORD"] = "AdminTest123"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import seed as seed_mod

CUR_YEAR = datetime.utcnow().year


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


def _create_material(client, admin_h, code):
    r = client.post("/api/materials", headers=admin_h,
                    json={"code": code, "name": code, "uom": "kg", "category": "malt"})
    assert r.status_code == 201, r.text
    return r.json()["material_id"]


def test_receive_without_lot_code_auto_generates_sequential(client, admin_h, thukho_h):
    mat_a = _create_material(client, admin_h, "AUTO-A")
    mat_b = _create_material(client, admin_h, "AUTO-B")
    r1 = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"material_id": mat_a, "quantity": 100, "uom": "kg"})
    assert r1.status_code == 200, r1.text
    code1 = r1.json()["lot_code"]
    assert code1.startswith(f"{CUR_YEAR}-")
    r2 = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"material_id": mat_b, "quantity": 50, "uom": "kg"})
    code2 = r2.json()["lot_code"]
    assert code2.startswith(f"{CUR_YEAR}-")
    assert code2 != code1
    # Tăng dần: mã sau > mã trước (so sánh số thứ tự phần đuôi).
    seq1 = int(code1.split("-")[-1])
    seq2 = int(code2.split("-")[-1])
    assert seq2 == seq1 + 1


def test_receive_same_material_same_manual_lot_code_accumulates(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "ACCUM-A")
    r1 = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "MANUAL-ACCUM-01", "material_id": mat_id, "quantity": 100, "uom": "kg"})
    assert r1.status_code == 200, r1.text
    lot_id = r1.json()["lot_id"]
    r2 = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "MANUAL-ACCUM-01", "material_id": mat_id, "quantity": 50, "uom": "kg"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["lot_id"] == lot_id
    assert r2.json()["on_hand"] == 150


def test_receive_same_lot_code_different_material_is_rejected_not_merged(client, admin_h, thukho_h):
    """Bug thực tế: trước đây nhập trùng mã lô của MỘT vật tư KHÁC sẽ âm thầm cộng nhầm
    vào lô đó. Nay phải bị CHẶN rõ ràng (409) — mã lô là duy nhất toàn hệ thống trong năm,
    không phải cộng nhầm và cũng không được lặng lẽ tạo lô trùng mã."""
    mat_1 = _create_material(client, admin_h, "COLLIDE-001")
    mat_2 = _create_material(client, admin_h, "COLLIDE-002")
    r1 = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "001", "material_id": mat_1, "quantity": 100, "uom": "kg"})
    assert r1.status_code == 200, r1.text
    lot1_id = r1.json()["lot_id"]

    r2 = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "001", "material_id": mat_2, "quantity": 30, "uom": "kg"})
    assert r2.status_code == 409, r2.text

    # Lô đầu vẫn nguyên 100kg, không bị vật tư 2 cộng nhầm vào.
    lots = client.get("/api/lots", headers=admin_h).json()
    lot1 = next(l for l in lots if l["lot_id"] == lot1_id)
    assert lot1["quantity"] == 100
    assert lot1["material_id"] == mat_1


def test_supplier_crud_and_receive_with_supplier(client, admin_h, thukho_h):
    sp = client.post("/api/suppliers", headers=admin_h,
                     json={"code": "NCC-TEST-01", "name": "Nha cung cap test", "address": "HN", "contact": "0900000000"})
    assert sp.status_code == 201, sp.text
    supplier_id = sp.json()["supplier_id"]

    listed = client.get("/api/suppliers", headers=admin_h).json()
    assert any(s["supplier_id"] == supplier_id for s in listed)

    mat_id = _create_material(client, admin_h, "SUP-MAT")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"material_id": mat_id, "quantity": 20, "uom": "kg",
                           "supplier_id": supplier_id, "unit_price": 12.5})
    assert rc.status_code == 200, rc.text
    lot_id = rc.json()["lot_id"]
    lot = client.get("/api/lots", headers=admin_h).json()
    lot = next(l for l in lot if l["lot_id"] == lot_id)
    assert lot["supplier_id"] == supplier_id
    assert lot["unit_price"] == 12.5

    upd = client.put(f"/api/suppliers/{supplier_id}", headers=admin_h,
                     json={"code": "NCC-TEST-01", "name": "Nha cung cap test (sua)"})
    assert upd.status_code == 200, upd.text
    assert upd.json()["name"] == "Nha cung cap test (sua)"


def test_supplier_delete_blocked_when_used(client, admin_h, thukho_h):
    sp = client.post("/api/suppliers", headers=admin_h,
                     json={"code": "NCC-BLOCK", "name": "NCC blocked"})
    supplier_id = sp.json()["supplier_id"]
    mat_id = _create_material(client, admin_h, "SUP-BLOCK-MAT")
    client.post("/api/warehouse/receive", headers=thukho_h,
               json={"material_id": mat_id, "quantity": 10, "uom": "kg", "supplier_id": supplier_id})
    r = client.delete(f"/api/suppliers/{supplier_id}", headers=admin_h)
    assert r.status_code == 409, r.text


def test_kcs_lot_no_save_and_read(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "KCSLOT-MAT")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"material_id": mat_id, "quantity": 40, "uom": "kg"})
    lot_id = rc.json()["lot_id"]

    upd = client.put(f"/api/lots/{lot_id}", headers=thukho_h, json={"kcs_lot_no": "KCS-0007"})
    assert upd.status_code == 200, upd.text
    assert upd.json()["kcs_lot_no"] == "KCS-0007"

    st = client.get(f"/api/lots/{lot_id}/qc-status", headers=admin_h).json()
    assert st["kcs_lot_no"] == "KCS-0007"


def test_receive_received_at_future_rejected(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "RCDT-FUTURE")
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    r = client.post("/api/warehouse/receive", headers=thukho_h,
                    json={"material_id": mat_id, "quantity": 10, "uom": "kg", "received_at": future})
    assert r.status_code == 409, r.text


def test_receive_received_at_too_far_past_rejected(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "RCDT-TOOFARPAST")
    too_old = (datetime.now(timezone.utc) - timedelta(days=16)).isoformat()
    r = client.post("/api/warehouse/receive", headers=thukho_h,
                    json={"material_id": mat_id, "quantity": 10, "uom": "kg", "received_at": too_old})
    assert r.status_code == 409, r.text


def test_receive_received_at_within_15_days_accepted(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "RCDT-OK")
    within = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    r = client.post("/api/warehouse/receive", headers=thukho_h,
                    json={"material_id": mat_id, "quantity": 10, "uom": "kg", "received_at": within})
    assert r.status_code == 200, r.text
    lot_id = r.json()["lot_id"]
    lot = next(l for l in client.get("/api/lots", headers=admin_h).json() if l["lot_id"] == lot_id)
    got = datetime.fromisoformat(lot["created_at"])
    want = datetime.fromisoformat(within)
    assert abs((got - want).total_seconds()) < 2
