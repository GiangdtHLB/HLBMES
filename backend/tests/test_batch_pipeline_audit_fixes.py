"""Test các fix từ đợt audit module "Mẻ sản xuất" (2026-09-02):

1. Xóa Tank/Lô lọc/Lô TP dọn ĐỦ bảng con (process log/daily readings/QC/NVL đã dùng) —
   mirror delete_ferment/delete_filter/delete_bottle module Nấu-Lọc-Chiết cũ.
2. Khóa EBR (Tank/Lô lọc/Mẻ SX/Lô TP) an toàn với race — with_for_update() + UniqueConstraint
   (batch_id, snapshot_version) trên ebr_snapshot làm backstop.
3. Ghi chép lên men (process log + daily readings) vào core EBR của Tank.
5. lot_no (Số lô bia) unique theo năm ở tầng DB (migration c310cce1e620).
6. Xóa lô lọc chặn khi đã KCS duyệt (mirror xóa lô TP).
7. update_pack_lot_shifts chặn SL âm.
8. Endpoint sửa Tank/Lô lọc (mã/tank vật lý/ghi chú).
9. genealogy._period có nhánh "batch" (Mẻ nấu không còn hiện trống khoảng thời gian).
11. genealogy không gắn nhãn "cycle" sai cho gộp nhánh (diamond) hợp lệ trong DAG.

Xem test_batch_pipeline.py/test_batch_tank_gaps.py/test_batch_pack_lot_ebr.py cho phần còn lại
của pipeline mới.
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


def _make_batch(client, admin_h, batch_code=None):
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(x for x in vers if x["state"] == "effective")
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


def _make_tank(client, admin_h, tank_code, tank_lm=None):
    batch_id = _make_batch(client, admin_h)
    _run_batch_to_completed(client, admin_h, batch_id)
    t = client.post("/api/batch-tanks", headers=admin_h,
                    json={"batch_ids": [batch_id], "tank_code": tank_code, "tank_lm": tank_lm})
    assert t.status_code == 201, t.text
    return t.json()


def _make_filter_lot(client, admin_h, suffix, tank_id=None):
    if tank_id is None:
        tank_id = _make_tank(client, admin_h, f"TANK-{suffix}")["tank_id"]
    bbt = client.post("/api/lines", headers=admin_h,
                      json={"code": f"BBT-{suffix}", "name": f"Tank thành phẩm {suffix}", "kind": "tank_bbt"})
    assert bbt.status_code == 201, bbt.text
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": f"FLOT-{suffix}", "to_bbt": bbt.json()["code"],
        "sources": [{"source_type": "tank", "source_tank_id": tank_id}],
    })
    assert draw.status_code == 201, draw.text
    return draw.json()["filter_lot_id"], tank_id


def _finish_only_source(client, admin_h, filter_lot_id, v_drawn=900):
    src = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()[0]
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    fin = client.put(f"/api/batch-filter-lots/batches/{batches[0]['batch_link_id']}/finish", headers=admin_h,
                     json={"draws": [{"source_link_id": src["link_id"], "dich_nha_hl": v_drawn}],
                          "nuoc_bai_khi_hl": 0})
    assert fin.status_code == 200, fin.text
    return fin.json()


def _make_pack_lot(client, admin_h, filter_lot_id, suffix, qty=500):
    pack = client.post(f"/api/batch-filter-lots/{filter_lot_id}/pack-lots", headers=admin_h,
                       json={"qty": qty, "pack_lot_code": f"PKG-{suffix}", "lot_no": f"LOT-{suffix}"})
    assert pack.status_code == 201, pack.text
    return pack.json()["pack_lot_id"]


def _a_material_workshop_lot(client, admin_h, code, qty):
    m = client.post("/api/materials", headers=admin_h, json={"code": code, "name": f"Vật tư {code}", "uom": "kg"})
    assert m.status_code == 201, m.text
    material_id = m.json()["material_id"]
    r = client.post("/api/warehouse/receive", headers=admin_h,
                    json={"lot_code": f"LOT-{code}-PX", "material_id": material_id,
                          "quantity": qty, "uom": "kg", "location": "Kho phân xưởng"})
    assert r.status_code == 200, r.text
    lots = client.get("/api/lots", headers=admin_h).json()
    lot = next(l for l in lots if l["lot_code"] == f"LOT-{code}-PX")
    return material_id, lot["lot_id"]


def _lot_qty(client, admin_h, lot_id):
    lots = client.get("/api/lots", headers=admin_h).json()
    return next(l for l in lots if l["lot_id"] == lot_id)["quantity"]


# ==================== 1. Xóa dọn đủ bảng con ====================

def test_delete_tank_cleans_up_process_log_daily_readings_and_qc(client, admin_h):
    tank = _make_tank(client, admin_h, "TANK-DELCLEAN1")
    tank_id = tank["tank_id"]
    pl = client.put(f"/api/batch-tanks/{tank_id}/process-log", headers=admin_h,
                    json={"kieu_men": "Lager", "note": "Test"})
    assert pl.status_code == 200, pl.text
    rd = client.put(f"/api/batch-tanks/{tank_id}/process-log/readings", headers=admin_h,
                    json={"readings": [{"day_no": 1, "nhiet_do_c": 12.5}]})
    assert rd.status_code == 200, rd.text
    rec = client.post("/api/brewing/qc-results", headers=admin_h,
                      json={"stage": "len_men_chinh", "scope_type": "batch_tank",
                            "scope_id": f"{tank_id}__len_men_chinh",
                            "parameter": "pH", "value": 5, "lower_limit": 1, "upper_limit": 10})
    assert rec.status_code == 201, rec.text

    d = client.delete(f"/api/batch-tanks/{tank_id}", headers=admin_h)
    assert d.status_code == 204, d.text

    from app.database import SessionLocal
    from app.models.batch_pipeline import BatchTankDailyReading, BatchTankProcessLog
    from app.models.quality import QualityResult
    db = SessionLocal()
    try:
        assert db.query(BatchTankProcessLog).filter_by(tank_id=tank_id).first() is None
        assert db.query(BatchTankDailyReading).filter_by(tank_id=tank_id).first() is None
        assert db.query(QualityResult).filter_by(
            scope_type="batch_tank", scope_id=f"{tank_id}__len_men_chinh").first() is None
    finally:
        db.close()


def test_delete_tank_blocked_by_planned_filter_order_source(client, admin_h):
    tank = _make_tank(client, admin_h, "TANK-DELPLANNED1")
    order = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-DELPLANNED1",
        "sources": [{"source_type": "tank", "source_tank_id": tank["tank_id"], "planned_v_dich_hl": 900}],
    })
    assert order.status_code == 201, order.text

    d = client.delete(f"/api/batch-tanks/{tank['tank_id']}", headers=admin_h)
    assert d.status_code == 409, d.text
    assert "Lệnh lọc" in d.json()["detail"]


def test_delete_filter_lot_blocked_when_qc_approved(client, admin_h):
    filter_lot_id, _tank_id = _make_filter_lot(client, admin_h, "DELAPPR1")
    _finish_only_source(client, admin_h, filter_lot_id)
    appr = client.post(f"/api/batch-filter-lots/{filter_lot_id}/approve", headers=admin_h)
    assert appr.status_code == 200, appr.text

    d = client.delete(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h)
    assert d.status_code == 409, d.text
    assert "duyệt" in d.json()["detail"]


def test_delete_filter_lot_undoes_material_usage_and_qc(client, admin_h):
    filter_lot_id, _tank_id = _make_filter_lot(client, admin_h, "DELMATFL1")
    _material_id, lot_id = _a_material_workshop_lot(client, admin_h, "MAT-DELMATFL1", 50)
    add = client.post(f"/api/batch-filter-lots/{filter_lot_id}/materials", headers=admin_h,
                      json={"lot_id": lot_id, "quantity": 12, "uom": "kg"})
    assert add.status_code == 201, add.text
    assert _lot_qty(client, admin_h, lot_id) == 38

    rec = client.post("/api/brewing/qc-results", headers=admin_h,
                      json={"stage": "loc", "scope_type": "batch_filter_lot", "scope_id": filter_lot_id,
                            "parameter": "pH", "value": 5, "lower_limit": 1, "upper_limit": 10})
    assert rec.status_code == 201, rec.text

    d = client.delete(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h)
    assert d.status_code == 204, d.text
    assert _lot_qty(client, admin_h, lot_id) == 50   # NVL đã xuất được hoàn lại

    from app.database import SessionLocal
    from app.models.quality import QualityResult
    db = SessionLocal()
    try:
        assert db.query(QualityResult).filter_by(
            scope_type="batch_filter_lot", scope_id=filter_lot_id).first() is None
    finally:
        db.close()


def test_delete_pack_lot_undoes_material_usage_and_qc(client, admin_h):
    filter_lot_id, _tank_id = _make_filter_lot(client, admin_h, "DELMATPK1")
    _finish_only_source(client, admin_h, filter_lot_id)
    pack_lot_id = _make_pack_lot(client, admin_h, filter_lot_id, "DELMATPK1")

    _material_id, lot_id = _a_material_workshop_lot(client, admin_h, "MAT-DELMATPK1", 50)
    add = client.post(f"/api/batch-pack-lots/{pack_lot_id}/materials", headers=admin_h,
                      json={"lot_id": lot_id, "quantity": 12, "uom": "kg"})
    assert add.status_code == 201, add.text
    assert _lot_qty(client, admin_h, lot_id) == 38

    rec = client.post("/api/brewing/qc-results", headers=admin_h,
                      json={"stage": "thanh_pham", "scope_type": "batch_pack_lot", "scope_id": pack_lot_id,
                            "parameter": "pH", "value": 5, "lower_limit": 1, "upper_limit": 10})
    assert rec.status_code == 201, rec.text

    d = client.delete(f"/api/batch-pack-lots/{pack_lot_id}", headers=admin_h)
    assert d.status_code == 204, d.text
    assert _lot_qty(client, admin_h, lot_id) == 50

    from app.database import SessionLocal
    from app.models.quality import QualityResult
    db = SessionLocal()
    try:
        assert db.query(QualityResult).filter_by(
            scope_type="batch_pack_lot", scope_id=pack_lot_id).first() is None
    finally:
        db.close()


# ==================== 2. Race condition khóa EBR ====================

def test_lock_tank_ebr_handles_concurrent_snapshot_gracefully(client, admin_h):
    """Giả lập race: 1 snapshot ĐÃ được commit bởi giao dịch khác (VD cascade từ lô TP) đúng lúc
    request này đang xử lý, TRƯỚC khi nó kịp set tank.locked=True (kịch bản with_for_update()
    không chặn được, VD SQLite không hỗ trợ row-lock thật) — UniqueConstraint phải bắt lỗi này
    ở tầng DB, service phải trả 409 rõ ràng thay vì 500 (IntegrityError chưa bắt)."""
    tank = _make_tank(client, admin_h, "TANK-RACE1")
    tank_id = tank["tank_id"]

    from app.common import new_id, utcnow
    from app.database import SessionLocal
    from app.models.signature import EBRSnapshot
    db = SessionLocal()
    try:
        db.add(EBRSnapshot(snap_id=new_id(), batch_id=tank_id, snapshot_version=1,
                           content_hash="deadbeef", content={}, locked_by="other_session",
                           locked_at=utcnow()))
        db.commit()
    finally:
        db.close()

    lock = client.post(f"/api/batch-tanks/{tank_id}/ebr/lock", headers=admin_h,
                       json={"password": "AdminTest123", "reason": "test race"})
    assert lock.status_code == 409, lock.text


# ==================== 3. Ghi chép lên men vào core EBR ====================

def test_tank_ebr_core_includes_fermentation_log(client, admin_h):
    tank = _make_tank(client, admin_h, "TANK-FERMLOG1")
    tank_id = tank["tank_id"]
    pl = client.put(f"/api/batch-tanks/{tank_id}/process-log", headers=admin_h,
                    json={"kieu_men": "Lager W-34/70", "note": "ghi chú test"})
    assert pl.status_code == 200, pl.text
    rd = client.put(f"/api/batch-tanks/{tank_id}/process-log/readings", headers=admin_h,
                    json={"readings": [{"day_no": 1, "nhiet_do_c": 12.5, "do_s": 11.2}]})
    assert rd.status_code == 200, rd.text

    ebr = client.get(f"/api/batch-tanks/{tank_id}/ebr", headers=admin_h)
    assert ebr.status_code == 200, ebr.text
    ferm = ebr.json()["core"]["fermentation_log"]
    assert ferm["manual"]["kieu_men"] == "Lager W-34/70"
    assert ferm["note"] == "ghi chú test"
    assert len(ferm["daily_readings"]) == 1
    assert ferm["daily_readings"][0]["nhiet_do_c"] == 12.5

    lock = client.post(f"/api/batch-tanks/{tank_id}/ebr/lock", headers=admin_h,
                       json={"password": "AdminTest123", "reason": "khóa test"})
    assert lock.status_code == 200, lock.text
    ebr2 = client.get(f"/api/batch-tanks/{tank_id}/ebr", headers=admin_h).json()
    # Đã khóa -> sửa ghi chép lên men phải bị chặn (mirror _assert_tank_unlocked, đã có từ trước).
    blocked = client.put(f"/api/batch-tanks/{tank_id}/process-log", headers=admin_h, json={"note": "sửa sau khóa"})
    assert blocked.status_code == 409, blocked.text
    assert ebr2["current_hash"] == ebr2["snapshot"]["hash"]   # chưa sửa gì -> hash khớp


# ==================== 6. update_pack_lot_shifts chặn số âm ====================

def test_update_pack_lot_shifts_rejects_negative_ca_qty(client, admin_h):
    filter_lot_id, _tank_id = _make_filter_lot(client, admin_h, "SHIFTNEG1")
    _finish_only_source(client, admin_h, filter_lot_id)
    pack_lot_id = _make_pack_lot(client, admin_h, filter_lot_id, "SHIFTNEG1")

    bad = client.put(f"/api/batch-pack-lots/{pack_lot_id}/shifts", headers=admin_h, json={"ca1_qty": -5})
    assert bad.status_code == 422, bad.text

    ok = client.put(f"/api/batch-pack-lots/{pack_lot_id}/shifts", headers=admin_h, json={"ca1_qty": 10})
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] in ("chiet_1_phan", "chiet_het")


# ==================== 8. Endpoint sửa Tank/Lô lọc ====================

def test_update_tank_edit_endpoint(client, admin_h):
    tank = _make_tank(client, admin_h, "TANK-EDIT1")
    tank_id = tank["tank_id"]

    ok = client.put(f"/api/batch-tanks/{tank_id}", headers=admin_h,
                    json={"tank_code": "TANK-EDIT1-FIXED", "note": "đã sửa"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["tank_code"] == "TANK-EDIT1-FIXED"
    assert ok.json()["note"] == "đã sửa"

    other = _make_tank(client, admin_h, "TANK-EDIT2")
    dup = client.put(f"/api/batch-tanks/{other['tank_id']}", headers=admin_h,
                     json={"tank_code": "TANK-EDIT1-FIXED"})
    assert dup.status_code == 409, dup.text

    lock = client.post(f"/api/batch-tanks/{tank_id}/ebr/lock", headers=admin_h,
                       json={"password": "AdminTest123", "reason": "khóa"})
    assert lock.status_code == 200, lock.text
    blocked = client.put(f"/api/batch-tanks/{tank_id}", headers=admin_h, json={"note": "sửa sau khóa"})
    assert blocked.status_code == 409, blocked.text


def test_update_filter_lot_edit_endpoint(client, admin_h):
    filter_lot_id, _tank_id = _make_filter_lot(client, admin_h, "FLEDIT1")

    ok = client.put(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h,
                    json={"filter_lot_code": "FLOT-FLEDIT1-FIXED", "note": "đã sửa"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["filter_lot_code"] == "FLOT-FLEDIT1-FIXED"
    assert ok.json()["note"] == "đã sửa"

    other_id, _t2 = _make_filter_lot(client, admin_h, "FLEDIT2")
    dup = client.put(f"/api/batch-filter-lots/{other_id}", headers=admin_h,
                     json={"filter_lot_code": "FLOT-FLEDIT1-FIXED"})
    assert dup.status_code == 409, dup.text


# ==================== 9. genealogy._period cho node "batch" ====================

def test_trace_backward_batch_node_shows_period(client, admin_h):
    batch_id = _make_batch(client, admin_h)
    started = _run_batch_to_completed(client, admin_h, batch_id)

    from datetime import datetime
    back = client.get("/api/trace/backward", headers=admin_h,
                      params={"node_type": "batch", "node_id": batch_id}).json()
    assert back["period"] is not None
    assert back["period"]["start"] is not None
    assert back["period"]["end"] is not None
    assert (datetime.fromisoformat(back["period"]["end"].replace("Z", "+00:00"))
            == datetime.fromisoformat(started["end_at"].replace("Z", "+00:00")))


# ==================== 11. genealogy không gắn nhãn "cycle" sai cho diamond ====================

def test_genealogy_diamond_not_mislabeled_as_cycle(client, admin_h):
    """FL3 phối 2 nguồn: 1 trực tiếp từ tank T, 1 "lọc lại" từ FL1 (cũng rút từ T) -> T xuất hiện
    2 lần trong cây truy ngược của FL3 (1 lần trực tiếp, 1 lần qua FL1) — đây là 1 "diamond" hợp
    lệ trong DAG (KHÔNG phải chu trình), cả 2 lần đều phải được mở rộng đầy đủ (có children),
    KHÔNG lần nào được gắn "cycle": true."""
    tank = _make_tank(client, admin_h, "TANK-DIAMOND1")
    tank_id = tank["tank_id"]
    fl1_id, _ = _make_filter_lot(client, admin_h, "DIAMOND-FL1", tank_id=tank_id)
    _finish_only_source(client, admin_h, fl1_id, v_drawn=400)

    bbt3 = client.post("/api/lines", headers=admin_h,
                       json={"code": "BBT-DIAMOND3", "name": "BBT diamond 3", "kind": "tank_bbt"})
    assert bbt3.status_code == 201, bbt3.text
    fl3 = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": "FLOT-DIAMOND3", "to_bbt": bbt3.json()["code"],
        "sources": [
            {"source_type": "tank", "source_tank_id": tank_id},
            {"source_type": "filter_lot", "source_filter_lot_id": fl1_id, "reason": "test diamond"},
        ],
    })
    assert fl3.status_code == 201, fl3.text
    fl3_id = fl3.json()["filter_lot_id"]

    back = client.get("/api/trace/backward", headers=admin_h,
                      params={"node_type": "batch_filter_lot", "node_id": fl3_id}).json()

    tank_occurrences = []

    def walk(node):
        if node["type"] == "batch_tank" and node["id"] == tank_id:
            tank_occurrences.append(node)
        for c in node.get("children", []):
            walk(c)

    walk(back)
    assert len(tank_occurrences) == 2, f"tank T phải xuất hiện đúng 2 lần (diamond), thấy {len(tank_occurrences)}"
    for occ in tank_occurrences:
        assert not occ.get("cycle"), "diamond hợp lệ KHÔNG được gắn nhãn cycle"
        assert occ["children"], "cả 2 lần xuất hiện đều phải được mở rộng đầy đủ (có children)"
