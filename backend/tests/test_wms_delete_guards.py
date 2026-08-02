"""Test 2 nhóm tính năng mới:
1) Quy tắc xóa theo đúng thứ tự công đoạn — chỉ được xóa 1 bước khi bước SAU nó chưa xảy ra;
   muốn xóa bước trước (khi bước sau đã có), phải xóa bước sau trước (Lọc chặn nếu đã Chiết,
   Lên men chặn nếu đã Lọc, Chiết chặn nếu đã sinh vỉ/keg Kho TP — trừ khi vỉ/keg đã bị xóa/
   chưa xuất kho).
2) CRUD vị trí kho thành phẩm (WmsLocation: sửa/xóa) + xóa vỉ/keg (chặn nếu đã xuất kho)."""

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


def _declare_pending(client, headers, stage, scope_type, scope_id):
    """Khai báo đạt mọi chỉ tiêu bắt buộc đang "pending" cho scope này — cần thiết vì các
    stage "len_men_phu"/"thanh_pham" dùng chung toàn cục, module test khác (VD
    test_stage_qc.py) có thể đã gán thêm nhóm mandatory cho stage này trước đó."""
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


def _a_brew_order(client, admin_h, order_code, product_id=None):
    r = client.post("/api/brewing/orders", headers=admin_h,
                    json={"order_code": order_code, "product_id": product_id, "auto_from_bom": False, "planned_volume_hl": 100})
    assert r.status_code == 201, r.text
    return r.json()["brew_order_id"]


def _build_chain(client, admin_h, vanhanh_h, kcs_h, suffix, finished_product_id=None):
    """Dựng 1 chuỗi Nấu->Lên men->Lọc->Chiết hoàn chỉnh (không pallet), trả về mọi id/code.
    finished_product_id tuỳ chọn — chỉ cần khi test sau đó còn thao tác kho TP theo số lượng
    quy đổi (xuất/phân rã/điều chuyển), vì _pack_divisor cần tra được pack_size qua SKU đã
    đăng ký danh mục (không có SKU -> mặc định 1, xem services/wms.py::_pack_divisor)."""
    lm_code = f"LM-{suffix}"
    order_id = _a_brew_order(client, admin_h, f"LN-{suffix}")
    b = client.post("/api/brewing/brews", headers=vanhanh_h,
                    json={"brew_code": f"BR-{suffix}", "wort_type": "Dich test", "volume_hl": 100,
                          "lm_code": lm_code, "tank_lm": f"T-{suffix}", "brew_order_id": order_id})
    assert b.status_code == 201, b.text
    ferments = client.get("/api/brewing/ferments", headers=kcs_h).json()["items"]
    ferment = next(f for f in ferments if f["lm_code"] == lm_code)
    _declare_pending(client, vanhanh_h, "len_men_phu", "ferment", f"{lm_code}__len_men_phu")
    ok = client.post(f"/api/brewing/ferments/{ferment['ferment_id']}/approve", headers=kcs_h)
    assert ok.status_code == 200, ok.text

    filter_order = client.post("/api/brewing/filter-orders", headers=admin_h,
                               json={"order_code": f"LOC-{suffix}", "blend_mode": "khong_phoi",
                                     "tank_ferment_ids": [ferment["ferment_id"]], "planned_volume_hl": 1000})
    assert filter_order.status_code == 201, filter_order.text
    filter_code = f"FL-{suffix}"
    bbt = f"BBT-{suffix}"
    f = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": filter_code, "beer_type": "Bia test", "wort_type": "Dich test",
                          "filter_order_id": filter_order.json()["filter_order_id"], "to_bbt": bbt})
    assert f.status_code == 201, f.text
    filter_id = f.json()["filter_id"]
    filter_tanks = client.get(f"/api/brewing/filters/{filter_id}/tanks", headers=admin_h).json()
    fin = client.post(f"/api/brewing/filters/{filter_id}/tanks/{filter_tanks[0]['line_id']}/finish",
                      headers=vanhanh_h, json={"v_dich_hl": 100, "nuoc_bai_khi_hl": 0,
                                                "batch_number": f"B-{suffix}", "order_number": f"O-{suffix}", "batch_seq_no": "1"})
    assert fin.status_code == 200, fin.text
    _declare_pending(client, vanhanh_h, "loc", "filter", filter_code)
    approve_filter = client.post(f"/api/brewing/filters/{filter_id}/approve", headers=kcs_h)
    assert approve_filter.status_code == 200, approve_filter.text

    bottle_code = f"CH-{suffix}"
    bo = client.post("/api/brewing/bottles", headers=vanhanh_h,
                     json={"bottle_code": bottle_code, "beer_type": "Bia test", "from_bbt": bbt,
                           "finished_product_id": finished_product_id})
    assert bo.status_code == 201, bo.text
    bottle_id = bo.json()["bottle_id"]
    bo_fin = client.post(f"/api/brewing/bottles/{bottle_id}/finish", headers=vanhanh_h,
                         json={"v_cap_chiet_hl": 100, "ca1": 100})
    assert bo_fin.status_code == 200, bo_fin.text

    return {"ferment_id": ferment["ferment_id"], "filter_id": filter_id, "bottle_id": bottle_id,
            "bottle_code": bottle_code}


