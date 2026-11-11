"""BC hieu suat he loc theo thang (filter_line_utilization_report) - yeu cau nguoi dung
2026-11-11: "Tao cho toi 1 bao cao o modul he loc nhu tinh o tren, co thoi gian khong loc va
thoi gian loc, %, so gio, so lit dich/thang, cho chon theo thang". Xem
services/dashboard.py::filter_line_utilization_report."""

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


def _build_filter_lot_with_batch(client, admin_h, suffix, started_at, ended_at, dich_nha_hl):
    """Mirror test_filter_production_report_duration_efficiency.py::_build_filter_lot_with_batch."""
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(x for x in vers if x["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                          "planned_qty": 1000, "allow_shortage": True})
    assert b.status_code == 201, b.text
    batch_id = b.json()["batch_id"]
    for target in ("ready", "running"):
        r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": target})
        assert r.status_code == 200, r.text
    aq = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": 1000})
    assert aq.status_code == 200, aq.text
    fin = client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={})
    assert fin.status_code == 200, fin.text
    r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "completed"})
    assert r.status_code == 200, r.text
    tank = client.post("/api/batch-tanks", headers=admin_h,
                       json={"batch_ids": [batch_id], "tank_code": f"TANK-FLUR-{suffix}"})
    assert tank.status_code == 201, tank.text
    bbt = client.post("/api/lines", headers=admin_h,
                      json={"code": f"BBT-FLUR-{suffix}", "name": f"BBT {suffix}", "kind": "tank_bbt"})
    assert bbt.status_code == 201, bbt.text
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": f"FLOT-FLUR-{suffix}", "to_bbt": bbt.json()["code"],
        "sources": [{"source_type": "tank", "source_tank_id": tank.json()["tank_id"]}],
        "category": "Bia lon"})
    assert draw.status_code == 201, draw.text
    filter_lot_id = draw.json()["filter_lot_id"]

    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    assert len(batches) == 1, batches
    batch_link_id = batches[0]["batch_link_id"]
    sources = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()
    assert len(sources) == 1, sources
    source_link_id = sources[0]["link_id"]

    r = client.put(f"/api/batch-filter-lots/batches/{batch_link_id}/finish", headers=admin_h, json={
        "draws": [{"source_link_id": source_link_id, "dich_nha_hl": dich_nha_hl}],
        "nuoc_bai_khi_hl": 0, "batch_seq_no": f"FLUR-{suffix}",
        "started_at": started_at, "ended_at": ended_at})
    assert r.status_code == 200, r.text
    return filter_lot_id


def test_monthly_running_idle_hours_and_liters(client, admin_h):
    # Thang 2030-06 co 30 ngay -> 720 gio lich.
    # Me A: 4h chay (10/6 01:00 -> 05:00), 50 hl = 5000 lit.
    _build_filter_lot_with_batch(client, admin_h, "A",
                                 started_at="2030-06-10T01:00:00Z", ended_at="2030-06-10T05:00:00Z",
                                 dich_nha_hl=50)
    # Me B: 6.5h chay (15/6 01:00 -> 07:30), 80 hl = 8000 lit.
    _build_filter_lot_with_batch(client, admin_h, "B",
                                 started_at="2030-06-15T01:00:00Z", ended_at="2030-06-15T07:30:00Z",
                                 dich_nha_hl=80)
    # Me C thang khac (7/2030) -> KHONG duoc tinh vao thang 6.
    _build_filter_lot_with_batch(client, admin_h, "C",
                                 started_at="2030-07-05T01:00:00Z", ended_at="2030-07-05T09:00:00Z",
                                 dich_nha_hl=999)

    rep = client.get("/api/reports/filter-line-utilization",
                     params={"year": 2030, "month": 6}, headers=admin_h).json()
    assert rep["year"] == 2030 and rep["month"] == 6
    assert rep["days_in_month"] == 30
    assert rep["total_hours"] == 720.0
    assert rep["batch_count"] == 2
    assert rep["running_hours"] == 10.5
    assert rep["idle_hours"] == 709.5
    assert rep["total_liters"] == 13000.0
    assert rep["running_pct"] == round(10.5 / 720 * 100, 1)
    assert rep["idle_pct"] == round(100 - rep["running_pct"], 1)
    assert rep["batches_missing_duration"] == 0


def test_month_with_no_batches_is_all_idle(client, admin_h):
    rep = client.get("/api/reports/filter-line-utilization",
                     params={"year": 2029, "month": 11}, headers=admin_h).json()
    assert rep["batch_count"] == 0
    assert rep["running_hours"] == 0.0
    assert rep["total_liters"] == 0.0
    assert rep["running_pct"] == 0.0
    assert rep["idle_pct"] == 100.0
    assert rep["idle_hours"] == rep["total_hours"]
