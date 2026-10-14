"""Test "Người sửa/ngày giờ sửa" cho Chỉ tiêu trong nhóm (QCParameterGroupItem) — yêu cầu
người dùng 2026-10-14: màn "Chỉ tiêu trong nhóm" không hiện ai vừa sửa Min/Max, phải tra
audit_log thủ công mới biết (phát hiện lúc điều tra lô lọc 1420). Xem
services/qc_catalog.py::update_item.
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


def test_group_item_updated_by_at_null_until_first_edit_then_stamped(client, admin_h):
    param = client.post("/api/qc/parameters", headers=admin_h,
                        json={"code": "CT_AUDITITEM01", "name": "Chỉ tiêu audit item", "lsl": 1, "usl": 10})
    assert param.status_code == 201, param.text
    param_id = param.json()["param_id"]
    group = client.post("/api/qc/groups", headers=admin_h,
                       json={"code": "GRP_AUDITITEM01", "name": "Nhóm audit item"})
    assert group.status_code == 201, group.text
    group_id = group.json()["group_id"]

    created = client.post(f"/api/qc/groups/{group_id}/items", headers=admin_h,
                          json={"param_id": param_id, "mandatory": True})
    assert created.status_code == 201, created.text
    item_id = created.json()["item_id"]
    assert created.json()["updated_by"] is None
    assert created.json()["updated_at"] is None

    items = client.get(f"/api/qc/groups/{group_id}/items", headers=admin_h).json()
    row = next(i for i in items if i["item_id"] == item_id)
    assert row["updated_by"] is None

    updated = client.put(f"/api/qc/groups/{group_id}/items/{item_id}", headers=admin_h,
                         json={"param_id": param_id, "mandatory": True,
                              "lsl_override": 4.4, "usl_override": 4.6})
    assert updated.status_code == 200, updated.text
    assert updated.json()["updated_by"] == "admin"
    assert updated.json()["updated_at"] is not None

    items_after = client.get(f"/api/qc/groups/{group_id}/items", headers=admin_h).json()
    row_after = next(i for i in items_after if i["item_id"] == item_id)
    assert row_after["updated_by"] == "admin"
    assert row_after["lsl_override"] == 4.4 and row_after["usl_override"] == 4.6
