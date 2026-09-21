"""Test NVL dùng cho Lô lọc (BatchFilterLotMaterialUsage) — chọn theo VẬT TƯ (material_id), hệ
thống tự chọn lô theo FIFO tại đúng "Ngày cấp" = BatchFilterLot.ended_at (yêu cầu người dùng
2026-09-16: bỏ tên tự do, không cho tự điền Ngày cấp, chặn hẳn khi không đủ tồn tại thời điểm kết
thúc). Enforcement cũ vẫn giữ nguyên: chọn lô KHÁC lô FIFO cũ nhất bắt buộc ghi lý do (áp dụng cho
CẢ BatchFilterLotMaterialUsage lẫn BatchPackLotMaterialUsage — yêu cầu người dùng 2026-09-01), và
lô lọc mở trước phải thêm NVL trước (yêu cầu người dùng 2026-09-15)."""

import os
import tempfile
from datetime import datetime, timedelta

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


def _force_finish_filter_lot(client, admin_h, filter_lot_id):
    """Đưa 1 lô lọc "dang_loc" ra khỏi trạng thái đó (Kết thúc mẻ dở dang nếu cần rồi "Hoàn thành
    lọc") — dùng để dọn đường cho hàng đợi (_assert_filter_material_addable) mà KHÔNG cần thêm
    nguyên liệu thật (tên tự do đã bị bỏ, không còn cách "thêm 1 dòng 0.001kg vô hại" như trước
    2026-09-16 nữa)."""
    fl = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()
    if fl["status"] != "dang_loc":
        return
    if fl.get("ended_at") is None:
        sources = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()
        draws = [{"source_link_id": s["link_id"], "dich_nha_hl": 1} for s in sources]
        batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
        for b in batches:
            if b.get("ended_at"):
                continue
            fin = client.put(f"/api/batch-filter-lots/batches/{b['batch_link_id']}/finish", headers=admin_h,
                             json={"draws": draws, "nuoc_bai_khi_hl": 0})
            assert fin.status_code == 200, fin.text
    done = client.post(f"/api/batch-filter-lots/{filter_lot_id}/finish-filtering", headers=admin_h)
    assert done.status_code == 200, done.text


@pytest.fixture(autouse=True)
def _unblock_dangling_filter_lots_before_each_test(client, admin_h):
    """Dọn đường TRƯỚC MỖI TEST (không phải trước mỗi lần gọi _make_filter_lot — nếu không sẽ tự
    phá vỡ chính các test kiểm tra thứ tự xếp hàng, vốn CỐ Ý tạo 2 lô lọc A/B trong CÙNG 1 test
    và dựa vào việc A còn "chặn" B). Điều kiện xếp hàng (_assert_filter_material_addable, yêu cầu
    người dùng 2026-09-15) sẽ chặn oan lô lọc mà 1 test SAU tạo ra nếu còn lô lọc "dang_loc" từ
    test TRƯỚC chưa hề có nguyên liệu nào — chuyển hẳn các lô đó sang "hoan_thanh" (không còn
    "chiếm hàng" nữa) trước khi test hiện tại bắt đầu."""
    lots = client.get("/api/batch-filter-lots", headers=admin_h).json()
    for fl in lots:
        if fl["status"] != "dang_loc":
            continue
        usage = client.get(f"/api/batch-filter-lots/{fl['filter_lot_id']}/materials", headers=admin_h).json()
        if usage:
            continue
        _force_finish_filter_lot(client, admin_h, fl["filter_lot_id"])
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


def _finish_only_source(client, admin_h, filter_lot_id, v_drawn=900, ended_at=None):
    """Kết thúc mẻ lọc duy nhất của 1 lô lọc mới tạo — đặt "Ngày cấp" (BatchFilterLot.ended_at)
    cho lô đó, điều kiện bắt buộc TRƯỚC khi thêm bất kỳ nguyên liệu nào (2026-09-16)."""
    src = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()[0]
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    payload = {"draws": [{"source_link_id": src["link_id"], "dich_nha_hl": v_drawn}], "nuoc_bai_khi_hl": 0}
    if ended_at is not None:
        payload["ended_at"] = ended_at.isoformat()
    fin = client.put(f"/api/batch-filter-lots/batches/{batches[0]['batch_link_id']}/finish", headers=admin_h,
                     json=payload)
    assert fin.status_code == 200, fin.text
    return fin.json()


