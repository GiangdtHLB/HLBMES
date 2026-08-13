"""Deviation major/critical bắt buộc CAPA đã đóng (root cause + action plan + effectiveness +
ngày kiểm tra hiệu lực) trước khi đóng; cả Deviation và CAPA đều bắt buộc ghi chú đóng + người
đóng khác người mở; overdue_action_alerts gộp Deviation/CAPA quá hạn xử lý cho Dashboard."""

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
def giamdoc_h(client):
    return _login(client, "giamdoc_sx", "123456")


def _create_material(client, admin_h, code):
    r = client.post("/api/materials", headers=admin_h,
                    json={"code": code, "name": f"Vật tư {code}", "uom": "kg", "category": "other"})
    assert r.status_code == 201, r.text
    return r.json()["material_id"]


def _receive_lot(client, admin_h, code, mat_id):
    r = client.post("/api/warehouse/receive", headers=admin_h,
                    json={"lot_code": code, "material_id": mat_id, "quantity": 10, "uom": "kg"})
    assert r.status_code == 200, r.text
    return r.json()["lot_id"]


def _open_deviation(client, opener_h, lot_id, severity):
    r = client.post("/api/quality/deviations", headers=opener_h,
                    json={"scope_type": "lot", "scope_id": lot_id, "reason": "Test", "severity": severity})
    assert r.status_code == 201, r.text
    return r.json()["deviation_id"]


def _advance_deviation(client, h, dev_id, target, extra=None):
    payload = {"target": target}
    if extra:
        payload.update(extra)
    return client.post(f"/api/quality/deviations/{dev_id}/transition", headers=h, json=payload)


def _advance_to_approval(client, h, dev_id):
    assert _advance_deviation(client, h, dev_id, "triage").status_code == 200
    assert _advance_deviation(client, h, dev_id, "investigation", {"investigation": "x"}).status_code == 200
    assert _advance_deviation(client, h, dev_id, "disposition", {"disposition": "x"}).status_code == 200
    assert _advance_deviation(client, h, dev_id, "approval").status_code == 200


def _open_capa(client, h, title, deviation_id=None):
    r = client.post("/api/qc/capa", headers=h,
                    json={"title": title, "deviation_id": deviation_id})
    assert r.status_code == 201, r.text
    return r.json()["capa_id"]


def _advance_capa(client, h, capa_id, target, payload=None):
    body = {"target": target}
    if payload:
        body.update(payload)
    return client.post(f"/api/qc/capa/{capa_id}/transition", headers=h, json=body)


def _close_capa_fully(client, opener_h, closer_h, admin_h, capa_id):
    """Đi hết chuỗi 7 giai đoạn CAPA (xem CAPA_TRANSITIONS, services/quality_adv.py) —
    kcs_approval/director_approval dùng admin_h (bypass mọi permission gate) vì các test ở
    file này chỉ quan tâm hành vi Deviation, không phải quyền duyệt CAPA (xem
    test_capa_phases.py cho việc đó). opener_h phải có vai trò QA/SUPERVISOR (hoặc admin) để
    qua được transition verification->kcs_approval (require_role hiện tại)."""
    assert _advance_capa(client, opener_h, capa_id, "investigation",
                         {"root_cause": "rc", "action_plan": "ap"}).status_code == 200
    assert _advance_capa(client, opener_h, capa_id, "action").status_code == 200
    assert _advance_capa(client, opener_h, capa_id, "verification", {"effectiveness": "ok"}).status_code == 200
    assert _advance_capa(client, opener_h, capa_id, "kcs_approval",
                         {"effectiveness_checked_at": "2026-08-01"}).status_code == 200
    assert _advance_capa(client, admin_h, capa_id, "director_approval",
                         {"kcs_approval_note": "Đạt yêu cầu."}).status_code == 200
    r = _advance_capa(client, closer_h, capa_id, "closed", {"close_note": "done"})
    assert r.status_code == 200, r.text


def test_deviation_major_cannot_close_without_closed_capa(client, admin_h, kcs_h):
    mat_id = _create_material(client, admin_h, "DEVCAPA-MAT-1")
    lot_id = _receive_lot(client, admin_h, "DEVCAPA-LOT-1", mat_id)
    dev_id = _open_deviation(client, admin_h, lot_id, "major")
    _advance_to_approval(client, kcs_h, dev_id)

    r = _advance_deviation(client, kcs_h, dev_id, "closed", {"close_note": "note"})
    assert r.status_code == 409, r.text
    assert "CAPA" in r.json()["detail"]


