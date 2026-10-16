"""Bug thực tế 2026-10-15 (lô lọc 1495): _assert_releasable trước đây chỉ cần CÓ 1 deviation bất
kỳ đã ĐÓNG cho cả phạm vi (scope_type/scope_id) là đủ để Release — dù deviation đó chỉ liệt kê 1
trong nhiều mã chỉ tiêu đang FAIL, các mã FAIL còn lại chưa từng được mở deviation vẫn release
được theo. Sửa lại: release chỉ được phép khi MỖI mã chỉ tiêu đang FAIL đều được ít nhất 1
deviation ĐÃ ĐÓNG liệt kê tới (Deviation.parameter, nối bằng dấu phẩy).
Xem services/quality.py::_assert_releasable.
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


def _make_group_with_param(client, admin_h, suffix, beer_type_id, lsl=1, usl=10):
    """Gán theo ĐÚNG 1 beer_type_id riêng của từng test (không để trống/universal) — tránh cộng
    dồn yêu cầu bắt buộc sang lô lọc của test KHÁC (mirror cảnh báo docstring
    test_filter_lot_quality_status_qc_gate.py::mandatory_loc_param)."""
    p = client.post("/api/qc/parameters", headers=admin_h,
                    json={"code": f"CT_{suffix}", "name": f"Chỉ tiêu {suffix}", "lsl": lsl, "usl": usl})
    assert p.status_code == 201, p.text
    param_id = p.json()["param_id"]
    g = client.post("/api/qc/groups", headers=admin_h,
                    json={"code": f"GRP_{suffix}", "name": f"Nhóm {suffix}"})
    assert g.status_code == 201, g.text
    group_id = g.json()["group_id"]
    it = client.post(f"/api/qc/groups/{group_id}/items", headers=admin_h,
                     json={"param_id": param_id, "mandatory": True})
    assert it.status_code == 201, it.text
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": "loc", "group_id": group_id, "beer_type_id": beer_type_id, "mandatory": True})
    assert link.status_code == 201, link.text
    return f"CT_{suffix}"


def _make_beer_type(client, admin_h, suffix):
    r = client.post("/api/beer-types", headers=admin_h,
                    json={"code": f"BT_{suffix}", "name": f"Loại bia {suffix}"})
    assert r.status_code == 201, r.text
    return r.json()["beer_type_id"]


def _build_filter_lot(client, admin_h, suffix, beer_type_id):
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(x for x in vers if x["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                          "planned_qty": 1000, "allow_shortage": True})
    assert b.status_code == 201, b.text
    batch_id = b.json()["batch_id"]
    for target in ("ready", "running"):
        r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": target})
        assert r.status_code == 200, r.text
    aq = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": 1000})
    assert aq.status_code == 200, aq.text
    fin = client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={})
    assert fin.status_code == 200, fin.text
    r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "completed"})
    assert r.status_code == 200, r.text
    tank = client.post("/api/batch-tanks", headers=admin_h,
                       json={"batch_ids": [batch_id], "tank_code": f"TANK-RELCOV-{suffix}"})
    assert tank.status_code == 201, tank.text
    tank_id = tank.json()["tank_id"]
    bbt = client.post("/api/lines", headers=admin_h,
                      json={"code": f"BBT-RELCOV-{suffix}", "name": f"BBT {suffix}", "kind": "tank_bbt"})
    assert bbt.status_code == 201, bbt.text
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": f"FLOT-RELCOV-{suffix}", "to_bbt": bbt.json()["code"],
        "sources": [{"source_type": "tank", "source_tank_id": tank_id}],
        "category": "Bia lon", "beer_type_id": beer_type_id})
    assert draw.status_code == 201, draw.text
    return draw.json()["filter_lot_id"]


def _record_fail(client, admin_h, filter_lot_id, code):
    r = client.post("/api/brewing/qc-results", headers=admin_h, json={
        "stage": "loc", "scope_type": "batch_filter_lot", "scope_id": filter_lot_id,
        "parameter": code, "value": 99, "lower_limit": 1, "upper_limit": 10})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "fail"


def _open_deviation(client, admin_h, filter_lot_id, parameter_codes):
    r = client.post("/api/quality/deviations", headers=admin_h, json={
        "scope_type": "batch_filter_lot", "scope_id": filter_lot_id,
        "severity": "minor", "reason": "Test", "parameter": ",".join(parameter_codes)})
    assert r.status_code == 201, r.text
    return r.json()["deviation_id"]


def _close_deviation_minor(client, kcs_h, dev_id):
    for target, extra in [("triage", None), ("investigation", {"investigation": "x"}),
                          ("disposition", {"disposition": "x"}), ("approval", None)]:
        payload = {"target": target, **(extra or {})}
        r = client.post(f"/api/quality/deviations/{dev_id}/transition", headers=kcs_h, json=payload)
        assert r.status_code == 200, r.text
    r = client.post(f"/api/quality/deviations/{dev_id}/transition", headers=kcs_h,
                    json={"target": "closed", "close_note": "note"})
    assert r.status_code == 200, r.text


def _release(client, kcs_h, filter_lot_id):
    return client.post("/api/quality/hold", headers=kcs_h, json={
        "scope_type": "batch_filter_lot", "scope_id": filter_lot_id, "on_hold": False, "reason": "Test release"})


def test_release_blocked_when_only_some_failing_params_covered_by_closed_deviation(client, admin_h, kcs_h):
    beer_type_id = _make_beer_type(client, admin_h, "RELCOV1")
    code_a = _make_group_with_param(client, admin_h, "RELCOVA", beer_type_id)
    code_b = _make_group_with_param(client, admin_h, "RELCOVB", beer_type_id)
    filter_lot_id = _build_filter_lot(client, admin_h, "RELCOV1", beer_type_id)
    _record_fail(client, admin_h, filter_lot_id, code_a)
    _record_fail(client, admin_h, filter_lot_id, code_b)

    fl = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()
    assert fl["quality_status"] == "on_hold"

    # Mở + đóng deviation CHỈ cho code_a, bỏ qua code_b.
    dev_id = _open_deviation(client, admin_h, filter_lot_id, [code_a])
    _close_deviation_minor(client, kcs_h, dev_id)

    r = _release(client, kcs_h, filter_lot_id)
    assert r.status_code == 409, r.text
    assert code_b in r.json()["detail"]
    assert code_a not in r.json()["detail"]   # code_a đã được cover, không còn bị liệt là thiếu


def test_release_succeeds_once_all_failing_params_covered_by_closed_deviations(client, admin_h, kcs_h):
    beer_type_id = _make_beer_type(client, admin_h, "RELCOV2")
    code_a = _make_group_with_param(client, admin_h, "RELCOVC", beer_type_id)
    code_b = _make_group_with_param(client, admin_h, "RELCOVD", beer_type_id)
    filter_lot_id = _build_filter_lot(client, admin_h, "RELCOV2", beer_type_id)
    _record_fail(client, admin_h, filter_lot_id, code_a)
    _record_fail(client, admin_h, filter_lot_id, code_b)

    # Mở 1 deviation DUY NHẤT nhưng liệt kê CẢ 2 mã (giống tick cả 2 checkbox trên UI).
    dev_id = _open_deviation(client, admin_h, filter_lot_id, [code_a, code_b])
    _close_deviation_minor(client, kcs_h, dev_id)

    r = _release(client, kcs_h, filter_lot_id)
    assert r.status_code == 200, r.text
    assert r.json()["quality_status"] == "released"


def test_release_blocked_while_any_deviation_still_open(client, admin_h, kcs_h):
    beer_type_id = _make_beer_type(client, admin_h, "RELCOV3")
    code_a = _make_group_with_param(client, admin_h, "RELCOVE", beer_type_id)
    filter_lot_id = _build_filter_lot(client, admin_h, "RELCOV3", beer_type_id)
    _record_fail(client, admin_h, filter_lot_id, code_a)

    dev_id = _open_deviation(client, admin_h, filter_lot_id, [code_a])
    # Chưa đóng — vẫn ở trạng thái "open".
    r = _release(client, kcs_h, filter_lot_id)
    assert r.status_code == 409, r.text
    assert "đang xử lý dở" in r.json()["detail"]
