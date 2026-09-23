"""Bug thực tế 2026-09-23: "lô lọc chưa nhập chỉ tiêu chất lượng mà đã release rồi" — Batch-
FilterLot/BatchPackLot.quality_status trước đây mặc định "released" ngay lúc tạo và KHÔNG BAO
GIỜ được cập nhật lại khi khai/xóa "Chỉ tiêu Lọc"/"Chỉ tiêu Chiết" (record_stage_result chỉ tự
release cho scope_type="batch", bỏ sót "loc"/"thanh_pham"; missing_mandatory_params cũng không
biết tính cho 2 scope này). Xem services/qc_catalog.py::sync_stage_quality_status/
_filter_pack_stage_context, services/batch_pipeline.py (3 điểm tạo BatchFilterLot/BatchPackLot).
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
def mandatory_loc_param(client, admin_h):
    """1 CHỈ chỉ tiêu bắt buộc, gán vào stage "loc" áp dụng cho MỌI loại bia (beer_type_id để
    trống) — tạo 1 LẦN DUY NHẤT cho cả module (áp dụng universal nên tạo nhiều bản sẽ CỘNG DỒN
    yêu cầu lên mọi lô lọc test sau, làm lô lọc ở test sau bị "on_hold" oan vì thiếu param của
    test trước — mọi test trong file này dùng CHUNG đúng 1 yêu cầu này)."""
    p = client.post("/api/qc/parameters", headers=admin_h,
                    json={"code": "CTLOC_QCGATE", "name": "Chỉ tiêu Lọc QCGATE", "lsl": 1, "usl": 10})
    assert p.status_code == 201, p.text
    param_id = p.json()["param_id"]
    g = client.post("/api/qc/groups", headers=admin_h,
                    json={"code": "GRPLOC_QCGATE", "name": "Nhóm Lọc QCGATE"})
    assert g.status_code == 201, g.text
    group_id = g.json()["group_id"]
    it = client.post(f"/api/qc/groups/{group_id}/items", headers=admin_h,
                     json={"param_id": param_id, "mandatory": True})
    assert it.status_code == 201, it.text
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": "loc", "group_id": group_id, "mandatory": True})
    assert link.status_code == 201, link.text
    return "CTLOC_QCGATE"


def _build_filter_lot(client, admin_h, suffix):
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
                       json={"batch_ids": [batch_id], "tank_code": f"TANK-QCGATE-{suffix}"})
    assert tank.status_code == 201, tank.text
    tank_id = tank.json()["tank_id"]
    bbt = client.post("/api/lines", headers=admin_h,
                      json={"code": f"BBT-QCGATE-{suffix}", "name": f"BBT {suffix}", "kind": "tank_bbt"})
    assert bbt.status_code == 201, bbt.text
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": f"FLOT-QCGATE-{suffix}", "to_bbt": bbt.json()["code"],
        "sources": [{"source_type": "tank", "source_tank_id": tank_id}]})
    assert draw.status_code == 201, draw.text
    return draw.json()["filter_lot_id"]


def test_new_filter_lot_starts_on_hold_when_mandatory_qc_param_exists(client, admin_h, mandatory_loc_param):
    """Trước khi sửa: lô lọc mới tạo, CHƯA khai chỉ tiêu nào, vẫn hiện "released" — đúng bug đã
    báo cáo (ảnh chụp lô T9.1339). Sau khi sửa: phải là "on_hold" ngay từ lúc tạo."""
    filter_lot_id = _build_filter_lot(client, admin_h, "NEW1")
    fl = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()
    assert fl["quality_status"] == "on_hold"


def test_filter_lot_releases_after_mandatory_param_recorded_and_holds_again_after_delete(client, admin_h, mandatory_loc_param):
    filter_lot_id = _build_filter_lot(client, admin_h, "REC1")
    fl = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()
    assert fl["quality_status"] == "on_hold"

    res = client.post("/api/brewing/qc-results", headers=admin_h, json={
        "stage": "loc", "scope_type": "batch_filter_lot", "scope_id": filter_lot_id,
        "parameter": mandatory_loc_param, "value": 5, "lower_limit": 1, "upper_limit": 10})
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "pass"
    result_id = res.json()["result_id"]

    fl2 = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()
    assert fl2["quality_status"] == "released"

    delr = client.delete(f"/api/brewing/qc-results/{result_id}", headers=admin_h)
    assert delr.status_code == 204, delr.text

    fl3 = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()
    assert fl3["quality_status"] == "on_hold"


def test_filter_lot_qc_fail_holds_status(client, admin_h, mandatory_loc_param):
    filter_lot_id = _build_filter_lot(client, admin_h, "FAIL1")

    res = client.post("/api/brewing/qc-results", headers=admin_h, json={
        "stage": "loc", "scope_type": "batch_filter_lot", "scope_id": filter_lot_id,
        "parameter": mandatory_loc_param, "value": 99, "lower_limit": 1, "upper_limit": 10})   # ngoài [1,10] -> fail
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "fail"

    fl = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()
    assert fl["quality_status"] == "on_hold"
