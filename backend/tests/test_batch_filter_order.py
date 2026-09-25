"""Test "Lệnh lọc" (BatchFilterOrder) cho pipeline "Mẻ sản xuất" — mirror UX của FilterOrder
(module Nấu-Lọc-Chiết cũ): khai báo nguồn (tank/lô lọc lại) + SL kế hoạch TRƯỚC, rồi tạo Lô lọc
thật (BatchFilterLot) bằng cách CHỌN 1 lệnh lọc còn dùng được — không tự chọn lại nguồn.
Xem services/batch_pipeline.py::create_filter_order/draw_from_filter_order.
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
    return b.json()["batch_id"]


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


def _make_tank(client, admin_h, batch_code, tank_code):
    batch_id = _make_batch(client, admin_h, batch_code)
    _run_batch_to_completed(client, admin_h, batch_id)
    r = client.post("/api/batch-tanks", headers=admin_h,
                    json={"batch_ids": [batch_id], "tank_code": tank_code})
    assert r.status_code == 201, r.text
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


def test_create_order_single_tank_and_draw_filter_lot(client, admin_h):
    tank = _make_tank(client, admin_h, "1", "TANK-FO-01")
    order = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-FO-01",
        "sources": [{"source_type": "tank", "source_tank_id": tank["tank_id"], "planned_v_dich_hl": 900}],
    })
    assert order.status_code == 201, order.text
    o = order.json()
    assert o["blend_mode"] == "khong_phoi"
    assert o["planned_volume_hl"] == 900
    assert o["is_complete"] is False and o["consumed_downstream"] is False and o["lot_count"] == 0

    sources = client.get(f"/api/batch-filter-orders/{o['order_id']}/sources", headers=admin_h).json()
    assert len(sources) == 1 and sources[0]["source_label"] == "TANK-FO-01"

    draw = client.post(f"/api/batch-filter-orders/{o['order_id']}/filter-lots", headers=admin_h,
                       json={"filter_lot_code": "FLOT-FO-01", "to_bbt": _make_bbt_line(client, admin_h, "FO01")})
    assert draw.status_code == 201, draw.text
    fl = draw.json()
    assert fl["order_id"] == o["order_id"]

    fl_sources = client.get(f"/api/batch-filter-lots/{fl['filter_lot_id']}/sources", headers=admin_h).json()
    assert len(fl_sources) == 1 and fl_sources[0]["source_tank_id"] == tank["tank_id"]

    order_after_create = client.get(f"/api/batch-filter-orders/{o['order_id']}", headers=admin_h).json()
    assert order_after_create["lot_count"] == 1 and order_after_create["is_complete"] is False   # chưa kết thúc nguồn


def test_order_auto_completes_and_locks_when_volume_reached(client, admin_h):
    """Yêu cầu người dùng 2026-09-23 (làm rõ lại): "sản lượng thực tế >= sản lượng kế hoạch - sai
    số thì lệnh lọc đó được coi là hoàn thành" — is_complete=True (đủ SL kế hoạch) TỰ ĐỘNG chuyển
    status="hoan_thanh", KHÔNG cần bấm nút, và tự chặn tạo thêm lô lọc/bấm "Hoàn thành lệnh lọc"
    (nút đó chỉ dành cho dừng sớm khi CHƯA đủ SL, xem test_finish_order_allows_early_stop...)."""
    tank = _make_tank(client, admin_h, "2", "TANK-FO-02")
    order = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-FO-02",
        "sources": [{"source_type": "tank", "source_tank_id": tank["tank_id"], "planned_v_dich_hl": 900}],
    }).json()

    draw = client.post(f"/api/batch-filter-orders/{order['order_id']}/filter-lots", headers=admin_h,
                       json={"filter_lot_code": "FLOT-FO-02", "to_bbt": _make_bbt_line(client, admin_h, "FO02")}).json()
    src = client.get(f"/api/batch-filter-lots/{draw['filter_lot_id']}/sources", headers=admin_h).json()[0]
    fin = _finish_source(client, admin_h, src, 900)
    assert fin.status_code == 200, fin.text

    order_after = client.get(f"/api/batch-filter-orders/{order['order_id']}", headers=admin_h).json()
    assert order_after["is_complete"] is True
    assert order_after["actual_volume_hl"] == 900
    assert order_after["status"] == "hoan_thanh"   # tự động, KHÔNG cần bấm gì
    assert order_after["completed"] is False        # KHÔNG do bấm nút — completed_by vẫn trống
    lot_after_finish = client.get(f"/api/batch-filter-lots/{draw['filter_lot_id']}", headers=admin_h).json()
    assert lot_after_finish["status"] == "dang_loc"   # Lô lọc con KHÔNG tự hoàn thành theo

    # Đã tự động hoàn thành -> không tạo thêm lô lọc được nữa.
    blocked = client.post(f"/api/batch-filter-orders/{order['order_id']}/filter-lots", headers=admin_h,
                          json={"filter_lot_code": "FLOT-FO-02-DUP", "to_bbt": _make_bbt_line(client, admin_h, "FO02DUP")})
    assert blocked.status_code == 409, blocked.text

    # Bấm "Hoàn thành lệnh lọc" khi đã tự động hoàn thành rồi -> chặn, không cần bấm.
    finish = client.post(f"/api/batch-filter-orders/{order['order_id']}/finish", headers=admin_h)
    assert finish.status_code == 409, finish.text
    assert "không cần bấm" in finish.json()["detail"]


def test_finish_order_allows_early_stop_before_volume_target_reached(client, admin_h):
    """Nút "Hoàn thành lệnh lọc" dùng để vận hành CHỦ ĐỘNG dừng sớm khi CHƯA đủ SL kế hoạch (VD
    chỉ lọc một nửa kế hoạch rồi quyết định không lọc thêm nữa) — yêu cầu người dùng 2026-09-23."""
    tank = _make_tank(client, admin_h, "12", "TANK-FO-02B")
    order = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-FO-02B",
        "sources": [{"source_type": "tank", "source_tank_id": tank["tank_id"], "planned_v_dich_hl": 900}],
    }).json()

    no_lot = client.post(f"/api/batch-filter-orders/{order['order_id']}/finish", headers=admin_h)
    assert no_lot.status_code == 409, no_lot.text   # chưa có lô lọc nào

    draw = client.post(f"/api/batch-filter-orders/{order['order_id']}/filter-lots", headers=admin_h,
                       json={"filter_lot_code": "FLOT-FO-02B", "to_bbt": _make_bbt_line(client, admin_h, "FO02B")}).json()
    src = client.get(f"/api/batch-filter-lots/{draw['filter_lot_id']}/sources", headers=admin_h).json()[0]
    _finish_source(client, admin_h, src, 500)   # 500 < 900 kế hoạch -> is_complete vẫn False

    order_mid = client.get(f"/api/batch-filter-orders/{order['order_id']}", headers=admin_h).json()
    assert order_mid["is_complete"] is False and order_mid["status"] == "dang_loc"

    # Dừng sớm — vận hành chủ động bấm "Hoàn thành lệnh lọc" dù chưa đủ SL kế hoạch.
    finish = client.post(f"/api/batch-filter-orders/{order['order_id']}/finish", headers=admin_h)
    assert finish.status_code == 200, finish.text
    assert finish.json()["status"] == "hoan_thanh"
    assert finish.json()["completed_by"] == "admin"

    # Bấm lần 2 -> chặn (đã hoàn thành rồi).
    again = client.post(f"/api/batch-filter-orders/{order['order_id']}/finish", headers=admin_h)
    assert again.status_code == 409, again.text

    # Đã hoàn thành -> không tạo thêm lô lọc được nữa.
    blocked = client.post(f"/api/batch-filter-orders/{order['order_id']}/filter-lots", headers=admin_h,
                          json={"filter_lot_code": "FLOT-FO-02B-DUP", "to_bbt": _make_bbt_line(client, admin_h, "FO02BDUP")})
    assert blocked.status_code == 409, blocked.text


def test_order_auto_completes_when_source_tank_drained_even_below_planned(client, admin_h):
    """Yêu cầu người dùng 2026-09-25: "khi lô lên men đó đã báo lọc hết, thì toàn bộ lệnh lọc đi
    theo lô đó sẽ sang hoàn thành luôn" — tank nguồn hao hụt thật (ít dịch hơn kế hoạch) khiến
    is_complete KHÔNG BAO GIỜ đạt, nhưng tank đã rút cạn (on_hand=0) thì lệnh lọc vẫn tự động
    "hoàn thành", không cần đợi is_complete lẫn không cần bấm nút thủ công."""
    tank = _make_tank(client, admin_h, "13", "TANK-FO-DRAINED")
    tank_before = client.get(f"/api/batch-tanks/{tank['tank_id']}", headers=admin_h).json()
    full_volume = tank_before["volume_hl"]
    assert full_volume > 0

    # Kế hoạch CỐ Ý lớn hơn hẳn tồn thật của tank -> is_complete sẽ không bao giờ đạt được.
    order = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-FO-DRAINED",
        "sources": [{"source_type": "tank", "source_tank_id": tank["tank_id"], "planned_v_dich_hl": full_volume * 3}],
    }).json()

    draw = client.post(f"/api/batch-filter-orders/{order['order_id']}/filter-lots", headers=admin_h,
                       json={"filter_lot_code": "FLOT-FO-DRAINED", "to_bbt": _make_bbt_line(client, admin_h, "FODRAINED")}).json()
    src = client.get(f"/api/batch-filter-lots/{draw['filter_lot_id']}/sources", headers=admin_h).json()[0]

    # Rút HẾT sạch tồn thật của tank (không đủ so với kế hoạch) -> tank chuyển "da_loc_het".
    fin = _finish_source(client, admin_h, src, full_volume)
    assert fin.status_code == 200, fin.text
    tank_after = client.get(f"/api/batch-tanks/{tank['tank_id']}", headers=admin_h).json()
    assert tank_after["status"] == "da_loc_het"
    assert tank_after["on_hand"] <= 1e-6

    order_after = client.get(f"/api/batch-filter-orders/{order['order_id']}", headers=admin_h).json()
    assert order_after["is_complete"] is False   # chưa đủ SL kế hoạch (planned = full_volume * 3)
    assert order_after["tank_sources_drained"] is True
    assert order_after["status"] == "hoan_thanh"
    assert order_after["completed"] is False   # tự động, KHÔNG do bấm nút

    # Đã tự động hoàn thành -> không tạo thêm lô lọc được nữa.
    blocked = client.post(f"/api/batch-filter-orders/{order['order_id']}/filter-lots", headers=admin_h,
                          json={"filter_lot_code": "FLOT-FO-DRAINED-DUP", "to_bbt": _make_bbt_line(client, admin_h, "FODRAINEDDUP")})
    assert blocked.status_code == 409, blocked.text

    # Bấm "Hoàn thành lệnh lọc" thủ công khi đã tự động hoàn thành rồi -> chặn, không cần bấm.
    finish = client.post(f"/api/batch-filter-orders/{order['order_id']}/finish", headers=admin_h)
    assert finish.status_code == 409, finish.text
    assert "không cần bấm" in finish.json()["detail"]


def test_blend_order_needs_all_tank_sources_drained_not_just_one(client, admin_h):
    """Lệnh lọc PHỐI nhiều tank — chỉ 1 trong số các tank nguồn "lọc hết" thì CHƯA đủ để tự động
    hoàn thành, phải HẾT CẢ (yêu cầu người dùng 2026-09-25, áp dụng đúng cho trường hợp phối)."""
    tank_a = _make_tank(client, admin_h, "14", "TANK-FO-BLEND-A")
    tank_b = _make_tank(client, admin_h, "15", "TANK-FO-BLEND-B")
    vol_a = client.get(f"/api/batch-tanks/{tank_a['tank_id']}", headers=admin_h).json()["volume_hl"]
    vol_b = client.get(f"/api/batch-tanks/{tank_b['tank_id']}", headers=admin_h).json()["volume_hl"]

    order = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-FO-BLEND-DRAIN", "blend_mode": "phoi",
        "sources": [
            {"source_type": "tank", "source_tank_id": tank_a["tank_id"], "planned_v_dich_hl": vol_a * 3},
            {"source_type": "tank", "source_tank_id": tank_b["tank_id"], "planned_v_dich_hl": vol_b * 3},
        ],
    }).json()

    draw = client.post(f"/api/batch-filter-orders/{order['order_id']}/filter-lots", headers=admin_h,
                       json={"filter_lot_code": "FLOT-FO-BLEND-DRAIN", "to_bbt": _make_bbt_line(client, admin_h, "FOBLENDDRAIN")}).json()
    sources = client.get(f"/api/batch-filter-lots/{draw['filter_lot_id']}/sources", headers=admin_h).json()
    src_a = next(s for s in sources if s["source_tank_id"] == tank_a["tank_id"])
    src_b = next(s for s in sources if s["source_tank_id"] == tank_b["tank_id"])

    # Chỉ rút hết tank A — tank B vẫn còn nguyên (chưa rút gì).
    fin_a = _finish_source(client, admin_h, src_a, vol_a)
    assert fin_a.status_code == 200, fin_a.text

    mid = client.get(f"/api/batch-filter-orders/{order['order_id']}", headers=admin_h).json()
    assert mid["tank_sources_drained"] is False   # tank B chưa hết -> CHƯA tự động hoàn thành
    assert mid["status"] == "dang_loc"

    # Rút hết nốt tank B -> CẢ HAI đã lọc hết -> lệnh tự động hoàn thành.
    fin_b = _finish_source(client, admin_h, src_b, vol_b)
    assert fin_b.status_code == 200, fin_b.text

    done = client.get(f"/api/batch-filter-orders/{order['order_id']}", headers=admin_h).json()
    assert done["tank_sources_drained"] is True
    assert done["status"] == "hoan_thanh"


def test_order_blocked_after_pack_lot_split(client, admin_h):
    tank = _make_tank(client, admin_h, "3", "TANK-FO-03")
    order = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-FO-03",
        "sources": [{"source_type": "tank", "source_tank_id": tank["tank_id"], "planned_v_dich_hl": 2000}],
    }).json()   # planned lớn hơn thực tế rút -> is_complete vẫn False sau khi finish 1 phần

    draw = client.post(f"/api/batch-filter-orders/{order['order_id']}/filter-lots", headers=admin_h,
                       json={"filter_lot_code": "FLOT-FO-03", "to_bbt": _make_bbt_line(client, admin_h, "FO03")}).json()
    src = client.get(f"/api/batch-filter-lots/{draw['filter_lot_id']}/sources", headers=admin_h).json()[0]
    _finish_source(client, admin_h, src, 900)

    order_mid = client.get(f"/api/batch-filter-orders/{order['order_id']}", headers=admin_h).json()
    assert order_mid["is_complete"] is False    # 900 < 2000 kế hoạch -> vẫn còn dùng được

    pack = client.post(f"/api/batch-filter-lots/{draw['filter_lot_id']}/pack-lots", headers=admin_h,
                       json={"qty": 500, "pack_lot_code": "PKG-FO-03", "lot_no": "LOT-FO-03"})
    assert pack.status_code == 201, pack.text

    order_after = client.get(f"/api/batch-filter-orders/{order['order_id']}", headers=admin_h).json()
    assert order_after["consumed_downstream"] is True

    blocked = client.post(f"/api/batch-filter-orders/{order['order_id']}/filter-lots", headers=admin_h,
                          json={"filter_lot_code": "FLOT-FO-03-DUP", "to_bbt": _make_bbt_line(client, admin_h, "FO03DUP")})
    assert blocked.status_code == 409, blocked.text


def test_blend_mode_validation_and_auto_beer_type(client, admin_h):
    tank1 = _make_tank(client, admin_h, "4", "TANK-FO-04A")
    tank2 = _make_tank(client, admin_h, "5", "TANK-FO-04B")

    single_but_phoi = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-FO-04-BAD", "blend_mode": "phoi",
        "sources": [{"source_type": "tank", "source_tank_id": tank1["tank_id"], "planned_v_dich_hl": 500}],
    })
    assert single_but_phoi.status_code == 409, single_but_phoi.text

    blend = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-FO-04",
        "sources": [{"source_type": "tank", "source_tank_id": tank1["tank_id"], "planned_v_dich_hl": 500},
                    {"source_type": "tank", "source_tank_id": tank2["tank_id"], "planned_v_dich_hl": 500}],
    })
    assert blend.status_code == 201, blend.text
    assert blend.json()["blend_mode"] == "phoi"
    assert blend.json()["planned_volume_hl"] == 1000


def test_refilter_source_requires_reason(client, admin_h):
    tank = _make_tank(client, admin_h, "6", "TANK-FO-05")
    order1 = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-FO-05A",
        "sources": [{"source_type": "tank", "source_tank_id": tank["tank_id"], "planned_v_dich_hl": 900}],
    }).json()
    draw1 = client.post(f"/api/batch-filter-orders/{order1['order_id']}/filter-lots", headers=admin_h,
                        json={"filter_lot_code": "FLOT-FO-05", "to_bbt": _make_bbt_line(client, admin_h, "FO05")}).json()

    missing_reason = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-FO-05B",
        "sources": [{"source_type": "filter_lot", "source_filter_lot_id": draw1["filter_lot_id"],
                    "planned_v_dich_hl": 500}],
    })
    assert missing_reason.status_code == 409, missing_reason.text

    ok = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-FO-05B",
        "sources": [{"source_type": "filter_lot", "source_filter_lot_id": draw1["filter_lot_id"],
                    "reason": "Lọc lại do chưa đạt độ trong", "planned_v_dich_hl": 500}],
    })
    assert ok.status_code == 201, ok.text


def test_delete_order_blocked_once_filter_lot_created(client, admin_h):
    tank = _make_tank(client, admin_h, "7", "TANK-FO-06")
    order = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-FO-06",
        "sources": [{"source_type": "tank", "source_tank_id": tank["tank_id"], "planned_v_dich_hl": 900}],
    }).json()
    client.post(f"/api/batch-filter-orders/{order['order_id']}/filter-lots", headers=admin_h,
               json={"filter_lot_code": "FLOT-FO-06", "to_bbt": _make_bbt_line(client, admin_h, "FO06")})

    blocked = client.delete(f"/api/batch-filter-orders/{order['order_id']}", headers=admin_h)
    assert blocked.status_code == 409, blocked.text

    tank2 = _make_tank(client, admin_h, "8", "TANK-FO-06B")
    order2 = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-FO-06B",
        "sources": [{"source_type": "tank", "source_tank_id": tank2["tank_id"], "planned_v_dich_hl": 900}],
    }).json()
    ok = client.delete(f"/api/batch-filter-orders/{order2['order_id']}", headers=admin_h)
    assert ok.status_code == 204, ok.text
    assert client.get(f"/api/batch-filter-orders/{order2['order_id']}", headers=admin_h).status_code == 404


def test_filter_lot_requires_to_bbt_and_blocks_occupied_tank(client, admin_h):
    tank = _make_tank(client, admin_h, "9", "TANK-FO-07")
    order = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-FO-07",
        "sources": [{"source_type": "tank", "source_tank_id": tank["tank_id"], "planned_v_dich_hl": 900}],
    }).json()

    missing = client.post(f"/api/batch-filter-orders/{order['order_id']}/filter-lots", headers=admin_h,
                          json={"filter_lot_code": "FLOT-FO-07"})
    assert missing.status_code == 422, missing.text   # to_bbt bắt buộc ở schema

    bbt_code = _make_bbt_line(client, admin_h, "FO07")
    before = client.get("/api/batch-filter-lots/available-bbt-lines", headers=admin_h).json()
    row_before = next(r for r in before if r["code"] == bbt_code)
    assert row_before["occupied"] is False

    draw = client.post(f"/api/batch-filter-orders/{order['order_id']}/filter-lots", headers=admin_h,
                       json={"filter_lot_code": "FLOT-FO-07", "to_bbt": bbt_code})
    assert draw.status_code == 201, draw.text
    assert draw.json()["to_bbt"] == bbt_code

    # Chưa kết thúc nguồn -> tank BBT vẫn coi là đang bị chiếm (all_finished=False)
    mid = client.get("/api/batch-filter-lots/available-bbt-lines", headers=admin_h).json()
    row_mid = next(r for r in mid if r["code"] == bbt_code)
    assert row_mid["occupied"] is True

    tank2 = _make_tank(client, admin_h, "10", "TANK-FO-07B")
    order2 = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-FO-07B",
        "sources": [{"source_type": "tank", "source_tank_id": tank2["tank_id"], "planned_v_dich_hl": 900}],
    }).json()
    blocked = client.post(f"/api/batch-filter-orders/{order2['order_id']}/filter-lots", headers=admin_h,
                          json={"filter_lot_code": "FLOT-FO-07B", "to_bbt": bbt_code})
    assert blocked.status_code == 409, blocked.text
    assert "chiếm dụng" in blocked.json()["detail"]

    unknown_bbt = client.post(f"/api/batch-filter-orders/{order2['order_id']}/filter-lots", headers=admin_h,
                              json={"filter_lot_code": "FLOT-FO-07C", "to_bbt": "NO-SUCH-BBT-CODE"})
    assert unknown_bbt.status_code == 404, unknown_bbt.text

    # Kết thúc nguồn + chưa duyệt KCS -> tank BBT hết bị chiếm dụng nếu chưa duyệt, dù còn dịch
    # (nhiều lô được phép cùng đổ vào 1 tank TRƯỚC khi duyệt KCS).
    src = client.get(f"/api/batch-filter-lots/{draw.json()['filter_lot_id']}/sources", headers=admin_h).json()[0]
    _finish_source(client, admin_h, src, 900)
    freed = client.get("/api/batch-filter-lots/available-bbt-lines", headers=admin_h).json()
    row_freed = next(r for r in freed if r["code"] == bbt_code)
    assert row_freed["occupied"] is False

    # Sau khi duyệt KCS (còn dịch) -> tank BBT bị chiếm dụng trở lại (chặn đổ thêm mẻ khác vào).
    approve = client.post(f"/api/batch-filter-lots/{draw.json()['filter_lot_id']}/approve", headers=admin_h)
    assert approve.status_code == 200, approve.text
    reoccupied = client.get("/api/batch-filter-lots/available-bbt-lines", headers=admin_h).json()
    row_reoccupied = next(r for r in reoccupied if r["code"] == bbt_code)
    assert row_reoccupied["occupied"] is True


def test_update_order_edits_planned_qty_blocked_after_filter_lot(client, admin_h):
    """Yêu cầu người dùng 2026-09-23: "lệnh lọc chưa hoàn thành thì cho thêm nút sửa, để tôi sửa
    số lượng theo kế hoạch, số lượng vật tư"."""
    mat = client.post("/api/materials", headers=admin_h,
                      json={"code": "MAT-FO-UPD", "name": "Bột trợ lọc FO update", "uom": "kg"})
    assert mat.status_code == 201, mat.text
    material_id = mat.json()["material_id"]
    recv = client.post("/api/warehouse/receive", headers=admin_h,
                       json={"lot_code": "LOT-FO-UPD", "material_id": material_id,
                             "quantity": 100, "uom": "kg", "location": "Kho công ty"})
    assert recv.status_code == 200, recv.text

    tank = _make_tank(client, admin_h, "11", "TANK-FO-08")
    order = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-FO-08",
        "sources": [{"source_type": "tank", "source_tank_id": tank["tank_id"], "planned_v_dich_hl": 900}],
        "lines": [{"material_id": material_id, "material_name": "Bột trợ lọc FO update",
                  "uom": "kg", "qty_planned": 5}],
    }).json()
    src = client.get(f"/api/batch-filter-orders/{order['order_id']}/sources", headers=admin_h).json()[0]
    line = client.get(f"/api/batch-filter-orders/{order['order_id']}/materials", headers=admin_h).json()[0]

    # Sửa SL dự kiến của nguồn + SL kế hoạch của vật tư.
    upd = client.put(f"/api/batch-filter-orders/{order['order_id']}", headers=admin_h, json={
        "sources": [{"link_id": src["link_id"], "planned_v_dich_hl": 850}],
        "lines": [{"line_id": line["line_id"], "qty_planned": 20}],
    })
    assert upd.status_code == 200, upd.text
    assert upd.json()["planned_volume_hl"] == 850
    sources_after = client.get(f"/api/batch-filter-orders/{order['order_id']}/sources", headers=admin_h).json()
    assert sources_after[0]["planned_v_dich_hl"] == 850
    lines_after = client.get(f"/api/batch-filter-orders/{order['order_id']}/materials", headers=admin_h).json()
    assert lines_after[0]["qty_planned"] == 20

    # Sửa vượt quá tồn kho (100kg đã nhập) -> chặn, không ghi gì cả (kể cả nguồn).
    over = client.put(f"/api/batch-filter-orders/{order['order_id']}", headers=admin_h, json={
        "sources": [{"link_id": src["link_id"], "planned_v_dich_hl": 500}],
        "lines": [{"line_id": line["line_id"], "qty_planned": 9999}],
    })
    assert over.status_code == 409, over.text
    unchanged = client.get(f"/api/batch-filter-orders/{order['order_id']}/sources", headers=admin_h).json()
    assert unchanged[0]["planned_v_dich_hl"] == 850   # vẫn giữ giá trị đã sửa thành công lần trước

    # Đã có lô lọc tạo từ lệnh -> không sửa được nữa.
    client.post(f"/api/batch-filter-orders/{order['order_id']}/filter-lots", headers=admin_h,
               json={"filter_lot_code": "FLOT-FO-08", "to_bbt": _make_bbt_line(client, admin_h, "FO08")})
    blocked = client.put(f"/api/batch-filter-orders/{order['order_id']}", headers=admin_h, json={
        "sources": [{"link_id": src["link_id"], "planned_v_dich_hl": 700}],
    })
    assert blocked.status_code == 409, blocked.text
