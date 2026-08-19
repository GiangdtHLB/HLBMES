"""Test: Công thức (Formula) có thêm trường process_reference_note (nội dung quyết định ban
hành công thức + quy trình sản xuất, khai báo 1 lần trên công thức). Xem
models/formula.py::Formula.process_reference_note.

Lưu ý: Lệnh nấu (BrewOrder) không còn nạp NVL từ Formula nữa (đã đổi về hệ Recipe/
RecipeVersion, xem services/brew_order.py::build_lines_from_recipe_version) — RecipeVersion
không có field tương đương process_reference_note, nên phần test cũ kiểm tra field này được
in ra qua get_order/_child_summary (formula_code/formula_process_note) đã bị bỏ cùng với việc
gỡ Formula khỏi luồng Lệnh nấu, không còn ý nghĩa để test lại ở đây."""

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
