"""Test 3 bổ sung cho "Đề nghị nhận vật tư" (MaterialRequest):

1) Gắn phiếu với 1 Lệnh nấu/Lệnh lọc lớn (source_type/source_id) — chỉ để tham chiếu/báo
   cáo — và endpoint xem trước (preview) nhu cầu NVL gộp theo vật tư của lệnh đó, dùng để tự
   động điền sẵn dòng khi tạo phiếu (xem services/warehouse.py::preview_source_materials).
2) Snapshot fifo_ok trên từng dòng NGAY LÚC XUẤT (fulfill_request_line/fulfill_all_lines) —
   trước đây phiếu đã xử lý xong không hiện được cảnh báo FIFO vì không có gì lưu lại; giờ
   hiện đúng theo trạng thái tồn kho tại thời điểm xuất, không suy đoán lại sau này.
3) "Lệnh SX (ERP)" (production_order) cũng là 1 nguồn hợp lệ song song brew_order/
   filter_master_order (xem services/warehouse.py::_aggregate_source_material_lines)."""

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
def thukho_h(client):
    return _login(client, "thukho", "123456")


@pytest.fixture(scope="module")
def vanhanh_h(client):
    return _login(client, "vanhanh", "123456")


def _create_material(client, admin_h, code):
    r = client.post("/api/materials", headers=admin_h,
                    json={"code": code, "name": f"Vật tư {code}", "uom": "kg", "category": "other"})
    assert r.status_code == 201, r.text
    return r.json()["material_id"]


def _receive(client, thukho_h, lot_code, material_id, quantity, location="Kho công ty"):
    r = client.post("/api/warehouse/receive", headers=thukho_h,
                    json={"lot_code": lot_code, "material_id": material_id, "quantity": quantity,
                          "uom": "kg", "location": location})
    assert r.status_code == 200, r.text
    return r.json()["lot_id"]


def _a_brew_order_with_lines(client, admin_h, order_code, mat_id, qty_total):
    r = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": order_code, "auto_from_bom": False, "planned_volume_hl": 100,
        "lines": [
            {"stt_label": "A", "is_header": True, "material_name": "Nguyên liệu chính"},
            {"stt_label": "1", "material_id": mat_id, "uom": "kg",
             "qty_per_batch": qty_total, "qty_total": qty_total},
        ],
    })
    assert r.status_code == 201, r.text
    return r.json()["brew_order_id"]


def _setup_ferment(client, admin_h, vanhanh_h, suffix):
    ob = client.post("/api/brewing/orders", headers=admin_h,
                     json={"order_code": f"LN-{suffix}", "auto_from_bom": False, "planned_volume_hl": 100})
    assert ob.status_code == 201, ob.text
    order_id = ob.json()["brew_order_id"]
    b = client.post("/api/brewing/brews", headers=vanhanh_h,
                    json={"brew_code": f"BR-{suffix}", "wort_type": "Dịch test", "volume_hl": 100,
                          "lm_code": f"LM-{suffix}", "tank_lm": f"T-{suffix}", "brew_order_id": order_id})
    assert b.status_code == 201, b.text
    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment = next(f for f in ferments if f["lm_code"] == f"LM-{suffix}")
    ok = client.post(f"/api/brewing/ferments/{ferment['ferment_id']}/approve", headers=admin_h)
    assert ok.status_code == 200, ok.text
    return ferment["ferment_id"]


def _a_filter_master_order_with_lines(client, admin_h, vanhanh_h, suffix, mat_id, qty_each):
    f1 = _setup_ferment(client, admin_h, vanhanh_h, f"{suffix}-A")
    f2 = _setup_ferment(client, admin_h, vanhanh_h, f"{suffix}-B")
    payload = {"order_code": f"LOC-{suffix}", "children": [
        {"blend_mode": "khong_phoi", "tanks": [{"ferment_id": f1, "planned_v_dich_hl": 50}],
         "volume_tolerance_hl": 0, "lines": [{"material_id": mat_id, "quantity": qty_each}]},
        {"blend_mode": "khong_phoi", "tanks": [{"ferment_id": f2, "planned_v_dich_hl": 50}],
         "volume_tolerance_hl": 0, "lines": [{"material_id": mat_id, "quantity": qty_each}]},
    ]}
    r = client.post("/api/brewing/filter-master-orders", headers=admin_h, json=payload)
    assert r.status_code == 201, r.text
    return r.json()["filter_master_order_id"]


