"""Test GET /api/reports/dashboard-summary đếm "Lệnh nấu" theo Lệnh sản xuất (BrewOrder) —
sau khi bỏ lớp "lệnh nấu lớn" (BrewMasterOrder), mỗi BrewOrder đứng phẳng, đếm thẳng 1:1 với
số lệnh người dùng thực sự tạo ra (services/dashboard.py::production_summary)."""

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


def test_dashboard_counts_brew_orders(client, admin_h):
    before = client.get("/api/reports/dashboard-summary", headers=admin_h).json()

    created1 = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": "LN-DASH-TEST-1", "auto_from_bom": False, "planned_volume_hl": 100.0})
    assert created1.status_code == 201, created1.text
    created2 = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": "LN-DASH-TEST-2", "auto_from_bom": False, "planned_volume_hl": 100.0})
    assert created2.status_code == 201, created2.text

    after = client.get("/api/reports/dashboard-summary", headers=admin_h).json()
    assert after["lenh_nau"]["total"] == before["lenh_nau"]["total"] + 2


def _make_batch(client, admin_h, batch_code):
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(x for x in vers if x["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                          "batch_code": batch_code, "planned_qty": 1000, "allow_shortage": True})
    assert b.status_code == 201, b.text
    return b.json()["batch_id"]


def _run_batch_to_completed(client, admin_h, batch_id):
    for target in ("ready", "running"):
        r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": target})
        assert r.status_code == 200, r.text
    aq = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": 1000})
    assert aq.status_code == 200, aq.text
    fin = client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={})
    assert fin.status_code == 200, fin.text
    r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "completed"})
    assert r.status_code == 200, r.text


