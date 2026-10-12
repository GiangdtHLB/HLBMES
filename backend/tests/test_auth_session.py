"""Test thời hạn phiên đăng nhập (UserSession.expires_at) — xem app/config.py::SESSION_HOURS,
app/services/ops_setting.py, routers/auth.py::login, security.py::get_current_user.

Bug thực tế 2026-10-12: routers/auth.py tự khai hằng số `SESSION_HOURS = 12` CỤC BỘ, không đọc
`config.SESSION_HOURS` — biến môi trường MES_SESSION_HOURS hoàn toàn vô tác dụng dù trông như
cấu hình được. Yêu cầu người dùng: (1) không muốn tài khoản bị buộc đăng xuất sau 12h — đổi mặc
định thành ~1 năm (8760h); (2) cấu hình được ngay trong Cài đặt vận hành (ops_setting.session_
hours, PUT /ops-settings) thay vì chỉ qua biến môi trường lúc khởi động server."""

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
from app.common import utcnow
from app.config import SESSION_HOURS
from app.database import SessionLocal
from app.models.auth import UserSession


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


def test_session_hours_default_is_about_one_year():
    """Mặc định phiên đăng nhập ~1 năm (8760h) — không còn 12h như trước."""
    assert SESSION_HOURS == 8760


def test_login_session_expiry_matches_config_session_hours(client):
    """Token tạo lúc đăng nhập phải hết hạn đúng theo config.SESSION_HOURS (qua MES_SESSION_HOURS
    nếu có khai), KHÔNG còn bị ghi đè bởi hằng số cục bộ 12h từng sót lại ở routers/auth.py."""
    r = client.post("/api/auth/login", json={"username": "admin", "password": "AdminTest123"})
    assert r.status_code == 200, r.text
    token = r.json()["token"]

    db = SessionLocal()
    try:
        sess = db.get(UserSession, token)
        assert sess is not None
        delta_hours = (sess.expires_at - sess.created_at).total_seconds() / 3600
        assert abs(delta_hours - SESSION_HOURS) < 0.01
        # Hết hạn phải còn rất xa (không còn kiểu hết hạn sau 12h như trước).
        assert (sess.expires_at - utcnow()).days > 300
    finally:
        db.close()


def test_ops_settings_includes_session_hours_default(client, admin_h):
    s = client.get("/api/ops-settings", headers=admin_h).json()
    assert s["session_hours"] == SESSION_HOURS


def test_updating_session_hours_via_settings_changes_new_login_expiry(client, admin_h):
    """Yêu cầu người dùng 2026-10-12: "cho tôi cài trong cài đặt được không, sẽ cài thời gian
    đăng nhập" — sửa qua PUT /ops-settings phải đổi ngay thời hạn của các phiên đăng nhập MỚI
    (phiên đã cấp từ trước giữ nguyên hạn cũ, không bị đổi ngược — xem UserSession.expires_at
    chỉ gán 1 lần lúc login, không có cơ chế cập nhật lại phiên đang sống)."""
    s = client.get("/api/ops-settings", headers=admin_h).json()
    s["session_hours"] = 48
    upd = client.put("/api/ops-settings", headers=admin_h, json=s)
    assert upd.status_code == 200, upd.text
    assert upd.json()["session_hours"] == 48

    r = client.post("/api/auth/login", json={"username": "admin", "password": "AdminTest123"})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    db = SessionLocal()
    try:
        sess = db.get(UserSession, token)
        assert sess is not None
        delta_hours = (sess.expires_at - sess.created_at).total_seconds() / 3600
        assert abs(delta_hours - 48) < 0.01
    finally:
        db.close()

    # Trả lại mặc định để không ảnh hưởng các test khác trong cùng file (module-scope DB).
    s["session_hours"] = SESSION_HOURS
    client.put("/api/ops-settings", headers=admin_h, json=s)


def test_update_settings_rejects_non_positive_session_hours(client, admin_h):
    s = client.get("/api/ops-settings", headers=admin_h).json()
    s["session_hours"] = 0
    bad = client.put("/api/ops-settings", headers=admin_h, json=s)
    assert bad.status_code in (400, 409), bad.text
