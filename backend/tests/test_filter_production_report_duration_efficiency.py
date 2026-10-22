"""BC he loc (filter_production_report) - yeu cau nguoi dung 2026-10-21: bo loc "Tu ngay - den
ngay" tuong minh, cot Ngay bat dau/Ngay ket thuc/Tong thoi gian loc/TB loc moi gio/% Hieu suat
(so voi 1 gia tri "100% hieu suat" chuan dat o Cai dat van hanh, OpsSetting.filter_batch_target_l).
Xem services/dashboard.py::filter_production_report/_batch_filter_lot_yield_items."""

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
    """Tao 1 lo loc moi (1 nguon = 1 tank len men) + ket thuc DUNG me loc con dau tien (tu dong
    mo san luc tao lo loc) voi started_at/ended_at/draws chi dinh - mirror _build_filter_lot o
    test_release_requires_all_fail_params_covered.py nhung don gian hoa (khong can beer_type/
    chi tieu QC, chi can du du lieu de filter_production_report tinh duoc)."""
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
                       json={"batch_ids": [batch_id], "tank_code": f"TANK-FPRDE-{suffix}"})
    assert tank.status_code == 201, tank.text
    bbt = client.post("/api/lines", headers=admin_h,
                      json={"code": f"BBT-FPRDE-{suffix}", "name": f"BBT {suffix}", "kind": "tank_bbt"})
    assert bbt.status_code == 201, bbt.text
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": f"FLOT-FPRDE-{suffix}", "to_bbt": bbt.json()["code"],
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
        "nuoc_bai_khi_hl": 0, "batch_seq_no": f"FPRDE-{suffix}",
        "started_at": started_at, "ended_at": ended_at})
    assert r.status_code == 200, r.text
    return filter_lot_id


def test_duration_avg_per_hour_and_efficiency_computed_from_target_setting(client, admin_h):
    # 100 hl dich = 10_000 lit, trong dung 5 gio (08:00 -> 13:00) -> TB 2_000 lit/gio.
    _build_filter_lot_with_batch(client, admin_h, "DUR1",
                                 started_at="2026-10-15T01:00:00Z", ended_at="2026-10-15T06:00:00Z",
                                 dich_nha_hl=100)

    s = client.get("/api/ops-settings", headers=admin_h).json()
    target_l = s["filter_batch_target_l"]
    try:
        rep = client.get("/api/reports/filter-production",
                         params={"date_from": "2026-10-15", "date_to": "2026-10-15"}, headers=admin_h).json()
        row = next(r for r in rep["items"] if r["filter_lot_code"] == "FLOT-FPRDE-DUR1")
        assert row["v_l"] == 10000
        assert row["duration_hours"] == 5
        assert row["avg_l_per_hour"] == 2000
        expected_pct = round(10000 / target_l * 100, 1)
        assert row["efficiency_pct"] == expected_pct

        # Doi nguong 100% hieu suat -> % phai doi theo dung cong thuc (khong hardcode gia tri cu).
        upd = client.put("/api/ops-settings", headers=admin_h, json={**s, "filter_batch_target_l": 20000})
        assert upd.status_code == 200, upd.text
        rep2 = client.get("/api/reports/filter-production",
                          params={"date_from": "2026-10-15", "date_to": "2026-10-15"}, headers=admin_h).json()
        row2 = next(r for r in rep2["items"] if r["filter_lot_code"] == "FLOT-FPRDE-DUR1")
        assert row2["efficiency_pct"] == 50.0
    finally:
        client.put("/api/ops-settings", headers=admin_h, json=s)


def test_date_range_filter_excludes_rows_outside_window(client, admin_h):
    _build_filter_lot_with_batch(client, admin_h, "DUR2",
                                 started_at="2026-01-05T01:00:00Z", ended_at="2026-01-05T03:00:00Z",
                                 dich_nha_hl=50)
    rep_in = client.get("/api/reports/filter-production",
                        params={"date_from": "2026-01-01", "date_to": "2026-01-10"}, headers=admin_h).json()
    assert any(r["filter_lot_code"] == "FLOT-FPRDE-DUR2" for r in rep_in["items"])

    rep_out = client.get("/api/reports/filter-production",
                         params={"date_from": "2026-02-01", "date_to": "2026-02-10"}, headers=admin_h).json()
    assert not any(r["filter_lot_code"] == "FLOT-FPRDE-DUR2" for r in rep_out["items"])