@pytest.fixture(scope="module")
def lager_product_id(client, admin_h):
    products = client.get("/api/products", headers=admin_h).json()
    return next(p["product_id"] for p in products if p["code"] == "BIA-LAGER")


@pytest.fixture(scope="module")
def lager_recipe_version_id(client, admin_h, lager_product_id):
    products = client.get("/api/products", headers=admin_h).json()
    beer_type_id = next(p["beer_type_id"] for p in products if p["product_id"] == lager_product_id)
    recipes = client.get("/api/recipes", headers=admin_h).json()
    recipe = next(r for r in recipes if r["beer_type_id"] == beer_type_id)
    versions = client.get(f"/api/recipes/{recipe['recipe_id']}/versions", headers=admin_h).json()
    return next(v["version_id"] for v in versions if v["state"] == "effective" and v["product_id"] == lager_product_id)


def _a_production_order(client, admin_h, code, product_id, recipe_version_id, planned_batch_count=1):
    r = client.post("/api/orders", headers=admin_h, json={
        "order_code": code, "product_id": product_id, "planned_qty": 100, "uom": "L",
        "recipe_version_id": recipe_version_id, "planned_batch_count": planned_batch_count})
    assert r.status_code == 201, r.text
    return r.json()["order_id"]


def test_preview_source_materials_brew_order_skips_header_row(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "SRC-BREW-MAT")
    _receive(client, thukho_h, "LOT-SRCPRE-01", mat_id, 50)
    order_id = _a_brew_order_with_lines(client, admin_h, "LN-SRCPRE01", mat_id, qty_total=12.5)

    r = client.get("/api/warehouse/requests/source-preview", headers=admin_h,
                   params={"source_type": "brew_order", "source_id": order_id})
    assert r.status_code == 200, r.text
    lines = r.json()
    assert len(lines) == 1
    assert lines[0]["material_id"] == mat_id
    assert lines[0]["material_code"] == "SRC-BREW-MAT"
    assert lines[0]["quantity"] == 12.5


def test_preview_source_materials_filter_master_order_sums_across_children(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "SRC-FILT-MAT")
    _receive(client, thukho_h, "LOT-SRCFILT-01", mat_id, 100)
    master_id = _a_filter_master_order_with_lines(client, admin_h, vanhanh_h, "SRCPRE01", mat_id, qty_each=3)

    r = client.get("/api/warehouse/requests/source-preview", headers=admin_h,
                   params={"source_type": "filter_master_order", "source_id": master_id})
    assert r.status_code == 200, r.text
    lines = r.json()
    assert len(lines) == 1
    assert lines[0]["material_id"] == mat_id
    assert lines[0]["quantity"] == 6   # 3 + 3 gộp từ 2 lệnh nhỏ


