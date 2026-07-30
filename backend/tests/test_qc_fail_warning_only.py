"""Chỉ tiêu Nấu/Lên men/Lọc/Chiết: giá trị FAIL (vượt giới hạn) chỉ CẢNH BÁO, không còn
chặn duyệt/khóa lô sang bước tiếp theo — chỉ còn chặn khi chỉ tiêu bắt buộc CHƯA khai báo
(pending). Xem qc_catalog.py::stage_qc_status (has_fail tách khỏi gate), brewing.py's
approve_ferment/approve_filter/approve_bottle, lot_lock.py::_stage_ok."""

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


def _make_group_with_param(client, admin_h, suffix):
    p = client.post("/api/qc/parameters", headers=admin_h,
                    json={"code": f"CT_{suffix}", "name": f"Chỉ tiêu {suffix}", "lsl": 1, "usl": 10})
    assert p.status_code == 201, p.text
    param_id = p.json()["param_id"]
    g = client.post("/api/qc/groups", headers=admin_h,
                    json={"code": f"GRP_{suffix}", "name": f"Nhóm {suffix}"})
    assert g.status_code == 201, g.text
    group_id = g.json()["group_id"]
    it = client.post(f"/api/qc/groups/{group_id}/items", headers=admin_h,
                     json={"param_id": param_id, "mandatory": True})
    assert it.status_code == 201, it.text
    return group_id, f"CT_{suffix}"


def _link_stage(client, admin_h, stage, group_id):
    """Gán nhóm CHUNG (không product/beer_type/finished_product scope) cho 1 stage — áp
    dụng cho MỌI scope_id của stage đó trong toàn CSDL test (dùng chung giữa các file test
    trong cùng 1 lần chạy pytest, xem services/qc_catalog.py::required_params_for_stage).
    Trả về link_id — caller PHẢI tự unlink cuối test (xem _unlink_all), tránh rò rỉ chỉ tiêu
    bắt buộc sang các file test khác chạy sau (đã từng gây fail chéo file khi viết test này)."""
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": stage, "group_id": group_id, "mandatory": True})
    assert link.status_code == 201, link.text
    return link.json()["link_id"]


def _unlink_all(client, admin_h, link_ids):
    for lid in link_ids:
        client.delete(f"/api/qc/stage-groups/{lid}", headers=admin_h)


def _declare_fail(client, headers, stage, scope_type, scope_id, code):
    """Khai 1 giá trị VƯỢT giới hạn trên (usl=10) cho tham số bắt buộc — mô phỏng FAIL."""
    r = client.post("/api/brewing/qc-results", headers=headers,
                    json={"stage": stage, "scope_type": scope_type, "scope_id": scope_id,
                          "parameter": code, "value": 999, "lower_limit": 1, "upper_limit": 10})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "fail"


