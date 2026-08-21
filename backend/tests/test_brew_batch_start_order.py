"""Test: sửa giờ bắt đầu mẻ nấu (routers/brewing.py::update_brew_batch_start) — mẻ trước
không được bắt đầu sau mẻ sau, mẻ sau không được bắt đầu trước mẻ trước, so sánh theo `seq`
trong CÙNG 1 mã nấu (brew_id)."""

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
                    json={"code": "BREW-STARTORD-01", "name": "Nhà nấu test", "kind": "brewhouse"})
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


def _add_batch(client, admin_h, brew_id, code, seq, started_at, line_id):
    r = client.post(f"/api/brewing/brews/{brew_id}/batches", headers=admin_h,
                    json={"batch_code": code, "seq": seq, "started_at": started_at, "line_id": line_id})
    assert r.status_code == 201, r.text
    return r.json()["batch_id"]


def test_start_time_edit_within_order_succeeds(client, admin_h, brewhouse_line_id):
    brew = _a_brew(client, admin_h, "STARTORD-A")
    b1 = _add_batch(client, admin_h, brew, "201", 1, "2026-01-10T08:00:00", brewhouse_line_id)
    b2 = _add_batch(client, admin_h, brew, "202", 2, "2026-01-10T12:00:00", brewhouse_line_id)

    ok = client.post(f"/api/brewing/brews/{brew}/batches/{b1}/start", headers=admin_h,
                     json={"started_at": "2026-01-10T09:00:00"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["started_at"].startswith("2026-01-10T09:00:00")

    ok2 = client.post(f"/api/brewing/brews/{brew}/batches/{b2}/start", headers=admin_h,
                      json={"started_at": "2026-01-10T13:00:00"})
    assert ok2.status_code == 200, ok2.text


def test_earlier_batch_cannot_start_after_later_batch(client, admin_h, brewhouse_line_id):
    brew = _a_brew(client, admin_h, "STARTORD-B")
    b1 = _add_batch(client, admin_h, brew, "203", 1, "2026-01-11T08:00:00", brewhouse_line_id)
    _b2 = _add_batch(client, admin_h, brew, "204", 2, "2026-01-11T12:00:00", brewhouse_line_id)

    blocked = client.post(f"/api/brewing/brews/{brew}/batches/{b1}/start", headers=admin_h,
                          json={"started_at": "2026-01-11T13:00:00"})
    assert blocked.status_code == 409, blocked.text
    assert "mẻ sau" in blocked.text.lower() or "sau" in blocked.text.lower()


def test_later_batch_cannot_start_before_earlier_batch(client, admin_h, brewhouse_line_id):
    brew = _a_brew(client, admin_h, "STARTORD-C")
    _b1 = _add_batch(client, admin_h, brew, "205", 1, "2026-01-12T08:00:00", brewhouse_line_id)
    b2 = _add_batch(client, admin_h, brew, "206", 2, "2026-01-12T12:00:00", brewhouse_line_id)

    blocked = client.post(f"/api/brewing/brews/{brew}/batches/{b2}/start", headers=admin_h,
                          json={"started_at": "2026-01-12T07:00:00"})
    assert blocked.status_code == 409, blocked.text
    assert "mẻ trước" in blocked.text.lower() or "trước" in blocked.text.lower()


def test_batch_without_seq_skips_order_check(client, admin_h, brewhouse_line_id):
    """Mẻ không gán seq (dữ liệu cũ) — không so sánh được với ai, luôn cho sửa."""
    brew = _a_brew(client, admin_h, "STARTORD-D")
    r = client.post(f"/api/brewing/brews/{brew}/batches", headers=admin_h,
                    json={"batch_code": "207", "started_at": "2026-01-13T08:00:00", "line_id": brewhouse_line_id})
    assert r.status_code == 201, r.text
    b1 = r.json()["batch_id"]

    ok = client.post(f"/api/brewing/brews/{brew}/batches/{b1}/start", headers=admin_h,
                     json={"started_at": "2099-01-01T00:00:00"})
    assert ok.status_code == 200, ok.text
