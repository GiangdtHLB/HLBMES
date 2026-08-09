"""Đếm dừng lắt nhắt theo tuần/ca (MS&SL) — upsert tally + weekly Pareto rank, tách biệt với
"Dừng lắt nhắt" residual ở waterfall (không đếm dòng target "Tổng dừng")."""

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
def vanhanh_h(client):
    return _login(client, "vanhanh", "123456")


@pytest.fixture(scope="module")
def reasons(client, vanhanh_h):
    rows = client.get("/api/downtime/reason-catalog",
                      params={"line_code": "CAN30K", "category": "dung_lat_nhat"}, headers=vanhanh_h).json()
    by_code = {r["sub_code"]: r["reason_id"] for r in rows}
    assert "tong_dung" in by_code   # dòng target — KHÔNG được xuất hiện trong Pareto MS&SL
    return by_code


def test_tong_dung_excluded_from_weekly_grid(client, vanhanh_h, reasons):
    grid = client.get("/api/downtime/minor-stop-tally",
                      params={"line_code": "CAN30K", "iso_year": 2026}, headers=vanhanh_h).json()
    sub_codes = {row["reason_id"] for row in grid["rows"]}
    assert reasons["tong_dung"] not in sub_codes
    assert len(grid["rows"]) == 14   # đúng 14 lý do lắt nhắt thật của MS&SL


def test_upsert_and_pareto_rank(client, vanhanh_h, reasons):
    ms1 = reasons["ms_1"]   # "Xe nâng không vào kệ vỏ lon kịp thời ở máy dỡ lon"
    ms2 = reasons["ms_2"]   # "Mắc lon, đổ lon trên băng tải máy dỡ lon"

    up1 = client.put("/api/downtime/minor-stop-tally", headers=vanhanh_h,
                     json={"reason_id": ms1, "iso_year": 2026, "iso_week": 10, "shift": "Ca1", "count": 5})
    assert up1.status_code == 200, up1.text
    client.put("/api/downtime/minor-stop-tally", headers=vanhanh_h,
              json={"reason_id": ms1, "iso_year": 2026, "iso_week": 11, "shift": "Ca1", "count": 3})
    client.put("/api/downtime/minor-stop-tally", headers=vanhanh_h,
              json={"reason_id": ms2, "iso_year": 2026, "iso_week": 10, "shift": "Ca2", "count": 2})

    pareto = client.get("/api/downtime/minor-stop-pareto",
                        params={"line_code": "CAN30K", "iso_year": 2026}, headers=vanhanh_h).json()
    assert pareto["total_count"] == 10
    assert pareto["items"][0]["count"] == 8   # ms1: 5+3, xếp hạng đầu
    assert pareto["items"][0]["cum_pct"] == 80.0
    assert pareto["items"][-1]["cum_pct"] == 100.0


def test_upsert_reason_must_be_minor_stop_category(client, vanhanh_h, reasons):
    ke_hoach = client.get("/api/downtime/reason-catalog",
                          params={"line_code": "CAN30K", "category": "ke_hoach"}, headers=vanhanh_h).json()[0]
    bad = client.put("/api/downtime/minor-stop-tally", headers=vanhanh_h,
                     json={"reason_id": ke_hoach["reason_id"], "iso_year": 2026, "iso_week": 1,
                           "shift": "Ca1", "count": 1})
    assert bad.status_code == 409, bad.text


def test_negative_count_rejected(client, vanhanh_h, reasons):
    bad = client.put("/api/downtime/minor-stop-tally", headers=vanhanh_h,
                     json={"reason_id": reasons["ms_3"], "iso_year": 2026, "iso_week": 1,
                           "shift": "Ca1", "count": -1})
    assert bad.status_code == 409, bad.text
