"""Test GET /api/quality/pending-stage-qc — panel "Công đoạn chờ khai báo chỉ tiêu chất
lượng" ở tab Chất lượng (mirror của Lô NVL chờ khai báo, nhưng gộp cả 4 công đoạn sản xuất:
mẻ nấu/lô lên men chính+phụ/mẻ lọc/mã chiết). Xem services/qc_catalog.py::list_pending_stage_declarations.
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
def vanhanh_h(client):
    return _login(client, "vanhanh", "123456")


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


def test_bottle_shows_pending_then_disappears_after_declare(client, admin_h, vanhanh_h):
    group_id, code = _make_group_with_param(client, admin_h, "PENDINGBTL")
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": "thanh_pham", "group_id": group_id, "mandatory": True})
    assert link.status_code == 201, link.text

    bottle_code = "CH-PENDING-01"
    b = client.post("/api/brewing/bottles", headers=vanhanh_h,
                    json={"bottle_code": bottle_code, "beer_type": "Bia test"})
    assert b.status_code == 201, b.text

    # bottle_code chỉ duy nhất TRONG 1 năm — scope_id thật (qc_catalog.bottle_scope_id) phải
    # kèm năm.
    scope_id = f"{b.json()['bottle_year']}-{bottle_code}__thanh_pham"
    pending = client.get("/api/quality/pending-stage-qc", headers=admin_h).json()
    row = next(p for p in pending if p["scope_type"] == "bottle" and p["scope_id"] == scope_id)
    assert row["stage"] == "thanh_pham"
    assert code in row["pending"]
    assert bottle_code in row["label"]

    rec = client.post("/api/brewing/qc-results", headers=vanhanh_h,
                      json={"stage": "thanh_pham", "scope_type": "bottle", "scope_id": scope_id,
                            "parameter": code, "value": 5, "lower_limit": 1, "upper_limit": 10})
    assert rec.status_code == 201, rec.text

    pending_after = client.get("/api/quality/pending-stage-qc", headers=admin_h).json()
    assert not any(p["scope_type"] == "bottle" and p["scope_id"] == scope_id for p in pending_after)

    client.delete(f"/api/qc/stage-groups/{link.json()['link_id']}", headers=admin_h)


def test_records_without_any_stage_group_are_never_pending(client, admin_h, vanhanh_h):
    """Mã chiết không có nhóm chỉ tiêu bắt buộc nào gán vào stage đó thì KHÔNG được liệt
    kê (required rỗng -> pending luôn rỗng) — tránh làm phiền panel với dữ liệu vô hạn."""
    bottle_code = "CH-NOGROUP-01"
    b = client.post("/api/brewing/bottles", headers=vanhanh_h,
                    json={"bottle_code": bottle_code, "beer_type": "Bia test"})
    assert b.status_code == 201, b.text
    scope_id = f"{bottle_code}__thanh_pham"

    pending = client.get("/api/quality/pending-stage-qc", headers=admin_h).json()
    assert not any(p["scope_type"] == "bottle" and p["scope_id"] == scope_id for p in pending)
