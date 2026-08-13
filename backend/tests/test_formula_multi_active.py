"""Test: nhiều công thức/dịch bia cùng hiệu lực đồng thời + chọn công thức khi lập Lệnh
nấu (xem services/formula.py, services/brew_order.py) — thay quy tắc cũ "chỉ 1 công thức
hiệu lực/dịch bia, tự suy ra khi tạo lệnh"."""

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
from app.common import new_id


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


def _a_product(client, headers):
    suffix = new_id()[:8]
    r = client.post("/api/products", headers=headers,
                    json={"code": f"PRD-{suffix}", "name": f"Dịch test {suffix}", "uom": "L"})
    assert r.status_code == 201, r.text
    return r.json()["product_id"]


def _a_formula(client, headers, product_id, qty=10):
    payload = {"code": f"CT-{new_id()[:8]}", "product_id": product_id, "base_qty": 1000, "base_uom": "L",
               "materials": [{"material_code": "MALT-PILS", "qty": qty, "uom": "kg"}]}
    r = client.post("/api/formulas", headers=headers, json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def test_two_formulas_same_product_both_stay_active(client, admin_h):
    product_id = _a_product(client, admin_h)
    f1 = _a_formula(client, admin_h, product_id, qty=10)
    f2 = _a_formula(client, admin_h, product_id, qty=20)

    client.post(f"/api/formulas/{f1['formula_id']}/activate", headers=admin_h)
    client.post(f"/api/formulas/{f2['formula_id']}/activate", headers=admin_h)

    f1_after = client.get(f"/api/formulas/{f1['formula_id']}", headers=admin_h).json()
    f2_after = client.get(f"/api/formulas/{f2['formula_id']}", headers=admin_h).json()
    assert f1_after["is_active"] is True
    assert f2_after["is_active"] is True


def test_brew_order_missing_formula_id_with_product_id_rejected(client, admin_h):
    product_id = _a_product(client, admin_h)
    f = _a_formula(client, admin_h, product_id)
    client.post(f"/api/formulas/{f['formula_id']}/activate", headers=admin_h)

    r = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": f"LN-NOFRM-{new_id()[:6]}", "product_id": product_id,
        "planned_batch_count": 1, "planned_volume_hl": 100, "volume_tolerance_hl": 0,
        "auto_from_bom": True, "lines": [],
    })
    assert r.status_code == 409, r.text
    assert "Chọn công thức" in r.text


def test_brew_order_correct_formula_id_loads_bom_from_that_formula(client, admin_h):
    product_id = _a_product(client, admin_h)
    f1 = _a_formula(client, admin_h, product_id, qty=10)
    f2 = _a_formula(client, admin_h, product_id, qty=999)
    client.post(f"/api/formulas/{f1['formula_id']}/activate", headers=admin_h)
    client.post(f"/api/formulas/{f2['formula_id']}/activate", headers=admin_h)

    order = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": f"LN-PICKFRM-{new_id()[:6]}", "product_id": product_id,
        "formula_id": f1["formula_id"],
        "planned_batch_count": 2, "planned_volume_hl": 100, "volume_tolerance_hl": 0,
        "auto_from_bom": True, "lines": [],
    })
    assert order.status_code == 201, order.text
    detail = client.get(f"/api/brewing/orders/{order.json()['brew_order_id']}", headers=admin_h).json()
    line = next(l for l in detail["lines"] if not l["is_header"])
    # f1 khai 10 kg/mẻ — phải nạp đúng từ f1, KHÔNG lẫn với f2 (999 kg/mẻ).
    assert line["qty_per_batch"] == pytest.approx(10)
    assert line["qty_total"] == pytest.approx(20)


def test_brew_order_formula_id_wrong_product_rejected(client, admin_h):
    product_a = _a_product(client, admin_h)
    product_b = _a_product(client, admin_h)
    f_b = _a_formula(client, admin_h, product_b)
    client.post(f"/api/formulas/{f_b['formula_id']}/activate", headers=admin_h)

    r = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": f"LN-WRONGPRD-{new_id()[:6]}", "product_id": product_a,
        "formula_id": f_b["formula_id"],
        "planned_batch_count": 1, "planned_volume_hl": 100, "volume_tolerance_hl": 0,
        "auto_from_bom": True, "lines": [],
    })
    assert r.status_code == 409, r.text
    assert "không thuộc Dịch bia" in r.text


def test_brew_order_formula_id_inactive_rejected(client, admin_h):
    product_id = _a_product(client, admin_h)
    f = _a_formula(client, admin_h, product_id)
    # KHÔNG activate — vẫn is_active=False.

    r = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": f"LN-INACTIVE-{new_id()[:6]}", "product_id": product_id,
        "formula_id": f["formula_id"],
        "planned_batch_count": 1, "planned_volume_hl": 100, "volume_tolerance_hl": 0,
        "auto_from_bom": True, "lines": [],
    })
    assert r.status_code == 409, r.text
    assert "không còn hiệu lực" in r.text
