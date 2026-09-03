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


def test_order_available_until_complete_then_blocked(client, admin_h):
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

    blocked = client.post(f"/api/batch-filter-orders/{order['order_id']}/filter-lots", headers=admin_h,
                          json={"filter_lot_code": "FLOT-FO-02-DUP", "to_bbt": _make_bbt_line(client, admin_h, "FO02DUP")})
    assert blocked.status_code == 409, blocked.text


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