def test_preview_source_materials_brew_order_surfaces_group_line_instead_of_dropping(client, admin_h, thukho_h):
    """Regression: dòng NVL khai theo Nhóm vật tư thay thế (alt_group_code, material_id=None)
    từng bị BỎ QUA HOÀN TOÀN ở đây (services/warehouse.py::_aggregate_source_material_lines)
    vì code cũ chặn `not l["material_id"]` — giờ phải trả về riêng với is_group=True kèm
    member_material_ids, để frontend cảnh báo thủ kho tự chọn mã cụ thể."""
    m1 = _create_material(client, admin_h, "SRC-GRP-MAT-1")
    m2 = _create_material(client, admin_h, "SRC-GRP-MAT-2")
    _receive(client, thukho_h, "LOT-SRCGRP-01", m1, 500)
    g = client.post("/api/material-alt-groups", headers=admin_h, json={
        "code": "SRC-ALTGRP-01", "name": "Nhóm test nạp lệnh", "unit": "kg",
        "member_material_ids": [m1, m2]}).json()

    products = client.get("/api/products", headers=admin_h).json()
    product = next(p for p in products if p["code"] == "BIA-LAGER")
    product_id = product["product_id"]
    # 1 Loại bia có đúng 1 Recipe (seed.py đã tạo REC-LAGER cho Loại bia của BIA-LAGER) — thêm 1
    # version mới (product_id=product_id) vào chính Recipe đó thay vì tạo Recipe khác (bị chặn
    # bởi unique beer_type_id).
    recipes = client.get("/api/recipes", headers=admin_h).json()
    recipe_id = next(r["recipe_id"] for r in recipes if r["beer_type_id"] == product["beer_type_id"])
    v = client.post(f"/api/recipes/{recipe_id}/versions", headers=admin_h, json={
        "product_id": product_id, "base_qty": 1000, "base_uom": "L",
        "materials": [{"alt_group_code": g["code"], "qty": 500, "uom": "kg"}]}).json()
    for target in ("review", "approved", "effective"):
        t = client.post(f"/api/recipes/versions/{v['version_id']}/transition", headers=admin_h, json={"target": target})
        assert t.status_code == 200, t.text

    order = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": "LN-SRCGRP01", "product_id": product_id, "recipe_version_id": v["version_id"],
        "planned_batch_count": 1, "planned_volume_hl": 100, "volume_tolerance_hl": 0,
        "auto_from_bom": True, "lines": [],
    })
    assert order.status_code == 201, order.text
    order_id = order.json()["brew_order_id"]

    r = client.get("/api/warehouse/requests/source-preview", headers=admin_h,
                   params={"source_type": "brew_order", "source_id": order_id})
    assert r.status_code == 200, r.text
    lines = r.json()
    group_line = next(l for l in lines if l["is_group"])
    assert group_line["material_id"] is None
    assert group_line["group_code"] == g["code"]
    assert set(group_line["member_material_ids"]) == {m1, m2}
    assert group_line["quantity"] == 500


def test_preview_source_materials_brew_order_member_qty_splits_into_separate_lines(client, admin_h, thukho_h):
    """Regression: dòng Nhóm vật tư khai ĐỊNH MỨC RIÊNG từng thành viên (member_qty, VD 2 mã
    tương đương nhưng khác nồng độ — 5kg mã A + 6kg mã B) trước đây bị gộp qua _add_group như
    kiểu nhóm cũ (1 nhu cầu chung 11kg, FIFO coi mã đầu "ăn hết", mã sau báo thừa) — SAI vì cả
    2 mã đều thực sự cần dùng ĐỒNG THỜI với định mức riêng của chính nó. Giờ phải trả về 2 dòng
    RIÊNG BIỆT (is_group=False, có material_id cụ thể), đúng số lượng của từng mã."""
    m1 = _create_material(client, admin_h, "SRC-MQTY-MAT-1")
    m2 = _create_material(client, admin_h, "SRC-MQTY-MAT-2")
    _receive(client, thukho_h, "LOT-SRCMQTY-01", m1, 500)
    _receive(client, thukho_h, "LOT-SRCMQTY-02", m2, 500)
    g = client.post("/api/material-alt-groups", headers=admin_h, json={
        "code": "SRC-MQTY-GRP-01", "name": "Nhóm test định mức riêng", "unit": "kg",
        "member_material_ids": [m1, m2], "selection_mode": "multi"}).json()

    products = client.get("/api/products", headers=admin_h).json()
    product = next(p for p in products if p["code"] == "BIA-LAGER")
    product_id = product["product_id"]
    recipes = client.get("/api/recipes", headers=admin_h).json()
    recipe_id = next(r["recipe_id"] for r in recipes if r["beer_type_id"] == product["beer_type_id"])
    v = client.post(f"/api/recipes/{recipe_id}/versions", headers=admin_h, json={
        "product_id": product_id, "base_qty": 1000, "base_uom": "L",
        "materials": [{"alt_group_code": g["code"], "uom": "kg",
                      "member_qty": [{"material_code": "SRC-MQTY-MAT-1", "qty": 5},
                                    {"material_code": "SRC-MQTY-MAT-2", "qty": 6}]}]}).json()
    for target in ("review", "approved", "effective"):
        t = client.post(f"/api/recipes/versions/{v['version_id']}/transition", headers=admin_h, json={"target": target})
        assert t.status_code == 200, t.text

    order = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": "LN-SRCMQTY01", "product_id": product_id, "recipe_version_id": v["version_id"],
        "planned_batch_count": 1, "planned_volume_hl": 100, "volume_tolerance_hl": 0,
        "auto_from_bom": True, "lines": [],
        "material_qty_overrides": {"0": {"selected_material_codes": ["SRC-MQTY-MAT-1", "SRC-MQTY-MAT-2"]}},
    })
    assert order.status_code == 201, order.text
    order_id = order.json()["brew_order_id"]

    r = client.get("/api/warehouse/requests/source-preview", headers=admin_h,
                   params={"source_type": "brew_order", "source_id": order_id})
    assert r.status_code == 200, r.text
    lines = r.json()
    assert not any(l["is_group"] for l in lines)   # KHÔNG gộp thành 1 dòng nhóm nữa
    by_code = {l["material_code"]: l for l in lines}
    assert by_code["SRC-MQTY-MAT-1"]["quantity"] == 5
    assert by_code["SRC-MQTY-MAT-2"]["quantity"] == 6


