"""Test Công thức nguyên vật liệu mới (Formula) — thay Recipe/RecipeVersion versioning
(xem models/formula.py, services/formula.py): nhiều công thức độc lập/1 dịch bia, chỉ đúng
1 công thức hiệu lực tại 1 thời điểm, khóa để chặn sửa, lịch sử kích hoạt.
"""

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


def _a_formula(client, headers, product_id, code=None, materials=None):
    payload = {"code": code or f"CT-{new_id()[:8]}", "product_id": product_id, "base_qty": 1000, "base_uom": "L",
               "materials": materials or [{"material_code": "MALT-PILS", "qty": 10, "uom": "kg"}]}
    r = client.post("/api/formulas", headers=headers, json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_formula_rejects_duplicate_code(client, admin_h):
    product_id = _a_product(client, admin_h)
    f = _a_formula(client, admin_h, product_id, code="CT-DUPCHECK")
    dup = client.post("/api/formulas", headers=admin_h,
                      json={"code": "CT-DUPCHECK", "product_id": product_id, "base_qty": 500, "base_uom": "L",
                            "materials": [{"material_code": "MALT-PILS", "qty": 5, "uom": "kg"}]})
    assert dup.status_code == 409, dup.text


def test_create_formula_rejects_unknown_material_code(client, admin_h):
    product_id = _a_product(client, admin_h)
    r = client.post("/api/formulas", headers=admin_h,
                    json={"code": f"CT-{new_id()[:8]}", "product_id": product_id, "base_qty": 1000, "base_uom": "L",
                          "materials": [{"material_code": "NOPE-NOT-A-REAL-CODE", "qty": 5, "uom": "kg"}]})
    assert r.status_code == 409, r.text


def test_create_formula_rejects_empty_materials(client, admin_h):
    product_id = _a_product(client, admin_h)
    r = client.post("/api/formulas", headers=admin_h,
                    json={"code": f"CT-{new_id()[:8]}", "product_id": product_id, "base_qty": 1000, "base_uom": "L",
                          "materials": []})
    assert r.status_code == 409, r.text


def test_multiple_formulas_allowed_per_product(client, admin_h):
    """Khác Recipe cũ (1 dịch bia = 1 recipe) — nhiều công thức độc lập/1 dịch bia được phép."""
    product_id = _a_product(client, admin_h)
    f1 = _a_formula(client, admin_h, product_id)
    f2 = _a_formula(client, admin_h, product_id)
    assert f1["formula_id"] != f2["formula_id"]
    lst = client.get(f"/api/formulas?product_id={product_id}", headers=admin_h).json()
    assert {x["formula_id"] for x in lst} == {f1["formula_id"], f2["formula_id"]}
    assert not f1["is_active"] and not f2["is_active"]


def test_activate_deactivates_previous_active_and_logs_history(client, admin_h):
    product_id = _a_product(client, admin_h)
    f1 = _a_formula(client, admin_h, product_id)
    f2 = _a_formula(client, admin_h, product_id)

    act1 = client.post(f"/api/formulas/{f1['formula_id']}/activate", headers=admin_h)
    assert act1.status_code == 200, act1.text
    assert act1.json()["is_active"] is True

    act2 = client.post(f"/api/formulas/{f2['formula_id']}/activate", headers=admin_h)
    assert act2.status_code == 200, act2.text
    assert act2.json()["is_active"] is True

    f1_after = client.get(f"/api/formulas/{f1['formula_id']}", headers=admin_h).json()
    assert f1_after["is_active"] is False, "f1 phải tự động ngừng hiệu lực khi f2 được kích hoạt"

    log = client.get(f"/api/formulas/activation-log?product_id={product_id}", headers=admin_h).json()
    actions_by_formula = [(x["formula_id"], x["action"]) for x in log]
    assert (f1["formula_id"], "activate") in actions_by_formula
    assert (f1["formula_id"], "deactivate") in actions_by_formula
    assert (f2["formula_id"], "activate") in actions_by_formula
    for entry in log:
        assert entry["changed_by"] == "admin"
        assert entry["changed_at"]


def test_activate_already_active_rejected(client, admin_h):
    product_id = _a_product(client, admin_h)
    f = _a_formula(client, admin_h, product_id)
    assert client.post(f"/api/formulas/{f['formula_id']}/activate", headers=admin_h).status_code == 200
    again = client.post(f"/api/formulas/{f['formula_id']}/activate", headers=admin_h)
    assert again.status_code == 409, again.text


def test_deactivate_without_replacement(client, admin_h):
    product_id = _a_product(client, admin_h)
    f = _a_formula(client, admin_h, product_id)
    client.post(f"/api/formulas/{f['formula_id']}/activate", headers=admin_h)
    deact = client.post(f"/api/formulas/{f['formula_id']}/deactivate", headers=admin_h)
    assert deact.status_code == 200, deact.text
    assert deact.json()["is_active"] is False
    again = client.post(f"/api/formulas/{f['formula_id']}/deactivate", headers=admin_h)
    assert again.status_code == 409


def test_update_allowed_when_unlocked(client, admin_h):
    product_id = _a_product(client, admin_h)
    f = _a_formula(client, admin_h, product_id)
    upd = client.put(f"/api/formulas/{f['formula_id']}", headers=admin_h,
                     json={"code": f["code"], "product_id": product_id, "note": "đã sửa",
                           "base_qty": 2000, "base_uom": "L",
                           "materials": [{"material_code": "MALT-PILS", "qty": 25, "uom": "kg"}]})
    assert upd.status_code == 200, upd.text
    assert upd.json()["note"] == "đã sửa"
    assert upd.json()["base_qty"] == 2000


def test_lock_blocks_update_and_delete(client, admin_h):
    product_id = _a_product(client, admin_h)
    f = _a_formula(client, admin_h, product_id)
    lock = client.post(f"/api/formulas/{f['formula_id']}/lock", headers=admin_h)
    assert lock.status_code == 200, lock.text
    assert lock.json()["locked"] is True

    upd = client.put(f"/api/formulas/{f['formula_id']}", headers=admin_h,
                     json={"code": f["code"], "product_id": product_id, "base_qty": 999, "base_uom": "L",
                           "materials": f["materials"]})
    assert upd.status_code == 409, upd.text

    delete = client.delete(f"/api/formulas/{f['formula_id']}", headers=admin_h)
    assert delete.status_code == 409, delete.text

    unlock = client.post(f"/api/formulas/{f['formula_id']}/unlock", headers=admin_h)
    assert unlock.status_code == 200, unlock.text
    assert unlock.json()["locked"] is False
    upd2 = client.put(f"/api/formulas/{f['formula_id']}", headers=admin_h,
                      json={"code": f["code"], "product_id": product_id, "base_qty": 1500, "base_uom": "L",
                            "materials": f["materials"]})
    assert upd2.status_code == 200, upd2.text


def test_delete_blocked_while_active(client, admin_h):
    product_id = _a_product(client, admin_h)
    f = _a_formula(client, admin_h, product_id)
    client.post(f"/api/formulas/{f['formula_id']}/activate", headers=admin_h)
    delete = client.delete(f"/api/formulas/{f['formula_id']}", headers=admin_h)
    assert delete.status_code == 409, delete.text
    client.post(f"/api/formulas/{f['formula_id']}/deactivate", headers=admin_h)
    delete2 = client.delete(f"/api/formulas/{f['formula_id']}", headers=admin_h)
    assert delete2.status_code == 204, delete2.text


def test_mutations_require_recipe_author_permission(client, admin_h):
    product_id = _a_product(client, admin_h)
    # tài khoản demo 'thukho' không có quyền recipe.author (theo seed.py)
    thukho_h = _login(client, "thukho", "123456")
    r = client.post("/api/formulas", headers=thukho_h,
                    json={"code": f"CT-{new_id()[:8]}", "product_id": product_id, "base_qty": 1000, "base_uom": "L",
                          "materials": [{"material_code": "MALT-PILS", "qty": 5, "uom": "kg"}]})
    assert r.status_code == 403, r.text
