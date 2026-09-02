"""Test Phase 2 — "Mẻ nấu" (BatchExecution, Mẻ sản xuất) dùng chỉ tiêu qua StageQcGroup
(stage "nau", scope_type "batch") thay vì đọc thẳng recipe_snapshot.quality_checks.

Xem services/batches.py::_assert_closeable, services/qc_catalog.py::missing_mandatory_params
(nhánh scope_type == "batch") và list_pending_stage_declarations (khối BatchExecution).
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
    """Tạo 1 BatchExecution mới từ Lệnh nấu + recipe version effective đã có sẵn trong seed
    (mirror pattern test_recipe_suspend_resume) — trả về (batch_id, product_id)."""
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(v for v in vers if v["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                          "batch_code": batch_code, "planned_qty": 1000, "allow_shortage": True})
    assert b.status_code == 201, b.text
    return b.json()["batch_id"], v["product_id"]


def test_batch_release_blocked_until_stage_qc_satisfied(client, admin_h):
    group_id, code = _make_group_with_param(client, admin_h, "BATCHNAU")
    batch_id, product_id = _make_batch(client, admin_h, "1")
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": "nau", "group_id": group_id, "product_id": product_id,
                             "mandatory": True})
    assert link.status_code == 201, link.text

    st = client.get(f"/api/brewing/qc-status?stage=nau&scope_type=batch&scope_id={batch_id}"
                    f"&product_id={product_id}", headers=admin_h).json()
    assert st["pending"] == [code]
    assert st["can_release"] is False

    blocked = client.post("/api/quality/hold", headers=admin_h,
                          json={"scope_type": "batch", "scope_id": batch_id, "on_hold": False})
    assert blocked.status_code == 409, blocked.text

    rec = client.post("/api/brewing/qc-results", headers=admin_h,
                      json={"stage": "nau", "scope_type": "batch", "scope_id": batch_id,
                            "parameter": code, "value": 5, "lower_limit": 1, "upper_limit": 10})
    assert rec.status_code == 201, rec.text

    ok = client.post("/api/quality/hold", headers=admin_h,
                     json={"scope_type": "batch", "scope_id": batch_id, "on_hold": False})
    assert ok.status_code == 200, ok.text
    assert ok.json()["quality_status"] == "released"

    client.delete(f"/api/qc/stage-groups/{link.json()['link_id']}", headers=admin_h)


def test_batch_close_blocked_until_stage_qc_satisfied(client, admin_h):
    """Close (transition -> closed) phải kiểm QC bắt buộc qua StageQcGroup (không còn đọc
    recipe_snapshot.quality_checks) — mirror hành vi release ở test trên, qua đường transition."""
    group_id, code = _make_group_with_param(client, admin_h, "BATCHCLOSE")
    batch_id, product_id = _make_batch(client, admin_h, "2")
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": "nau", "group_id": group_id, "product_id": product_id,
                             "mandatory": True})
    assert link.status_code == 201, link.text

    client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "ready"})
    client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "running"})
    client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": 1000})
    client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={})
    complete = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "completed"})
    assert complete.status_code == 200, complete.text

    # chưa release chất lượng -> chặn close (lý do "chưa release", chưa tới nhánh QC)
    blocked_hold = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h,
                               json={"target": "closed"})
    assert blocked_hold.status_code == 409, blocked_hold.text

    # release bị chặn vì còn thiếu chỉ tiêu QC bắt buộc
    blocked_release = client.post("/api/quality/hold", headers=admin_h,
                                  json={"scope_type": "batch", "scope_id": batch_id, "on_hold": False})
    assert blocked_release.status_code == 409, blocked_release.text

    rec = client.post("/api/brewing/qc-results", headers=admin_h,
                      json={"stage": "nau", "scope_type": "batch", "scope_id": batch_id,
                            "parameter": code, "value": 5, "lower_limit": 1, "upper_limit": 10})
    assert rec.status_code == 201, rec.text

    ok_release = client.post("/api/quality/hold", headers=admin_h,
                             json={"scope_type": "batch", "scope_id": batch_id, "on_hold": False})
    assert ok_release.status_code == 200, ok_release.text

    ok_close = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h,
                           json={"target": "closed"})
    assert ok_close.status_code == 200, ok_close.text
    assert ok_close.json()["state"] == "closed"

    client.delete(f"/api/qc/stage-groups/{link.json()['link_id']}", headers=admin_h)


def test_batch_with_fail_result_blocks_release(client, admin_h):
    group_id, code = _make_group_with_param(client, admin_h, "BATCHFAIL")
    batch_id, product_id = _make_batch(client, admin_h, "3")
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": "nau", "group_id": group_id, "product_id": product_id,
                             "mandatory": True})
    assert link.status_code == 201, link.text

    fail = client.post("/api/brewing/qc-results", headers=admin_h,
                       json={"stage": "nau", "scope_type": "batch", "scope_id": batch_id,
                             "parameter": code, "value": 20, "lower_limit": 1, "upper_limit": 10})
    assert fail.status_code == 201 and fail.json()["status"] == "fail", fail.text

    st = client.get(f"/api/brewing/qc-status?stage=nau&scope_type=batch&scope_id={batch_id}"
                    f"&product_id={product_id}", headers=admin_h).json()
    assert code not in st["pending"]     # đã khai báo (không còn thiếu)
    assert st["can_release"] is False    # nhưng FAIL nên vẫn chặn

    blocked = client.post("/api/quality/hold", headers=admin_h,
                          json={"scope_type": "batch", "scope_id": batch_id, "on_hold": False})
    assert blocked.status_code == 409, blocked.text

    client.delete(f"/api/qc/stage-groups/{link.json()['link_id']}", headers=admin_h)


def test_batch_without_stage_group_never_pending_and_release_unblocked(client, admin_h):
    """Không có nhóm chỉ tiêu bắt buộc nào gán stage "nau" cho product này -> required rỗng,
    hành vi cũ (release không bị QC chặn) vẫn giữ nguyên — không phá batch hiện có/seed."""
    batch_id, product_id = _make_batch(client, admin_h, "4")
    st = client.get(f"/api/brewing/qc-status?stage=nau&scope_type=batch&scope_id={batch_id}"
                    f"&product_id={product_id}", headers=admin_h).json()
    assert st["pending"] == [] and st["can_release"] is True

    pending = client.get("/api/quality/pending-stage-qc", headers=admin_h).json()
    assert not any(p["scope_type"] == "batch" and p["scope_id"] == batch_id for p in pending)

    ok = client.post("/api/quality/hold", headers=admin_h,
                     json={"scope_type": "batch", "scope_id": batch_id, "on_hold": False})
    assert ok.status_code == 200, ok.text


def test_batch_shows_in_pending_stage_declarations(client, admin_h):
    """Mẻ SX (BatchExecution, stage "nau") giờ LUÔN ở lại panel "chờ khai báo" kể cả sau khi
    khai đủ — chỉ `pending` đổi thành rỗng, KHÔNG bị loại khỏi danh sách (yêu cầu người dùng
    2026-09-02: "khi khai xong công đoạn đó thì không cần ẩn đi nhé", áp dụng cho toàn bộ
    pipeline "Mẻ SX", không riêng Lên men)."""
    group_id, code = _make_group_with_param(client, admin_h, "BATCHPENDLIST")
    batch_id, product_id = _make_batch(client, admin_h, "5")
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": "nau", "group_id": group_id, "product_id": product_id,
                             "mandatory": True})
    assert link.status_code == 201, link.text

    pending = client.get("/api/quality/pending-stage-qc", headers=admin_h).json()
    row = next(p for p in pending if p["scope_type"] == "batch" and p["scope_id"] == batch_id)
    assert row["stage"] == "nau"
    assert code in row["pending"]
    assert "5" in row["label"]

    client.post("/api/brewing/qc-results", headers=admin_h,
               json={"stage": "nau", "scope_type": "batch", "scope_id": batch_id,
                     "parameter": code, "value": 5, "lower_limit": 1, "upper_limit": 10})
    pending_after = client.get("/api/quality/pending-stage-qc", headers=admin_h).json()
    row_after = next((p for p in pending_after if p["scope_type"] == "batch" and p["scope_id"] == batch_id), None)
    assert row_after is not None
    assert row_after["pending"] == []

    client.delete(f"/api/qc/stage-groups/{link.json()['link_id']}", headers=admin_h)
