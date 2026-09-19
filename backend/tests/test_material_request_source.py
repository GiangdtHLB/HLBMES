"""Test 3 bổ sung cho "Đề nghị nhận vật tư" (MaterialRequest):

1) Gắn phiếu với 1 Lệnh nấu (source_type/source_id) — chỉ để tham chiếu/báo cáo — và endpoint
   xem trước (preview) nhu cầu NVL gộp theo vật tư của lệnh đó, dùng để tự động điền sẵn dòng
   khi tạo phiếu (xem services/warehouse.py::preview_source_materials).
2) Snapshot fifo_ok trên từng dòng NGAY LÚC XUẤT (fulfill_request_line/fulfill_all_lines) —
   trước đây phiếu đã xử lý xong không hiện được cảnh báo FIFO vì không có gì lưu lại; giờ
   hiện đúng theo trạng thái tồn kho tại thời điểm xuất, không suy đoán lại sau này.
3) source_type chỉ chấp nhận brew_order (xem
   services/warehouse.py::_aggregate_source_material_lines) — module Nấu-Lọc-Chiết cũ
   (filter_master_order) đã xóa hẳn, không còn là 1 lựa chọn source_type nữa."""

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


@pytest.fixture(scope="module")
def lager_product_id(client, admin_h):
    products = client.get("/api/products", headers=admin_h).json()
    return next(p["product_id"] for p in products if p["code"] == "BIA-LAGER")


@pytest.fixture(scope="module")
def lager_beer_type_id(client, admin_h, lager_product_id):
    products = client.get("/api/products", headers=admin_h).json()
    return next(p["beer_type_id"] for p in products if p["product_id"] == lager_product_id)


@pytest.fixture(scope="module")
def lager_recipe_version_id(client, admin_h, lager_product_id, lager_beer_type_id):
    recipes = client.get("/api/recipes", headers=admin_h).json()
    recipe = next(r for r in recipes if r["beer_type_id"] == lager_beer_type_id)
    versions = client.get(f"/api/recipes/{recipe['recipe_id']}/versions", headers=admin_h).json()
    return next(v["version_id"] for v in versions if v["state"] == "effective" and v["product_id"] == lager_product_id)




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

    # Chọn lô ưu tiên (mới hơn) dù còn lô cũ hơn PHẢI có lý do (2026-09-18) — thiếu lý do bị chặn.
    blocked = client.post(f"/api/warehouse/requests/{req['request_id']}/lines/{line_id}/fulfill", headers=thukho_h,
                          json={"lot_id": newer_lot, "quantity": 10, "location_to": "Kho phân xưởng"})
    assert blocked.status_code >= 400
    assert "lý do" in blocked.json()["detail"].lower()

    # Có lý do rồi thì hệ thống KHÔNG chặn, chỉ chụp lại cảnh báo FIFO + lý do để xem sau.
    f = client.post(f"/api/warehouse/requests/{req['request_id']}/lines/{line_id}/fulfill", headers=thukho_h,
                    json={"lot_id": newer_lot, "quantity": 10, "location_to": "Kho phân xưởng",
                          "reason": "Lô cũ đang chờ khách hàng kiểm tra riêng, chưa dùng được"})
    assert f.status_code == 200, f.text

    listed = client.get("/api/warehouse/requests", headers=thukho_h).json()
    row = next(x for x in listed if x["request_id"] == req["request_id"])
    assert row["lines"][0]["fifo_ok"] is False
    assert row["lines"][0]["reason"] == "Lô cũ đang chờ khách hàng kiểm tra riêng, chưa dùng được"
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

    u = client.post(f"/api/warehouse/requests/{req['request_id']}/lines/{line_id}/undo-fulfill", headers=admin_h)
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


