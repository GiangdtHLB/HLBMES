"""OEE cho khung giờ bất kỳ (blueprint "OEE khung giờ bất kỳ" 2026-09-20) — 3 luồng sự kiện
thô có mốc thời gian (downtime_event đã có, OeeCountEvent/OeeRejectEvent mới) lọc theo
[t1, t2] bất kỳ, KHÔNG suy phế phẩm từ (Tổng − Tốt). Xem services/oee_window.py."""

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
    # "kcs" role="qa" — không phải operator/supervisor/engineer — đúng đối tượng cần bị chặn
    # khỏi ghi count/reject event.
    return _login(client, "kcs", "123456")


def _make_line(client, admin_h, code, rate=600.0):
    r = client.post("/api/lines", headers=admin_h,
                    json={"code": code, "name": f"Line test {code}", "kind": "line",
                         "ideal_rate_per_min": rate})
    assert r.status_code == 201, r.text
    return code


def _make_reason(client, admin_h, line_code, category="breakdown"):
    r = client.post("/api/downtime/reason-catalog", headers=admin_h,
                    json={"line_code": line_code, "category": category, "sub_code": "test_reason",
                         "sub_label": "Lý do test", "target_pct": 0.0})
    assert r.status_code == 201, r.text
    return r.json()["reason_id"]


def _iso(dt):
    return dt.isoformat()


def test_oee_window_computes_from_independent_event_streams(client, admin_h):
    """Khung 60 phút: 10' dừng máy (start_at/end_at chính xác) -> run_time 50'. Good=200,
    reject=20 (nhập riêng, KHÔNG suy từ tổng) -> total=220.
    A = 50/60 = 0.8333, P = 220/(50*ideal_rate), Q = 200/220."""
    line = _make_line(client, admin_h, "LINE-WIN-01", rate=5.0)
    reason_id = _make_reason(client, admin_h, line)

    t1 = datetime(2026, 9, 1, 6, 0, tzinfo=timezone.utc)
    t2 = t1 + timedelta(minutes=60)
    dt_start = t1 + timedelta(minutes=20)
    dt_end = dt_start + timedelta(minutes=10)

    dt = client.post("/api/downtime", headers=admin_h,
                     json={"line": line, "reason_catalog_id": reason_id,
                          "from_time": _iso(dt_start), "to_time": _iso(dt_end)})
    assert dt.status_code == 201, dt.text

    good = client.post("/api/downtime/count-events", headers=admin_h,
                       json={"line": line, "ts": _iso(t1 + timedelta(minutes=5)), "qty": 200})
    assert good.status_code == 201, good.text
    reject = client.post("/api/downtime/reject-events", headers=admin_h,
                         json={"line": line, "ts": _iso(t1 + timedelta(minutes=6)),
                              "qty": 20, "reason": "Lỗi dán nhãn"})
    assert reject.status_code == 201, reject.text

    r = client.get("/api/downtime/oee-window", headers=admin_h,
                   params={"line": line, "t1": _iso(t1), "t2": _iso(t2)})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["window_min"] == 60.0
    assert d["downtime_min"] == 10.0
    assert d["run_time_min"] == 50.0
    assert d["good"] == 200
    assert d["reject"] == 20
    assert d["total"] == 220
    assert abs(d["availability"] - 50 / 60) < 1e-4
    assert abs(d["quality"] - 200 / 220) < 1e-4
    expected_perf = min(220 / (50 * 5.0), 1.0)
    assert abs(d["performance"] - expected_perf) < 1e-4
    expected_oee = (50 / 60) * expected_perf * (200 / 220)
    assert abs(d["oee"] - expected_oee) < 1e-4


def test_oee_window_events_outside_window_excluded(client, admin_h):
    line = _make_line(client, admin_h, "LINE-WIN-02", rate=10.0)
    t1 = datetime(2026, 9, 2, 6, 0, tzinfo=timezone.utc)
    t2 = t1 + timedelta(minutes=30)

    # 1 sự kiện TRONG khung, 1 sự kiện TRƯỚC khung -> chỉ cái trong khung được tính.
    client.post("/api/downtime/count-events", headers=admin_h,
               json={"line": line, "ts": _iso(t1 + timedelta(minutes=10)), "qty": 50})
    client.post("/api/downtime/count-events", headers=admin_h,
               json={"line": line, "ts": _iso(t1 - timedelta(minutes=5)), "qty": 999})

    r = client.get("/api/downtime/oee-window", headers=admin_h,
                   params={"line": line, "t1": _iso(t1), "t2": _iso(t2)})
    assert r.status_code == 200, r.text
    assert r.json()["good"] == 50


def test_oee_window_includes_event_exactly_at_t2_boundary(client, admin_h):
    """input datetime-local (frontend) chỉ chính xác tới phút — ghi sự kiện rồi xem OEE khung
    kết thúc = bây giờ trong cùng 1 phút rất dễ cho ts trùng khớp đúng t2. Biên t2 phải
    INCLUSIVE, không loại nhầm sự kiện vừa ghi ra khỏi khung."""
    line = _make_line(client, admin_h, "LINE-WIN-06")
    t1 = datetime(2026, 9, 4, 6, 0, tzinfo=timezone.utc)
    t2 = t1 + timedelta(minutes=30)
    client.post("/api/downtime/count-events", headers=admin_h,
               json={"line": line, "ts": _iso(t2), "qty": 77})  # ts đúng bằng t2

    r = client.get("/api/downtime/oee-window", headers=admin_h,
                   params={"line": line, "t1": _iso(t1), "t2": _iso(t2)})
    assert r.status_code == 200, r.text
    assert r.json()["good"] == 77


def test_oee_window_rejects_invalid_range(client, admin_h):
    line = _make_line(client, admin_h, "LINE-WIN-03")
    t1 = datetime(2026, 9, 3, 6, 0, tzinfo=timezone.utc)
    t2 = t1 - timedelta(minutes=10)  # t2 trước t1 -> không hợp lệ
    r = client.get("/api/downtime/oee-window", headers=admin_h,
                   params={"line": line, "t1": _iso(t1), "t2": _iso(t2)})
    assert r.status_code == 409, r.text


def test_count_and_reject_events_reject_negative_qty(client, admin_h):
    line = _make_line(client, admin_h, "LINE-WIN-04")
    bad_good = client.post("/api/downtime/count-events", headers=admin_h,
                           json={"line": line, "qty": -5})
    assert bad_good.status_code == 409, bad_good.text
    bad_reject = client.post("/api/downtime/reject-events", headers=admin_h,
                             json={"line": line, "qty": -1})
    assert bad_reject.status_code == 409, bad_reject.text


def test_count_event_requires_operator_role(client, admin_h, kcs_h):
    line = _make_line(client, admin_h, "LINE-WIN-05")
    forbidden = client.post("/api/downtime/count-events", headers=kcs_h,
                            json={"line": line, "qty": 10})
    assert forbidden.status_code == 403, forbidden.text
