"""Test báo cáo năng lượng theo khoảng ngày (GET /api/energy/report) — tổng theo nhóm,
chuỗi theo kỳ (ngày/tháng), phân theo khu vực cho biểu đồ tròn/bảng breakdown."""

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
def setup_data(client, admin_h):
    g = client.post("/api/energy/groups", headers=admin_h,
                    json={"code": "DIEN-TEST", "name": "Điện test", "unit": "kWh"})
    assert g.status_code == 201, g.text
    group_id = g.json()["group_id"]

    a1 = client.post("/api/energy/areas", headers=admin_h, json={"code": "KHU-A-TEST", "name": "Khu A test"})
    a2 = client.post("/api/energy/areas", headers=admin_h, json={"code": "KHU-B-TEST", "name": "Khu B test"})
    assert a1.status_code == 201 and a2.status_code == 201
    area1_id, area2_id = a1.json()["area_id"], a2.json()["area_id"]

    readings = [
        {"day": "2026-07-01", "group_id": group_id, "area_id": area1_id, "value": 100},
        {"day": "2026-07-01", "group_id": group_id, "area_id": area2_id, "value": 50},
        {"day": "2026-07-02", "group_id": group_id, "area_id": area1_id, "value": 120},
        {"day": "2026-07-02", "group_id": group_id, "area_id": area2_id, "value": 60},
    ]
    for r in readings:
        resp = client.post("/api/energy/readings", headers=admin_h, json=r)
        assert resp.status_code == 201, resp.text
    return {"group_id": group_id, "area1_id": area1_id, "area2_id": area2_id}


def test_report_totals_and_series_all_areas(client, admin_h, setup_data):
    resp = client.get("/api/energy/report", headers=admin_h,
                      params={"date_from": "2026-07-01", "date_to": "2026-07-02", "group_by": "day"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    gid = setup_data["group_id"]

    assert body["totals"][gid] == 330  # 100+50+120+60
    assert any(g["group_id"] == gid and g["code"] == "DIEN-TEST" for g in body["groups"])

    day_totals = {s["period"]: s["value"] for s in body["series"] if s["group_id"] == gid}
    assert day_totals["2026-07-01"] == 150
    assert day_totals["2026-07-02"] == 180

    by_area = {r["area_id"]: r["value"] for r in body["by_area"] if r["group_id"] == gid}
    assert by_area[setup_data["area1_id"]] == 220  # 100+120
    assert by_area[setup_data["area2_id"]] == 110  # 50+60

    area_names = {r["area_id"]: r["area_name"] for r in body["by_area"]}
    assert area_names[setup_data["area1_id"]] == "Khu A test"


def test_report_filtered_by_single_area(client, admin_h, setup_data):
    resp = client.get("/api/energy/report", headers=admin_h, params={
        "date_from": "2026-07-01", "date_to": "2026-07-02", "group_by": "day",
        "area_id": setup_data["area1_id"],
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    gid = setup_data["group_id"]
    assert body["totals"][gid] == 220  # chỉ khu A: 100+120
    # chỉ 1 khu -> by_area vẫn trả về nhưng chỉ có đúng khu đó
    assert {r["area_id"] for r in body["by_area"]} == {setup_data["area1_id"]}


def test_report_group_by_month(client, admin_h, setup_data):
    resp = client.get("/api/energy/report", headers=admin_h,
                      params={"date_from": "2026-07-01", "date_to": "2026-07-02", "group_by": "month"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    gid = setup_data["group_id"]
    month_rows = [s for s in body["series"] if s["group_id"] == gid]
    assert len(month_rows) == 1
    assert month_rows[0]["period"] == "2026-07"
    assert month_rows[0]["value"] == 330


def test_report_default_date_range_no_error(client, admin_h):
    resp = client.get("/api/energy/report", headers=admin_h)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "totals" in body and "series" in body and "by_area" in body
