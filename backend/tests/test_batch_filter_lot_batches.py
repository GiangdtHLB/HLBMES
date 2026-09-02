"""Test "1 mẻ lọc có thể rút CÙNG LÚC từ NHIỀU nguồn" cho Lô lọc (Mẻ SX) — mirror
FilterOrderTank (module "template" vs "mẻ") nhưng đảo lại: 1 mẻ (BatchFilterLotBatch) thuộc về
CẢ lô lọc, mỗi khoản rút/nguồn (BatchFilterLotBatchDraw) tách riêng (VD 1 lần chạy máy phối tank
lên men 01 + tank 02), nuoc_bai_khi_hl (nước DAW) phối thêm CHUNG cho cả mẻ. Có cờ "mẻ cuối"
(is_final_batch) độc lập với tổng hợp/khoá/xóa. Xem services/batch_pipeline.py::
add_filter_lot_batch/finish_filter_lot_batch/toggle_final_batch/delete_filter_lot_batch/
_sync_filter_lot_aggregate.
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


def _make_tank(client, admin_h, suffix, qty=1000):
    # batch_code giờ bắt buộc số nguyên (2026-09-02) — bỏ trống để tự sinh, không dùng suffix
    # (thường không phải số) làm mã mẻ; tank_code vẫn tự do nên vẫn dùng suffix để phân biệt.
    batch_id = _make_batch(client, admin_h, None)
    _run_batch_to_completed(client, admin_h, batch_id)
    tank = client.post("/api/batch-tanks", headers=admin_h,
                       json={"batch_ids": [batch_id], "tank_code": f"TANK-FLBATCH-{suffix}"})
    assert tank.status_code == 201, tank.text
    return tank.json()["tank_id"]


def _make_bbt_line(client, admin_h, suffix):
    r = client.post("/api/lines", headers=admin_h,
                    json={"code": f"BBT-{suffix}", "name": f"Tank thành phẩm {suffix}", "kind": "tank_bbt"})
    assert r.status_code == 201, r.text
    return r.json()["code"]


def _draw_single_source(client, admin_h, suffix, tank_qty=1000):
    tank_id = _make_tank(client, admin_h, suffix, tank_qty)
    to_bbt = _make_bbt_line(client, admin_h, suffix)
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": f"FLOT-FLBATCH-{suffix}", "to_bbt": to_bbt,
        "sources": [{"source_type": "tank", "source_tank_id": tank_id}],
    })
    assert draw.status_code == 201, draw.text
    filter_lot_id = draw.json()["filter_lot_id"]
    src = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()[0]
    return filter_lot_id, src["link_id"], tank_id


def _draw_two_sources(client, admin_h, suffix, tank_qty=1000):
    tank_a = _make_tank(client, admin_h, f"{suffix}A", tank_qty)
    tank_b = _make_tank(client, admin_h, f"{suffix}B", tank_qty)
    to_bbt = _make_bbt_line(client, admin_h, suffix)
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": f"FLOT-FLBATCH-{suffix}", "to_bbt": to_bbt,
        "sources": [{"source_type": "tank", "source_tank_id": tank_a},
                   {"source_type": "tank", "source_tank_id": tank_b}],
    })
    assert draw.status_code == 201, draw.text
    filter_lot_id = draw.json()["filter_lot_id"]
    sources = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()
    src_a = next(s for s in sources if s["source_tank_id"] == tank_a)["link_id"]
    src_b = next(s for s in sources if s["source_tank_id"] == tank_b)["link_id"]
    return filter_lot_id, src_a, src_b, tank_a, tank_b


def test_batch_auto_created_with_one_draw_per_source_on_create(client, admin_h):
    filter_lot_id, src_a, src_b, _tank_a, _tank_b = _draw_two_sources(client, admin_h, "AUTO01")
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    assert len(batches) == 1
    b = batches[0]
    assert b["ended_at"] is None
    assert {d["source_link_id"] for d in b["draws"]} == {src_a, src_b}
    assert all(d["dich_nha_hl"] is None for d in b["draws"])


def test_finish_batch_deducts_each_tank_by_its_own_draw_not_nuoc_bai_khi(client, admin_h):
    filter_lot_id, src_a, src_b, tank_a, tank_b = _draw_two_sources(client, admin_h, "DAW01")
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    batch_link_id = batches[0]["batch_link_id"]

    fin = client.put(f"/api/batch-filter-lots/batches/{batch_link_id}/finish", headers=admin_h,
                     json={"draws": [{"source_link_id": src_a, "dich_nha_hl": 300},
                                     {"source_link_id": src_b, "dich_nha_hl": 150}],
                          "nuoc_bai_khi_hl": 50})
    assert fin.status_code == 200, fin.text

    tank_a_after = client.get(f"/api/batch-tanks/{tank_a}", headers=admin_h).json()
    tank_b_after = client.get(f"/api/batch-tanks/{tank_b}", headers=admin_h).json()
    assert tank_a_after["on_hand"] == 700.0   # 1000 - 300
    assert tank_b_after["on_hand"] == 850.0   # 1000 - 150 (nước DAW không rút từ tank nào)

    fl = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()
    assert fl["v_dich_hl"] == 450.0   # 300 + 150
    assert fl["nuoc_bai_khi_hl"] == 50.0
    assert fl["volume_hl"] == 500.0   # tổng BBT = dịch 2 tank đã lọc + nước DAW
    assert fl["on_hand"] == 500.0
    assert fl["ended_at"] is not None   # mẻ duy nhất, đã kết thúc


def test_add_batch_blocked_until_previous_finished_then_aggregates_across_batches(client, admin_h):
    filter_lot_id, source_link_id, tank_id = _draw_single_source(client, admin_h, "MULTI01", tank_qty=1000)
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    first_batch_id = batches[0]["batch_link_id"]

    blocked = client.post(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h)
    assert blocked.status_code == 409, blocked.text   # mẻ đầu chưa kết thúc

    client.put(f"/api/batch-filter-lots/batches/{first_batch_id}/finish", headers=admin_h,
              json={"draws": [{"source_link_id": source_link_id, "dich_nha_hl": 200}],
                    "nuoc_bai_khi_hl": 20, "batch_seq_no": "1"})

    added = client.post(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h)
    assert added.status_code == 201, added.text
    second_batch_id = added.json()["batch_link_id"]
    assert added.json()["draws"][0]["source_link_id"] == source_link_id

    fl_mid = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()
    assert fl_mid["ended_at"] is None   # mẻ 2 chưa kết thúc -> lô lọc chưa "lọc xong hết"

    fin2 = client.put(f"/api/batch-filter-lots/batches/{second_batch_id}/finish", headers=admin_h,
                      json={"draws": [{"source_link_id": source_link_id, "dich_nha_hl": 150}],
                           "nuoc_bai_khi_hl": 10, "batch_seq_no": "2"})
    assert fin2.status_code == 200, fin2.text

    fl = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()
    assert fl["v_dich_hl"] == 350.0        # 200 + 150 (2 mẻ)
    assert fl["nuoc_bai_khi_hl"] == 30.0   # 20 + 10
    assert fl["volume_hl"] == 380.0
    assert fl["ended_at"] is not None      # cả 2 mẻ đã kết thúc

    tank_after = client.get(f"/api/batch-tanks/{tank_id}", headers=admin_h).json()
    assert tank_after["on_hand"] == 650.0  # 1000 - 200 - 150


def test_toggle_final_batch_flag(client, admin_h):
    filter_lot_id, source_link_id, _tank_id = _draw_single_source(client, admin_h, "FINAL01")
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    batch_link_id = batches[0]["batch_link_id"]
    assert batches[0]["is_final_batch"] is False

    on = client.post(f"/api/batch-filter-lots/batches/{batch_link_id}/toggle-final", headers=admin_h)
    assert on.status_code == 200, on.text
    assert on.json()["is_final_batch"] is True

    off = client.post(f"/api/batch-filter-lots/batches/{batch_link_id}/toggle-final", headers=admin_h)
    assert off.status_code == 200, off.text
    assert off.json()["is_final_batch"] is False


def test_delete_batch_refunds_each_source_and_blocked_when_last_of_filter_lot(client, admin_h):
    filter_lot_id, src_a, src_b, tank_a, tank_b = _draw_two_sources(client, admin_h, "DELBATCH01")
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    first_batch_id = batches[0]["batch_link_id"]
    client.put(f"/api/batch-filter-lots/batches/{first_batch_id}/finish", headers=admin_h,
              json={"draws": [{"source_link_id": src_a, "dich_nha_hl": 200},
                              {"source_link_id": src_b, "dich_nha_hl": 100}],
                    "nuoc_bai_khi_hl": 0})

    added = client.post(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h)
    second_batch_id = added.json()["batch_link_id"]
    client.put(f"/api/batch-filter-lots/batches/{second_batch_id}/finish", headers=admin_h,
              json={"draws": [{"source_link_id": src_a, "dich_nha_hl": 50},
                              {"source_link_id": src_b, "dich_nha_hl": 30}],
                    "nuoc_bai_khi_hl": 0})

    fl_mid = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()
    assert fl_mid["on_hand"] == 380.0   # 200+100+50+30

    deleted = client.delete(f"/api/batch-filter-lots/batches/{second_batch_id}", headers=admin_h)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["on_hand"] == 300.0   # hoàn 50+30 về 2 tank, chỉ còn mẻ 1

    tank_a_after = client.get(f"/api/batch-tanks/{tank_a}", headers=admin_h).json()
    tank_b_after = client.get(f"/api/batch-tanks/{tank_b}", headers=admin_h).json()
    assert tank_a_after["on_hand"] == 800.0   # 1000 - 200 (mẻ 2 đã hoàn 50)
    assert tank_b_after["on_hand"] == 900.0   # 1000 - 100 (mẻ 2 đã hoàn 30)

    # mẻ 1 giờ là mẻ DUY NHẤT của cả lô lọc -> chặn xóa
    blocked = client.delete(f"/api/batch-filter-lots/batches/{first_batch_id}", headers=admin_h)
    assert blocked.status_code == 409, blocked.text


def test_delete_batch_blocked_when_pack_lot_already_consumed_more_than_remaining(client, admin_h):
    filter_lot_id, source_link_id, _tank_id = _draw_single_source(client, admin_h, "DELGUARD01")
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    first_batch_id = batches[0]["batch_link_id"]
    client.put(f"/api/batch-filter-lots/batches/{first_batch_id}/finish", headers=admin_h,
              json={"draws": [{"source_link_id": source_link_id, "dich_nha_hl": 200}], "nuoc_bai_khi_hl": 0})
    added = client.post(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h)
    second_batch_id = added.json()["batch_link_id"]
    client.put(f"/api/batch-filter-lots/batches/{second_batch_id}/finish", headers=admin_h,
              json={"draws": [{"source_link_id": source_link_id, "dich_nha_hl": 100}], "nuoc_bai_khi_hl": 0})
    # tổng 300 hl -> tách 25000 lít (250 hl) lô thành phẩm, chỉ còn 50 hl < mẻ 2 (100 hl)
    appr = client.post(f"/api/batch-filter-lots/{filter_lot_id}/approve", headers=admin_h)
    assert appr.status_code == 200, appr.text
    to_bbt = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()["to_bbt"]
    pack = client.post("/api/batch-pack-lots", headers=admin_h,
                       json={"from_bbt": to_bbt, "qty": 25000, "pack_lot_code": "PKG-DELGUARD01",
                             "lot_no": "LOT-DELGUARD01"})
    assert pack.status_code == 201, pack.text

    blocked = client.delete(f"/api/batch-filter-lots/batches/{second_batch_id}", headers=admin_h)
    assert blocked.status_code == 409, blocked.text


def test_finish_rejects_draw_source_not_belonging_to_batch(client, admin_h):
    filter_lot_id, source_link_id, _tank_id = _draw_single_source(client, admin_h, "BADSRC01")
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    batch_link_id = batches[0]["batch_link_id"]
    bad = client.put(f"/api/batch-filter-lots/batches/{batch_link_id}/finish", headers=admin_h,
                     json={"draws": [{"source_link_id": "nonexistent-source", "dich_nha_hl": 100}],
                          "nuoc_bai_khi_hl": 0})
    assert bad.status_code in (400, 409), bad.text


def test_finish_batch_accepts_custom_started_at_and_ended_at(client, admin_h):
    """Popup "Sửa" mẻ lọc cho sửa cả giờ bắt đầu/kết thúc (yêu cầu người dùng 2026-09-01) — không
    còn tự động ghi đè ended_at = utcnow() mỗi lần "Sửa", và created_at ("Bắt đầu") sửa được."""
    filter_lot_id, source_link_id, _tank_id = _draw_single_source(client, admin_h, "TIMES01")
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    batch_link_id = batches[0]["batch_link_id"]

    fin = client.put(f"/api/batch-filter-lots/batches/{batch_link_id}/finish", headers=admin_h,
                     json={"draws": [{"source_link_id": source_link_id, "dich_nha_hl": 200}],
                          "nuoc_bai_khi_hl": 0,
                          "started_at": "2026-01-01T08:00:00", "ended_at": "2026-01-01T09:30:00"})
    assert fin.status_code == 200, fin.text

    b = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()[0]
    assert b["created_at"].startswith("2026-01-01T08:00:00")
    assert b["ended_at"].startswith("2026-01-01T09:30:00")

    # Sửa lại (không đổi giờ bắt đầu, đổi giờ kết thúc) -> created_at giữ nguyên nếu không truyền started_at.
    fin2 = client.put(f"/api/batch-filter-lots/batches/{batch_link_id}/finish", headers=admin_h,
                      json={"draws": [{"source_link_id": source_link_id, "dich_nha_hl": 250}],
                           "nuoc_bai_khi_hl": 0, "ended_at": "2026-01-01T10:00:00"})
    assert fin2.status_code == 200, fin2.text
    b2 = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()[0]
    assert b2["created_at"].startswith("2026-01-01T08:00:00")   # giữ nguyên, không bị ghi đè
    assert b2["ended_at"].startswith("2026-01-01T10:00:00")     # cập nhật theo giờ mới sửa