def test_preview_source_materials_filter_master_order_surfaces_group_line(client, admin_h, thukho_h, vanhanh_h):
    m1 = _create_material(client, admin_h, "SRC-FGRP-MAT-1")
    m2 = _create_material(client, admin_h, "SRC-FGRP-MAT-2")
    _receive(client, thukho_h, "LOT-SRCFGRP-01", m1, 20)
    g = client.post("/api/material-alt-groups", headers=admin_h, json={
        "code": "SRC-FALTGRP-01", "name": "Nhóm test lọc", "unit": "kg",
        "member_material_ids": [m1, m2]}).json()

    f1 = _setup_ferment(client, admin_h, vanhanh_h, "FGRP-A")
    f2 = _setup_ferment(client, admin_h, vanhanh_h, "FGRP-B")
    payload = {"order_code": "LOC-FGRP01", "children": [
        {"blend_mode": "khong_phoi", "tanks": [{"ferment_id": f1, "planned_v_dich_hl": 50}],
         "volume_tolerance_hl": 0, "lines": [{"alt_group_code": g["code"], "quantity": 3}]},
        {"blend_mode": "khong_phoi", "tanks": [{"ferment_id": f2, "planned_v_dich_hl": 50}],
         "volume_tolerance_hl": 0, "lines": [{"alt_group_code": g["code"], "quantity": 3}]},
    ]}
    r = client.post("/api/brewing/filter-master-orders", headers=admin_h, json=payload)
    assert r.status_code == 201, r.text
    master_id = r.json()["filter_master_order_id"]

    r2 = client.get("/api/warehouse/requests/source-preview", headers=admin_h,
                    params={"source_type": "filter_master_order", "source_id": master_id})
    assert r2.status_code == 200, r2.text
    lines = r2.json()
    group_line = next(l for l in lines if l["is_group"])
    assert group_line["material_id"] is None
    assert group_line["group_code"] == g["code"]
    assert set(group_line["member_material_ids"]) == {m1, m2}
    assert group_line["quantity"] == 6   # 3 + 3 gộp từ 2 lệnh nhỏ


def test_preview_source_materials_invalid_type_rejected(client, admin_h):
    r = client.get("/api/warehouse/requests/source-preview", headers=admin_h,
                   params={"source_type": "bogus", "source_id": "x"})
    assert r.status_code == 409, r.text


def test_preview_source_materials_not_found(client, admin_h):
    r = client.get("/api/warehouse/requests/source-preview", headers=admin_h,
                   params={"source_type": "brew_order", "source_id": "does-not-exist"})
    assert r.status_code == 404, r.text


