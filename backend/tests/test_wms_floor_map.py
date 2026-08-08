"""Sơ đồ kho vật lý (GET /api/wms/warehouses/{id}/floor-map) — sơ đồ Dãy xếp/Kho tạm cho 1 kho
thành phẩm cụ thể, hiển thị lô nào đang ở vị trí nào và có "sẵn sàng xuất FIFO" hay không. Điểm
cốt lõi cần test: cờ sẵn sàng FIFO tính RIÊNG trong phạm vi kho đang xem — khác với
{type}_fifo_ok của list_lot_summaries (tính "cũ nhất" xuyên TOÀN hệ thống, mọi kho)."""

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
from app.models.wms import FinishedGoodsUnit


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


def _add_unit(product_name, lot_code, loc_id, age_days):
    db = SessionLocal()
    try:
        db.add(FinishedGoodsUnit(unit_id=new_id(), unit_code=f"KEG-FM-{new_id()[:8]}",
                                 unit_type="keg", product_name=product_name, lot_code=lot_code,
                                 quantity=5, status="stored", location_id=loc_id,
                                 created_by="admin", created_at=utcnow() - timedelta(days=age_days)))
        db.commit()
    finally:
        db.close()


def test_floor_map_fifo_ready_scoped_to_own_warehouse_not_global(client, admin_h):
    wh_dm = client.post("/api/wms/warehouses", headers=admin_h,
                        json={"code": "WH-FM-DM", "name": "Kho FloorMap Đông Mai"}).json()
    wh_hl = client.post("/api/wms/warehouses", headers=admin_h,
                        json={"code": "WH-FM-HL", "name": "Kho FloorMap Hạ Long"}).json()
    loc_dm = client.post("/api/wms/locations", headers=admin_h,
                         json={"code": "D01-FM", "name": "Dãy xếp 01", "capacity": 500,
                               "warehouse_id": wh_dm["warehouse_id"]}).json()
    loc_dm_empty = client.post("/api/wms/locations", headers=admin_h,
                               json={"code": "D02-FM", "name": "Dãy xếp 02", "capacity": 500,
                                     "warehouse_id": wh_dm["warehouse_id"]}).json()
    loc_hl = client.post("/api/wms/locations", headers=admin_h,
                         json={"code": "A1-FM-HL", "name": "Khu A1", "capacity": 500,
                               "warehouse_id": wh_hl["warehouse_id"]}).json()

    product_name = f"FM-TEST-{new_id()[:8]}"
    # Lô ở Đông Mai mới hơn (5 ngày) NHƯNG lô ở Hạ Long cũ hơn (30 ngày) — nếu tính FIFO toàn hệ
    # thống (như list_lot_summaries) thì lô Đông Mai sẽ KHÔNG sẵn sàng FIFO (còn lô cũ hơn ở kho
    # khác); nhưng vì sơ đồ chỉ tính trong phạm vi Đông Mai, lô Đông Mai vẫn phải "sẵn sàng".
    _add_unit(product_name, "LOT-DM-NEWER", loc_dm["loc_id"], age_days=5)
    _add_unit(product_name, "LOT-HL-OLDER", loc_hl["loc_id"], age_days=30)

    rows = client.get(f"/api/wms/warehouses/{wh_dm['warehouse_id']}/floor-map", headers=admin_h).json()

    codes = {r["code"] for r in rows}
    assert codes == {"D01-FM", "D02-FM"}, "chỉ trả vị trí thuộc kho Đông Mai, không lẫn Hạ Long"

    row_d01 = next(r for r in rows if r["code"] == "D01-FM")
    assert len(row_d01["lots"]) == 1
    lot = row_d01["lots"][0]
    assert lot["product_name"] == product_name
    assert lot["lot_code"] == "LOT-DM-NEWER"
    assert lot["count"] == 5
    assert lot["fifo_ready"] is True, "lô Đông Mai phải sẵn sàng FIFO trong phạm vi kho này dù có lô cũ hơn ở kho khác"

    row_d02 = next(r for r in rows if r["code"] == "D02-FM")
    assert row_d02["lots"] == [], "vị trí không có hàng phải trả lots rỗng, không lỗi"


def test_floor_map_second_newer_lot_not_fifo_ready(client, admin_h):
    wh = client.post("/api/wms/warehouses", headers=admin_h,
                     json={"code": "WH-FM-2", "name": "Kho FloorMap 2"}).json()
    loc_old = client.post("/api/wms/locations", headers=admin_h,
                          json={"code": "D01-FM2", "name": "Dãy xếp 01", "capacity": 500,
                                "warehouse_id": wh["warehouse_id"]}).json()
    loc_new = client.post("/api/wms/locations", headers=admin_h,
                          json={"code": "D02-FM2", "name": "Dãy xếp 02", "capacity": 500,
                                "warehouse_id": wh["warehouse_id"]}).json()
    product_name = f"FM-TEST2-{new_id()[:8]}"
    _add_unit(product_name, "LOT-OLD", loc_old["loc_id"], age_days=20)
    _add_unit(product_name, "LOT-NEW", loc_new["loc_id"], age_days=2)

    rows = client.get(f"/api/wms/warehouses/{wh['warehouse_id']}/floor-map", headers=admin_h).json()
    old_lot = next(r for r in rows if r["code"] == "D01-FM2")["lots"][0]
    new_lot = next(r for r in rows if r["code"] == "D02-FM2")["lots"][0]
    assert old_lot["fifo_ready"] is True
    assert new_lot["fifo_ready"] is False
