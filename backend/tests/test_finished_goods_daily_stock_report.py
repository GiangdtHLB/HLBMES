"""Test báo cáo NXT kho thành phẩm THEO NGÀY (GET /api/reports/finished-goods-stock-daily-report,
mirror mẫu Excel sheet "Ngày X.X"): CHỈ 1 ngày mỗi lần gọi (`day=` query param, không phải khoảng
ngày — tránh tải/hiển thị nhiều ngày cùng lúc gây big data). Tồn đầu/Nhập sản xuất/Xuất ĐL&KM/Tồn
cuối dựng lại tại đúng mốc cắt ngày cấu hình (OpsSetting.fg_day_cutoff_hour, giờ VN), CHIA RIÊNG
theo từng KHO THÀNH PHẨM (`warehouses` — mirror mẫu Excel Kho Đông Mai/Kho Hạ Long), gộp nhóm theo
category trong mỗi kho, và mỗi dòng SKU-trong-1-kho có `oldest_at`/`fifo_ok` SO SÁNH CẢ CÁC KHO để
báo thủ kho nên xuất từ kho nào trước theo đúng nguyên tắc FIFO.
"""

import os
import tempfile
from datetime import datetime, timezone

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
from app.models.wms import FinishedGoodsUnit, WmsLocation, WmsWarehouse
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


def _mk_unit(db, *, fp, qty, created_at, status="stored", shipped_at=None,
            source=None, is_consigned=False, lot_code=None):
    u = FinishedGoodsUnit(unit_id=new_id(), unit_code=f"U-{new_id()[:8]}", unit_type=fp.unit_type,
                          finished_product_id=fp.finished_product_id, product_name=fp.code,
                          quantity=qty, status=status, created_at=created_at, shipped_at=shipped_at,
                          source=source, created_by="admin", is_consigned=is_consigned, lot_code=lot_code)
    db.add(u)
    return u


def _set_cutoff_hour(client, admin_h, hour):
    r = client.get("/api/ops-settings", headers=admin_h)
    s = r.json()
    s["fg_day_cutoff_hour"] = hour
    r2 = client.put("/api/ops-settings", headers=admin_h, json=s)
    assert r2.status_code == 200, r2.text
    assert r2.json()["fg_day_cutoff_hour"] == hour


def _row_for(body, fp_id):
    """Tìm dòng theo fp_id ở BẤT KỲ kho nào (body["warehouses"][i]["groups"][j]["rows"]) — dùng
    cho các test không quan tâm SKU rơi vào kho nào, chỉ cần đúng số liệu Tồn đầu/Nhập/Xuất/Tồn
    cuối. Các đơn vị tạo qua _mk_unit không gán location_id nên luôn rơi vào bucket "Chưa xác
    định kho" duy nhất — an toàn giả định chỉ 1 dòng khớp."""
    for wh in body["warehouses"]:
        for g in wh["groups"]:
            for rr in g["rows"]:
                if rr["finished_product_id"] == fp_id:
                    return rr
    return None