def test_deviation_major_closes_after_capa_closed(client, admin_h, kcs_h):
    mat_id = _create_material(client, admin_h, "DEVCAPA-MAT-2")
    lot_id = _receive_lot(client, admin_h, "DEVCAPA-LOT-2", mat_id)
    dev_id = _open_deviation(client, admin_h, lot_id, "major")
    capa_id = _open_capa(client, kcs_h, "CAPA cho DEVCAPA-2", deviation_id=dev_id)
    _close_capa_fully(client, kcs_h, admin_h, admin_h, capa_id)

    _advance_to_approval(client, kcs_h, dev_id)
    r = _advance_deviation(client, kcs_h, dev_id, "closed", {"close_note": "note"})
    assert r.status_code == 200, r.text
    assert r.json()["close_note"] == "note"


def test_deviation_minor_closes_without_capa(client, admin_h, kcs_h):
    mat_id = _create_material(client, admin_h, "DEVCAPA-MAT-3")
    lot_id = _receive_lot(client, admin_h, "DEVCAPA-LOT-3", mat_id)
    dev_id = _open_deviation(client, admin_h, lot_id, "minor")
    _advance_to_approval(client, kcs_h, dev_id)
    r = _advance_deviation(client, kcs_h, dev_id, "closed", {"close_note": "note"})
    assert r.status_code == 200, r.text


def test_deviation_close_requires_note(client, admin_h, kcs_h):
    mat_id = _create_material(client, admin_h, "DEVCAPA-MAT-4")
    lot_id = _receive_lot(client, admin_h, "DEVCAPA-LOT-4", mat_id)
    dev_id = _open_deviation(client, admin_h, lot_id, "minor")
    _advance_to_approval(client, kcs_h, dev_id)
    r = _advance_deviation(client, kcs_h, dev_id, "closed")
    assert r.status_code == 409, r.text
    assert "ghi chú" in r.json()["detail"]


def test_deviation_closer_must_differ_from_opener(client, admin_h, kcs_h):
    mat_id = _create_material(client, admin_h, "DEVCAPA-MAT-5")
    lot_id = _receive_lot(client, admin_h, "DEVCAPA-LOT-5", mat_id)
    dev_id = _open_deviation(client, kcs_h, lot_id, "minor")
    _advance_to_approval(client, kcs_h, dev_id)
    r = _advance_deviation(client, kcs_h, dev_id, "closed", {"close_note": "note"})
    assert r.status_code == 409, r.text
    assert "khác người mở" in r.json()["detail"]


def test_capa_kcs_approval_requires_effectiveness_date(client, admin_h, kcs_h):
    """Hiệu lực + ngày kiểm tra hiệu lực bắt buộc trước khi chuyển sang kcs_approval (đã
    dời khỏi bước "closed" cũ sang đúng bước này — xem services/quality_adv.py::transition_capa)."""
    capa_id = _open_capa(client, kcs_h, "CAPA thiếu điều kiện duyệt")
    assert _advance_capa(client, kcs_h, capa_id, "investigation",
                         {"root_cause": "rc", "action_plan": "ap"}).status_code == 200
    assert _advance_capa(client, kcs_h, capa_id, "action").status_code == 200
    assert _advance_capa(client, kcs_h, capa_id, "verification", {"effectiveness": "ok"}).status_code == 200

    r = _advance_capa(client, kcs_h, capa_id, "kcs_approval")
    assert r.status_code == 409, r.text
    assert "ngày kiểm tra hiệu lực" in r.json()["detail"]


def test_capa_closed_requires_close_note(client, admin_h, kcs_h):
    capa_id = _open_capa(client, kcs_h, "CAPA thiếu ghi chú đóng")
    assert _advance_capa(client, kcs_h, capa_id, "investigation",
                         {"root_cause": "rc", "action_plan": "ap"}).status_code == 200
    assert _advance_capa(client, kcs_h, capa_id, "action").status_code == 200
    assert _advance_capa(client, kcs_h, capa_id, "verification", {"effectiveness": "ok"}).status_code == 200
    assert _advance_capa(client, kcs_h, capa_id, "kcs_approval",
                         {"effectiveness_checked_at": "2026-08-01"}).status_code == 200
    assert _advance_capa(client, admin_h, capa_id, "director_approval",
                         {"kcs_approval_note": "Đạt yêu cầu."}).status_code == 200

    r = _advance_capa(client, admin_h, capa_id, "closed")
    assert r.status_code == 409, r.text
    assert "ghi chú đóng" in r.json()["detail"]


