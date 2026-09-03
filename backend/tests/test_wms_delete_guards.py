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


# test_delete_bottle_blocked_until_units_deleted (bottle bị chặn xóa khi còn vỉ/keg trong kho)
# đã bỏ — approve_bottle đã tháo khỏi WMS, bottle mới không còn cách nào tạo ra vỉ/keg để rơi
# vào trạng thái này nữa (xem docstring approve_bottle hiện tại). Coverage tương đương (chặn
# xóa Lô thành phẩm) nay là guard sẵn có `if p.approved: ...` ở delete_pack_lot — chặn RỘNG HƠN
# (mọi lô đã Duyệt KCS, không chỉ khi có vỉ/keg), nên không cần test unlock-rồi-xóa riêng.


def test_cannot_delete_shipped_unit(client, admin_h):
    """1 dòng lô (xem docs/WMS-LOT-LEVEL-REDESIGN.md) chỉ chuyển hẳn sang status="shipped"
    khi bị xuất TRỌN VẸN — xuất một phần chỉ tách dòng (phần "stored" còn lại tách sang dòng
    khác), nên phải xuất ĐÚNG BẰNG số lượng cả lô để dòng gốc không bị tách. Dùng "Nhập kho
    thủ công" (source=manual, cần confirm-receipt-by-lot trước khi xuất được) thay chuỗi chiết
    cũ đã tháo khỏi WMS — mirror test_wms_units.py::test_delete_units_batch_blocked_if_shipped
    nhưng qua DELETE đơn (không phải delete-batch)."""
    fp = client.post("/api/finished-products", headers=admin_h,
                     json={"code": "SKU-DELGUARD04", "name": "SKU delguard04", "uom": "lon",
                           "unit_type": "vi", "pack_size": 24})
    assert fp.status_code == 201, fp.text
    loc = client.post("/api/wms/locations", headers=admin_h,
                      json={"code": "LOC-DELGUARD04", "name": "Vị trí delguard04", "capacity": 5000})
    assert loc.status_code == 201, loc.text
    build = client.post("/api/wms/units", headers=admin_h,
                        json={"finished_product_id": fp.json()["finished_product_id"],
                              "product_name": "SKU-DELGUARD04", "lot_code": "LOT-DELGUARD04",
                              "total": 2400, "pack_size": 24, "unit_type": "vi", "loc_id": loc.json()["loc_id"]})
    assert build.status_code == 201, build.text
    unit_code = build.json()["unit_codes"][0]
    units = client.get("/api/wms/units", headers=admin_h).json()
    unit = next(u for u in units if u["unit_code"] == unit_code)
    unit_id = unit["unit_id"]

    confirm = client.post("/api/wms/units/confirm-receipt-by-lot", headers=admin_h,
                          json={"product_name": "SKU-DELGUARD04", "lot_code": "LOT-DELGUARD04", "unit_type": "vi"})
    assert confirm.status_code == 200, confirm.text

    st = client.post("/api/suppliers", headers=admin_h, json={"code": "DIST-DELGUARD", "name": "NPP test"})
    assert st.status_code == 201, st.text
    ship = client.post("/api/wms/shipments", headers=admin_h,
                       json={"ship_to_id": st.json()["supplier_id"],
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


# ==================== Audit đợt 2 (2026-09-03) — FK-delete safety Kho TP/WMS ====================
# 18. delete_vehicle không kiểm tra Shipment/WmsTransfer.vehicle_id.
# 19. delete_location sót WmsTransferLine/WmsTransfer/NearExpiryEntry/ConsignedEntry/
#     FactoryImportEntry tham chiếu vị trí (chỉ kiểm tra tồn LIVE, không kiểm tra lịch sử).
# 20. delete_unit(s)/delete_units_by_criteria không dọn/chặn khi còn WmsTransferLine (FK NOT
#     NULL, không ondelete, tự nhận là "giữ vĩnh viễn làm lịch sử").
# 21. delete_warehouse không kiểm tra Shipment.warehouse_id/LoadOrder.warehouse_id.

def test_delete_vehicle_blocked_by_shipment(client, admin_h):
    v = client.post("/api/wms/vehicles", headers=admin_h, json={"plate": "R2-VEH-SHIP"})
    assert v.status_code == 201, v.text
    vehicle_id = v.json()["vehicle_id"]

    loc = client.post("/api/wms/locations", headers=admin_h,
                      json={"code": "R2-VEH-LOC1", "name": "R2 veh loc1", "capacity": 100}).json()
    build = client.post("/api/wms/units", headers=admin_h,
                        json={"product_name": "R2-VEH-SKU", "lot_code": "R2-VEH-LOT", "total": 10,
                              "pack_size": 1, "loc_id": loc["loc_id"]})
    assert build.status_code == 201, build.text
    confirm = client.post("/api/wms/units/confirm-receipt-by-lot", headers=admin_h,
                          json={"product_name": "R2-VEH-SKU", "lot_code": "R2-VEH-LOT", "unit_type": "vi"})
    assert confirm.status_code == 200, confirm.text
    st = client.post("/api/suppliers", headers=admin_h, json={"code": "R2-VEH-DIST", "name": "NPP test veh"})
    assert st.status_code == 201, st.text
    ship = client.post("/api/wms/shipments", headers=admin_h,
                       json={"ship_to_id": st.json()["supplier_id"], "vehicle_id": vehicle_id,
                             "lines": [{"product_name": "R2-VEH-SKU", "lot_code": "R2-VEH-LOT",
                                       "unit_type": "vi", "quantity": 5}]})
    assert ship.status_code == 201, ship.text

    blocked = client.delete(f"/api/wms/vehicles/{vehicle_id}", headers=admin_h)
    assert blocked.status_code == 409, blocked.text
    assert "phiếu xuất kho" in blocked.json()["detail"].lower()


def test_delete_vehicle_blocked_by_transfer(client, admin_h):
    v = client.post("/api/wms/vehicles", headers=admin_h, json={"plate": "R2-VEH-TRANS"})
    assert v.status_code == 201, v.text
    vehicle_id = v.json()["vehicle_id"]

    loc_a = client.post("/api/wms/locations", headers=admin_h,
                        json={"code": "R2-VEHTX-LOCA", "name": "loc a", "capacity": 100}).json()["loc_id"]
    loc_b = client.post("/api/wms/locations", headers=admin_h,
                        json={"code": "R2-VEHTX-LOCB", "name": "loc b", "capacity": 100}).json()["loc_id"]
    build = client.post("/api/wms/units", headers=admin_h,
                        json={"product_name": "R2-VEHTX-SKU", "lot_code": "R2-VEHTX-LOT", "total": 10,
                              "pack_size": 1, "loc_id": loc_a})
    assert build.status_code == 201, build.text
    confirm = client.post("/api/wms/units/confirm-receipt-by-lot", headers=admin_h,
                          json={"product_name": "R2-VEHTX-SKU", "lot_code": "R2-VEHTX-LOT", "unit_type": "vi"})
    assert confirm.status_code == 200, confirm.text
    tr = client.post("/api/wms/transfers", headers=admin_h,
                     json={"to_location_id": loc_b, "vehicle_id": vehicle_id,
                           "lines": [{"product_name": "R2-VEHTX-SKU", "lot_code": "R2-VEHTX-LOT",
                                     "unit_type": "vi", "quantity": 5}]})
    assert tr.status_code == 201, tr.text

    blocked = client.delete(f"/api/wms/vehicles/{vehicle_id}", headers=admin_h)
    assert blocked.status_code == 409, blocked.text
    assert "điều chuyển" in blocked.json()["detail"].lower()


def test_delete_warehouse_blocked_by_shipment(client, admin_h):
    wh = client.post("/api/wms/warehouses", headers=admin_h,
                     json={"code": "R2-WH-SHIP", "name": "Kho test R2 shipment"})
    assert wh.status_code == 201, wh.text
    warehouse_id = wh.json()["warehouse_id"]

    loc = client.post("/api/wms/locations", headers=admin_h,
                      json={"code": "R2-WH-LOC", "name": "R2 wh loc", "capacity": 100,
                            "warehouse_id": warehouse_id}).json()
    build = client.post("/api/wms/units", headers=admin_h,
                        json={"product_name": "R2-WH-SKU", "lot_code": "R2-WH-LOT", "total": 10,
                              "pack_size": 1, "loc_id": loc["loc_id"]})
    assert build.status_code == 201, build.text
    confirm = client.post("/api/wms/units/confirm-receipt-by-lot", headers=admin_h,
                          json={"product_name": "R2-WH-SKU", "lot_code": "R2-WH-LOT", "unit_type": "vi"})
    assert confirm.status_code == 200, confirm.text
    st = client.post("/api/suppliers", headers=admin_h, json={"code": "R2-WH-DIST", "name": "NPP test wh"})
    assert st.status_code == 201, st.text
    ship = client.post("/api/wms/shipments", headers=admin_h,
                       json={"ship_to_id": st.json()["supplier_id"], "warehouse_id": warehouse_id,
                             "lines": [{"product_name": "R2-WH-SKU", "lot_code": "R2-WH-LOT",
                                       "unit_type": "vi", "quantity": 5}]})
    assert ship.status_code == 201, ship.text

    # Xóa hết vị trí trước để loại trừ nguyên nhân "còn vị trí" (guard đã có sẵn) — vẫn phải
    # chặn vì Shipment.warehouse_id còn tham chiếu.
    del_loc = client.delete(f"/api/wms/locations/{loc['loc_id']}", headers=admin_h)
    assert del_loc.status_code == 409, del_loc.text  # còn unit "stored" — dùng lại kho khác để test warehouse guard riêng

    blocked = client.delete(f"/api/wms/warehouses/{warehouse_id}", headers=admin_h)
    assert blocked.status_code == 409, blocked.text


def test_delete_location_blocked_by_transfer_history_even_after_stock_moved_away(client, admin_h):
    loc_a = client.post("/api/wms/locations", headers=admin_h,
                        json={"code": "R2-LOCTX-A", "name": "loc a", "capacity": 100}).json()["loc_id"]
    loc_b = client.post("/api/wms/locations", headers=admin_h,
                        json={"code": "R2-LOCTX-B", "name": "loc b", "capacity": 100}).json()["loc_id"]
    loc_c = client.post("/api/wms/locations", headers=admin_h,
                        json={"code": "R2-LOCTX-C", "name": "loc c", "capacity": 100}).json()["loc_id"]
    build = client.post("/api/wms/units", headers=admin_h,
                        json={"product_name": "R2-LOCTX-SKU", "lot_code": "R2-LOCTX-LOT", "total": 10,
                              "pack_size": 1, "loc_id": loc_a})
    assert build.status_code == 201, build.text
    confirm = client.post("/api/wms/units/confirm-receipt-by-lot", headers=admin_h,
                          json={"product_name": "R2-LOCTX-SKU", "lot_code": "R2-LOCTX-LOT", "unit_type": "vi"})
    assert confirm.status_code == 200, confirm.text

    tr1 = client.post("/api/wms/transfers", headers=admin_h,
                      json={"to_location_id": loc_b,
                            "lines": [{"product_name": "R2-LOCTX-SKU", "lot_code": "R2-LOCTX-LOT",
                                      "unit_type": "vi", "quantity": 10}]})
    assert tr1.status_code == 201, tr1.text

    # loc_a KHÔNG còn unit "stored" nào (đã chuyển hết đi) — guard tồn LIVE cũ sẽ cho qua, nhưng
    # WmsTransferLine.from_location_id vẫn trỏ tới loc_a (lịch sử) -> vẫn phải chặn xóa.
    blocked_a = client.delete(f"/api/wms/locations/{loc_a}", headers=admin_h)
    assert blocked_a.status_code == 409, blocked_a.text
    assert "điều chuyển" in blocked_a.json()["detail"].lower()

    # Chuyển tiếp từ loc_b sang loc_c -> loc_b cũng hết tồn LIVE, nhưng WmsTransfer.to_location_id
    # (phiếu tr1) vẫn trỏ tới loc_b -> vẫn phải chặn xóa.
    tr2 = client.post("/api/wms/transfers", headers=admin_h,
                      json={"to_location_id": loc_c,
                            "lines": [{"product_name": "R2-LOCTX-SKU", "lot_code": "R2-LOCTX-LOT",
                                      "unit_type": "vi", "quantity": 10}]})
    assert tr2.status_code == 201, tr2.text
    blocked_b = client.delete(f"/api/wms/locations/{loc_b}", headers=admin_h)
    assert blocked_b.status_code == 409, blocked_b.text
    assert "điều chuyển" in blocked_b.json()["detail"].lower()


def _release_chiet_unit_to_wms(client, admin_h, suffix):
    """Dựng 1 vỉ/keg nguồn "chiet" (qua pipeline Mẻ sản xuất, release_pack_lot_to_wms) — KHÁC
    "manual" (build_units): "chiet" xuất/điều chuyển được NGAY, không cần confirm-receipt-by-lot
    trước — cần thiết để cô lập test khỏi guard "đã duyệt Trưởng bộ phận kho" sẵn có (guard đó
    chỉ áp dụng SAU khi confirm, che mất guard MỚI đang test ở đây nếu dùng unit "manual" đã
    confirm, vì "manual" bắt buộc confirm mới điều chuyển được)."""
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
        assert client.post(f"/api/batches/{batch_id}/transition", headers=admin_h,
                           json={"target": target}).status_code == 200
    assert client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h,
                       json={"actual_qty": 1000}).status_code == 200
    assert client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={}).status_code == 200
    assert client.post(f"/api/batches/{batch_id}/transition", headers=admin_h,
                       json={"target": "completed"}).status_code == 200
    tank = client.post("/api/batch-tanks", headers=admin_h,
                       json={"batch_ids": [batch_id], "tank_code": f"TANK-{suffix}"})
    assert tank.status_code == 201, tank.text
    bbt = client.post("/api/lines", headers=admin_h,
                      json={"code": f"BBT-{suffix}", "name": f"BBT {suffix}", "kind": "tank_bbt"})
    assert bbt.status_code == 201, bbt.text
    fl = client.post("/api/batch-filter-lots", headers=admin_h,
                     json={"filter_lot_code": f"FLOT-{suffix}", "to_bbt": bbt.json()["code"],
                           "sources": [{"source_type": "tank", "source_tank_id": tank.json()["tank_id"]}]})
    assert fl.status_code == 201, fl.text
    filter_lot_id = fl.json()["filter_lot_id"]
    src = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()[0]
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    fin = client.put(f"/api/batch-filter-lots/batches/{batches[0]['batch_link_id']}/finish", headers=admin_h,
                    json={"draws": [{"source_link_id": src["link_id"], "dich_nha_hl": 900}], "nuoc_bai_khi_hl": 0})
    assert fin.status_code == 200, fin.text
    fp = client.post("/api/finished-products", headers=admin_h,
                     json={"code": f"SKU-{suffix}", "name": f"SKU {suffix}", "uom": "lon",
                           "unit_type": "vi", "pack_size": 1})
    assert fp.status_code == 201, fp.text
    pack = client.post(f"/api/batch-filter-lots/{filter_lot_id}/pack-lots", headers=admin_h,
                      json={"qty": 500, "pack_lot_code": f"PKG-{suffix}", "lot_no": f"LOT-{suffix}",
                            "finished_product_id": fp.json()["finished_product_id"]})
    assert pack.status_code == 201, pack.text
    pack_lot_id = pack.json()["pack_lot_id"]
    shifts = client.put(f"/api/batch-pack-lots/{pack_lot_id}/shifts", headers=admin_h, json={"ca1_qty": 10})
    assert shifts.status_code == 200, shifts.text
    approve = client.post(f"/api/batch-pack-lots/{pack_lot_id}/approve", headers=admin_h)
    assert approve.status_code == 200, approve.text
    release = client.post(f"/api/batch-pack-lots/{pack_lot_id}/release-to-wms", headers=admin_h)
    assert release.status_code == 200, release.text
    unit_code = release.json()["unit_codes"][0]
    units = client.get("/api/wms/units", headers=admin_h).json()
    return next(u for u in units if u["unit_code"] == unit_code)


