"""Test NVL dùng cho Lô lọc (BatchFilterLotMaterialUsage, mới) — mirror test_filter_material_usage.py
(module Nấu-Lọc-Chiết cũ) cho pipeline "Mẻ SX", CỘNG THÊM enforcement mới: chọn lô KHÁC lô FIFO
cũ nhất bắt buộc ghi lý do (áp dụng cho CẢ BatchFilterLotMaterialUsage lẫn BatchPackLotMaterialUsage
đã có sẵn — yêu cầu người dùng 2026-09-01).
"""

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

from app.common import utcnow
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


@pytest.fixture(autouse=True)
def _unblock_dangling_filter_lots_before_each_test(client, admin_h):
    """Dọn đường TRƯỚC MỖI TEST (không phải trước mỗi lần gọi _make_filter_lot — nếu không sẽ tự
    phá vỡ chính các test kiểm tra thứ tự xếp hàng, vốn CỐ Ý tạo 2 lô lọc A/B trong CÙNG 1 test
    và dựa vào việc A còn "chặn" B). Điều kiện xếp hàng mới (_assert_filter_material_addable,
    yêu cầu người dùng 2026-09-15) sẽ chặn oan lô lọc mà 1 test SAU tạo ra nếu còn lô lọc
    "dang_loc" từ test TRƯỚC chưa hề có nguyên liệu nào (VD test cố ý kiểm tra 1 nhánh lỗi,
    không thêm nguyên liệu thật) — dọn sạch các lô đó trước khi test hiện tại bắt đầu."""
    _unblock_earlier_filter_lots(client, admin_h)
    yield


def _a_material_with_stock(client, admin_h, code, qty_company=0, qty_workshop=0):
    m = client.post("/api/materials", headers=admin_h, json={"code": code, "name": f"Vật tư {code}", "uom": "kg"})
    assert m.status_code == 201, m.text
    material_id = m.json()["material_id"]
    if qty_company:
        r = client.post("/api/warehouse/receive", headers=admin_h,
                        json={"lot_code": f"LOT-{code}-CTY", "material_id": material_id,
                              "quantity": qty_company, "uom": "kg", "location": "Kho công ty"})
        assert r.status_code == 200, r.text
    if qty_workshop:
        r = client.post("/api/warehouse/receive", headers=admin_h,
                        json={"lot_code": f"LOT-{code}-PX", "material_id": material_id,
                              "quantity": qty_workshop, "uom": "kg", "location": "Kho phân xưởng"})
        assert r.status_code == 200, r.text
    return material_id


def _a_workshop_lot(client, admin_h, material_id, lot_code, qty):
    r = client.post("/api/warehouse/receive", headers=admin_h,
                    json={"lot_code": lot_code, "material_id": material_id,
                          "quantity": qty, "uom": "kg", "location": "Kho phân xưởng"})
    assert r.status_code == 200, r.text
    return r


def _lot_id_by_code(client, admin_h, lot_code):
    lots = client.get("/api/lots", headers=admin_h).json()
    return next(l for l in lots if l["lot_code"] == lot_code)


def _make_batch_tank(client, admin_h, batch_code, tank_code):
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(x for x in vers if x["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                          "batch_code": batch_code, "planned_qty": 1000, "allow_shortage": True})
    assert b.status_code == 201, b.text
    batch_id = b.json()["batch_id"]
    for target in ("ready", "running"):
        r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": target})
        assert r.status_code == 200, r.text
    aq = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": 1000})
    assert aq.status_code == 200, aq.text
    fin = client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={})
    assert fin.status_code == 200, fin.text
    r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "completed"})
    assert r.status_code == 200, r.text
    t = client.post("/api/batch-tanks", headers=admin_h,
                    json={"batch_ids": [batch_id], "tank_code": tank_code})
    assert t.status_code == 201, t.text
    return t.json()


