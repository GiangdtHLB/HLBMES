"""Test tạo NHIỀU mẻ 1 lần (POST /brewing/brews/{brew_id}/batches/bulk) — giải quyết đúng yêu
cầu "1 mã nấu có 12+ mẻ, không phải bấm từng mẻ một". Xem services/brew_order.py::
create_brew_batches_bulk."""

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
def brewhouse_line_id(client, admin_h):
    r = client.post("/api/lines", headers=admin_h,
                    json={"code": "BREW-BULK-01", "name": "Nhà nấu test bulk", "kind": "brewhouse"})
    assert r.status_code == 201, r.text
    return r.json()["line_id"]


@pytest.fixture(scope="module")
def non_brewhouse_line_id(client, admin_h):
    r = client.post("/api/lines", headers=admin_h,
                    json={"code": "LINE-BULK-01", "name": "Dây chuyền chiết test bulk", "kind": "line"})
    assert r.status_code == 201, r.text
    return r.json()["line_id"]


def _a_brew(client, admin_h, suffix):
    order = client.post("/api/brewing/orders", headers=admin_h,
                        json={"order_code": f"LN-BULK-{suffix}", "auto_from_bom": False, "planned_volume_hl": 100})
    assert order.status_code == 201, order.text
    b = client.post("/api/brewing/brews", headers=admin_h,
                    json={"brew_code": f"BR-BULK-{suffix}", "wort_type": "Dịch test",
                          "brew_order_id": order.json()["brew_order_id"]})
    assert b.status_code == 201, b.text
    return b.json()["brew_id"]


def test_bulk_create_generates_sequential_unique_codes(client, admin_h, brewhouse_line_id):
    brew_id = _a_brew(client, admin_h, "A")
    r = client.post(f"/api/brewing/brews/{brew_id}/batches/bulk", headers=admin_h,
                    json={"count": 12, "line_id": brewhouse_line_id, "started_at": "2026-01-10T08:00:00"})
    assert r.status_code == 201, r.text
    batches = r.json()
    assert len(batches) == 12
    codes = sorted(int(b["batch_code"]) for b in batches)
    assert codes == list(range(codes[0], codes[0] + 12)), "mã mẻ phải liên tiếp, không trùng"
    assert len({b["batch_code"] for b in batches}) == 12
    assert all(b["line_id"] == brewhouse_line_id for b in batches)

    rows = client.get(f"/api/brewing/brews/{brew_id}/batches", headers=admin_h).json()
    assert len(rows) == 12


def test_bulk_create_avoids_codes_used_by_other_brew_same_year(client, admin_h, brewhouse_line_id):
    """Số mẻ là dãy đếm CHUNG toàn nhà máy theo năm (không phải riêng từng mã nấu) — mẻ tạo
    bulk cho mã nấu B không được trùng mã đã dùng ở mã nấu A cùng năm."""
    brew_a = _a_brew(client, admin_h, "B1")
    single = client.post(f"/api/brewing/brews/{brew_a}/batches", headers=admin_h,
                         json={"batch_code": "999", "started_at": "2026-01-10T08:00:00", "line_id": brewhouse_line_id})
    assert single.status_code == 201, single.text

    brew_b = _a_brew(client, admin_h, "B2")
    r = client.post(f"/api/brewing/brews/{brew_b}/batches/bulk", headers=admin_h,
                    json={"count": 3, "line_id": brewhouse_line_id, "started_at": "2026-01-10T09:00:00"})
    assert r.status_code == 201, r.text
    codes = {int(b["batch_code"]) for b in r.json()}
    assert 999 not in codes
    assert min(codes) > 999


def test_bulk_create_rejects_non_brewhouse_line(client, admin_h, non_brewhouse_line_id):
    brew_id = _a_brew(client, admin_h, "C")
    r = client.post(f"/api/brewing/brews/{brew_id}/batches/bulk", headers=admin_h,
                    json={"count": 2, "line_id": non_brewhouse_line_id})
    assert r.status_code == 409, r.text


def test_bulk_create_rejects_zero_count(client, admin_h, brewhouse_line_id):
    brew_id = _a_brew(client, admin_h, "D")
    r = client.post(f"/api/brewing/brews/{brew_id}/batches/bulk", headers=admin_h,
                    json={"count": 0, "line_id": brewhouse_line_id})
    assert r.status_code == 422, r.text


def test_bulk_create_spaces_out_started_at_by_interval(client, admin_h, brewhouse_line_id):
    """Mẻ sau phải bắt đầu TRỄ HƠN mẻ trước theo interval_minutes — KHÔNG dùng chung 1 giờ bắt
    đầu cho cả loạt (tính năng tạo hàng loạt cũ đã bị bỏ đúng vì lý do này, xem comment ở
    frontend/app.js). Mặc định 90 phút, mirror chu kỳ nấu thật quan sát được."""
    brew_id = _a_brew(client, admin_h, "E")
    r = client.post(f"/api/brewing/brews/{brew_id}/batches/bulk", headers=admin_h,
                    json={"count": 4, "line_id": brewhouse_line_id, "started_at": "2026-01-10T04:00:00"})
    assert r.status_code == 201, r.text
    batches = sorted(r.json(), key=lambda b: b["seq"])
    started_ats = [b["started_at"] for b in batches]
    assert started_ats == [
        "2026-01-10T04:00:00+00:00", "2026-01-10T05:30:00+00:00",
        "2026-01-10T07:00:00+00:00", "2026-01-10T08:30:00+00:00",
    ]


def test_bulk_create_custom_interval(client, admin_h, brewhouse_line_id):
    brew_id = _a_brew(client, admin_h, "F")
    r = client.post(f"/api/brewing/brews/{brew_id}/batches/bulk", headers=admin_h,
                    json={"count": 3, "line_id": brewhouse_line_id, "started_at": "2026-01-10T04:00:00",
                          "interval_minutes": 0})
    assert r.status_code == 201, r.text
    started_ats = {b["started_at"] for b in r.json()}
    assert started_ats == {"2026-01-10T04:00:00+00:00"}, "interval_minutes=0 phải cho cùng 1 giờ nếu chủ động chọn"