def test_delete_unit_blocked_after_transfer_history(client, admin_h):
    unit = _release_chiet_unit_to_wms(client, admin_h, "R2UNITTX")
    assert unit["status"] == "stored"
    loc_b = client.post("/api/wms/locations", headers=admin_h,
                        json={"code": "R2-UNITTX-B", "name": "loc b", "capacity": 100}).json()["loc_id"]
    tr = client.post("/api/wms/transfers", headers=admin_h,
                     json={"to_location_id": loc_b,
                           "lines": [{"product_name": unit["product"], "lot_code": unit["lot_code"],
                                     "unit_type": unit["unit_type"], "quantity": unit["quantity"]}]})
    assert tr.status_code == 201, tr.text

    units = client.get("/api/wms/units", headers=admin_h).json()
    moved_unit = next(u for u in units if u["product"] == unit["product"] and u["lot_code"] == unit["lot_code"]
                     and u["status"] == "stored")

    blocked = client.delete(f"/api/wms/units/{moved_unit['unit_id']}", headers=admin_h)
    assert blocked.status_code == 409, blocked.text
    assert "điều chuyển" in blocked.json()["detail"].lower()

    blocked_batch = client.post("/api/wms/units/delete-batch", headers=admin_h,
                                json={"unit_ids": [moved_unit["unit_id"]]})
    assert blocked_batch.status_code == 409, blocked_batch.text


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
                              "product_name": "TEST-SKU-LOC02", "lot_code": "TEST-LOT", "total": 48, "pack_size": 24,
                              "loc_id": loc["loc_id"]})
    assert build.status_code == 201, build.text
    unit_code = build.json()["unit_codes"][0]
    units = client.get("/api/wms/units", headers=admin_h).json()
    unit_id = next(u for u in units if u["unit_code"] == unit_code)["unit_id"]
    putaway = client.post(f"/api/wms/units/{unit_id}/putaway", headers=admin_h,
                          json={"loc_id": loc["loc_id"]})
    assert putaway.status_code == 200, putaway.text

    blocked = client.delete(f"/api/wms/locations/{loc['loc_id']}", headers=admin_h)
    assert blocked.status_code == 409, blocked.text
