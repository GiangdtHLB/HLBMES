"""Test Lô thành phẩm (Mẻ SX) nhập kho thành phẩm (WMS) — thay thế vai trò của
routers/brewing.py::approve_bottle (module Nấu-Lọc-Chiết cũ, đã THÁO khỏi WMS, xem docstring
hiện tại của approve_bottle). services/batch_pipeline.py::release_pack_lot_to_wms là nơi DUY
NHẤT còn tạo FinishedGoodsUnit từ sản xuất — mirror đúng mechanics của _create_units (1 dòng/
lô bất kể ca lớn cỡ nào, quy đổi vỉ/keg qua pack_size) mà trước đây được test qua approve_bottle.
"""

import os
import tempfile

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["MES_DATABASE_URL"] = f"sqlite:///{_TMP.name}"
os.environ["MES_DEV_HEADER_AUTH"] = "0"
os.environ["MES_RL_ENABLED"] = "0"
os.environ["MES_ADMIN_PASSWORD"] = "AdminTest123"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import seed as seed_mod


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


def _make_batch(client, admin_h, batch_code):
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(v for v in vers if v["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                          "batch_code": batch_code, "planned_qty": 1000, "allow_shortage": True})
    assert b.status_code == 201, b.text
    return b.json()["batch_id"]


def _make_bbt_line(client, admin_h, suffix):
    r = client.post("/api/lines", headers=admin_h,
                    json={"code": f"BBT-{suffix}", "name": f"Tank thành phẩm {suffix}", "kind": "tank_bbt"})
    assert r.status_code == 201, r.text
    return r.json()["code"]


def _run_batch_to_completed(client, admin_h, batch_id, actual_qty=None):
    for target in ("ready", "running"):
        r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": target})
        assert r.status_code == 200, r.text
    if actual_qty is None:
        actual_qty = client.get(f"/api/batches/{batch_id}", headers=admin_h).json()["planned_qty"]
    aq = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": actual_qty})
    assert aq.status_code == 200, aq.text
    fin = client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={})
    assert fin.status_code == 200, fin.text
    r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "completed"})
    assert r.status_code == 200, r.text
    return r.json()


def _finish_source(client, admin_h, source, dich_nha_hl, nuoc_bai_khi_hl=0):
    """1 mẻ lọc tự có sẵn 1 khoản rút (draw) cho MỖI nguồn ngay lúc tạo lô lọc — "Kết thúc" tức
    là kết thúc mẻ đó, khai V dịch nha cho khoản rút của nguồn này. `source` là dict trả về từ
    GET .../sources (cần cả filter_lot_id lẫn link_id)."""
    batches = client.get(f"/api/batch-filter-lots/{source['filter_lot_id']}/batches", headers=admin_h).json()
    batch_link_id = batches[-1]["batch_link_id"]
    return client.put(f"/api/batch-filter-lots/batches/{batch_link_id}/finish", headers=admin_h,
                      json={"draws": [{"source_link_id": source["link_id"], "dich_nha_hl": dich_nha_hl}],
                           "nuoc_bai_khi_hl": nuoc_bai_khi_hl})


