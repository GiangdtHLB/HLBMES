"""Bug thực tế 2026-10-16 (phát hiện qua câu hỏi người dùng: "sao không thấy mẻ nào onhold ở
đây" khi xem bảng "Lịch sử Hold/Release"): mọi lần quality_status tự động chuyển ON_HOLD —
qua services/quality.py::record_result (scope_type batch/lot) HOẶC qua
services/qc_catalog.py::sync_stage_quality_status (batch_filter_lot/batch_pack_lot)/
sync_tank_quality_status (batch_tank) — đều đổi thẳng cột DB, KHÔNG ghi audit log nào cả. Chỉ
có set_hold() (thao tác tay) và attempt_auto_release() (tự release) là ghi audit — khiến lịch sử
Hold/Release chỉ toàn thấy RELEASE, không bao giờ thấy HOLD, dù trạng thái "ĐANG HOLD" hiện tại
là có thật. Sửa: mọi nơi tự động đổi quality_status giờ đều ghi audit action "hold"/"release"
khi THẬT SỰ có chuyển trạng thái (so sánh before/after, không ghi lặp nếu không đổi)."""

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


def _make_batch(client, admin_h):
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(x for x in vers if x["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                          "planned_qty": 1000, "allow_shortage": True})
    assert b.status_code == 201, b.text
    return b.json()["batch_id"]


def _audit_actions(client, admin_h, entity_type, entity_id):
    rows = client.get(f"/api/audit?entity_type={entity_type}&entity_id={entity_id}&action=hold,release",
                      headers=admin_h).json()
    # API trả mới nhất trước (seq desc) -> đảo lại cho đúng thứ tự thời gian xảy ra.
    return [r["action"] for r in reversed(rows)]


def test_record_result_fail_logs_hold_audit_once(client, admin_h):
    """services/quality.py::record_result — FAIL lần đầu phải ghi đúng 1 dòng audit "hold"; FAIL
    thêm lần nữa (vẫn đang on_hold, không đổi trạng thái) KHÔNG được ghi thêm dòng nào (tránh
    lịch sử Hold/Release ngập rác 1 dòng/mỗi lần ghi FAIL thêm)."""
    batch_id = _make_batch(client, admin_h)
    assert _audit_actions(client, admin_h, "batch", batch_id) == []

    r1 = client.post("/api/quality/results", headers=admin_h, json={
        "scope_type": "batch", "scope_id": batch_id, "parameter": "AUDITQ1",
        "value": 99, "lower_limit": 1, "upper_limit": 10})
    assert r1.status_code == 201, r1.text
    assert _audit_actions(client, admin_h, "batch", batch_id) == ["hold"]

    r2 = client.post("/api/quality/results", headers=admin_h, json={
        "scope_type": "batch", "scope_id": batch_id, "parameter": "AUDITQ2",
        "value": 98, "lower_limit": 1, "upper_limit": 10})
    assert r2.status_code == 201, r2.text
    # Vẫn đang on_hold từ trước -> không đổi trạng thái -> không ghi thêm audit.
    assert _audit_actions(client, admin_h, "batch", batch_id) == ["hold"]


def test_sync_stage_quality_status_logs_hold_at_creation_and_release_after_pass(client, admin_h):
    """services/qc_catalog.py::sync_stage_quality_status — lô lọc mới tạo (chưa khai chỉ tiêu bắt
    buộc) phải tự ghi audit "hold" ngay lúc tạo; sau khi khai đủ + không FAIL, phải tự ghi audit
    "release"."""
    beer_type_id = client.post("/api/beer-types", headers=admin_h,
                               json={"code": "BT_HOLDAUDIT", "name": "Loai bia HOLDAUDIT"}).json()["beer_type_id"]
    param_code = "CT_HOLDAUDIT"
    p = client.post("/api/qc/parameters", headers=admin_h,
                    json={"code": param_code, "name": "Chi tieu HOLDAUDIT", "lsl": 1, "usl": 10})
    assert p.status_code == 201, p.text
    g = client.post("/api/qc/groups", headers=admin_h,
                    json={"code": "GRP_HOLDAUDIT", "name": "Nhom HOLDAUDIT"})
    assert g.status_code == 201, g.text
    group_id = g.json()["group_id"]
    it = client.post(f"/api/qc/groups/{group_id}/items", headers=admin_h,
                     json={"param_id": p.json()["param_id"], "mandatory": True})
    assert it.status_code == 201, it.text
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": "loc", "group_id": group_id, "beer_type_id": beer_type_id, "mandatory": True})
    assert link.status_code == 201, link.text

    batch_id = _make_batch(client, admin_h)
    for target in ("ready", "running"):
        r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": target})
        assert r.status_code == 200, r.text
    aq = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": 1000})
    assert aq.status_code == 200, aq.text
    fin = client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={})
    assert fin.status_code == 200, fin.text
    r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "completed"})
    assert r.status_code == 200, r.text
    tank = client.post("/api/batch-tanks", headers=admin_h,
                       json={"batch_ids": [batch_id], "tank_code": "TANK-HOLDAUDIT"})
    assert tank.status_code == 201, tank.text
    bbt = client.post("/api/lines", headers=admin_h,
                      json={"code": "BBT-HOLDAUDIT", "name": "BBT HOLDAUDIT", "kind": "tank_bbt"})
    assert bbt.status_code == 201, bbt.text
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": "FLOT-HOLDAUDIT", "to_bbt": bbt.json()["code"],
        "sources": [{"source_type": "tank", "source_tank_id": tank.json()["tank_id"]}],
        "category": "Bia lon", "beer_type_id": beer_type_id})
    assert draw.status_code == 201, draw.text
    filter_lot_id = draw.json()["filter_lot_id"]

    # Chưa khai chỉ tiêu nào -> ngay lúc tạo đã tự chuyển on_hold -> phải có đúng 1 audit "hold".
    assert draw.json()["quality_status"] == "on_hold"
    assert _audit_actions(client, admin_h, "batch_filter_lot", filter_lot_id) == ["hold"]

    rec = client.post("/api/brewing/qc-results", headers=admin_h, json={
        "stage": "loc", "scope_type": "batch_filter_lot", "scope_id": filter_lot_id,
        "parameter": param_code, "value": 5, "lower_limit": 1, "upper_limit": 10})
    assert rec.status_code == 201, rec.text

    fl = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()
    assert fl["quality_status"] == "released"
    assert _audit_actions(client, admin_h, "batch_filter_lot", filter_lot_id) == ["hold", "release"]
