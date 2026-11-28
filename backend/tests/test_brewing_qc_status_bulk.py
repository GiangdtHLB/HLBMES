"""Test GET /api/brewing/qc-status-bulk — routers/brewing.py::brewing_qc_status_bulk.

"Điều độ" trước đây gọi /qc-status RIÊNG cho TỪNG WorkOrder đang hiển thị (N+1 ở tầng frontend —
sự cố thực tế 2026-11-28, khảo sát hiệu năng toàn app: 122 WO -> 133 request cùng lúc, ~97 giây
xử lý dồn vào server). Endpoint bulk này PHẢI ra kết quả giống hệt gọi /qc-status riêng từng WO.
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


def _make_group_with_param(client, admin_h, suffix):
    p = client.post("/api/qc/parameters", headers=admin_h,
                    json={"code": f"CT_{suffix}", "name": f"Chỉ tiêu {suffix}", "lsl": 1, "usl": 10})
    assert p.status_code == 201, p.text
    param_id = p.json()["param_id"]
    g = client.post("/api/qc/groups", headers=admin_h,
                    json={"code": f"GRP_{suffix}", "name": f"Nhóm {suffix}"})
    assert g.status_code == 201, g.text
    group_id = g.json()["group_id"]
    it = client.post(f"/api/qc/groups/{group_id}/items", headers=admin_h,
                     json={"param_id": param_id, "mandatory": True})
    assert it.status_code == 201, it.text
    return group_id, f"CT_{suffix}"


def _make_wo(client, admin_h, brew_order_id):
    r = client.post("/api/workorders", headers=admin_h, json={"brew_order_id": brew_order_id})
    assert r.status_code == 201, r.text
    return r.json()["wo_id"]


def test_bulk_matches_single_call_per_wo_and_reflects_already_recorded(client, admin_h):
    group_id, code = _make_group_with_param(client, admin_h, "WOBULK01")
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": "nuoc_nau", "group_id": group_id, "mandatory": True})
    assert link.status_code == 201, link.text

    brew_order_id = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    wo1 = _make_wo(client, admin_h, brew_order_id)
    wo2 = _make_wo(client, admin_h, brew_order_id)

    # wo1 CHƯA khai -> pending; wo2 ĐÃ khai đủ -> không pending — đảm bảo bulk trả đúng RIÊNG cho
    # từng WO, không bị lẫn/ghi đè nhau qua cache dùng chung.
    rec = client.post("/api/brewing/qc-results", headers=admin_h,
                      json={"stage": "nuoc_nau", "scope_type": "work_order", "scope_id": wo2,
                           "parameter": code, "value": 5})
    assert rec.status_code == 201, rec.text

    single1 = client.get(f"/api/brewing/qc-status?stage=nuoc_nau&scope_type=work_order&scope_id={wo1}",
                        headers=admin_h).json()
    single2 = client.get(f"/api/brewing/qc-status?stage=nuoc_nau&scope_type=work_order&scope_id={wo2}",
                        headers=admin_h).json()
    assert single1["pending"] == [code]
    assert single2["pending"] == []

    bulk = client.get(f"/api/brewing/qc-status-bulk?stage=nuoc_nau&scope_type=work_order&scope_ids={wo1},{wo2}",
                      headers=admin_h).json()
    assert set(bulk.keys()) == {wo1, wo2}
    assert bulk[wo1] == single1
    assert bulk[wo2] == single2


def test_bulk_empty_scope_ids_returns_empty_dict(client, admin_h):
    r = client.get("/api/brewing/qc-status-bulk?stage=nuoc_nau&scope_type=work_order&scope_ids=",
                   headers=admin_h)
    assert r.status_code == 200, r.text
    assert r.json() == {}