def test_add_filter_lot_material_blocked_before_ended_at(client, admin_h):
    """Chưa "Kết thúc" mẻ lọc nào (chưa có ended_at) -> chưa có "Ngày cấp" -> chặn hẳn việc thêm
    nguyên liệu (yêu cầu người dùng 2026-09-16: "Lọc và chiết đều lấy ngày cấp là ngày kết thúc
    của mẻ lọc/chiết, không cho tự điền")."""
    suffix = "FLMU-NOEND"
    material_id = _a_material_with_stock(client, admin_h, f"MAT-{suffix}", qty_workshop=50)
    filter_lot_id = _make_filter_lot(client, admin_h, suffix)

    blocked = client.post(f"/api/batch-filter-lots/{filter_lot_id}/materials", headers=admin_h,
                          json={"material_id": material_id, "quantity": 5})
    assert blocked.status_code == 409, blocked.text
    assert "kết thúc" in blocked.json()["detail"].lower()


def test_add_filter_lot_material_from_workshop_lot_deducts_stock(client, admin_h):
    suffix = "FLMU01"
    material_id = _a_material_with_stock(client, admin_h, f"MAT-{suffix}", qty_workshop=50)
    filter_lot_id = _make_filter_lot(client, admin_h, suffix)
    _finish_only_source(client, admin_h, filter_lot_id)

    add = client.post(f"/api/batch-filter-lots/{filter_lot_id}/materials", headers=admin_h,
                      json={"material_id": material_id, "quantity": 12})
    assert add.status_code == 201, add.text
    rows = add.json()
    assert len(rows) == 1
    usage = rows[0]
    assert usage["material_name"] == f"Vật tư MAT-{suffix}"
    assert usage["lot_pm"] == f"LOT-MAT-{suffix}-PX"
    assert usage["fifo_ok"] is True
    assert usage["movement_id"]
    assert usage["supply_date"] is not None

    assert _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix}-PX")["quantity"] == 38

    listed = client.get(f"/api/batch-filter-lots/{filter_lot_id}/materials", headers=admin_h).json()
    assert len(listed) == 1 and listed[0]["usage_id"] == usage["usage_id"]

    delete = client.delete(f"/api/batch-filter-lots/materials/{usage['usage_id']}", headers=admin_h)
    assert delete.status_code == 204, delete.text
    assert _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix}-PX")["quantity"] == 50


def test_add_filter_lot_material_insufficient_stock_at_ended_at_blocks_all_or_nothing(client, admin_h):
    """Không đủ tồn kho phân xưởng TẠI THỜI ĐIỂM ended_at cho đủ quantity -> chặn hẳn, không trừ
    dở dang (yêu cầu người dùng 2026-09-16: "nếu không đủ vật tư tại thời điểm kết thúc thì sẽ
    cảnh báo và không cho nhập")."""
    suffix = "FLMU-SHORT"
    material_id = _a_material_with_stock(client, admin_h, f"MAT-{suffix}", qty_workshop=5)
    filter_lot_id = _make_filter_lot(client, admin_h, suffix)
    _finish_only_source(client, admin_h, filter_lot_id)

    blocked = client.post(f"/api/batch-filter-lots/{filter_lot_id}/materials", headers=admin_h,
                          json={"material_id": material_id, "quantity": 12})
    assert blocked.status_code == 409, blocked.text
    assert "thiếu" in blocked.json()["detail"].lower()
    # All-or-nothing: không trừ dở dang.
    assert _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix}-PX")["quantity"] == 5