def _build_pack_lot(client, admin_h, suffix, fp_payload=None, ca1=10, ca2=0, ca3=0, v_drawn=900):
    """mẻ nấu -> tank -> lô lọc duyệt KCS -> lô thành phẩm đã Duyệt KCS + khai SL theo ca,
    SẴN SÀNG để release_pack_lot_to_wms. Trả về pack_lot_id."""
    fp_id = None
    if fp_payload:
        fp = client.post("/api/finished-products", headers=admin_h,
                         json={**fp_payload, "code": f"SKU-{suffix}"})
        assert fp.status_code == 201, fp.text
        fp_id = fp.json()["finished_product_id"]

    batch_id = _make_batch(client, admin_h, None)
    _run_batch_to_completed(client, admin_h, batch_id)
    tank = client.post("/api/batch-tanks", headers=admin_h,
                       json={"batch_ids": [batch_id], "tank_code": f"TANK-PKWMS-{suffix}"})
    assert tank.status_code == 201, tank.text
    to_bbt = _make_bbt_line(client, admin_h, suffix)
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": f"FLOT-PKWMS-{suffix}", "to_bbt": to_bbt,
        "sources": [{"source_type": "tank", "source_tank_id": tank.json()["tank_id"]}],
    })
    assert draw.status_code == 201, draw.text
    filter_lot_id = draw.json()["filter_lot_id"]
    src = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()[0]
    fin = _finish_source(client, admin_h, src, v_drawn)
    assert fin.status_code == 200, fin.text
    appr = client.post(f"/api/batch-filter-lots/{filter_lot_id}/approve", headers=admin_h)
    assert appr.status_code == 200, appr.text

    pack = client.post("/api/batch-pack-lots", headers=admin_h, json={
        "from_bbt": to_bbt, "qty": 1000, "pack_lot_code": f"PKG-PKWMS-{suffix}",
        "lot_no": f"LOT-PKWMS-{suffix}", "finished_product_id": fp_id,
    })
    assert pack.status_code == 201, pack.text
    pack_lot_id = pack.json()["pack_lot_id"]

    shifts = client.put(f"/api/batch-pack-lots/{pack_lot_id}/shifts", headers=admin_h,
                        json={"ca1_qty": ca1, "ca2_qty": ca2, "ca3_qty": ca3})
    assert shifts.status_code == 200, shifts.text

    approve = client.post(f"/api/batch-pack-lots/{pack_lot_id}/approve", headers=admin_h)
    assert approve.status_code == 200, approve.text
    return pack_lot_id, fp_id


def test_release_creates_one_row_regardless_of_ca_count(client, admin_h):
    """Ca 1/2/3 tính theo VỈ (đơn vị đóng gói), không phải lon rời — release_pack_lot_to_wms
    luôn sinh ĐÚNG 1 dòng lô duy nhất bất kể ca1 lớn cỡ nào (mirror _create_units, trước đây
    test qua approve_bottle — xem docs/WMS-LOT-LEVEL-REDESIGN.md)."""
    pack_lot_id, fp_id = _build_pack_lot(
        client, admin_h, "ROW01", {"name": "SKU vi test", "uom": "lon", "unit_type": "vi", "pack_size": 24},
        ca1=100)
    release = client.post(f"/api/batch-pack-lots/{pack_lot_id}/release-to-wms", headers=admin_h)
    assert release.status_code == 200, release.text
    result = release.json()
    assert result["unit_type"] == "vi"
    assert result["count"] == 100   # 100 vỉ thật, dù chỉ 1 dòng DB

    units = client.get("/api/wms/units", headers=admin_h).json()
    made = [u for u in units if u["unit_code"] in result["unit_codes"]]
    assert len(made) == 1
    assert made[0]["quantity"] == 2400   # 100 vỉ x 24 lon/vỉ
    assert made[0]["status"] == "stored"

    p = client.get(f"/api/batch-pack-lots/{pack_lot_id}", headers=admin_h).json()
    assert p["stocked"] is True and p["stocked_by"] == "admin"


def test_release_creates_keg_one_row(client, admin_h):
    pack_lot_id, _ = _build_pack_lot(
        client, admin_h, "KEG01", {"name": "SKU keg test", "uom": "lít", "unit_type": "keg", "pack_size": 1},
        ca1=10)
    release = client.post(f"/api/batch-pack-lots/{pack_lot_id}/release-to-wms", headers=admin_h)
    assert release.status_code == 200, release.text
    assert release.json()["unit_type"] == "keg"
    assert release.json()["count"] == 10

    units = client.get("/api/wms/units", headers=admin_h).json()
    made = [u for u in units if u["unit_code"] in release.json()["unit_codes"]]
    assert len(made) == 1 and made[0]["unit_type"] == "keg" and made[0]["quantity"] == 10


