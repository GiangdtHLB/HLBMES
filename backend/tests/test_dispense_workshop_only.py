"""Cấp liệu (Mẻ sản xuất) CHỈ được lấy từ Kho phân xưởng — kể cả "Cấp 1 vật tư" (tự chọn lô
theo FEFO, không cho chọn lô thủ công) và tiêu thụ trực tiếp qua POST /batches/{id}/consume.

Bug thực tế đã gặp (yêu cầu người dùng 2026-09-14, phát hiện qua đối chiếu "Xem tồn kho" ≠
"Xuất theo đề nghị" trên server thật): services/dispense.py::_plan_consume, khi KHÔNG chỉ định
lot_id (nhánh "Cấp 1 vật tư"), gọi `_fefo_lots()` (mọi kho) thay vì `_workshop_fefo_lots()` (chỉ
Kho phân xưởng) — khiến 41 mẻ nấu thử nghiệm vô tình rút NVL thẳng từ Kho công ty. Đã sửa ở
services/batches.py::consume_lot (chặn gốc, áp dụng cho mọi đường vào) + services/dispense.py
(chặn sớm ở _plan_consume khi chỉ định lot_id, và đổi nhánh tự động sang _workshop_fefo_lots).

Cũng test cột "Cấp tự do?" mới (is_free) trên services/dispense.py::batch_dispense_summary —
vật tư tiêu thụ ngoài công thức (BOM) phải hiện is_free=True kèm material_name/uom tra được.
"""

import os
import tempfile
from datetime import timedelta

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["MES_DATABASE_URL"] = f"sqlite:///{_TMP.name}"
os.environ["MES_DEV_HEADER_AUTH"] = "0"
os.environ["MES_RL_ENABLED"] = "0"
os.environ["MES_ADMIN_PASSWORD"] = "AdminTest123"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import seed as seed_mod
from app.common import utcnow


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


def _new_material(client, admin_h, suffix):
    r = client.post("/api/materials", headers=admin_h,
                    json={"code": f"WSO-{suffix}", "name": f"Vật tư test {suffix}", "uom": "kg"})
    assert r.status_code == 201, r.text
    return r.json()["material_id"], r.json()["code"]


def _receive_lot(client, admin_h, material_id, qty, location, days_to_expiry=30):
    r = client.post("/api/warehouse/receive", headers=admin_h, json={
        "material_id": material_id, "quantity": qty, "uom": "kg", "location": location,
        "expiry": (utcnow() + timedelta(days=days_to_expiry)).isoformat(),
    })
    assert r.status_code == 200, r.text
    return r.json()["lot_id"]


def _recipe_version(client, admin_h, suffix, material_code, qty, base_qty=100):
    bt = client.post("/api/beer-types", headers=admin_h,
                     json={"code": f"BT-WSO-{suffix}", "name": f"Loại test {suffix}"})
    assert bt.status_code == 201, bt.text
    r = client.post("/api/recipes", headers=admin_h,
                    json={"code": f"CT-WSO-{suffix}", "name": "Test workshop-only",
                         "beer_type_id": bt.json()["beer_type_id"]})
    assert r.status_code == 201, r.text
    recipe_id = r.json()["recipe_id"]
    prod = client.post("/api/products", headers=admin_h,
                       json={"code": f"PRD-WSO-{suffix}", "name": f"Dịch test {suffix}", "uom": "L",
                            "beer_type_id": bt.json()["beer_type_id"]})
    assert prod.status_code == 201, prod.text
    v = client.post(f"/api/recipes/{recipe_id}/versions", headers=admin_h,
                    json={"base_qty": base_qty, "base_uom": "L", "product_id": prod.json()["product_id"],
                         "materials": [{"material_code": material_code, "qty": qty, "uom": "kg"}]})
    assert v.status_code == 201, v.text
    version_id = v.json()["version_id"]
    for target in ("review", "approved", "effective"):
        t = client.post(f"/api/recipes/versions/{version_id}/transition", headers=admin_h,
                        json={"target": target})
        assert t.status_code == 200, t.text
    return version_id


def _new_batch(client, admin_h, version_id, planned_qty, suffix, allow_shortage=False):
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": version_id,
                         "planned_qty": planned_qty, "allow_shortage": allow_shortage})
    assert b.status_code == 201, b.text
    return b.json()["batch_id"]


