"""Test sửa trực tiếp giờ bắt đầu/kết thúc + SL thực tế của 1 Mẻ sản xuất (BatchExecution) —
services/batches.py::set_start_at/set_end_at/set_actual_qty. Trước đây start_at/end_at chỉ tự
set = utcnow() khi transition() (không sửa lại được), actual_qty chỉ tăng được qua produce_lot
(bắt buộc tạo hẳn 1 lô output + genealogy edge) — không có cách nhập/sửa trực tiếp đơn giản.
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
from app.common import utcnow


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


def test_set_start_and_finish_directly_and_can_correct(client, admin_h):
    batch_id = _make_batch(client, admin_h, "1")
    b = client.get(f"/api/batches/{batch_id}", headers=admin_h).json()
    assert b["start_at"] is None and b["end_at"] is None

    t1 = utcnow().isoformat()
    r = client.post(f"/api/batches/{batch_id}/start", headers=admin_h, json={"start_at": t1})
    assert r.status_code == 200, r.text
    assert r.json()["start_at"][:19] == t1[:19]

    t2 = (utcnow()).isoformat()
    r2 = client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={"end_at": t2})
    assert r2.status_code == 200, r2.text
    assert r2.json()["end_at"][:19] == t2[:19]

    # Gọi lại /start để SỬA giờ (bấm nhầm trước đó) -> vẫn cho phép, không chặn như transition().
    t3 = utcnow().isoformat()
    r3 = client.post(f"/api/batches/{batch_id}/start", headers=admin_h, json={"start_at": t3})
    assert r3.status_code == 200, r3.text
    assert r3.json()["start_at"][:19] == t3[:19]


def test_finish_without_end_at_defaults_to_now(client, admin_h):
    batch_id = _make_batch(client, admin_h, "2")
    r = client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={})
    assert r.status_code == 200, r.text
    assert r.json()["end_at"] is not None


def test_set_actual_qty_directly_and_correct(client, admin_h):
    batch_id = _make_batch(client, admin_h, "3")
    b = client.get(f"/api/batches/{batch_id}", headers=admin_h).json()
    assert b["actual_qty"] is None

    r = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": 950})
    assert r.status_code == 200, r.text
    assert r.json()["actual_qty"] == 950.0

    # Sửa lại (bấm nhầm) -> đè thẳng giá trị mới, không cộng dồn (khác produce_lot).
    r2 = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": 980})
    assert r2.status_code == 200, r2.text
    assert r2.json()["actual_qty"] == 980.0


def test_set_actual_qty_rejects_negative(client, admin_h):
    batch_id = _make_batch(client, admin_h, "4")
    r = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": -5})
    assert r.status_code == 409, r.text


def test_direct_edits_blocked_when_ebr_locked(client, admin_h):
    batch_id = _make_batch(client, admin_h, "5")
    sign = client.post(f"/api/batches/{batch_id}/ebr/sign", headers=admin_h,
                       json={"password": "AdminTest123", "meaning": "Xác nhận thực thi"})
    assert sign.status_code == 200, sign.text
    lock = client.post(f"/api/batches/{batch_id}/ebr/lock", headers=admin_h,
                       json={"password": "AdminTest123", "reason": "Phê duyệt release"})
    assert lock.status_code == 200, lock.text

    r = client.post(f"/api/batches/{batch_id}/start", headers=admin_h,
                    json={"start_at": utcnow().isoformat()})
    assert r.status_code == 409, r.text
    r2 = client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={})
    assert r2.status_code == 409, r2.text
    r3 = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": 100})
    assert r3.status_code == 409, r3.text
