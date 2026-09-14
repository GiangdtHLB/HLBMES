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


def test_dispense_summary_marks_free_dispense_outside_recipe(client, admin_h):
    """Cấp cho mẻ 1 vật tư KHÔNG có trong công thức (chỉ khả dĩ qua "Cấp 1 vật tư" tự do) phải
    hiện is_free=True kèm material_name/uom tra được — trước đây batch_dispense_summary() BỎ
    QUA hoàn toàn các dòng này (chỉ duyệt bom.compare_batch()["lines"], không đọc "extras")."""
    in_recipe_id, in_recipe_code = _new_material(client, admin_h, "SUM_IN")
    free_id, free_code = _new_material(client, admin_h, "SUM_FREE")
    _receive_lot(client, admin_h, in_recipe_id, 20, "Kho phân xưởng")
    _receive_lot(client, admin_h, free_id, 20, "Kho phân xưởng")

    version_id = _recipe_version(client, admin_h, "SUM01", in_recipe_code, qty=10, base_qty=100)
    batch_id = _new_batch(client, admin_h, version_id, planned_qty=100, suffix="SUM01")

    r = client.post(f"/api/dispense/{batch_id}", headers=admin_h, json={
        "lines": [{"material_code": in_recipe_code, "quantity": 10},
                 {"material_code": free_code, "quantity": 3}],
    })
    assert r.status_code == 200, r.text

    summary = client.get(f"/api/dispense/{batch_id}/summary", headers=admin_h).json()
    by_code = {l["material_code"]: l for l in summary}
    assert by_code[in_recipe_code]["is_free"] is False
    assert by_code[in_recipe_code]["planned"] == 10.0

    free_row = by_code[free_code]
    assert free_row["is_free"] is True
    assert free_row["planned"] is None
    assert free_row["actual"] == 3.0
    assert free_row["material_name"] == f"Vật tư test SUM_FREE"
    assert free_row["uom"] == "kg"
    assert free_row["status"] == "ngoai_bom"

    bom = client.get(f"/api/batches/{batch_id}/bom", headers=admin_h).json()
    bom_by_code = {l["material_code"]: l for l in bom["lines"]}
    assert bom_by_code[free_code]["is_free"] is True
    assert bom_by_code[in_recipe_code]["is_free"] is False
