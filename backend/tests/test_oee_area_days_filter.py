"""GET /oee lọc theo area (khu vực dây chuyền, VD "chiet") + days (số ngày gần nhất) — yêu
cầu người dùng 2026-09-20: "OEE lấy theo dây chuyền chiết, chỉ tính 5 ngày gần nhất, tránh
hiển thị quá nhiều". Xem routers/performance.py::list_oee."""

import os
import tempfile
from datetime import timedelta

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


def _make_line(client, admin_h, code, area):
    r = client.post("/api/lines", headers=admin_h,
                    json={"code": code, "name": f"Line {code}", "kind": "line", "area": area})
    assert r.status_code == 201, r.text
    return code


def _make_oee(client, admin_h, line, shift_date):
    r = client.post("/api/oee", headers=admin_h,
                    json={"line": line, "shift": "A", "shift_date": shift_date.isoformat(),
                         "planned_time_min": 480, "downtime_min": 0, "ideal_rate_per_min": 10,
                         "total_count": 100, "good_count": 100})
    assert r.status_code == 201, r.text


def test_oee_area_filter_excludes_other_areas(client, admin_h):
    chiet_line = _make_line(client, admin_h, "LINE-AREA-CHIET", "chiet")
    nau_line = _make_line(client, admin_h, "LINE-AREA-NAU", "nau")
    _make_oee(client, admin_h, chiet_line, utcnow())
    _make_oee(client, admin_h, nau_line, utcnow())

    r = client.get("/api/oee", headers=admin_h, params={"area": "chiet"})
    assert r.status_code == 200, r.text
    lines = {row["line"] for row in r.json()}
    assert chiet_line in lines
    assert nau_line not in lines


def test_oee_days_filter_excludes_old_records(client, admin_h):
    line = _make_line(client, admin_h, "LINE-DAYS-01", "chiet")
    _make_oee(client, admin_h, line, utcnow())
    _make_oee(client, admin_h, line, utcnow() - timedelta(days=10))

    r = client.get("/api/oee", headers=admin_h, params={"line": line, "days": 5})
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["shift_date"]


def test_oee_area_and_days_combine(client, admin_h):
    line = _make_line(client, admin_h, "LINE-DAYS-02", "chiet")
    other_area_line = _make_line(client, admin_h, "LINE-DAYS-03", "nau")
    _make_oee(client, admin_h, line, utcnow())
    _make_oee(client, admin_h, other_area_line, utcnow())
    _make_oee(client, admin_h, line, utcnow() - timedelta(days=10))

    r = client.get("/api/oee", headers=admin_h, params={"area": "chiet", "days": 5})
    assert r.status_code == 200, r.text
    lines = [row["line"] for row in r.json()]
    assert lines.count(line) == 1
    assert other_area_line not in lines
