"""Test QCParameter.value_type (numeric|pass_fail) — cho phép khai báo 1 chỉ tiêu chỉ ghi
Đạt/Không đạt thay vì nhập số. Quy ước: value=1/lower=1/upper=1 là Đạt (pass), value=0/lower=1/
upper=1 là Không đạt (fail) — tái dùng nguyên vẹn hàm đánh giá numeric có sẵn (_evaluate),
không đổi logic đánh giá. Phủ: mặc định numeric, CRUD giữ đúng value_type, value_type xuất
hiện trong required list của GET /lots/{id}/qc-status, và luồng Đạt/Không đạt qua
POST /quality/results tính đúng status.
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


def _create_material(client, admin_h, code):
    r = client.post("/api/materials", headers=admin_h,
                    json={"code": code, "name": f"Vật tư {code}", "uom": "kg", "category": "other"})
    assert r.status_code == 201, r.text
    return r.json()["material_id"]


def test_parameter_defaults_to_numeric_value_type(client, admin_h):
    p = client.post("/api/qc/parameters", headers=admin_h,
                    json={"code": "VT_NUM_DEFAULT", "name": "Chỉ tiêu số mặc định"})
    assert p.status_code == 201, p.text
    assert p.json()["value_type"] == "numeric"


def test_parameter_create_and_edit_pass_fail_value_type(client, admin_h):
    p = client.post("/api/qc/parameters", headers=admin_h,
                    json={"code": "VT_PF01", "name": "Ngoại quan", "value_type": "pass_fail"})
    assert p.status_code == 201, p.text
    param_id = p.json()["param_id"]
    assert p.json()["value_type"] == "pass_fail"

    params = client.get("/api/qc/parameters", headers=admin_h).json()
    row = next(x for x in params if x["param_id"] == param_id)
    assert row["value_type"] == "pass_fail"

    upd = client.put(f"/api/qc/parameters/{param_id}", headers=admin_h,
                     json={"code": "VT_PF01", "name": "Ngoại quan", "value_type": "numeric", "active": True})
    assert upd.status_code == 200, upd.text
    assert upd.json()["value_type"] == "numeric"


def test_lot_qc_status_exposes_value_type_and_pass_fail_flow(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "QCT-PF-MAT")

    p = client.post("/api/qc/parameters", headers=admin_h,
                    json={"code": "VT_PF_FLOW", "name": "Đạt/Không đạt cảm quan", "value_type": "pass_fail"})
    assert p.status_code == 201, p.text
    param_id = p.json()["param_id"]

    g = client.post("/api/qc/groups", headers=admin_h,
                    json={"code": "GRP-PF-FLOW", "name": "Nhóm chỉ tiêu Đạt/Không đạt"})
    assert g.status_code == 201, g.text
    group_id = g.json()["group_id"]

    it = client.post(f"/api/qc/groups/{group_id}/items", headers=admin_h,
                     json={"param_id": param_id, "mandatory": True})
    assert it.status_code == 201, it.text

    link = client.post(f"/api/materials/{mat_id}/qc-groups", headers=admin_h,
                       json={"group_id": group_id, "mandatory": True})
    assert link.status_code == 201, link.text

    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "LOT-PF-FLOW-01", "material_id": mat_id, "quantity": 100, "uom": "kg"})
    assert rc.status_code == 200, rc.text
    assert rc.json()["status"] == "on_hold"
    lot_id = rc.json()["lot_id"]

    st = client.get(f"/api/lots/{lot_id}/qc-status", headers=thukho_h).json()
    req = next(r for r in st["required"] if r["code"] == "VT_PF_FLOW")
    assert req["value_type"] == "pass_fail"

    # Không đạt (value=0/lower=1/upper=1) -> fail, không đủ điều kiện release.
    fail_rec = client.post("/api/quality/results", headers=thukho_h,
                           json={"scope_type": "lot", "scope_id": lot_id, "parameter": "VT_PF_FLOW",
                                 "value": 0, "lower_limit": 1, "upper_limit": 1})
    assert fail_rec.status_code == 201, fail_rec.text
    assert fail_rec.json()["status"] == "fail"

    # Đạt (value=1/lower=1/upper=1) -> pass.
    pass_rec = client.post("/api/quality/results", headers=thukho_h,
                           json={"scope_type": "lot", "scope_id": lot_id, "parameter": "VT_PF_FLOW",
                                 "value": 1, "lower_limit": 1, "upper_limit": 1})
    assert pass_rec.status_code == 201, pass_rec.text
    assert pass_rec.json()["status"] == "pass"

    st2 = client.get(f"/api/lots/{lot_id}/qc-status", headers=thukho_h).json()
    assert st2["can_release"] is True
