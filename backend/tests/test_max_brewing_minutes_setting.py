"""Test ngưỡng cảnh báo giờ nấu chuẩn tối đa — app/services/ops_setting.py::max_brewing_minutes.

Yêu cầu người dùng 2026-10-16: "Mẻ nấu thì từ giờ bắt đầu đến giờ kết thúc không quá 8h00, nếu
quá thì sẽ cảnh báo [...] Số giờ này có thể cài đặt ở trong phần cài đặt, cài giờ, phút." Ngưỡng
chỉ dùng để FE hiển thị ghi chú cảnh báo (không chặn ghi) — test này chỉ xác nhận field
GET/PUT /ops-settings round-trip đúng và validation > 0 hoạt động, giống pattern của
test_auth_session.py cho session_hours.
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


@pytest.fixture(scope="module")
def admin_h(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "AdminTest123"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_ops_settings_includes_max_brewing_minutes_default(client, admin_h):
    s = client.get("/api/ops-settings", headers=admin_h).json()
    assert s["max_brewing_minutes"] == 480


def test_updating_max_brewing_minutes_round_trips(client, admin_h):
    s = client.get("/api/ops-settings", headers=admin_h).json()
    s["max_brewing_minutes"] = 390  # 6h30
    upd = client.put("/api/ops-settings", headers=admin_h, json=s)
    assert upd.status_code == 200, upd.text
    assert upd.json()["max_brewing_minutes"] == 390

    s2 = client.get("/api/ops-settings", headers=admin_h).json()
    assert s2["max_brewing_minutes"] == 390

    # Trả lại mặc định để không ảnh hưởng các test khác trong cùng file (module-scope DB).
    s2["max_brewing_minutes"] = 480
    client.put("/api/ops-settings", headers=admin_h, json=s2)


def test_update_settings_rejects_non_positive_max_brewing_minutes(client, admin_h):
    s = client.get("/api/ops-settings", headers=admin_h).json()
    s["max_brewing_minutes"] = 0
    bad = client.put("/api/ops-settings", headers=admin_h, json=s)
    assert bad.status_code in (400, 409), bad.text