def test_delete_filter_lot_material_blocked_after_kcs_approve(client, admin_h):
    """Sau khi KCS duyệt lô lọc (qc_approved=True), không thể xóa/hoàn NVL đã dùng nữa — mirror
    đúng chặn của delete_filter_lot (yêu cầu người dùng 2026-09-21: "đã dùng rồi thì không thể
    xóa, hoàn tác, hay sửa")."""
    suffix = "FLMU-APPR"
    material_id = _a_material_with_stock(client, admin_h, f"MAT-{suffix}", qty_workshop=50)
    filter_lot_id = _make_filter_lot(client, admin_h, suffix)
    _finish_only_source(client, admin_h, filter_lot_id)

    add = client.post(f"/api/batch-filter-lots/{filter_lot_id}/materials", headers=admin_h,
                      json={"material_id": material_id, "quantity": 12})
    assert add.status_code == 201, add.text
    usage_id = add.json()[0]["usage_id"]

    appr = client.post(f"/api/batch-filter-lots/{filter_lot_id}/approve", headers=admin_h)
    assert appr.status_code == 200, appr.text

    blocked = client.delete(f"/api/batch-filter-lots/materials/{usage_id}", headers=admin_h)
    assert blocked.status_code == 409, blocked.text


def test_suggest_filter_lot_material_previews_fifo_pick_without_deducting(client, admin_h):
    """GET .../materials/suggest xem trước lô sẽ dùng (FIFO, tại đúng ended_at) mà KHÔNG trừ tồn
    (yêu cầu người dùng 2026-09-16: "hiện tại không biết lấy lô nào khi chọn vật tư trong list")."""
    suffix = "FLMU-SUGGEST"
    material_id = _a_material_with_stock(client, admin_h, f"MAT-{suffix}", qty_workshop=50)
    filter_lot_id = _make_filter_lot(client, admin_h, suffix)
    _finish_only_source(client, admin_h, filter_lot_id)

    suggest = client.get(f"/api/batch-filter-lots/{filter_lot_id}/materials/suggest", headers=admin_h,
                         params={"material_id": material_id, "quantity": 12})
    assert suggest.status_code == 200, suggest.text
    body = suggest.json()
    assert body["shortfall"] == 0.0
    assert len(body["picks"]) == 1
    assert body["picks"][0]["lot_code"] == f"LOT-MAT-{suffix}-PX"
    assert body["picks"][0]["quantity"] == 12

    # Chỉ xem trước, KHÔNG trừ tồn thật.
    assert _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix}-PX")["quantity"] == 50

    short = client.get(f"/api/batch-filter-lots/{filter_lot_id}/materials/suggest", headers=admin_h,
                       params={"material_id": material_id, "quantity": 999})
    assert short.status_code == 200, short.text
    assert short.json()["shortfall"] == pytest.approx(949.0)


def test_add_filter_lot_material_blocks_non_workshop_lot(client, admin_h):
    suffix = "FLMU02"
    material_id = _a_material_with_stock(client, admin_h, f"MAT-{suffix}", qty_company=20)
    filter_lot_id = _make_filter_lot(client, admin_h, suffix)
    _finish_only_source(client, admin_h, filter_lot_id)
    lot = _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix}-CTY")

    blocked = client.post(f"/api/batch-filter-lots/{filter_lot_id}/materials", headers=admin_h,
                          json={"material_id": material_id, "lot_id": lot["lot_id"], "quantity": 5})
    assert blocked.status_code == 409, blocked.text
    assert "kho phân xưởng" in blocked.json()["detail"].lower()


def test_add_filter_lot_material_non_fifo_requires_reason(client, admin_h):
    """Chọn lô KHÁC lô cũ nhất (FIFO) — chặn nếu không ghi lý do, cho qua nếu có lý do, và
    fifo_ok/reason phải lưu đúng."""
    suffix = "FLMU03"
    material_id = _a_material_with_stock(client, admin_h, f"MAT-{suffix}", qty_workshop=10)
    _a_workshop_lot(client, admin_h, material_id, f"LOT-{suffix}-NEWER", 20)
    filter_lot_id = _make_filter_lot(client, admin_h, suffix)
    _finish_only_source(client, admin_h, filter_lot_id)
    newer_lot = _lot_id_by_code(client, admin_h, f"LOT-{suffix}-NEWER")

    no_reason = client.post(f"/api/batch-filter-lots/{filter_lot_id}/materials", headers=admin_h,
                            json={"material_id": material_id, "lot_id": newer_lot["lot_id"], "quantity": 5})
    assert no_reason.status_code == 409, no_reason.text
    assert "fifo" in no_reason.json()["detail"].lower()

    with_reason = client.post(f"/api/batch-filter-lots/{filter_lot_id}/materials", headers=admin_h,
                              json={"material_id": material_id, "lot_id": newer_lot["lot_id"], "quantity": 5,
                                   "reason": "Lô cũ đã hết chỗ chứa"})
    assert with_reason.status_code == 201, with_reason.text
    usage = with_reason.json()[0]
    assert usage["fifo_ok"] is False
    assert usage["reason"] == "Lô cũ đã hết chỗ chứa"