def test_dispense_auto_fefo_never_picks_company_lot_even_if_earlier(client, admin_h):
    """Lô Kho công ty hết hạn SỚM HƠN (đáng lẽ đứng đầu FEFO) vẫn KHÔNG được "Cấp 1 vật tư" tự
    động chọn — chỉ lô Kho phân xưởng (dù hết hạn muộn hơn) mới hợp lệ. Đây đúng kịch bản lỗi
    thật đã xảy ra trên server (TD-KCT-13 và 14 lô khác bị rút nhầm từ Kho công ty)."""
    material_id, code = _new_material(client, admin_h, "AUTO01")
    company_lot = _receive_lot(client, admin_h, material_id, 100, "Kho công ty", days_to_expiry=5)
    workshop_lot = _receive_lot(client, admin_h, material_id, 20, "Kho phân xưởng", days_to_expiry=60)

    version_id = _recipe_version(client, admin_h, "AUTO01", code, qty=10, base_qty=100)
    batch_id = _new_batch(client, admin_h, version_id, planned_qty=100, suffix="AUTO01")

    ok = client.post(f"/api/dispense/{batch_id}", headers=admin_h,
                     json={"lines": [{"material_code": code, "quantity": 10}]})
    assert ok.status_code == 200, ok.text
    assert ok.json()["lines"][0]["lot_id"] == workshop_lot

    lots = {l["lot_id"]: l["quantity"] for l in client.get("/api/lots", headers=admin_h).json()}
    assert lots[workshop_lot] == 10.0
    assert lots[company_lot] == 100.0   # KHÔNG bị đụng tới


def test_dispense_auto_fefo_fails_when_only_company_stock_exists(client, admin_h):
    material_id, code = _new_material(client, admin_h, "AUTO02")
    _receive_lot(client, admin_h, material_id, 100, "Kho công ty")

    version_id = _recipe_version(client, admin_h, "AUTO02", code, qty=10, base_qty=100)
    batch_id = _new_batch(client, admin_h, version_id, planned_qty=100, suffix="AUTO02", allow_shortage=True)

    r = client.post(f"/api/dispense/{batch_id}", headers=admin_h,
                    json={"lines": [{"material_code": code, "quantity": 10}]})
    assert r.status_code == 409, r.text
    assert "Không đủ lô khả dụng" in r.json()["detail"]


def test_dispense_explicit_lot_id_rejected_for_company_lot(client, admin_h):
    material_id, code = _new_material(client, admin_h, "PICK01")
    company_lot = _receive_lot(client, admin_h, material_id, 50, "Kho công ty")

    version_id = _recipe_version(client, admin_h, "PICK01", code, qty=10, base_qty=100)
    batch_id = _new_batch(client, admin_h, version_id, planned_qty=100, suffix="PICK01", allow_shortage=True)

    r = client.post(f"/api/dispense/{batch_id}", headers=admin_h,
                    json={"lines": [{"material_code": code, "lot_id": company_lot, "quantity": 10}]})
    assert r.status_code == 409, r.text
    assert "Kho phân xưởng" in r.json()["detail"]

    lots = {l["lot_id"]: l["quantity"] for l in client.get("/api/lots", headers=admin_h).json()}
    assert lots[company_lot] == 50.0   # chặn TRƯỚC khi trừ (planning-time), không trừ 1 phần


def test_consume_endpoint_rejects_company_lot(client, admin_h):
    material_id, code = _new_material(client, admin_h, "CONS01")
    company_lot = _receive_lot(client, admin_h, material_id, 50, "Kho công ty")
    version_id = _recipe_version(client, admin_h, "CONS01", code, qty=5, base_qty=100)
    batch_id = _new_batch(client, admin_h, version_id, planned_qty=100, suffix="CONS01", allow_shortage=True)
    for target in ("ready", "running"):
        t = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": target})
        assert t.status_code == 200, t.text

    r = client.post(f"/api/batches/{batch_id}/consume", headers=admin_h,
                    json={"lot_id": company_lot, "quantity": 5})
    assert r.status_code == 409, r.text
    assert "Kho phân xưởng" in r.json()["detail"]


def test_backflush_never_picks_company_lot(client, admin_h):
    material_id, code = _new_material(client, admin_h, "BKF01")
    company_lot = _receive_lot(client, admin_h, material_id, 100, "Kho công ty", days_to_expiry=5)
    workshop_lot = _receive_lot(client, admin_h, material_id, 20, "Kho phân xưởng", days_to_expiry=60)

    version_id = _recipe_version(client, admin_h, "BKF01", code, qty=10, base_qty=100)
    batch_id = _new_batch(client, admin_h, version_id, planned_qty=100, suffix="BKF01")

    r = client.post(f"/api/dispense/{batch_id}/backflush", headers=admin_h,
                    json={"produced_qty": 100})
    assert r.status_code == 200, r.text

    lots = {l["lot_id"]: l["quantity"] for l in client.get("/api/lots", headers=admin_h).json()}
    assert lots[workshop_lot] == 10.0
    assert lots[company_lot] == 100.0


