"""Test hiệu năng + tính đúng của Truy xuôi xuất (GET /trace/forward) từ 1 mã chiết khi số
vỉ/keg sinh ra RẤT LỚN (thực tế: approve_bottle tạo 1 cạnh GenealogyEdge/đơn vị — 1 mẻ chiết
lớn có thể sinh hàng trăm nghìn vỉ). Bug thực tế: _walk() đệ quy TỪNG cạnh (N+1 query + đệ quy
hàng trăm nghìn lần) khiến request treo nhiều phút/giờ, không bao giờ trả về — nút "Truy xuôi
xuất" trên UI không chạy được. Fix: genealogy._bottle_forward_groups gộp qua SQL GROUP BY khi
số cạnh vượt BOTTLE_UNIT_AGGREGATE_THRESHOLD, trả về 1 dòng/(loại đơn vị, trạng thái, phiếu
xuất) kèm luôn thông tin nơi xuất đến/lái xe/ngày giờ/loại xuất — không cần đệ quy thêm.
Dưới ngưỡng vẫn đệ quy đầy đủ (giữ nguyên mã từng vỉ/keg) — test bằng test_traceability_brew_chain.py.
"""

import os
import tempfile
import time

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
from app.models.brewing import BottleRecord
from app.models.wms import FinishedGoodsUnit, Shipment, ShipToLocation
from app.services import genealogy


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


def _build_huge_bottle(db, *, unit_count=300, shipped_count=5):
    """Mô phỏng approve_bottle với số lượng vỉ LỚN — trực tiếp tạo BottleRecord +
    FinishedGoodsUnit + GenealogyEdge (mirror đúng code thật ở wms.py/approve_bottle) để
    không phải dựng lại toàn bộ chuỗi Nấu->Lên men->Lọc->Chiết chỉ để test 1 hàm gộp nhóm."""
    bottle_id = new_id()
    db.add(BottleRecord(bottle_id=bottle_id, bottle_code=f"CH-HUGE-{bottle_id[:8]}",
                        beer_type="Bia test", approved=True))

    ship_to = ShipToLocation(ship_to_id=new_id(), code=f"NPP-HUGE-{bottle_id[:8]}", name="NPP Test Huge")
    db.add(ship_to)
    shipment = Shipment(shipment_id=new_id(), shipment_code=f"SHP-HUGE-{bottle_id[:8]}",
                        ship_to_id=ship_to.ship_to_id, driver_name="Nguyễn Văn Tài",
                        vehicle_plate="14C-99999", shipment_type="promo", from_location="Kho công ty")
    db.add(shipment)
    db.flush()

    for i in range(unit_count):
        shipped = i < shipped_count
        u = FinishedGoodsUnit(unit_id=new_id(), unit_code=f"VI-HUGE-{bottle_id[:6]}-{i:06d}",
                              unit_type="vi", product_name="CSPS330 test", lot_code="LOT-HUGE-1",
                              quantity=24, status="shipped" if shipped else "stored",
                              shipment_id=shipment.shipment_id if shipped else None,
                              ship_to_id=ship_to.ship_to_id if shipped else None,
                              created_by="admin", created_at=utcnow())
        db.add(u)
        db.flush()
        genealogy.add_edge(db, from_type="bottle", from_id=bottle_id, to_type="finished_goods_unit",
                           to_id=u.unit_id, relation="chiết", quantity=u.quantity, uom="vi")
    db.commit()
    return bottle_id


def test_trace_forward_aggregates_huge_bottle_fanout_fast(client, admin_h):
    db = SessionLocal()
    try:
        bottle_id = _build_huge_bottle(db, unit_count=300, shipped_count=5)
    finally:
        db.close()

    started = time.perf_counter()
    r = client.get(f"/api/trace/forward?node_type=bottle&node_id={bottle_id}", headers=admin_h)
    elapsed = time.perf_counter() - started
    assert r.status_code == 200, r.text
    assert elapsed < 5, f"Truy xuôi xuất mất {elapsed:.1f}s cho 300 đơn vị — phải gộp nhóm, không đệ quy từng cạnh."

    tree = r.json()
    assert tree["type"] == "bottle"
    children = tree["children"]
    # Gộp còn 2 nhóm: 5 vỉ đã xuất (1 phiếu) + 295 vỉ còn tồn kho — KHÔNG phải 300 dòng riêng lẻ.
    assert len(children) == 2

    shipped_group = next(c for c in children if c["type"] == "shipment_group")
    assert shipped_group["count"] == 5
    assert shipped_group["quantity"] == 5 * 24
    assert shipped_group["ship_to_code"] == f"NPP-HUGE-{bottle_id[:8]}"
    assert shipped_group["driver_name"] == "Nguyễn Văn Tài"
    assert shipped_group["vehicle_plate"] == "14C-99999"
    assert shipped_group["shipment_type"] == "promo"

    stock_group = next(c for c in children if c["type"] == "stock_group")
    assert stock_group["count"] == 295
    assert stock_group["unit_status"] == "stored"


def test_recall_simulation_fast_for_huge_bottle_fanout(client, admin_h):
    db = SessionLocal()
    try:
        bottle_id = _build_huge_bottle(db, unit_count=250, shipped_count=3)
    finally:
        db.close()

    started = time.perf_counter()
    r = client.get(f"/api/trace/recall?node_type=bottle&node_id={bottle_id}", headers=admin_h)
    elapsed = time.perf_counter() - started
    assert r.status_code == 200, r.text
    assert elapsed < 5, f"Recall simulation mất {elapsed:.1f}s cho 250 đơn vị — phải gộp nhóm."
    assert r.json()["affected_count"] == 2  # 1 nhóm đã xuất + 1 nhóm còn tồn kho
