"""Test báo cáo xuất thành phẩm theo ca (GET /api/reports/finished-goods-shift-report):
- Quy đổi lít đúng theo dung tích suy từ tên SKU (330ml=0.33L, 20L keg=20L).
- Bucket đúng ca theo giờ shipped_at (Ca 1: 06h-14h, Ca 2: 14h-22h, Ca 3: 22h-06h hôm sau,
  quy về NGÀY BẮT ĐẦU ca — mốc 23h thuộc ca 3 của NGÀY HÔM ĐÓ, không phải hôm sau).
- SKU không suy được dung tích (tên không có ml/L) bị loại khỏi tổng, liệt kê ở unmatched_products.
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
from app.services.wms import _resolve_liters_per_unit, _bucket_shift, finished_goods_shift_report


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


def test_resolve_liters_per_unit_ml_and_l_patterns():
    assert _resolve_liters_per_unit("Bia lon Sapphire 330ml") == pytest.approx(0.33)
    assert _resolve_liters_per_unit("Bia chai Classic 450ml") == pytest.approx(0.45)
    assert _resolve_liters_per_unit("Bia tươi Legend 20L") == 20.0
    assert _resolve_liters_per_unit("Bia hơi Hạ Long 30L") == 30.0
    assert _resolve_liters_per_unit("Không có dung tích") is None
    assert _resolve_liters_per_unit(None) is None


def test_bucket_shift_boundaries_and_ca3_midnight_span():
    # _bucket_shift nhận shipped_at LƯU UTC (xem UTCDateTime) và tự +7h quy về giờ VN trước khi
    # xếp ca — input dưới đây là giờ UTC tương ứng với mốc giờ VN nêu trong comment (VN = UTC+7).
    assert _bucket_shift(datetime(2026, 7, 19, 23, 0)) == ("2026-07-20", 1)  # 06h00 VN
    assert _bucket_shift(datetime(2026, 7, 20, 6, 59)) == ("2026-07-20", 1)  # 13h59 VN
    assert _bucket_shift(datetime(2026, 7, 20, 7, 0)) == ("2026-07-20", 2)  # 14h00 VN
    assert _bucket_shift(datetime(2026, 7, 20, 14, 59)) == ("2026-07-20", 2)  # 21h59 VN
    # 23h VN thuộc Ca 3 của NGÀY 20 (ngày bắt đầu ca), không phải ngày 21.
    assert _bucket_shift(datetime(2026, 7, 20, 16, 0)) == ("2026-07-20", 3)  # 23h00 VN
    # 03h sáng VN thuộc phần "đêm qua" của Ca 3 — quy về ngày hôm trước.
    assert _bucket_shift(datetime(2026, 7, 20, 20, 0)) == ("2026-07-20", 3)  # 03h00 VN hôm sau


def _mk_unit(db, *, fp, qty, shipped_at, unit_type="vi"):
    u = FinishedGoodsUnit(unit_id=new_id(), unit_code=f"U-{new_id()[:8]}", unit_type=unit_type,
                          finished_product_id=fp.finished_product_id, product_name=fp.code,
                          quantity=qty, status="shipped", shipped_at=shipped_at, created_by="admin")
    db.add(u)
    return u


def test_finished_goods_shift_report_converts_and_buckets(client, admin_h):
    db = SessionLocal()
    try:
        suffix = new_id()[:8]
        fp_lon = FinishedProduct(finished_product_id=new_id(), code=f"FGSHIP-LON-{suffix}",
                                 name="Bia lon Sapphire 330ml", uom="lon", unit_type="vi",
                                 pack_size=24, category="Bia lon")
        fp_keg = FinishedProduct(finished_product_id=new_id(), code=f"FGSHIP-KEG-{suffix}",
                                 name="Bia tươi Legend 20L", uom="keg", unit_type="keg",
                                 pack_size=1, category="Bia tươi")
        fp_unknown = FinishedProduct(finished_product_id=new_id(), code=f"FGSHIP-UNK-{suffix}",
                                     name=f"SKU không rõ dung tích {suffix}", uom="cái",
                                     unit_type="vi", pack_size=1, category="Khác")
        db.add_all([fp_lon, fp_keg, fp_unknown])
        db.flush()

        day = "2026-06-15"
        # shipped_at lưu UTC — dùng giờ UTC tương ứng với 08h00/23h30 giờ VN (VN = UTC+7) để
        # _bucket_shift (quy đổi +7h nội bộ) xếp đúng ca như comment bên dưới mô tả.
        ca1_time = datetime.fromisoformat(day + "T01:00:00")  # 08h00 VN → Ca 1
        ca3_time = datetime.fromisoformat(day + "T16:30:00")  # 23h30 VN → Ca 3

        # Ca 1: 100 lon (quantity=100 đơn vị lon nhỏ) x 0.33L = 33L.
        _mk_unit(db, fp=fp_lon, qty=100, shipped_at=ca1_time)
        # Ca 3 (23h30 -> vẫn thuộc ngày `day`): 5 keg x 20L = 100L.
        _mk_unit(db, fp=fp_keg, qty=5, shipped_at=ca3_time, unit_type="keg")
        # SKU không rõ dung tích: phải bị loại khỏi tổng, xuất hiện ở unmatched_products.
        _mk_unit(db, fp=fp_unknown, qty=7, shipped_at=ca1_time)
        db.commit()
    finally:
        db.close()

    date_from = day + "T00:00:00"
    date_to = day + "T23:59:59.999999"
    r = client.get(
        f"/api/reports/finished-goods-shift-report?date_from={date_from}&date_to={date_to}",
        headers=admin_h)
    assert r.status_code == 200, r.text
    rpt = r.json()

    assert rpt["total_liters"] == 133  # 33 (lon) + 100 (keg), round() từng dòng

    by_ca = {c["ca"]: c["liters"] for c in rpt["by_ca"]}
    assert by_ca[1] == 33
    assert by_ca[2] == 0
    assert by_ca[3] == 100

    day_row = next(d for d in rpt["by_day"] if d["date"] == day)
    assert day_row["ca1"] == 33
    assert day_row["ca3"] == 100

    by_cat = {c["category"]: c for c in rpt["by_category"]}
    assert by_cat["Bia lon"]["ca1"] == 33
    assert by_cat["Bia tươi"]["ca3"] == 100
    assert "Khác" not in by_cat  # SKU không rõ dung tích không cộng vào by_category

    unmatched_names = [u["product_name"] for u in rpt["unmatched_products"]]
    assert f"SKU không rõ dung tích {suffix}" in unmatched_names
    unmatched = next(u for u in rpt["unmatched_products"] if u["product_name"] == f"SKU không rõ dung tích {suffix}")
    assert unmatched["units"] == 7


def test_finished_goods_shift_report_excludes_consigned_units(client, admin_h):
    """is_consigned=True (bia gửi xuất lại lần 2) phải bị LOẠI hoàn toàn khỏi báo cáo — lượng
    này đã được tính vào phiếu xuất gốc buổi sáng, tính tiếp sẽ đếm trùng. is_near_expiry
    (bia cận date) thì KHÔNG loại — xem docstring finished_goods_shift_report/ConsignedEntry."""
    db = SessionLocal()
    try:
        suffix = new_id()[:8]
        fp = FinishedProduct(finished_product_id=new_id(), code=f"FGSHIP-GUI-{suffix}",
                             name="Bia lon Sapphire 330ml", uom="lon", unit_type="vi",
                             pack_size=24, category="Bia lon")
        db.add(fp)
        db.flush()

        day = "2026-06-16"
        ca1_time = datetime.fromisoformat(day + "T01:00:00")  # 08h00 VN -> Ca 1

        normal = _mk_unit(db, fp=fp, qty=50, shipped_at=ca1_time)
        consigned = _mk_unit(db, fp=fp, qty=30, shipped_at=ca1_time)
        consigned.is_consigned = True
        near_expiry = _mk_unit(db, fp=fp, qty=20, shipped_at=ca1_time)
        near_expiry.is_near_expiry = True
        db.commit()
    finally:
        db.close()

    date_from = day + "T00:00:00"
    date_to = day + "T23:59:59.999999"
    r = client.get(
        f"/api/reports/finished-goods-shift-report?date_from={date_from}&date_to={date_to}",
        headers=admin_h)
    assert r.status_code == 200, r.text
    rpt = r.json()
    # (50 thường + 20 cận date) x 0.33L = 23.1L, làm tròn 23 — 30 bia gửi KHÔNG được cộng vào.
    assert rpt["total_liters"] == 23


def test_finished_goods_shift_report_direct_service_call_empty_range():
    db = SessionLocal()
    try:
        result = finished_goods_shift_report(db, datetime(2010, 1, 1), datetime(2010, 1, 2))
    finally:
        db.close()
    assert result["total_liters"] == 0
    assert result["by_ca"] == [{"ca": 1, "label": "Ca 1", "liters": 0},
                               {"ca": 2, "label": "Ca 2", "liters": 0},
                               {"ca": 3, "label": "Ca 3", "liters": 0}]
    assert result["by_day"] == []
    assert result["shifts"] == []
    assert result["unmatched_products"] == []
