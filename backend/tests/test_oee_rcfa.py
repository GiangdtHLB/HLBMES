"""RCFA (Root Cause Failure Analysis) + 5 Whys — CRUD, tự sinh rcfa_no, recheck W+1..W+12."""

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
def quandoc_h(client):
    return _login(client, "quandoc", "123456")   # supervisor


@pytest.fixture(scope="module")
def kcs_h(client):
    return _login(client, "kcs", "123456")   # role=qa, không thuộc operator/supervisor/engineer


def test_create_requires_valid_role(client, quandoc_h, kcs_h):
    payload = {"line_code": "CAN30K", "machine": "Chiết", "part": "Vòi chiết số 3",
              "duration_min": 90, "description": "Thay nấm đẳng áp vòi chiết số 3"}
    denied = client.post("/api/rcfa", headers=kcs_h, json=payload)
    assert denied.status_code == 403, denied.text

    created = client.post("/api/rcfa", headers=quandoc_h, json=payload)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["rcfa_no"].startswith("RCFA-")


def test_rcfa_no_sequential(client, quandoc_h):
    payload = {"line_code": "CAN30K", "machine": "Đóng thùng", "duration_min": 40}
    r1 = client.post("/api/rcfa", headers=quandoc_h, json=payload).json()
    r2 = client.post("/api/rcfa", headers=quandoc_h, json=payload).json()
    assert r1["rcfa_no"] != r2["rcfa_no"]


def test_get_update_and_recheck(client, quandoc_h):
    created = client.post("/api/rcfa", headers=quandoc_h,
                          json={"line_code": "CAN30K", "machine": "Hầm TT", "duration_min": 30,
                                "five_whys": [{"level": 1, "text": "Lỗi feedback safety relay",
                                              "category": "hong_dot_ngot"}]})
    rcfa_id = created.json()["rcfa_id"]

    got = client.get(f"/api/rcfa/{rcfa_id}", headers=quandoc_h).json()
    assert got["machine"] == "Hầm TT"
    assert len(got["five_whys"]) == 1
    assert len(got["recheck_schedule"]) == 12
    assert all(w["checked"] is False for w in got["recheck_schedule"])

    upd = client.put(f"/api/rcfa/{rcfa_id}", headers=quandoc_h,
                     json={"line_code": "CAN30K", "machine": "Hầm TT", "duration_min": 30,
                           "corrective_action": "Khởi động lại PLC B&R", "checker": "quandoc"})
    assert upd.status_code == 200, upd.text

    recheck = client.put(f"/api/rcfa/{rcfa_id}/recheck", headers=quandoc_h,
                         json={"week_offset": 1, "checked": True, "note": "Không tái diễn"})
    assert recheck.status_code == 200, recheck.text
    w1 = next(w for w in recheck.json()["recheck_schedule"] if w["week_offset"] == 1)
    assert w1["checked"] is True
    assert w1["note"] == "Không tái diễn"

    bad_week = client.put(f"/api/rcfa/{rcfa_id}/recheck", headers=quandoc_h,
                          json={"week_offset": 99, "checked": True})
    assert bad_week.status_code == 409, bad_week.text


def test_list_filters_by_line(client, quandoc_h):
    client.post("/api/rcfa", headers=quandoc_h, json={"line_code": "OTHER-LINE", "machine": "X"})
    rows = client.get("/api/rcfa", params={"line_code": "CAN30K"}, headers=quandoc_h).json()
    assert all(r["line_code"] == "CAN30K" for r in rows)
    assert len(rows) >= 3
