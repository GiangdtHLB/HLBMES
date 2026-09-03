"""Test "Sửa Thực tế" (adjust_actual) trên bảng Định mức↔Thực tế của "Cấp liệu cho mẻ" — tự
tính chênh lệch với thực tế hiện tại rồi tự cấp thêm (tăng, qua FEFO all-or-nothing) hoặc hoàn
lại (giảm, theo LIFO — hoàn lô đã dùng GẦN NHẤT trước). Xem services/dispense.py::adjust_actual.
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
                    json={"code": f"ADJ-{suffix}", "name": f"Vật tư test {suffix}", "uom": "kg"})
    assert r.status_code == 201, r.text
    return r.json()["material_id"], r.json()["code"]


def _receive_workshop_lot(client, admin_h, material_id, qty, days_to_expiry):
    r = client.post("/api/warehouse/receive", headers=admin_h, json={
        "material_id": material_id, "quantity": qty, "uom": "kg",
        "location": "Kho phân xưởng",
        "expiry": (utcnow() + timedelta(days=days_to_expiry)).isoformat(),
    })
    assert r.status_code == 200, r.text
    return r.json()["lot_id"]


def _recipe_version(client, admin_h, suffix, material_code, qty, base_qty=100):
    bt = client.post("/api/beer-types", headers=admin_h,
                     json={"code": f"BT-ADJ-{suffix}", "name": f"Loại test {suffix}"})
    assert bt.status_code == 201, bt.text
    r = client.post("/api/recipes", headers=admin_h,
                    json={"code": f"CT-ADJ-{suffix}", "name": "Test recipe sửa thực tế",
                         "beer_type_id": bt.json()["beer_type_id"]})
    assert r.status_code == 201, r.text
    recipe_id = r.json()["recipe_id"]
    prod = client.post("/api/products", headers=admin_h,
                       json={"code": f"PRD-ADJ-{suffix}", "name": f"Dịch test {suffix}", "uom": "L",
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
                         "planned_qty": planned_qty,   # batch_code: để tự sinh (giờ bắt buộc số nguyên)
                         "allow_shortage": allow_shortage})
    assert b.status_code == 201, b.text
    return b.json()["batch_id"]


def _bom_actual(client, admin_h, batch_id, code):
    bom = client.get(f"/api/batches/{batch_id}/bom", headers=admin_h).json()
    return next(l for l in bom["lines"] if l["material_code"] == code)["actual"]


def test_adjust_increase_uses_fefo_and_blocked_without_reason(client, admin_h):
    material_id, code = _new_material(client, admin_h, "INC01")
    lot_id = _receive_workshop_lot(client, admin_h, material_id, 50, days_to_expiry=10)
    version_id = _recipe_version(client, admin_h, "INC01", code, qty=100, base_qty=100)
    batch_id = _new_batch(client, admin_h, version_id, planned_qty=100, suffix="INC01", allow_shortage=True)

    no_reason = client.post(f"/api/dispense/{batch_id}/adjust", headers=admin_h,
                            json={"material_code": code, "new_actual": 20, "reason": ""})
    assert no_reason.status_code == 409, no_reason.text   # lý do rỗng -> chặn

    adj = client.post(f"/api/dispense/{batch_id}/adjust", headers=admin_h,
                      json={"material_code": code, "new_actual": 20, "reason": "Cân lại thấy cần thêm 20kg"})
    assert adj.status_code == 200, adj.text
    assert _bom_actual(client, admin_h, batch_id, code) == 20.0

    lot_after = next(l for l in client.get("/api/lots", headers=admin_h).json() if l["lot_id"] == lot_id)
    assert lot_after["quantity"] == 30.0   # 50 - 20

    hist = client.get(f"/api/dispense?batch_id={batch_id}", headers=admin_h).json()
    adj_disp = next(d for d in hist if d["mode"] == "adjust")
    assert adj_disp["lines"][0]["quantity"] == 20.0 and adj_disp["lines"][0]["reason"]


def test_adjust_increase_blocked_all_or_nothing_when_insufficient(client, admin_h):
    material_id, code = _new_material(client, admin_h, "INCSHORT01")
    lot_id = _receive_workshop_lot(client, admin_h, material_id, 5, days_to_expiry=10)
    version_id = _recipe_version(client, admin_h, "INCSHORT01", code, qty=100, base_qty=100)
    batch_id = _new_batch(client, admin_h, version_id, planned_qty=100, suffix="INCSHORT01", allow_shortage=True)

    blocked = client.post(f"/api/dispense/{batch_id}/adjust", headers=admin_h,
                          json={"material_code": code, "new_actual": 20, "reason": "cần thêm"})
    assert blocked.status_code == 409, blocked.text

    lot_after = next(l for l in client.get("/api/lots", headers=admin_h).json() if l["lot_id"] == lot_id)
    assert lot_after["quantity"] == 5.0   # chưa trừ gì


def test_adjust_decrease_refunds_most_recently_used_lot_first(client, admin_h):
    material_id, code = _new_material(client, admin_h, "DEC01")
    lot_old = _receive_workshop_lot(client, admin_h, material_id, 10, days_to_expiry=5)    # dùng trước (FEFO)
    lot_new = _receive_workshop_lot(client, admin_h, material_id, 10, days_to_expiry=30)   # dùng sau
    version_id = _recipe_version(client, admin_h, "DEC01", code, qty=100, base_qty=100)
    batch_id = _new_batch(client, admin_h, version_id, planned_qty=100, suffix="DEC01", allow_shortage=True)

    # Cấp 2 lần liên tiếp -> lô cũ (FEFO) dùng trước hết 10, rồi lô mới dùng 5 -> thực tế = 15.
    first = client.post(f"/api/dispense/{batch_id}", headers=admin_h,
                        json={"lines": [{"material_code": code, "quantity": 10}]})
    assert first.status_code == 200, first.text
    second = client.post(f"/api/dispense/{batch_id}", headers=admin_h,
                         json={"lines": [{"material_code": code, "quantity": 5}]})
    assert second.status_code == 200, second.text
    assert _bom_actual(client, admin_h, batch_id, code) == 15.0

    # Sửa Thực tế xuống 12 -> hoàn 3kg -> phải hoàn về lot_new (lần dùng GẦN NHẤT) trước, không
    # đụng tới lot_old dù lot_old là lô FEFO/lô dùng đầu tiên.
    adj = client.post(f"/api/dispense/{batch_id}/adjust", headers=admin_h,
                      json={"material_code": code, "new_actual": 12, "reason": "Cân lại thấy dùng ít hơn"})
    assert adj.status_code == 200, adj.text
    assert _bom_actual(client, admin_h, batch_id, code) == 12.0

    lots = {l["lot_id"]: l["quantity"] for l in client.get("/api/lots", headers=admin_h).json()}
    assert lots[lot_old] == 0.0     # vẫn hết (không hoàn)
    assert lots[lot_new] == 8.0     # 10 - 5 dùng + 3 hoàn = 8


def test_adjust_decrease_blocked_when_more_than_consumed_history(client, admin_h):
    material_id, code = _new_material(client, admin_h, "DECGUARD01")
    _receive_workshop_lot(client, admin_h, material_id, 10, days_to_expiry=10)
    version_id = _recipe_version(client, admin_h, "DECGUARD01", code, qty=100, base_qty=100)
    batch_id = _new_batch(client, admin_h, version_id, planned_qty=100, suffix="DECGUARD01", allow_shortage=True)
    disp = client.post(f"/api/dispense/{batch_id}", headers=admin_h,
                       json={"lines": [{"material_code": code, "quantity": 4}]})
    assert disp.status_code == 200, disp.text

    over = client.post(f"/api/dispense/{batch_id}/adjust", headers=admin_h,
                       json={"material_code": code, "new_actual": -1, "reason": "test âm"})
    assert over.status_code == 409, over.text   # muốn hoàn 5kg nhưng chỉ có 4kg lịch sử để hoàn


def test_adjust_no_op_when_same_value_rejected(client, admin_h):
    material_id, code = _new_material(client, admin_h, "NOOP01")
    _receive_workshop_lot(client, admin_h, material_id, 10, days_to_expiry=10)
    version_id = _recipe_version(client, admin_h, "NOOP01", code, qty=100, base_qty=100)
    batch_id = _new_batch(client, admin_h, version_id, planned_qty=100, suffix="NOOP01", allow_shortage=True)
    client.post(f"/api/dispense/{batch_id}", headers=admin_h,
               json={"lines": [{"material_code": code, "quantity": 5}]})

    same = client.post(f"/api/dispense/{batch_id}/adjust", headers=admin_h,
                       json={"material_code": code, "new_actual": 5, "reason": "không đổi gì"})
    assert same.status_code == 409, same.text