def test_release_blocked_until_approved_and_ca_declared(client, admin_h):
    batch_id = _make_batch(client, admin_h, None)
    _run_batch_to_completed(client, admin_h, batch_id)
    tank = client.post("/api/batch-tanks", headers=admin_h,
                       json={"batch_ids": [batch_id], "tank_code": "TANK-PKWMS-GATE"})
    to_bbt = _make_bbt_line(client, admin_h, "GATE")
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": "FLOT-PKWMS-GATE", "to_bbt": to_bbt,
        "sources": [{"source_type": "tank", "source_tank_id": tank.json()["tank_id"]}],
    })
    filter_lot_id = draw.json()["filter_lot_id"]
    src = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()[0]
    _finish_source(client, admin_h, src, 900)
    client.post(f"/api/batch-filter-lots/{filter_lot_id}/approve", headers=admin_h)

    pack = client.post("/api/batch-pack-lots", headers=admin_h, json={
        "from_bbt": to_bbt, "qty": 500, "pack_lot_code": "PKG-PKWMS-GATE", "lot_no": "LOT-PKWMS-GATE"})
    pack_lot_id = pack.json()["pack_lot_id"]

    not_approved = client.post(f"/api/batch-pack-lots/{pack_lot_id}/release-to-wms", headers=admin_h)
    assert not_approved.status_code == 409, not_approved.text

    approve = client.post(f"/api/batch-pack-lots/{pack_lot_id}/approve", headers=admin_h)
    assert approve.status_code == 200, approve.text

    no_ca = client.post(f"/api/batch-pack-lots/{pack_lot_id}/release-to-wms", headers=admin_h)
    assert no_ca.status_code == 409, no_ca.text

    client.put(f"/api/batch-pack-lots/{pack_lot_id}/shifts", headers=admin_h, json={"ca1_qty": 5})
    ok = client.post(f"/api/batch-pack-lots/{pack_lot_id}/release-to-wms", headers=admin_h)
    assert ok.status_code == 200, ok.text

    dup = client.post(f"/api/batch-pack-lots/{pack_lot_id}/release-to-wms", headers=admin_h)
    assert dup.status_code == 409, dup.text


def test_release_requires_production_release_to_wms_permission(client, admin_h, vanhanh_h):
    pack_lot_id, _ = _build_pack_lot(client, admin_h, "PERM01", ca1=5)
    forbidden = client.post(f"/api/batch-pack-lots/{pack_lot_id}/release-to-wms", headers=vanhanh_h)
    assert forbidden.status_code == 403, forbidden.text


def test_delete_unit_resets_pack_lot_stocked_flag(client, admin_h):
    pack_lot_id, _ = _build_pack_lot(client, admin_h, "UNLOCK01", ca1=3)
    release = client.post(f"/api/batch-pack-lots/{pack_lot_id}/release-to-wms", headers=admin_h)
    assert release.status_code == 200, release.text
    unit_code = release.json()["unit_codes"][0]
    units = client.get("/api/wms/units", headers=admin_h).json()
    unit_id = next(u["unit_id"] for u in units if u["unit_code"] == unit_code)

    p_before = client.get(f"/api/batch-pack-lots/{pack_lot_id}", headers=admin_h).json()
    assert p_before["stocked"] is True

    deleted = client.delete(f"/api/wms/units/{unit_id}", headers=admin_h)
    assert deleted.status_code == 204, deleted.text

    p_after = client.get(f"/api/batch-pack-lots/{pack_lot_id}", headers=admin_h).json()
    assert p_after["stocked"] is False


def test_delete_units_batch_resets_pack_lot_stocked_flag(client, admin_h):
    """Xóa cả lô (1 dòng duy nhất dù ca lớn) qua /wms/units/delete-batch cũng phải mở khóa lại
    lô thành phẩm nguồn — mirror test_delete_unit_resets_pack_lot_stocked_flag nhưng qua
    services/wms.py::delete_units."""
    pack_lot_id, _ = _build_pack_lot(client, admin_h, "UNLOCKBATCH01", ca1=100)
    release = client.post(f"/api/batch-pack-lots/{pack_lot_id}/release-to-wms", headers=admin_h)
    assert release.status_code == 200, release.text
    unit_codes = release.json()["unit_codes"]
    units = client.get("/api/wms/units", headers=admin_h).json()
    unit_ids = [u["unit_id"] for u in units if u["unit_code"] in unit_codes]
    assert len(unit_ids) == 1

    deleted = client.post("/api/wms/units/delete-batch", headers=admin_h, json={"unit_ids": unit_ids})
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] == 1

    p_after = client.get(f"/api/batch-pack-lots/{pack_lot_id}", headers=admin_h).json()
    assert p_after["stocked"] is False


