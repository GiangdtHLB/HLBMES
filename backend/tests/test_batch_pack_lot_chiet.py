"""Test 3 yêu cầu mới của người dùng (2026-08-31) cho pipeline "Mẻ sản xuất":

1. Lô thành phẩm (BatchPackLot) tạo theo kiểu "Chiết" — chọn Tank BBT nào đi chiết (mirror
   BottleRecord.from_bbt/add_bottle), server tự tìm lô lọc nguồn; kèm dây chuyền chiết + ngày
   giờ bắt đầu chiết (pack_date) + NVL cấp cho chiết (BatchPackLotMaterialUsage).
2. Tank lên men hiển thị ngày bắt đầu/kết thúc vào dịch + thời gian lên men thực tế so với
   chuẩn (Product.ferment_days_std) — xem services/batch_pipeline.py::_tank_out.

Xem services/batch_pipeline.py cho phần còn lại của pipeline (test_batch_pipeline.py/
test_batch_filter_order.py/test_batch_tank_gaps.py).
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


def _make_batch(client, admin_h, batch_code):
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(v for v in vers if v["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                          "batch_code": batch_code, "planned_qty": 1000, "allow_shortage": True})
    assert b.status_code == 201, b.text
    return b.json()


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


def _make_bbt_line(client, admin_h, suffix):
    r = client.post("/api/lines", headers=admin_h,
                    json={"code": f"BBT-{suffix}", "name": f"Tank thành phẩm {suffix}", "kind": "tank_bbt"})
    assert r.status_code == 201, r.text
    return r.json()["code"]


def _finish_source(client, admin_h, source, dich_nha_hl, nuoc_bai_khi_hl=0):
    """1 mẻ lọc tự có sẵn 1 khoản rút (draw) cho MỖI nguồn ngay lúc tạo lô lọc — "Kết thúc" tức
    là kết thúc mẻ đó, khai V dịch nha cho khoản rút của nguồn này. `source` là dict trả về từ
    GET .../sources (cần cả filter_lot_id lẫn link_id)."""
    batches = client.get(f"/api/batch-filter-lots/{source['filter_lot_id']}/batches", headers=admin_h).json()
    batch_link_id = batches[-1]["batch_link_id"]
    return client.put(f"/api/batch-filter-lots/batches/{batch_link_id}/finish", headers=admin_h,
                      json={"draws": [{"source_link_id": source["link_id"], "dich_nha_hl": dich_nha_hl}],
                           "nuoc_bai_khi_hl": nuoc_bai_khi_hl})


def _build_approved_filter_lot(client, admin_h, suffix, v_drawn=900):
    """mẻ nấu (chạy xong -> completed) -> tank -> lô lọc đã kết thúc + duyệt KCS. Trả về
    (batch, tank_id, filter_lot_id, to_bbt)."""
    batch = _make_batch(client, admin_h, None)   # batch_code giờ bắt buộc số nguyên — để tự sinh
    _run_batch_to_completed(client, admin_h, batch["batch_id"])
    tank = client.post("/api/batch-tanks", headers=admin_h,
                       json={"batch_ids": [batch["batch_id"]], "tank_code": f"TANK-CHIET-{suffix}"})
    assert tank.status_code == 201, tank.text
    tank_id = tank.json()["tank_id"]
    to_bbt = _make_bbt_line(client, admin_h, suffix)
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": f"FLOT-CHIET-{suffix}", "to_bbt": to_bbt,
        "sources": [{"source_type": "tank", "source_tank_id": tank_id}],
    })
    assert draw.status_code == 201, draw.text
    filter_lot_id = draw.json()["filter_lot_id"]
    src = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()[0]
    fin = _finish_source(client, admin_h, src, v_drawn)
    assert fin.status_code == 200, fin.text
    appr = client.post(f"/api/batch-filter-lots/{filter_lot_id}/approve", headers=admin_h)
    assert appr.status_code == 200, appr.text
    return batch, tank_id, filter_lot_id, to_bbt


def test_pack_lot_from_bbt_requires_eligible_tank(client, admin_h):
    unknown = client.post("/api/batch-pack-lots", headers=admin_h,
                          json={"from_bbt": "BBT-NOPE", "qty": 10, "pack_lot_code": "PKG-CHIET-BAD", "lot_no": "LOT-BAD"})
    assert unknown.status_code == 409, unknown.text  # not in eligible list -> DomainError

    missing = client.post("/api/batch-pack-lots", headers=admin_h,
                          json={"qty": 10, "pack_lot_code": "PKG-CHIET-BAD2"})
    assert missing.status_code == 422, missing.text  # from_bbt required by schema


def test_pack_lot_from_bbt_creates_with_line_and_pack_date(client, admin_h):
    _batch, _tank_id, filter_lot_id, to_bbt = _build_approved_filter_lot(client, admin_h, "01")

    eligible = client.get("/api/batch-pack-lots/eligible-bbt-lines", headers=admin_h).json()
    row = next((r for r in eligible if r["code"] == to_bbt), None)
    assert row is not None, eligible
    assert row["on_hand_bbt"] == 900.0

    # qty (Số lượng cấp chiết) đơn vị LÍT — 30000 lít = 300 hl, quy đổi khi trừ tồn lô lọc (hl).
    pack = client.post("/api/batch-pack-lots", headers=admin_h, json={
        "from_bbt": to_bbt, "qty": 30000, "pack_lot_code": "PKG-CHIET-01",
        "lot_no": "LOTBIA-01", "line": "CL01, CL02",
        "pack_date": "2026-08-20T08:00:00",
    })
    assert pack.status_code == 201, pack.text
    p = pack.json()
    assert p["from_bbt"] == to_bbt
    assert p["filter_lot_id"] == filter_lot_id
    assert p["line"] == "CL01, CL02"
    assert p["pack_date"].startswith("2026-08-20T08:00:00")

    fl = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()
    assert fl["on_hand"] == 600.0  # 900 - 300 hl (qty 30000 lít), DELTA đúng như split_filter_lot_to_pack_lot

    # còn tồn (600 > 0) và vẫn đã duyệt hết -> vẫn đủ điều kiện chiết tiếp
    eligible2 = client.get("/api/batch-pack-lots/eligible-bbt-lines", headers=admin_h).json()
    row2 = next((r for r in eligible2 if r["code"] == to_bbt), None)
    assert row2 is not None and row2["on_hand_bbt"] == 600.0


def test_pack_lot_from_bbt_blocked_when_not_all_finished(client, admin_h):
    """1 tank thành phẩm cần NHIỀU mẻ lọc mới đầy — mẻ 1 đã kết thúc, mẻ 2 vừa mở CHƯA kết thúc
    -> tank BBT KHÔNG đủ điều kiện chiết (ended_at yêu cầu TẤT CẢ mẻ đã kết thúc) — approve cũng
    sẽ bị chặn."""
    b1 = _make_batch(client, admin_h, "1")
    _run_batch_to_completed(client, admin_h, b1["batch_id"])
    t1 = client.post("/api/batch-tanks", headers=admin_h,
                     json={"batch_ids": [b1["batch_id"]], "tank_code": "TANK-CHIETBLK-1"}).json()
    to_bbt = _make_bbt_line(client, admin_h, "BLK")
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": "FLOT-CHIETBLK", "to_bbt": to_bbt,
        "sources": [{"source_type": "tank", "source_tank_id": t1["tank_id"]}],
    })
    assert draw.status_code == 201, draw.text
    filter_lot_id = draw.json()["filter_lot_id"]
    src = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()[0]
    fin = _finish_source(client, admin_h, src, 500)
    assert fin.status_code == 200, fin.text

    added = client.post(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h)
    assert added.status_code == 201, added.text   # mẻ 2 mở, chưa kết thúc

    appr = client.post(f"/api/batch-filter-lots/{filter_lot_id}/approve", headers=admin_h)
    assert appr.status_code == 409, appr.text  # ended_at None (còn mẻ chưa kết thúc)

    eligible = client.get("/api/batch-pack-lots/eligible-bbt-lines", headers=admin_h).json()
    assert not any(r["code"] == to_bbt for r in eligible)

    bad = client.post("/api/batch-pack-lots", headers=admin_h,
                      json={"from_bbt": to_bbt, "qty": 100, "pack_lot_code": "PKG-CHIETBLK", "lot_no": "LOT-CHIETBLK"})
    assert bad.status_code == 409, bad.text


def test_pack_lot_material_usage_free_text_add_list_delete(client, admin_h):
    _batch, _tank_id, filter_lot_id, to_bbt = _build_approved_filter_lot(client, admin_h, "MAT")
    pack = client.post("/api/batch-pack-lots", headers=admin_h,
                       json={"from_bbt": to_bbt, "qty": 200, "pack_lot_code": "PKG-CHIET-MAT", "lot_no": "LOT-CHIET-MAT"})
    assert pack.status_code == 201, pack.text
    pack_lot_id = pack.json()["pack_lot_id"]

    empty = client.get(f"/api/batch-pack-lots/{pack_lot_id}/materials", headers=admin_h).json()
    assert empty == []

    add = client.post(f"/api/batch-pack-lots/{pack_lot_id}/materials", headers=admin_h,
                      json={"material_name": "CO2 thực phẩm", "quantity": 5, "uom": "kg"})
    assert add.status_code == 201, add.text
    usage_id = add.json()["usage_id"]
    assert add.json()["material_name"] == "CO2 thực phẩm"
    assert add.json()["movement_id"] is None  # không chọn lot_id -> không trừ kho thật

    no_name_no_lot = client.post(f"/api/batch-pack-lots/{pack_lot_id}/materials", headers=admin_h,
                                 json={"quantity": 1})
    assert no_name_no_lot.status_code == 409, no_name_no_lot.text

    listed = client.get(f"/api/batch-pack-lots/{pack_lot_id}/materials", headers=admin_h).json()
    assert len(listed) == 1 and listed[0]["usage_id"] == usage_id

    delr = client.delete(f"/api/batch-pack-lots/materials/{usage_id}", headers=admin_h)
    assert delr.status_code == 204, delr.text


def test_pack_lot_shifts_qty_and_time_editable_repeatedly(client, admin_h):
    _batch, _tank_id, _filter_lot_id, to_bbt = _build_approved_filter_lot(client, admin_h, "SHIFT")
    pack = client.post("/api/batch-pack-lots", headers=admin_h,
                       json={"from_bbt": to_bbt, "qty": 900, "pack_lot_code": "PKG-CHIET-SHIFT",
                             "lot_no": "LOT-CHIET-SHIFT"})
    assert pack.status_code == 201, pack.text
    pack_lot_id = pack.json()["pack_lot_id"]
    assert pack.json()["ca1_qty"] is None and pack.json()["ca1_start_at"] is None

    upd = client.put(f"/api/batch-pack-lots/{pack_lot_id}/shifts", headers=admin_h, json={
        "ca1_qty": 500, "ca1_start_at": "2026-08-31T08:00:00", "ca1_end_at": "2026-08-31T16:00:00",
        "ca2_qty": 400, "ca2_start_at": "2026-08-31T16:00:00", "ca2_end_at": "2026-09-01T00:00:00",
    })
    assert upd.status_code == 200, upd.text
    body = upd.json()
    assert body["ca1_qty"] == 500 and body["ca1_start_at"].startswith("2026-08-31T08:00:00")
    assert body["ca2_qty"] == 400
    assert body["ca3_qty"] is None   # ca3 chưa gửi -> giữ nguyên None

    fixed = client.put(f"/api/batch-pack-lots/{pack_lot_id}/shifts", headers=admin_h,
                       json={"ca1_qty": 480})
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["ca1_qty"] == 480
    assert fixed.json()["ca1_start_at"].startswith("2026-08-31T08:00:00")  # field khác không gửi -> giữ nguyên
    assert fixed.json()["ca2_qty"] == 400
    assert client.get(f"/api/batch-pack-lots/{pack_lot_id}/materials", headers=admin_h).json() == []


def test_pack_lot_qty_liters_converts_to_hl_on_filter_lot(client, admin_h):
    """Số lượng cấp chiết (qty) đơn vị LÍT; lô lọc nguồn (on_hand) đơn vị hl — mọi thao tác
    tạo/sửa/xóa lô TP phải quy đổi đúng 1 hl = 100 lít khi trừ/hoàn tồn lô lọc."""
    _batch, _tank_id, filter_lot_id, to_bbt = _build_approved_filter_lot(client, admin_h, "LITER", v_drawn=1000)
    pack = client.post("/api/batch-pack-lots", headers=admin_h, json={
        "from_bbt": to_bbt, "qty": 25000, "pack_lot_code": "PKG-CHIET-LITER", "lot_no": "LOT-CHIET-LITER"})
    assert pack.status_code == 201, pack.text
    pack_lot_id = pack.json()["pack_lot_id"]
    assert pack.json()["qty"] == 25000   # lưu nguyên đơn vị lít, không quy đổi khi hiển thị

    fl = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()
    assert fl["on_hand"] == 750.0   # 1000 hl - 250 hl (25000 lít / 100)

    upd = client.put(f"/api/batch-pack-lots/{pack_lot_id}/qty", headers=admin_h, json={"qty": 35000})
    assert upd.status_code == 200, upd.text
    fl2 = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()
    assert fl2["on_hand"] == 650.0   # 750 - 100 hl (thêm 10000 lít)

    delp = client.delete(f"/api/batch-pack-lots/{pack_lot_id}", headers=admin_h)
    assert delp.status_code == 204, delp.text
    fl3 = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()
    assert fl3["on_hand"] == 1000.0


def test_tank_shows_vao_dich_dates_and_ferment_duration(client, admin_h):
    b1 = _make_batch(client, admin_h, "2")
    b2 = _make_batch(client, admin_h, "3")
    product_id = b1["product_id"]
    upd = client.put(f"/api/products/{product_id}", headers=admin_h, json={
        "code": next(p["code"] for p in client.get("/api/products", headers=admin_h).json()
                    if p["product_id"] == product_id),
        "name": next(p["name"] for p in client.get("/api/products", headers=admin_h).json()
                    if p["product_id"] == product_id),
        "ferment_days_std": 14,
    })
    assert upd.status_code == 200, upd.text

    # Business rule mới (merge_batches_into_tank): chỉ được gộp mẻ ĐÃ hoàn thành (completed) vào
    # tank -> cả 2 mẻ phải chạy xong TRƯỚC khi gộp, không còn cách quan sát trạng thái "dở dang"
    # (1 mẻ xong, 1 mẻ chưa) qua tank nữa như bản cũ (khi đó còn gộp được mẻ "planned").
    _run_batch_to_completed(client, admin_h, b1["batch_id"])
    _run_batch_to_completed(client, admin_h, b2["batch_id"])

    tank = client.post("/api/batch-tanks", headers=admin_h,
                       json={"batch_ids": [b1["batch_id"], b2["batch_id"]], "tank_code": "TANK-DATE-01"})
    assert tank.status_code == 201, tank.text
    tank_id = tank.json()["tank_id"]
    assert tank.json()["vao_dich_start"] is not None  # cả 2 mẻ đã "chạy" (start_at) từ trước khi gộp
    assert tank.json()["vao_dich_end"] is not None    # cả 2 mẻ đã "hoàn thành" (end_at) từ trước khi gộp
    assert tank.json()["ferment_days_std"] == 14

    done = client.get(f"/api/batch-tanks/{tank_id}", headers=admin_h).json()
    assert done["vao_dich_end"] is not None
    assert done["days_elapsed"] is not None and done["days_elapsed"] >= 0
    assert done["ready_date"] is not None