def test_dispense_summary_marks_free_dispense_via_cap_1_vat_tu_note(client, admin_h):
    """"Cấp tự do" bám theo CÁCH cấp (Dispense.note="Cấp tự do", đúng note nút "Cấp 1 vật tư"
    dp_go ghi — xem views_ext.js), KHÔNG PHẢI theo việc vật tư có nằm trong công thức hay không
    (yêu cầu người dùng làm rõ 2026-09-14: dropdown "Cấp 1 vật tư" chỉ cho chọn vật tư CÓ trong
    BOM — 1 vật tư có định mức vẫn hiện "Cấp tự do" nếu có ít nhất 1 lần cấp qua nút đó, kể cả
    đã có phần khác cấp qua "Áp dụng gợi ý"). Vật tư ngoài công thức hoàn toàn (chỉ khả dĩ qua
    API trực tiếp) vẫn phải hiện đúng material_name/uom (trước đây bảng này bỏ qua hẳn — không
    đọc compare_batch()["extras"])."""
    in_recipe_id, in_recipe_code = _new_material(client, admin_h, "SUM_IN")
    mixed_id, mixed_code = _new_material(client, admin_h, "SUM_MIXED")
    free_id, free_code = _new_material(client, admin_h, "SUM_FREE")
    lot_in_recipe = _receive_lot(client, admin_h, in_recipe_id, 20, "Kho phân xưởng")
    _receive_lot(client, admin_h, mixed_id, 20, "Kho phân xưởng")
    _receive_lot(client, admin_h, free_id, 20, "Kho phân xưởng")

    bt = client.post("/api/beer-types", headers=admin_h, json={"code": "BT-SUM01", "name": "Loại SUM01"})
    assert bt.status_code == 201, bt.text
    recipe = client.post("/api/recipes", headers=admin_h,
                        json={"code": "CT-SUM01", "name": "Test SUM01", "beer_type_id": bt.json()["beer_type_id"]})
    assert recipe.status_code == 201, recipe.text
    prod = client.post("/api/products", headers=admin_h,
                       json={"code": "PRD-SUM01", "name": "Dich SUM01", "uom": "L",
                            "beer_type_id": bt.json()["beer_type_id"]})
    assert prod.status_code == 201, prod.text
    v = client.post(f"/api/recipes/{recipe.json()['recipe_id']}/versions", headers=admin_h,
                    json={"base_qty": 100, "base_uom": "L", "product_id": prod.json()["product_id"],
                         "materials": [{"material_code": in_recipe_code, "qty": 10, "uom": "kg"},
                                      {"material_code": mixed_code, "qty": 10, "uom": "kg"}]})
    assert v.status_code == 201, v.text
    version_id = v.json()["version_id"]
    for target in ("review", "approved", "effective"):
        t = client.post(f"/api/recipes/versions/{version_id}/transition", headers=admin_h, json={"target": target})
        assert t.status_code == 200, t.text
    batch_id = _new_batch(client, admin_h, version_id, planned_qty=100, suffix="SUM01")

    # in_recipe_code: CHỈ cấp qua "Áp dụng gợi ý" (chỉ định lot_id, note "Cấp theo gợi ý (FEFO)").
    guided = client.post(f"/api/dispense/{batch_id}", headers=admin_h, json={
        "lines": [{"material_code": in_recipe_code, "lot_id": lot_in_recipe, "quantity": 10}],
        "note": "Cấp theo gợi ý (FEFO)",
    })
    assert guided.status_code == 200, guided.text

    # mixed_code: cấp qua "Cấp 1 vật tư" (tự chọn FEFO, note "Cấp tự do") — dù CÓ định mức.
    mixed = client.post(f"/api/dispense/{batch_id}", headers=admin_h, json={
        "lines": [{"material_code": mixed_code, "quantity": 10}], "note": "Cấp tự do",
    })
    assert mixed.status_code == 200, mixed.text

    # free_code: ngoài công thức hoàn toàn, cũng qua "Cấp 1 vật tư" (note "Cấp tự do").
    free = client.post(f"/api/dispense/{batch_id}", headers=admin_h, json={
        "lines": [{"material_code": free_code, "quantity": 3}], "note": "Cấp tự do",
    })
    assert free.status_code == 200, free.text

    summary = client.get(f"/api/dispense/{batch_id}/summary", headers=admin_h).json()
    by_code = {l["material_code"]: l for l in summary}
    assert by_code[in_recipe_code]["is_free"] is False
    assert by_code[in_recipe_code]["planned"] == 10.0

    assert by_code[mixed_code]["is_free"] is True
    assert by_code[mixed_code]["planned"] == 10.0   # vẫn CÓ định mức — chỉ khác ở cách cấp

    free_row = by_code[free_code]
    assert free_row["is_free"] is True
    assert free_row["planned"] is None
    assert free_row["actual"] == 3.0
    assert free_row["material_name"] == "Vật tư test SUM_FREE"
    assert free_row["uom"] == "kg"
    assert free_row["status"] == "ngoai_bom"

    bom = client.get(f"/api/batches/{batch_id}/bom", headers=admin_h).json()
    bom_by_code = {l["material_code"]: l for l in bom["lines"]}
    assert bom_by_code[in_recipe_code]["is_free"] is False
    assert bom_by_code[mixed_code]["is_free"] is True
    assert bom_by_code[free_code]["is_free"] is True


