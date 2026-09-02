"""Test 2 gate mới cho BatchExecution (2026-08-31, theo yêu cầu người dùng):

1. Chỉ cho ghi actual (tham số quy trình, POST .../actuals) khi mẻ đang RUNNING — trước đây còn
   cho phép cả HELD, nay chỉ running (xem services/batches.py::record_actual).
2. Chặn chuyển mẻ sang "completed" (transition) nếu CHƯA nhập đủ thời gian bắt đầu, thời gian kết
   thúc, và SL thực tế — trước đây transition() tự động set end_at=utcnow() nên không có gate nào
   cả (xem services/batches.py::transition). Root cause của gate này: 1 mẻ nấu còn "planned"
   (chưa nấu xong, chưa có actual_qty) đã lỡ bị gộp vào tank lên men, khiến on_hand tank cộng
   nhầm SL kế hoạch của mẻ đó vào như thể là dịch thật đã có — ép người dùng phải nhập actual_qty/
   start_at/end_at trước khi "hoàn thành" giúp đảm bảo dữ liệu này luôn có khi mẻ được coi là xong.
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


def _make_batch(client, admin_h, batch_code):
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(v for v in vers if v["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                          "batch_code": batch_code, "planned_qty": 1000, "allow_shortage": True})
    assert b.status_code == 201, b.text
    return b.json()["batch_id"]


def test_complete_blocked_until_start_end_actual_all_set(client, admin_h):
    batch_id = _make_batch(client, admin_h, "1")
    client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "ready"})
    client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "running"})
    # start_at đã tự set lúc running -> chỉ còn thiếu end_at + actual_qty.
    r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "completed"})
    assert r.status_code == 409, r.text
    assert "thời gian kết thúc" in r.json()["detail"] and "SL thực tế" in r.json()["detail"]

    aq = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": 950})
    assert aq.status_code == 200, aq.text
    # còn thiếu end_at.
    r2 = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "completed"})
    assert r2.status_code == 409, r2.text
    assert "thời gian kết thúc" in r2.json()["detail"] and "SL thực tế" not in r2.json()["detail"]

    fin = client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={})
    assert fin.status_code == 200, fin.text
    r3 = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "completed"})
    assert r3.status_code == 200, r3.text
    assert r3.json()["state"] == "completed"


def test_record_actual_blocked_when_planned_or_held(client, admin_h):
    batch_id = _make_batch(client, admin_h, "2")
    blocked_planned = client.post(f"/api/batches/{batch_id}/actuals", headers=admin_h,
                                  json={"name": "Nhiệt độ", "actual": 20})
    assert blocked_planned.status_code == 409, blocked_planned.text

    client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "ready"})
    client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "running"})
    ok_running = client.post(f"/api/batches/{batch_id}/actuals", headers=admin_h,
                             json={"name": "Nhiệt độ", "actual": 20})
    assert ok_running.status_code == 200, ok_running.text

    client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "held"})
    blocked_held = client.post(f"/api/batches/{batch_id}/actuals", headers=admin_h,
                               json={"name": "Nhiệt độ", "actual": 21})
    assert blocked_held.status_code == 409, blocked_held.text
