"""Test: sửa Mã mẻ sau khi đã tạo (routers/brewing.py::update_brew_batch_code) — cùng ràng
buộc duy nhất trong năm như lúc tạo mẻ (add_brew_batch)."""

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
def brewhouse_line_id(client, admin_h):
    existing = client.get("/api/lines", headers=admin_h, params={"kind": "brewhouse"}).json()
    if existing:
        return existing[0]["line_id"]
    r = client.post("/api/lines", headers=admin_h,
                    json={"code": "BREW-CODEEDIT-01", "name": "Nhà nấu test", "kind": "brewhouse"})
    assert r.status_code == 201, r.text
    return r.json()["line_id"]


def _a_brew(client, admin_h, suffix):
    order = client.post("/api/brewing/orders", headers=admin_h,
                       json={"order_code": f"LN-{suffix}", "auto_from_bom": False, "planned_volume_hl": 100})
    assert order.status_code == 201, order.text
    b = client.post("/api/brewing/brews", headers=admin_h,
                   json={"brew_code": f"BR-{suffix}", "wort_type": "Dịch test",
                         "brew_order_id": order.json()["brew_order_id"]})
    assert b.status_code == 201, b.text
    return b.json()["brew_id"]


def _add_batch(client, admin_h, brew_id, code, started_at, line_id):
    r = client.post(f"/api/brewing/brews/{brew_id}/batches", headers=admin_h,
                    json={"batch_code": code, "started_at": started_at, "line_id": line_id})
    assert r.status_code == 201, r.text
    return r.json()["batch_id"]


def test_edit_batch_code_succeeds(client, admin_h, brewhouse_line_id):
    brew = _a_brew(client, admin_h, "CODEEDIT-A")
    b1 = _add_batch(client, admin_h, brew, "301", "2026-01-10T08:00:00", brewhouse_line_id)

    r = client.put(f"/api/brewing/brews/{brew}/batches/{b1}/code", headers=admin_h,
                   json={"batch_code": "302"})
    assert r.status_code == 200, r.text
    assert r.json()["batch_code"] == "302"


def test_edit_batch_code_duplicate_in_year_blocked(client, admin_h, brewhouse_line_id):
    brew = _a_brew(client, admin_h, "CODEEDIT-B")
    b1 = _add_batch(client, admin_h, brew, "303", "2026-01-10T08:00:00", brewhouse_line_id)
    _b2 = _add_batch(client, admin_h, brew, "304", "2026-01-10T09:00:00", brewhouse_line_id)

    blocked = client.put(f"/api/brewing/brews/{brew}/batches/{b1}/code", headers=admin_h,
                         json={"batch_code": "304"})
    assert blocked.status_code == 409, blocked.text


def test_edit_batch_code_rejects_non_positive_int(client, admin_h, brewhouse_line_id):
    brew = _a_brew(client, admin_h, "CODEEDIT-C")
    b1 = _add_batch(client, admin_h, brew, "305", "2026-01-10T08:00:00", brewhouse_line_id)

    bad = client.put(f"/api/brewing/brews/{brew}/batches/{b1}/code", headers=admin_h,
                     json={"batch_code": "abc"})
    assert bad.status_code == 422, bad.text


def test_edit_batch_line_and_note(client, admin_h, brewhouse_line_id):
    """Sửa Dây chuyền/Ghi chú (routers/brewing.py::update_brew_batch_details) — chọn nhầm
    dây chuyền lúc tạo mẻ thì sửa lại được, không cần xóa tạo lại mẻ."""
    other_line = client.post("/api/lines", headers=admin_h,
                             json={"code": "BREW-CODEEDIT-02", "name": "Nhà nấu test 2", "kind": "brewhouse"})
    assert other_line.status_code == 201, other_line.text
    other_line_id = other_line.json()["line_id"]

    brew = _a_brew(client, admin_h, "CODEEDIT-D")
    b1 = _add_batch(client, admin_h, brew, "306", "2026-01-10T08:00:00", brewhouse_line_id)

    r = client.put(f"/api/brewing/brews/{brew}/batches/{b1}", headers=admin_h,
                   json={"line_id": other_line_id, "note": "Ghi chú test"})
    assert r.status_code == 200, r.text
    assert r.json()["line_id"] == other_line_id
    assert r.json()["note"] == "Ghi chú test"

    rows = client.get(f"/api/brewing/brews/{brew}/batches", headers=admin_h).json()
    row = next(x for x in rows if x["batch_id"] == b1)
    assert row["line_id"] == other_line_id
    assert row["note"] == "Ghi chú test"


def test_edit_batch_line_rejects_non_brewhouse(client, admin_h, brewhouse_line_id):
    non_brewhouse = client.post("/api/lines", headers=admin_h,
                                json={"code": "LINE-CODEEDIT-01", "name": "Dây chuyền chiết test", "kind": "line"})
    assert non_brewhouse.status_code == 201, non_brewhouse.text

    brew = _a_brew(client, admin_h, "CODEEDIT-E")
    b1 = _add_batch(client, admin_h, brew, "307", "2026-01-10T08:00:00", brewhouse_line_id)

    bad = client.put(f"/api/brewing/brews/{brew}/batches/{b1}", headers=admin_h,
                     json={"line_id": non_brewhouse.json()["line_id"]})
    assert bad.status_code == 409, bad.text