def test_dashboard_stat_cards_source_from_new_batch_pipeline(client, admin_h):
    """6 thẻ "Lệnh & mẻ sản xuất" phải phản ánh pipeline "Mẻ sản xuất" mới (BatchExecution/
    BatchTank/BatchFilterLot(Batch)/BatchPackLot), không phải module Nấu-Lọc-Chiết cũ. "Mẻ nấu"/
    "Mẻ lọc"/"Mẻ chiết" đều hiện TỔNG SỐ cộng dồn (yêu cầu người dùng 2026-09-02: "hiển thị tất
    cả số lượng ra, bên dưới có ghi chú rồi" — total KHÔNG giảm khi 1 mẻ hoàn thành, chỉ chuyển
    từ "đang thực hiện" sang "hoàn thành" trong phần ghi chú). Riêng "Tank đang lên men" CHỈ tính
    tank còn đúng nghĩa đang lên men (status "len_men"/"cho_loc") — tank đã bị rút dịch (dù chỉ
    một phần) đã sang công đoạn Lọc, không tính vào đây nữa (yêu cầu người dùng 2026-09-02: "tank
    đang lọc mà lại vẫn hiển thị đang lên men")."""
    before = client.get("/api/reports/dashboard-summary", headers=admin_h).json()

    # Mẻ nấu: total LUÔN tăng khi tạo mẻ, dù "running" hay đã "completed" — chỉ phần ghi chú
    # (hoàn thành/đang thực hiện) đổi theo trạng thái thật.
    batch_id = _make_batch(client, admin_h, None)
    r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "ready"})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "running"})
    assert r.status_code == 200, r.text
    after_running = client.get("/api/reports/dashboard-summary", headers=admin_h).json()
    assert after_running["me_nau"]["total"] == before["me_nau"]["total"] + 1
    assert after_running["me_nau"]["dang_thuc_hien"] == before["me_nau"]["dang_thuc_hien"] + 1
    assert after_running["me_nau"]["hoan_thanh"] == before["me_nau"]["hoan_thanh"]

    aq = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": 1000})
    assert aq.status_code == 200, aq.text
    fin = client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={})
    assert fin.status_code == 200, fin.text
    r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "completed"})
    assert r.status_code == 200, r.text
    after_batch_done = client.get("/api/reports/dashboard-summary", headers=admin_h).json()
    assert after_batch_done["me_nau"]["total"] == before["me_nau"]["total"] + 1  # total KHÔNG đổi khi xong
    assert after_batch_done["me_nau"]["hoan_thanh"] == before["me_nau"]["hoan_thanh"] + 1

    # Tank đang lên men: tank mới tạo (chưa rút gì) -> tính là đang lên men; rút MỘT PHẦN dịch
    # (chuyển sang "loc_1_phan", đã sang công đoạn Lọc) -> KHÔNG còn tính là đang lên men nữa,
    # dù total (số tank vật lý trong Danh mục) không đổi.
    line = client.post("/api/lines", headers=admin_h,
                       json={"code": "FV-DASHNEW-1", "name": "Tank dashnew", "kind": "tank"})
    assert line.status_code == 201, line.text
    tank = client.post("/api/batch-tanks", headers=admin_h,
                       json={"batch_ids": [batch_id], "tank_code": "TANK-DASHNEW-1", "tank_lm": "FV-DASHNEW-1"})
    assert tank.status_code == 201, tank.text
    tank_id = tank.json()["tank_id"]
    after_tank = client.get("/api/reports/dashboard-summary", headers=admin_h).json()
    assert after_tank["tank_len_men"]["total"] == before["tank_len_men"]["total"] + 1
    assert after_tank["tank_len_men"]["dang_su_dung"] == before["tank_len_men"]["dang_su_dung"] + 1

    bbt = client.post("/api/lines", headers=admin_h,
                      json={"code": "BBT-DASHNEW-1", "name": "BBT dashnew", "kind": "tank_bbt"})
    assert bbt.status_code == 201, bbt.text
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": "FLOT-DASHNEW-1", "to_bbt": "BBT-DASHNEW-1",
        "sources": [{"source_type": "tank", "source_tank_id": tank_id}],
    })
    assert draw.status_code == 201, draw.text
    filter_lot_id = draw.json()["filter_lot_id"]
    src = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()[0]
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    batch_link_id = batches[0]["batch_link_id"]
    # Mẻ lọc #1 vừa tạo (add_filter_lot_batch tự sinh khi tạo lô lọc) CHƯA "Kết thúc" -> total
    # tăng ngay, tính "đang thực hiện" (chưa có "hoàn thành" nào ở bước này).
    after_lot_created = client.get("/api/reports/dashboard-summary", headers=admin_h).json()
    assert after_lot_created["me_loc"]["total"] == before["me_loc"]["total"] + 1
    assert after_lot_created["me_loc"]["dang_thuc_hien"] == before["me_loc"]["dang_thuc_hien"] + 1

    # Rút MỘT PHẦN (500/1000 hl) rồi "Kết thúc" mẻ #1 -> tank chuyển "loc_1_phan" (đã sang Lọc,
    # không còn tính "đang lên men"); mẻ #1 chuyển từ "đang thực hiện" sang "hoàn thành" (total
    # "Mẻ lọc" KHÔNG đổi).
    partial = client.put(f"/api/batch-filter-lots/batches/{batch_link_id}/finish", headers=admin_h,
                        json={"draws": [{"source_link_id": src["link_id"], "dich_nha_hl": 500}],
                             "nuoc_bai_khi_hl": 0})
    assert partial.status_code == 200, partial.text
    after_partial_draw = client.get("/api/reports/dashboard-summary", headers=admin_h).json()
    assert after_partial_draw["tank_len_men"]["dang_su_dung"] == before["tank_len_men"]["dang_su_dung"]
    assert after_partial_draw["tank_len_men"]["total"] == before["tank_len_men"]["total"] + 1
    # Tank "loc_1_phan" (rút dở dang) đếm riêng vào "dang_loc" (yêu cầu người dùng 2026-09-02:
    # ghi chú thêm "số tank đang lọc") — KHÔNG gộp vào "trong" (trống thật sự).
    assert after_partial_draw["tank_len_men"]["dang_loc"] == before["tank_len_men"].get("dang_loc", 0) + 1
    assert after_partial_draw["me_loc"]["total"] == before["me_loc"]["total"] + 1
    assert after_partial_draw["me_loc"]["hoan_thanh"] == before["me_loc"]["hoan_thanh"] + 1

    # Thêm mẻ lọc #2 (CHƯA kết thúc) cho CÙNG lô lọc đó — tank vẫn "loc_1_phan" (không tính lại
    # là đang lên men), "Mẻ lọc" total tăng thêm 1 (mẻ #2, đang thực hiện).
    add2 = client.post(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h)
    assert add2.status_code == 201, add2.text
    after_batch2 = client.get("/api/reports/dashboard-summary", headers=admin_h).json()
    assert after_batch2["tank_len_men"]["dang_su_dung"] == before["tank_len_men"]["dang_su_dung"]
    assert after_batch2["me_loc"]["total"] == before["me_loc"]["total"] + 2
    assert after_batch2["me_loc"]["dang_thuc_hien"] == before["me_loc"]["dang_thuc_hien"] + 1

    # Kết thúc hẳn mẻ #2 (rút thêm cho đủ) -> chuyển sang "hoàn thành", total vẫn giữ nguyên +2.
    batch_link_id2 = add2.json()["batch_link_id"]
    fin = client.put(f"/api/batch-filter-lots/batches/{batch_link_id2}/finish", headers=admin_h,
                     json={"draws": [{"source_link_id": src["link_id"], "dich_nha_hl": 900}],
                          "nuoc_bai_khi_hl": 0})
    assert fin.status_code == 200, fin.text
    after_filter_done = client.get("/api/reports/dashboard-summary", headers=admin_h).json()
    assert after_filter_done["me_loc"]["total"] == before["me_loc"]["total"] + 2
    assert after_filter_done["me_loc"]["hoan_thanh"] == before["me_loc"]["hoan_thanh"] + 2
    assert after_filter_done["me_loc"]["dang_thuc_hien"] == before["me_loc"]["dang_thuc_hien"]

    pack = client.post(f"/api/batch-filter-lots/{filter_lot_id}/pack-lots", headers=admin_h,
                       json={"qty": 500, "pack_lot_code": "PKG-DASHNEW-1", "lot_no": "LOT-DASHNEW-1"})
    assert pack.status_code == 201, pack.text
    after_pack = client.get("/api/reports/dashboard-summary", headers=admin_h).json()
    assert after_pack["me_chiet"]["total"] == before["me_chiet"]["total"] + 1
    assert after_pack["me_chiet"]["hoan_thanh"] == before["me_chiet"]["hoan_thanh"]  # chưa duyệt KCS

    bna = client.get("/api/reports/bottled-not-approved", headers=admin_h).json()
    assert any(it["pack_lot_code"] == "PKG-DASHNEW-1" for it in bna["items"])


