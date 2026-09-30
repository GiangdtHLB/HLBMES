"""Xác nhận 1 dòng BOM đang "Chưa dùng" (thực tế = 0) là CHỦ Ý "Không sử dụng" — khác "Chưa
dùng" (mơ hồ, chưa biết sẽ cấp hay không). Xem services/dispense.py::confirm_material_not_used/
unconfirm_material_not_used, services/bom.py::not_used_codes.
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


@pytest.fixture(autouse=True)
def _cleanup_dangling_batches(client, admin_h):
    yield
    batches = client.get("/api/batches", headers=admin_h).json()
    for b in batches:
        if b["state"] in ("planned", "ready", "running", "held"):
            client.post(f"/api/batches/{b['batch_id']}/transition", headers=admin_h,
                        json={"target": "cancelled"})


def _clear_seed_batch_9002(client, admin_h):
    batches = client.get("/api/batches", headers=admin_h).json()
    b9002 = next((b for b in batches if b.get("batch_code") == "9002"), None)
    if b9002 and b9002["state"] in ("running", "held"):
        r = client.post(f"/api/batches/{b9002['batch_id']}/transition", headers=admin_h,
                        json={"target": "cancelled"})
        assert r.status_code == 200, r.text


def _new_material(client, admin_h, suffix):
    r = client.post("/api/materials", headers=admin_h,
                    json={"code": f"NU-{suffix}", "name": f"Vật tư test {suffix}", "uom": "kg"})
    assert r.status_code == 201, r.text
    return r.json()["material_id"], r.json()["code"]


def _recipe_version(client, admin_h, suffix, material_code, qty, base_qty=100):
    bt = client.post("/api/beer-types", headers=admin_h,
                     json={"code": f"BT-NU-{suffix}", "name": f"Loại test {suffix}"})
    assert bt.status_code == 201, bt.text
    r = client.post("/api/recipes", headers=admin_h,
                    json={"code": f"CT-NU-{suffix}", "name": "Test recipe không sử dụng",
                         "beer_type_id": bt.json()["beer_type_id"]})
    assert r.status_code == 201, r.text
    recipe_id = r.json()["recipe_id"]
    prod = client.post("/api/products", headers=admin_h,
                       json={"code": f"PRD-NU-{suffix}", "name": f"Dịch test {suffix}", "uom": "L",
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


def _new_batch(client, admin_h, version_id, planned_qty, suffix):
    _clear_seed_batch_9002(client, admin_h)
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": version_id,
                         "planned_qty": planned_qty, "allow_shortage": True})
    assert b.status_code == 201, b.text
    batch_id = b.json()["batch_id"]
    s = client.post(f"/api/batches/{batch_id}/start", headers=admin_h,
                    json={"start_at": utcnow().isoformat()})
    assert s.status_code == 200, s.text
    return batch_id


def _bom_line(client, admin_h, batch_id, code):
    bom = client.get(f"/api/batches/{batch_id}/bom", headers=admin_h).json()
    return next(l for l in bom["lines"] if l["material_code"] == code)


def test_confirm_then_unconfirm_toggles_status(client, admin_h):
    material_id, code = _new_material(client, admin_h, "TOGGLE01")
    version_id = _recipe_version(client, admin_h, "TOGGLE01", code, qty=5)
    batch_id = _new_batch(client, admin_h, version_id, planned_qty=100, suffix="TOGGLE01")

    line = _bom_line(client, admin_h, batch_id, code)
    assert line["status"] == "chua_dung"

    r = client.post(f"/api/dispense/{batch_id}/materials/{code}/not-used", headers=admin_h)
    assert r.status_code == 200, r.text
    line2 = next(l for l in r.json()["bom"]["lines"] if l["material_code"] == code)
    assert line2["status"] == "khong_su_dung"

    # Vẫn giữ nguyên qua GET riêng (không chỉ trong response của chính lần confirm).
    line3 = _bom_line(client, admin_h, batch_id, code)
    assert line3["status"] == "khong_su_dung"

    # "Gợi ý cấp liệu" không còn gợi ý dòng đã xác nhận không sử dụng.
    sug = client.get(f"/api/dispense/{batch_id}/suggest", headers=admin_h).json()
    assert all(l["material_code"] != code for l in sug["lines"])

    # Bỏ xác nhận -> quay lại "chưa dùng".
    r2 = client.delete(f"/api/dispense/{batch_id}/materials/{code}/not-used", headers=admin_h)
    assert r2.status_code == 200, r2.text
    line4 = _bom_line(client, admin_h, batch_id, code)
    assert line4["status"] == "chua_dung"


def test_cannot_confirm_line_already_dispensed(client, admin_h):
    material_id, code = _new_material(client, admin_h, "USED01")
    version_id = _recipe_version(client, admin_h, "USED01", code, qty=5)
    # Nhận lô TRƯỚC khi tạo/bắt đầu mẻ — _assert_dispensable chỉ cho chọn lô đã thực sự tồn tại
    # ở Kho phân xưởng TÍNH ĐẾN đúng thời điểm mẻ bắt đầu nấu (mirror test_dispense_suggest.py).
    recv = client.post("/api/warehouse/receive", headers=admin_h, json={
        "material_id": material_id, "quantity": 5, "uom": "kg", "location": "Kho phân xưởng"})
    assert recv.status_code == 200, recv.text
    lot_id = recv.json()["lot_id"]
    batch_id = _new_batch(client, admin_h, version_id, planned_qty=100, suffix="USED01")
    disp = client.post(f"/api/dispense/{batch_id}", headers=admin_h,
                       json={"lines": [{"material_code": code, "lot_id": lot_id, "quantity": 5}]})
    assert disp.status_code == 200, disp.text

    r = client.post(f"/api/dispense/{batch_id}/materials/{code}/not-used", headers=admin_h)
    assert r.status_code == 409, r.text


def test_cannot_confirm_material_not_in_bom(client, admin_h):
    material_id, code = _new_material(client, admin_h, "OTHER01")
    other_material_id, other_code = _new_material(client, admin_h, "OTHER02")
    version_id = _recipe_version(client, admin_h, "OTHER01", code, qty=5)
    batch_id = _new_batch(client, admin_h, version_id, planned_qty=100, suffix="OTHER01")

    r = client.post(f"/api/dispense/{batch_id}/materials/{other_code}/not-used", headers=admin_h)
    assert r.status_code == 409, r.text


def test_confirming_all_lines_marks_batch_fully_dispensed(client, admin_h):
    material_id, code = _new_material(client, admin_h, "FULL01")
    version_id = _recipe_version(client, admin_h, "FULL01", code, qty=5)
    batch_id = _new_batch(client, admin_h, version_id, planned_qty=100, suffix="FULL01")

    before = client.get("/api/dispense/fully-dispensed-map", headers=admin_h).json()
    assert before.get(batch_id) is False

    r = client.post(f"/api/dispense/{batch_id}/materials/{code}/not-used", headers=admin_h)
    assert r.status_code == 200, r.text

    after = client.get("/api/dispense/fully-dispensed-map", headers=admin_h).json()
    assert after.get(batch_id) is True
