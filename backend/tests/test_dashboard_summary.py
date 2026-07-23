"""Test GET /api/reports/dashboard-summary đếm "Lệnh nấu" theo LỆNH (BrewMasterOrder — cái
người dùng thực sự tạo ra ở Lệnh SX), không phải theo lệnh nhỏ (BrewOrder con) bên trong.
Bug thực tế: trước đây dashboard dùng brew_order_svc.list_orders() (danh sách lệnh nhỏ) cho
thẻ "Lệnh nấu", trong khi "Lệnh lọc" cùng màn hình đã đúng đếm theo master order — khiến 1
Lệnh nấu có 2 lệnh nhỏ hiện thành "2", không khớp số lệnh người dùng thực sự tạo ra.
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


def _child(planned_volume_hl=100.0):
    return {"product_id": None, "planned_batch_count": 1, "planned_volume_hl": planned_volume_hl,
            "volume_tolerance_hl": 0.0, "auto_from_bom": False, "lines": []}


def test_dashboard_counts_brew_master_orders_not_children(client, admin_h):
    before = client.get("/api/reports/dashboard-summary", headers=admin_h).json()

    created = client.post("/api/brewing/brew-master-orders", headers=admin_h,
                          json={"order_code": "LN-DASH-TEST", "children": [_child(), _child()]})
    assert created.status_code == 201, created.text

    after = client.get("/api/reports/dashboard-summary", headers=admin_h).json()
    # 1 lệnh nấu (master) mới, chứa 2 lệnh nhỏ -> "total" chỉ tăng 1, không phải 2.
    assert after["lenh_nau"]["total"] == before["lenh_nau"]["total"] + 1
