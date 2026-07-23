"""Test nút Xóa (guarded delete) cho 5 danh mục còn thiếu — Loại bia, Dịch bia, Vật tư, Sản
phẩm thành phẩm, Dây chuyền/Tank (xem services/master_data.py). Mỗi entity: xóa được khi chưa
dùng ở đâu; bị chặn (kèm thông báo liệt kê nơi đang dùng) khi đã có bản ghi tham chiếu tới; và
yêu cầu quyền master.manage."""

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


def _a_beer_type(client, admin_h, code):
    r = client.post("/api/beer-types", headers=admin_h, json={"code": code, "name": code})
    assert r.status_code == 201, r.text
    return r.json()["beer_type_id"]


def _a_product(client, admin_h, code, beer_type_id=None):
    r = client.post("/api/products", headers=admin_h,
                    json={"code": code, "name": code, "uom": "L", "beer_type_id": beer_type_id})
    assert r.status_code == 201, r.text
    return r.json()["product_id"]


def _a_material(client, admin_h, code):
    r = client.post("/api/materials", headers=admin_h,
                    json={"code": code, "name": code, "uom": "kg", "category": "other"})
    assert r.status_code == 201, r.text
    return r.json()["material_id"]


def _a_finished_product(client, admin_h, code, product_id=None):
    r = client.post("/api/finished-products", headers=admin_h,
                    json={"code": code, "name": code, "uom": "lon", "product_id": product_id})
    assert r.status_code == 201, r.text
    return r.json()["finished_product_id"]


def _a_line(client, admin_h, code, kind="line"):
    r = client.post("/api/lines", headers=admin_h,
                    json={"code": code, "name": code, "kind": kind})
    assert r.status_code == 201, r.text
    return r.json()["line_id"]


def _a_qc_group(client, admin_h, code):
    r = client.post("/api/qc/groups", headers=admin_h, json={"code": code, "name": code})
    assert r.status_code == 201, r.text
    return r.json()["group_id"]


# ---- Xóa được khi chưa dùng ở đâu ----

def test_delete_unused_beer_type(client, admin_h):
    bt_id = _a_beer_type(client, admin_h, "BT-DEL-01")
    r = client.delete(f"/api/beer-types/{bt_id}", headers=admin_h)
    assert r.status_code == 204, r.text


def test_delete_unused_product(client, admin_h):
    p_id = _a_product(client, admin_h, "PR-DEL-01")
    r = client.delete(f"/api/products/{p_id}", headers=admin_h)
    assert r.status_code == 204, r.text


def test_delete_unused_material(client, admin_h):
    m_id = _a_material(client, admin_h, "MT-DEL-01")
    r = client.delete(f"/api/materials/{m_id}", headers=admin_h)
    assert r.status_code == 204, r.text


def test_delete_unused_finished_product(client, admin_h):
    fp_id = _a_finished_product(client, admin_h, "FP-DEL-01")
    r = client.delete(f"/api/finished-products/{fp_id}", headers=admin_h)
    assert r.status_code == 204, r.text


def test_delete_unused_line(client, admin_h):
    line_id = _a_line(client, admin_h, "LN-DEL-01")
    r = client.delete(f"/api/lines/{line_id}", headers=admin_h)
    assert r.status_code == 204, r.text


# ---- Xóa bị chặn khi đang được tham chiếu ----

def test_delete_beer_type_blocked_by_product(client, admin_h):
    bt_id = _a_beer_type(client, admin_h, "BT-DEL-02")
    _a_product(client, admin_h, "PR-DEL-02", beer_type_id=bt_id)
    r = client.delete(f"/api/beer-types/{bt_id}", headers=admin_h)
    assert r.status_code == 409, r.text
    assert "dịch bia" in r.json()["detail"]


def test_delete_product_blocked_by_finished_product(client, admin_h):
    p_id = _a_product(client, admin_h, "PR-DEL-03")
    _a_finished_product(client, admin_h, "FP-DEL-02", product_id=p_id)
    r = client.delete(f"/api/products/{p_id}", headers=admin_h)
    assert r.status_code == 409, r.text
    assert "sản phẩm thành phẩm" in r.json()["detail"]


def test_delete_material_blocked_by_qc_group_link(client, admin_h):
    m_id = _a_material(client, admin_h, "MT-DEL-02")
    g_id = _a_qc_group(client, admin_h, "QG-DEL-01")
    link = client.post(f"/api/materials/{m_id}/qc-groups", headers=admin_h, json={"group_id": g_id})
    assert link.status_code == 201, link.text
    r = client.delete(f"/api/materials/{m_id}", headers=admin_h)
    assert r.status_code == 409, r.text
    assert "gán nhóm chỉ tiêu QC" in r.json()["detail"]


def test_delete_finished_product_blocked_by_stage_qc_group(client, admin_h):
    fp_id = _a_finished_product(client, admin_h, "FP-DEL-03")
    g_id = _a_qc_group(client, admin_h, "QG-DEL-02")
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": "thanh_pham", "group_id": g_id, "finished_product_id": fp_id})
    assert link.status_code == 201, link.text
    r = client.delete(f"/api/finished-products/{fp_id}", headers=admin_h)
    assert r.status_code == 409, r.text
    assert "nhóm chỉ tiêu công đoạn" in r.json()["detail"]


def test_delete_line_blocked_by_oee_record(client, admin_h):
    line_id = _a_line(client, admin_h, "LN-DEL-02")
    r = client.post("/api/oee", headers=admin_h,
                    json={"line": "LN-DEL-02", "planned_time_min": 480, "ideal_rate_per_min": 200})
    assert r.status_code == 201, r.text
    d = client.delete(f"/api/lines/{line_id}", headers=admin_h)
    assert d.status_code == 409, d.text
    assert "OEE" in d.json()["detail"]


# ---- Yêu cầu quyền master.manage ----

def test_delete_requires_master_manage_permission(client, admin_h, vanhanh_h):
    bt_id = _a_beer_type(client, admin_h, "BT-DEL-03")
    r = client.delete(f"/api/beer-types/{bt_id}", headers=vanhanh_h)
    assert r.status_code == 403, r.text