def test_add_filter_lot_material_supply_date_equals_ended_at(client, admin_h):
    """"Ngày cấp" (supply_date) LUÔN = BatchFilterLot.ended_at — server tự gán, không nhận input
    (yêu cầu người dùng 2026-09-16) — CHÍNH LÀ mốc dùng để trừ tồn kho phân xưởng "tính đến
    ngày" (StockMovement.ts qua issue(issued_at=...))."""
    suffix = "FLMU-SUP01"
    material_id = _a_material_with_stock(client, admin_h, f"MAT-{suffix}", qty_workshop=50)
    filter_lot_id = _make_filter_lot(client, admin_h, suffix)
    _finish_only_source(client, admin_h, filter_lot_id)
    ended_at = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()["ended_at"]

    add = client.post(f"/api/batch-filter-lots/{filter_lot_id}/materials", headers=admin_h,
                      json={"material_id": material_id, "quantity": 12})
    assert add.status_code == 201, add.text
    usage = add.json()[0]
    assert usage["supply_date"] is not None
    got = datetime.fromisoformat(usage["supply_date"].replace("Z", "+00:00"))
    want = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
    assert abs((got - want).total_seconds()) < 2


def test_add_filter_lot_material_backdated_ended_at_used_for_stock_as_of(client, admin_h):
    suffix = "FLMU-SUP02"
    mat = client.post("/api/materials", headers=admin_h,
                      json={"code": f"MAT-{suffix}", "name": f"Vật tư MAT-{suffix}", "uom": "kg"})
    assert mat.status_code == 201, mat.text
    material_id = mat.json()["material_id"]
    # Nhận kho backdated TRƯỚC ended_at (nếu không, "before" ở dưới sẽ rơi vào lúc lô còn chưa
    # tồn tại, không phải lúc chưa bị trừ — 2 chuyện khác nhau).
    recv = client.post("/api/warehouse/receive", headers=admin_h, json={
        "lot_code": f"LOT-MAT-{suffix}-PX", "material_id": material_id, "quantity": 50, "uom": "kg",
        "location": "Kho phân xưởng", "received_at": (utcnow() - timedelta(hours=3)).isoformat()})
    assert recv.status_code == 200, recv.text
    filter_lot_id = _make_filter_lot(client, admin_h, suffix)
    ended_at = utcnow() - timedelta(hours=1)
    _finish_only_source(client, admin_h, filter_lot_id, ended_at=ended_at)

    add = client.post(f"/api/batch-filter-lots/{filter_lot_id}/materials", headers=admin_h,
                      json={"material_id": material_id, "quantity": 12})
    assert add.status_code == 201, add.text
    usage = add.json()[0]
    got = datetime.fromisoformat(usage["supply_date"].replace("Z", "+00:00"))
    assert abs((got - ended_at).total_seconds()) < 2

    # TRƯỚC ended_at -> chưa trừ, còn nguyên 50kg.
    before = (ended_at - timedelta(minutes=1)).isoformat()
    stock_before = client.get("/api/warehouse/stock/as-of", headers=admin_h,
                              params={"as_of": before, "location": "Kho phân xưởng"}).json()
    row_before = next((r for r in stock_before if r["material_id"] == material_id), None)
    assert row_before is not None and row_before["on_hand"] == 50.0

    # TỪ ended_at trở đi -> đã trừ 12kg, còn 38kg (dù giờ bấm nút thật là "now", muộn hơn).
    stock_at = client.get("/api/warehouse/stock/as-of", headers=admin_h,
                          params={"as_of": ended_at.isoformat(), "location": "Kho phân xưởng"}).json()
    row_at = next(r for r in stock_at if r["material_id"] == material_id)
    assert row_at["on_hand"] == 38.0


