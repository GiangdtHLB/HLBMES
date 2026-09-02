"""Test Danh mục Dây chuyền sản xuất / Tank lên men / Tank thành phẩm — 3 mục tách từ
ProductionLine (kind=line|tank|tank_bbt|brewhouse), khai báo công suất+đơn vị (line) hoặc
thể tích+đơn vị (tank/tank_bbt)."""

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


def test_create_line_with_capacity(client, admin_h):
    r = client.post("/api/lines", headers=admin_h,
                    json={"code": "LINE-TEST01", "name": "Dây chuyền test", "kind": "line",
                          "area": "chiet", "ideal_rate_per_min": 200, "capacity_uom": "lon/phút"})
    assert r.status_code == 201, r.text
    lines = client.get("/api/lines?kind=line", headers=admin_h).json()
    row = next(l for l in lines if l["code"] == "LINE-TEST01")
    assert row["ideal_rate_per_min"] == 200
    assert row["capacity_uom"] == "lon/phút"


def test_create_tank_with_volume(client, admin_h):
    r = client.post("/api/lines", headers=admin_h,
                    json={"code": "FV-TEST01", "name": "Tank LM test", "kind": "tank",
                          "volume": 150, "volume_uom": "hl"})
    assert r.status_code == 201, r.text
    lines = client.get("/api/lines?kind=tank", headers=admin_h).json()
    row = next(l for l in lines if l["code"] == "FV-TEST01")
    assert row["volume"] == 150
    assert row["volume_uom"] == "hl"


def test_create_tank_bbt_with_volume(client, admin_h):
    r = client.post("/api/lines", headers=admin_h,
                    json={"code": "BBT-TEST01", "name": "Tank BBT test", "kind": "tank_bbt",
                          "volume": 200, "volume_uom": "hl"})
    assert r.status_code == 201, r.text
    lines = client.get("/api/lines?kind=tank_bbt", headers=admin_h).json()
    row = next(l for l in lines if l["code"] == "BBT-TEST01")
    assert row["volume"] == 200


def test_update_line(client, admin_h):
    lines = client.get("/api/lines?kind=line", headers=admin_h).json()
    line_id = next(l for l in lines if l["code"] == "LINE-TEST01")["line_id"]
    r = client.put(f"/api/lines/{line_id}", headers=admin_h,
                   json={"ideal_rate_per_min": 250, "capacity_uom": "chai/phút"})
    assert r.status_code == 200, r.text
    lines = client.get("/api/lines?kind=line", headers=admin_h).json()
    row = next(l for l in lines if l["line_id"] == line_id)
    assert row["ideal_rate_per_min"] == 250
    assert row["capacity_uom"] == "chai/phút"


def test_update_tank_volume(client, admin_h):
    lines = client.get("/api/lines?kind=tank", headers=admin_h).json()
    line_id = next(l for l in lines if l["code"] == "FV-TEST01")["line_id"]
    r = client.put(f"/api/lines/{line_id}", headers=admin_h, json={"volume": 180})
    assert r.status_code == 200, r.text
    lines = client.get("/api/lines?kind=tank", headers=admin_h).json()
    row = next(l for l in lines if l["line_id"] == line_id)
    assert row["volume"] == 180


def test_update_line_code(client, admin_h):
    lines = client.get("/api/lines?kind=line", headers=admin_h).json()
    line_id = next(l for l in lines if l["code"] == "LINE-TEST01")["line_id"]
    r = client.put(f"/api/lines/{line_id}", headers=admin_h, json={"code": "LINE-TEST01-RENAMED"})
    assert r.status_code == 200, r.text
    lines = client.get("/api/lines?kind=line", headers=admin_h).json()
    row = next(l for l in lines if l["line_id"] == line_id)
    assert row["code"] == "LINE-TEST01-RENAMED"


def test_update_line_code_blocked_when_duplicate(client, admin_h):
    lines = client.get("/api/lines?kind=tank", headers=admin_h).json()
    line_id = next(l for l in lines if l["code"] == "FV-TEST01")["line_id"]
    # "LINE-TEST01-RENAMED" đã có ở test trên (mã dùng chung 1 bảng ProductionLine cho cả
    # line/tank/tank_bbt) — đổi trùng phải bị chặn, không đổi mã cũ đi.
    r = client.put(f"/api/lines/{line_id}", headers=admin_h, json={"code": "LINE-TEST01-RENAMED"})
    assert r.status_code == 403, r.text
    lines = client.get("/api/lines?kind=tank", headers=admin_h).json()
    row = next(l for l in lines if l["line_id"] == line_id)
    assert row["code"] == "FV-TEST01"


def test_update_unknown_line_404(client, admin_h):
    r = client.put("/api/lines/does-not-exist", headers=admin_h, json={"volume": 1})
    assert r.status_code == 404, r.text