def test_fulfill_all_lines_splits_across_multiple_lots_when_oldest_alone_is_short(
        client, admin_h, thukho_h, vanhanh_h):
    """Regression 2026-09-18: bản cũ của fulfill_all_lines lọc `MaterialLot.quantity >=
    line.quantity` TRƯỚC KHI tìm lô cũ nhất — nếu lô THẬT SỰ cũ nhất còn hàng nhưng không đủ 1
    mình, nó bị loại thẳng, hệ thống nhảy sang lô MỚI HƠN (dù cộng lô cũ + lô mới vẫn đủ) rồi tự
    gắn fifo_ok=False. Giờ phải LẤY HẾT lô cũ nhất trước, thiếu bao nhiêu lấy tiếp lô cũ kế tiếp
    (mirror dispense.py._plan_consume) — kết quả phải dùng CẢ 2 lô và fifo_ok=True."""
    mat_id = _create_material(client, admin_h, "FIFO-SPLIT-MAT")
    old_lot_id = _receive(client, thukho_h, "LOT-SPLIT-OLD", mat_id, 3)
    new_lot_id = _receive(client, thukho_h, "LOT-SPLIT-NEW", mat_id, 50)

    r = client.post("/api/warehouse/requests", headers=vanhanh_h,
                    json={"lines": [{"material_id": mat_id, "quantity": 10, "uom": "kg"}]})
    req = r.json()

    fa = client.post(f"/api/warehouse/requests/{req['request_id']}/fulfill-all", headers=thukho_h, json={})
    assert fa.status_code == 200, fa.text
    assert len(fa.json()["fulfilled"]) == 1
    assert fa.json()["skipped"] == []

    listed = client.get("/api/warehouse/requests", headers=thukho_h).json()
    row = next(x for x in listed if x["request_id"] == req["request_id"])
    line = row["lines"][0]
    assert line["fifo_ok"] is True
    assert sorted(line["fulfilled_lot_codes"]) == ["LOT-SPLIT-NEW", "LOT-SPLIT-OLD"]

    lots = {l["lot_id"]: l for l in client.get("/api/lots", headers=thukho_h).json()}
    # Lô cũ chuyển NGUYÊN dòng sang Kho phân xưởng (lấy đúng hết 3kg, không tách dòng vì chuyển
    # hết tồn — xem _transfer_lot), lô mới chỉ mất đúng phần còn thiếu (7kg), không bị bỏ qua.
    assert lots[old_lot_id]["quantity"] == 3
    assert lots[old_lot_id]["location"] == "Kho phân xưởng"
    assert lots[new_lot_id]["quantity"] == 43


