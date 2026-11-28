"""Test tham số `days` (tuỳ chọn) của GET /api/quality/results — routers/quality.py::list_results.

Tab "Chất lượng" (VIEWS.quality) gọi KHÔNG lọc gì để dựng bảng "scope đang cần chú ý" — trước
đây kéo nguyên TOÀN BỘ QualityResult từng ghi từ trước tới giờ (sự cố thực tế 2026-11-28, khảo
sát hiệu năng toàn app: 832KB, 3,6 giây). `days` chỉ áp dụng khi KHÔNG lọc theo `scope_id` — mọi
nơi khác (tra kết quả của 1 bản ghi cụ thể) không bị ảnh hưởng."""

import os
import tempfile
from datetime import datetime, timedelta, timezone

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["MES_DATABASE_URL"] = f"sqlite:///{_TMP.name}"
os.environ["MES_DEV_HEADER_AUTH"] = "0"
os.environ["MES_RL_ENABLED"] = "0"
os.environ["MES_ADMIN_PASSWORD"] = "AdminTest123"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import seed as seed_mod
from app.routers import quality as quality_router


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


def test_days_excludes_old_results_but_scope_id_lookup_is_unaffected(client, admin_h, monkeypatch):
    lot_id = client.get("/api/lots", headers=admin_h).json()[0]["lot_id"]
    rec = client.post("/api/quality/results", headers=admin_h, json={
        "scope_type": "lot", "scope_id": lot_id, "parameter": "DAYSFILTER_PARAM01", "value": 5.0})
    assert rec.status_code == 201, rec.text

    # Khong loc gi -> van thay (vua ghi "hom nay" that).
    now_default = client.get("/api/quality/results?days=90", headers=admin_h).json()
    assert any(r["parameter"] == "DAYSFILTER_PARAM01" for r in now_default)

    # Gia lap "hien tai" lui xa ve tuong lai -> ban ghi vua tao roi vao qua khu xa, ngoai cua so 90 ngay.
    fake_now = datetime.now(timezone.utc) + timedelta(days=100)
    monkeypatch.setattr(quality_router, "utcnow", lambda: fake_now)

    windowed = client.get("/api/quality/results?days=90", headers=admin_h).json()
    assert not any(r["parameter"] == "DAYSFILTER_PARAM01" for r in windowed)

    # scope_id van tra duoc nhu thuong (khong bi anh huong boi days/"hien tai" gia lap).
    by_scope = client.get(f"/api/quality/results?scope_id={lot_id}&days=90", headers=admin_h).json()
    assert any(r["parameter"] == "DAYSFILTER_PARAM01" for r in by_scope)

    # Khong truyen days -> van tra het nhu truoc (hanh vi cu, khong loc theo thoi gian).
    no_days = client.get("/api/quality/results", headers=admin_h).json()
    assert any(r["parameter"] == "DAYSFILTER_PARAM01" for r in no_days)
