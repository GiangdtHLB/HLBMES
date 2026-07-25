"""Test Hold/Release theo công đoạn sản xuất (Nấu/Lên men/Lọc/Chiết) — tách khỏi Mẻ SX
(ISA-88)/Lô NVL vốn có sẵn. Xem services/quality.py::_STAGE_MODELS + routers/brewing.py
::_assert_unlocked (HOLD phải chặn sửa/xóa/chuyển bước giống hệt cơ chế khóa lô)."""

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
def vanhanh_h(client):
    return _login(client, "vanhanh", "123456")


@pytest.fixture(scope="module")
def kcs_h(client):
    return _login(client, "kcs", "123456")


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


def _a_brew_order(client, admin_h, order_code):
    r = client.post("/api/brewing/orders", headers=admin_h,
                    json={"order_code": order_code, "auto_from_bom": False, "planned_volume_hl": 100})
    assert r.status_code == 201, r.text
    return r.json()["brew_order_id"]


_batch_code_seq = iter(range(1, 10000))  # số mẻ duy nhất TOÀN NHÀ MÁY trong năm — không tái dùng "1"


def _setup_stage_chain(client, admin_h, vanhanh_h, suffix, line_id):
    """Tạo đủ 1 chuỗi Nấu -> Lên men -> Lọc -> Chiết, trả về dict id của từng công đoạn."""
    order_id = _a_brew_order(client, admin_h, f"LN-{suffix}")
    b = client.post("/api/brewing/brews", headers=vanhanh_h,
                    json={"brew_code": f"BR-{suffix}", "wort_type": "Dịch test", "volume_hl": 100,
                          "lm_code": f"LM-{suffix}", "tank_lm": f"T-{suffix}", "brew_order_id": order_id})
    assert b.status_code == 201, b.text
    brew_id = b.json()["brew_id"]
    bb = client.post(f"/api/brewing/brews/{brew_id}/batches", headers=vanhanh_h,
                     json={"batch_code": str(next(_batch_code_seq)), "line_id": line_id})
    assert bb.status_code == 201, bb.text
    batch_id = bb.json()["batch_id"]

    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment_id = next(f for f in ferments if f["lm_code"] == f"LM-{suffix}")["ferment_id"]
    approve_lm = client.post(f"/api/brewing/ferments/{ferment_id}/approve", headers=admin_h)
    assert approve_lm.status_code == 200, approve_lm.text

    fo = client.post("/api/brewing/filter-orders", headers=admin_h,
                     json={"order_code": f"LOC-{suffix}", "blend_mode": "khong_phoi",
                           "tank_ferment_ids": [ferment_id], "planned_volume_hl": 1000})
    assert fo.status_code == 201, fo.text
    f = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": f"FL-{suffix}", "beer_type": "Bia test",
                          "filter_order_id": fo.json()["filter_order_id"], "to_bbt": f"BBT-{suffix}"})
    assert f.status_code == 201, f.text
    filter_id = f.json()["filter_id"]

    # Chiết cần tank BBT nguồn đã lọc xong + KCS duyệt (xem available_bbt_tanks) mới tạo
    # được — finish + duyệt mẻ lọc trước, không ảnh hưởng ý nghĩa test filter hold vì
    # _assert_unlocked vẫn chạy TRƯỚC check "đã duyệt" trong approve_filter.
    tanks = client.get(f"/api/brewing/filters/{filter_id}/tanks", headers=admin_h).json()
    fin = client.post(f"/api/brewing/filters/{filter_id}/tanks/{tanks[0]['line_id']}/finish", headers=vanhanh_h,
                      json={"v_dich_hl": 90, "nuoc_bai_khi_hl": 10})
    assert fin.status_code == 200, fin.text
    _declare_pending(client, vanhanh_h, "loc", "filter", f"FL-{suffix}")
    approve_f = client.post(f"/api/brewing/filters/{filter_id}/approve", headers=admin_h)
    assert approve_f.status_code == 200, approve_f.text

    bt = client.post("/api/brewing/bottles", headers=vanhanh_h,
                     json={"bottle_code": f"CH-{suffix}", "beer_type": "Bia test", "from_bbt": f"BBT-{suffix}"})
    assert bt.status_code == 201, bt.text
    bottle_id = bt.json()["bottle_id"]

    return {"batch_id": batch_id, "brew_id": brew_id, "ferment_id": ferment_id,
            "filter_id": filter_id, "bottle_id": bottle_id}


def _declare_pending(client, headers, stage, scope_type, scope_id):
    status = client.get(f"/api/brewing/qc-status?stage={stage}&scope_type={scope_type}&scope_id={scope_id}",
                        headers=headers).json()
    for p in status["required"]:
        if p["code"] in status["pending"]:
            lsl = p["lsl"] if p["lsl"] is not None else 0
            usl = p["usl"] if p["usl"] is not None else lsl + 10
            r = client.post("/api/brewing/qc-results", headers=headers,
                            json={"stage": stage, "scope_type": scope_type, "scope_id": scope_id,
                                  "parameter": p["code"], "value": (lsl + usl) / 2,
                                  "lower_limit": lsl, "upper_limit": usl})
            assert r.status_code == 201, r.text


def _hold(client, headers, scope_type, scope_id, on_hold):
    return client.post("/api/quality/hold", headers=headers,
                       json={"scope_type": scope_type, "scope_id": scope_id, "on_hold": on_hold})


