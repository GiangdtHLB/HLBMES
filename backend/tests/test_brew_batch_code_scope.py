"""Test: số mẻ (BrewBatch.batch_code) là 1 dãy đếm chung TOÀN NHÀ MÁY — 2 mã nấu khác
nhau KHÔNG được dùng trùng số mẻ. Dãy số này reset lại từ đầu mỗi năm (theo năm của
started_at), nên số mẻ chỉ cần duy nhất TRONG CÙNG 1 năm, không phải vĩnh viễn.

Lưu ý: mọi test trong file này dùng CHUNG 1 DB (module-scoped) — mỗi test phải dùng
batch_code (+ năm) riêng biệt, không trùng với batch_code đã tạo ở test khác trong file."""

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


def _a_brewhouse_line(client, admin_h):
    """Dây chuyền nấu (ProductionLine.kind="brewhouse") dùng cho test — lấy lại nếu đã có
    (idempotent), tạo mới nếu chưa có (seed.py không seed sẵn dây chuyền loại brewhouse)."""
    existing = client.get("/api/lines", headers=admin_h, params={"kind": "brewhouse"}).json()
    if existing:
        return existing[0]["line_id"]
    r = client.post("/api/lines", headers=admin_h,
                    json={"code": "BREW-TEST-01", "name": "Nhà nấu test", "kind": "brewhouse"})
    assert r.status_code == 201, r.text
    return r.json()["line_id"]


@pytest.fixture(scope="module")
def brewhouse_line_id(client, admin_h):
    return _a_brewhouse_line(client, admin_h)


def _a_brew(client, admin_h, suffix):
    order = client.post("/api/brewing/orders", headers=admin_h,
                       json={"order_code": f"LN-{suffix}", "auto_from_bom": False, "planned_volume_hl": 100})
    assert order.status_code == 201, order.text
    b = client.post("/api/brewing/brews", headers=admin_h,
                   json={"brew_code": f"BR-{suffix}", "wort_type": "Dịch test",
                         "brew_order_id": order.json()["brew_order_id"]})
    assert b.status_code == 201, b.text
    return b.json()["brew_id"]


def test_same_batch_code_blocked_across_different_brews_same_year(client, admin_h, brewhouse_line_id):
    brew_a = _a_brew(client, admin_h, "BATCHSCOPE-A")
    brew_b = _a_brew(client, admin_h, "BATCHSCOPE-B")

    a2 = client.post(f"/api/brewing/brews/{brew_a}/batches", headers=admin_h,
                     json={"batch_code": "101", "started_at": "2026-01-15T08:00:00", "line_id": brewhouse_line_id})
    assert a2.status_code == 201, a2.text

    b2 = client.post(f"/api/brewing/brews/{brew_b}/batches", headers=admin_h,
                     json={"batch_code": "101", "started_at": "2026-03-01T08:00:00", "line_id": brewhouse_line_id})
    assert b2.status_code == 409, b2.text


def test_batch_code_still_unique_within_same_brew(client, admin_h, brewhouse_line_id):
    brew = _a_brew(client, admin_h, "BATCHSCOPE-C")
    first = client.post(f"/api/brewing/brews/{brew}/batches", headers=admin_h,
                        json={"batch_code": "102", "started_at": "2026-01-20T08:00:00", "line_id": brewhouse_line_id})
    assert first.status_code == 201, first.text

    dup = client.post(f"/api/brewing/brews/{brew}/batches", headers=admin_h,
                      json={"batch_code": "102", "started_at": "2026-01-21T08:00:00", "line_id": brewhouse_line_id})
    assert dup.status_code == 409, dup.text


