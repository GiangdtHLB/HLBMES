"""CAPA theo giai đoạn + duyệt 2 cấp (Trưởng phòng KCS -> Giám đốc/Phó GĐ Sản xuất - Kỹ
thuật) + đính kèm tài liệu (xem services/quality_adv.py::CAPA_TRANSITIONS,
add_capa_attachment/list_capa_attachments/delete_capa_attachment)."""

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
def kcs_truongphong_h(client):
    return _login(client, "kcs_truongphong", "123456")


@pytest.fixture(scope="module")
def giamdoc_h(client):
    return _login(client, "giamdoc_sx", "123456")


def _open_capa(client, h, title):
    r = client.post("/api/qc/capa", headers=h, json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()["capa_id"]


def _advance_capa(client, h, capa_id, target, payload=None):
    body = {"target": target}
    if payload:
        body.update(payload)
    return client.post(f"/api/qc/capa/{capa_id}/transition", headers=h, json=body)


def test_full_chain_open_to_closed(client, kcs_h, kcs_truongphong_h, giamdoc_h):
    capa_id = _open_capa(client, kcs_h, "CAPA full chain")
    assert _advance_capa(client, kcs_h, capa_id, "investigation",
                         {"root_cause": "rc", "action_plan": "ap"}).status_code == 200
    assert _advance_capa(client, kcs_h, capa_id, "action").status_code == 200
    assert _advance_capa(client, kcs_h, capa_id, "verification", {"effectiveness": "ok"}).status_code == 200
    assert _advance_capa(client, kcs_h, capa_id, "kcs_approval",
                         {"effectiveness_checked_at": "2026-08-01"}).status_code == 200
    r_kcs = _advance_capa(client, kcs_truongphong_h, capa_id, "director_approval",
                          {"kcs_approval_note": "Đạt yêu cầu."})
    assert r_kcs.status_code == 200, r_kcs.text
    r_dir = _advance_capa(client, giamdoc_h, capa_id, "closed", {"close_note": "done"})
    assert r_dir.status_code == 200, r_dir.text

    c = next(x for x in client.get("/api/qc/capa", headers=kcs_h).json() if x["capa_id"] == capa_id)
    assert c["state"] == "closed"
    assert c["kcs_approved_by"] == "kcs_truongphong"
    assert c["director_approved_by"] == "giamdoc_sx"


def test_blocked_skip_ahead_kcs_approval_to_closed(client, kcs_h, giamdoc_h):
    """Không cho nhảy cóc kcs_approval -> closed (phải qua director_approval trước)."""
    capa_id = _open_capa(client, kcs_h, "CAPA skip-ahead")
    assert _advance_capa(client, kcs_h, capa_id, "investigation",
                         {"root_cause": "rc", "action_plan": "ap"}).status_code == 200
    assert _advance_capa(client, kcs_h, capa_id, "action").status_code == 200
    assert _advance_capa(client, kcs_h, capa_id, "verification", {"effectiveness": "ok"}).status_code == 200
    assert _advance_capa(client, kcs_h, capa_id, "kcs_approval",
                         {"effectiveness_checked_at": "2026-08-01"}).status_code == 200

    r = _advance_capa(client, giamdoc_h, capa_id, "closed", {"close_note": "done"})
    assert r.status_code == 409, r.text
    assert "Không thể chuyển" in r.json()["detail"]


def test_kcs_approval_to_director_approval_requires_kcs_permission(client, kcs_h, admin_h):
    """kcs (nhân viên KCS thường, không có quality.capa_approve_kcs) không được duyệt bước
    kcs_approval->director_approval — chỉ Trưởng phòng KCS (hoặc admin) mới có quyền này."""
    capa_id = _open_capa(client, kcs_h, "CAPA thiếu quyền KCS duyệt")
    assert _advance_capa(client, kcs_h, capa_id, "investigation",
                         {"root_cause": "rc", "action_plan": "ap"}).status_code == 200
    assert _advance_capa(client, kcs_h, capa_id, "action").status_code == 200
    assert _advance_capa(client, kcs_h, capa_id, "verification", {"effectiveness": "ok"}).status_code == 200
    assert _advance_capa(client, kcs_h, capa_id, "kcs_approval",
                         {"effectiveness_checked_at": "2026-08-01"}).status_code == 200

    r = _advance_capa(client, kcs_h, capa_id, "director_approval")
    assert r.status_code == 403, r.text


def test_director_approval_to_closed_requires_director_permission(client, kcs_h, kcs_truongphong_h):
    """kcs_truongphong (có quality.capa_approve_kcs nhưng KHÔNG có quality.capa_approve_director)
    không được tự đóng CAPA — chỉ Giám đốc/Phó GĐ Sản xuất - Kỹ thuật (hoặc admin) mới được."""
    capa_id = _open_capa(client, kcs_h, "CAPA thiếu quyền Giám đốc duyệt")
    assert _advance_capa(client, kcs_h, capa_id, "investigation",
                         {"root_cause": "rc", "action_plan": "ap"}).status_code == 200
    assert _advance_capa(client, kcs_h, capa_id, "action").status_code == 200
    assert _advance_capa(client, kcs_h, capa_id, "verification", {"effectiveness": "ok"}).status_code == 200
    assert _advance_capa(client, kcs_h, capa_id, "kcs_approval",
                         {"effectiveness_checked_at": "2026-08-01"}).status_code == 200
    assert _advance_capa(client, kcs_truongphong_h, capa_id, "director_approval",
                         {"kcs_approval_note": "Đạt yêu cầu."}).status_code == 200

    r = _advance_capa(client, kcs_truongphong_h, capa_id, "closed", {"close_note": "done"})
    assert r.status_code == 403, r.text


def test_admin_can_close_own_capa_bypassing_kcs_and_director_perms(client, admin_h):
    """Admin coi như có mọi quyền (require_perm bypass ADMIN) — vẫn tự đóng được CAPA mình
    mở, kể cả không có quality.capa_approve_kcs/director (giữ đúng hành vi #928)."""
    capa_id = _open_capa(client, admin_h, "CAPA admin full chain")
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


def _fully_close_capa(client, kcs_h, kcs_truongphong_h, giamdoc_h, title):
    capa_id = _open_capa(client, kcs_h, title)
    _advance_capa(client, kcs_h, capa_id, "investigation", {"root_cause": "rc", "action_plan": "ap"})
    _advance_capa(client, kcs_h, capa_id, "action")
    _advance_capa(client, kcs_h, capa_id, "verification", {"effectiveness": "ok"})
    _advance_capa(client, kcs_h, capa_id, "kcs_approval", {"effectiveness_checked_at": "2026-08-01"})
    _advance_capa(client, kcs_truongphong_h, capa_id, "director_approval",
                 {"kcs_approval_note": "Đạt yêu cầu."})
    _advance_capa(client, giamdoc_h, capa_id, "closed", {"close_note": "done"})
    return capa_id


def test_attachment_upload_list_download(client, kcs_h, kcs_truongphong_h, giamdoc_h):
    capa_id = _fully_close_capa(client, kcs_h, kcs_truongphong_h, giamdoc_h, "CAPA đính kèm")

    files = {"file": ("bao-cao.txt", b"noi dung bao cao capa", "text/plain")}
    up = client.post(f"/api/qc/capa/{capa_id}/attachments", headers=kcs_h,
                     files=files, data={"note": "Báo cáo điều tra"})
    assert up.status_code == 201, up.text
    attachment_id = up.json()["attachment_id"]

    lst = client.get(f"/api/qc/capa/{capa_id}/attachments", headers=kcs_h).json()
    assert any(a["attachment_id"] == attachment_id for a in lst)
    att = next(a for a in lst if a["attachment_id"] == attachment_id)
    assert att["file_name"] == "bao-cao.txt"
    assert att["note"] == "Báo cáo điều tra"
    assert att["uploaded_by"] == "kcs"

    dl = client.get(f"/api/qc/capa/attachments/{attachment_id}/download", headers=kcs_h)
    assert dl.status_code == 200, dl.text
    assert dl.content == b"noi dung bao cao capa"


def test_attachment_delete_blocked_for_unrelated_user(client, kcs_h, kcs_truongphong_h, giamdoc_h):
    capa_id = _fully_close_capa(client, kcs_h, kcs_truongphong_h, giamdoc_h, "CAPA đính kèm xóa")
    files = {"file": ("tep.txt", b"data", "text/plain")}
    up = client.post(f"/api/qc/capa/{capa_id}/attachments", headers=kcs_h, files=files)
    assert up.status_code == 201, up.text
    attachment_id = up.json()["attachment_id"]

    # giamdoc_sx không liên quan CAPA này (không phải opened_by, không phải admin) -> bị chặn.
    blocked = client.delete(f"/api/qc/capa/attachments/{attachment_id}", headers=giamdoc_h)
    assert blocked.status_code == 409, blocked.text

    ok = client.delete(f"/api/qc/capa/attachments/{attachment_id}", headers=kcs_h)
    assert ok.status_code == 200, ok.text
    lst = client.get(f"/api/qc/capa/{capa_id}/attachments", headers=kcs_h).json()
    assert not any(a["attachment_id"] == attachment_id for a in lst)


def test_capa_scope_persists_through_open_and_list(client, kcs_h):
    """Phạm vi (scope_type/scope_id) chọn lúc mở CAPA phải lưu và trả lại đúng qua danh sách —
    không suy ra qua deviation_id (xem AskUserQuestion trong phiên: cho chọn trực tiếp)."""
    r = client.post("/api/qc/capa", headers=kcs_h,
                    json={"title": "CAPA có phạm vi", "scope_type": "brew_batch", "scope_id": "BB-001"})
    assert r.status_code == 201, r.text
    capa_id = r.json()["capa_id"]

    c = next(x for x in client.get("/api/qc/capa", headers=kcs_h).json() if x["capa_id"] == capa_id)
    assert c["scope_type"] == "brew_batch"
    assert c["scope_id"] == "BB-001"


def test_capa_without_scope_leaves_scope_fields_null(client, kcs_h):
    """CAPA hành chính không gắn 1 công đoạn/lô cụ thể — để trống scope vẫn mở được bình thường."""
    capa_id = _open_capa(client, kcs_h, "CAPA hành chính không phạm vi")
    c = next(x for x in client.get("/api/qc/capa", headers=kcs_h).json() if x["capa_id"] == capa_id)
    assert c["scope_type"] is None
    assert c["scope_id"] is None


def test_director_approval_requires_kcs_approval_note(client, kcs_h, kcs_truongphong_h):
    """Trưởng phòng KCS không được duyệt suông — thiếu nhận xét thì chặn ở bước
    kcs_approval->director_approval (mỗi bước duyệt cần ý kiến riêng, theo yêu cầu người dùng)."""
    capa_id = _open_capa(client, kcs_h, "CAPA thiếu nhận xét KCS")
    assert _advance_capa(client, kcs_h, capa_id, "investigation",
                         {"root_cause": "rc", "action_plan": "ap"}).status_code == 200
    assert _advance_capa(client, kcs_h, capa_id, "action").status_code == 200
    assert _advance_capa(client, kcs_h, capa_id, "verification", {"effectiveness": "ok"}).status_code == 200
    assert _advance_capa(client, kcs_h, capa_id, "kcs_approval",
                         {"effectiveness_checked_at": "2026-08-01"}).status_code == 200

    r_missing = _advance_capa(client, kcs_truongphong_h, capa_id, "director_approval")
    assert r_missing.status_code == 409, r_missing.text
    assert "nhận xét" in r_missing.json()["detail"]

    r_ok = _advance_capa(client, kcs_truongphong_h, capa_id, "director_approval",
                         {"kcs_approval_note": "Đã kiểm tra hiệu lực, đạt yêu cầu."})
    assert r_ok.status_code == 200, r_ok.text

    c = next(x for x in client.get("/api/qc/capa", headers=kcs_h).json() if x["capa_id"] == capa_id)
    assert c["kcs_approval_note"] == "Đã kiểm tra hiệu lực, đạt yêu cầu."
    assert c["kcs_approved_by"] == "kcs_truongphong"
