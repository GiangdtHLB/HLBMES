"""Test Phase 3 — pipeline mới cho "Mẻ sản xuất": tank lên men (BatchTank) -> lô lọc
(BatchFilterLot, phối/lọc lại) -> lô thành phẩm (BatchPackLot). Xem services/batch_pipeline.py.

Phủ: gộp N mẻ vào 1 tank (chặn double-link), rút dịch (phối nhiều tank + lọc lại), on_hand
giảm/hoàn theo DELTA ở mọi bước, tách nhiều lô thành phẩm, chặn tách vượt tồn, xóa hoàn tác tồn,
QC gate (StageQcGroup) chặn duyệt lô lọc/lô thành phẩm, và genealogy truy ngược từ lô thành
phẩm về tới tận mẻ nấu gốc.
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


def _merge_tank(client, admin_h, batch_ids, tank_code):
    r = client.post("/api/batch-tanks", headers=admin_h,
                    json={"batch_ids": batch_ids, "tank_code": tank_code, "tank_lm": f"T-{tank_code}"})
    assert r.status_code == 201, r.text
    return r.json()


def _make_bbt_line(client, admin_h, suffix):
    r = client.post("/api/lines", headers=admin_h,
                    json={"code": f"BBT-{suffix}", "name": f"Tank thành phẩm {suffix}", "kind": "tank_bbt"})
    assert r.status_code == 201, r.text
    return r.json()["code"]


def _finish_source(client, admin_h, source, dich_nha_hl, nuoc_bai_khi_hl=0):
    """1 mẻ lọc (BatchFilterLotBatch) tự có sẵn 1 khoản rút (draw) cho MỖI nguồn ngay lúc tạo lô
    lọc (xem draw_from_tank_into_filter_lot/draw_from_filter_order) — "Kết thúc" tức là kết thúc
    mẻ đó, khai V dịch nha cho khoản rút của nguồn này. `source` là dict trả về từ GET
    .../sources (cần cả filter_lot_id lẫn link_id)."""
    batches = client.get(f"/api/batch-filter-lots/{source['filter_lot_id']}/batches", headers=admin_h).json()
    batch_link_id = batches[-1]["batch_link_id"]
    return client.put(f"/api/batch-filter-lots/batches/{batch_link_id}/finish", headers=admin_h,
                      json={"draws": [{"source_link_id": source["link_id"], "dich_nha_hl": dich_nha_hl}],
                           "nuoc_bai_khi_hl": nuoc_bai_khi_hl})


def _finish_batch_all_sources(client, admin_h, filter_lot_id, source_amounts, nuoc_bai_khi_hl=0):
    """Kết thúc mẻ lọc số 1 của 1 lô lọc CÙNG LÚC cho MỌI nguồn phối (1 lần chạy máy) —
    `source_amounts`: {source_link_id: dich_nha_hl}."""
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    batch_link_id = batches[-1]["batch_link_id"]
    return client.put(f"/api/batch-filter-lots/batches/{batch_link_id}/finish", headers=admin_h,
                      json={"draws": [{"source_link_id": sid, "dich_nha_hl": v}
                                     for sid, v in source_amounts.items()],
                           "nuoc_bai_khi_hl": nuoc_bai_khi_hl})


def test_merge_batches_into_tank_and_double_link_blocked(client, admin_h):
    b1 = _make_batch(client, admin_h, "1")
    b2 = _make_batch(client, admin_h, "2")
    _run_batch_to_completed(client, admin_h, b1)
    _run_batch_to_completed(client, admin_h, b2)
    tank = _merge_tank(client, admin_h, [b1, b2], "TANK-PIPE-01")
    assert tank["on_hand"] == 2000.0
    assert tank["volume_hl"] == 2000.0

    batches = client.get(f"/api/batch-tanks/{tank['tank_id']}/batches", headers=admin_h).json()
    assert set(batches["batch_ids"]) == {b1, b2}

    dup = client.post("/api/batch-tanks", headers=admin_h,
                      json={"batch_ids": [b1], "tank_code": "TANK-PIPE-DUP"})
    assert dup.status_code == 409, dup.text

    back = client.get("/api/trace/backward", headers=admin_h,
                      params={"node_type": "batch_tank", "node_id": tank["tank_id"]}).json()
    assert back is not None


def test_merge_batches_still_planned_and_on_hand_accumulates_via_actual_qty(client, admin_h):
    """Gộp mẻ vào tank được ở BẤT KỲ trạng thái nào (kể cả "planned" — mirror thực tế nấu nhiều
    mẻ liên tiếp cùng đổ 1 tank, mẻ nào xong bơm vào mẻ đó, không đợi hết cả đợt mới có tank) —
    on_hand/volume_hl CHỈ cộng theo actual_qty đã ghi (mẻ chưa xong đóng góp 0, KHÔNG lấy tạm
    planned_qty — đó là gốc bug tồn tank cộng nhầm SL kế hoạch của mẻ chưa nấu như dịch thật).
    set_actual_qty() sau đó cộng dồn đúng phần chênh lệch vào on_hand tank theo DELTA."""
    b1 = _make_batch(client, admin_h, "3")
    b2 = _make_batch(client, admin_h, "4")
    # Cả 2 mẻ còn "planned" (chưa hề chạy) lúc gộp -> tồn tank = 0, không phải 2000 (planned_qty).
    tank = _merge_tank(client, admin_h, [b1, b2], "TANK-PIPE-DELTA-01")
    assert tank["on_hand"] == 0.0
    assert tank["volume_hl"] == 0.0

    for target in ("ready", "running"):
        client.post(f"/api/batches/{b1}/transition", headers=admin_h, json={"target": target})
    aq1 = client.post(f"/api/batches/{b1}/actual-qty", headers=admin_h, json={"actual_qty": 480})
    assert aq1.status_code == 200, aq1.text
    after_b1 = client.get(f"/api/batch-tanks/{tank['tank_id']}", headers=admin_h).json()
    assert after_b1["on_hand"] == 480.0 and after_b1["volume_hl"] == 480.0

    for target in ("ready", "running"):
        client.post(f"/api/batches/{b2}/transition", headers=admin_h, json={"target": target})
    aq2 = client.post(f"/api/batches/{b2}/actual-qty", headers=admin_h, json={"actual_qty": 505})
    assert aq2.status_code == 200, aq2.text
    after_b2 = client.get(f"/api/batch-tanks/{tank['tank_id']}", headers=admin_h).json()
    assert after_b2["on_hand"] == 985.0 and after_b2["volume_hl"] == 985.0

    # Sửa lại actual_qty đã ghi (bấm nhầm) -> tank cộng/trừ đúng phần chênh lệch, không cộng dồn sai.
    fix = client.post(f"/api/batches/{b1}/actual-qty", headers=admin_h, json={"actual_qty": 490})
    assert fix.status_code == 200, fix.text
    after_fix = client.get(f"/api/batch-tanks/{tank['tank_id']}", headers=admin_h).json()
    assert after_fix["on_hand"] == 995.0 and after_fix["volume_hl"] == 995.0


def test_draw_blend_finish_and_split_pack_lots(client, admin_h):
    b1 = _make_batch(client, admin_h, "5")
    b2 = _make_batch(client, admin_h, "6")
    _run_batch_to_completed(client, admin_h, b1)
    _run_batch_to_completed(client, admin_h, b2)
    tank1 = _merge_tank(client, admin_h, [b1], "TANK-PIPE-02")
    tank2 = _merge_tank(client, admin_h, [b2], "TANK-PIPE-03")

    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": "FLOT-PIPE-01", "to_bbt": _make_bbt_line(client, admin_h, "PIPE01"),
        "sources": [{"source_type": "tank", "source_tank_id": tank1["tank_id"]},
                    {"source_type": "tank", "source_tank_id": tank2["tank_id"]}],
    })
    assert draw.status_code == 201, draw.text
    filter_lot_id = draw.json()["filter_lot_id"]
    assert draw.json()["on_hand"] == 0.0    # chưa "Kết thúc" nguồn nào

    sources = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()
    assert len(sources) == 2

    # 1 mẻ lọc phối cả 2 tank trong CÙNG 1 lần chạy máy -> kết thúc 1 lần cho cả 2 khoản rút.
    fin = _finish_batch_all_sources(client, admin_h, filter_lot_id,
                                    {s["link_id"]: 900 for s in sources})
    assert fin.status_code == 200, fin.text

    fl = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()
    assert fl["on_hand"] == 1800.0 and fl["volume_hl"] == 1800.0
    assert fl["ended_at"] is not None

    tank1_after = client.get(f"/api/batch-tanks/{tank1['tank_id']}", headers=admin_h).json()
    tank2_after = client.get(f"/api/batch-tanks/{tank2['tank_id']}", headers=admin_h).json()
    assert tank1_after["on_hand"] == 100.0    # 1000 - 900
    assert tank2_after["on_hand"] == 100.0

    # qty (Số lượng cấp chiết) đơn vị LÍT — quy đổi 1 hl = 100 lít khi trừ tồn lô lọc (hl).
    over = client.post(f"/api/batch-filter-lots/{filter_lot_id}/pack-lots", headers=admin_h,
                       json={"qty": 500000, "pack_lot_code": "PKG-PIPE-OVER", "lot_no": "LOT-OVER"})
    assert over.status_code == 409, over.text

    p1 = client.post(f"/api/batch-filter-lots/{filter_lot_id}/pack-lots", headers=admin_h,
                     json={"qty": 100000, "pack_lot_code": "PKG-PIPE-01", "lot_no": "LOT-01"})
    assert p1.status_code == 201, p1.text
    p2 = client.post(f"/api/batch-filter-lots/{filter_lot_id}/pack-lots", headers=admin_h,
                     json={"qty": 80000, "pack_lot_code": "PKG-PIPE-02", "lot_no": "LOT-02"})
    assert p2.status_code == 201, p2.text

    fl_after = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()
    assert fl_after["on_hand"] == 0.0

    pack_lots = client.get("/api/batch-pack-lots", headers=admin_h,
                           params={"filter_lot_id": filter_lot_id}).json()
    assert len(pack_lots) == 2

    # xóa 1 lô TP -> hoàn tồn lại lô lọc
    delp = client.delete(f"/api/batch-pack-lots/{p2.json()['pack_lot_id']}", headers=admin_h)
    assert delp.status_code == 204, delp.text
    fl_refund = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()
    assert fl_refund["on_hand"] == 800.0

    # genealogy: truy ngược từ lô TP còn lại phải thấy cả 2 tank -> cả 2 mẻ nấu gốc
    back = client.get("/api/trace/backward", headers=admin_h,
                      params={"node_type": "batch_pack_lot", "node_id": p1.json()["pack_lot_id"]}).json()
    import json as _j
    back_str = _j.dumps(back)
    assert tank1["tank_id"] in back_str and tank2["tank_id"] in back_str
    assert b1 in back_str and b2 in back_str


def test_refilter_chain_and_source_delete_guard(client, admin_h):
    b1 = _make_batch(client, admin_h, "7")
    _run_batch_to_completed(client, admin_h, b1)
    tank1 = _merge_tank(client, admin_h, [b1], "TANK-PIPE-04")

    draw1 = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": "FLOT-PIPE-02", "to_bbt": _make_bbt_line(client, admin_h, "PIPE02"),
        "sources": [{"source_type": "tank", "source_tank_id": tank1["tank_id"]}],
    })
    assert draw1.status_code == 201, draw1.text
    fl1_id = draw1.json()["filter_lot_id"]
    s1 = client.get(f"/api/batch-filter-lots/{fl1_id}/sources", headers=admin_h).json()[0]
    _finish_source(client, admin_h, s1, 1000)

    missing_reason = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": "FLOT-PIPE-03-BAD", "to_bbt": _make_bbt_line(client, admin_h, "PIPE03BAD"),
        "sources": [{"source_type": "filter_lot", "source_filter_lot_id": fl1_id}],
    })
    assert missing_reason.status_code == 409, missing_reason.text

    draw2 = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": "FLOT-PIPE-03", "to_bbt": _make_bbt_line(client, admin_h, "PIPE03"),
        "sources": [{"source_type": "filter_lot", "source_filter_lot_id": fl1_id,
                    "reason": "Lọc lại do chưa đạt độ trong"}],
    })
    assert draw2.status_code == 201, draw2.text
    fl2_id = draw2.json()["filter_lot_id"]
    s2 = client.get(f"/api/batch-filter-lots/{fl2_id}/sources", headers=admin_h).json()[0]
    assert s2["source_type"] == "filter_lot"
    fin2 = _finish_source(client, admin_h, s2, 950)
    assert fin2.status_code == 200, fin2.text

    fl1_after = client.get(f"/api/batch-filter-lots/{fl1_id}", headers=admin_h).json()
    assert fl1_after["on_hand"] == 50.0    # 1000 - 950

    # chặn xóa mẻ lọc duy nhất của cả lô lọc fl2
    batches2 = client.get(f"/api/batch-filter-lots/{fl2_id}/batches", headers=admin_h).json()
    last = client.delete(f"/api/batch-filter-lots/batches/{batches2[0]['batch_link_id']}", headers=admin_h)
    assert last.status_code == 409, last.text

    # chặn xóa fl1 vì fl2 đã lọc lại từ nó
    blocked_del = client.delete(f"/api/batch-filter-lots/{fl1_id}", headers=admin_h)
    assert blocked_del.status_code == 409, blocked_del.text


def test_filter_lot_and_pack_lot_qc_gate(client, admin_h):
    group_id, code = _make_group_with_param(client, admin_h, "PIPEFLOT")
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": "loc", "group_id": group_id, "mandatory": True})
    assert link.status_code == 201, link.text

    b1 = _make_batch(client, admin_h, "8")
    _run_batch_to_completed(client, admin_h, b1)
    tank1 = _merge_tank(client, admin_h, [b1], "TANK-PIPE-05")
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": "FLOT-PIPE-QC", "to_bbt": _make_bbt_line(client, admin_h, "PIPEQC"),
        "sources": [{"source_type": "tank", "source_tank_id": tank1["tank_id"]}],
    })
    filter_lot_id = draw.json()["filter_lot_id"]
    s = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()[0]
    _finish_source(client, admin_h, s, 1000)

    blocked = client.post(f"/api/batch-filter-lots/{filter_lot_id}/approve", headers=admin_h)
    assert blocked.status_code == 409, blocked.text

    rec = client.post("/api/brewing/qc-results", headers=admin_h,
                      json={"stage": "loc", "scope_type": "batch_filter_lot", "scope_id": filter_lot_id,
                            "parameter": code, "value": 5, "lower_limit": 1, "upper_limit": 10})
    assert rec.status_code == 201, rec.text

    ok = client.post(f"/api/batch-filter-lots/{filter_lot_id}/approve", headers=admin_h)
    assert ok.status_code == 200, ok.text
    assert ok.json()["qc_approved"] is True

    client.delete(f"/api/qc/stage-groups/{link.json()['link_id']}", headers=admin_h)

    # pack lot QC gate (stage "thanh_pham", scope_type "batch_pack_lot")
    group_id2, code2 = _make_group_with_param(client, admin_h, "PIPEPACK")
    link2 = client.post("/api/qc/stage-groups", headers=admin_h,
                        json={"stage": "thanh_pham", "group_id": group_id2, "mandatory": True})
    assert link2.status_code == 201, link2.text

    p = client.post(f"/api/batch-filter-lots/{filter_lot_id}/pack-lots", headers=admin_h,
                    json={"qty": 500, "pack_lot_code": "PKG-PIPE-QC", "lot_no": "LOT-PIPE-QC"})
    assert p.status_code == 201, p.text
    pack_lot_id = p.json()["pack_lot_id"]

    blocked2 = client.post(f"/api/batch-pack-lots/{pack_lot_id}/approve", headers=admin_h)
    assert blocked2.status_code == 409, blocked2.text

    rec2 = client.post("/api/brewing/qc-results", headers=admin_h,
                       json={"stage": "thanh_pham", "scope_type": "batch_pack_lot", "scope_id": pack_lot_id,
                             "parameter": code2, "value": 5, "lower_limit": 1, "upper_limit": 10})
    assert rec2.status_code == 201, rec2.text

    ok2 = client.post(f"/api/batch-pack-lots/{pack_lot_id}/approve", headers=admin_h)
    assert ok2.status_code == 200, ok2.text
    assert ok2.json()["approved"] is True

    client.delete(f"/api/qc/stage-groups/{link2.json()['link_id']}", headers=admin_h)


def test_pack_lot_status_dang_chiet_1_phan_chiet_het(client, admin_h):
    """Trạng thái Chiết (yêu cầu người dùng 2026-09-02: "bổ sung thêm cột trạng thái"):
    - Vừa tách (chưa ghi SL theo ca nào) -> "dang_chiet".
    - Đã ghi SL theo ca (ca1+ca2+ca3 > 0) NHƯNG lô lọc nguồn còn tồn ngoài ngưỡng "làm rỗng tank"
      -> "chiet_1_phan".
    - Lô lọc nguồn đã về trong ngưỡng dung sai (~ đã chiết cạn thật) -> "chiet_het" — áp dụng
      ngay cả cho lô TP đã tách TRƯỚC đó (trạng thái suy theo lô lọc NGUỒN hiện tại, không lưu
      cứng lúc tách — 1 lô lọc có thể tách nhiều lô TP, "chiết hết" mô tả tank vật lý, không
      phải riêng 1 lô TP)."""
    b1 = _make_batch(client, admin_h, "9")
    _run_batch_to_completed(client, admin_h, b1)
    tank1 = _merge_tank(client, admin_h, [b1], "TANK-PSTATUS-01")
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": "FLOT-PSTATUS-01", "to_bbt": _make_bbt_line(client, admin_h, "PSTATUS01"),
        "sources": [{"source_type": "tank", "source_tank_id": tank1["tank_id"]}],
    })
    assert draw.status_code == 201, draw.text
    filter_lot_id = draw.json()["filter_lot_id"]
    sources = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()
    fin = _finish_batch_all_sources(client, admin_h, filter_lot_id, {sources[0]["link_id"]: 1000})
    assert fin.status_code == 200, fin.text   # filter_lot.on_hand = 1000 hl

    # Tách lô TP #1 (900 hl -> 90000 lít) -> filter_lot còn dư 100 hl (ngoài ngưỡng mặc định 2hl).
    p1 = client.post(f"/api/batch-filter-lots/{filter_lot_id}/pack-lots", headers=admin_h,
                     json={"qty": 90000, "pack_lot_code": "PKG-PSTATUS-01", "lot_no": "LOT-PSTATUS-01"})
    assert p1.status_code == 201, p1.text
    pack_lot_id = p1.json()["pack_lot_id"]
    assert p1.json()["status"] == "dang_chiet"
    assert p1.json()["status_label"] == "Đang chiết"

    shifts = client.put(f"/api/batch-pack-lots/{pack_lot_id}/shifts", headers=admin_h,
                        json={"ca1_qty": 10, "ca2_qty": 0, "ca3_qty": 0})
    assert shifts.status_code == 200, shifts.text
    assert shifts.json()["status"] == "chiet_1_phan"

    got = client.get(f"/api/batch-pack-lots/{pack_lot_id}", headers=admin_h).json()
    assert got["status"] == "chiet_1_phan"

    # Tách nốt lô TP #2 lấy hết phần còn lại (100 hl -> 10000 lít) -> filter_lot về 0 (trong
    # ngưỡng) -> CẢ lô TP #1 (dù không đổi gì) lẫn #2 (sau khi ghi ca) đều phải hiện "chiet_het".
    p2 = client.post(f"/api/batch-filter-lots/{filter_lot_id}/pack-lots", headers=admin_h,
                     json={"qty": 10000, "pack_lot_code": "PKG-PSTATUS-02", "lot_no": "LOT-PSTATUS-02"})
    assert p2.status_code == 201, p2.text
    pack_lot_id2 = p2.json()["pack_lot_id"]
    shifts2 = client.put(f"/api/batch-pack-lots/{pack_lot_id2}/shifts", headers=admin_h,
                         json={"ca1_qty": 1, "ca2_qty": 0, "ca3_qty": 0})
    assert shifts2.status_code == 200, shifts2.text
    assert shifts2.json()["status"] == "chiet_het"

    got1_after = client.get(f"/api/batch-pack-lots/{pack_lot_id}", headers=admin_h).json()
    assert got1_after["status"] == "chiet_het"
    assert got1_after["status_label"] == "Chiết hết"

    listed = client.get("/api/batch-pack-lots", headers=admin_h,
                        params={"filter_lot_id": filter_lot_id}).json()
    assert {p["pack_lot_id"]: p["status"] for p in listed} == {
        pack_lot_id: "chiet_het", pack_lot_id2: "chiet_het"}
