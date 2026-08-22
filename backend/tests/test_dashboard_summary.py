"""Test GET /api/reports/dashboard-summary đếm "Lệnh nấu" theo Lệnh sản xuất (BrewOrder) —
sau khi bỏ lớp "lệnh nấu lớn" (BrewMasterOrder), mỗi BrewOrder đứng phẳng, đếm thẳng 1:1 với
số lệnh người dùng thực sự tạo ra (services/dashboard.py::production_summary)."""

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


def test_dashboard_counts_brew_orders(client, admin_h):
    before = client.get("/api/reports/dashboard-summary", headers=admin_h).json()

    created1 = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": "LN-DASH-TEST-1", "auto_from_bom": False, "planned_volume_hl": 100.0})
    assert created1.status_code == 201, created1.text
    created2 = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": "LN-DASH-TEST-2", "auto_from_bom": False, "planned_volume_hl": 100.0})
    assert created2.status_code == 201, created2.text

    after = client.get("/api/reports/dashboard-summary", headers=admin_h).json()
    assert after["lenh_nau"]["total"] == before["lenh_nau"]["total"] + 2