def test_add_pack_lot_material_uses_ended_at_for_stock_as_of(client, admin_h):
    """Chiết KHÔNG có field "Ngày cấp" riêng theo từng dòng nguyên liệu — dùng thẳng
    BatchPackLot.ended_at (MAX giờ kết thúc trong số các ca ĐÃ khai cả SL và giờ) làm mốc trừ tồn
    kho, KHÔNG cho tự điền (yêu cầu người dùng 2026-09-16, thay cho pack_date trước đây)."""
    suffix = "PLMU-SUP01"
    mat = client.post("/api/materials", headers=admin_h,
                      json={"code": f"MAT-{suffix}", "name": f"Vật tư MAT-{suffix}", "uom": "kg"})
    assert mat.status_code == 201, mat.text
    material_id = mat.json()["material_id"]
    # Nhận kho backdated TRƯỚC ended_at (nếu không, "before" ở dưới sẽ rơi vào lúc lô còn chưa
    # tồn tại, không phải lúc chưa bị trừ).
    recv = client.post("/api/warehouse/receive", headers=admin_h, json={
        "lot_code": f"LOT-MAT-{suffix}-PX", "material_id": material_id, "quantity": 10, "uom": "kg",
        "location": "Kho phân xưởng", "received_at": (utcnow() - timedelta(hours=3)).isoformat()})
    assert recv.status_code == 200, recv.text
    filter_lot_id = _make_filter_lot(client, admin_h, suffix)
    _finish_only_source(client, admin_h, filter_lot_id)
    appr = client.post(f"/api/batch-filter-lots/{filter_lot_id}/approve", headers=admin_h)
    assert appr.status_code == 200, appr.text
    to_bbt = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()["to_bbt"]
    pack = client.post("/api/batch-pack-lots", headers=admin_h,
                       json={"from_bbt": to_bbt, "qty": 200, "pack_lot_code": f"PKG-{suffix}",
                            "lot_no": f"LOT-{suffix}"})
    assert pack.status_code == 201, pack.text
    pack_lot_id = pack.json()["pack_lot_id"]

    ended_at = utcnow() - timedelta(hours=1)
    shifts = client.put(f"/api/batch-pack-lots/{pack_lot_id}/shifts", headers=admin_h,
                        json={"ca1_qty": 200, "ca1_end_at": ended_at.isoformat()})
    assert shifts.status_code == 200, shifts.text

    add = client.post(f"/api/batch-pack-lots/{pack_lot_id}/materials", headers=admin_h,
                      json={"material_id": material_id, "quantity": 4})
    assert add.status_code == 201, add.text
    usage = add.json()[0]
    got = datetime.fromisoformat(usage["supply_date"].replace("Z", "+00:00"))
    assert abs((got - ended_at).total_seconds()) < 2

    before = (ended_at - timedelta(minutes=1)).isoformat()
    stock_before = client.get("/api/warehouse/stock/as-of", headers=admin_h,
                              params={"as_of": before, "location": "Kho phân xưởng"}).json()
    row_before = next(r for r in stock_before if r["material_id"] == material_id)
    assert row_before["on_hand"] == 10.0

    stock_at = client.get("/api/warehouse/stock/as-of", headers=admin_h,
                          params={"as_of": ended_at.isoformat(), "location": "Kho phân xưởng"}).json()
    row_at = next(r for r in stock_at if r["material_id"] == material_id)
    assert row_at["on_hand"] == 6.0


