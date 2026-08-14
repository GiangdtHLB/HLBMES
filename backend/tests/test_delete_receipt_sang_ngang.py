"""Regression: xóa 1 lượt nhập kho (nút "Xóa" per-row → DELETE /movements/{id} →
delete_receipt) khi lô đó có đề nghị "Xuất sang ngang" đang chờ duyệt (pending).

Lỗi trước đây (chỉ lộ trên MSSQL, SQLite bỏ qua FK): sang_ngang_request.lot_id trỏ tới
material_lot nhưng đề nghị pending CHƯA move stock nên _lot_used()=False → qua guard → DELETE
material_lot vỡ FK 547 → 500. delete_receipt phải dọn các đề nghị con (pending/rejected) trước
khi xóa lô cuối cùng."""

import os
import tempfile

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ.setdefault("MES_DATABASE_URL", f"sqlite:///{_TMP.name}")
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


def _material(client, admin_h, code):
    r = client.post("/api/materials", headers=admin_h,
                    json={"code": code, "name": f"Vật tư {code}", "uom": "kg", "category": "other"})
    assert r.status_code == 201, r.text
    return r.json()["material_id"]


def _receipt_movement_id(client, admin_h, lot_id):
    r = client.get("/api/warehouse/movements?movement_type=receipt", headers=admin_h)
    assert r.status_code == 200, r.text
    mv = next((m for m in r.json() if m.get("lot_id") == lot_id), None)
    assert mv is not None, f"không thấy movement receipt cho lô {lot_id}"
    return mv["movement_id"]


def test_delete_receipt_with_pending_sang_ngang(client, admin_h):
    mat_id = _material(client, admin_h, "DRSN01")
    # create_sang_ngang: receive() (tăng tồn công ty, StockMovement receipt) + đề nghị pending.
    r = client.post("/api/warehouse/sang-ngang", headers=admin_h,
                    json={"material_id": mat_id, "quantity": 500, "uom": "kg"})
    assert r.status_code == 201, r.text
    req = r.json()
    lot_id = req["lot_id"]
    req_id = req["request_id"]

    # Đề nghị pending đang tồn tại, lô chưa move → trước fix: xóa receipt sẽ 500 (FK 547).
    pend = client.get("/api/warehouse/sang-ngang?status=pending", headers=admin_h).json()
    assert any(x["request_id"] == req_id for x in pend)

    mv_id = _receipt_movement_id(client, admin_h, lot_id)
    res = client.delete(f"/api/warehouse/movements/{mv_id}", headers=admin_h)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["deleted"] is True and body["lot_deleted"] is True

    # Lô đã bị xóa (receipt duy nhất) và đề nghị con cũng biến mất — không còn bản ghi mồ côi.
    after = client.get("/api/warehouse/sang-ngang", headers=admin_h).json()
    assert not any(x["request_id"] == req_id for x in after)
    recs = client.get("/api/warehouse/movements?movement_type=receipt", headers=admin_h).json()
    assert not any(m.get("lot_id") == lot_id for m in recs)
