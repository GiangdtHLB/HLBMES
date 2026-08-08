"""Test báo cáo tồn kho thành phẩm theo tuổi lô (GET /api/reports/inventory-aging) — mỗi dòng
1 (sản phẩm, lô, loại đơn vị) còn tồn kho, kèm số ngày đã tồn (tính từ đơn vị nhập sớm nhất)
và nhãn cảnh báo (age_bucket) để khối kinh doanh biết lô nào cần đẩy bán gấp."""

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
from app.models.wms import FinishedGoodsUnit, WmsLocation
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


def test_inventory_aging_reports_age_days_and_bucket(client, admin_h):
    db = SessionLocal()
    try:
        loc = WmsLocation(loc_id=new_id(), code=f"AGE-LOC-{new_id()[:6]}", name="Vị trí test tuổi lô")
        db.add(loc)
        db.flush()

        product_name = f"AGING-TEST-{new_id()[:8]}"
        # Đăng ký danh mục SKU (pack_size=24) — cần thiết để _pack_divisor tra đúng, không
        # có SKU sẽ mặc định 1 và "count" (số vỉ) bị lệch thành quantity thô (24 thay vì 1).
        fp = FinishedProduct(finished_product_id=new_id(), code=product_name, name=product_name,
                             uom="lon", unit_type="vi", pack_size=24)
        db.add(fp)
        db.flush()
        now = utcnow()
        old_unit = FinishedGoodsUnit(unit_id=new_id(), unit_code=f"VI-AGE-OLD-{new_id()[:6]}",
                                     unit_type="vi", finished_product_id=fp.finished_product_id,
                                     product_name=product_name, lot_code="LOT-AGE-OLD",
                                     quantity=24, status="stored", location_id=loc.loc_id,
                                     created_by="admin", created_at=now - timedelta(days=95))
        new_unit = FinishedGoodsUnit(unit_id=new_id(), unit_code=f"VI-AGE-NEW-{new_id()[:6]}",
                                     unit_type="vi", finished_product_id=fp.finished_product_id,
                                     product_name=product_name, lot_code="LOT-AGE-NEW",
                                     quantity=24, status="stored", location_id=None,
                                     created_by="admin", created_at=now - timedelta(days=5))
        db.add_all([old_unit, new_unit])
        db.commit()
    finally:
        db.close()

    rows = client.get("/api/reports/inventory-aging", headers=admin_h).json()
    old_row = next(r for r in rows if r["lot_code"] == "LOT-AGE-OLD")
    new_row = next(r for r in rows if r["lot_code"] == "LOT-AGE-NEW")

    assert old_row["age_days"] >= 95
    assert old_row["age_bucket"] == "critical"
    assert old_row["count"] == 1
    assert old_row["locations"] == [{"code": loc.code, "count": 1, "warehouse_code": None}]
    assert old_row["unplaced"] == 0

    assert new_row["age_days"] <= 6
    assert new_row["age_bucket"] == "ok"
    assert new_row["unplaced"] == 1
    assert new_row["locations"] == []

    # Sắp xếp giảm dần theo tuổi — lô cũ nhất phải đứng trước lô mới hơn.
    assert rows.index(old_row) < rows.index(new_row)


def test_inventory_aging_uses_configurable_thresholds(client, admin_h):
    """Ngưỡng cảnh báo (Cài đặt vận hành) phải áp dụng ngay cho báo cáo — hạ ngưỡng caution
    xuống 3 ngày thì lô 5-ngày-tuổi (vốn "ok" ở mặc định 30/60/90) phải chuyển sang "caution"."""
    r = client.put("/api/ops-settings", headers=admin_h, json={
        "empty_cct_tolerance_hl": 2.0, "empty_bbt_tolerance_hl": 2.0,
        "aging_caution_days": 3, "aging_warning_days": 10, "aging_critical_days": 20})
    assert r.status_code == 200, r.text
    try:
        db = SessionLocal()
        try:
            product_name = f"AGING-THRESH-{new_id()[:8]}"
            unit = FinishedGoodsUnit(unit_id=new_id(), unit_code=f"VI-AGE-THRESH-{new_id()[:6]}",
                                     unit_type="vi", product_name=product_name, lot_code="LOT-AGE-THRESH",
                                     quantity=24, status="stored", location_id=None,
                                     created_by="admin", created_at=utcnow() - timedelta(days=5))
            db.add(unit)
            db.commit()
        finally:
            db.close()

        rows = client.get("/api/reports/inventory-aging", headers=admin_h).json()
        row = next(r for r in rows if r["lot_code"] == "LOT-AGE-THRESH")
        assert row["age_bucket"] == "caution"
    finally:
        # Reset về mặc định cho các test khác dùng chung mes.db/module client.
        client.put("/api/ops-settings", headers=admin_h, json={
            "empty_cct_tolerance_hl": 2.0, "empty_bbt_tolerance_hl": 2.0,
            "aging_caution_days": 30, "aging_warning_days": 60, "aging_critical_days": 90})
