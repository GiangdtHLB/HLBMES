"""Test Lô thành phẩm (Mẻ SX) nhập kho thành phẩm (WMS, hệ pallet/case) — thay thế vai trò của
routers/brewing.py::approve_bottle (module Nấu-Lọc-Chiết cũ, đã THÁO khỏi WMS, xem docstring
hiện tại của approve_bottle).

MỖI DÒNG phân bổ (quy cách đóng gói) có nút "Duyệt nhập kho TP" RIÊNG (yêu cầu người dùng
2026-09-20: "Mỗi quy cách sẽ có 1 nút duyệt nhập kho TP") — 2 hành động tách biệt:
- save_pack_lot_allocations (PUT .../pack-allocations, quyền batch.execute) — nhân viên chiết
  khai/lưu phân bổ NGAY trong lúc chiết, không chờ Duyệt KCS. Lưu lại saved_by/saved_at cho
  TỪNG dòng.
- release_pack_lot_allocation (POST .../pack-allocations/{row_id}/release, quyền
  production.release_to_wms) — Giám đốc/Phó GĐ SX duyệt nhập kho CHO ĐÚNG 1 dòng, vẫn phải chờ
  đã Duyệt KCS (p.approved). Lưu lại released_by/released_at cho dòng đó, tạo đúng số Pallet
  thật theo quy cách (case_count = units_per_pallet, + 1 pallet lẻ nếu còn dư). Dòng đã release
  là bất biến — không sửa/xóa được nữa.
`unstocked_remainder` (BatchPackLot property) = SL theo ca - tổng SL các dòng ĐÃ release — dùng
để cảnh báo "còn vỉ/két chưa được duyệt nhập kho thành phẩm".
Xem services/wms.py::_build_pallet.
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


@pytest.fixture(scope="module")
def kcs_h(client):
    return _login(client, "kcs", "123456")


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


def _make_sku(client, admin_h, suffix, unit_type="vi", pack_size=24):
    fp = client.post("/api/finished-products", headers=admin_h,
                     json={"name": f"SKU test {suffix}", "code": f"SKU-{suffix}",
                          "uom": "lon", "unit_type": unit_type, "pack_size": pack_size})
    assert fp.status_code == 201, fp.text
    return fp.json()["finished_product_id"]


def _make_spec(client, admin_h, fp_id, code, units_per_pallet, layers=None):
    r = client.post("/api/packing-specs", headers=admin_h,
                    json={"code": code, "name": code, "finished_product_id": fp_id,
                         "units_per_pallet": units_per_pallet, "layers": layers})
    assert r.status_code == 201, r.text
    return r.json()["spec_id"]


def _save_allocations(client, headers, pack_lot_id, allocations):
    return client.put(f"/api/batch-pack-lots/{pack_lot_id}/pack-allocations", headers=headers,
                      json={"allocations": allocations})


def _make_location(client, admin_h, suffix, capacity=50):
    r = client.post("/api/wms/locations", headers=admin_h,
                    json={"code": f"LOC-{suffix}", "name": f"Vị trí {suffix}", "capacity": capacity})
    assert r.status_code == 201, r.text
    return r.json()["loc_id"]


def _release_row(client, headers, pack_lot_id, row_id, loc_id):
    return client.post(f"/api/batch-pack-lots/{pack_lot_id}/pack-allocations/{row_id}/release",
                       headers=headers, json={"loc_id": loc_id})


def _row_id_for_spec(pack_lot, spec_id):
    return next(r["row_id"] for r in pack_lot["pack_allocations"] if r["spec_id"] == spec_id)


def _build_pack_lot(client, admin_h, suffix, fp_id, ca1=10, ca2=0, ca3=0, v_drawn=900, approve=True):
    """mẻ nấu -> tank -> lô lọc duyệt KCS -> lô thành phẩm + khai SL theo ca, SẴN SÀNG để lưu
    phân bổ/nhập kho. `approve=True` cũng Duyệt KCS lô TP luôn. Trả về pack_lot_id."""
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
        "lot_no": f"LOT-PKWMS-{suffix}", "finished_product_id": fp_id, "line": "CL01",
    })
    assert pack.status_code == 201, pack.text
    pack_lot_id = pack.json()["pack_lot_id"]

    shifts = client.put(f"/api/batch-pack-lots/{pack_lot_id}/shifts", headers=admin_h,
                        json={"ca1_qty": ca1, "ca2_qty": ca2, "ca3_qty": ca3})
    assert shifts.status_code == 200, shifts.text

    if approve:
        approve_r = client.post(f"/api/batch-pack-lots/{pack_lot_id}/approve", headers=admin_h)
        assert approve_r.status_code == 200, approve_r.text
    return pack_lot_id


def test_release_row_creates_full_and_remainder_pallets_and_stamps_who(client, admin_h):
    """110 vỉ/pallet, khai 250 vỉ trong 1 dòng -> 2 pallet đầy (110) + 1 pallet lẻ (30). Lưu lại
    đúng saved_by lúc lưu và released_by lúc duyệt nhập kho cho dòng đó."""
    fp_id = _make_sku(client, admin_h, "ROW01")
    spec_id = _make_spec(client, admin_h, fp_id, "QC01", 110, layers=10)
    pack_lot_id = _build_pack_lot(client, admin_h, "ROW01", fp_id, ca1=250)

    loc_id = _make_location(client, admin_h, "ROW01")
    saved = _save_allocations(client, admin_h, pack_lot_id, [{"spec_id": spec_id, "quantity": 250}])
    assert saved.status_code == 200, saved.text
    row = saved.json()["pack_allocations"][0]
    assert row["saved_by"] == "admin" and row["released"] is False
    assert saved.json()["unstocked_remainder"] == 250

    release = _release_row(client, admin_h, pack_lot_id, row["row_id"], loc_id)
    assert release.status_code == 200, release.text
    result = release.json()
    assert len(result["pallet_codes"]) == 3
    assert result["stocked"] is True
    assert result["location"] == "LOC-ROW01"

    p = client.get(f"/api/batch-pack-lots/{pack_lot_id}", headers=admin_h).json()
    released_row = p["pack_allocations"][0]
    assert released_row["released"] is True and released_row["released_by"] == "admin"
    assert released_row["location"] == "LOC-ROW01"
    assert p["stocked"] is True and p["stocked_by"] == "admin"
    assert p["unstocked_remainder"] == 0

    pallets = client.get("/api/wms/pallets", headers=admin_h).json()
    made = [pl for pl in pallets if pl["pallet_code"] in result["pallet_codes"]]
    case_counts = sorted(pl["case_count"] for pl in made)
    assert case_counts == [30, 110, 110]
    for pl in made:
        assert pl["units_per_case"] == 24
        assert pl["status"] == "stored"
        assert pl["location"] == "LOC-ROW01"


def test_each_row_has_independent_release_button_and_remainder_warning(client, admin_h):
    """2 dòng (2 quy cách khác nhau) — duyệt nhập kho từng dòng RIÊNG, cảnh báo còn thiếu giảm
    dần đúng theo từng lần duyệt (yêu cầu người dùng 2026-09-20)."""
    fp_id = _make_sku(client, admin_h, "ROW02", unit_type="keg", pack_size=1)
    spec_a = _make_spec(client, admin_h, fp_id, "QC-A", 100)
    spec_b = _make_spec(client, admin_h, fp_id, "QC-B", 110)
    pack_lot_id = _build_pack_lot(client, admin_h, "ROW02", fp_id, ca1=100, ca2=110)

    loc_id = _make_location(client, admin_h, "ROW02")
    saved = _save_allocations(client, admin_h, pack_lot_id,
                              [{"spec_id": spec_a, "quantity": 100}, {"spec_id": spec_b, "quantity": 110}])
    assert saved.status_code == 200, saved.text
    row_a = _row_id_for_spec(saved.json(), spec_a)
    row_b = _row_id_for_spec(saved.json(), spec_b)
    assert saved.json()["unstocked_remainder"] == 210

    release_a = _release_row(client, admin_h, pack_lot_id, row_a, loc_id)
    assert release_a.status_code == 200, release_a.text
    assert release_a.json()["stocked"] is False   # còn dòng B chưa duyệt

    mid = client.get(f"/api/batch-pack-lots/{pack_lot_id}", headers=admin_h).json()
    assert mid["unstocked_remainder"] == 110
    assert mid["stocked"] is False

    release_b = _release_row(client, admin_h, pack_lot_id, row_b, loc_id)
    assert release_b.status_code == 200, release_b.text
    assert release_b.json()["stocked"] is True

    done = client.get(f"/api/batch-pack-lots/{pack_lot_id}", headers=admin_h).json()
    assert done["unstocked_remainder"] == 0
    assert done["stocked"] is True

    pallets = client.get("/api/wms/pallets", headers=admin_h).json()
    codes = release_a.json()["pallet_codes"] + release_b.json()["pallet_codes"]
    made = [pl for pl in pallets if pl["pallet_code"] in codes]
    assert sorted(pl["case_count"] for pl in made) == [100, 110]


def test_pallets_endpoint_filters_by_lot_code(client, admin_h):
    """`GET /wms/pallets?lot_code=...` (thêm 2026-09-25 cho trang chi tiết Lô thành phẩm — tóm tắt
    "đã đóng bao nhiêu pallet theo từng số vỉ") CHỈ trả đúng pallet của lô đó, không lẫn pallet
    của lô KHÁC (khác lot_no) dù cùng SKU/cùng thời điểm."""
    fp_id = _make_sku(client, admin_h, "LOTFILTER", unit_type="keg", pack_size=1)
    spec_a = _make_spec(client, admin_h, fp_id, "QC-A", 100)
    spec_b = _make_spec(client, admin_h, fp_id, "QC-B", 110)
    loc_id = _make_location(client, admin_h, "LOTFILTER")

    pack_lot_1 = _build_pack_lot(client, admin_h, "LOTFILTER1", fp_id, ca1=100)
    saved1 = _save_allocations(client, admin_h, pack_lot_1, [{"spec_id": spec_a, "quantity": 100}])
    row1 = saved1.json()["pack_allocations"][0]["row_id"]
    rel1 = _release_row(client, admin_h, pack_lot_1, row1, loc_id)
    assert rel1.status_code == 200, rel1.text

    pack_lot_2 = _build_pack_lot(client, admin_h, "LOTFILTER2", fp_id, ca1=110)
    saved2 = _save_allocations(client, admin_h, pack_lot_2, [{"spec_id": spec_b, "quantity": 110}])
    row2 = saved2.json()["pack_allocations"][0]["row_id"]
    rel2 = _release_row(client, admin_h, pack_lot_2, row2, loc_id)
    assert rel2.status_code == 200, rel2.text

    p1 = client.get(f"/api/batch-pack-lots/{pack_lot_1}", headers=admin_h).json()
    lot_code_1 = p1["lot_no"] or p1["pack_lot_code"]

    filtered = client.get("/api/wms/pallets", headers=admin_h, params={"lot_code": lot_code_1}).json()
    assert filtered, filtered
    assert all(pl["lot_code"] == lot_code_1 for pl in filtered)
    codes_1 = set(rel1.json()["pallet_codes"])
    codes_2 = set(rel2.json()["pallet_codes"])
    returned_codes = {pl["pallet_code"] for pl in filtered}
    assert returned_codes == codes_1
    assert not (returned_codes & codes_2)


def test_release_row_blocked_until_kcs_approved(client, admin_h):
    fp_id = _make_sku(client, admin_h, "NOAPPROVE")
    spec_id = _make_spec(client, admin_h, fp_id, "QC01", 110)
    pack_lot_id = _build_pack_lot(client, admin_h, "NOAPPROVE", fp_id, ca1=110, approve=False)

    loc_id = _make_location(client, admin_h, "NOAPPROVE")
    saved = _save_allocations(client, admin_h, pack_lot_id, [{"spec_id": spec_id, "quantity": 110}])
    assert saved.status_code == 200, saved.text
    row_id = saved.json()["pack_allocations"][0]["row_id"]

    blocked = _release_row(client, admin_h, pack_lot_id, row_id, loc_id)
    assert blocked.status_code == 409, blocked.text
    assert "Duyệt KCS" in blocked.json()["detail"]

    approve = client.post(f"/api/batch-pack-lots/{pack_lot_id}/approve", headers=admin_h)
    assert approve.status_code == 200, approve.text

    release = _release_row(client, admin_h, pack_lot_id, row_id, loc_id)
    assert release.status_code == 200, release.text


def test_release_row_blocked_when_already_released(client, admin_h):
    fp_id = _make_sku(client, admin_h, "DUPROW")
    spec_id = _make_spec(client, admin_h, fp_id, "QC01", 110)
    pack_lot_id = _build_pack_lot(client, admin_h, "DUPROW", fp_id, ca1=110)
    loc_id = _make_location(client, admin_h, "DUPROW")
    saved = _save_allocations(client, admin_h, pack_lot_id, [{"spec_id": spec_id, "quantity": 110}])
    row_id = saved.json()["pack_allocations"][0]["row_id"]

    ok = _release_row(client, admin_h, pack_lot_id, row_id, loc_id)
    assert ok.status_code == 200, ok.text

    dup = _release_row(client, admin_h, pack_lot_id, row_id, loc_id)
    assert dup.status_code == 409, dup.text


def test_release_row_not_found(client, admin_h):
    fp_id = _make_sku(client, admin_h, "NOROW")
    loc_id = _make_location(client, admin_h, "NOROW")
    pack_lot_id = _build_pack_lot(client, admin_h, "NOROW", fp_id, ca1=110)
    missing = _release_row(client, admin_h, pack_lot_id, "not-a-real-row-id", loc_id)
    assert missing.status_code == 404, missing.text


def test_release_row_requires_loc_id(client, admin_h):
    fp_id = _make_sku(client, admin_h, "NOLOC")
    spec_id = _make_spec(client, admin_h, fp_id, "QC01", 110)
    pack_lot_id = _build_pack_lot(client, admin_h, "NOLOC", fp_id, ca1=110)
    saved = _save_allocations(client, admin_h, pack_lot_id, [{"spec_id": spec_id, "quantity": 110}])
    row_id = saved.json()["pack_allocations"][0]["row_id"]

    missing_loc = client.post(f"/api/batch-pack-lots/{pack_lot_id}/pack-allocations/{row_id}/release",
                              headers=admin_h, json={"loc_id": ""})
    assert missing_loc.status_code == 409, missing_loc.text
    assert "vị trí kho" in missing_loc.json()["detail"]

    bad_loc = _release_row(client, admin_h, pack_lot_id, row_id, "not-a-real-loc-id")
    assert bad_loc.status_code == 404, bad_loc.text


def test_release_row_blocked_when_location_full(client, admin_h):
    fp_id = _make_sku(client, admin_h, "LOCFULL")
    spec_id = _make_spec(client, admin_h, fp_id, "QC01", 100)
    loc_id = _make_location(client, admin_h, "LOCFULL", capacity=1)
    pack_lot_id = _build_pack_lot(client, admin_h, "LOCFULL", fp_id, ca1=150)
    saved = _save_allocations(client, admin_h, pack_lot_id, [{"spec_id": spec_id, "quantity": 150}])
    row_id = saved.json()["pack_allocations"][0]["row_id"]

    # 150 vỉ / 100 mỗi pallet -> 2 pallet (1 đầy + 1 lẻ), vị trí chỉ chứa được 1 -> chặn, không
    # tạo pallet nào cả (kiểm tra trước, xuất sau).
    blocked = _release_row(client, admin_h, pack_lot_id, row_id, loc_id)
    assert blocked.status_code == 409, blocked.text
    assert "không đủ chỗ" in blocked.json()["detail"]

    p = client.get(f"/api/batch-pack-lots/{pack_lot_id}", headers=admin_h).json()
    assert p["pack_allocations"][0]["released"] is False


def test_release_row_blocked_when_pallet_count_absurdly_high(client, admin_h):
    """Nhập nhầm số lượng (vd. dư số 0) có thể sinh ra hàng nghìn pallet trong 1 lần duyệt —
    mỗi pallet là 1 db.commit() riêng nên số lượng lớn khiến request treo/timeout, trả về lỗi
    500 khó hiểu thay vì thông báo rõ ràng (lỗi thật gặp khi test 2026-09-20: duyệt 1 dòng
    300.000 vỉ / 100 vỉ mỗi pallet = 3000 pallet). Chặn sớm, không tạo pallet nào."""
    fp_id = _make_sku(client, admin_h, "HUGEQTY")
    spec_id = _make_spec(client, admin_h, fp_id, "QC01", 1)
    loc_id = _make_location(client, admin_h, "HUGEQTY", capacity=10000)
    pack_lot_id = _build_pack_lot(client, admin_h, "HUGEQTY", fp_id, ca1=501)
    saved = _save_allocations(client, admin_h, pack_lot_id, [{"spec_id": spec_id, "quantity": 501}])
    row_id = saved.json()["pack_allocations"][0]["row_id"]

    blocked = _release_row(client, admin_h, pack_lot_id, row_id, loc_id)
    assert blocked.status_code == 409, blocked.text
    assert "vượt quá" in blocked.json()["detail"]

    p = client.get(f"/api/batch-pack-lots/{pack_lot_id}", headers=admin_h).json()
    assert p["pack_allocations"][0]["released"] is False
    pallets = client.get("/api/wms/pallets", headers=admin_h).json()
    assert not any(pl["lot_code"] == p["lot_no"] for pl in pallets)


def test_save_cannot_modify_or_drop_released_row(client, admin_h):
    """Dòng đã Duyệt nhập kho (đã tạo pallet thật) là bất biến — không cho đổi spec/số lượng,
    và nếu client gửi thiếu dòng đó thì tự khôi phục lại nguyên trạng (không mất vết pallet)."""
    fp_id = _make_sku(client, admin_h, "IMMUT")
    spec_id = _make_spec(client, admin_h, fp_id, "QC01", 110)
    spec_other = _make_spec(client, admin_h, fp_id, "QC02", 50)
    pack_lot_id = _build_pack_lot(client, admin_h, "IMMUT", fp_id, ca1=110)
    loc_id = _make_location(client, admin_h, "IMMUT")
    saved = _save_allocations(client, admin_h, pack_lot_id, [{"spec_id": spec_id, "quantity": 110}])
    row_id = saved.json()["pack_allocations"][0]["row_id"]
    _release_row(client, admin_h, pack_lot_id, row_id, loc_id)

    tampered = _save_allocations(client, admin_h, pack_lot_id,
                                 [{"row_id": row_id, "spec_id": spec_id, "quantity": 999}])
    assert tampered.status_code == 409, tampered.text
    assert "không thể sửa" in tampered.json()["detail"]

    # Gửi thiếu dòng đã released (client cũ) — server tự khôi phục lại, không mất.
    dropped = _save_allocations(client, admin_h, pack_lot_id, [{"spec_id": spec_other, "quantity": 5}])
    assert dropped.status_code == 200, dropped.text
    rows = dropped.json()["pack_allocations"]
    assert any(r["row_id"] == row_id and r["released"] for r in rows)
    assert any(r["spec_id"] == spec_other for r in rows)


def test_release_row_blocked_when_spec_belongs_to_other_sku(client, admin_h):
    """Chặn ngay lúc LƯU (spec sai SKU không thể lưu được) — xác nhận vẫn giữ nguyên hành vi cũ."""
    fp_a = _make_sku(client, admin_h, "SKUA")
    fp_b = _make_sku(client, admin_h, "SKUB")
    spec_b = _make_spec(client, admin_h, fp_b, "QC-B", 110)
    pack_lot_id = _build_pack_lot(client, admin_h, "SKUA", fp_a, ca1=110)

    saved = _save_allocations(client, admin_h, pack_lot_id, [{"spec_id": spec_b, "quantity": 110}])
    assert saved.status_code == 409, saved.text
    assert "không thuộc SKU" in saved.json()["detail"]


def test_save_allocations_requires_batch_execute_permission(client, admin_h, kcs_h):
    """kcs chỉ có quyền quality.release, không có batch.execute (chỉ nhân viên vận hành/kỹ
    thuật mới khai được phân bổ đóng gói — mirror update_pack_lot_shifts)."""
    fp_id = _make_sku(client, admin_h, "PERMSAVE")
    spec_id = _make_spec(client, admin_h, fp_id, "QC01", 110)
    pack_lot_id = _build_pack_lot(client, admin_h, "PERMSAVE", fp_id, ca1=110)

    forbidden = _save_allocations(client, kcs_h, pack_lot_id, [{"spec_id": spec_id, "quantity": 110}])
    assert forbidden.status_code == 403, forbidden.text


def test_release_row_requires_production_release_to_wms_permission(client, admin_h, vanhanh_h):
    fp_id = _make_sku(client, admin_h, "PERM01")
    spec_id = _make_spec(client, admin_h, fp_id, "QC01", 110)
    pack_lot_id = _build_pack_lot(client, admin_h, "PERM01", fp_id, ca1=5)
    loc_id = _make_location(client, admin_h, "PERM01")
    saved = _save_allocations(client, admin_h, pack_lot_id, [{"spec_id": spec_id, "quantity": 5}])
    row_id = saved.json()["pack_allocations"][0]["row_id"]

    forbidden = _release_row(client, vanhanh_h, pack_lot_id, row_id, loc_id)
    assert forbidden.status_code == 403, forbidden.text


def test_pack_lot_rejects_duplicate_lot_no_same_year(client, admin_h):
    """Số lô bia (lot_no) là số lô GMP thật in trên bao bì — PHẢI duy nhất trong cùng 1 năm,
    mirror đúng quy ước (năm, mã) đã áp cho pack_lot_code/filter_lot_code/batch_code (yêu cầu
    người dùng 2026-09-01: 2 lô thành phẩm khác nhau đã lỡ trùng cùng "Số lô bia")."""
    fp_id = _make_sku(client, admin_h, "DUPLOT")
    pack_lot_id = _build_pack_lot(client, admin_h, "DUPLOT1", fp_id, ca1=5)
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
        "from_bbt": to_bbt, "qty": 500, "pack_lot_code": "PKG-PKWMS-DUPLOT2", "lot_no": dup_lot_no,
        "finished_product_id": fp_id, "line": "CL01"})
    assert dup.status_code == 409, dup.text
    assert "duy nhất" in dup.json()["detail"]

    ok = client.post("/api/batch-pack-lots", headers=admin_h, json={
        "from_bbt": to_bbt, "qty": 500, "pack_lot_code": "PKG-PKWMS-DUPLOT3", "lot_no": dup_lot_no + "-B",
        "finished_product_id": fp_id, "line": "CL01"})
    assert ok.status_code == 201, ok.text
