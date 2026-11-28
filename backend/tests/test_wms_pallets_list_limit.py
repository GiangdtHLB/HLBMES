"""Test tham số `limit` (mặc định 500) của GET /wms/pallets — services/wms.py::list_pallets.

Màn "Bao bì" (VIEWS.wms) gọi /wms/pallets KHÔNG lọc gì để hiện bảng tìm-kiếm-tại-chỗ — trước đây
kéo nguyên MỌI pallet từng tạo (sự cố thực tế 2026-11-28, khảo sát hiệu năng toàn app: 1,2MB,
6,6 giây, càng phình to theo thời gian tích lũy). Lọc theo `lot_code` (1 lô cụ thể) KHÔNG áp dụng
giới hạn này — 1 lô không bao giờ có hàng trăm pallet."""

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


def _build_pallet(client, admin_h, lot_code):
    r = client.post("/api/wms/pallets", headers=admin_h,
                    json={"product": "TEST-LIMIT", "lot_code": lot_code, "case_count": 1, "units_per_case": 24})
    assert r.status_code == 201, r.text
    return r.json()


def test_limit_caps_unfiltered_list_but_not_lot_code_filtered(client, admin_h):
    for i in range(4):
        _build_pallet(client, admin_h, f"LOTLIMIT-{i}")

    full = client.get("/api/wms/pallets", headers=admin_h).json()
    assert len(full) >= 4

    capped = client.get("/api/wms/pallets?limit=2", headers=admin_h).json()
    assert len(capped) == 2
    assert [p["pallet_id"] for p in capped] == [p["pallet_id"] for p in full[:2]]

    # loc theo lot_code: khong bi gioi han dau, du co truyen limit nho.
    by_lot = client.get("/api/wms/pallets?lot_code=LOTLIMIT-0&limit=0", headers=admin_h).json()
    assert len(by_lot) == 1 and by_lot[0]["lot_code"] == "LOTLIMIT-0"


def test_default_limit_500_still_returns_everything_when_fewer_exist(client, admin_h):
    full = client.get("/api/wms/pallets", headers=admin_h).json()
    default = client.get("/api/wms/pallets?limit=500", headers=admin_h).json()
    assert len(default) == len(full)
