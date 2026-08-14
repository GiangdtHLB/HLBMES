"""Regression (MSSQL FK): xóa vị trí cất Kho công ty khi lô từng ở đó đã RỖNG (quantity==0).

Guard delete_material_location chỉ chặn khi còn lô quantity != 0. Nhưng lô đã rỗng vẫn giữ
material_lot.location_id trỏ tới vị trí → FK fk_material_lot_location_id chặn DELETE trên MSSQL
(547), SQLite bỏ qua nên không lộ. Fix: NULL-out location_id của lô rỗng + flush trước khi xóa.
"""

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


def test_delete_location_after_lot_emptied(client, admin_h):
    mat_id = _material(client, admin_h, "DMLEL01")
    r = client.post("/api/warehouse/locations", headers=admin_h,
                    json={"code": "LOC-EMPTY-01", "name": "Vị trí rỗng test"})
    assert r.status_code in (200, 201), r.text
    loc = r.json()

    # Nhập lô vào đúng vị trí này.
    rc = client.post("/api/warehouse/receive", headers=admin_h,
                     json={"material_id": mat_id, "quantity": 30, "uom": "kg",
                           "location_id": loc["loc_id"]})
    assert rc.status_code == 200, rc.text
    lot_id = rc.json()["lot_id"]

    # Rút hết → lô rỗng (quantity==0) nhưng location_id VẪN trỏ tới vị trí.
    ri = client.post("/api/warehouse/issue", headers=admin_h,
                     json={"lot_id": lot_id, "quantity": 30, "mode": "tu_do", "reason": "drain"})
    assert ri.status_code == 200, ri.text

    # Trước fix: FK 547 → 500. Sau fix: gỡ location_id lô rỗng rồi xóa được.
    rd = client.delete(f"/api/warehouse/locations/{loc['loc_id']}", headers=admin_h)
    assert rd.status_code == 200, rd.text

    after = client.get("/api/warehouse/locations", headers=admin_h).json()
    assert not any(l["loc_id"] == loc["loc_id"] for l in after)
