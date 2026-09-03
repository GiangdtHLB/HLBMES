"""Test các khoảng trống vừa bổ sung cho BatchTank (Tank lên men, Mẻ SX) sau khi rà soát đối
chiếu với FermentRecord (module Nấu-Lọc-Chiết cũ):
1. Chỉ tiêu lên men chính + lên men phụ (2 stage riêng, không lẫn kết quả).
2. "Làm rỗng tank" — buộc tồn về 0 trong ngưỡng dung sai cấu hình (mirror empty_ferment_cct).
3. "Ghi chép lên men" — bảng thông tin đầu (manual_json) + bảng theo ngày.
4. Danh mục "Tank lên men" (ProductionLine kind=tank) + cờ đang chiếm dụng.
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
def kcs_h(client):
    return _login(client, "kcs", "123456")


@pytest.fixture(scope="module")
def vanhanh_h(client):
    return _login(client, "vanhanh", "123456")


def _make_group_with_param(client, admin_h, suffix):
    p = client.post("/api/qc/parameters", headers=admin_h,
                    json={"code": f"CT_{suffix}", "name": f"Chỉ tiêu {suffix}", "lsl": 1, "usl": 10})
    assert p.status_code == 201, p.text
    param_id = p.json()["param_id"]
    g = client.post("/api/qc/groups", headers=admin_h,
                    json={"code": f"GRP_{suffix}", "name": f"Nhóm {suffix}"})
    assert g.status_code == 201, g.text
    group_id = g.json()["group_id"]
    it = client.post(f"/api/qc/groups/{group_id}/items", headers=admin_h,
                     json={"param_id": param_id, "mandatory": True})
    assert it.status_code == 201, it.text
    return group_id, f"CT_{suffix}"


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


def _make_tank(client, admin_h, batch_code, tank_code, tank_lm=None):
    batch_id = _make_batch(client, admin_h, batch_code)
    _run_batch_to_completed(client, admin_h, batch_id)
    r = client.post("/api/batch-tanks", headers=admin_h,
                    json={"batch_ids": [batch_id], "tank_code": tank_code, "tank_lm": tank_lm})
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


def test_len_men_chinh_and_phu_do_not_share_recorded_values(client, admin_h):
    chinh_group, chinh_code = _make_group_with_param(client, admin_h, "TANKCHINH")
    phu_group, phu_code = _make_group_with_param(client, admin_h, "TANKPHU")
    client.post("/api/qc/stage-groups", headers=admin_h,
               json={"stage": "len_men_chinh", "group_id": chinh_group, "mandatory": True})
    client.post("/api/qc/stage-groups", headers=admin_h,
               json={"stage": "len_men_phu", "group_id": phu_group, "mandatory": True})

    tank = _make_tank(client, admin_h, "1", "TANK-GAP-01")
    scope_chinh = f"{tank['tank_id']}__len_men_chinh"
    scope_phu = f"{tank['tank_id']}__len_men_phu"

    rec = client.post("/api/brewing/qc-results", headers=admin_h,
                      json={"stage": "len_men_chinh", "scope_type": "batch_tank", "scope_id": scope_chinh,
                            "parameter": chinh_code, "value": 5, "lower_limit": 1, "upper_limit": 10})
    assert rec.status_code == 201, rec.text

    st_chinh = client.get(f"/api/brewing/qc-status?stage=len_men_chinh&scope_type=batch_tank&scope_id={scope_chinh}",
                          headers=admin_h).json()
    assert st_chinh["can_release"] is True

    st_phu = client.get(f"/api/brewing/qc-status?stage=len_men_phu&scope_type=batch_tank&scope_id={scope_phu}",
                        headers=admin_h).json()
    assert st_phu["pending"] == [phu_code]
    assert st_phu["can_release"] is False


def test_genealogy_shows_both_chinh_and_phu_qc_summary(client, admin_h):
    tank = _make_tank(client, admin_h, "2", "TANK-GAP-02")
    back = client.get("/api/trace/backward", headers=admin_h,
                      params={"node_type": "batch_tank", "node_id": tank["tank_id"]}).json()
    assert back["type"] == "batch_tank"
    stages = {q["stage"] for q in back["qc"]}
    assert stages == {"len_men_chinh", "len_men_phu"}


def test_empty_tank_within_tolerance_and_blocked_over_tolerance(client, admin_h):
    settings = client.get("/api/ops-settings", headers=admin_h).json()
    tol = settings["empty_cct_tolerance_hl"]

    tank = _make_tank(client, admin_h, "3", "TANK-GAP-03")
    # Rút hết gần như toàn bộ, chỉ để lại phần dư trong ngưỡng dung sai.
    order = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-TGAP-03",
        "sources": [{"source_type": "tank", "source_tank_id": tank["tank_id"], "planned_v_dich_hl": 1000}],
    }).json()
    draw = client.post(f"/api/batch-filter-orders/{order['order_id']}/filter-lots", headers=admin_h,
                       json={"filter_lot_code": "FLOT-TGAP-03", "to_bbt": _make_bbt_line(client, admin_h, "TGAP03")}).json()
    src = client.get(f"/api/batch-filter-lots/{draw['filter_lot_id']}/sources", headers=admin_h).json()[0]
    _finish_source(client, admin_h, src, 1000 - tol / 2)

    tank_after = client.get(f"/api/batch-tanks/{tank['tank_id']}", headers=admin_h).json()
    assert tank_after["on_hand"] == round(tol / 2, 3)

    ok = client.post(f"/api/batch-tanks/{tank['tank_id']}/empty", headers=admin_h)
    assert ok.status_code == 200, ok.text
    assert ok.json()["on_hand"] == 0.0

    already_empty = client.post(f"/api/batch-tanks/{tank['tank_id']}/empty", headers=admin_h)
    assert already_empty.status_code == 409, already_empty.text


def test_empty_tank_blocked_when_residual_exceeds_tolerance(client, admin_h):
    tank = _make_tank(client, admin_h, "4", "TANK-GAP-04")
    blocked = client.post(f"/api/batch-tanks/{tank['tank_id']}/empty", headers=admin_h)
    assert blocked.status_code == 409, blocked.text
    assert "vượt ngưỡng" in blocked.json()["detail"]


def test_over_draw_allows_negative_on_hand_with_am_status(client, admin_h):
    """Đồng hồ đo lúc lọc ra số VƯỢT tồn phần mềm đang có (VD tồn 1000 hl, đo ra 1001 hl) — CHO
    PHÉP ghi nhận (không chặn cứng), nhưng phải hiện rõ trạng thái "âm" riêng biệt (khác hẳn
    "da_loc_het" — 2 trạng thái ý nghĩa vật lý ngược nhau), và tank đó KHÔNG được coi là trống
    (vẫn chiếm dụng) cho tới khi "Làm rỗng tank" đưa về đúng 0 (yêu cầu người dùng 2026-09-02)."""
    line = client.post("/api/lines", headers=admin_h,
                       json={"code": "FV-GAPTEST-AM1", "name": "Tank test am", "kind": "tank"})
    assert line.status_code == 201, line.text
    tank = _make_tank(client, admin_h, "7", "TANK-GAP-07", tank_lm="FV-GAPTEST-AM1")
    order = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-TGAP-07",
        "sources": [{"source_type": "tank", "source_tank_id": tank["tank_id"], "planned_v_dich_hl": 1000}],
    }).json()
    draw = client.post(f"/api/batch-filter-orders/{order['order_id']}/filter-lots", headers=admin_h,
                       json={"filter_lot_code": "FLOT-TGAP-07", "to_bbt": _make_bbt_line(client, admin_h, "TGAP07")}).json()
    src = client.get(f"/api/batch-filter-lots/{draw['filter_lot_id']}/sources", headers=admin_h).json()[0]
    fin = _finish_source(client, admin_h, src, 1001)  # tồn chỉ có 1000 -> đo ra 1001, dư ra 1 hl âm
    assert fin.status_code == 200, fin.text

    tank_after = client.get(f"/api/batch-tanks/{tank['tank_id']}", headers=admin_h).json()
    assert tank_after["on_hand"] == -1.0
    assert tank_after["status"] == "am"
    assert "Âm" in tank_after["status_label"]

    # Tank vẫn coi là chiếm dụng dù tồn âm — KHÔNG được gộp mẻ nấu mới vào tank vật lý này.
    lines = client.get("/api/batch-tanks/available-lines", headers=admin_h).json()
    row = next(r for r in lines if r["code"] == "FV-GAPTEST-AM1")
    assert row["occupied"] is True

    # "Làm rỗng tank" phải xử lý được CẢ tồn âm (trong ngưỡng dung sai) — đưa đúng về 0.
    emptied = client.post(f"/api/batch-tanks/{tank['tank_id']}/empty", headers=admin_h)
    assert emptied.status_code == 200, emptied.text
    assert emptied.json()["on_hand"] == 0.0
    assert emptied.json()["status"] == "da_loc_het"


def test_empty_tank_rejects_negative_residual_beyond_tolerance(client, admin_h):
    tank = _make_tank(client, admin_h, "8", "TANK-GAP-08")
    order = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-TGAP-08",
        "sources": [{"source_type": "tank", "source_tank_id": tank["tank_id"], "planned_v_dich_hl": 1000}],
    }).json()
    draw = client.post(f"/api/batch-filter-orders/{order['order_id']}/filter-lots", headers=admin_h,
                       json={"filter_lot_code": "FLOT-TGAP-08", "to_bbt": _make_bbt_line(client, admin_h, "TGAP08")}).json()
    src = client.get(f"/api/batch-filter-lots/{draw['filter_lot_id']}/sources", headers=admin_h).json()[0]
    _finish_source(client, admin_h, src, 1050)  # dư ra 50 hl âm — vượt xa ngưỡng mặc định 2.0 hl
    over = client.post(f"/api/batch-tanks/{tank['tank_id']}/empty", headers=admin_h)
    assert over.status_code == 409, over.text
    assert "vượt ngưỡng" in over.json()["detail"]


def test_process_log_header_and_daily_readings(client, admin_h):
    tank = _make_tank(client, admin_h, "5", "TANK-GAP-05")
    tank_id = tank["tank_id"]

    initial = client.get(f"/api/batch-tanks/{tank_id}/process-log", headers=admin_h).json()
    assert initial["auto"]["so_tank"] is None
    assert "5" in initial["auto"]["so_me"]
    assert initial["manual"]["order_number"] is None
    assert initial["readings"] == []

    upd = client.put(f"/api/batch-tanks/{tank_id}/process-log", headers=admin_h, json={
        "order_number": "ORD-01", "batch_number": "BATCH-01", "kieu_men": "Ale",
        "mat_do_ml_b": 12.5, "note": "test note",
        "ha_phu_events": [{"at": "2026-08-01 08:00", "nguoi_lenh": "A", "nguoi_nhan_lenh": "B", "truc_ca": "C"}],
    })
    assert upd.status_code == 200, upd.text
    assert upd.json()["order_number"] == "ORD-01"
    assert upd.json()["ha_phu_events"][0]["nguoi_lenh"] == "A"
    assert upd.json()["note"] == "test note"

    readings = client.put(f"/api/batch-tanks/{tank_id}/process-log/readings", headers=admin_h, json={
        "readings": [
            {"day_no": 1, "reading_date": "2026-08-01", "nhiet_do_c": 18.0, "do_s": 12.0, "mat_do_tb": 50.0,
             "kcs": "dat", "truc_ca": "dat"},
            {"day_no": 2, "reading_date": "2026-08-02"},
        ],
    })
    assert readings.status_code == 200, readings.text
    day1 = next(r for r in readings.json() if r["day_no"] == 1)
    assert day1["measured_by"] == "admin" and day1["measured_at"] is not None
    assert day1["kcs_by"] == "admin"
    day2 = next(r for r in readings.json() if r["day_no"] == 2)
    assert day2["measured_by"] is None

    final = client.get(f"/api/batch-tanks/{tank_id}/process-log", headers=admin_h).json()
    assert final["manual"]["kieu_men"] == "Ale"
    assert len(final["readings"]) == 2


def test_available_tank_lines_reflects_occupied_state(client, admin_h):
    line = client.post("/api/lines", headers=admin_h,
                       json={"code": "FV-GAPTEST-01", "name": "Tank test gap", "kind": "tank"})
    assert line.status_code == 201, line.text

    before = client.get("/api/batch-tanks/available-lines", headers=admin_h).json()
    row = next(r for r in before if r["code"] == "FV-GAPTEST-01")
    assert row["occupied"] is False

    tank = _make_tank(client, admin_h, "6", "TANK-GAP-06", tank_lm="FV-GAPTEST-01")

    after = client.get("/api/batch-tanks/available-lines", headers=admin_h).json()
    row_after = next(r for r in after if r["code"] == "FV-GAPTEST-01")
    assert row_after["occupied"] is True

    # Rút hết + làm rỗng -> tank vật lý phải trống lại.
    order = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-TGAP-06",
        "sources": [{"source_type": "tank", "source_tank_id": tank["tank_id"], "planned_v_dich_hl": 1000}],
    }).json()
    draw = client.post(f"/api/batch-filter-orders/{order['order_id']}/filter-lots", headers=admin_h,
                       json={"filter_lot_code": "FLOT-TGAP-06", "to_bbt": _make_bbt_line(client, admin_h, "TGAP06")}).json()
    src = client.get(f"/api/batch-filter-lots/{draw['filter_lot_id']}/sources", headers=admin_h).json()[0]
    _finish_source(client, admin_h, src, 999)
    client.post(f"/api/batch-tanks/{tank['tank_id']}/empty", headers=admin_h)

    freed = client.get("/api/batch-tanks/available-lines", headers=admin_h).json()
    row_freed = next(r for r in freed if r["code"] == "FV-GAPTEST-01")
    assert row_freed["occupied"] is False


def test_tank_shows_dang_nau_until_all_merged_batches_finish(client, admin_h):
    """Tank gộp từ mẻ nấu CHƯA hoàn thành (chưa có end_at) phải hiện "Đang điền dịch" (status
    key vẫn giữ "dang_nau" nội bộ, chỉ đổi nhãn hiển thị theo yêu cầu người dùng 2026-09-02:
    "Trạng thái không phải là đang nấu, mà là đang điền dịch") — KHÔNG được coi là "Đang lên men"
    (len_men) dù có thể đã có dịch tồn từ CÁC mẻ khác đã xong cùng gộp — merge_batches_into_tank
    cho gộp mẻ ở bất kỳ trạng thái nào (kể cả chưa nấu xong), tank chỉ thật sự "đang lên men" khi
    TẤT CẢ mẻ đã gộp đều hoàn thành (yêu cầu người dùng 2026-09-02: "chưa kết thúc các mẻ nấu thì
    chưa được gọi là lên men... khi có dịch tồn ở tank lên men mà chưa kết thúc tất cả các mẻ sản
    xuất thì là đang nấu")."""
    # Mẻ 1: chưa hoàn thành (mới "running", chưa actual_qty/finish/completed).
    unfinished_id = _make_batch(client, admin_h, "10")
    r = client.post(f"/api/batches/{unfinished_id}/transition", headers=admin_h, json={"target": "ready"})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/batches/{unfinished_id}/transition", headers=admin_h, json={"target": "running"})
    assert r.status_code == 200, r.text

    line = client.post("/api/lines", headers=admin_h,
                       json={"code": "FV-DANGNAU-1", "name": "Tank dangnau", "kind": "tank"})
    assert line.status_code == 201, line.text
    tank = client.post("/api/batch-tanks", headers=admin_h,
                       json={"batch_ids": [unfinished_id], "tank_code": "TANK-DANGNAU-1",
                             "tank_lm": "FV-DANGNAU-1"})
    assert tank.status_code == 201, tank.text
    tank_id = tank.json()["tank_id"]
    got = client.get(f"/api/batch-tanks/{tank_id}", headers=admin_h).json()
    assert got["status"] == "dang_nau"
    assert got["status_label"] == "Đang điền dịch"

    # Gộp THÊM 1 mẻ ĐÃ hoàn thành vào CÙNG tank (qua batch-tank-link trực tiếp DB, vì API tạo
    # tank chỉ nhận batch_ids lúc tạo — mô phỏng đúng tình huống "tank đã có dịch tồn từ mẻ khác
    # nhưng còn 1 mẻ khác trong đó chưa xong") — trạng thái vẫn phải là "dang_nau", KHÔNG được
    # nhảy sang "len_men" dù giờ đã có volume/on_hand > 0.
    from app.database import SessionLocal
    from app.models.batch_pipeline import BatchTank, BatchTankLink
    from app.models.batches import BatchExecution
    finished_id = _make_batch(client, admin_h, "11")
    _run_batch_to_completed(client, admin_h, finished_id, actual_qty=500)
    db2 = SessionLocal()
    from app.common import new_id
    db2.add(BatchTankLink(link_id=new_id(), tank_id=tank_id, batch_id=finished_id))
    t = db2.get(BatchTank, tank_id)
    t.on_hand += 500
    t.volume_hl += 500
    db2.commit()
    db2.close()

    got2 = client.get(f"/api/batch-tanks/{tank_id}", headers=admin_h).json()
    assert got2["on_hand"] == 500
    assert got2["status"] == "dang_nau"

    # Hoàn thành nốt mẻ còn lại (đã ở "running" từ đầu test, không transition lại "ready") ->
    # tank chuyển sang "len_men" (đúng nghĩa đang lên men).
    aq = client.post(f"/api/batches/{unfinished_id}/actual-qty", headers=admin_h, json={"actual_qty": 300})
    assert aq.status_code == 200, aq.text
    fin = client.post(f"/api/batches/{unfinished_id}/finish", headers=admin_h, json={})
    assert fin.status_code == 200, fin.text
    r = client.post(f"/api/batches/{unfinished_id}/transition", headers=admin_h, json={"target": "completed"})
    assert r.status_code == 200, r.text
    db3 = SessionLocal()
    t2 = db3.get(BatchTank, tank_id)
    t2.on_hand += 300
    t2.volume_hl += 300
    db3.commit()
    db3.close()
    got3 = client.get(f"/api/batch-tanks/{tank_id}", headers=admin_h).json()
    assert got3["status"] == "len_men"
    assert got3["status_label"] == "Đang lên men"


def test_ferment_qc_sample_kcs_only_for_batch_tank_scope(client, admin_h, kcs_h, vanhanh_h):
    """Ghi "lần lấy mẫu" CT chính/CT phụ lên men (POST /brewing/qc-samples) cho pipeline "Mẻ sản
    xuất" mới (scope_type="batch_tank") CHỈ dành cho KCS (quyền "quality.release") — vận hành
    (chỉ có "batch.execute") phải bị chặn 403 (yêu cầu người dùng 2026-09-02: "chỉ cho nhân viên
    KCS được điền"). Module Nấu-Lọc-Chiết CŨ (scope_type="ferment") KHÔNG bị ảnh hưởng — vẫn cho
    vận hành ghi như cũ (xem test_qc_sample.py, không đổi)."""
    p = client.post("/api/qc/parameters", headers=admin_h,
                    json={"code": "CT_KCSONLY1", "name": "Chỉ tiêu KCS only 1", "lsl": 1, "usl": 10})
    assert p.status_code == 201, p.text
    g = client.post("/api/qc/groups", headers=admin_h, json={"code": "GRP_KCSONLY1", "name": "Nhóm KCS only 1"})
    assert g.status_code == 201, g.text
    group_id = g.json()["group_id"]
    it = client.post(f"/api/qc/groups/{group_id}/items", headers=admin_h,
                     json={"param_id": p.json()["param_id"], "mandatory": True})
    assert it.status_code == 201, it.text
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": "len_men_chinh", "group_id": group_id, "mandatory": True})
    assert link.status_code == 201, link.text

    tank = _make_tank(client, admin_h, "9", "TANK-KCSONLY1")
    scope_id = f"{tank['tank_id']}__len_men_chinh"
    body = {"stage": "len_men_chinh", "scope_type": "batch_tank", "scope_id": scope_id,
            "results": [{"parameter": "CT_KCSONLY1", "value": 5, "lower_limit": 1, "upper_limit": 10}]}

    blocked = client.post("/api/brewing/qc-samples", headers=vanhanh_h, json=body)
    assert blocked.status_code == 403, blocked.text

    ok = client.post("/api/brewing/qc-samples", headers=kcs_h, json=body)
    assert ok.status_code == 201, ok.text


def _order_and_version(client, admin_h):
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(x for x in vers if x["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    return oid, v["version_id"]


def test_batch_code_braumat_duplicate_rejected_and_blank_auto_generates_integer(client, admin_h):
    """Mã mẻ Braumat trùng TRONG CÙNG 1 NĂM phải bị chặn (409); không nhập thì tự sinh số nguyên
    kế tiếp TRONG NĂM HIỆN TẠI; nhập chữ (không phải số nguyên) cũng bị chặn (409) — yêu cầu
    người dùng 2026-09-02: "Ép định dạng số nguyên cho mẻ từ giờ trở đi và khi hết năm thì sẽ tự
    tính lại từ đầu, nghĩa là chỉ trong năm cần khác thôi, còn năm sau sẽ lặp lại được" (mirror
    đúng quy ước brew_code/lm_code/filter_code/bottle_code — unique theo batch_year, không phải
    toàn hệ thống). Dữ liệu CŨ tạo trước ràng buộc này (mã dạng chữ như "B-LIVEWIP1") không bị
    ép sửa lại — chỉ áp dụng validate cho bản ghi tạo MỚI, xem services/batches.py::create_batch."""
    oid, vid = _order_and_version(client, admin_h)

    ok1 = client.post("/api/batches", headers=admin_h,
                      json={"order_id": oid, "recipe_version_id": vid, "batch_code": "88001",
                            "planned_qty": 100, "allow_shortage": True})
    assert ok1.status_code == 201, ok1.text
    assert ok1.json()["batch_code"] == "88001"
    this_year = ok1.json()["batch_year"]

    dup = client.post("/api/batches", headers=admin_h,
                      json={"order_id": oid, "recipe_version_id": vid, "batch_code": "88001",
                            "planned_qty": 100, "allow_shortage": True})
    assert dup.status_code == 409, dup.text

    non_integer = client.post("/api/batches", headers=admin_h,
                              json={"order_id": oid, "recipe_version_id": vid, "batch_code": "B-88002",
                                    "planned_qty": 100, "allow_shortage": True})
    assert non_integer.status_code == 409, non_integer.text

    zero_or_negative = client.post("/api/batches", headers=admin_h,
                                   json={"order_id": oid, "recipe_version_id": vid, "batch_code": "0",
                                         "planned_qty": 100, "allow_shortage": True})
    assert zero_or_negative.status_code == 409, zero_or_negative.text

    auto = client.post("/api/batches", headers=admin_h,
                       json={"order_id": oid, "recipe_version_id": vid,
                             "planned_qty": 100, "allow_shortage": True})
    assert auto.status_code == 201, auto.text
    assert auto.json()["batch_code"].isdigit()
    assert auto.json()["batch_year"] == this_year

    # Dời "88001" đã tạo ở trên sang NĂM TRƯỚC (giả lập qua sửa thẳng DB, vì batch_year luôn lấy
    # theo utcnow() lúc tạo, không nhập tay được qua API) -> cùng mã "88001" tạo LẠI ở năm hiện
    # tại phải được (khác năm thì không tính trùng).
    from app.database import SessionLocal
    from app.models.batches import BatchExecution
    db = SessionLocal()
    try:
        row = db.get(BatchExecution, ok1.json()["batch_id"])
        row.batch_year = this_year - 1
        db.commit()
    finally:
        db.close()
    reused_next_year = client.post("/api/batches", headers=admin_h,
                                   json={"order_id": oid, "recipe_version_id": vid, "batch_code": "88001",
                                         "planned_qty": 100, "allow_shortage": True})
    assert reused_next_year.status_code == 201, reused_next_year.text
    assert reused_next_year.json()["batch_year"] == this_year
