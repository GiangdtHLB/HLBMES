"""Test xóa mẻ sản xuất (BatchExecution) — services/batches.py::delete_batch.

Trước đây mẻ sản xuất KHÔNG có cách nào xóa hẳn (chỉ chuyển trạng thái sang "cancelled"),
khác với mọi lớp khác trong hệ thống (BrewBatch cũ, BatchTank/BatchFilterLot/BatchPackLot mới)
đều có xóa kèm guard. Thêm delete_batch mirror delete_brew_batch: chặn khi đã khóa hồ sơ (EBR)
hoặc đã gộp vào tank lên men; hoàn tồn lô NVL đã tiêu thụ (consume/dispense/backflush đều tạo
genealogy edge lot->batch cùng cơ chế); chặn xóa nếu lô output đã sản xuất (produce_lot) bị
tiêu thụ tiếp ở nơi khác.
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


def test_delete_plain_batch_succeeds(client, admin_h):
    batch_id = _make_batch(client, admin_h, "1")
    r = client.delete(f"/api/batches/{batch_id}", headers=admin_h)
    assert r.status_code == 204, r.text
    assert client.get(f"/api/batches/{batch_id}", headers=admin_h).status_code == 404


def _run_batch_to_completed(client, admin_h, batch_id, actual_qty=None):
    for target in ("ready", "running"):
        r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": target})
        assert r.status_code == 200, r.text
    if actual_qty is None:
        actual_qty = client.get(f"/api/batches/{batch_id}", headers=admin_h).json()["planned_qty"]
    aq = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": actual_qty})
    assert aq.status_code == 200, aq.text
    fin = client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={})
    assert fin.status_code == 200, fin.text
    r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "completed"})
    assert r.status_code == 200, r.text
    return r.json()


def test_delete_blocked_when_merged_into_tank(client, admin_h):
    batch_id = _make_batch(client, admin_h, "2")
    _run_batch_to_completed(client, admin_h, batch_id)
    tank = client.post("/api/batch-tanks", headers=admin_h,
                       json={"batch_ids": [batch_id], "tank_code": "TANK-DEL-02"})
    assert tank.status_code == 201, tank.text
    r = client.delete(f"/api/batches/{batch_id}", headers=admin_h)
    assert r.status_code == 409, r.text
    assert client.get(f"/api/batches/{batch_id}", headers=admin_h).status_code == 200


def test_delete_blocked_when_ebr_locked(client, admin_h):
    batch_id = _make_batch(client, admin_h, "3")
    sign = client.post(f"/api/batches/{batch_id}/ebr/sign", headers=admin_h,
                       json={"password": "AdminTest123", "meaning": "Xác nhận thực thi"})
    assert sign.status_code == 200, sign.text
    lock = client.post(f"/api/batches/{batch_id}/ebr/lock", headers=admin_h,
                       json={"password": "AdminTest123", "reason": "Phê duyệt release"})
    assert lock.status_code == 200, lock.text
    r = client.delete(f"/api/batches/{batch_id}", headers=admin_h)
    assert r.status_code == 409, r.text


def test_delete_restores_consumed_lot_quantity(client, admin_h):
    batch_id = _make_batch(client, admin_h, "4")
    mat = client.post("/api/materials", headers=admin_h,
                      json={"code": "NVL-DEL-04", "name": "NVL xóa mẻ 04", "uom": "kg"})
    assert mat.status_code == 201, mat.text
    lot = client.post("/api/lots", headers=admin_h,
                      json={"lot_code": "LOT-DEL-04", "material_id": mat.json()["material_id"],
                            "quantity": 500, "uom": "kg", "location": "Kho phân xưởng"})
    assert lot.status_code == 201, lot.text
    lot_id = lot.json()["lot_id"]

    consume = client.post(f"/api/batches/{batch_id}/consume", headers=admin_h,
                          json={"lot_id": lot_id, "quantity": 120})
    assert consume.status_code == 200, consume.text
    remaining = next(l for l in client.get("/api/lots", headers=admin_h).json() if l["lot_id"] == lot_id)
    assert remaining["quantity"] == 380

    r = client.delete(f"/api/batches/{batch_id}", headers=admin_h)
    assert r.status_code == 204, r.text
    restored = next(l for l in client.get("/api/lots", headers=admin_h).json() if l["lot_id"] == lot_id)
    assert restored["quantity"] == 500
    assert restored["status"] == "available"


def test_delete_blocked_when_produced_lot_consumed_downstream(client, admin_h):
    batch_id = _make_batch(client, admin_h, "5")
    produce = client.post(f"/api/batches/{batch_id}/produce", headers=admin_h,
                          json={"lot_code": "LOT-DEL-05-OUT", "quantity": 200, "lot_type": "brew"})
    assert produce.status_code == 201, produce.text
    out_lot_id = produce.json()["lot_id"]
    release = client.post("/api/quality/hold", headers=admin_h,
                         json={"scope_type": "lot", "scope_id": out_lot_id, "on_hold": False})
    assert release.status_code == 200, release.text

    batch2_id = _make_batch(client, admin_h, "6")
    consume2 = client.post(f"/api/batches/{batch2_id}/consume", headers=admin_h,
                           json={"lot_id": out_lot_id, "quantity": 50})
    assert consume2.status_code == 200, consume2.text

    r = client.delete(f"/api/batches/{batch_id}", headers=admin_h)
    assert r.status_code == 409, r.text


def test_delete_removes_own_produced_lot_when_untouched(client, admin_h):
    batch_id = _make_batch(client, admin_h, "7")
    produce = client.post(f"/api/batches/{batch_id}/produce", headers=admin_h,
                          json={"lot_code": "LOT-DEL-06-OUT", "quantity": 200, "lot_type": "brew"})
    assert produce.status_code == 201, produce.text
    out_lot_id = produce.json()["lot_id"]

    r = client.delete(f"/api/batches/{batch_id}", headers=admin_h)
    assert r.status_code == 204, r.text
    lots = client.get("/api/lots", headers=admin_h).json()
    assert not any(l["lot_id"] == out_lot_id for l in lots)