def test_add_pack_lot_material_non_fifo_requires_reason(client, admin_h):
    """Cùng enforcement FIFO+lý do áp dụng cho NVL lô thành phẩm (chiết) đã có sẵn từ trước."""
    suffix = "PLMU-FIFO"
    material_id = _a_material_with_stock(client, admin_h, f"MAT-{suffix}", qty_workshop=10)
    _a_workshop_lot(client, admin_h, material_id, f"LOT-{suffix}-NEWER", 20)
    filter_lot_id = _make_filter_lot(client, admin_h, suffix)
    _finish_only_source(client, admin_h, filter_lot_id)
    appr = client.post(f"/api/batch-filter-lots/{filter_lot_id}/approve", headers=admin_h)
    assert appr.status_code == 200, appr.text
    to_bbt = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()["to_bbt"]
    pack = client.post("/api/batch-pack-lots", headers=admin_h,
                       json={"from_bbt": to_bbt, "qty": 200, "pack_lot_code": f"PKG-{suffix}", "lot_no": f"LOT-{suffix}"})
    assert pack.status_code == 201, pack.text
    pack_lot_id = pack.json()["pack_lot_id"]
    shifts = client.put(f"/api/batch-pack-lots/{pack_lot_id}/shifts", headers=admin_h,
                        json={"ca1_qty": 200, "ca1_end_at": utcnow().isoformat()})
    assert shifts.status_code == 200, shifts.text
    newer_lot = _lot_id_by_code(client, admin_h, f"LOT-{suffix}-NEWER")

    no_reason = client.post(f"/api/batch-pack-lots/{pack_lot_id}/materials", headers=admin_h,
                            json={"material_id": material_id, "lot_id": newer_lot["lot_id"], "quantity": 3})
    assert no_reason.status_code == 409, no_reason.text
    assert "fifo" in no_reason.json()["detail"].lower()

    with_reason = client.post(f"/api/batch-pack-lots/{pack_lot_id}/materials", headers=admin_h,
                              json={"material_id": material_id, "lot_id": newer_lot["lot_id"], "quantity": 3,
                                   "reason": "Lô cũ để dành mẻ khác"})
    assert with_reason.status_code == 201, with_reason.text
    usage = with_reason.json()[0]
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
    _finish_only_source(client, admin_h, filter_lot_a)
    _finish_only_source(client, admin_h, filter_lot_b)
    material_b = _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix_b}-PX")["material_id"]

    blocked = client.post(f"/api/batch-filter-lots/{filter_lot_b}/materials", headers=admin_h,
                          json={"material_id": material_b, "quantity": 5})
    assert blocked.status_code == 409, blocked.text
    assert "mở trước" in blocked.json()["detail"]

    # Thêm NVL cho A trước -> A "đến lượt", B hết bị chặn.
    material_a = _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix_a}-PX")["material_id"]
    ok_a = client.post(f"/api/batch-filter-lots/{filter_lot_a}/materials", headers=admin_h,
                       json={"material_id": material_a, "quantity": 5})
    assert ok_a.status_code == 201, ok_a.text

    ok_b = client.post(f"/api/batch-filter-lots/{filter_lot_b}/materials", headers=admin_h,
                       json={"material_id": material_b, "quantity": 5})
    assert ok_b.status_code == 201, ok_b.text


def test_completed_filter_lot_no_longer_blocks_later_ones(client, admin_h):
    """Lô lọc đã "Hoàn thành lọc" (status != dang_loc) không còn "chiếm hàng" nữa dù chưa từng
    thêm NVL nào — không phải lô lọc nào cũng cần NVL trợ lọc (mirror chỉ xét RUNNING/HELD ở
    Nấu, không xét COMPLETED/CLOSED/CANCELLED)."""
    suffix_a, suffix_b = "FLORD-C1", "FLORD-C2"
    _a_material_with_stock(client, admin_h, f"MAT-{suffix_b}", qty_workshop=50)
    filter_lot_a = _make_filter_lot(client, admin_h, suffix_a)
    filter_lot_b = _make_filter_lot(client, admin_h, suffix_b)
    _finish_only_source(client, admin_h, filter_lot_b)
    material_b = _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix_b}-PX")["material_id"]

    # A chưa xong -> B vẫn bị chặn trước.
    blocked = client.post(f"/api/batch-filter-lots/{filter_lot_b}/materials", headers=admin_h,
                          json={"material_id": material_b, "quantity": 5})
    assert blocked.status_code == 409, blocked.text

    # Kết thúc + "Hoàn thành lọc" A mà KHÔNG thêm NVL nào (hợp lệ nghiệp vụ).
    _finish_only_source(client, admin_h, filter_lot_a)
    done = client.post(f"/api/batch-filter-lots/{filter_lot_a}/finish-filtering", headers=admin_h)
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "hoan_thanh"

    ok_b = client.post(f"/api/batch-filter-lots/{filter_lot_b}/materials", headers=admin_h,
                       json={"material_id": material_b, "quantity": 5})
    assert ok_b.status_code == 201, ok_b.text