def test_fulfill_all_lines_skips_line_needing_fifo_reason_without_blocking_others(
        client, admin_h, thukho_h, vanhanh_h):
    """Yêu cầu người dùng 2026-09-18: nếu 1 dòng dùng preferred_lot_id KHÁC lô cũ nhất (sẽ ra
    fifo_ok=False), "Duyệt cả phiếu" phải BỎ QUA đúng dòng đó (không chặn các dòng FIFO đúng khác
    trong cùng phiếu) trừ khi có sẵn lý do trong `reasons`; dòng bị bỏ qua phải duyệt riêng qua
    "Xuất dòng này" kèm lý do."""
    mat_bad = _create_material(client, admin_h, "FIFO-ALLSKIP-BAD")
    mat_ok = _create_material(client, admin_h, "FIFO-ALLSKIP-OK")
    older_lot = _receive(client, thukho_h, "LOT-ALLSKIP-OLD", mat_bad, 50)
    newer_lot = _receive(client, thukho_h, "LOT-ALLSKIP-NEW", mat_bad, 50)
    _receive(client, thukho_h, "LOT-ALLSKIP-OK", mat_ok, 50)

    r = client.post("/api/warehouse/requests", headers=vanhanh_h,
                    json={"lines": [{"material_id": mat_bad, "quantity": 10, "uom": "kg",
                                     "preferred_lot_id": newer_lot},
                                    {"material_id": mat_ok, "quantity": 5, "uom": "kg"}]})
    req = r.json()
    bad_line_id = next(l["line_id"] for l in req["lines"] if l["material_id"] == mat_bad)
    ok_line_id = next(l["line_id"] for l in req["lines"] if l["material_id"] == mat_ok)

    # Thiếu lý do -> dòng mat_bad bị bỏ qua, dòng mat_ok (FIFO đúng, không cần lý do) vẫn xuất.
    fa = client.post(f"/api/warehouse/requests/{req['request_id']}/fulfill-all", headers=thukho_h, json={})
    assert fa.status_code == 200, fa.text
    assert [f["line_id"] for f in fa.json()["fulfilled"]] == [ok_line_id]
    assert [s["line_id"] for s in fa.json()["skipped"]] == [bad_line_id]

    listed = client.get("/api/warehouse/requests", headers=thukho_h).json()
    row = next(x for x in listed if x["request_id"] == req["request_id"])
    by_id = {l["line_id"]: l for l in row["lines"]}
    assert by_id[bad_line_id]["status"] == "pending"
    assert by_id[ok_line_id]["status"] == "fulfilled"

    # Có lý do trong `reasons` -> dòng mat_bad giờ xuất được, fifo_ok=False + lý do lưu lại đúng.
    fa2 = client.post(f"/api/warehouse/requests/{req['request_id']}/fulfill-all", headers=thukho_h,
                      json={"reasons": {bad_line_id: "Khách chỉ định đúng lô mới do khác biệt bao bì"}})
    assert fa2.status_code == 200, fa2.text
    assert [f["line_id"] for f in fa2.json()["fulfilled"]] == [bad_line_id]
    assert fa2.json()["skipped"] == []

    listed2 = client.get("/api/warehouse/requests", headers=thukho_h).json()
    row2 = next(x for x in listed2 if x["request_id"] == req["request_id"])
    bad_line = next(l for l in row2["lines"] if l["line_id"] == bad_line_id)
    assert bad_line["status"] == "fulfilled"
    assert bad_line["fifo_ok"] is False
    assert bad_line["reason"] == "Khách chỉ định đúng lô mới do khác biệt bao bì"


def test_fulfill_request_line_rejects_lot_not_yet_received_as_of_requested_date(
        client, admin_h, thukho_h, vanhanh_h):
    """Regression 2026-09-18 (báo cáo thật trên production mes-dma.biahalong.com, vật tư 2NP09):
    trước đây fulfill_request_line/fulfill_all_lines chỉ tra MaterialLot.quantity > 0 HIỆN TẠI để
    chọn lô nguồn, không so với `req.requested_receipt_date` — cho phép 1 lô Nhập kho SAU đó vẫn
    bị gán vào 1 giao dịch khai hiệu lực SỚM HƠN ngày lô đó thực sự về kho. Giờ phải chặn cứng."""
    from datetime import timedelta
    from app.common import utcnow

    mat_id = _create_material(client, admin_h, "ASOF-REJECT-MAT")
    now = utcnow()
    received_at = (now - timedelta(days=3)).isoformat()
    r = client.post("/api/warehouse/receive", headers=thukho_h,
                    json={"lot_code": "LOT-ASOF-LATE", "material_id": mat_id, "quantity": 50,
                          "uom": "kg", "location": "Kho công ty", "received_at": received_at})
    assert r.status_code == 200, r.text
    lot_id = r.json()["lot_id"]

    requested_receipt_date = (now - timedelta(days=6)).isoformat()   # 3 ngày TRƯỚC khi lô về kho
    req = client.post("/api/warehouse/requests", headers=vanhanh_h,
                      json={"lines": [{"material_id": mat_id, "quantity": 10, "uom": "kg"}],
                           "requested_receipt_date": requested_receipt_date}).json()
    line_id = req["lines"][0]["line_id"]

    blocked = client.post(f"/api/warehouse/requests/{req['request_id']}/lines/{line_id}/fulfill",
                          headers=thukho_h,
                          json={"lot_id": lot_id, "quantity": 10, "location_to": "Kho phân xưởng"})
    assert blocked.status_code >= 400, blocked.text
    assert "chưa đủ tồn" in blocked.json()["detail"].lower()

    lots = {l["lot_id"]: l["quantity"] for l in client.get("/api/lots", headers=thukho_h).json()}
    assert lots[lot_id] == 50   # không bị trừ tồn dù bị chặn giữa đường