def test_batch_code_freed_after_delete_even_for_different_brew(client, admin_h, brewhouse_line_id):
    """Xóa mẻ ở 1 mã nấu thì số mẻ đó được giải phóng — mã nấu KHÁC (cùng năm) có thể
    dùng lại được, không còn báo trùng."""
    brew_old = _a_brew(client, admin_h, "BATCHSCOPE-OLD")
    created = client.post(f"/api/brewing/brews/{brew_old}/batches", headers=admin_h,
                          json={"batch_code": "103", "started_at": "2026-02-01T08:00:00", "line_id": brewhouse_line_id})
    assert created.status_code == 201, created.text
    batch_id = created.json()["batch_id"]

    brew_other = _a_brew(client, admin_h, "BATCHSCOPE-OTHER")
    blocked = client.post(f"/api/brewing/brews/{brew_other}/batches", headers=admin_h,
                         json={"batch_code": "103", "started_at": "2026-02-02T08:00:00", "line_id": brewhouse_line_id})
    assert blocked.status_code == 409, blocked.text

    deleted = client.delete(f"/api/brewing/brews/{brew_old}/batches/{batch_id}", headers=admin_h)
    assert deleted.status_code == 204, deleted.text

    now_allowed = client.post(f"/api/brewing/brews/{brew_other}/batches", headers=admin_h,
                              json={"batch_code": "103", "started_at": "2026-02-02T08:00:00", "line_id": brewhouse_line_id})
    assert now_allowed.status_code == 201, now_allowed.text


def test_batch_code_resets_each_year(client, admin_h, brewhouse_line_id):
    """Số mẻ đã dùng trong năm 2026 vẫn được đánh lại từ đầu trong năm 2027 — dãy đếm
    reset theo năm, không phải vĩnh viễn toàn hệ thống."""
    brew_2026 = _a_brew(client, admin_h, "BATCHSCOPE-Y2026")
    b2026 = client.post(f"/api/brewing/brews/{brew_2026}/batches", headers=admin_h,
                       json={"batch_code": "104", "started_at": "2026-06-01T08:00:00", "line_id": brewhouse_line_id})
    assert b2026.status_code == 201, b2026.text

    brew_2027 = _a_brew(client, admin_h, "BATCHSCOPE-Y2027")
    b2027 = client.post(f"/api/brewing/brews/{brew_2027}/batches", headers=admin_h,
                       json={"batch_code": "104", "started_at": "2027-01-05T08:00:00", "line_id": brewhouse_line_id})
    assert b2027.status_code == 201, b2027.text


def test_qc_result_not_shared_between_batches_with_same_code(client, admin_h, brewhouse_line_id):
    """Chỉ tiêu (QualityResult scope_type=brew_batch) phải scope theo batch_id (duy nhất
    toàn hệ thống), KHÔNG theo batch_code — dùng 2 mẻ cùng batch_code ở 2 năm khác nhau
    (trùng code được vì reset theo năm) để xác nhận chỉ tiêu không bị lẫn giữa 2 mẻ."""
    brew_a = _a_brew(client, admin_h, "QCSCOPE-A")
    brew_b = _a_brew(client, admin_h, "QCSCOPE-B")

    ba = client.post(f"/api/brewing/brews/{brew_a}/batches", headers=admin_h,
                     json={"batch_code": "105", "started_at": "2028-05-01T08:00:00", "line_id": brewhouse_line_id})
    assert ba.status_code == 201, ba.text
    batch_id_a = ba.json()["batch_id"]

    bb = client.post(f"/api/brewing/brews/{brew_b}/batches", headers=admin_h,
                     json={"batch_code": "105", "started_at": "2029-05-01T08:00:00", "line_id": brewhouse_line_id})
    assert bb.status_code == 201, bb.text
    batch_id_b = bb.json()["batch_id"]

    rec = client.post("/api/brewing/qc-results", headers=admin_h, json={
        "stage": "nau", "scope_type": "brew_batch", "scope_id": batch_id_a,
        "parameter": "TEST-PARAM", "value": 5.0,
    })
    assert rec.status_code == 201, rec.text

    status_a = client.get("/api/brewing/qc-status", headers=admin_h,
                          params={"stage": "nau", "scope_type": "brew_batch", "scope_id": batch_id_a}).json()
    assert any(r["parameter"] == "TEST-PARAM" for r in status_a["recorded"])

    status_b = client.get("/api/brewing/qc-status", headers=admin_h,
                          params={"stage": "nau", "scope_type": "brew_batch", "scope_id": batch_id_b}).json()
    assert not any(r["parameter"] == "TEST-PARAM" for r in status_b["recorded"]), \
        "Mẻ của mã nấu B không được thấy chỉ tiêu đã khai báo cho mẻ của mã nấu A"