def test_daily_report_single_day_only_no_range(client, admin_h):
    """Endpoint chỉ nhận `day=` (1 ngày), KHÔNG có date_from/date_to — trả về đúng 1 bộ
    warehouses/date, không phải danh sách nhiều ngày."""
    r = client.get("/api/reports/finished-goods-stock-daily-report?day=2026-06-10", headers=admin_h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["date"] == "2026-06-10"
    assert "days" not in body
    assert "groups" not in body
    assert "warehouses" in body
    for wh in body["warehouses"]:
        assert "warehouse_name" in wh and "groups" in wh


def test_daily_report_reconstructs_opening_at_cutoff_and_scopes_produced_shipped(client, admin_h):
    """cutoff_hour=6 -> 'ngày D' = 06h00 VN ngày D đến 06h00 VN ngày D+1 = 23:00 UTC (D-1) đến
    23:00 UTC (D) (VN = UTC+7). Xác nhận Tồn đầu dựng đúng tại mốc đầu ngày (gồm cả đơn vị sẽ
    xuất SAU ngày này), Nhập/Xuất chỉ tính trong đúng cửa sổ ngày, Tồn cuối = Tồn đầu+Nhập-Xuất."""
    _set_cutoff_hour(client, admin_h, 6)
    try:
        suffix = new_id()[:8]
        r = client.post("/api/finished-products", headers=admin_h,
                        json={"code": f"FGDAY-{suffix}", "name": "Bia keg test theo ngày",
                              "uom": "keg", "unit_type": "keg", "pack_size": 1, "category": "Bia tươi"})
        assert r.status_code == 201, r.text
        fp_id = r.json()["finished_product_id"]

        very_early = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
        # Ngày 2026-06-10 (cutoff=6) = cửa sổ UTC [2026-06-09T23:00, 2026-06-10T23:00).
        within_day = datetime(2026, 6, 10, 5, 0, 0, tzinfo=timezone.utc)
        ship_within_day = datetime(2026, 6, 10, 10, 0, 0, tzinfo=timezone.utc)
        # Xuất SAU ngày 06-10 (thuộc ngày 06-11) — vẫn phải tính vào Tồn đầu ngày 06-10.
        ship_next_day = datetime(2026, 6, 11, 8, 0, 0, tzinfo=timezone.utc)

        db = SessionLocal()
        try:
            fp = db.get(FinishedProduct, fp_id)
            a = _mk_unit(db, fp=fp, qty=50, created_at=very_early, status="stored")
            c = _mk_unit(db, fp=fp, qty=15, created_at=very_early, status="shipped", shipped_at=ship_within_day)
            e = _mk_unit(db, fp=fp, qty=8, created_at=very_early, status="shipped", shipped_at=ship_next_day)
            b = _mk_unit(db, fp=fp, qty=20, created_at=within_day, status="stored", source="chiet")
            db.add_all([a, c, e, b])
            db.commit()
        finally:
            db.close()

        r = client.get(f"/api/reports/finished-goods-stock-daily-report?day=2026-06-10&product_ids={fp_id}",
                       headers=admin_h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["date"] == "2026-06-10"
        assert body["cutoff_hour"] == 6

        row = _row_for(body, fp_id)
        assert row is not None
        # Tồn đầu = A(50)+C(15)+E(8) = 73 — E chưa xuất tới đầu ngày (xuất ở ngày 06-11) nên vẫn
        # tồn tại tại mốc đầu ngày, dù không tính vào Xuất ĐL&KM (chỉ C xuất trong cửa sổ ngày này).
        assert row["opening_stock"] == 73
        assert row["produced"] == 20
        assert row["shipped"] == 15
        assert row["closing_stock"] == 78  # 73 + 20 - 15
    finally:
        _set_cutoff_hour(client, admin_h, 0)


def test_daily_report_excludes_consigned_from_shipped_but_counts_in_opening(client, admin_h):
    """Bia gửi (is_consigned=True) xuất lại trong ngày KHÔNG được tính vào Xuất ĐL&KM (đã tính vào
    phiếu xuất gốc trước đó, tránh đếm trùng — đúng quy ước finished_goods_shift_report), nhưng
    VẪN tính vào Tồn đầu nếu đơn vị đó còn tồn tại tại đúng mốc đầu ngày."""
    _set_cutoff_hour(client, admin_h, 0)
    suffix = new_id()[:8]
    r = client.post("/api/finished-products", headers=admin_h,
                    json={"code": f"FGDAYC-{suffix}", "name": "Bia keg test bia gửi theo ngày",
                          "uom": "keg", "unit_type": "keg", "pack_size": 1, "category": "Bia tươi"})
    assert r.status_code == 201, r.text
    fp_id = r.json()["finished_product_id"]

    before = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
    within_day = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)

    db = SessionLocal()
    try:
        fp = db.get(FinishedProduct, fp_id)
        _mk_unit(db, fp=fp, qty=40, created_at=before, status="stored")
        _mk_unit(db, fp=fp, qty=12, created_at=before, status="shipped", shipped_at=within_day,
                is_consigned=True)
        db.commit()
    finally:
        db.close()

    r = client.get(f"/api/reports/finished-goods-stock-daily-report?day=2026-07-10&product_ids={fp_id}",
                   headers=admin_h)
    assert r.status_code == 200, r.text
    body = r.json()
    row = _row_for(body, fp_id)

    # Tồn đầu = 40 + 12 = 52 (cả 2 đơn vị đều tồn tại tại đầu ngày — bia gửi chưa xuất tới lúc đó).
    assert row["opening_stock"] == 52
    # Xuất ĐL&KM = 0 vì đơn vị duy nhất xuất trong ngày là bia gửi (is_consigned=True), bị loại.
    assert row["shipped"] == 0
    assert row["produced"] == 0
    assert row["closing_stock"] == 52


def test_daily_report_groups_by_category_with_subtotal_and_cutoff_from_ops_settings(client, admin_h):
    _set_cutoff_hour(client, admin_h, 6)
    try:
        r = client.get("/api/reports/finished-goods-stock-daily-report?day=2026-06-10", headers=admin_h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["cutoff_hour"] == 6
        for wh in body["warehouses"]:
            for g in wh["groups"]:
                for key in ("opening_stock", "produced", "shipped", "closing_stock"):
                    assert g["subtotal"][key] == round(sum(rr[key] for rr in g["rows"]), 2)
    finally:
        _set_cutoff_hour(client, admin_h, 0)


def test_daily_report_defaults_to_today_when_day_omitted(client, admin_h):
    from app.common import utcnow
    r = client.get("/api/reports/finished-goods-stock-daily-report", headers=admin_h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["date"] == utcnow().date().isoformat()


def test_daily_report_splits_by_warehouse_and_flags_cross_warehouse_fifo(client, admin_h):
    """1 SKU tồn ở CẢ 2 kho: mỗi kho phải ra 1 dòng riêng (chia đúng theo warehouse_id qua
    FinishedGoodsUnit.location_id -> WmsLocation.warehouse_id), và cột fifo_ok phải đánh dấu
    ĐÚNG kho đang giữ lô nhập SỚM NHẤT (so sánh CẢ 2 kho, dựa trên tồn "stored" HIỆN TẠI, không
    phụ thuộc ngày `day` đang xem) — kho còn lại (lô mới hơn) phải fifo_ok=False."""
    suffix = new_id()[:8]
    db = SessionLocal()
    try:
        wh_dm = WmsWarehouse(warehouse_id=new_id(), code=f"DMT-{suffix}", name=f"Kho Đông Mai Test {suffix}")
        wh_hl = WmsWarehouse(warehouse_id=new_id(), code=f"HLT-{suffix}", name=f"Kho Hạ Long Test {suffix}")
        loc_dm = WmsLocation(loc_id=new_id(), code=f"LOCDM-{suffix}", name="Vị trí DM test",
                            warehouse_id=wh_dm.warehouse_id)
        loc_hl = WmsLocation(loc_id=new_id(), code=f"LOCHL-{suffix}", name="Vị trí HL test",
                            warehouse_id=wh_hl.warehouse_id)
        db.add_all([wh_dm, wh_hl, loc_dm, loc_hl])
        db.commit()
        wh_dm_id, wh_hl_id, loc_dm_id, loc_hl_id = (wh_dm.warehouse_id, wh_hl.warehouse_id,
                                                    loc_dm.loc_id, loc_hl.loc_id)
    finally:
        db.close()

    r = client.post("/api/finished-products", headers=admin_h,
                    json={"code": f"FGWH-{suffix}", "name": "Bia keg test chia kho",
                          "uom": "keg", "unit_type": "keg", "pack_size": 1, "category": "Bia tươi"})
    assert r.status_code == 201, r.text
    fp_id = r.json()["finished_product_id"]

    older = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)   # lô cũ hơn -> ở kho Đông Mai
    newer = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)   # lô mới hơn -> ở kho Hạ Long

    db = SessionLocal()
    try:
        fp = db.get(FinishedProduct, fp_id)
        u_dm = _mk_unit(db, fp=fp, qty=10, created_at=older, status="stored", lot_code=f"LOT-DM-{suffix}")
        u_dm.location_id = loc_dm_id
        u_hl = _mk_unit(db, fp=fp, qty=15, created_at=newer, status="stored", lot_code=f"LOT-HL-{suffix}")
        u_hl.location_id = loc_hl_id
        db.add_all([u_dm, u_hl])
        db.commit()
    finally:
        db.close()

    r = client.get(f"/api/reports/finished-goods-stock-daily-report?day=2026-08-01&product_ids={fp_id}",
                   headers=admin_h)
    assert r.status_code == 200, r.text
    body = r.json()

    wh_dm_out = next(w for w in body["warehouses"] if w["warehouse_id"] == wh_dm_id)
    wh_hl_out = next(w for w in body["warehouses"] if w["warehouse_id"] == wh_hl_id)
    assert wh_dm_out["warehouse_code"] == f"DMT-{suffix}"
    assert wh_hl_out["warehouse_code"] == f"HLT-{suffix}"

    row_dm = _row_for({"warehouses": [wh_dm_out]}, fp_id)
    row_hl = _row_for({"warehouses": [wh_hl_out]}, fp_id)
    assert row_dm is not None and row_hl is not None
    assert row_dm["opening_stock"] == 10
    assert row_hl["opening_stock"] == 15

    # Kho Đông Mai giữ lô CŨ HƠN (2026-05-01) -> phải là kho fifo_ok=True (xuất trước).
    assert row_dm["oldest_at"].startswith("2026-05-01")
    assert row_dm["fifo_ok"] is True
    # Kho Hạ Long giữ lô mới hơn (2026-06-01) -> không phải lô cũ nhất toàn hệ thống -> fifo_ok=False.
    assert row_hl["oldest_at"].startswith("2026-06-01")
    assert row_hl["fifo_ok"] is False

    # "Lô cần xuất" + "Vị trí kho" phải đúng theo TỪNG kho — mã lô + vị trí của chính đơn vị đang
    # giữ mốc oldest_at TRONG kho đó (không lẫn giữa 2 kho).
    assert row_dm["reorder_lot_code"] == f"LOT-DM-{suffix}"
    assert row_dm["reorder_location"] == f"LOCDM-{suffix} - Vị trí DM test"
    assert row_hl["reorder_lot_code"] == f"LOT-HL-{suffix}"
    assert row_hl["reorder_location"] == f"LOCHL-{suffix} - Vị trí HL test"