def _unblock_earlier_filter_lots(client, admin_h):
    """Dọn đường trước khi tạo lô lọc MỚI trong test: điều kiện xếp hàng mới
    (_assert_filter_material_addable, yêu cầu người dùng 2026-09-15 — "lô lọc mở trước phải
    thêm NVL trước") sẽ chặn oan lô lọc SẮP tạo nếu còn lô lọc "dang_loc" từ test TRƯỚC chưa hề
    có nguyên liệu nào (VD test cố ý kiểm tra 1 nhánh lỗi, không thêm nguyên liệu thật). Thêm 1
    dòng nguyên liệu TỰ DO (material_name, không lot_id -> không đụng tồn kho thật) cho các lô
    đó để "đến lượt" — không ảnh hưởng gì tới lô MỚI đang test."""
    lots = client.get("/api/batch-filter-lots", headers=admin_h).json()
    for fl in lots:
        if fl["status"] != "dang_loc":
            continue
        usage = client.get(f"/api/batch-filter-lots/{fl['filter_lot_id']}/materials", headers=admin_h).json()
        if usage:
            continue
        add = client.post(f"/api/batch-filter-lots/{fl['filter_lot_id']}/materials", headers=admin_h,
                          json={"material_name": "AUTO-UNBLOCK (test)", "quantity": 0.001, "uom": "kg"})
        assert add.status_code == 201, add.text


def _make_filter_lot(client, admin_h, suffix):
    # batch_code giờ bắt buộc số nguyên (2026-09-02) — bỏ trống để tự sinh, suffix (không phải
    # số) chỉ dùng cho tank_code (tự do định dạng).
    tank = _make_batch_tank(client, admin_h, None, f"TANK-{suffix}")
    order = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": f"LOC-{suffix}",
        "sources": [{"source_type": "tank", "source_tank_id": tank["tank_id"], "planned_v_dich_hl": 900}],
    })
    assert order.status_code == 201, order.text
    bbt = client.post("/api/lines", headers=admin_h,
                      json={"code": f"BBT-{suffix}", "name": f"Tank thành phẩm {suffix}", "kind": "tank_bbt"})
    assert bbt.status_code == 201, bbt.text
    fl = client.post(f"/api/batch-filter-orders/{order.json()['order_id']}/filter-lots", headers=admin_h,
                     json={"filter_lot_code": f"FLOT-{suffix}", "to_bbt": bbt.json()["code"]})
    assert fl.status_code == 201, fl.text
    return fl.json()["filter_lot_id"]


def test_add_filter_lot_material_from_workshop_lot_deducts_stock(client, admin_h):
    suffix = "FLMU01"
    material_id = _a_material_with_stock(client, admin_h, f"MAT-{suffix}", qty_workshop=50)
    filter_lot_id = _make_filter_lot(client, admin_h, suffix)
    lot = _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix}-PX")

    add = client.post(f"/api/batch-filter-lots/{filter_lot_id}/materials", headers=admin_h,
                      json={"lot_id": lot["lot_id"], "quantity": 12, "uom": "kg"})
    assert add.status_code == 201, add.text
    usage = add.json()
    assert usage["material_name"] == f"Vật tư MAT-{suffix}"
    assert usage["lot_pm"] == f"LOT-MAT-{suffix}-PX"
    assert usage["fifo_ok"] is True
    assert usage["movement_id"]

    assert _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix}-PX")["quantity"] == 38

    listed = client.get(f"/api/batch-filter-lots/{filter_lot_id}/materials", headers=admin_h).json()
    assert len(listed) == 1 and listed[0]["usage_id"] == usage["usage_id"]

    delete = client.delete(f"/api/batch-filter-lots/materials/{usage['usage_id']}", headers=admin_h)
    assert delete.status_code == 204, delete.text
    assert _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix}-PX")["quantity"] == 50