def test_delete_filter_blocked_while_bottle_references_it(client, admin_h, vanhanh_h, kcs_h):
    chain = _build_chain(client, admin_h, vanhanh_h, kcs_h, "DELGUARD01")
    blocked = client.delete(f"/api/brewing/filters/{chain['filter_id']}", headers=vanhanh_h)
    assert blocked.status_code == 409, blocked.text
    assert "chiết" in blocked.json()["detail"].lower()

    ok = client.delete(f"/api/brewing/bottles/{chain['bottle_id']}", headers=vanhanh_h)
    assert ok.status_code == 204, ok.text
    ok2 = client.delete(f"/api/brewing/filters/{chain['filter_id']}", headers=vanhanh_h)
    assert ok2.status_code == 204, ok2.text


def test_delete_ferment_blocked_while_filter_references_it(client, admin_h, vanhanh_h, kcs_h):
    """_build_chain duyệt KCS lô lên men (Duyệt LM) trước khi lọc — xóa bị chặn vì còn mẻ lọc
    tham chiếu; SAU KHI gỡ bỏ mẻ lọc/mẻ chiết, xóa vẫn tiếp tục bị chặn vì lô LM đã duyệt KCS
    (xem routers/brewing.py::delete_ferment — "đã duyệt KCS" chặn vĩnh viễn, không phải chỉ
    tạm thời vì còn tham chiếu hạ lưu)."""
    chain = _build_chain(client, admin_h, vanhanh_h, kcs_h, "DELGUARD02")
    blocked = client.delete(f"/api/brewing/ferments/{chain['ferment_id']}", headers=vanhanh_h)
    assert blocked.status_code == 409, blocked.text
    assert "lọc" in blocked.json()["detail"].lower()

    client.delete(f"/api/brewing/bottles/{chain['bottle_id']}", headers=vanhanh_h)
    client.delete(f"/api/brewing/filters/{chain['filter_id']}", headers=vanhanh_h)
    still_blocked = client.delete(f"/api/brewing/ferments/{chain['ferment_id']}", headers=vanhanh_h)
    assert still_blocked.status_code == 409, still_blocked.text
    assert "duyệt kcs" in still_blocked.json()["detail"].lower()


def test_delete_bottle_blocked_until_units_deleted(client, admin_h, vanhanh_h, kcs_h):
    chain = _build_chain(client, admin_h, vanhanh_h, kcs_h, "DELGUARD03")
    _declare_pending(client, vanhanh_h, "thanh_pham", "bottle", f"{chain['bottle_code']}__thanh_pham")
    # Duyệt nhập kho thành phẩm nay thuộc quyền Giám đốc/Phó GĐ Sản xuất (production.release_to_wms),
    # tách khỏi quality.release của KCS — dùng admin_h (bypass mọi permission) thay vì kcs_h ở đây.
    approve = client.post(f"/api/brewing/bottles/{chain['bottle_id']}/approve", headers=admin_h)
    assert approve.status_code == 200, approve.text
    unit_codes = approve.json()["unit_codes"]

    blocked = client.delete(f"/api/brewing/bottles/{chain['bottle_id']}", headers=vanhanh_h)
    assert blocked.status_code == 409, blocked.text
    assert "vỉ/keg" in blocked.json()["detail"].lower()

    units = client.get("/api/wms/units", headers=vanhanh_h).json()

    # Xóa unit cần quyền warehouse.issue (kcs không có quyền kho — chỉ có quality.release).
    for code in unit_codes:
        u = next(x for x in units if x["unit_code"] == code)
        del_unit = client.delete(f"/api/wms/units/{u['unit_id']}", headers=admin_h)
        assert del_unit.status_code == 204, del_unit.text

    # Bottle giờ phải xóa được (approved/stocked đã được "mở khóa" lại).
    ok = client.delete(f"/api/brewing/bottles/{chain['bottle_id']}", headers=vanhanh_h)
    assert ok.status_code == 204, ok.text


