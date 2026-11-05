"""Test báo cáo "BC hiệu suất chi tiết theo tháng" (Nhóm D, port từ phần mềm QLSX cũ
dma.biahalong.com:88 › Báo cáo sản xuất, yêu cầu người dùng 2026-11-05) trong
services/yield_reports.py::monthly_yield_detail.

Ghi hiệu suất qua đúng API thật (POST /batches/{id}/yield) để có FK hợp lệ, sau đó SỬA THẲNG
recorded_at qua ORM (API luôn tự set = utcnow(), không nhận tham số) để đẩy bản ghi vào đúng
tháng test (2031-06, tương lai xa — không đụng dữ liệu seed/test khác)."""

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
from app.models.recipe_ext import BatchYieldActual


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


def _make_batch(client, admin_h, suffix):
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(x for x in vers if x["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                          "planned_qty": 1000, "allow_shortage": True})
    assert b.status_code == 201, b.text
    batch_id = b.json()["batch_id"]
    for target in ("ready", "running"):
        r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": target})
        assert r.status_code == 200, r.text
    return batch_id


def _record_yield_in_month(client, admin_h, batch_id, step_key, input_qty, output_qty, when):
    """API luôn set recorded_at=utcnow() — không truyền được qua payload. Lấy diff
    before/after theo yield_id (KHÔNG dùng order_by recorded_at desc) để tìm đúng dòng vừa tạo,
    vì các lần gọi trước đó trong cùng test đã bị sửa recorded_at sang TƯƠNG LAI (2031), nên thời
    điểm thật (utcnow() lúc tạo) của dòng MỚI luôn "nhỏ hơn" các dòng cũ đã bị sửa — order_by desc
    sẽ chọn nhầm dòng cũ."""
    db = SessionLocal()
    try:
        before_ids = {r.yield_id for r in db.query(BatchYieldActual.yield_id).filter(
            BatchYieldActual.batch_id == batch_id, BatchYieldActual.step_key == step_key)}
    finally:
        db.close()
    r = client.post(f"/api/batches/{batch_id}/yield", headers=admin_h,
                    json={"step_key": step_key, "input_qty": input_qty, "output_qty": output_qty})
    assert r.status_code == 200, r.text
    db = SessionLocal()
    try:
        rows = db.query(BatchYieldActual).filter(
            BatchYieldActual.batch_id == batch_id, BatchYieldActual.step_key == step_key)
        row = next(r for r in rows if r.yield_id not in before_ids)
        row.recorded_at = when
        db.commit()
    finally:
        db.close()


def test_monthly_yield_detail_aggregates_by_step(client, admin_h):
    b1 = _make_batch(client, admin_h, "YLD01")
    b2 = _make_batch(client, admin_h, "YLD02")
    JUN2031 = datetime(2031, 6, 15, tzinfo=timezone.utc)
    JUL2031 = datetime(2031, 7, 1, tzinfo=timezone.utc)

    _record_yield_in_month(client, admin_h, b1, "nau", 1000, 950, JUN2031)   # 95%
    _record_yield_in_month(client, admin_h, b2, "nau", 1000, 900, JUN2031)   # 90%
    _record_yield_in_month(client, admin_h, b1, "loc", 950, 940, JUN2031)    # 98.95%
    _record_yield_in_month(client, admin_h, b1, "nau", 1000, 999, JUL2031)   # ngoài tháng test — phải bị loại

    r = client.get("/api/reports/monthly-yield-detail", headers=admin_h,
                   params={"year": 2031, "month": 6})
    assert r.status_code == 200, r.text
    rep = r.json()

    nau = next(s for s in rep["summary"] if s["step_key"] == "nau")
    assert nau["n"] == 2
    assert nau["avg_pct"] == round((95.0 + 90.0) / 2, 2)

    loc = next(s for s in rep["summary"] if s["step_key"] == "loc")
    assert loc["n"] == 1
    assert loc["avg_pct"] == 98.95

    assert len(rep["items"]) == 3   # 2 nau + 1 loc trong tháng 6 — bản ghi tháng 7 không lọt vào
    assert all(i["step_key"] != "nau" or i["output_qty"] != 999 for i in rep["items"])


def _build_full_batch_chain(client, admin_h, suffix, start_at_iso, dich_nha_hl, pack_qty,
                            pack_date_iso, category="Bia lon"):
    """Dựng 1 chuỗi mẻ nấu -> gộp tank -> lô lọc -> lô thành phẩm — mirror
    test_production_reports.py::_build_batch_to_pack (không import chéo giữa 2 file test, theo
    đúng quy ước mỗi file test tự chứa — xem docstring các file test khác trong repo)."""
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(x for x in vers if x["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                          "planned_qty": dich_nha_hl * 100, "allow_shortage": True})
    assert b.status_code == 201, b.text
    batch_id = b.json()["batch_id"]
    product_id = b.json()["product_id"]
    st = client.post(f"/api/batches/{batch_id}/start", headers=admin_h, json={"start_at": start_at_iso})
    assert st.status_code == 200, st.text
    for target in ("ready", "running"):
        r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": target})
        assert r.status_code == 200, r.text
    aq = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h,
                     json={"actual_qty": dich_nha_hl * 100})
    assert aq.status_code == 200, aq.text
    fin = client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={})
    assert fin.status_code == 200, fin.text
    r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "completed"})
    assert r.status_code == 200, r.text
    t = client.post("/api/batch-tanks", headers=admin_h,
                    json={"batch_ids": [batch_id], "tank_code": f"TANK-{suffix}"})
    assert t.status_code == 201, t.text
    tank_id = t.json()["tank_id"]
    bbt = client.post("/api/lines", headers=admin_h,
                      json={"code": f"BBT-{suffix}", "name": f"Tank thành phẩm {suffix}", "kind": "tank_bbt"})
    assert bbt.status_code == 201, bbt.text
    prod = next(p for p in client.get("/api/products", headers=admin_h).json()
               if p["product_id"] == product_id)
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": f"FLOT-{suffix}", "to_bbt": bbt.json()["code"],
        "sources": [{"source_type": "tank", "source_tank_id": tank_id}], "category": category,
        "beer_type_id": prod["beer_type_id"],
    })
    assert draw.status_code == 201, draw.text
    filter_lot_id = draw.json()["filter_lot_id"]
    src = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()[0]
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    finfl = client.put(f"/api/batch-filter-lots/batches/{batches[0]['batch_link_id']}/finish", headers=admin_h,
                       json={"draws": [{"source_link_id": src["link_id"], "dich_nha_hl": dich_nha_hl}],
                            "nuoc_bai_khi_hl": 0})
    assert finfl.status_code == 200, finfl.text
    pack = client.post(f"/api/batch-filter-lots/{filter_lot_id}/pack-lots", headers=admin_h,
                       json={"qty": pack_qty, "pack_lot_code": f"PKG-{suffix}", "lot_no": f"LOT-{suffix}",
                             "pack_date": pack_date_iso})
    assert pack.status_code == 201, pack.text
    return {"batch_id": batch_id, "product_id": product_id, "filter_lot_id": filter_lot_id}