def test_add_filter_lot_material_blocks_non_workshop_lot(client, admin_h):
    suffix = "FLMU02"
    _a_material_with_stock(client, admin_h, f"MAT-{suffix}", qty_company=20)
    filter_lot_id = _make_filter_lot(client, admin_h, suffix)
    lot = _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix}-CTY")

    blocked = client.post(f"/api/batch-filter-lots/{filter_lot_id}/materials", headers=admin_h,
                          json={"lot_id": lot["lot_id"], "quantity": 5})
    assert blocked.status_code == 409, blocked.text
    assert "kho phân xưởng" in blocked.json()["detail"].lower()


def test_add_filter_lot_material_non_fifo_requires_reason(client, admin_h):
    """Chọn lô KHÁC lô cũ nhất (FIFO) — chặn nếu không ghi lý do, cho qua nếu có lý do, và
    fifo_ok/reason phải lưu đúng."""
    suffix = "FLMU03"
    material_id = _a_material_with_stock(client, admin_h, f"MAT-{suffix}", qty_workshop=10)
    _a_workshop_lot(client, admin_h, material_id, f"LOT-{suffix}-NEWER", 20)
    filter_lot_id = _make_filter_lot(client, admin_h, suffix)
    newer_lot = _lot_id_by_code(client, admin_h, f"LOT-{suffix}-NEWER")

    no_reason = client.post(f"/api/batch-filter-lots/{filter_lot_id}/materials", headers=admin_h,
                            json={"lot_id": newer_lot["lot_id"], "quantity": 5})
    assert no_reason.status_code == 409, no_reason.text
    assert "fifo" in no_reason.json()["detail"].lower()

    with_reason = client.post(f"/api/batch-filter-lots/{filter_lot_id}/materials", headers=admin_h,
                              json={"lot_id": newer_lot["lot_id"], "quantity": 5, "reason": "Lô cũ đã hết chỗ chứa"})
    assert with_reason.status_code == 201, with_reason.text
    usage = with_reason.json()
    assert usage["fifo_ok"] is False
    assert usage["reason"] == "Lô cũ đã hết chỗ chứa"


def test_add_filter_lot_material_supply_date_defaults_to_now_and_drives_stock_as_of(client, admin_h):
    """"Ngày cấp" (supply_date) mặc định = bây giờ nếu không khai, và CHÍNH LÀ mốc dùng để trừ
    tồn kho phân xưởng "tính đến ngày" (StockMovement.ts qua issue(issued_at=...)) — KHÁC
    created_at (yêu cầu người dùng 2026-09-15)."""
    suffix = "FLMU-SUP01"
    material_id = _a_material_with_stock(client, admin_h, f"MAT-{suffix}", qty_workshop=50)
    filter_lot_id = _make_filter_lot(client, admin_h, suffix)
    lot = _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix}-PX")

    add = client.post(f"/api/batch-filter-lots/{filter_lot_id}/materials", headers=admin_h,
                      json={"lot_id": lot["lot_id"], "quantity": 12, "uom": "kg"})
    assert add.status_code == 201, add.text
    usage = add.json()
    assert usage["supply_date"] is not None
    assert usage["created_at"] is not None


