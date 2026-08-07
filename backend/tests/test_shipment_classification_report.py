"""Test báo cáo phân loại xuất kho (GET /api/reports/shipment-classification-report):
lượng bia khuyến mại/đổi trả (theo Shipment.shipment_type) + cận date/gửi (theo cờ trên chính
FinishedGoodsUnit) theo ngày hoặc tháng — 4 chỉ số ĐỘC LẬP, không loại trừ nhau.
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
from app.models.wms import FinishedGoodsUnit, Shipment
from app.models.master import FinishedProduct
from app.models.materials import Supplier


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


def test_shipment_classification_report_buckets_independently(client, admin_h):
    db = SessionLocal()
    try:
        suffix = new_id()[:8]
        fp = FinishedProduct(finished_product_id=new_id(), code=f"SCR-{suffix}",
                             name="Bia lon test SCR", uom="lon", unit_type="vi",
                             pack_size=1, category="Bia lon")
        ship_to = Supplier(supplier_id=new_id(), code=f"SCR-DIST-{suffix}", name="NPP test SCR")
        db.add(ship_to)
        db.flush()

        promo_ship = Shipment(shipment_id=new_id(), shipment_code=f"SCR-PROMO-{suffix}",
                              ship_to_id=ship_to.supplier_id, shipment_type="promo", created_by="admin")
        return_ship = Shipment(shipment_id=new_id(), shipment_code=f"SCR-RETURN-{suffix}",
                               ship_to_id=ship_to.supplier_id, shipment_type="return", created_by="admin")
        db.add_all([promo_ship, return_ship])
        db.flush()

        day = "2026-06-17"
        t = datetime.fromisoformat(day + "T01:00:00")  # 08h VN -> Ca 1, cùng "ngày" bucket

        def _u(qty, shipment=None, line_type=None, near_expiry=False, consigned=False):
            u = FinishedGoodsUnit(unit_id=new_id(), unit_code=f"U-{new_id()[:8]}", unit_type="vi",
                                  finished_product_id=fp.finished_product_id, product_name=fp.code,
                                  quantity=qty, status="shipped", shipped_at=t, created_by="admin",
                                  shipment_id=shipment.shipment_id if shipment else None,
                                  shipment_line_type=line_type,
                                  is_near_expiry=near_expiry, is_consigned=consigned)
            db.add(u)
            return u

        _u(10, shipment=promo_ship, line_type="promo")     # promo
        _u(5, shipment=return_ship, line_type="return")    # return
        _u(7, near_expiry=True)                      # cận date, dòng thường (không set)
        _u(3, consigned=True)                        # gửi, dòng thường
        db.commit()
    finally:
        db.close()

    date_from = day + "T00:00:00"
    date_to = day + "T23:59:59.999999"
    r = client.get(
        f"/api/reports/shipment-classification-report?date_from={date_from}&date_to={date_to}&group_by=day",
        headers=admin_h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["group_by"] == "day"
    row = next(x for x in body["rows"] if x["period"] == day)
    assert row["promo"] == 10
    assert row["return"] == 5
    assert row["near_expiry"] == 7
    assert row["consigned"] == 3

    # group_by=month gộp về "YYYY-MM" của cùng mốc ngày đó.
    r2 = client.get(
        f"/api/reports/shipment-classification-report?date_from={date_from}&date_to={date_to}&group_by=month",
        headers=admin_h)
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["group_by"] == "month"
    row2 = next(x for x in body2["rows"] if x["period"] == day[:7])
    assert row2["promo"] == 10
    assert row2["return"] == 5
    assert row2["near_expiry"] == 7
    assert row2["consigned"] == 3


def test_shipment_classification_report_rejects_bad_group_by(client, admin_h):
    r = client.get(
        "/api/reports/shipment-classification-report?date_from=2026-01-01T00:00:00&date_to=2026-01-02T00:00:00&group_by=week",
        headers=admin_h)
    assert r.status_code == 409, r.text