def test_hold_release_permissions(client, admin_h, vanhanh_h, kcs_h, brewhouse_line_id):
    ids = _setup_stage_chain(client, admin_h, vanhanh_h, "PERM", brewhouse_line_id)
    denied_hold = _hold(client, vanhanh_h, "ferment", ids["ferment_id"], True)
    assert denied_hold.status_code == 403, denied_hold.text

    ok_hold = _hold(client, kcs_h, "ferment", ids["ferment_id"], True)
    assert ok_hold.status_code == 200, ok_hold.text
    assert ok_hold.json()["quality_status"] == "on_hold"

    denied_release = _hold(client, vanhanh_h, "ferment", ids["ferment_id"], False)
    assert denied_release.status_code == 403, denied_release.text

    ok_release = _hold(client, kcs_h, "ferment", ids["ferment_id"], False)
    assert ok_release.status_code == 200, ok_release.text
    assert ok_release.json()["quality_status"] == "released"


def test_hold_brew_batch_blocks_finish(client, admin_h, vanhanh_h, brewhouse_line_id):
    ids = _setup_stage_chain(client, admin_h, vanhanh_h, "NAU", brewhouse_line_id)
    hold = _hold(client, admin_h, "brew_batch", ids["batch_id"], True)
    assert hold.status_code == 200, hold.text

    blocked = client.post(f"/api/brewing/brews/{ids['brew_id']}/batches/{ids['batch_id']}/finish",
                          headers=vanhanh_h, json={})
    assert blocked.status_code == 409, blocked.text
    assert "HOLD" in blocked.json()["detail"]

    release = _hold(client, admin_h, "brew_batch", ids["batch_id"], False)
    assert release.status_code == 200, release.text
    ok = client.post(f"/api/brewing/brews/{ids['brew_id']}/batches/{ids['batch_id']}/finish",
                     headers=vanhanh_h, json={})
    assert ok.status_code == 200, ok.text

    rows = client.get(f"/api/brewing/brews/{ids['brew_id']}/batches", headers=admin_h).json()
    row = next(r for r in rows if r["batch_id"] == ids["batch_id"])
    assert row["quality_status"] == "released"


def test_hold_ferment_blocks_approve(client, admin_h, vanhanh_h, brewhouse_line_id):
    ids = _setup_stage_chain(client, admin_h, vanhanh_h, "LM", brewhouse_line_id)
    hold = _hold(client, admin_h, "ferment", ids["ferment_id"], True)
    assert hold.status_code == 200, hold.text

    blocked = client.post(f"/api/brewing/ferments/{ids['ferment_id']}/approve", headers=admin_h)
    assert blocked.status_code == 409, blocked.text
    assert "HOLD" in blocked.json()["detail"]

    _hold(client, admin_h, "ferment", ids["ferment_id"], False)
    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    row = next(f for f in ferments if f["ferment_id"] == ids["ferment_id"])
    assert row["quality_status"] == "released"


def test_hold_filter_blocks_approve(client, admin_h, vanhanh_h, brewhouse_line_id):
    ids = _setup_stage_chain(client, admin_h, vanhanh_h, "LOC", brewhouse_line_id)
    hold = _hold(client, admin_h, "filter", ids["filter_id"], True)
    assert hold.status_code == 200, hold.text

    blocked = client.post(f"/api/brewing/filters/{ids['filter_id']}/approve", headers=admin_h)
    assert blocked.status_code == 409, blocked.text
    assert "HOLD" in blocked.json()["detail"]

    _hold(client, admin_h, "filter", ids["filter_id"], False)
    rows = client.get("/api/brewing/filters", headers=admin_h).json()
    row = next(r for r in rows if r["filter_id"] == ids["filter_id"])
    assert row["quality_status"] == "released"


def test_hold_bottle_blocks_finish(client, admin_h, vanhanh_h, brewhouse_line_id):
    ids = _setup_stage_chain(client, admin_h, vanhanh_h, "CHIET", brewhouse_line_id)
    hold = _hold(client, admin_h, "bottle", ids["bottle_id"], True)
    assert hold.status_code == 200, hold.text

    blocked = client.post(f"/api/brewing/bottles/{ids['bottle_id']}/finish", headers=vanhanh_h,
                          json={"v_cap_chiet_hl": 50})
    assert blocked.status_code == 409, blocked.text
    assert "HOLD" in blocked.json()["detail"]

    _hold(client, admin_h, "bottle", ids["bottle_id"], False)
    ok = client.post(f"/api/brewing/bottles/{ids['bottle_id']}/finish", headers=vanhanh_h,
                     json={"v_cap_chiet_hl": 50})
    assert ok.status_code == 200, ok.text


def test_hold_unknown_scope_not_found(client, admin_h):
    r = _hold(client, admin_h, "ferment", "does-not-exist", True)
    assert r.status_code == 404, r.text


def test_flat_brew_batches_endpoint_lists_quality_status(client, admin_h, vanhanh_h, brewhouse_line_id):
    ids = _setup_stage_chain(client, admin_h, vanhanh_h, "FLATLIST", brewhouse_line_id)
    rows = client.get("/api/brewing/brew-batches", headers=admin_h).json()
    row = next(r for r in rows if r["batch_id"] == ids["batch_id"])
    assert row["quality_status"] == "released"
    assert row["brew_code"] == "BR-FLATLIST"
