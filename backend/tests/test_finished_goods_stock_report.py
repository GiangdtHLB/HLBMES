"""Test báo cáo Nhập-Xuất-Tồn kho thành phẩm (GET /api/reports/finished-goods-stock-report,
mirror mẫu Excel "NXT KHO THANH PHAM"): tồn đầu dựng lại đúng điểm-thời-gian date_from, nhập
sản xuất/xuất ĐL&KM chỉ tính trong kỳ (loại bia gửi), đề xuất "Đóng bổ sung" theo ngưỡng
OpsSetting.finished_goods_restock_days, gộp nhóm theo category + dòng tổng phụ, và
PUT /api/finished-products/{id}/plan lưu đúng 3 field kế hoạch + yêu cầu quyền master.manage.
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


@pytest.fixture(scope="module")
def vanhanh_h(client):
    return _login(client, "vanhanh", "123456")


def _mk_unit(db, *, fp, qty, created_at, status="stored", shipped_at=None,
            source=None, is_consigned=False):
    u = FinishedGoodsUnit(unit_id=new_id(), unit_code=f"U-{new_id()[:8]}", unit_type=fp.unit_type,
                          finished_product_id=fp.finished_product_id, product_name=fp.code,
                          quantity=qty, status=status, created_at=created_at, shipped_at=shipped_at,
                          source=source, created_by="admin", is_consigned=is_consigned)
    db.add(u)
    return u


def test_stock_report_opening_and_period_and_restock(client, admin_h):
    suffix = new_id()[:8]
    # unit_type="keg" (không thuộc nhóm "chia theo pack_size" như vỉ) để quantity ánh xạ 1:1
    # với số đơn vị hiển thị, tránh phải quy đổi qua pack_size trong phép tính kỳ vọng dưới đây.
    r = client.post("/api/finished-products", headers=admin_h,
                    json={"code": f"FGSTK-{suffix}", "name": "Bia keg test NXT",
                          "uom": "keg", "unit_type": "keg", "pack_size": 1, "category": "Bia tươi"})
    assert r.status_code == 201, r.text
    fp_id = r.json()["finished_product_id"]

    date_from = datetime.fromisoformat("2026-06-10T00:00:00")
    date_to = datetime.fromisoformat("2026-06-17T00:00:00")
    before_from = datetime.fromisoformat("2026-06-05T00:00:00")
    in_period = datetime.fromisoformat("2026-06-12T00:00:00")
    shipped_before_from = datetime.fromisoformat("2026-06-07T00:00:00")

    db = SessionLocal()
    try:
        fp = db.get(FinishedProduct, fp_id)
        # Tồn đầu: tạo trước date_from, còn "stored" tại date_from -> tính vào Tồn đầu.
        _mk_unit(db, fp=fp, qty=50, created_at=before_from, status="stored")
        # Tạo trước date_from nhưng ĐÃ xuất TRƯỚC date_from -> KHÔNG tính vào Tồn đầu.
        _mk_unit(db, fp=fp, qty=10, created_at=before_from, status="shipped",
                shipped_at=shipped_before_from)
        # Nhập sản xuất trong kỳ (source=chiet, created_at trong [date_from, date_to)).
        _mk_unit(db, fp=fp, qty=30, created_at=in_period, status="stored", source="chiet")
        # Tạo trước date_from, còn tồn TẠI date_from, nhưng xuất ĐL&KM trong kỳ -> vẫn tính vào
        # Tồn đầu (đã tồn tại đúng mốc date_from) VÀ tính vào Xuất ĐL & KM (không phải bia gửi).
        _mk_unit(db, fp=fp, qty=15, created_at=before_from, status="shipped",
                shipped_at=in_period, is_consigned=False)
        # Tương tự nhưng là bia gửi -> vẫn tính vào Tồn đầu, nhưng KHÔNG tính vào Xuất ĐL & KM.
        _mk_unit(db, fp=fp, qty=5, created_at=before_from, status="shipped",
                shipped_at=in_period, is_consigned=True)
        db.commit()
    finally:
        db.close()

    q = f"date_from={date_from.isoformat()}&date_to={date_to.isoformat()}"
    r = client.get(f"/api/reports/finished-goods-stock-report?{q}", headers=admin_h)
    assert r.status_code == 200, r.text
    body = r.json()

    row = None
    for g in body["groups"]:
        for rr in g["rows"]:
            if rr["finished_product_id"] == fp_id:
                row = rr
    assert row is not None, "Không thấy SKU vừa tạo trong báo cáo"

    # Tồn đầu = 50 + 15 + 5 = 70 (loại bỏ đúng unit đã xuất TRƯỚC date_from — 10 — nhưng vẫn
    # gồm 2 unit tồn tại tại đúng mốc date_from rồi mới xuất SAU đó trong kỳ, dù đích xuất là
    # ĐL&KM hay bia gửi — cả hai đều không ảnh hưởng gì tới việc chúng CÓ tồn tại lúc date_from).
    assert row["opening_stock"] == 70
    # Nhập sản xuất trong kỳ = 30.
    assert row["produced"] == 30
    # Xuất ĐL & KM trong kỳ = 15 (loại bia gửi).
    assert row["shipped"] == 15
    # Tồn thực tế hiện tại (status=stored, không phụ thuộc kỳ) = 50 + 30 = 80.
    assert row["on_hand"] == 80
    # Không có xuất non-consigned trong 7 ngày gần nhất tính từ HÔM NAY (dữ liệu test ở quá khứ xa).
    assert row["avg_daily_shipped_7d"] == 0
    assert row["days_of_stock"] is None
    assert row["restock_suggested"] is False


def test_stock_report_groups_by_category_with_subtotal(client, admin_h):
    r = client.get("/api/reports/finished-goods-stock-report", headers=admin_h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "groups" in body and "restock_days" in body
    for g in body["groups"]:
        assert g["subtotal"]["on_hand"] == round(sum(rr["on_hand"] for rr in g["rows"]), 2)
        assert g["subtotal"]["opening_stock"] == round(sum(rr["opening_stock"] for rr in g["rows"]), 2)


def test_monthly_plan_expected_production_qty_roundtrip(client, admin_h):
    suffix = new_id()[:8]
    r = client.post("/api/finished-products", headers=admin_h,
                    json={"code": f"FGEXP-{suffix}", "name": "Bia lon test SX dự kiến",
                          "uom": "lon", "unit_type": "vi", "pack_size": 24, "category": "Bia lon"})
    assert r.status_code == 201, r.text
    fp_id = r.json()["finished_product_id"]

    now = datetime.utcnow()
    r = client.put(f"/api/finished-products/{fp_id}/monthly-plan", headers=admin_h,
                   json={"year": now.year,
                         "cells": [{"month": now.month, "initial_qty": 1000, "adjusted_qty": None,
                                   "expected_production_qty": 800}]})
    assert r.status_code == 200, r.text
    body = r.json()
    cell = next(c for c in body["months"] if c["month"] == now.month)
    assert cell["expected_production_qty"] == 800

    # GET lại bảng xác nhận đã lưu bền, không chỉ trả về đúng response.
    r2 = client.get(f"/api/finished-products/monthly-plan?year={now.year}", headers=admin_h)
    row = next(x for x in r2.json() if x["finished_product_id"] == fp_id)
    cell2 = next(c for c in row["months"] if c["month"] == now.month)
    assert cell2["expected_production_qty"] == 800


def test_monthly_plan_adjusted_overrides_initial_and_feeds_report(client, admin_h):
    suffix = new_id()[:8]
    r = client.post("/api/finished-products", headers=admin_h,
                    json={"code": f"FGMPLAN-{suffix}", "name": "Bia lon test KH tháng",
                          "uom": "lon", "unit_type": "vi", "pack_size": 24, "category": "Bia lon"})
    assert r.status_code == 201, r.text
    fp_id = r.json()["finished_product_id"]

    now = datetime.utcnow()
    r = client.put(f"/api/finished-products/{fp_id}/monthly-plan", headers=admin_h,
                   json={"year": now.year,
                         "cells": [{"month": now.month, "initial_qty": 1000, "adjusted_qty": 1500}]})
    assert r.status_code == 200, r.text
    body = r.json()
    cell = next(c for c in body["months"] if c["month"] == now.month)
    assert cell["initial_qty"] == 1000
    assert cell["adjusted_qty"] == 1500

    # Báo cáo NXT kho thành phẩm phải lấy đúng kế hoạch điều chỉnh (1500), không phải ban đầu.
    r2 = client.get(f"/api/reports/finished-goods-stock-report?product_ids={fp_id}", headers=admin_h)
    assert r2.status_code == 200, r2.text
    row = next(rr for g in r2.json()["groups"] for rr in g["rows"] if rr["finished_product_id"] == fp_id)
    assert row["monthly_target_stock"] == 1500

    # Xóa kế hoạch điều chỉnh (None) -> báo cáo rơi về lại kế hoạch ban đầu.
    r = client.put(f"/api/finished-products/{fp_id}/monthly-plan", headers=admin_h,
                   json={"year": now.year,
                         "cells": [{"month": now.month, "initial_qty": 1000, "adjusted_qty": None}]})
    assert r.status_code == 200, r.text
    r3 = client.get(f"/api/reports/finished-goods-stock-report?product_ids={fp_id}", headers=admin_h)
    row3 = next(rr for g in r3.json()["groups"] for rr in g["rows"] if rr["finished_product_id"] == fp_id)
    assert row3["monthly_target_stock"] == 1000


def test_monthly_plan_list_grid_and_requires_permission(client, admin_h, vanhanh_h):
    now = datetime.utcnow()
    r = client.get(f"/api/finished-products/monthly-plan?year={now.year}", headers=admin_h)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)
    for row in r.json():
        assert len(row["months"]) == 12

    suffix = new_id()[:8]
    r = client.post("/api/finished-products", headers=admin_h,
                    json={"code": f"FGMPLAN2-{suffix}", "name": "Bia lon test quyền KH tháng",
                          "uom": "lon", "unit_type": "vi", "pack_size": 24, "category": "Bia lon"})
    fp_id = r.json()["finished_product_id"]
    r = client.put(f"/api/finished-products/{fp_id}/monthly-plan", headers=vanhanh_h,
                   json={"year": now.year, "cells": [{"month": 1, "initial_qty": 10}]})
    assert r.status_code == 403, r.text


def test_ops_settings_restock_days_roundtrip(client, admin_h):
    r = client.get("/api/ops-settings", headers=admin_h)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["finished_goods_restock_days"] == 7.0

    s["finished_goods_restock_days"] = 10.0
    r2 = client.put("/api/ops-settings", headers=admin_h, json=s)
    assert r2.status_code == 200, r2.text
    assert r2.json()["finished_goods_restock_days"] == 10.0


def test_ops_settings_fg_color_thresholds_roundtrip_and_feed_report(client, admin_h):
    r = client.get("/api/ops-settings", headers=admin_h)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["fg_days_of_stock_critical_days"] == 3.0
    assert s["fg_days_in_stock_warning_days"] == 30.0

    s["fg_days_of_stock_critical_days"] = 4.0
    s["fg_days_in_stock_warning_days"] = 45.0
    r2 = client.put("/api/ops-settings", headers=admin_h, json=s)
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["fg_days_of_stock_critical_days"] == 4.0
    assert body["fg_days_in_stock_warning_days"] == 45.0

    q = "date_from=2026-06-10T00:00:00&date_to=2026-06-17T00:00:00"
    rep = client.get(f"/api/reports/finished-goods-stock-report?{q}", headers=admin_h)
    assert rep.status_code == 200, rep.text
    rep_body = rep.json()
    assert rep_body["days_of_stock_critical_days"] == 4.0
    assert rep_body["days_in_stock_warning_days"] == 45.0

    # Trả 2 ngưỡng về mặc định để không ảnh hưởng các test khác chạy sau trong cùng module.
    s["fg_days_of_stock_critical_days"] = 3.0
    s["fg_days_in_stock_warning_days"] = 30.0
    r3 = client.put("/api/ops-settings", headers=admin_h, json=s)
    assert r3.status_code == 200, r3.text