def test_filter_and_pack_material_supply_date_also_reflected_in_inventory_report(client, admin_h):
    """"Ngày cấp" (Lọc/Chiết: ended_at) không chỉ tính đúng ở "Tồn kho tính đến ngày" (đã test ở
    2 test trên) mà PHẢI khớp CẢ "BC nhập-xuất-tồn" (inventory_report/lot_inventory_report) VÀ
    "Sổ chi tiết vật tư" (material_transaction_detail) — cả 3 đều đọc chung StockMovement.ts do
    warehouse_svc.issue(issued_at=...) ghi, không cần xử lý riêng như Nấu (yêu cầu người dùng
    2026-09-15: xác nhận toàn bộ chuỗi nhất quán)."""
    suffix = "FLMU-RPT01"
    mat = client.post("/api/materials", headers=admin_h,
                      json={"code": f"MAT-{suffix}", "name": f"Vật tư MAT-{suffix}", "uom": "kg"})
    assert mat.status_code == 201, mat.text
    material_id = mat.json()["material_id"]
    recv = client.post("/api/warehouse/receive", headers=admin_h, json={
        "lot_code": f"LOT-MAT-{suffix}-PX", "material_id": material_id, "quantity": 50, "uom": "kg",
        "location": "Kho phân xưởng", "received_at": (utcnow() - timedelta(hours=3)).isoformat()})
    assert recv.status_code == 200, recv.text
    filter_lot_id = _make_filter_lot(client, admin_h, suffix)
    supply_date = utcnow() - timedelta(hours=1)
    _finish_only_source(client, admin_h, filter_lot_id, ended_at=supply_date)

    add = client.post(f"/api/batch-filter-lots/{filter_lot_id}/materials", headers=admin_h,
                      json={"material_id": material_id, "quantity": 12})
    assert add.status_code == 201, add.text
    lot = _lot_id_by_code(client, admin_h, f"LOT-MAT-{suffix}-PX")

    # Kỳ báo cáo CHỈ phủ tới supply_date + 5 phút — KHÔNG phủ tới "now" (giờ bấm nút thật).
    date_from = (utcnow() - timedelta(hours=4)).isoformat()
    date_to = (supply_date + timedelta(minutes=5)).isoformat()

    rep = client.get("/api/warehouse/report", headers=admin_h, params={
        "date_from": date_from, "date_to": date_to, "location": "Kho phân xưởng"}).json()
    row = next(r for r in rep if r["material_id"] == material_id)
    assert row["issued"] == pytest.approx(12.0)

    rep_lot = client.get("/api/warehouse/report/by-lot", headers=admin_h, params={
        "date_from": date_from, "date_to": date_to, "location": "Kho phân xưởng"}).json()
    lot_row = next(r for r in rep_lot if r["lot_id"] == lot["lot_id"])
    assert lot_row["issued"] == pytest.approx(12.0)

    detail = client.get("/api/warehouse/report/material-detail", headers=admin_h, params={
        "material_id": material_id, "date_from": date_from, "date_to": date_to,
        "location": "Kho phân xưởng"}).json()
    total_out = sum(r["out"] for r in detail["rows"])
    assert total_out == pytest.approx(12.0)

    # Kỳ báo cáo CHỈ phủ "now" trở đi (không phủ supply_date) -> KHÔNG được tính lại lần 2.
    date_from2 = (utcnow() - timedelta(minutes=1)).isoformat()
    date_to2 = (utcnow() + timedelta(hours=1)).isoformat()
    rep2 = client.get("/api/warehouse/report", headers=admin_h, params={
        "date_from": date_from2, "date_to": date_to2, "location": "Kho phân xưởng"}).json()
    row2 = next((r for r in rep2 if r["material_id"] == material_id), None)
    assert row2 is None or row2["issued"] == 0.0