def test_add_filter_lot_material_backdated_supply_date_used_for_stock_as_of(client, admin_h):
    suffix = "FLMU-SUP02"
    mat = client.post("/api/materials", headers=admin_h,
                      json={"code": f"MAT-{suffix}", "name": f"Vật tư MAT-{suffix}", "uom": "kg"})
    assert mat.status_code == 201, mat.text
    material_id = mat.json()["material_id"]
    # Nhận kho backdated TRƯỚC supply_date (nếu không, "before" ở dưới sẽ rơi vào lúc lô còn
    # chưa tồn tại, không phải lúc chưa bị trừ — 2 chuyện khác nhau).
    recv = client.post("/api/warehouse/receive", headers=admin_h, json={
        "lot_code": f"LOT-MAT-{suffix}-PX", "material_id": material_id, "quantity": 50, "uom": "kg",
        "location": "Kho phân xưởng", "received_at": (utcnow() - timedelta(hours=3)).isoformat()})
    assert recv.status_code == 200, recv.text
    filter_lot_id = _make_filter_lot(client, admin_h, suffix)
    lot = _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix}-PX")

    supply_date = utcnow() - timedelta(hours=1)
    add = client.post(f"/api/batch-filter-lots/{filter_lot_id}/materials", headers=admin_h,
                      json={"lot_id": lot["lot_id"], "quantity": 12, "uom": "kg",
                           "supply_date": supply_date.isoformat()})
    assert add.status_code == 201, add.text
    usage = add.json()
    from datetime import datetime
    got = datetime.fromisoformat(usage["supply_date"].replace("Z", "+00:00"))
    assert abs((got - supply_date).total_seconds()) < 2

    # TRƯỚC supply_date -> chưa trừ, còn nguyên 50kg.
    before = (supply_date - timedelta(minutes=1)).isoformat()
    stock_before = client.get("/api/warehouse/stock/as-of", headers=admin_h,
                              params={"as_of": before, "location": "Kho phân xưởng"}).json()
    row_before = next((r for r in stock_before if r["material_id"] == material_id), None)
    assert row_before is not None and row_before["on_hand"] == 50.0

    # TỪ supply_date trở đi -> đã trừ 12kg, còn 38kg (dù giờ bấm nút thật là "now", muộn hơn).
    stock_at = client.get("/api/warehouse/stock/as-of", headers=admin_h,
                          params={"as_of": supply_date.isoformat(), "location": "Kho phân xưởng"}).json()
    row_at = next(r for r in stock_at if r["material_id"] == material_id)
    assert row_at["on_hand"] == 38.0


def test_add_filter_lot_material_future_supply_date_rejected(client, admin_h):
    suffix = "FLMU-SUP03"
    material_id = _a_material_with_stock(client, admin_h, f"MAT-{suffix}", qty_workshop=50)
    filter_lot_id = _make_filter_lot(client, admin_h, suffix)
    lot = _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix}-PX")

    future = (utcnow() + timedelta(hours=1)).isoformat()
    add = client.post(f"/api/batch-filter-lots/{filter_lot_id}/materials", headers=admin_h,
                      json={"lot_id": lot["lot_id"], "quantity": 12, "uom": "kg", "supply_date": future})
    assert add.status_code == 409, add.text


def test_add_pack_lot_material_uses_pack_date_for_stock_as_of(client, admin_h):
    """Chiết KHÔNG có field "Ngày cấp" riêng theo từng dòng nguyên liệu — dùng thẳng
    BatchPackLot.pack_date (khai 1 lần ở mức lô thành phẩm) làm mốc trừ tồn kho, KHÁC created_at
    (yêu cầu người dùng 2026-09-15, áp dụng nhất quán với Lọc/Nấu)."""
    suffix = "PLMU-SUP01"
    mat = client.post("/api/materials", headers=admin_h,
                      json={"code": f"MAT-{suffix}", "name": f"Vật tư MAT-{suffix}", "uom": "kg"})
    assert mat.status_code == 201, mat.text
    material_id = mat.json()["material_id"]
    # Nhận kho backdated TRƯỚC pack_date (nếu không, "before" ở dưới sẽ rơi vào lúc lô còn chưa
    # tồn tại, không phải lúc chưa bị trừ).
    recv = client.post("/api/warehouse/receive", headers=admin_h, json={
        "lot_code": f"LOT-MAT-{suffix}-PX", "material_id": material_id, "quantity": 10, "uom": "kg",
        "location": "Kho phân xưởng", "received_at": (utcnow() - timedelta(hours=3)).isoformat()})
    assert recv.status_code == 200, recv.text
    filter_lot_id = _make_filter_lot(client, admin_h, suffix)
    src = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()[0]
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    fin = client.put(f"/api/batch-filter-lots/batches/{batches[0]['batch_link_id']}/finish", headers=admin_h,
                     json={"draws": [{"source_link_id": src["link_id"], "dich_nha_hl": 900}], "nuoc_bai_khi_hl": 0})
    assert fin.status_code == 200, fin.text
    appr = client.post(f"/api/batch-filter-lots/{filter_lot_id}/approve", headers=admin_h)
    assert appr.status_code == 200, appr.text
    to_bbt = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()["to_bbt"]
    pack_date = utcnow() - timedelta(hours=1)
    pack = client.post("/api/batch-pack-lots", headers=admin_h,
                       json={"from_bbt": to_bbt, "qty": 200, "pack_lot_code": f"PKG-{suffix}",
                            "lot_no": f"LOT-{suffix}", "pack_date": pack_date.isoformat()})
    assert pack.status_code == 201, pack.text
    pack_lot_id = pack.json()["pack_lot_id"]
    lot = _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix}-PX")

    add = client.post(f"/api/batch-pack-lots/{pack_lot_id}/materials", headers=admin_h,
                      json={"lot_id": lot["lot_id"], "quantity": 4})
    assert add.status_code == 201, add.text

    before = (pack_date - timedelta(minutes=1)).isoformat()
    stock_before = client.get("/api/warehouse/stock/as-of", headers=admin_h,
                              params={"as_of": before, "location": "Kho phân xưởng"}).json()
    row_before = next(r for r in stock_before if r["material_id"] == material_id)
    assert row_before["on_hand"] == 10.0

    stock_at = client.get("/api/warehouse/stock/as-of", headers=admin_h,
                          params={"as_of": pack_date.isoformat(), "location": "Kho phân xưởng"}).json()
    row_at = next(r for r in stock_at if r["material_id"] == material_id)
    assert row_at["on_hand"] == 6.0