def test_capa_closer_must_differ_from_opener(client, admin_h, giamdoc_h):
    """closer_h (giamdoc_h) có quyền quality.capa_approve_director nên qua được permission
    gate, nhưng bị chặn vì cũng CHÍNH LÀ người mở CAPA (opener_h == closer_h). giamdoc_sx
    không có sẵn quality.deviation (chỉ có production.release_to_wms + capa_approve_director
    theo seed.py) — cấp tạm quyền đó qua PUT /auth/users để mở được CAPA trong test này."""
    u = client.get("/api/auth/users", headers=admin_h).json()
    giamdoc_user = next(x for x in u if x["username"] == "giamdoc_sx")
    grant = client.put("/api/auth/users/giamdoc_sx", headers=admin_h, json={
        "full_name": giamdoc_user["full_name"], "job_title": giamdoc_user["job_title"],
        "role": giamdoc_user["role"], "allowed_views": giamdoc_user["allowed_views"],
        "permissions": giamdoc_user["permissions"] + ",quality.deviation"})
    assert grant.status_code == 200, grant.text

    capa_id = _open_capa(client, giamdoc_h, "CAPA closer=opener")
    assert _advance_capa(client, giamdoc_h, capa_id, "investigation",
                         {"root_cause": "rc", "action_plan": "ap"}).status_code == 200
    assert _advance_capa(client, giamdoc_h, capa_id, "action").status_code == 200
    assert _advance_capa(client, giamdoc_h, capa_id, "verification", {"effectiveness": "ok"}).status_code == 200
    assert _advance_capa(client, giamdoc_h, capa_id, "kcs_approval",
                         {"effectiveness_checked_at": "2026-08-01"}).status_code == 200
    assert _advance_capa(client, admin_h, capa_id, "director_approval",
                         {"kcs_approval_note": "Đạt yêu cầu."}).status_code == 200

    r = _advance_capa(client, giamdoc_h, capa_id, "closed", {"close_note": "done"})
    assert r.status_code == 409, r.text
    assert "khác người mở" in r.json()["detail"]


def test_capa_admin_can_close_own_capa(client, admin_h):
    capa_id = _open_capa(client, admin_h, "CAPA admin tự mở tự đóng")
    assert _advance_capa(client, admin_h, capa_id, "investigation",
                         {"root_cause": "rc", "action_plan": "ap"}).status_code == 200
    assert _advance_capa(client, admin_h, capa_id, "action").status_code == 200
    assert _advance_capa(client, admin_h, capa_id, "verification", {"effectiveness": "ok"}).status_code == 200
    assert _advance_capa(client, admin_h, capa_id, "kcs_approval",
                         {"effectiveness_checked_at": "2026-08-01"}).status_code == 200
    assert _advance_capa(client, admin_h, capa_id, "director_approval",
                         {"kcs_approval_note": "Đạt yêu cầu."}).status_code == 200
    r = _advance_capa(client, admin_h, capa_id, "closed", {"close_note": "done"})
    assert r.status_code == 200, r.text


def test_deviation_admin_can_close_own_deviation(client, admin_h):
    mat_id = _create_material(client, admin_h, "DEVCAPA-MAT-7")
    lot_id = _receive_lot(client, admin_h, "DEVCAPA-LOT-7", mat_id)
    dev_id = _open_deviation(client, admin_h, lot_id, "minor")
    _advance_to_approval(client, admin_h, dev_id)
    r = _advance_deviation(client, admin_h, dev_id, "closed", {"close_note": "note"})
    assert r.status_code == 200, r.text


def test_overdue_action_alerts_lists_only_open_past_due(client, admin_h, kcs_h):
    mat_id = _create_material(client, admin_h, "DEVCAPA-MAT-6")
    lot_id = _receive_lot(client, admin_h, "DEVCAPA-LOT-6", mat_id)
    r = client.post("/api/quality/deviations", headers=admin_h,
                    json={"scope_type": "lot", "scope_id": lot_id, "reason": "Quá hạn",
                          "severity": "minor", "due_date": "2020-01-01"})
    assert r.status_code == 201, r.text
    dev_id = r.json()["deviation_id"]

    capa_r = client.post("/api/qc/capa", headers=kcs_h,
                         json={"title": "CAPA quá hạn", "due_date": "2020-01-01"})
    assert capa_r.status_code == 201, capa_r.text

    body = client.get("/api/reports/overdue-action-alerts", headers=admin_h).json()
    codes = {it["code"] for it in body["items"]}
    dev = client.get("/api/quality/deviations", headers=admin_h).json()
    dev_code = next(d["deviation_code"] for d in dev if d["deviation_id"] == dev_id)
    assert dev_code in codes
    assert "CAPA quá hạn" in [it["title"] for it in body["items"]] or any(
        it["kind"] == "capa" for it in body["items"])
    for it in body["items"]:
        assert it["days_overdue"] > 0
