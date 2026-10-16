"""Test BatchTank.quality_status tự động đồng bộ theo CT Chính/CT Phụ (yêu cầu người dùng
2026-10-16): tank trước giờ KHÔNG có cơ chế nào — mặc định "released" ngay lúc tạo, không bao giờ
cập nhật lại, y hệt bug 2026-09-23 từng gặp ở Lọc/Thành phẩm trước sync_stage_quality_status.

Quy tắc đã xác nhận: chỉ cần MỘT TRONG HAI công đoạn (CT Chính HOẶC CT Phụ) còn thiếu chỉ tiêu
bắt buộc hoặc có FAIL là đủ để tank chuyển "on_hold" — logic OR, không cần cả 2 cùng lúc.

CỐ Ý KHÔNG chặn thao tác nào khi tank on_hold (yêu cầu người dùng: "onhold thì vẫn cho đi lọc") —
test cuối xác nhận tạo lô lọc từ tank đang on_hold vẫn thành công bình thường.

Xem services/qc_catalog.py::sync_tank_quality_status.
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


def _make_group_with_param(client, admin_h, suffix, stage, product_id, lsl=1, usl=10):
    """Trả về (code, link_id) — link_id PHẢI được xóa lại ở cuối test (xem `_cleanup_links`),
    vì mọi test trong file này dùng CHUNG đúng 1 product_id (từ cùng 1 công thức seed sẵn, xem
    _make_batch) — không xóa thì yêu cầu bắt buộc của test NÀY sẽ cộng dồn sang tank của test
    SAU, làm tank đó bị tính "on_hold" oan vì thiếu đúng mã chỉ tiêu của test trước (mirror cảnh
    báo docstring test_filter_lot_quality_status_qc_gate.py::mandatory_loc_param)."""
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
                       json={"stage": stage, "group_id": group_id, "product_id": product_id, "mandatory": True})
    assert link.status_code == 201, link.text
    return f"CT_{suffix}", link.json()["link_id"]


def _cleanup_links(client, admin_h, *link_ids):
    for link_id in link_ids:
        client.delete(f"/api/qc/stage-groups/{link_id}", headers=admin_h)


def _make_batch(client, admin_h):
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(x for x in vers if x["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                          "planned_qty": 1000, "allow_shortage": True})
    assert b.status_code == 201, b.text
    return b.json()["batch_id"], v["product_id"]


def _run_batch_to_completed(client, admin_h, batch_id):
    for target in ("ready", "running"):
        r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": target})
        assert r.status_code == 200, r.text
    aq = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": 1000})
    assert aq.status_code == 200, aq.text
    fin = client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={})
    assert fin.status_code == 200, fin.text
    r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "completed"})
    assert r.status_code == 200, r.text


def _make_tank(client, admin_h, suffix):
    batch_id, product_id = _make_batch(client, admin_h)
    _run_batch_to_completed(client, admin_h, batch_id)
    t = client.post("/api/batch-tanks", headers=admin_h,
                    json={"batch_ids": [batch_id], "tank_code": f"TANK-HOLDSYNC-{suffix}"})
    assert t.status_code == 201, t.text
    return t.json()["tank_id"], product_id


def _tank_quality_status(client, admin_h, tank_id):
    tanks = client.get("/api/batch-tanks?year=2026", headers=admin_h).json()
    items = tanks.get("items", tanks) if isinstance(tanks, dict) else tanks
    return next(t for t in items if t["tank_id"] == tank_id)["quality_status"]


def _record_sample(client, admin_h, tank_id, stage, parameter, value, lower=1, upper=10):
    r = client.post("/api/brewing/qc-samples", headers=admin_h, json={
        "stage": stage, "scope_type": "batch_tank", "scope_id": f"{tank_id}__{stage}",
        "results": [{"parameter": parameter, "value": value, "lower_limit": lower, "upper_limit": upper}]})
    assert r.status_code == 201, r.text
    return r.json()


def test_tank_on_hold_after_fail_then_released_after_corrected_pass(client, admin_h):
    tank_id, product_id = _make_tank(client, admin_h, "A")
    code, link_id = _make_group_with_param(client, admin_h, "HOLDSYNCA", "len_men_chinh", product_id)
    try:
        _record_sample(client, admin_h, tank_id, "len_men_chinh", code, value=99)   # ngoài [1,10] -> fail
        assert _tank_quality_status(client, admin_h, tank_id) == "on_hold"

        # "Lần lấy mẫu" thứ 2 cho ĐÚNG mã đó, lần này đạt — latest_results_by_param chỉ tính
        # giá trị MỚI NHẤT nên has_fail phải hết, tank tự release lại.
        _record_sample(client, admin_h, tank_id, "len_men_chinh", code, value=5)
        assert _tank_quality_status(client, admin_h, tank_id) == "released"
    finally:
        _cleanup_links(client, admin_h, link_id)


def test_tank_stays_on_hold_if_only_one_of_two_stages_clear(client, admin_h):
    """Logic OR: CT Chính đã đạt nhưng CT Phụ vẫn còn thiếu -> tank vẫn on_hold, không cần CẢ
    HAI cùng fail/thiếu mới hold."""
    tank_id, product_id = _make_tank(client, admin_h, "B")
    code_chinh, link_chinh = _make_group_with_param(client, admin_h, "HOLDSYNCB1", "len_men_chinh", product_id)
    code_phu, link_phu = _make_group_with_param(client, admin_h, "HOLDSYNCB2", "len_men_phu", product_id)
    try:
        _record_sample(client, admin_h, tank_id, "len_men_chinh", code_chinh, value=5)
        # CT Chính đã pass nhưng CT Phụ chưa nhập gì -> vẫn on_hold.
        assert _tank_quality_status(client, admin_h, tank_id) == "on_hold"

        _record_sample(client, admin_h, tank_id, "len_men_phu", code_phu, value=5)
        assert _tank_quality_status(client, admin_h, tank_id) == "released"
    finally:
        _cleanup_links(client, admin_h, link_chinh, link_phu)


def test_tank_on_hold_when_either_stage_has_fail(client, admin_h):
    tank_id, product_id = _make_tank(client, admin_h, "C")
    code, link_id = _make_group_with_param(client, admin_h, "HOLDSYNCC", "len_men_phu", product_id)
    try:
        _record_sample(client, admin_h, tank_id, "len_men_phu", code, value=99)   # ngoài [1,10] -> fail
        assert _tank_quality_status(client, admin_h, tank_id) == "on_hold"
    finally:
        _cleanup_links(client, admin_h, link_id)


def test_tank_on_hold_does_not_block_creating_filter_lot(client, admin_h):
    """CỐ Ý KHÔNG chặn — tank đang on_hold vẫn tạo lô lọc (đi lọc) bình thường, không có
    _assert_unlocked/_assert_not_on_hold nào tham chiếu quality_status của tank cả."""
    tank_id, product_id = _make_tank(client, admin_h, "D")
    code, link_id = _make_group_with_param(client, admin_h, "HOLDSYNCD", "len_men_chinh", product_id)
    try:
        _record_sample(client, admin_h, tank_id, "len_men_chinh", code, value=99)   # fail -> on_hold
        assert _tank_quality_status(client, admin_h, tank_id) == "on_hold"

        bbt = client.post("/api/lines", headers=admin_h,
                         json={"code": "BBT-HOLDSYNCD", "name": "BBT HOLDSYNCD", "kind": "tank_bbt"})
        assert bbt.status_code == 201, bbt.text
        draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
            "filter_lot_code": "FLOT-HOLDSYNCD", "to_bbt": bbt.json()["code"],
            "sources": [{"source_type": "tank", "source_tank_id": tank_id}],
            "category": "Bia lon"})
        assert draw.status_code == 201, draw.text   # không bị chặn dù tank đang on_hold
    finally:
        _cleanup_links(client, admin_h, link_id)