def test_add_pack_lot_material_non_fifo_requires_reason(client, admin_h):
    """Cùng enforcement FIFO+lý do áp dụng cho NVL lô thành phẩm (chiết) đã có sẵn từ trước."""
    suffix = "PLMU-FIFO"
    material_id = _a_material_with_stock(client, admin_h, f"MAT-{suffix}", qty_workshop=10)
    _a_workshop_lot(client, admin_h, material_id, f"LOT-{suffix}-NEWER", 20)
    filter_lot_id = _make_filter_lot(client, admin_h, suffix)
    src = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()[0]
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    fin = client.put(f"/api/batch-filter-lots/batches/{batches[0]['batch_link_id']}/finish", headers=admin_h,
                     json={"draws": [{"source_link_id": src["link_id"], "dich_nha_hl": 900}], "nuoc_bai_khi_hl": 0})
    assert fin.status_code == 200, fin.text
    appr = client.post(f"/api/batch-filter-lots/{filter_lot_id}/approve", headers=admin_h)
    assert appr.status_code == 200, appr.text
    to_bbt = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()["to_bbt"]
    pack = client.post("/api/batch-pack-lots", headers=admin_h,
                       json={"from_bbt": to_bbt, "qty": 200, "pack_lot_code": f"PKG-{suffix}", "lot_no": f"LOT-{suffix}"})
    assert pack.status_code == 201, pack.text
    pack_lot_id = pack.json()["pack_lot_id"]
    newer_lot = _lot_id_by_code(client, admin_h, f"LOT-{suffix}-NEWER")

    no_reason = client.post(f"/api/batch-pack-lots/{pack_lot_id}/materials", headers=admin_h,
                            json={"lot_id": newer_lot["lot_id"], "quantity": 3})
    assert no_reason.status_code == 409, no_reason.text
    assert "fifo" in no_reason.json()["detail"].lower()

    with_reason = client.post(f"/api/batch-pack-lots/{pack_lot_id}/materials", headers=admin_h,
                              json={"lot_id": newer_lot["lot_id"], "quantity": 3, "reason": "Lô cũ để dành mẻ khác"})
    assert with_reason.status_code == 201, with_reason.text
    usage = with_reason.json()
    assert usage["fifo_ok"] is False
    assert usage["reason"] == "Lô cũ để dành mẻ khác"