def _finish_one_me_loc(client, admin_h, suffix, dich_nha_hl):
    """Dựng đủ chuỗi Mẻ nấu -> Tank -> Lô lọc (pipeline mới) và "Kết thúc" 1 mẻ lọc với
    dich_nha_hl chỉ định, trả về filter_lot_id — dùng để test phân loại sản lượng lọc."""
    batch_id = _make_batch(client, admin_h, None)
    _run_batch_to_completed(client, admin_h, batch_id)
    line = client.post("/api/lines", headers=admin_h,
                       json={"code": f"FV-YIELD-{suffix}", "name": f"Tank yield {suffix}", "kind": "tank"})
    assert line.status_code == 201, line.text
    tank = client.post("/api/batch-tanks", headers=admin_h,
                       json={"batch_ids": [batch_id], "tank_code": f"TANK-YIELD-{suffix}",
                             "tank_lm": f"FV-YIELD-{suffix}"})
    assert tank.status_code == 201, tank.text
    tank_id = tank.json()["tank_id"]
    bbt = client.post("/api/lines", headers=admin_h,
                      json={"code": f"BBT-YIELD-{suffix}", "name": f"BBT yield {suffix}", "kind": "tank_bbt"})
    assert bbt.status_code == 201, bbt.text
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": f"FLOT-YIELD-{suffix}", "to_bbt": f"BBT-YIELD-{suffix}",
        "sources": [{"source_type": "tank", "source_tank_id": tank_id}],
    })
    assert draw.status_code == 201, draw.text
    filter_lot_id = draw.json()["filter_lot_id"]
    src = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()[0]
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    batch_link_id = batches[0]["batch_link_id"]
    fin = client.put(f"/api/batch-filter-lots/batches/{batch_link_id}/finish", headers=admin_h,
                     json={"draws": [{"source_link_id": src["link_id"], "dich_nha_hl": dich_nha_hl}],
                          "nuoc_bai_khi_hl": 0})
    assert fin.status_code == 200, fin.text
    return filter_lot_id


def test_low_yield_filter_alerts_source_from_new_batch_pipeline(client, admin_h):
    """Widget Dashboard "Sản lượng lọc thấp" (GET /api/reports/low-yield-filter-alerts, xem
    services/dashboard.py::low_yield_filter_alerts/_batch_filter_lot_yield_items) đổi nguồn sang
    pipeline "Mẻ sản xuất" mới (BatchFilterLotBatch), tính toán tương tự y hệt module cũ (yêu
    cầu người dùng 2026-09-02: "Sản lượng lọc thấp thì lấy theo mẻ của Lọc, tính toán tương tự
    như modul cũ") — chỉ gồm mẻ Thấp (mặc định ≤500L), sắp tăng dần theo V lọc (hụt nặng nhất
    lên đầu), không lẫn mẻ Bình thường/Cao."""
    low_filter_lot_id = _finish_one_me_loc(client, admin_h, "DASHLOW-A", 2)   # 200L -> Thấp
    lower_filter_lot_id = _finish_one_me_loc(client, admin_h, "DASHLOW-B", 1)  # 100L -> Thấp hơn
    high_filter_lot_id = _finish_one_me_loc(client, admin_h, "DASHHIGH", 25)   # 2500L -> Cao

    r = client.get("/api/reports/low-yield-filter-alerts", headers=admin_h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["low_l"] == 500.0
    ids = {it["filter_lot_id"] for it in data["items"]}
    assert low_filter_lot_id in ids and lower_filter_lot_id in ids
    assert high_filter_lot_id not in ids
    assert all(it["classification"] == "thap" for it in data["items"])
    v_ls = [it["v_l"] for it in data["items"]]
    assert v_ls == sorted(v_ls)

    r2 = client.get("/api/reports/low-yield-filter-alerts?limit=1", headers=admin_h)
    assert len(r2.json()["items"]) == 1
    assert r2.json()["items"][0]["v_l"] == 100.0