def test_create_request_with_source_stores_and_shows_label(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "SRC-CREATE-MAT")
    _receive(client, thukho_h, "LOT-SRCCREATE-01", mat_id, 50)
    order_id = _a_brew_order_with_lines(client, admin_h, "LN-SRCCREATE01", mat_id, qty_total=5)

    r = client.post("/api/warehouse/requests", headers=vanhanh_h, json={
        "lines": [{"material_id": mat_id, "quantity": 5, "uom": "kg"}],
        "source_type": "brew_order", "source_id": order_id,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["source_type"] == "brew_order"
    assert body["source_id"] == order_id
    assert body["source_label"] == "Lệnh nấu LN-SRCCREATE01"

    listed = client.get("/api/warehouse/requests", headers=thukho_h).json()
    row = next(x for x in listed if x["request_id"] == body["request_id"])
    assert row["source_label"] == "Lệnh nấu LN-SRCCREATE01"


def test_create_request_source_type_without_id_rejected(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "SRC-NOID-MAT")
    _receive(client, thukho_h, "LOT-SRCNOID-01", mat_id, 50)
    r = client.post("/api/warehouse/requests", headers=vanhanh_h, json={
        "lines": [{"material_id": mat_id, "quantity": 5, "uom": "kg"}],
        "source_type": "brew_order",
    })
    assert r.status_code == 409, r.text


def test_create_request_source_id_not_found(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "SRC-BOGUS-MAT")
    _receive(client, thukho_h, "LOT-SRCBOGUS-01", mat_id, 50)
    r = client.post("/api/warehouse/requests", headers=vanhanh_h, json={
        "lines": [{"material_id": mat_id, "quantity": 5, "uom": "kg"}],
        "source_type": "brew_order", "source_id": "does-not-exist",
    })
    assert r.status_code == 404, r.text


def test_fulfill_line_snapshots_fifo_ok_true_for_oldest_lot(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "FIFO-OK-MAT")
    lot_id = _receive(client, thukho_h, "LOT-FIFOOK-01", mat_id, 50)

    r = client.post("/api/warehouse/requests", headers=vanhanh_h,
                    json={"lines": [{"material_id": mat_id, "quantity": 10, "uom": "kg"}]})
    assert r.status_code == 201, r.text
    req = r.json()
    line_id = req["lines"][0]["line_id"]
    assert req["lines"][0]["fifo_ok"] is None   # còn pending — chưa xuất, chưa có snapshot

    f = client.post(f"/api/warehouse/requests/{req['request_id']}/lines/{line_id}/fulfill", headers=thukho_h,
                    json={"lot_id": lot_id, "quantity": 10, "location_to": "Kho phân xưởng"})
    assert f.status_code == 200, f.text

    listed = client.get("/api/warehouse/requests", headers=thukho_h).json()
    row = next(x for x in listed if x["request_id"] == req["request_id"])
    assert row["lines"][0]["fifo_ok"] is True


def test_fulfill_line_snapshots_fifo_ok_false_when_older_lot_skipped(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "FIFO-BAD-MAT")
    older_lot = _receive(client, thukho_h, "LOT-FIFOBAD-OLD", mat_id, 50)
    newer_lot = _receive(client, thukho_h, "LOT-FIFOBAD-NEW", mat_id, 50)

    r = client.post("/api/warehouse/requests", headers=vanhanh_h,
                    json={"lines": [{"material_id": mat_id, "quantity": 10, "uom": "kg",
                                    "preferred_lot_id": newer_lot}]})
    assert r.status_code == 201, r.text
    req = r.json()
    line_id = req["lines"][0]["line_id"]

    # Thủ kho vẫn chọn đúng lô ưu tiên (mới hơn) dù còn lô cũ hơn — hệ thống KHÔNG chặn,
    # chỉ chụp lại cảnh báo FIFO để xem sau.
    f = client.post(f"/api/warehouse/requests/{req['request_id']}/lines/{line_id}/fulfill", headers=thukho_h,
                    json={"lot_id": newer_lot, "quantity": 10, "location_to": "Kho phân xưởng"})
    assert f.status_code == 200, f.text

    listed = client.get("/api/warehouse/requests", headers=thukho_h).json()
    row = next(x for x in listed if x["request_id"] == req["request_id"])
    assert row["lines"][0]["fifo_ok"] is False
    # Xuất 10/50 (một phần) — transfer() tách lô mới mang đúng 10 sang Kho phân xưởng (xem
    # services/warehouse.py::transfer split-lot), nên fulfilled_lot_id KHÔNG còn bằng newer_lot
    # gốc nữa; xác nhận đúng nguồn (newer_lot, không phải older_lot) qua tồn còn lại của nó.
    fulfilled_lot_id = row["lines"][0]["fulfilled_lot_id"]
    assert fulfilled_lot_id != newer_lot
    lots = client.get("/api/lots", headers=thukho_h).json()
    fulfilled_lot = next(l for l in lots if l["lot_id"] == fulfilled_lot_id)
    assert fulfilled_lot["quantity"] == 10
    remaining_newer = next(l for l in lots if l["lot_id"] == newer_lot)
    assert remaining_newer["quantity"] == 40


def test_undo_fulfill_resets_fifo_ok_to_none(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "FIFO-UNDO-MAT")
    lot_id = _receive(client, thukho_h, "LOT-FIFOUNDO-01", mat_id, 50)

    r = client.post("/api/warehouse/requests", headers=vanhanh_h,
                    json={"lines": [{"material_id": mat_id, "quantity": 10, "uom": "kg"}]})
    req = r.json()
    line_id = req["lines"][0]["line_id"]
    client.post(f"/api/warehouse/requests/{req['request_id']}/lines/{line_id}/fulfill", headers=thukho_h,
               json={"lot_id": lot_id, "quantity": 10, "location_to": "Kho phân xưởng"})

    u = client.post(f"/api/warehouse/requests/{req['request_id']}/lines/{line_id}/undo-fulfill", headers=thukho_h)
    assert u.status_code == 200, u.text
    assert u.json()["fifo_ok"] is None


def test_fulfill_all_lines_snapshots_fifo_ok(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "FIFO-ALL-MAT")
    lot_id = _receive(client, thukho_h, "LOT-FIFOALL-01", mat_id, 50)

    r = client.post("/api/warehouse/requests", headers=vanhanh_h,
                    json={"lines": [{"material_id": mat_id, "quantity": 10, "uom": "kg"}]})
    req = r.json()

    fa = client.post(f"/api/warehouse/requests/{req['request_id']}/fulfill-all", headers=thukho_h, json={})
    assert fa.status_code == 200, fa.text
    assert len(fa.json()["fulfilled"]) == 1

    listed = client.get("/api/warehouse/requests", headers=thukho_h).json()
    row = next(x for x in listed if x["request_id"] == req["request_id"])
    assert row["lines"][0]["fifo_ok"] is True
    # SL xin (10) < SL lô gốc (50) -> transfer() tách lô mới ở đích (xem services/warehouse.py
    # ::transfer partial-split, task #803) — fulfilled_lot_id là lô TÁCH, không còn là lot_id gốc.
    fulfilled_lot_id = row["lines"][0]["fulfilled_lot_id"]
    assert fulfilled_lot_id != lot_id
    lots = client.get("/api/lots", headers=thukho_h).json()
    fulfilled_lot = next(l for l in lots if l["lot_id"] == fulfilled_lot_id)
    assert fulfilled_lot["quantity"] == 10
    original_lot = next(l for l in lots if l["lot_id"] == lot_id)
    assert original_lot["quantity"] == 40


def test_preview_source_materials_production_order(client, admin_h, lager_product_id, lager_recipe_version_id):
    order_id = _a_production_order(client, admin_h, "PO-SRCPRE01", lager_product_id, lager_recipe_version_id)

    r = client.get("/api/warehouse/requests/source-preview", headers=admin_h,
                   params={"source_type": "production_order", "source_id": order_id})
    assert r.status_code == 200, r.text
    lines = {l["material_name"]: l for l in r.json() if not l["is_group"]}
    assert set(lines.keys()) >= {"Malt Pilsner", "Hoa bia Saaz", "Men Lager W-34/70"}
    assert lines["Malt Pilsner"]["quantity"] == pytest.approx(1200)


def test_preview_source_materials_production_order_not_found(client, admin_h):
    r = client.get("/api/warehouse/requests/source-preview", headers=admin_h,
                   params={"source_type": "production_order", "source_id": "does-not-exist"})
    assert r.status_code == 404, r.text


def test_create_request_with_production_order_source_stores_and_shows_label(
        client, admin_h, thukho_h, vanhanh_h, lager_product_id, lager_recipe_version_id):
    order_id = _a_production_order(client, admin_h, "PO-SRCCREATE01", lager_product_id, lager_recipe_version_id)
    mat_id = _create_material(client, admin_h, "SRC-PO-CREATE-MAT")
    _receive(client, thukho_h, "LOT-SRCPOCREATE-01", mat_id, 50)

    r = client.post("/api/warehouse/requests", headers=vanhanh_h, json={
        "lines": [{"material_id": mat_id, "quantity": 5, "uom": "kg"}],
        "source_type": "production_order", "source_id": order_id,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["source_type"] == "production_order"
    assert body["source_id"] == order_id
    assert body["source_label"] == "Lệnh SX (ERP) PO-SRCCREATE01"
