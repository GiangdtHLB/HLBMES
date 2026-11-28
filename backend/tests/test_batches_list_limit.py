"""Test tham số `limit` (tuỳ chọn) của GET /api/batches — services/routers/batches.py::list_batches.

Dashboard "Mẻ gần đây" trước đây tải NGUYÊN TOÀN BỘ lịch sử mẻ nấu (hàng nghìn dòng tích lũy)
chỉ để cắt còn 8 dòng ở client — thêm `limit` để Dashboard xin đúng số dòng cần, không tải thừa
(yêu cầu người dùng 2026-11-28: khảo sát hiệu năng dashboard). Không truyền `limit` vẫn giữ
nguyên hành vi cũ (mọi nơi khác cần danh sách đầy đủ để tự tìm/lọc phía client)."""

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


def _make_batch(client, admin_h):
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(v for v in vers if v["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                         "planned_qty": 1000, "allow_shortage": True})   # batch_code: tu sinh
    assert b.status_code == 201, b.text
    return b.json()["batch_id"]


def test_limit_returns_the_n_most_recent_matching_unlimited_order(client, admin_h):
    # Du lieu seed co the chi co 1-2 me demo -- tu tao them cho chac chan co du >=3 me.
    for _ in range(3):
        _make_batch(client, admin_h)

    full = client.get("/api/batches", headers=admin_h).json()
    assert len(full) >= 3

    limited = client.get("/api/batches?limit=3", headers=admin_h).json()
    assert len(limited) == 3
    assert [b["batch_id"] for b in limited] == [b["batch_id"] for b in full[:3]]


def test_no_limit_param_keeps_full_list(client, admin_h):
    full = client.get("/api/batches", headers=admin_h).json()
    no_limit = client.get("/api/batches?limit=0", headers=admin_h).json()
    assert len(no_limit) == len(full)   # limit=0 (falsy) -> bo qua, giu nguyen hanh vi cu


def test_limit_larger_than_total_returns_everything(client, admin_h):
    full = client.get("/api/batches", headers=admin_h).json()
    over = client.get(f"/api/batches?limit={len(full) + 1000}", headers=admin_h).json()
    assert len(over) == len(full)