def test_overall_yield_and_norms_report(client, admin_h):
    built = _build_full_batch_chain(client, admin_h, "NORM01", "2031-08-01T08:00:00+00:00",
                                    dich_nha_hl=21, pack_qty=2100, category="Bia lon test norm",
                                    pack_date_iso="2031-08-15T10:00:00+00:00")
    prod = next(p for p in client.get("/api/products", headers=admin_h).json()
               if p["product_id"] == built["product_id"])
    # PUT thay thế TOÀN BỘ ProductIn — PHẢI giữ nguyên beer_type_id (và các field khác), nếu
    # không sẽ bị xóa về None (bug thật gặp phải: làm mất beer_type_id khiến TEST SAU dùng cùng
    # product không còn suy được Loại bia khi tạo lô lọc -> 409 "Chưa chọn Loại bia").
    upd = client.put(f"/api/products/{built['product_id']}", headers=admin_h, json={
        "code": prod["code"], "name": prod["name"], "uom": prod["uom"],
        "ferment_days_std": prod["ferment_days_std"], "beer_type_id": prod["beer_type_id"],
        "v_dich_norm_hl": 20, "energy_norm_kwh_per_hl": 5.0,
    })
    assert upd.status_code == 200, upd.text

    r = client.get("/api/reports/overall-yield-and-norms", headers=admin_h,
                   params={"year": 2031, "month": 8})
    assert r.status_code == 200, r.text
    rep = r.json()

    assert rep["overall_yield"]["output_l"] == 2100
    assert rep["overall_yield"]["yield_pct"] == 100.0

    row = next(i for i in rep["v_dich_by_product"] if i["batch_count"] == 1
              and i["avg_v_dich_per_batch_hl"] == 21)
    assert row["v_dich_norm_hl"] == 20
    assert row["pct_of_norm"] == round(21 / 20 * 100, 2)

    # Chưa cấu hình kết nối CSDL điện ngoài trong DB test -> actual_kwh phải None kèm lỗi, nhưng
    # norm_kwh_per_hl (tính từ Product, không cần CSDL ngoài) vẫn phải có giá trị.
    assert rep["energy"]["norm_kwh_per_hl"] == 5.0
    assert rep["energy"]["actual_kwh"] is None
    assert rep["energy"]["error"] is not None


