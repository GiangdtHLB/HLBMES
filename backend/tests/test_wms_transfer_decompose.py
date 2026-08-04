"""Test điều chuyển nội bộ, phân rã vỉ->lon, và trường shipment_type (khuyến mại/đổi
trả) trên phiếu xuất kho — các tính năng bổ sung trên nền FinishedGoodsUnit:
- Điều chuyển: đổi location_id hàng loạt, chặn khi đích đầy sức chứa, chặn unit đã xuất.
- Phân rã: vỉ -> N lon (quantity=1), vỉ gốc chuyển status="decomposed", lon kế thừa
  created_at của vỉ gốc, chặn phân rã keg/phân rã 2 lần/xóa vỉ đã phân rã.
- Xuất kho theo lon sau khi phân rã + trường shipment_type.
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
def thukho_h(client):
    return _login(client, "thukho", "123456")


def _ensure_finished_product(client, admin_h, suffix, pack_size, unit_type):
    """Đăng ký (hoặc tái dùng nếu đã có) danh mục SKU-{suffix} với đúng pack_size — cần thiết
    để _pack_divisor tra cứu đúng ở CẢ tầng tạo lẫn tầng tiêu thụ sau này (transfer/decompose/
    free-issue/shipment); nếu không đăng ký, sản phẩm "vô danh" sẽ rơi vào nhánh fallback=1
    của _pack_divisor, gây lệch quy đổi vỉ<->lon so với pack_size khai báo ở đây."""
    code = f"SKU-{suffix}"
    existing = client.get("/api/finished-products", headers=admin_h).json()
    found = next((fp for fp in existing if fp["code"] == code), None)
    if found:
        return found["finished_product_id"]
    r = client.post("/api/finished-products", headers=admin_h,
                    json={"code": code, "name": code, "uom": "lon",
                          "unit_type": unit_type, "pack_size": pack_size})
    assert r.status_code == 201, r.text
    return r.json()["finished_product_id"]


def _build_units(client, admin_h, suffix, total, pack_size=24, unit_type="vi"):
    fp_id = _ensure_finished_product(client, admin_h, suffix, pack_size, unit_type)
    r = client.post("/api/wms/units", headers=admin_h,
                    json={"finished_product_id": fp_id, "product_name": f"SKU-{suffix}",
                          "lot_code": f"LOT-{suffix}", "total": total, "pack_size": pack_size,
                          "unit_type": unit_type})
    assert r.status_code == 201, r.text
    # "Nhập kho thủ công" (build_units không is_opening_balance) giờ cần Trưởng bộ phận kho
    # duyệt trước khi xuất được (source="manual") — tự duyệt luôn để không chặn oan các test
    # khác (helper này chỉ để dựng sẵn tồn kho, không phải test bước duyệt).
    confirm = client.post("/api/wms/units/confirm-receipt-by-lot", headers=admin_h,
                          json={"product_name": f"SKU-{suffix}", "lot_code": f"LOT-{suffix}", "unit_type": unit_type})
    assert confirm.status_code == 200, confirm.text
    return r.json()


def _make_location(client, admin_h, code, capacity=10):
    r = client.post("/api/wms/locations", headers=admin_h,
                    json={"code": code, "name": code, "zone": "test", "kind": "bin", "capacity": capacity})
    assert r.status_code == 201, r.text
    return r.json()["loc_id"]


def _units_by_codes(client, admin_h, codes):
    all_units = client.get("/api/wms/units", headers=admin_h).json()
    codes = set(codes)
    return [u for u in all_units if u["unit_code"] in codes]


def test_transfer_moves_units_between_locations(client, admin_h):
    loc_a = _make_location(client, admin_h, "TX-A")
    loc_b = _make_location(client, admin_h, "TX-B", capacity=1)
    built = _build_units(client, admin_h, "TXFER01", total=48, pack_size=24, unit_type="vi")
    unit_ids = []
    for code in built["unit_codes"]:
        u = _units_by_codes(client, admin_h, [code])[0]
        put = client.post(f"/api/wms/units/{u['unit_id']}/putaway", headers=admin_h, json={"loc_id": loc_a})
        assert put.status_code == 200, put.text
        unit_ids.append(u["unit_id"])

    # Đích chỉ chứa được 1 (capacity=1) trong khi có 2 unit cần chuyển -> chặn.
    blocked = client.post("/api/wms/units/transfer", headers=admin_h,
                          json={"unit_ids": unit_ids, "to_loc_id": loc_b})
    assert blocked.status_code == 409, blocked.text

    loc_c = _make_location(client, admin_h, "TX-C", capacity=10)
    ok = client.post("/api/wms/units/transfer", headers=admin_h,
                     json={"unit_ids": unit_ids, "to_loc_id": loc_c})
    assert ok.status_code == 200, ok.text
    assert ok.json()["moved"] == 2

    moved_units = _units_by_codes(client, admin_h, built["unit_codes"])
    assert all(u["location"] == "TX-C" for u in moved_units)


def test_transfer_blocks_shipped_unit(client, admin_h):
    built = _build_units(client, admin_h, "TXFER02", total=24, pack_size=24, unit_type="vi")
    unit = _units_by_codes(client, admin_h, built["unit_codes"])[0]

    ship_to = client.post("/api/suppliers", headers=admin_h,
                          json={"code": "TXFER-ST", "name": "Test ship-to"})
    assert ship_to.status_code == 201, ship_to.text
    ship_to_id = ship_to.json()["supplier_id"]
    shipped = client.post("/api/wms/shipments", headers=admin_h,
                          json={"ship_to_id": ship_to_id,
                                "lines": [{"product_name": "SKU-TXFER02", "lot_code": "LOT-TXFER02",
                                          "unit_type": "vi", "quantity": 1}]})
    assert shipped.status_code == 201, shipped.text

    loc = _make_location(client, admin_h, "TX-D")
    blocked = client.post("/api/wms/units/transfer", headers=admin_h,
                          json={"unit_ids": [unit["unit_id"]], "to_loc_id": loc})
    assert blocked.status_code == 409, blocked.text


def test_decompose_vi_into_lon_units(client, admin_h):
    """Phân rã 1 dòng vỉ -> ĐÚNG 1 dòng lon kế thừa nguyên quantity (24), không tách N dòng
    lon riêng lẻ nữa (xem docs/WMS-LOT-LEVEL-REDESIGN.md — dòng lon giờ có thể đại diện rất
    nhiều lon rời, không còn luôn là "1 lon/1 dòng" như trước)."""
    built = _build_units(client, admin_h, "DECOMP01", total=24, pack_size=24, unit_type="vi")
    vi = _units_by_codes(client, admin_h, built["unit_codes"])[0]

    res = client.post(f"/api/wms/units/{vi['unit_id']}/decompose", headers=admin_h)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["count"] == 24
    assert len(body["lon_unit_codes"]) == 1

    lon_units = _units_by_codes(client, admin_h, body["lon_unit_codes"])
    assert len(lon_units) == 1
    assert lon_units[0]["unit_type"] == "lon" and lon_units[0]["quantity"] == 24 and lon_units[0]["status"] == "stored"

    vi_after = _units_by_codes(client, admin_h, [vi["unit_code"]])[0]
    assert vi_after["status"] == "decomposed"
    assert vi_after["created_at"] == lon_units[0]["created_at"]  # lon kế thừa đúng tuổi vỉ gốc


def test_decompose_blocks_keg_and_double_decompose_and_delete(client, admin_h):
    keg = _build_units(client, admin_h, "DECOMPKEG", total=1, pack_size=1, unit_type="keg")
    keg_unit = _units_by_codes(client, admin_h, keg["unit_codes"])[0]
    blocked_keg = client.post(f"/api/wms/units/{keg_unit['unit_id']}/decompose", headers=admin_h)
    assert blocked_keg.status_code == 409, blocked_keg.text

    built = _build_units(client, admin_h, "DECOMP02", total=24, pack_size=24, unit_type="vi")
    vi = _units_by_codes(client, admin_h, built["unit_codes"])[0]
    first = client.post(f"/api/wms/units/{vi['unit_id']}/decompose", headers=admin_h)
    assert first.status_code == 201, first.text

    second = client.post(f"/api/wms/units/{vi['unit_id']}/decompose", headers=admin_h)
    assert second.status_code == 409, second.text

    del_res = client.delete(f"/api/wms/units/{vi['unit_id']}", headers=admin_h)
    assert del_res.status_code == 409, del_res.text


def test_decompose_works_for_custom_divide_by_pack_unit_type(client, admin_h):
    """Bug thật gặp trong Kho TP: khai báo 1 loại đơn vị MỚI trong Danh mục "Loại đơn vị tồn
    kho" (VD "ket") với divide_by_pack_size=True — trước fix, Phân rã chỉ nhận biết cứng loại
    "vi" nên loại tự khai báo này không phân rã được dù Danh mục nói nó chia-theo-pack giống
    Vỉ. Xác nhận cả decompose_unit (1 dòng) lẫn decompose_batch (theo số lượng) đều hoạt động
    với loại tự khai báo, và loại KHÔNG chia-theo-pack (selectable nhưng divide=False) vẫn bị
    chặn như "keg"."""
    ket_type = client.post("/api/unit-types", headers=admin_h,
                          json={"code": "ket", "name": "Két", "divide_by_pack_size": True, "selectable": True})
    assert ket_type.status_code == 201, ket_type.text

    # 2 dòng riêng (mỗi lần build 1 dòng, giống pattern test_decompose_batch_by_count) — 1 dòng
    # dùng cho decompose_unit, 1 dòng dùng cho decompose_batch.
    _build_units(client, admin_h, "DECOMPKET", total=24, pack_size=24, unit_type="ket")
    _build_units(client, admin_h, "DECOMPKET", total=24, pack_size=24, unit_type="ket")
    all_units = client.get("/api/wms/units", headers=admin_h).json()
    units = [u for u in all_units if u["lot_code"] == "LOT-DECOMPKET" and u["unit_type"] == "ket"]
    assert len(units) == 2

    # decompose_unit (1 dòng cụ thể) — trước fix sẽ 409 "Chỉ có thể phân rã đơn vị loại vỉ."
    single = client.post(f"/api/wms/units/{units[0]['unit_id']}/decompose", headers=admin_h)
    assert single.status_code == 201, single.text
    assert single.json()["count"] == 24

    # decompose_batch (theo số lượng, không unit_type trong payload -> phải TỰ chặn vì mặc
    # định "vi" không khớp lô đang toàn "ket", không được ngầm hiểu nhầm sang lô khác.
    wrong_type = client.post("/api/wms/units/decompose-batch", headers=admin_h,
                             json={"product_name": "SKU-DECOMPKET", "lot_code": "LOT-DECOMPKET", "count": 1})
    assert wrong_type.status_code == 409, wrong_type.text

    batch = client.post("/api/wms/units/decompose-batch", headers=admin_h,
                        json={"product_name": "SKU-DECOMPKET", "lot_code": "LOT-DECOMPKET",
                              "unit_type": "ket", "count": 1})
    assert batch.status_code == 201, batch.text
    assert batch.json()["vi_decomposed"] == 1 and batch.json()["lon_created"] == 24


def test_ship_lon_units_after_decompose(client, admin_h):
    """Xuất MỘT PHẦN của 1 dòng lon (10/24) -> TÁCH dòng (xem _consume_lot_rows): 1 dòng mới
    quantity=10 chuyển "shipped", dòng gốc còn lại quantity=14 vẫn "stored" — không còn 24
    dòng lon riêng lẻ để chọn 10/24 như mô hình cũ."""
    built = _build_units(client, admin_h, "DECOMP03", total=24, pack_size=24, unit_type="vi")
    vi = _units_by_codes(client, admin_h, built["unit_codes"])[0]
    decomposed = client.post(f"/api/wms/units/{vi['unit_id']}/decompose", headers=admin_h).json()
    assert len(decomposed["lon_unit_codes"]) == 1  # 1 dòng lon duy nhất, quantity=24

    ship_to = client.post("/api/suppliers", headers=admin_h,
                          json={"code": "DECOMP-ST", "name": "Test ship-to lon"})
    assert ship_to.status_code == 201, ship_to.text
    ship_to_id = ship_to.json()["supplier_id"]

    shipment = client.post("/api/wms/shipments", headers=admin_h,
                           json={"ship_to_id": ship_to_id,
                                 "lines": [{"product_name": "SKU-DECOMP03", "lot_code": "LOT-DECOMP03",
                                           "unit_type": "lon", "quantity": 10}],
                                 "shipment_type": "promo"})
    assert shipment.status_code == 201, shipment.text
    assert shipment.json()["fifo_ok"] is True  # chỉ có 1 dòng lon -> không có dòng nào cũ hơn bị bỏ qua

    lons_after = [u for u in client.get("/api/wms/units", headers=admin_h).json()
                  if u["lot_code"] == "LOT-DECOMP03" and u["unit_type"] == "lon"]
    assert len(lons_after) == 2
    shipped = [u for u in lons_after if u["status"] == "shipped"]
    stored = [u for u in lons_after if u["status"] == "stored"]
    assert len(shipped) == 1 and shipped[0]["quantity"] == 10
    assert len(stored) == 1 and stored[0]["quantity"] == 14

    ships = client.get("/api/wms/shipments", headers=admin_h).json()
    made = next(s for s in ships if s["shipment_id"] == shipment.json()["shipment_id"])
    assert made["shipment_type"] == "promo"


def test_decompose_batch_by_count(client, admin_h):
    # 5 vỉ riêng (mỗi vỉ 1 dòng, total=24 mỗi lần build) cùng sản phẩm/lô -> phân rã 3/5 theo số lượng.
    for _ in range(5):
        _build_units(client, admin_h, "DECOMPBATCH", total=24, pack_size=24, unit_type="vi")
    all_units = client.get("/api/wms/units", headers=admin_h).json()
    vis = [u for u in all_units if u["lot_code"] == "LOT-DECOMPBATCH" and u["unit_type"] == "vi"]
    assert len(vis) == 5

    res = client.post("/api/wms/units/decompose-batch", headers=admin_h,
                      json={"product_name": "SKU-DECOMPBATCH", "lot_code": "LOT-DECOMPBATCH", "count": 3})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["vi_decomposed"] == 3 and body["lon_created"] == 72 and body["requested"] == 3
    assert body["audit_id"]

    after = client.get("/api/wms/units", headers=admin_h).json()
    vis_after = [u for u in after if u["lot_code"] == "LOT-DECOMPBATCH" and u["unit_type"] == "vi"]
    decomposed = [u for u in vis_after if u["status"] == "decomposed"]
    stored = [u for u in vis_after if u["status"] == "stored"]
    assert len(decomposed) == 3 and len(stored) == 2
    # 3 dòng lon (1 dòng/vỉ phân rã, không tách theo từng lon rời) tổng quantity = 72.
    lons = [u for u in after if u["lot_code"] == "LOT-DECOMPBATCH" and u["unit_type"] == "lon"]
    assert len(lons) == 3
    assert sum(u["quantity"] for u in lons) == 72

    # Yêu cầu nhiều hơn số vỉ còn tồn (2) -> phân rã hết 2, trả về đúng số đã xử lý.
    res2 = client.post("/api/wms/units/decompose-batch", headers=admin_h,
                       json={"product_name": "SKU-DECOMPBATCH", "lot_code": "LOT-DECOMPBATCH", "count": 10})
    assert res2.status_code == 201, res2.text
    body2 = res2.json()
    assert body2["vi_decomposed"] == 2 and body2["lon_created"] == 48 and body2["requested"] == 10

    # Không còn vỉ nào -> lỗi rõ ràng.
    res3 = client.post("/api/wms/units/decompose-batch", headers=admin_h,
                       json={"product_name": "SKU-DECOMPBATCH", "lot_code": "LOT-DECOMPBATCH", "count": 1})
    assert res3.status_code == 409, res3.text


def test_undo_decompose_batch_restores_vi_and_removes_lon(client, admin_h):
    for _ in range(2):
        _build_units(client, admin_h, "UNDODECOMP", total=24, pack_size=24, unit_type="vi")
    res = client.post("/api/wms/units/decompose-batch", headers=admin_h,
                      json={"product_name": "SKU-UNDODECOMP", "lot_code": "LOT-UNDODECOMP", "count": 2})
    assert res.status_code == 201, res.text
    audit_id = res.json()["audit_id"]

    before_undo = client.get("/api/wms/units", headers=admin_h).json()
    lons_before = [u for u in before_undo if u["lot_code"] == "LOT-UNDODECOMP" and u["unit_type"] == "lon"]
    assert len(lons_before) == 2  # 2 dòng lon (1 dòng/vỉ phân rã), tổng quantity = 48
    assert sum(u["quantity"] for u in lons_before) == 48

    undo = client.post(f"/api/wms/units/decompose-batch/{audit_id}/undo", headers=admin_h)
    assert undo.status_code == 200, undo.text
    assert undo.json() == {"vi_restored": 2, "lon_removed": 48}

    after_undo = client.get("/api/wms/units", headers=admin_h).json()
    vis_after = [u for u in after_undo if u["lot_code"] == "LOT-UNDODECOMP" and u["unit_type"] == "vi"]
    lons_after = [u for u in after_undo if u["lot_code"] == "LOT-UNDODECOMP" and u["unit_type"] == "lon"]
    assert len(vis_after) == 2 and all(u["status"] == "stored" for u in vis_after)
    assert lons_after == []

    # Hoàn tác lần 2 cùng audit_id -> chặn (đã hoàn tác trước đó).
    redo = client.post(f"/api/wms/units/decompose-batch/{audit_id}/undo", headers=admin_h)
    assert redo.status_code == 409, redo.text


def test_undo_decompose_batch_blocked_if_lon_shipped(client, admin_h):
    _build_units(client, admin_h, "UNDOSHIP", total=24, pack_size=24, unit_type="vi")
    res = client.post("/api/wms/units/decompose-batch", headers=admin_h,
                      json={"product_name": "SKU-UNDOSHIP", "lot_code": "LOT-UNDOSHIP", "count": 1})
    assert res.status_code == 201, res.text
    audit_id = res.json()["audit_id"]

    ship_to = client.post("/api/suppliers", headers=admin_h,
                          json={"code": "UNDOSHIP-ST", "name": "Test undo ship-to"})
    assert ship_to.status_code == 201, ship_to.text
    shipment = client.post("/api/wms/shipments", headers=admin_h,
                           json={"ship_to_id": ship_to.json()["supplier_id"],
                                 "lines": [{"product_name": "SKU-UNDOSHIP", "lot_code": "LOT-UNDOSHIP",
                                           "unit_type": "lon", "quantity": 1}]})
    assert shipment.status_code == 201, shipment.text

    blocked = client.post(f"/api/wms/units/decompose-batch/{audit_id}/undo", headers=admin_h)
    assert blocked.status_code == 409, blocked.text


def test_relocate_batch_places_unplaced_units_by_count(client, admin_h):
    built = _build_units(client, admin_h, "RELOC01", total=72, pack_size=24, unit_type="vi")
    assert built["count"] == 3  # 3 vỉ, chưa có vị trí (mới build)
    loc_small = _make_location(client, admin_h, "RELOC-SMALL", capacity=2)
    loc_big = _make_location(client, admin_h, "RELOC-BIG", capacity=10)

    # Đích chỉ chứa 2 trong khi yêu cầu cất cả 3 -> chặn.
    blocked = client.post("/api/wms/units/relocate-batch", headers=admin_h,
                          json={"product_name": "SKU-RELOC01", "lot_code": "LOT-RELOC01", "unit_type": "vi",
                                "from_loc_id": None, "to_loc_id": loc_small, "count": 3})
    assert blocked.status_code == 409, blocked.text

    ok = client.post("/api/wms/units/relocate-batch", headers=admin_h,
                     json={"product_name": "SKU-RELOC01", "lot_code": "LOT-RELOC01", "unit_type": "vi",
                           "from_loc_id": None, "to_loc_id": loc_big, "count": 2})
    assert ok.status_code == 200, ok.text
    assert ok.json() == {"moved": 2, "to_location": "RELOC-BIG", "requested": 2}

    # Dòng gốc (72=3 vỉ) bị TÁCH: 2 vỉ (48) đặt vào RELOC-BIG, 1 vỉ (24) còn lại chưa có vị
    # trí — không còn 3 dòng riêng lẻ để lọc theo built["unit_codes"] như mô hình cũ.
    lot_units = [u for u in client.get("/api/wms/units", headers=admin_h).json()
                 if u["lot_code"] == "LOT-RELOC01"]
    placed = [u for u in lot_units if u["location"] == "RELOC-BIG"]
    unplaced = [u for u in lot_units if not u["location"]]
    assert len(placed) == 1 and placed[0]["quantity"] == 48
    assert len(unplaced) == 1 and unplaced[0]["quantity"] == 24

    # Điều chuyển tiếp từ RELOC-BIG sang 1 vị trí khác theo số lượng (không cần chọn từng đơn vị).
    loc_dest = _make_location(client, admin_h, "RELOC-DEST", capacity=10)
    moved = client.post("/api/wms/units/relocate-batch", headers=admin_h,
                        json={"product_name": "SKU-RELOC01", "lot_code": "LOT-RELOC01", "unit_type": "vi",
                              "from_loc_id": loc_big, "to_loc_id": loc_dest, "count": 1})
    assert moved.status_code == 200, moved.text
    assert moved.json()["moved"] == 1


def test_resolve_by_lot_code_returns_aggregate(client, admin_h):
    built = _build_units(client, admin_h, "RESOLVE01", total=48, pack_size=24, unit_type="vi")
    assert built["count"] == 2

    res = client.get("/api/wms/resolve", params={"code": "LOT-RESOLVE01"}, headers=admin_h)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["type"] == "lot"
    assert body["lot_code"] == "LOT-RESOLVE01"
    assert body["product"] == "SKU-RESOLVE01"
    assert body["unit_count"] == 2
    assert body["by_status"] == {"stored": 2}
    assert body["by_type"] == {"vi": 2}

    # Vẫn tra được theo unit_code cụ thể (tương thích tem đã in trước đây).
    unit = _units_by_codes(client, admin_h, built["unit_codes"])[0]
    res2 = client.get("/api/wms/resolve", params={"code": unit["unit_code"]}, headers=admin_h)
    assert res2.status_code == 200, res2.text
    assert res2.json()["type"] == "finished_goods_unit"


def test_free_issue_batch_admin_only(client, admin_h, thukho_h):
    _build_units(client, admin_h, "FREEISSUE01", total=24, pack_size=24, unit_type="vi")
    blocked = client.post("/api/wms/units/free-issue", headers=thukho_h,
                          json={"product_name": "SKU-FREEISSUE01", "lot_code": "LOT-FREEISSUE01",
                                "unit_type": "vi", "count": 1, "reason": "Thử nghiệm"})
    assert blocked.status_code == 403, blocked.text


def test_free_issue_batch_requires_reason(client, admin_h):
    _build_units(client, admin_h, "FREEISSUENOREASON", total=24, pack_size=24, unit_type="vi")
    missing = client.post("/api/wms/units/free-issue", headers=admin_h,
                          json={"product_name": "SKU-FREEISSUENOREASON", "lot_code": "LOT-FREEISSUENOREASON",
                                "unit_type": "vi", "count": 1})
    assert missing.status_code == 422, missing.text  # reason là trường bắt buộc ở schema

    blank = client.post("/api/wms/units/free-issue", headers=admin_h,
                        json={"product_name": "SKU-FREEISSUENOREASON", "lot_code": "LOT-FREEISSUENOREASON",
                              "unit_type": "vi", "count": 1, "reason": "   "})
    assert blank.status_code == 409, blank.text  # DomainError -> lý do rỗng/toàn khoảng trắng bị chặn


def test_free_issue_batch_by_count_and_undo(client, admin_h):
    for _ in range(3):
        _build_units(client, admin_h, "FREEISSUE02", total=24, pack_size=24, unit_type="vi")
    all_units = client.get("/api/wms/units", headers=admin_h).json()
    vis = [u for u in all_units if u["lot_code"] == "LOT-FREEISSUE02" and u["unit_type"] == "vi"]
    assert len(vis) == 3

    res = client.post("/api/wms/units/free-issue", headers=admin_h,
                      json={"product_name": "SKU-FREEISSUE02", "lot_code": "LOT-FREEISSUE02",
                            "unit_type": "vi", "count": 2, "reason": "Hủy hàng kiểm tra"})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["issued"] == 2 and body["requested"] == 2
    audit_id = body["audit_id"]

    after = client.get("/api/wms/units", headers=admin_h).json()
    vis_after = [u for u in after if u["lot_code"] == "LOT-FREEISSUE02" and u["unit_type"] == "vi"]
    issued = [u for u in vis_after if u["status"] == "issued_free"]
    stored = [u for u in vis_after if u["status"] == "stored"]
    assert len(issued) == 2 and len(stored) == 1

    # issued_free bị loại khỏi tổng hợp tồn khả dụng (list_lot_summaries lọc status="stored").
    lot_summary = client.get("/api/wms/units/by-lot", headers=admin_h).json()
    g = next(x for x in lot_summary if x["lot_code"] == "LOT-FREEISSUE02")
    assert g["vi_count"] == 1

    history = client.get("/api/wms/units/free-issue-history", headers=admin_h).json()
    entry = next(e for e in history if e["audit_id"] == audit_id)
    assert entry["issued"] == 2 and entry["requested"] == 2 and entry["undone"] is False
    assert entry["reason"] == "Hủy hàng kiểm tra"

    undo = client.post(f"/api/wms/units/free-issue/{audit_id}/undo", headers=admin_h)
    assert undo.status_code == 200, undo.text
    assert undo.json() == {"restored": 2}

    after_undo = client.get("/api/wms/units", headers=admin_h).json()
    vis_after_undo = [u for u in after_undo if u["lot_code"] == "LOT-FREEISSUE02" and u["unit_type"] == "vi"]
    assert all(u["status"] == "stored" for u in vis_after_undo)

    redo = client.post(f"/api/wms/units/free-issue/{audit_id}/undo", headers=admin_h)
    assert redo.status_code == 409, redo.text

    history_after = client.get("/api/wms/units/free-issue-history", headers=admin_h).json()
    entry_after = next(e for e in history_after if e["audit_id"] == audit_id)
    assert entry_after["undone"] is True


def test_free_issue_batch_insufficient_stock(client, admin_h):
    _build_units(client, admin_h, "FREEISSUE03", total=24, pack_size=24, unit_type="vi")
    res = client.post("/api/wms/units/free-issue", headers=admin_h,
                      json={"product_name": "SKU-FREEISSUE03", "lot_code": "LOT-FREEISSUE03",
                            "unit_type": "vi", "count": 10, "reason": "Thử nghiệm"})
    assert res.status_code == 201, res.text
    assert res.json()["issued"] == 1 and res.json()["requested"] == 10

    res2 = client.post("/api/wms/units/free-issue", headers=admin_h,
                       json={"product_name": "SKU-FREEISSUE03", "lot_code": "LOT-FREEISSUE03",
                             "unit_type": "vi", "count": 1, "reason": "Thử nghiệm"})
    assert res2.status_code == 409, res2.text
