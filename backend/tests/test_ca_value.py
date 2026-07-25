"""Test giá trị CA (bao bì NCC) cho chỉ tiêu chất lượng NVL, phân biệt với giá trị nhà máy tự
đo:
1) MaterialGroup.is_raw_material CRUD (tạo/sửa) đúng như is_packaging.
2) lot_qc_status trả về is_raw_material=True khi vật tư thuộc nhóm được đánh dấu, False khi
   không (kể cả khi không gán nhóm nào).
3) POST /quality/results lưu ca_value tách biệt value, KHÔNG ảnh hưởng status (pass/fail vẫn
   chỉ tính theo value vs limit).
4) lot_qc_status.recorded[] trả về đúng ca_value đã lưu."""

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


def test_material_group_is_raw_material_crud(client, admin_h):
    r = client.post("/api/material-groups", headers=admin_h,
                    json={"code": "CAV-GROUP-A", "name": "Nguyên liệu chính test", "is_raw_material": True})
    assert r.status_code == 201, r.text
    assert r.json()["is_raw_material"] is True
    group_id = r.json()["group_id"]

    upd = client.put(f"/api/material-groups/{group_id}", headers=admin_h,
                     json={"code": "CAV-GROUP-A", "name": "Nguyên liệu chính test", "active": True,
                           "is_packaging": False, "is_raw_material": False})
    assert upd.status_code == 200, upd.text
    assert upd.json()["is_raw_material"] is False


def _setup_material_with_group(client, admin_h, mat_code, group_code, is_raw_material, param_code):
    g = client.post("/api/material-groups", headers=admin_h,
                    json={"code": group_code, "name": f"Nhóm {group_code}", "is_raw_material": is_raw_material})
    assert g.status_code == 201, g.text

    mat = client.post("/api/materials", headers=admin_h,
                      json={"code": mat_code, "name": f"Vật tư {mat_code}", "uom": "kg", "category": group_code})
    assert mat.status_code == 201, mat.text
    mat_id = mat.json()["material_id"]

    p = client.post("/api/qc/parameters", headers=admin_h,
                    json={"code": param_code, "name": "Độ ẩm", "unit": "%", "lsl": 2, "usl": 6})
    assert p.status_code == 201, p.text
    param_id = p.json()["param_id"]

    qcg = client.post("/api/qc/groups", headers=admin_h,
                      json={"code": f"GRP-{group_code}", "name": f"Chỉ tiêu {group_code}"})
    assert qcg.status_code == 201, qcg.text
    qc_group_id = qcg.json()["group_id"]

    it = client.post(f"/api/qc/groups/{qc_group_id}/items", headers=admin_h,
                     json={"param_id": param_id, "mandatory": True})
    assert it.status_code == 201, it.text

    link = client.post(f"/api/materials/{mat_id}/qc-groups", headers=admin_h,
                       json={"group_id": qc_group_id, "mandatory": True})
    assert link.status_code == 201, link.text
    return mat_id


def test_lot_qc_status_exposes_is_raw_material_flag(client, admin_h, thukho_h):
    mat_raw = _setup_material_with_group(client, admin_h, "CAV-NVL-RAW", "CAV-GROUP-RAW", True, "DO_AM_RAW")
    mat_other = _setup_material_with_group(client, admin_h, "CAV-NVL-OTHER", "CAV-GROUP-OTHER", False, "DO_AM_OTHER")

    rc1 = client.post("/api/warehouse/receive", headers=thukho_h,
                      json={"lot_code": "CAV-LOT-RAW-01", "material_id": mat_raw, "quantity": 100, "uom": "kg"})
    assert rc1.status_code == 200, rc1.text
    lot_raw = rc1.json()["lot_id"]

    rc2 = client.post("/api/warehouse/receive", headers=thukho_h,
                      json={"lot_code": "CAV-LOT-OTHER-01", "material_id": mat_other, "quantity": 100, "uom": "kg"})
    assert rc2.status_code == 200, rc2.text
    lot_other = rc2.json()["lot_id"]

    st_raw = client.get(f"/api/lots/{lot_raw}/qc-status", headers=admin_h).json()
    assert st_raw["is_raw_material"] is True

    st_other = client.get(f"/api/lots/{lot_other}/qc-status", headers=admin_h).json()
    assert st_other["is_raw_material"] is False


def test_record_result_persists_ca_value_without_affecting_status(client, admin_h, thukho_h):
    mat_id = _setup_material_with_group(client, admin_h, "CAV-NVL-PASS", "CAV-GROUP-PASS", True, "DO_AM_PASS")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "CAV-LOT-PASS-01", "material_id": mat_id, "quantity": 100, "uom": "kg"})
    assert rc.status_code == 200, rc.text
    lot_id = rc.json()["lot_id"]

    # value=4 nằm trong [2,6] -> PASS; ca_value=99 nằm NGOÀI khoảng nhưng chỉ tham khảo,
    # KHÔNG được dùng để tính status -> status vẫn phải là PASS.
    res = client.post("/api/quality/results", headers=admin_h,
                      json={"scope_type": "lot", "scope_id": lot_id, "parameter": "DO_AM_PASS",
                            "value": 4, "ca_value": 99, "lower_limit": 2, "upper_limit": 6})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["value"] == 4
    assert body["ca_value"] == 99
    assert body["status"] == "pass"

    st = client.get(f"/api/lots/{lot_id}/qc-status", headers=admin_h).json()
    rec = next(r for r in st["recorded"] if r["parameter"] == "DO_AM_PASS")
    assert rec["ca_value"] == 99
    assert rec["value"] == 4
    assert rec["status"] == "pass"
