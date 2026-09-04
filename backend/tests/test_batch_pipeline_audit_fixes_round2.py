"""Test các fix đợt audit thứ 2 của pipeline "Mẻ sản xuất" (2026-09-03) — khác các mục đã sửa
+ test ở test_batch_pipeline_audit_fixes.py (đợt 1, 2026-09-02):

12. finish_filter_lot_batch/split_filter_lot_to_pack_lot/update_pack_lot_qty/
    delete_filter_lot_batch/delete_filter_lot/delete_pack_lot dùng with_for_update() khi đọc-
    rồi-ghi on_hand (không test concurrency thật — SQLite 1 connection không mô phỏng được race
    thật, chỉ xác nhận các hàm vẫn hoạt động đúng sau khi thêm khóa hàng).
13. finish_filter_lot_batch validate dấu TỪNG nguồn (dich_nha_hl) + nuoc_bai_khi_hl, không chỉ
    tổng.
14. Trường "kcs" (đạt/không đạt) trong nhật ký lên men yêu cầu role QA/OPERATOR — mirror
    services/quality.py::record_result — không phải bất kỳ ai có batch.execute cũng ghi được.
15. Xóa Tank/Lô lọc/Lô TP dọn kèm Deviation (trước đây chỉ dọn QualityResult).
16. sign_tank/sign_filter_lot/sign_pack_lot ký xong (chưa khóa) thì chặn xóa entity đó — tránh
    Signature (chữ ký điện tử) mồ côi.
17. list_filter_lot_batches có tie-breaker phụ (batch_link_id) sau created_at — thứ tự "mẻ lọc
    cuối" ổn định dù 2 bản ghi trùng created_at.
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
        tank_id = _make_tank(client, admin_h, f"TANK-R2-{suffix}")["tank_id"]
    bbt = client.post("/api/lines", headers=admin_h,
                      json={"code": f"BBT-R2-{suffix}", "name": f"Tank thành phẩm {suffix}", "kind": "tank_bbt"})
    assert bbt.status_code == 201, bbt.text
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": f"FLOT-R2-{suffix}", "to_bbt": bbt.json()["code"],
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
                       json={"qty": qty, "pack_lot_code": f"PKG-R2-{suffix}", "lot_no": f"LOT-R2-{suffix}"})
    assert pack.status_code == 201, pack.text
    return pack.json()["pack_lot_id"]


# ==================== 13. Validate dấu TỪNG nguồn khi Kết thúc mẻ lọc ====================
# Lưu ý: schema FilterLotBatchDrawIn.dich_nha_hl/FinishFilterLotBatchIn.nuoc_bai_khi_hl đã có
# Field(ge=0) (schemas.py) — chặn số âm ngay ở tầng Pydantic (422) TRƯỚC KHI vào tới service, nên
# 2 test dưới đây xác nhận validate ge=0 vẫn đứng vững qua API thật (không phải giả định suông).
# services/batch_pipeline.py::finish_filter_lot_batch vẫn giữ check thủ công y hệt làm phòng thủ
# 2 lớp cho caller nội bộ không qua schema (VD gọi thẳng service trong 1 script/migration).

def test_finish_filter_lot_rejects_negative_per_source_draw(client, admin_h):
    filter_lot_id, tank_id = _make_filter_lot(client, admin_h, "NEGDRAW")
    src = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()[0]
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    r = client.put(f"/api/batch-filter-lots/batches/{batches[0]['batch_link_id']}/finish", headers=admin_h,
                  json={"draws": [{"source_link_id": src["link_id"], "dich_nha_hl": -5}],
                        "nuoc_bai_khi_hl": 100})
    assert r.status_code == 422, r.text


def test_finish_filter_lot_rejects_negative_nuoc_bai_khi(client, admin_h):
    filter_lot_id, tank_id = _make_filter_lot(client, admin_h, "NEGDAW")
    src = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()[0]
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    r = client.put(f"/api/batch-filter-lots/batches/{batches[0]['batch_link_id']}/finish", headers=admin_h,
                  json={"draws": [{"source_link_id": src["link_id"], "dich_nha_hl": 900}],
                        "nuoc_bai_khi_hl": -1})
    assert r.status_code == 422, r.text


# ==================== 14. Trường "kcs" yêu cầu role QA/OPERATOR ====================

def test_daily_reading_kcs_requires_qa_or_operator_role(client, admin_h):
    tank = _make_tank(client, admin_h, "TANK-R2-KCSPERM")
    tank_id = tank["tank_id"]

    # Tạo 1 tài khoản có quyền "batch.execute" nhưng role KHÔNG phải QA/OPERATOR (VD engineer).
    eng = client.post("/api/auth/users", headers=admin_h, json={
        "username": "eng_r2_kcsperm", "password": "Str0ngP@ssw0rd!", "full_name": "Test Engineer",
        "job_title": "Test", "role": "engineer", "permissions": "batch.execute"})
    assert eng.status_code == 201, eng.text
    eng_h = _login(client, "eng_r2_kcsperm", "Str0ngP@ssw0rd!")

    # Ghi nhiệt độ (không đụng "kcs") vẫn được — batch.execute là đủ cho các trường vận hành.
    ok = client.put(f"/api/batch-tanks/{tank_id}/process-log/readings", headers=eng_h,
                    json={"readings": [{"day_no": 1, "nhiet_do_c": 12.5}]})
    assert ok.status_code == 200, ok.text

    # Nhưng set "kcs" (đạt/không đạt) thì bị chặn — không phải QA/OPERATOR.
    blocked = client.put(f"/api/batch-tanks/{tank_id}/process-log/readings", headers=eng_h,
                         json={"readings": [{"day_no": 2, "kcs": "dat"}]})
    assert blocked.status_code == 403, blocked.text

    # 1 tài khoản role=qa (nhưng seed "kcs" thật không có quyền batch.execute nên không dùng
    # được màn này ở đời thật — tạo user test riêng có CẢ role=qa LẪN batch.execute) ghi "kcs"
    # được bình thường.
    qa = client.post("/api/auth/users", headers=admin_h, json={
        "username": "qa_r2_kcsperm", "password": "Str0ngP@ssw0rd!", "full_name": "Test QA",
        "job_title": "Test", "role": "qa", "permissions": "batch.execute"})
    assert qa.status_code == 201, qa.text
    qa_h = _login(client, "qa_r2_kcsperm", "Str0ngP@ssw0rd!")
    ok2 = client.put(f"/api/batch-tanks/{tank_id}/process-log/readings", headers=qa_h,
                     json={"readings": [{"day_no": 2, "kcs": "dat"}]})
    assert ok2.status_code == 200, ok2.text
    row2 = next(r for r in ok2.json() if r["day_no"] == 2)
    assert row2["kcs"] == "dat"


# ==================== 15. Xóa dọn kèm Deviation ====================

def test_delete_tank_cleans_up_deviation(client, admin_h):
    tank = _make_tank(client, admin_h, "TANK-R2-DEVCLEAN")
    tank_id = tank["tank_id"]
    dev = client.post("/api/quality/deviations", headers=admin_h,
                      json={"scope_type": "batch_tank", "scope_id": tank_id,
                            "severity": "minor", "reason": "Test deviation dọn khi xóa tank"})
    assert dev.status_code == 201, dev.text

    d = client.delete(f"/api/batch-tanks/{tank_id}", headers=admin_h)
    assert d.status_code == 204, d.text

    remaining = client.get("/api/quality/deviations", headers=admin_h).json()
    assert not any(x["deviation_id"] == dev.json()["deviation_id"] for x in remaining)


def test_delete_filter_lot_cleans_up_deviation(client, admin_h):
    filter_lot_id, _ = _make_filter_lot(client, admin_h, "DEVCLEAN")
    dev = client.post("/api/quality/deviations", headers=admin_h,
                      json={"scope_type": "batch_filter_lot", "scope_id": filter_lot_id,
                            "severity": "minor", "reason": "Test deviation dọn khi xóa lô lọc"})
    assert dev.status_code == 201, dev.text

    d = client.delete(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h)
    assert d.status_code == 204, d.text

    remaining = client.get("/api/quality/deviations", headers=admin_h).json()
    assert not any(x["deviation_id"] == dev.json()["deviation_id"] for x in remaining)


def test_delete_pack_lot_cleans_up_deviation(client, admin_h):
    filter_lot_id, _ = _make_filter_lot(client, admin_h, "PACKDEVCLEAN")
    _finish_only_source(client, admin_h, filter_lot_id)
    pack_lot_id = _make_pack_lot(client, admin_h, filter_lot_id, "PACKDEVCLEAN")
    dev = client.post("/api/quality/deviations", headers=admin_h,
                      json={"scope_type": "batch_pack_lot", "scope_id": pack_lot_id,
                            "severity": "minor", "reason": "Test deviation dọn khi xóa lô TP"})
    assert dev.status_code == 201, dev.text

    d = client.delete(f"/api/batch-pack-lots/{pack_lot_id}", headers=admin_h)
    assert d.status_code == 204, d.text

    remaining = client.get("/api/quality/deviations", headers=admin_h).json()
    assert not any(x["deviation_id"] == dev.json()["deviation_id"] for x in remaining)


# ==================== 16. Ký (chưa khóa) thì chặn xóa ====================

def test_signed_but_unlocked_tank_cannot_be_deleted(client, admin_h):
    tank = _make_tank(client, admin_h, "TANK-R2-SIGNDEL")
    tank_id = tank["tank_id"]
    sign = client.post(f"/api/batch-tanks/{tank_id}/ebr/sign", headers=admin_h,
                       json={"password": "AdminTest123", "meaning": "Xác nhận xong lên men", "reason": "Test"})
    assert sign.status_code == 200, sign.text

    blocked = client.delete(f"/api/batch-tanks/{tank_id}", headers=admin_h)
    assert blocked.status_code == 409, blocked.text
    assert "chữ ký điện tử" in blocked.json()["detail"]


def test_signed_but_unlocked_filter_lot_cannot_be_deleted(client, admin_h):
    filter_lot_id, _ = _make_filter_lot(client, admin_h, "SIGNDELFL")
    sign = client.post(f"/api/batch-filter-lots/{filter_lot_id}/ebr/sign", headers=admin_h,
                       json={"password": "AdminTest123", "meaning": "Xác nhận xong lọc", "reason": "Test"})
    assert sign.status_code == 200, sign.text

    blocked = client.delete(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h)
    assert blocked.status_code == 409, blocked.text
    assert "chữ ký điện tử" in blocked.json()["detail"]


# ==================== 17. Thứ tự "mẻ lọc cuối" ổn định (tie-breaker) ====================

def test_filter_lot_batches_order_is_stable_when_created_at_ties(client, admin_h):
    filter_lot_id, tank_id = _make_filter_lot(client, admin_h, "TIEBREAK")
    _finish_only_source(client, admin_h, filter_lot_id, v_drawn=100)
    add2 = client.post(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h)
    assert add2.status_code == 201, add2.text

    # Ép 2 bản ghi có CÙNG created_at (mô phỏng 2 request gần như đồng thời trên MSSQL) — trực
    # tiếp qua DB, mirror cách test_batch_pipeline_audit_fixes.py giả lập race condition.
    from app.database import SessionLocal
    from app.models.batch_pipeline import BatchFilterLotBatch
    db = SessionLocal()
    try:
        rows = db.execute(BatchFilterLotBatch.__table__.select().where(
            BatchFilterLotBatch.filter_lot_id == filter_lot_id)).fetchall()
        assert len(rows) == 2
        same_ts = rows[0].created_at
        for row in rows:
            b = db.get(BatchFilterLotBatch, row.batch_link_id)
            b.created_at = same_ts
        db.commit()
    finally:
        db.close()

    order1 = [b["batch_link_id"] for b in client.get(
        f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()]
    order2 = [b["batch_link_id"] for b in client.get(
        f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()]
    assert order1 == order2 == sorted(order1)
