"""Smoke test end-to-end (pytest + FastAPI TestClient) trên SQLite tạm.

Chạy:  cd backend && pytest -q   (cần requirements-dev.txt)
"""

import os
import tempfile

# Đặt DB tạm TRƯỚC khi import app (engine khởi tạo lúc import).
_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["MES_DATABASE_URL"] = f"sqlite:///{_TMP.name}"
os.environ["MES_DEV_HEADER_AUTH"] = "0"
os.environ["MES_RL_ENABLED"] = "0"   # tắt rate-limit để test đăng nhập nhiều lần

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import seed as seed_mod


@pytest.fixture(scope="module", autouse=True)
def _seeded():
    seed_mod.seed()           # tạo bảng + dữ liệu mẫu
    yield


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert r.json()["db"]["ok"] is True


def test_login_and_me(client):
    h = _login(client, "admin", "admin123")
    me = client.get("/api/auth/me", headers=h).json()
    assert me["username"] == "admin" and me["role"] == "admin"


def test_auth_required_without_token(client):
    # Endpoint cần token → 403 khi không có (header fallback đã tắt)
    assert client.get("/api/auth/users").status_code == 403


def test_rbac_permission(client):
    h = _login(client, "vanhanh", "123456")            # operator, không có order.create
    r = client.post("/api/orders", headers=h,
                    json={"order_code": "PO-X", "product_id": "x", "planned_qty": 1})
    assert r.status_code == 403   # thiếu quyền order.create


def test_workorder_board(client):
    h = _login(client, "quandoc", "123456")
    board = client.get("/api/workorders", headers=h).json()
    assert isinstance(board, list) and len(board) >= 1


def test_audit_chain_intact(client):
    h = _login(client, "admin", "admin123")
    assert client.get("/api/audit/verify-chain", headers=h).json()["intact"] is True


def test_scan_and_historian(client):
    h = _login(client, "quandoc", "123456")
    s = client.get("/api/scan", params={"code": "B-2406-0001"}, headers=h).json()
    assert s["type"] == "batch"
    tags = client.get("/api/historian/tags", headers=h).json()
    assert len(tags) >= 1


def test_bom_availability(client):
    h = _login(client, "quandoc", "123456")
    rid = client.get("/api/recipes", headers=h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=h).json()
    vid = next(v["version_id"] for v in vers if v["state"] == "effective")
    av = client.get("/api/batches/availability",
                    params={"recipe_version_id": vid, "planned_qty": 50000}, headers=h).json()
    assert "shortage" in av and "rows" in av