def test_cannot_delete_shipped_unit(client, admin_h, vanhanh_h, kcs_h):
    """1 dòng lô (xem docs/WMS-LOT-LEVEL-REDESIGN.md) chỉ chuyển hẳn sang status="shipped"
    khi bị xuất TRỌN VẸN — xuất một phần chỉ tách dòng (phần "stored" còn lại tách sang dòng
    khác), nên phải xuất ĐÚNG BẰNG số lượng cả lô (ca1=100) để dòng gốc không bị tách. Cần
    đăng ký SKU (FinishedProduct) trước để _pack_divisor tra đúng pack_size=24 lúc xuất —
    không có SKU sẽ mặc định 1, khiến "quantity=100" chỉ xuất được 100/2400 lon (một phần)."""
    fp = client.post("/api/finished-products", headers=admin_h,
                     json={"code": "SKU-DELGUARD04", "name": "SKU delguard04", "uom": "lon",
                           "unit_type": "vi", "pack_size": 24})
    assert fp.status_code == 201, fp.text
    chain = _build_chain(client, admin_h, vanhanh_h, kcs_h, "DELGUARD04",
                         finished_product_id=fp.json()["finished_product_id"])
    _declare_pending(client, vanhanh_h, "thanh_pham", "bottle", f"{chain['bottle_code']}__thanh_pham")
    # Duyệt nhập kho thành phẩm nay thuộc quyền Giám đốc/Phó GĐ Sản xuất (production.release_to_wms),
    # tách khỏi quality.release của KCS — dùng admin_h (bypass mọi permission) thay vì kcs_h ở đây.
    approve = client.post(f"/api/brewing/bottles/{chain['bottle_id']}/approve", headers=admin_h)
    assert approve.json()["count"] == 100
    unit_code = approve.json()["unit_codes"][0]
    units = client.get("/api/wms/units", headers=vanhanh_h).json()
    unit = next(u for u in units if u["unit_code"] == unit_code)
    unit_id = unit["unit_id"]

    st = client.post("/api/wms/ship-to", headers=admin_h, json={"code": "DIST-DELGUARD", "name": "NPP test"})
    assert st.status_code == 201, st.text
    ship = client.post("/api/wms/shipments", headers=admin_h,
                       json={"ship_to_id": st.json()["ship_to_id"],
                             "lines": [{"product_name": unit["product"], "lot_code": unit["lot_code"],
                                       "unit_type": unit["unit_type"], "quantity": 100}]})
    assert ship.status_code == 201, ship.text

    blocked = client.delete(f"/api/wms/units/{unit_id}", headers=admin_h)
    assert blocked.status_code == 409, blocked.text
    assert "xuất kho" in blocked.json()["detail"].lower()


def test_wms_location_crud(client, admin_h):
    created = client.post("/api/wms/locations", headers=admin_h,
                          json={"code": "TEST-LOC-01", "name": "Vị trí test", "zone": "Z1",
                                "kind": "bin", "capacity": 5})
    assert created.status_code == 201, created.text
    loc_id = created.json()["loc_id"]

    locs = client.get("/api/wms/locations", headers=admin_h).json()
    row = next(l for l in locs if l["loc_id"] == loc_id)
    assert row["capacity"] == 5 and row["active"] is True and row["used"] == 0

    updated = client.put(f"/api/wms/locations/{loc_id}", headers=admin_h, json={"capacity": 8})
    assert updated.status_code == 200, updated.text
    locs2 = client.get("/api/wms/locations", headers=admin_h).json()
    assert next(l for l in locs2 if l["loc_id"] == loc_id)["capacity"] == 8

    deleted = client.delete(f"/api/wms/locations/{loc_id}", headers=admin_h)
    assert deleted.status_code == 204, deleted.text
    locs3 = client.get("/api/wms/locations", headers=admin_h).json()
    assert not any(l["loc_id"] == loc_id for l in locs3)


def test_wms_location_delete_blocked_when_unit_stored(client, admin_h, vanhanh_h):
    """capacity=5 tính theo SỐ VỈ (không phải lon) — cần đăng ký SKU trước để _pack_divisor
    tra đúng pack_size=24, nếu không sẽ mặc định 1 và 48 lon bị hiểu nhầm thành 48 vỉ (> 5)."""
    fp = client.post("/api/finished-products", headers=admin_h,
                     json={"code": "TEST-SKU-LOC02", "name": "TEST-SKU-LOC02", "uom": "lon",
                           "unit_type": "vi", "pack_size": 24})
    assert fp.status_code == 201, fp.text
    loc = client.post("/api/wms/locations", headers=admin_h,
                      json={"code": "TEST-LOC-02", "name": "Vị trí test 2", "capacity": 5}).json()
    build = client.post("/api/wms/units", headers=admin_h,
                        json={"finished_product_id": fp.json()["finished_product_id"],
                              "product_name": "TEST-SKU-LOC02", "lot_code": "TEST-LOT", "total": 48, "pack_size": 24})
    assert build.status_code == 201, build.text
    unit_code = build.json()["unit_codes"][0]
    units = client.get("/api/wms/units", headers=admin_h).json()
    unit_id = next(u for u in units if u["unit_code"] == unit_code)["unit_id"]
    putaway = client.post(f"/api/wms/units/{unit_id}/putaway", headers=admin_h,
                          json={"loc_id": loc["loc_id"]})
    assert putaway.status_code == 200, putaway.text

    blocked = client.delete(f"/api/wms/locations/{loc['loc_id']}", headers=admin_h)
    assert blocked.status_code == 409, blocked.text
