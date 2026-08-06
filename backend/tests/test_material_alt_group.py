"""Test Nhóm vật tư thay thế (MaterialAltGroup) — VD "Malt Úc" = Malt Úc rời + Malt Úc bao,
cùng bản chất khác quy cách đóng gói (xem models/master.py::MaterialAltGroup). Công thức có
thể khai 1 dòng NVL bằng NHÓM này thay vì 1 material_code cụ thể; thủ kho tự chọn mã cụ thể
lúc xuất kho thật, tùy tồn kho lúc đó (xem services/brew_order.py::_resolve_group_members).

Phạm vi test:
1) CRUD nhóm vật tư thay thế (trùng code, thiếu thành viên, xóa khi đang dùng trong công thức).
2) services/formula.py chấp nhận dòng NVL khai theo alt_group_code thay vì material_code.
3) services/brew_order.py build_lines_from_bom/preview trả đúng dòng nhóm (material_id=None,
   member_material_ids đúng, tồn kho cộng dồn qua các thành viên).
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


def _material_id(client, admin_h, code):
    materials = client.get("/api/materials", headers=admin_h).json()
    return next(m["material_id"] for m in materials if m["code"] == code)


@pytest.fixture(scope="module")
def malt_pils_id(client, admin_h):
    return _material_id(client, admin_h, "MALT-PILS")


@pytest.fixture(scope="module")
def malt_vienna_id(client, admin_h):
    return _material_id(client, admin_h, "MALT-VIENNA")


@pytest.fixture(scope="module")
def lager_product_id(client, admin_h):
    products = client.get("/api/products", headers=admin_h).json()
    return next(p["product_id"] for p in products if p["code"] == "BIA-LAGER")


def _a_alt_group(client, admin_h, member_ids, code=None, name=None, unit="kg"):
    payload = {"code": code or f"ALTGRP-{new_id()[:8]}", "name": name or "Malt test",
               "member_material_ids": member_ids, "unit": unit}
    r = client.post("/api/material-alt-groups", headers=admin_h, json=payload)
    assert r.status_code == 201, r.text
    return r.json()


# ---- 1) CRUD ----

def test_create_alt_group_rejects_duplicate_code(client, admin_h, malt_pils_id, malt_vienna_id):
    g = _a_alt_group(client, admin_h, [malt_pils_id, malt_vienna_id], code="ALTGRP-DUPCHECK")
    dup = client.post("/api/material-alt-groups", headers=admin_h,
                      json={"code": "ALTGRP-DUPCHECK", "name": "Khác", "unit": "kg",
                            "member_material_ids": [malt_pils_id]})
    assert dup.status_code == 409, dup.text


def test_create_alt_group_rejects_no_members(client, admin_h):
    r = client.post("/api/material-alt-groups", headers=admin_h,
                    json={"code": f"ALTGRP-{new_id()[:8]}", "name": "Rỗng", "unit": "kg",
                          "member_material_ids": []})
    assert r.status_code == 409, r.text


def test_update_alt_group(client, admin_h, malt_pils_id, malt_vienna_id):
    g = _a_alt_group(client, admin_h, [malt_pils_id])
    upd = client.put(f"/api/material-alt-groups/{g['group_id']}", headers=admin_h,
                     json={"code": g["code"], "name": "Đã sửa", "unit": "kg",
                           "member_material_ids": [malt_pils_id, malt_vienna_id], "active": True})
    assert upd.status_code == 200, upd.text
    assert upd.json()["name"] == "Đã sửa"
    assert set(upd.json()["member_material_ids"]) == {malt_pils_id, malt_vienna_id}


def test_delete_alt_group_ok_when_unused(client, admin_h, malt_pils_id):
    g = _a_alt_group(client, admin_h, [malt_pils_id])
    r = client.delete(f"/api/material-alt-groups/{g['group_id']}", headers=admin_h)
    assert r.status_code == 204, r.text


def test_delete_alt_group_blocked_when_used_in_formula(client, admin_h, malt_pils_id, malt_vienna_id, lager_product_id):
    g = _a_alt_group(client, admin_h, [malt_pils_id, malt_vienna_id])
    f = client.post("/api/formulas", headers=admin_h,
                    json={"code": f"CT-{new_id()[:8]}", "product_id": lager_product_id,
                          "base_qty": 1000, "base_uom": "L",
                          "materials": [{"alt_group_code": g["code"], "qty": 100, "uom": "kg"}]})
    assert f.status_code == 201, f.text

    blocked = client.delete(f"/api/material-alt-groups/{g['group_id']}", headers=admin_h)
    assert blocked.status_code == 409, blocked.text


# ---- 2) services/formula.py — dòng NVL theo alt_group_code ----

def test_formula_accepts_alt_group_line(client, admin_h, malt_pils_id, malt_vienna_id, lager_product_id):
    g = _a_alt_group(client, admin_h, [malt_pils_id, malt_vienna_id])
    r = client.post("/api/formulas", headers=admin_h,
                    json={"code": f"CT-{new_id()[:8]}", "product_id": lager_product_id,
                          "base_qty": 1000, "base_uom": "L",
                          "materials": [{"alt_group_code": g["code"], "qty": 825, "uom": "kg"}]})
    assert r.status_code == 201, r.text
    line = r.json()["materials"][0]
    assert line["alt_group_code"] == g["code"]
    assert line.get("material_code") is None


def test_formula_rejects_line_with_both_or_neither_code(client, admin_h, malt_pils_id, lager_product_id):
    g = _a_alt_group(client, admin_h, [malt_pils_id])
    both = client.post("/api/formulas", headers=admin_h,
                       json={"code": f"CT-{new_id()[:8]}", "product_id": lager_product_id,
                             "base_qty": 1000, "base_uom": "L",
                             "materials": [{"material_code": "MALT-PILS", "alt_group_code": g["code"],
                                            "qty": 10, "uom": "kg"}]})
    assert both.status_code == 409, both.text

    neither = client.post("/api/formulas", headers=admin_h,
                          json={"code": f"CT-{new_id()[:8]}", "product_id": lager_product_id,
                                "base_qty": 1000, "base_uom": "L",
                                "materials": [{"qty": 10, "uom": "kg"}]})
    assert neither.status_code == 409, neither.text


def test_formula_rejects_unknown_or_inactive_alt_group(client, admin_h, malt_pils_id, lager_product_id):
    unknown = client.post("/api/formulas", headers=admin_h,
                          json={"code": f"CT-{new_id()[:8]}", "product_id": lager_product_id,
                                "base_qty": 1000, "base_uom": "L",
                                "materials": [{"alt_group_code": "NOPE-NOT-REAL", "qty": 10, "uom": "kg"}]})
    assert unknown.status_code == 409, unknown.text

    g = _a_alt_group(client, admin_h, [malt_pils_id])
    client.put(f"/api/material-alt-groups/{g['group_id']}", headers=admin_h,
              json={"code": g["code"], "name": g["name"], "unit": "kg",
                    "member_material_ids": [malt_pils_id], "active": False})
    inactive = client.post("/api/formulas", headers=admin_h,
                           json={"code": f"CT-{new_id()[:8]}", "product_id": lager_product_id,
                                 "base_qty": 1000, "base_uom": "L",
                                 "materials": [{"alt_group_code": g["code"], "qty": 10, "uom": "kg"}]})
    assert inactive.status_code == 409, inactive.text


# ---- 3) services/brew_order.py — build_lines_from_bom/preview cho dòng nhóm ----

def test_brew_order_bom_preview_resolves_alt_group_line(client, admin_h, malt_pils_id, malt_vienna_id, lager_product_id):
    g = _a_alt_group(client, admin_h, [malt_pils_id, malt_vienna_id], name="Malt Úc")
    formula = client.post("/api/formulas", headers=admin_h,
                          json={"code": f"CT-{new_id()[:8]}", "product_id": lager_product_id,
                                "base_qty": 1000, "base_uom": "L",
                                "materials": [{"alt_group_code": g["code"], "qty": 825, "uom": "kg"}]}).json()
    client.post(f"/api/formulas/{formula['formula_id']}/activate", headers=admin_h)

    preview = client.get("/api/brewing/orders/bom-preview", headers=admin_h,
                         params={"product_id": lager_product_id, "planned_batch_count": 2,
                                 "planned_volume_hl": 100}).json()
    line = next(l for l in preview if not l.get("is_header"))
    assert line["material_id"] is None
    assert line["material_name"] == "Malt Úc"
    assert set(line["member_material_ids"]) == {malt_pils_id, malt_vienna_id}
    assert line["qty_per_batch"] == 825
    assert line["qty_total"] == 1650  # 825 x 2 mẻ
    # Tồn kho snapshot phải CỘNG DỒN qua cả 2 mã thành viên, không chỉ tra theo 1 material_id.
    assert line["stock_company_snapshot"] is not None or line["stock_workshop_snapshot"] is not None


def test_brew_order_created_from_alt_group_formula_persists_group_code(client, admin_h, malt_pils_id, malt_vienna_id, lager_product_id):
    g = _a_alt_group(client, admin_h, [malt_pils_id, malt_vienna_id], name="Malt Úc")
    formula = client.post("/api/formulas", headers=admin_h,
                          json={"code": f"CT-{new_id()[:8]}", "product_id": lager_product_id,
                                "base_qty": 1000, "base_uom": "L",
                                "materials": [{"alt_group_code": g["code"], "qty": 500, "uom": "kg"}]}).json()
    client.post(f"/api/formulas/{formula['formula_id']}/activate", headers=admin_h)

    order = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": f"LN-ALTGRP-{new_id()[:6]}", "product_id": lager_product_id,
        "planned_batch_count": 1, "planned_volume_hl": 100, "volume_tolerance_hl": 0,
        "auto_from_bom": True, "lines": [],
    })
    assert order.status_code == 201, order.text

    detail = client.get(f"/api/brewing/orders/{order.json()['brew_order_id']}", headers=admin_h).json()
    line = next(l for l in detail["lines"] if not l["is_header"])
    assert line["material_id"] is None
    assert line["material_group_code"] == g["code"]
    assert set(line["member_material_ids"]) == {malt_pils_id, malt_vienna_id}