def test_add_filter_lot_material_blocked_by_earlier_unstarted_filter_lot(client, admin_h):
    """Lô lọc mở (created_at) TRƯỚC mà CHƯA thêm NVL lần nào phải chặn lô lọc mở SAU — xếp hàng
    theo thứ tự mở lô (yêu cầu người dùng 2026-09-15, mirror _assert_dispensable cho Nấu, áp
    dụng thêm cho Lọc)."""
    suffix_a, suffix_b = "FLORD-A", "FLORD-B"
    _a_material_with_stock(client, admin_h, f"MAT-{suffix_a}", qty_workshop=50)
    _a_material_with_stock(client, admin_h, f"MAT-{suffix_b}", qty_workshop=50)
    filter_lot_a = _make_filter_lot(client, admin_h, suffix_a)
    filter_lot_b = _make_filter_lot(client, admin_h, suffix_b)   # tạo SAU A
    lot_b = _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix_b}-PX")

    blocked = client.post(f"/api/batch-filter-lots/{filter_lot_b}/materials", headers=admin_h,
                          json={"lot_id": lot_b["lot_id"], "quantity": 5})
    assert blocked.status_code == 409, blocked.text
    assert "mở trước" in blocked.json()["detail"]

    # Thêm NVL cho A trước -> A "đến lượt", B hết bị chặn.
    lot_a = _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix_a}-PX")
    ok_a = client.post(f"/api/batch-filter-lots/{filter_lot_a}/materials", headers=admin_h,
                       json={"lot_id": lot_a["lot_id"], "quantity": 5})
    assert ok_a.status_code == 201, ok_a.text

    ok_b = client.post(f"/api/batch-filter-lots/{filter_lot_b}/materials", headers=admin_h,
                       json={"lot_id": lot_b["lot_id"], "quantity": 5})
    assert ok_b.status_code == 201, ok_b.text


def test_completed_filter_lot_no_longer_blocks_later_ones(client, admin_h):
    """Lô lọc đã "Hoàn thành lọc" (status != dang_loc) không còn "chiếm hàng" nữa dù chưa từng
    thêm NVL nào — không phải lô lọc nào cũng cần NVL trợ lọc (mirror chỉ xét RUNNING/HELD ở
    Nấu, không xét COMPLETED/CLOSED/CANCELLED)."""
    suffix_a, suffix_b = "FLORD-C1", "FLORD-C2"
    _a_material_with_stock(client, admin_h, f"MAT-{suffix_b}", qty_workshop=50)
    filter_lot_a = _make_filter_lot(client, admin_h, suffix_a)
    filter_lot_b = _make_filter_lot(client, admin_h, suffix_b)
    lot_b = _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix_b}-PX")

    # A chưa xong -> B vẫn bị chặn trước.
    blocked = client.post(f"/api/batch-filter-lots/{filter_lot_b}/materials", headers=admin_h,
                          json={"lot_id": lot_b["lot_id"], "quantity": 5})
    assert blocked.status_code == 409, blocked.text

    # Kết thúc + "Hoàn thành lọc" A mà KHÔNG thêm NVL nào (hợp lệ nghiệp vụ).
    src = client.get(f"/api/batch-filter-lots/{filter_lot_a}/sources", headers=admin_h).json()[0]
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_a}/batches", headers=admin_h).json()
    fin = client.put(f"/api/batch-filter-lots/batches/{batches[0]['batch_link_id']}/finish", headers=admin_h,
                     json={"draws": [{"source_link_id": src["link_id"], "dich_nha_hl": 900}], "nuoc_bai_khi_hl": 0})
    assert fin.status_code == 200, fin.text
    done = client.post(f"/api/batch-filter-lots/{filter_lot_a}/finish-filtering", headers=admin_h)
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "hoan_thanh"

    ok_b = client.post(f"/api/batch-filter-lots/{filter_lot_b}/materials", headers=admin_h,
                       json={"lot_id": lot_b["lot_id"], "quantity": 5})
    assert ok_b.status_code == 201, ok_b.text