def test_fully_dispensed_map_marks_only_batches_with_full_recipe_coverage(client, admin_h):
    """GET /dispense/fully-dispensed-map — dùng đánh dấu ✓ ở danh sách "Chọn mẻ" (Cấp liệu),
    yêu cầu người dùng 2026-09-14. True chỉ khi MỌI dòng định mức đã đủ (Thực tế >= Định mức
    trong dung sai); mẻ chưa cấp gì hoặc mới cấp 1 phần phải là False."""
    material_id, code = _new_material(client, admin_h, "FULLMAP01")
    _receive_lot(client, admin_h, material_id, 20, "Kho phân xưởng")
    version_id = _recipe_version(client, admin_h, "FULLMAP01", code, qty=10, base_qty=100)

    empty_batch_id = _new_batch(client, admin_h, version_id, planned_qty=100, suffix="FULLMAP_EMPTY")
    full_batch_id = _new_batch(client, admin_h, version_id, planned_qty=100, suffix="FULLMAP_FULL")

    ok = client.post(f"/api/dispense/{full_batch_id}", headers=admin_h,
                     json={"lines": [{"material_code": code, "quantity": 10}]})
    assert ok.status_code == 200, ok.text

    fmap = client.get("/api/dispense/fully-dispensed-map", headers=admin_h).json()
    assert fmap[empty_batch_id] is False
    assert fmap[full_batch_id] is True

    # Mẻ khác vật tư, khai định mức 2 dòng nhưng chỉ cấp 1 -> vẫn False (thiếu 1 dòng).
    material_id2, code2 = _new_material(client, admin_h, "FULLMAP02")
    _receive_lot(client, admin_h, material_id2, 20, "Kho phân xưởng")
    bt = client.post("/api/beer-types", headers=admin_h, json={"code": "BT-FULLMAP02", "name": "Loại FULLMAP02"})
    assert bt.status_code == 201, bt.text
    recipe = client.post("/api/recipes", headers=admin_h,
                        json={"code": "CT-FULLMAP02", "name": "Test partial", "beer_type_id": bt.json()["beer_type_id"]})
    assert recipe.status_code == 201, recipe.text
    prod = client.post("/api/products", headers=admin_h,
                       json={"code": "PRD-FULLMAP02", "name": "Dich FULLMAP02", "uom": "L",
                            "beer_type_id": bt.json()["beer_type_id"]})
    assert prod.status_code == 201, prod.text
    v = client.post(f"/api/recipes/{recipe.json()['recipe_id']}/versions", headers=admin_h,
                    json={"base_qty": 100, "base_uom": "L", "product_id": prod.json()["product_id"],
                         "materials": [{"material_code": code, "qty": 10, "uom": "kg"},
                                      {"material_code": code2, "qty": 5, "uom": "kg"}]})
    assert v.status_code == 201, v.text
    version_id2 = v.json()["version_id"]
    for target in ("review", "approved", "effective"):
        t = client.post(f"/api/recipes/versions/{version_id2}/transition", headers=admin_h, json={"target": target})
        assert t.status_code == 200, t.text
    partial_batch_id = _new_batch(client, admin_h, version_id2, planned_qty=100, suffix="FULLMAP_PARTIAL",
                                  allow_shortage=True)
    ok2 = client.post(f"/api/dispense/{partial_batch_id}", headers=admin_h,
                      json={"lines": [{"material_code": code, "quantity": 10}]})
    assert ok2.status_code == 200, ok2.text

    fmap2 = client.get("/api/dispense/fully-dispensed-map", headers=admin_h).json()
    assert fmap2[partial_batch_id] is False
