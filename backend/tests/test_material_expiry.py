"""Test báo cáo hạn sử dụng NVL (GET /api/warehouse/expiry) — dùng cho biểu đồ dashboard
"Nguyên vật liệu sắp/đã hết hạn": mỗi dòng kèm tên/mã vật tư, chỉ xét lô NVL còn tồn kho
(không lẫn lô thành phẩm/bán thành phẩm dùng chung bảng material_lot)."""

import os
import tempfile
from datetime import timedelta

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["MES_DATABASE_URL"] = f"sqlite:///{_TMP.name}"
os.environ["MES_DEV_HEADER_AUTH"] = "0"
os.environ["MES_RL_ENABLED"] = "0"
os.environ["MES_ADMIN_PASSWORD"] = "AdminTest123"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import seed as seed_mod
from app.database import SessionLocal
from app.common import new_id, utcnow
from app.models.materials import MaterialLot


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


def _create_material(client, admin_h, code):
    r = client.post("/api/materials", headers=admin_h,
                    json={"code": code, "name": f"Vat tu {code}", "uom": "kg", "category": "malt"})
    assert r.status_code == 201, r.text
    return r.json()["material_id"]


def test_expiry_report_classifies_and_includes_material_name(client, admin_h):
    mat_id = _create_material(client, admin_h, "EXP-MAT-01")
    now = utcnow()
    db = SessionLocal()
    try:
        expired_lot = MaterialLot(lot_id=new_id(), lot_code=f"EXP-OLD-{new_id()[:6]}", lot_year=now.year,
                                  material_id=mat_id, quantity=20, uom="kg",
                                  expiry=now - timedelta(days=3), created_at=now)
        near_lot = MaterialLot(lot_id=new_id(), lot_code=f"EXP-NEAR-{new_id()[:6]}", lot_year=now.year,
                               material_id=mat_id, quantity=10, uom="kg",
                               expiry=now + timedelta(days=5), created_at=now)
        ok_lot = MaterialLot(lot_id=new_id(), lot_code=f"EXP-OK-{new_id()[:6]}", lot_year=now.year,
                             material_id=mat_id, quantity=15, uom="kg",
                             expiry=now + timedelta(days=200), created_at=now)
        db.add_all([expired_lot, near_lot, ok_lot])
        db.commit()
        expired_code, near_code, ok_code = expired_lot.lot_code, near_lot.lot_code, ok_lot.lot_code
    finally:
        db.close()

    rows = client.get("/api/warehouse/expiry?warn_days=14", headers=admin_h).json()
    by_code = {r["lot_code"]: r for r in rows}

    assert by_code[expired_code]["status"] == "expired"
    assert by_code[expired_code]["days_left"] < 0
    assert by_code[expired_code]["material_code"] == "EXP-MAT-01"
    assert by_code[expired_code]["material_name"] == "Vat tu EXP-MAT-01"

    assert by_code[near_code]["status"] == "near"
    assert by_code[ok_code]["status"] == "ok"


def test_expiry_report_excludes_zero_quantity_lots(client, admin_h):
    mat_id = _create_material(client, admin_h, "EXP-MAT-ZERO")
    now = utcnow()
    db = SessionLocal()
    try:
        depleted = MaterialLot(lot_id=new_id(), lot_code=f"EXP-ZERO-{new_id()[:6]}", lot_year=now.year,
                               material_id=mat_id, quantity=0, uom="kg",
                               expiry=now - timedelta(days=1), created_at=now)
        db.add(depleted)
        db.commit()
        zero_code = depleted.lot_code
    finally:
        db.close()

    rows = client.get("/api/warehouse/expiry", headers=admin_h).json()
    assert all(r["lot_code"] != zero_code for r in rows)