def test_wms_units_show_pack_lot_code_as_bottle_code(client, admin_h):
    """"Mã chiết" (bottle_codes) ở Kho TP trước đây LUÔN trống cho hàng nhập từ pipeline "Mẻ SX"
    (release_pack_lot_to_wms không tạo BottleRecord nên join theo BottleRecord.lot_no không bao
    giờ khớp) — giờ phải hiện đúng BatchPackLot.pack_lot_code, cả ở danh sách từng đơn vị
    (GET /wms/units) lẫn bảng tổng hợp theo lô (GET /wms/units/by-lot), yêu cầu người dùng
    2026-09-01: Mã chiết = mã của lô TP."""
    pack_lot_id, _ = _build_pack_lot(client, admin_h, "BCODE01", ca1=10)
    pack = client.get(f"/api/batch-pack-lots/{pack_lot_id}", headers=admin_h).json()
    release = client.post(f"/api/batch-pack-lots/{pack_lot_id}/release-to-wms", headers=admin_h)
    assert release.status_code == 200, release.text

    units = client.get("/api/wms/units", headers=admin_h).json()
    made = next(u for u in units if u["unit_code"] in release.json()["unit_codes"])
    assert made["bottle_codes"] == [pack["pack_lot_code"]]

    by_lot = client.get("/api/wms/units/by-lot", headers=admin_h).json()
    row = next(r for r in by_lot if r["lot_code"] == pack["lot_no"])
    assert row["bottle_codes"] == [pack["pack_lot_code"]]


def test_pack_lot_rejects_duplicate_lot_no_same_year(client, admin_h):
    """Số lô bia (lot_no) là số lô GMP thật in trên bao bì — PHẢI duy nhất trong cùng 1 năm,
    mirror đúng quy ước (năm, mã) đã áp cho pack_lot_code/filter_lot_code/batch_code (yêu cầu
    người dùng 2026-09-01: 2 lô thành phẩm khác nhau đã lỡ trùng cùng "Số lô bia")."""
    pack_lot_id, _ = _build_pack_lot(client, admin_h, "DUPLOT1", ca1=5)
    dup_lot_no = client.get(f"/api/batch-pack-lots/{pack_lot_id}", headers=admin_h).json()["lot_no"]

    batch_id = _make_batch(client, admin_h, None)
    _run_batch_to_completed(client, admin_h, batch_id)
    tank = client.post("/api/batch-tanks", headers=admin_h,
                       json={"batch_ids": [batch_id], "tank_code": "TANK-PKWMS-DUPLOT2"})
    to_bbt = _make_bbt_line(client, admin_h, "DUPLOT2")
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": "FLOT-PKWMS-DUPLOT2", "to_bbt": to_bbt,
        "sources": [{"source_type": "tank", "source_tank_id": tank.json()["tank_id"]}],
    })
    filter_lot_id = draw.json()["filter_lot_id"]
    src = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()[0]
    _finish_source(client, admin_h, src, 900)
    client.post(f"/api/batch-filter-lots/{filter_lot_id}/approve", headers=admin_h)

    dup = client.post("/api/batch-pack-lots", headers=admin_h, json={
        "from_bbt": to_bbt, "qty": 500, "pack_lot_code": "PKG-PKWMS-DUPLOT2", "lot_no": dup_lot_no})
    assert dup.status_code == 409, dup.text
    assert "duy nhất" in dup.json()["detail"]

    ok = client.post("/api/batch-pack-lots", headers=admin_h, json={
        "from_bbt": to_bbt, "qty": 500, "pack_lot_code": "PKG-PKWMS-DUPLOT3", "lot_no": dup_lot_no + "-B"})
    assert ok.status_code == 201, ok.text
