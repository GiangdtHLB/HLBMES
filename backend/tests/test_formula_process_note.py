"""Test: Công thức có thêm trường process_reference_note (nội dung quyết định ban hành
công thức + quy trình sản xuất, khai báo 1 lần trên công thức) — phải in nguyên văn vào
phiếu Lệnh nấu mỗi khi công thức đó được chọn cho 1 lệnh nấu nhỏ. Xem
models/formula.py::Formula.process_reference_note,
services/brew_order.py::get_order/_child_summary (field formula_code/formula_process_note
trả ra cho frontend::printBrewOrder)."""

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

REF_NOTE = ("Quyết định ban hành công thức và quy trình sản xuất Bia hơi Hạ Long-Sản xuất tại "
            "phân xưởng sản xuất Hạ Long số 106/2025/QĐ-HCNS ngày 21/1/2026. Lần ban hành 03 "
            "ngày 10/3/2025.")


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


def _a_material(client, headers, code):
    r = client.post("/api/materials", headers=headers, json={"code": code, "name": f"NVL {code}", "uom": "kg"})
    assert r.status_code == 201, r.text
    return r.json()["material_id"]


def _receive_workshop_stock(client, headers, material_id, code, qty=100):
    # Nhập vào Kho phân xưởng — không bị chặn bởi yêu cầu chọn vị trí kho (chỉ áp dụng phía
    # Kho công ty, xem routers/warehouse.py::receive) — đủ để build_lines_from_bom không báo
    # thiếu tồn khi tạo Lệnh nấu test.
    r = client.post("/api/warehouse/receive", headers=headers,
                    json={"lot_code": f"LOT-{code}", "material_id": material_id,
                          "quantity": qty, "uom": "kg", "location": "Kho phân xưởng"})
    assert r.status_code == 200, r.text


def test_create_formula_with_process_reference_note(client, admin_h):
    product_id = _a_product(client, admin_h)
    mat_code = f"MAT-{new_id()[:6]}"
    _a_material(client, admin_h, mat_code)
    r = client.post("/api/formulas", headers=admin_h, json={
        "code": f"CT-{new_id()[:8]}", "product_id": product_id, "base_qty": 1000, "base_uom": "L",
        "process_reference_note": REF_NOTE,
        "materials": [{"material_code": mat_code, "qty": 10, "uom": "kg"}],
    })
    assert r.status_code == 201, r.text
    formula = r.json()
    assert formula["process_reference_note"] == REF_NOTE

    fetched = client.get(f"/api/formulas/{formula['formula_id']}", headers=admin_h).json()
    assert fetched["process_reference_note"] == REF_NOTE


def test_update_formula_process_reference_note(client, admin_h):
    product_id = _a_product(client, admin_h)
    mat_code = f"MAT-{new_id()[:6]}"
    _a_material(client, admin_h, mat_code)
    r = client.post("/api/formulas", headers=admin_h, json={
        "code": f"CT-{new_id()[:8]}", "product_id": product_id, "base_qty": 1000, "base_uom": "L",
        "materials": [{"material_code": mat_code, "qty": 10, "uom": "kg"}],
    })
    formula = r.json()
    assert formula["process_reference_note"] is None

    u = client.put(f"/api/formulas/{formula['formula_id']}", headers=admin_h, json={
        "code": formula["code"], "product_id": product_id, "base_qty": 1000, "base_uom": "L",
        "process_reference_note": REF_NOTE,
        "materials": [{"material_code": mat_code, "qty": 10, "uom": "kg"}],
    })
    assert u.status_code == 200, u.text
    assert u.json()["process_reference_note"] == REF_NOTE


def test_brew_order_surfaces_formula_process_note(client, admin_h):
    product_id = _a_product(client, admin_h)
    mat_code = f"MAT-{new_id()[:6]}"
    material_id = _a_material(client, admin_h, mat_code)
    _receive_workshop_stock(client, admin_h, material_id, mat_code)
    formula = client.post("/api/formulas", headers=admin_h, json={
        "code": f"CT-{new_id()[:8]}", "product_id": product_id, "base_qty": 1000, "base_uom": "L",
        "process_reference_note": REF_NOTE,
        "materials": [{"material_code": mat_code, "qty": 10, "uom": "kg"}],
    }).json()
    client.post(f"/api/formulas/{formula['formula_id']}/activate", headers=admin_h)

    order = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": f"LN-{new_id()[:8]}", "product_id": product_id, "formula_id": formula["formula_id"],
        "planned_batch_count": 2, "planned_volume_hl": 100, "volume_tolerance_hl": 0,
        "auto_from_bom": True, "lines": [],
    })
    assert order.status_code == 201, order.text
    order_id = order.json()["brew_order_id"]

    detail = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    assert detail["formula_code"] == formula["code"]
    assert detail["formula_process_note"] == REF_NOTE


def test_brew_master_order_children_surface_formula_process_note(client, admin_h):
    product_id = _a_product(client, admin_h)
    mat_code = f"MAT-{new_id()[:6]}"
    material_id = _a_material(client, admin_h, mat_code)
    _receive_workshop_stock(client, admin_h, material_id, mat_code)
    formula = client.post("/api/formulas", headers=admin_h, json={
        "code": f"CT-{new_id()[:8]}", "product_id": product_id, "base_qty": 1000, "base_uom": "L",
        "process_reference_note": REF_NOTE,
        "materials": [{"material_code": mat_code, "qty": 10, "uom": "kg"}],
    }).json()
    client.post(f"/api/formulas/{formula['formula_id']}/activate", headers=admin_h)

    r = client.post("/api/brewing/brew-master-orders", headers=admin_h, json={
        "order_code": f"LNL-{new_id()[:8]}",
        "children": [{"product_id": product_id, "formula_id": formula["formula_id"],
                      "planned_batch_count": 2, "planned_volume_hl": 100, "volume_tolerance_hl": 0,
                      "auto_from_bom": True, "lines": []}],
    })
    assert r.status_code == 201, r.text
    master_id = r.json()["brew_master_order_id"]

    master = client.get(f"/api/brewing/brew-master-orders/{master_id}", headers=admin_h).json()
    child = master["children"][0]
    assert child["formula_code"] == formula["code"]
    assert child["formula_process_note"] == REF_NOTE

    listed = client.get("/api/brewing/brew-master-orders", headers=admin_h).json()
    row = next(m for m in listed if m["brew_master_order_id"] == master_id)
    assert row["children"][0]["formula_process_note"] == REF_NOTE


def test_brew_order_without_formula_has_null_process_note(client, admin_h):
    order = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": f"LN-NOFORM-{new_id()[:8]}", "auto_from_bom": False, "planned_volume_hl": 100,
        "lines": [],
    })
    assert order.status_code == 201, order.text
    detail = client.get(f"/api/brewing/orders/{order.json()['brew_order_id']}", headers=admin_h).json()
    assert detail["formula_code"] is None
    assert detail["formula_process_note"] is None
