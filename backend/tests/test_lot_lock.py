"""Test tính năng "Khóa lô" theo TỪNG CÔNG ĐOẠN độc lập: Nấu → Lên men → Lọc → Chiết. KCS
khóa xuôi theo thứ tự (không khóa được 1 công đoạn nếu công đoạn nguồn chưa khóa); chỉ admin
mở khóa được, và phải mở NGƯỢC thứ tự (Chiết → Lọc → Lên men → Nấu). Lệnh nấu (BrewOrder) /
Lệnh lọc lớn+nhỏ (FilterMasterOrder/FilterOrder) không có nút riêng — tự suy ra trạng thái
khóa từ TẤT CẢ con. Xem services/lot_lock.py, routers/brewing.py::_assert_unlocked."""

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


def _build_full_chain(client, admin_h, vanhanh_h, suffix, line_id):
    """Dựng 1 chuỗi đầy đủ Lệnh nấu -> mã nấu -> mẻ (finish+đủ chỉ tiêu) -> lô LM (duyệt) ->
    Lệnh lọc -> mẻ lọc (finish+duyệt) -> mẻ chiết (finish+duyệt) — mọi điều kiện "tự hoàn
    thành" đã đủ cho TỪNG công đoạn, nhưng CHƯA khóa gì cả. Trả về dict id."""
    order = client.post("/api/brewing/orders", headers=admin_h,
                        json={"order_code": f"LN-LOCK-{suffix}", "auto_from_bom": False,
                              "planned_volume_hl": 100})
    assert order.status_code == 201, order.text
    brew_order_id = order.json()["brew_order_id"]

    brew = client.post("/api/brewing/brews", headers=vanhanh_h,
                       json={"brew_code": f"BR-LOCK-{suffix}", "wort_type": "Dịch test", "volume_hl": 100,
                             "lm_code": f"LM-LOCK-{suffix}", "tank_lm": f"T-LOCK-{suffix}",
                             "brew_order_id": brew_order_id})
    assert brew.status_code == 201, brew.text
    brew_id = brew.json()["brew_id"]

    batch = client.post(f"/api/brewing/brews/{brew_id}/batches", headers=vanhanh_h,
                        json={"batch_code": str(700 + ord(suffix) - ord("A")), "line_id": line_id})
    assert batch.status_code == 201, batch.text
    batch_id = batch.json()["batch_id"]
    fin_batch = client.post(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/finish", headers=vanhanh_h)
    assert fin_batch.status_code == 200, fin_batch.text
    _declare_pending(client, vanhanh_h, "nau", "brew_batch", batch_id)

    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment = next(f for f in ferments if f["lm_code"] == f"LM-LOCK-{suffix}")
    ferment_id = ferment["ferment_id"]
    _declare_pending(client, vanhanh_h, "len_men_chinh", "ferment", f"LM-LOCK-{suffix}__len_men_chinh")
    _declare_pending(client, vanhanh_h, "len_men_phu", "ferment", f"LM-LOCK-{suffix}__len_men_phu")
    ok = client.post(f"/api/brewing/ferments/{ferment_id}/approve", headers=admin_h)
    assert ok.status_code == 200, ok.text

    master = client.post("/api/brewing/filter-master-orders", headers=admin_h,
                         json={"order_code": f"LOC-LOCK-{suffix}",
                               "children": [{"blend_mode": "khong_phoi",
                                            "tanks": [{"tank_type": "cct", "ferment_id": ferment_id,
                                                      "planned_v_dich_hl": 100}]}]})
    assert master.status_code == 201, master.text
    master_detail = client.get(f"/api/brewing/filter-master-orders/{master.json()['filter_master_order_id']}",
                               headers=admin_h).json()
    filter_order_id = master_detail["children"][0]["filter_order_id"]

    filt = client.post("/api/brewing/filters", headers=vanhanh_h,
                       json={"filter_code": f"FL-LOCK-{suffix}", "filter_order_id": filter_order_id,
                             "to_bbt": f"BBT-LOCK-{suffix}"})
    assert filt.status_code == 201, filt.text
    filter_id = filt.json()["filter_id"]
    tanks = client.get(f"/api/brewing/filters/{filter_id}/tanks", headers=admin_h).json()
    fin_filt = client.post(f"/api/brewing/filters/{filter_id}/tanks/{tanks[0]['line_id']}/finish",
                           headers=vanhanh_h, json={"v_dich_hl": 100, "nuoc_bai_khi_hl": 0})
    assert fin_filt.status_code == 200, fin_filt.text
    _declare_pending(client, vanhanh_h, "loc", "filter", f"FL-LOCK-{suffix}")
    approve_filt = client.post(f"/api/brewing/filters/{filter_id}/approve", headers=admin_h)
    assert approve_filt.status_code == 200, approve_filt.text

    bottle = client.post("/api/brewing/bottles", headers=vanhanh_h,
                         json={"bottle_code": f"CH-LOCK-{suffix}", "from_bbt": f"BBT-LOCK-{suffix}"})
    assert bottle.status_code == 201, bottle.text
    bottle_id = bottle.json()["bottle_id"]
    fin_bottle = client.post(f"/api/brewing/bottles/{bottle_id}/finish", headers=vanhanh_h,
                             json={"v_cap_chiet_hl": 100, "ca1": 100, "ca2": 0, "ca3": 0})
    assert fin_bottle.status_code == 200, fin_bottle.text
    _declare_pending(client, vanhanh_h, "thanh_pham", "bottle", f"CH-LOCK-{suffix}__thanh_pham")
    approve_bottle = client.post(f"/api/brewing/bottles/{bottle_id}/approve", headers=admin_h)
    assert approve_bottle.status_code == 200, approve_bottle.text

    return {"brew_order_id": brew_order_id, "brew_id": brew_id, "batch_id": batch_id,
            "ferment_id": ferment_id, "filter_master_order_id": master.json()["filter_master_order_id"],
            "filter_order_id": filter_order_id, "filter_id": filter_id, "bottle_id": bottle_id}


def _brew_order_locked(client, admin_h, brew_order_id):
    orders = client.get("/api/brewing/orders", headers=admin_h).json()
    return next(o for o in orders if o["brew_order_id"] == brew_order_id)["locked"]


def _filter_order_locked(client, admin_h, filter_order_id):
    orders = client.get("/api/brewing/filter-orders", headers=admin_h).json()
    return next(o for o in orders if o["filter_order_id"] == filter_order_id)["locked"]


def _filter_master_order_locked(client, admin_h, filter_master_order_id):
    masters = client.get("/api/brewing/filter-master-orders", headers=admin_h).json()
    return next(m for m in masters if m["filter_master_order_id"] == filter_master_order_id)["locked"]


def test_lock_requires_forward_order_and_own_completion(client, admin_h, vanhanh_h, brewhouse_line_id):
    ids = _build_full_chain(client, admin_h, vanhanh_h, "A", brewhouse_line_id)

    # Không thể khóa Lên men khi Nấu (mã nấu nguồn) chưa khóa.
    r = client.post(f"/api/brewing/ferments/{ids['ferment_id']}/lock-lot", headers=admin_h)
    assert r.status_code == 409, r.text

    # Không thể khóa Lọc khi Lên men chưa khóa.
    r = client.post(f"/api/brewing/filters/{ids['filter_id']}/lock-lot", headers=admin_h)
    assert r.status_code == 409, r.text

    # Không thể khóa Chiết khi Lọc chưa khóa.
    r = client.post(f"/api/brewing/bottles/{ids['bottle_id']}/lock-lot", headers=admin_h)
    assert r.status_code == 409, r.text

    # Khóa Nấu thành công (đã hoàn thành mẻ + đủ chỉ tiêu) -> Lệnh nấu tự khóa theo (chỉ 1 mã
    # nấu duy nhất dưới lệnh này).
    r = client.post(f"/api/brewing/brews/{ids['brew_id']}/lock-lot", headers=admin_h)
    assert r.status_code == 200, r.text
    assert r.json()["locked"] is True
    brews = client.get("/api/brewing/brews", headers=admin_h).json()
    brew_row = next(b for b in brews if b["brew_id"] == ids["brew_id"])
    assert brew_row["locked"] is True
    assert _brew_order_locked(client, admin_h, ids["brew_order_id"]) is True

    # Giờ khóa Lên men được rồi.
    r = client.post(f"/api/brewing/ferments/{ids['ferment_id']}/lock-lot", headers=admin_h)
    assert r.status_code == 200, r.text
    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    assert next(f for f in ferments if f["ferment_id"] == ids["ferment_id"])["locked"] is True

    # Giờ khóa Lọc được -> Lệnh lọc nhỏ + Lệnh lọc lớn tự khóa theo.
    r = client.post(f"/api/brewing/filters/{ids['filter_id']}/lock-lot", headers=admin_h)
    assert r.status_code == 200, r.text
    assert _filter_order_locked(client, admin_h, ids["filter_order_id"]) is True
    assert _filter_master_order_locked(client, admin_h, ids["filter_master_order_id"]) is True

    # Giờ khóa Chiết được.
    r = client.post(f"/api/brewing/bottles/{ids['bottle_id']}/lock-lot", headers=admin_h)
    assert r.status_code == 200, r.text
    bottles = client.get("/api/brewing/bottles", headers=admin_h).json()
    assert next(b for b in bottles if b["bottle_id"] == ids["bottle_id"])["locked"] is True


def test_lock_blocks_mutations_at_locked_stage(client, admin_h, vanhanh_h, brewhouse_line_id):
    ids = _build_full_chain(client, admin_h, vanhanh_h, "B", brewhouse_line_id)
    r = client.post(f"/api/brewing/brews/{ids['brew_id']}/lock-lot", headers=admin_h)
    assert r.status_code == 200, r.text

    # Mã nấu đã khóa -> thêm mẻ mới bị chặn.
    add_batch = client.post(f"/api/brewing/brews/{ids['brew_id']}/batches", headers=vanhanh_h,
                            json={"batch_code": "799", "line_id": brewhouse_line_id})
    assert add_batch.status_code == 409, add_batch.text

    # Lệnh nấu đã tự khóa theo -> xóa bị chặn.
    del_order = client.delete(f"/api/brewing/orders/{ids['brew_order_id']}", headers=admin_h)
    assert del_order.status_code == 409, del_order.text

    # Lên men CHƯA khóa (chỉ Nấu khóa) -> vẫn ghi chỉ tiêu bình thường, không bị chặn nhầm.
    qc = client.post("/api/brewing/qc-results", headers=vanhanh_h,
                     json={"stage": "len_men_chinh", "scope_type": "ferment",
                           "scope_id": f"LM-LOCK-B__len_men_chinh", "parameter": "TEST-PARAM",
                           "value": 1, "lower_limit": 0, "upper_limit": 10})
    assert qc.status_code == 201, qc.text


def test_lock_requires_permission(client, admin_h, vanhanh_h, brewhouse_line_id):
    ids = _build_full_chain(client, admin_h, vanhanh_h, "C", brewhouse_line_id)
    r = client.post(f"/api/brewing/brews/{ids['brew_id']}/lock-lot", headers=vanhanh_h)
    assert r.status_code == 403, r.text


def test_unlock_requires_admin_and_reverse_order(client, admin_h, vanhanh_h, brewhouse_line_id):
    ids = _build_full_chain(client, admin_h, vanhanh_h, "D", brewhouse_line_id)
    for kind, id_ in (("brews", ids["brew_id"]), ("ferments", ids["ferment_id"]),
                     ("filters", ids["filter_id"]), ("bottles", ids["bottle_id"])):
        r = client.post(f"/api/brewing/{kind}/{id_}/lock-lot", headers=admin_h)
        assert r.status_code == 200, r.text

    # Không phải admin -> 403.
    forbidden = client.post(f"/api/brewing/bottles/{ids['bottle_id']}/unlock-lot", headers=vanhanh_h)
    assert forbidden.status_code == 403, forbidden.text

    # Không thể mở Nấu khi Lên men còn khóa.
    r = client.post(f"/api/brewing/brews/{ids['brew_id']}/unlock-lot", headers=admin_h)
    assert r.status_code == 409, r.text
    # Không thể mở Lên men khi Lọc còn khóa.
    r = client.post(f"/api/brewing/ferments/{ids['ferment_id']}/unlock-lot", headers=admin_h)
    assert r.status_code == 409, r.text
    # Không thể mở Lọc khi Chiết còn khóa.
    r = client.post(f"/api/brewing/filters/{ids['filter_id']}/unlock-lot", headers=admin_h)
    assert r.status_code == 409, r.text

    # Mở đúng thứ tự ngược: Chiết -> Lọc -> Lên men -> Nấu.
    r = client.post(f"/api/brewing/bottles/{ids['bottle_id']}/unlock-lot", headers=admin_h)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/brewing/filters/{ids['filter_id']}/unlock-lot", headers=admin_h)
    assert r.status_code == 200, r.text
    assert _filter_order_locked(client, admin_h, ids["filter_order_id"]) is False
    assert _filter_master_order_locked(client, admin_h, ids["filter_master_order_id"]) is False
    r = client.post(f"/api/brewing/ferments/{ids['ferment_id']}/unlock-lot", headers=admin_h)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/brewing/brews/{ids['brew_id']}/unlock-lot", headers=admin_h)
    assert r.status_code == 200, r.text
    assert _brew_order_locked(client, admin_h, ids["brew_order_id"]) is False

    # Sau khi mở, sửa lại được bình thường.
    fin = client.post(f"/api/brewing/bottles/{ids['bottle_id']}/finish", headers=vanhanh_h,
                      json={"v_cap_chiet_hl": 100})
    assert fin.status_code == 200, fin.text


def test_colors_computed_live_from_real_data_not_manual_flags(client, admin_h, vanhanh_h, brewhouse_line_id):
    """Phần 1 của plan gốc — màu Nấu/Lên men/Lọc/Chiết phải phản ánh dữ liệu nhập qua ĐÚNG
    endpoint thật (POST /qc-results, POST /materials, ...), không phải cột has_indicators/
    has_nvl (đã xác nhận là cờ chết, xem routers/brewing.py::_stage_ok)."""
    ids = _build_full_chain(client, admin_h, vanhanh_h, "E", brewhouse_line_id)

    brews = client.get("/api/brewing/brews", headers=admin_h).json()
    brew_row = next(b for b in brews if b["brew_id"] == ids["brew_id"])
    assert brew_row["color"] == "green"

    add_nvl = client.post(f"/api/brewing/brews/{ids['brew_id']}/batches/{ids['batch_id']}/materials",
                          headers=vanhanh_h, json={"material_name": "Malt test", "quantity": 10, "uom": "kg"})
    assert add_nvl.status_code == 201, add_nvl.text
    brews = client.get("/api/brewing/brews", headers=admin_h).json()
    brew_row = next(b for b in brews if b["brew_id"] == ids["brew_id"])
    assert brew_row["color"] == "blue"

    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment_row = next(f for f in ferments if f["ferment_id"] == ids["ferment_id"])
    assert ferment_row["color"] == "blue"

    filters = client.get("/api/brewing/filters", headers=admin_h).json()
    filter_row = next(f for f in filters if f["filter_id"] == ids["filter_id"])
    assert filter_row["color"] == "green"
    add_filt_nvl = client.post(f"/api/brewing/filters/{ids['filter_id']}/materials", headers=vanhanh_h,
                               json={"material_name": "Bột trợ lọc", "quantity": 1, "uom": "kg"})
    assert add_filt_nvl.status_code == 201, add_filt_nvl.text
    filters = client.get("/api/brewing/filters", headers=admin_h).json()
    filter_row = next(f for f in filters if f["filter_id"] == ids["filter_id"])
    assert filter_row["color"] == "blue"

    bottles = client.get("/api/brewing/bottles", headers=admin_h).json()
    bottle_row = next(b for b in bottles if b["bottle_id"] == ids["bottle_id"])
    assert bottle_row["color"] == "blue"
