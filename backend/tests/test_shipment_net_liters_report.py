"""Test báo cáo tổng lít xuất theo (ngày, loại bia) trong 1 kỳ tùy chọn
(GET /api/reports/shipment-net-liters-report): tổng lít GỘP (gồm cả bia gửi), tách riêng
cận date/gửi, và cột cuối tự trừ bia gửi (Thực xuất = Tổng lít - Gửi, KHÔNG trừ cận date).
"""

import os
import tempfile
from datetime import datetime

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
from app.common import new_id
from app.models.wms import FinishedGoodsUnit
from app.models.master import FinishedProduct


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


def _mk_unit(db, *, fp, qty, shipped_at, near_expiry=False, consigned=False):
    u = FinishedGoodsUnit(unit_id=new_id(), unit_code=f"U-{new_id()[:8]}", unit_type="vi",
                          finished_product_id=fp.finished_product_id, product_name=fp.code,
                          quantity=qty, status="shipped", shipped_at=shipped_at, created_by="admin",
                          is_near_expiry=near_expiry, is_consigned=consigned)
    db.add(u)
    return u


def test_shipment_net_liters_report_computes_gross_and_net(client, admin_h):
    db = SessionLocal()
    try:
        suffix = new_id()[:8]
        fp = FinishedProduct(finished_product_id=new_id(), code=f"SNL-{suffix}",
                             name="Bia lon Sapphire 330ml", uom="lon", unit_type="vi",
                             pack_size=24, category="Bia lon")
        db.add(fp)
        db.flush()

        day = "2026-06-20"
        ca1_time = datetime.fromisoformat(day + "T01:00:00")  # 08h00 VN -> ngày 20/6

        # 100 đơn vị thường + 20 cận date (KHÔNG trừ) + 30 bia gửi (BỊ trừ) -> 0.33L/đơn vị.
        _mk_unit(db, fp=fp, qty=100, shipped_at=ca1_time)
        _mk_unit(db, fp=fp, qty=20, shipped_at=ca1_time, near_expiry=True)
        _mk_unit(db, fp=fp, qty=30, shipped_at=ca1_time, consigned=True)
        db.commit()
    finally:
        db.close()

    date_from = day + "T00:00:00"
    date_to = day + "T23:59:59.999999"
    r = client.get(
        f"/api/reports/shipment-net-liters-report?date_from={date_from}&date_to={date_to}",
        headers=admin_h)
    assert r.status_code == 200, r.text
    body = r.json()

    row = next(x for x in body["rows"] if x["date"] == day and x["category"] == "Bia lon")
    # Tổng lít gộp: (100+20+30) x 0.33 = 49.5 -> làm tròn 50 (cận date KHÔNG bị loại khỏi tổng
    # lít gộp — chỉ hiện riêng để biết cấu thành, không trừ ở cột thực xuất).
    assert row["total_liters"] == 50
    assert row["near_expiry_liters"] == round(20 * 0.33)
    assert row["consigned_liters"] == round(30 * 0.33)
    # Thực xuất = Tổng lít - Gửi (không trừ cận date).
    assert row["net_liters"] == row["total_liters"] - row["consigned_liters"]

    day_row = next(x for x in body["by_day"] if x["date"] == day)
    assert day_row["total_liters"] == row["total_liters"]
    assert day_row["net_liters"] == row["net_liters"]

    assert body["totals"]["total_liters"] == row["total_liters"]
    assert body["totals"]["net_liters"] == row["net_liters"]


def test_shipment_net_liters_report_unmatched_sku_excluded(client, admin_h):
    db = SessionLocal()
    try:
        suffix = new_id()[:8]
        fp = FinishedProduct(finished_product_id=new_id(), code=f"SNL-UNK-{suffix}",
                             name=f"SKU không rõ dung tích {suffix}", uom="cái",
                             unit_type="vi", pack_size=1, category="Khác")
        db.add(fp)
        db.flush()
        day = "2026-06-21"
        t = datetime.fromisoformat(day + "T01:00:00")
        _mk_unit(db, fp=fp, qty=7, shipped_at=t)
        db.commit()
    finally:
        db.close()

    date_from = day + "T00:00:00"
    date_to = day + "T23:59:59.999999"
    r = client.get(
        f"/api/reports/shipment-net-liters-report?date_from={date_from}&date_to={date_to}",
        headers=admin_h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert not any(x["date"] == day for x in body["rows"])
    unmatched_names = [u["product_name"] for u in body["unmatched_products"]]
    assert f"SKU không rõ dung tích {suffix}" in unmatched_names