def test_fail_warns_but_does_not_block_full_chain(client, admin_h, vanhanh_h, brewhouse_line_id):
    suffix = "WARNONLY"
    nau_group, nau_code = _make_group_with_param(client, admin_h, f"{suffix}_NAU")
    chinh_group, chinh_code = _make_group_with_param(client, admin_h, f"{suffix}_CHINH")
    phu_group, phu_code = _make_group_with_param(client, admin_h, f"{suffix}_PHU")
    loc_group, loc_code = _make_group_with_param(client, admin_h, f"{suffix}_LOC")
    tp_group, tp_code = _make_group_with_param(client, admin_h, f"{suffix}_TP")
    link_ids = [
        _link_stage(client, admin_h, "nau", nau_group),
        _link_stage(client, admin_h, "len_men_chinh", chinh_group),
        _link_stage(client, admin_h, "len_men_phu", phu_group),
        _link_stage(client, admin_h, "loc", loc_group),
        _link_stage(client, admin_h, "thanh_pham", tp_group),
    ]
    try:
        order = client.post("/api/brewing/orders", headers=admin_h,
                            json={"order_code": f"LN-{suffix}", "auto_from_bom": False, "planned_volume_hl": 100})
        assert order.status_code == 201, order.text
        brew_order_id = order.json()["brew_order_id"]

        brew = client.post("/api/brewing/brews", headers=vanhanh_h,
                           json={"brew_code": f"BR-{suffix}", "wort_type": "Dịch test", "volume_hl": 100,
                                 "lm_code": f"LM-{suffix}", "tank_lm": f"T-{suffix}",
                                 "brew_order_id": brew_order_id})
        assert brew.status_code == 201, brew.text
        brew_id = brew.json()["brew_id"]

        batch = client.post(f"/api/brewing/brews/{brew_id}/batches", headers=vanhanh_h,
                            json={"batch_code": "601", "line_id": brewhouse_line_id})
        assert batch.status_code == 201, batch.text
        batch_id = batch.json()["batch_id"]
        fin_batch = client.post(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/finish", headers=vanhanh_h)
        assert fin_batch.status_code == 200, fin_batch.text

        # FAIL ở Nấu — vẫn cho Kết thúc mẻ (không có gate) và vẫn khóa được mã nấu sau này.
        _declare_fail(client, vanhanh_h, "nau", "brew_batch", batch_id, nau_code)

        ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
        ferment = next(f for f in ferments if f["lm_code"] == f"LM-{suffix}")
        ferment_id = ferment["ferment_id"]

        # FAIL ở lên men phụ — Duyệt LM vẫn phải THÀNH CÔNG (chỉ cảnh báo qua qc_has_fail).
        _declare_fail(client, vanhanh_h, "len_men_phu", "ferment", f"LM-{suffix}__len_men_phu", phu_code)
        approve_ferment = client.post(f"/api/brewing/ferments/{ferment_id}/approve", headers=admin_h)
        assert approve_ferment.status_code == 200, approve_ferment.text
        assert approve_ferment.json()["qc_approved"] is True
        assert approve_ferment.json()["qc_has_fail"] is True

        # FAIL ở Nấu vẫn phải khóa được mã nấu — cảnh báo, không chặn.
        lock_brew = client.post(f"/api/brewing/brews/{brew_id}/lock-lot", headers=admin_h)
        assert lock_brew.status_code == 200, lock_brew.text

        # FAIL ở lên men chính vẫn phải khóa được lô LM.
        _declare_fail(client, vanhanh_h, "len_men_chinh", "ferment", f"LM-{suffix}__len_men_chinh", chinh_code)
        lock_ferment = client.post(f"/api/brewing/ferments/{ferment_id}/lock-lot", headers=admin_h)
        assert lock_ferment.status_code == 200, lock_ferment.text

        master = client.post("/api/brewing/filter-master-orders", headers=admin_h,
                             json={"order_code": f"LOC-{suffix}",
                                   "children": [{"blend_mode": "khong_phoi",
                                                "tanks": [{"tank_type": "cct", "ferment_id": ferment_id,
                                                          "planned_v_dich_hl": 100}]}]})
        assert master.status_code == 201, master.text
        master_detail = client.get(f"/api/brewing/filter-master-orders/{master.json()['filter_master_order_id']}",
                                   headers=admin_h).json()
        filter_order_id = master_detail["children"][0]["filter_order_id"]

        filt = client.post("/api/brewing/filters", headers=vanhanh_h,
                           json={"filter_code": f"FL-{suffix}", "filter_order_id": filter_order_id,
                                 "to_bbt": f"BBT-{suffix}"})
        assert filt.status_code == 201, filt.text
        filter_id = filt.json()["filter_id"]
        tanks = client.get(f"/api/brewing/filters/{filter_id}/tanks", headers=admin_h).json()
        fin_filt = client.post(f"/api/brewing/filters/{filter_id}/tanks/{tanks[0]['line_id']}/finish",
                               headers=vanhanh_h, json={"v_dich_hl": 100, "nuoc_bai_khi_hl": 0,
                                                         "batch_number": f"B-{suffix}", "order_number": f"O-{suffix}", "batch_seq_no": "1"})
        assert fin_filt.status_code == 200, fin_filt.text

        # FAIL ở lọc — Duyệt KCS lọc vẫn phải THÀNH CÔNG.
        _declare_fail(client, vanhanh_h, "loc", "filter", f"FL-{suffix}", loc_code)
        approve_filt = client.post(f"/api/brewing/filters/{filter_id}/approve", headers=admin_h)
        assert approve_filt.status_code == 200, approve_filt.text
        assert approve_filt.json()["qc_has_fail"] is True

        bottle = client.post("/api/brewing/bottles", headers=vanhanh_h,
                             json={"bottle_code": f"CH-{suffix}", "from_bbt": f"BBT-{suffix}"})
        assert bottle.status_code == 201, bottle.text
        bottle_id = bottle.json()["bottle_id"]
        fin_bottle = client.post(f"/api/brewing/bottles/{bottle_id}/finish", headers=vanhanh_h,
                                 json={"v_cap_chiet_hl": 100, "ca1": 100, "ca2": 0, "ca3": 0})
        assert fin_bottle.status_code == 200, fin_bottle.text

        # FAIL ở thành phẩm — Duyệt chiết vẫn phải THÀNH CÔNG (vẫn nhập kho thành phẩm).
        _declare_fail(client, vanhanh_h, "thanh_pham", "bottle", f"CH-{suffix}__thanh_pham", tp_code)
        approve_bottle = client.post(f"/api/brewing/bottles/{bottle_id}/approve", headers=admin_h)
        assert approve_bottle.status_code == 200, approve_bottle.text
        assert approve_bottle.json()["qc_has_fail"] is True
    finally:
        _unlink_all(client, admin_h, link_ids)


def test_pending_declaration_still_blocks_approve(client, admin_h, vanhanh_h):
    """Chưa khai báo (pending) — khác với FAIL — vẫn phải tiếp tục chặn duyệt như cũ."""
    group_id, code = _make_group_with_param(client, admin_h, "PENDBLOCK")
    link_id = _link_stage(client, admin_h, "len_men_phu", group_id)
    try:
        order = client.post("/api/brewing/orders", headers=admin_h,
                            json={"order_code": "LN-PENDBLOCK", "auto_from_bom": False, "planned_volume_hl": 100})
        assert order.status_code == 201, order.text
        brew = client.post("/api/brewing/brews", headers=vanhanh_h,
                           json={"brew_code": "BR-PENDBLOCK", "wort_type": "Dịch test", "volume_hl": 100,
                                 "lm_code": "LM-PENDBLOCK", "tank_lm": "T-PENDBLOCK",
                                 "brew_order_id": order.json()["brew_order_id"]})
        assert brew.status_code == 201, brew.text

        ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
        ferment = next(f for f in ferments if f["lm_code"] == "LM-PENDBLOCK")
        blocked = client.post(f"/api/brewing/ferments/{ferment['ferment_id']}/approve", headers=admin_h)
        assert blocked.status_code == 409, blocked.text
        assert "thiếu" in blocked.json()["detail"]
    finally:
        _unlink_all(client, admin_h, [link_id])