def test_energy_actual_uses_total_packed_output_not_narrow_yield_output(client, admin_h, monkeypatch):
    """kWh/hl thực tế PHẢI chia cho TỔNG sản lượng chiết ra trong tháng (mọi lô thành phẩm có
    pack_date trong tháng), KHÔNG phải overall_yield["output_l"] (chỉ tính lô lọc đã chiết HẾT —
    tập con hẹp hơn) — bug đã phát hiện khi test UI live cho ra 22.742 kWh/hl vô lý (lấy nhầm mẫu
    số hẹp) và đã fix trong overall_yield_and_norms_report()."""
    _build_full_batch_chain(client, admin_h, "NORM02FULL", "2031-09-01T08:00:00+00:00",
                            dich_nha_hl=21, pack_qty=2100, category="Bia lon test norm2",
                            pack_date_iso="2031-09-10T10:00:00+00:00")
    # Lô thứ 2: CHƯA rút hết (on_hand > 0) -> KHÔNG được tính vào overall_yield["output_l"]
    # (mirror test_production_reports.py::test_pack_output_by_category_partial_drain_excluded...),
    # nhưng VẪN phải cộng vào tổng sản lượng chiết ra dùng làm mẫu số năng lượng.
    _build_full_batch_chain(client, admin_h, "NORM02PARTIAL", "2031-09-02T08:00:00+00:00",
                            dich_nha_hl=30, pack_qty=1000, category="Bia lon test norm2 partial",
                            pack_date_iso="2031-09-11T10:00:00+00:00")

    from app.services import energy_external
    monkeypatch.setattr(energy_external, "electricity_report",
                        lambda db, start, end: {"total_station": 310000.0})

    r = client.get("/api/reports/overall-yield-and-norms", headers=admin_h,
                   params={"year": 2031, "month": 9})
    assert r.status_code == 200, r.text
    rep = r.json()

    assert rep["overall_yield"]["output_l"] == 2100   # chỉ lô đã chiết hết — KHÔNG gồm lô partial
    total_output_hl = (2100 + 1000) / 100.0            # mẫu số ĐÚNG phải gồm CẢ 2 lô
    assert rep["energy"]["actual_kwh"] == 310000.0
    assert rep["energy"]["actual_kwh_per_hl"] == round(310000.0 / total_output_hl, 4)