def test_fulfill_all_lines_skips_line_when_only_lot_not_yet_received_as_of_requested_date(
        client, admin_h, thukho_h, vanhanh_h):
    """Cùng bug trên nhưng qua đường "Duyệt cả phiếu" (tự chọn lô, không chỉ định tay) — dòng phải
    bị BỎ QUA (skipped) thay vì lặng lẽ dùng lô chưa kịp về kho."""
    from datetime import timedelta
    from app.common import utcnow

    mat_id = _create_material(client, admin_h, "ASOF-ALLSKIP-MAT")
    now = utcnow()
    received_at = (now - timedelta(days=3)).isoformat()
    r = client.post("/api/warehouse/receive", headers=thukho_h,
                    json={"lot_code": "LOT-ASOF-ALLSKIP", "material_id": mat_id, "quantity": 50,
                          "uom": "kg", "location": "Kho công ty", "received_at": received_at})
    assert r.status_code == 200, r.text
    lot_id = r.json()["lot_id"]

    requested_receipt_date = (now - timedelta(days=6)).isoformat()
    req = client.post("/api/warehouse/requests", headers=vanhanh_h,
                      json={"lines": [{"material_id": mat_id, "quantity": 10, "uom": "kg"}],
                           "requested_receipt_date": requested_receipt_date}).json()
    line_id = req["lines"][0]["line_id"]

    fa = client.post(f"/api/warehouse/requests/{req['request_id']}/fulfill-all", headers=thukho_h, json={})
    assert fa.status_code == 200, fa.text
    assert fa.json()["fulfilled"] == []
    assert [s["line_id"] for s in fa.json()["skipped"]] == [line_id]

    lots = {l["lot_id"]: l["quantity"] for l in client.get("/api/lots", headers=thukho_h).json()}
    assert lots[lot_id] == 50


def test_fulfill_request_line_allows_lot_received_before_requested_date(
        client, admin_h, thukho_h, vanhanh_h):
    """Đối chứng: lô ĐÃ về kho trước ngày đề nghị nhận kho thì vẫn xuất bình thường — không bị
    chặn nhầm bởi kiểm tra as-of mới thêm."""
    from datetime import timedelta
    from app.common import utcnow

    mat_id = _create_material(client, admin_h, "ASOF-ALLOW-MAT")
    now = utcnow()
    received_at = (now - timedelta(days=6)).isoformat()
    r = client.post("/api/warehouse/receive", headers=thukho_h,
                    json={"lot_code": "LOT-ASOF-ALLOW", "material_id": mat_id, "quantity": 50,
                          "uom": "kg", "location": "Kho công ty", "received_at": received_at})
    assert r.status_code == 200, r.text
    lot_id = r.json()["lot_id"]

    requested_receipt_date = (now - timedelta(days=3)).isoformat()   # SAU ngày lô về kho -> hợp lệ
    req = client.post("/api/warehouse/requests", headers=vanhanh_h,
                      json={"lines": [{"material_id": mat_id, "quantity": 10, "uom": "kg"}],
                           "requested_receipt_date": requested_receipt_date}).json()
    line_id = req["lines"][0]["line_id"]

    f = client.post(f"/api/warehouse/requests/{req['request_id']}/lines/{line_id}/fulfill",
                    headers=thukho_h,
                    json={"lot_id": lot_id, "quantity": 10, "location_to": "Kho phân xưởng"})
    assert f.status_code == 200, f.text

