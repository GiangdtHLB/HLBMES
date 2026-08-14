"""Test vị trí kho nguyên vật liệu (Kho công ty): danh mục CRUD, bắt buộc chọn vị trí lúc
nhập kho SAU KHI danh mục đã có dữ liệu, đổi vị trí lô đang tồn (relocate), và không ảnh hưởng
tới Kho phân xưởng (chưa có danh mục vị trí riêng)."""

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


def _create_material(client, admin_h, code):
    r = client.post("/api/materials", headers=admin_h,
                    json={"code": code, "name": f"Vật tư {code}", "uom": "kg", "category": "other"})
    assert r.status_code == 201, r.text
    return r.json()["material_id"]


def test_receive_unaffected_before_any_location_declared(client, admin_h, thukho_h):
    """Trước khi danh mục vị trí có bất kỳ vị trí nào, nhập kho vẫn hoạt động bình thường —
    tránh vấn đề con-gà-quả-trứng (không ai nhập kho được nếu bắt buộc ngay từ đầu)."""
    mat_id = _create_material(client, admin_h, "LOC-PRE-01")
    r = client.post("/api/warehouse/receive", headers=thukho_h,
                    json={"lot_code": "LOT-LOC-PRE-01", "material_id": mat_id, "quantity": 10, "uom": "kg"})
    assert r.status_code == 200, r.text
    assert "lot_id" in r.json()


def test_location_crud_and_guarded_delete(client, admin_h, thukho_h):
    r = client.post("/api/warehouse/locations", headers=admin_h,
                    json={"code": "A1-01", "name": "Kệ A1 tầng 1", "zone": "A"})
    assert r.status_code == 201, r.text
    loc = r.json()
    assert loc["code"] == "A1-01"

    r = client.get("/api/warehouse/locations", headers=thukho_h)
    assert r.status_code == 200
    assert any(l["loc_id"] == loc["loc_id"] for l in r.json())

    r = client.put(f"/api/warehouse/locations/{loc['loc_id']}", headers=admin_h,
                   json={"code": "A1-01", "name": "Kệ A1 tầng 1 (sửa)", "zone": "A", "active": True})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Kệ A1 tầng 1 (sửa)"

    # Gán 1 lô vào vị trí này rồi mới thử xóa — phải bị chặn vì đang chứa lô còn tồn.
    mat_id = _create_material(client, admin_h, "LOC-GUARD-01")
    r = client.post("/api/warehouse/receive", headers=thukho_h,
                    json={"lot_code": "LOT-LOC-GUARD-01", "material_id": mat_id, "quantity": 20,
                         "uom": "kg", "location_id": loc["loc_id"]})
    assert r.status_code == 200, r.text

    r = client.delete(f"/api/warehouse/locations/{loc['loc_id']}", headers=admin_h)
    assert r.status_code == 409, r.text

    r = client.post("/api/warehouse/locations", headers=admin_h,
                    json={"code": "A1-02", "name": "Kệ A1 tầng 2"})
    assert r.status_code == 201, r.text
    loc2 = r.json()
    r = client.delete(f"/api/warehouse/locations/{loc2['loc_id']}", headers=admin_h)
    assert r.status_code == 200, r.text


def test_receive_at_company_requires_location_once_catalog_populated(client, admin_h, thukho_h):
    """Danh mục vị trí đã có dữ liệu (từ test trước) — nhập vào Kho công ty giờ bắt buộc chọn
    vị trí; nhập vào Kho phân xưởng thì không (chưa có danh mục riêng cho phân xưởng)."""
    mat_id = _create_material(client, admin_h, "LOC-REQ-01")
    r = client.post("/api/warehouse/receive", headers=thukho_h,
                    json={"lot_code": "LOT-LOC-REQ-01", "material_id": mat_id, "quantity": 5, "uom": "kg"})
    assert r.status_code == 409, r.text

    r = client.post("/api/warehouse/receive", headers=admin_h,
                    json={"lot_code": "LOT-LOC-REQ-02", "material_id": mat_id, "quantity": 5,
                         "uom": "kg", "location": "Kho phân xưởng"})
    assert r.status_code == 200, r.text


def test_relocate_lot_moves_to_new_location(client, admin_h, thukho_h):
    r = client.post("/api/warehouse/locations", headers=admin_h,
                    json={"code": "B2-01", "name": "Kệ B2 tầng 1"})
    loc_from = r.json()
    r = client.post("/api/warehouse/locations", headers=admin_h,
                    json={"code": "B2-02", "name": "Kệ B2 tầng 2"})
    loc_to = r.json()

    mat_id = _create_material(client, admin_h, "LOC-RELOC-01")
    r = client.post("/api/warehouse/receive", headers=thukho_h,
                    json={"lot_code": "LOT-LOC-RELOC-01", "material_id": mat_id, "quantity": 15,
                         "uom": "kg", "location_id": loc_from["loc_id"]})
    lot_id = r.json()["lot_id"]

    r = client.post(f"/api/warehouse/lots/{lot_id}/relocate", headers=thukho_h,
                    json={"location_id": loc_to["loc_id"]})
    assert r.status_code == 200, r.text
    assert r.json()["location_id"] == loc_to["loc_id"]

    r = client.get("/api/lots", headers=thukho_h)
    lot = next(l for l in r.json() if l["lot_id"] == lot_id)
    assert lot["location_id"] == loc_to["loc_id"]


def test_relocate_blocked_for_workshop_lot(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "LOC-RELOC-PX-01")
    r = client.post("/api/warehouse/receive", headers=admin_h,
                    json={"lot_code": "LOT-LOC-RELOC-PX-01", "material_id": mat_id, "quantity": 8,
                         "uom": "kg", "location": "Kho phân xưởng"})
    assert r.status_code == 200, r.text
    lot_id = r.json()["lot_id"]

    r = client.post(f"/api/warehouse/locations", headers=admin_h,
                    json={"code": "C1-01", "name": "Kệ C1 tầng 1"})
    loc = r.json()

    r = client.post(f"/api/warehouse/lots/{lot_id}/relocate", headers=admin_h,
                    json={"location_id": loc["loc_id"]})
    assert r.status_code == 409, r.text
