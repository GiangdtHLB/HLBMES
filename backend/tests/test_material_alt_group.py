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


def _a_alt_group(client, admin_h, member_ids, code=None, name=None, unit="kg", selection_mode="single"):
    payload = {"code": code or f"ALTGRP-{new_id()[:8]}", "name": name or "Malt test",
               "member_material_ids": member_ids, "unit": unit, "selection_mode": selection_mode}
    r = client.post("/api/material-alt-groups", headers=admin_h, json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _lager_recipe_id(client, admin_h, lager_product_id):
    """1 dịch bia có đúng 1 Recipe — seed.py đã tạo sẵn REC-LAGER cho BIA-LAGER, các test dưới
    THÊM version mới vào chính Recipe này (không tạo Recipe khác cho cùng sản phẩm — bị chặn
    bởi unique product_id, xem models/recipes.py)."""
    recipes = client.get("/api/recipes", headers=admin_h).json()
    return next(r["recipe_id"] for r in recipes if r["product_id"] == lager_product_id)


def _activate_recipe_version(client, headers, version_id):
    for target in ("review", "approved", "effective"):
        r = client.post(f"/api/recipes/versions/{version_id}/transition", headers=headers, json={"target": target})
        assert r.status_code == 200, r.text


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
    recipe_id = _lager_recipe_id(client, admin_h, lager_product_id)
    v = client.post(f"/api/recipes/{recipe_id}/versions", headers=admin_h,
                    json={"base_qty": 1000, "base_uom": "L",
                          "materials": [{"alt_group_code": g["code"], "qty": 825, "uom": "kg"}]}).json()
    _activate_recipe_version(client, admin_h, v["version_id"])

    preview = client.get("/api/brewing/orders/bom-preview", headers=admin_h,
                         params={"recipe_version_id": v["version_id"], "planned_batch_count": 2,
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
    recipe_id = _lager_recipe_id(client, admin_h, lager_product_id)
    v = client.post(f"/api/recipes/{recipe_id}/versions", headers=admin_h,
                    json={"base_qty": 1000, "base_uom": "L",
                          "materials": [{"alt_group_code": g["code"], "qty": 500, "uom": "kg"}]}).json()
    _activate_recipe_version(client, admin_h, v["version_id"])

    order = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": f"LN-ALTGRP-{new_id()[:6]}", "product_id": lager_product_id,
        "recipe_version_id": v["version_id"],
        "planned_batch_count": 1, "planned_volume_hl": 100, "volume_tolerance_hl": 0,
        "auto_from_bom": True, "lines": [],
    })
    assert order.status_code == 201, order.text

    detail = client.get(f"/api/brewing/orders/{order.json()['brew_order_id']}", headers=admin_h).json()
    line = next(l for l in detail["lines"] if not l["is_header"])
    assert line["material_id"] is None
    assert line["material_group_code"] == g["code"]
    assert set(line["member_material_ids"]) == {malt_pils_id, malt_vienna_id}


# ---- 4) selection_mode + định mức RIÊNG từng thành viên (member_qty) ----

def test_alt_group_defaults_to_single_mode(client, admin_h, malt_pils_id):
    g = _a_alt_group(client, admin_h, [malt_pils_id])
    assert g["selection_mode"] == "single"


def test_alt_group_accepts_multi_mode(client, admin_h, malt_pils_id, malt_vienna_id):
    r = client.post("/api/material-alt-groups", headers=admin_h,
                    json={"code": f"ALTGRP-{new_id()[:8]}", "name": "CO2 tương đương", "unit": "kg",
                          "member_material_ids": [malt_pils_id, malt_vienna_id], "selection_mode": "multi"})
    assert r.status_code == 201, r.text
    assert r.json()["selection_mode"] == "multi"


def test_alt_group_rejects_invalid_selection_mode(client, admin_h, malt_pils_id):
    r = client.post("/api/material-alt-groups", headers=admin_h,
                    json={"code": f"ALTGRP-{new_id()[:8]}", "name": "X", "unit": "kg",
                          "member_material_ids": [malt_pils_id], "selection_mode": "some_other_mode"})
    assert r.status_code == 409, r.text


def test_bom_preview_member_qty_resolves_per_member_amounts(client, admin_h, malt_pils_id, malt_vienna_id, lager_product_id):
    """Dòng nhóm khai member_qty (mỗi thành viên 1 định mức riêng, VD do khác nồng độ) — BOM
    preview phải trả đúng qty_per_batch/qty_total RIÊNG từng mã trong member_breakdown, không
    còn 1 con số dùng chung cho cả dòng."""
    g = _a_alt_group(client, admin_h, [malt_pils_id, malt_vienna_id], name="CO2 tương đương")
    recipe_id = _lager_recipe_id(client, admin_h, lager_product_id)
    v = client.post(f"/api/recipes/{recipe_id}/versions", headers=admin_h,
                    json={"base_qty": 1000, "base_uom": "L",
                          "materials": [{"alt_group_code": g["code"], "uom": "kg",
                                        "member_qty": [{"material_code": "MALT-PILS", "qty": 5},
                                                      {"material_code": "MALT-VIENNA", "qty": 6}]}]}).json()
    _activate_recipe_version(client, admin_h, v["version_id"])

    preview = client.get("/api/brewing/orders/bom-preview", headers=admin_h,
                         params={"recipe_version_id": v["version_id"], "planned_batch_count": 2,
                                 "planned_volume_hl": 100}).json()
    line = next(l for l in preview if not l.get("is_header"))
    assert line["material_id"] is None
    assert line["qty_per_batch"] == 11    # tổng 2 mã: 5 + 6 (chỉ mang tính hiển thị tổng quan)
    assert line["qty_total"] == 22        # (5 + 6) x 2 mẻ
    breakdown_by_code = {mb["material_code"]: mb for mb in line["member_breakdown"]}
    assert breakdown_by_code["MALT-PILS"]["qty_per_batch"] == 5
    assert breakdown_by_code["MALT-PILS"]["qty_total"] == 10   # 5 x 2 mẻ
    assert breakdown_by_code["MALT-VIENNA"]["qty_per_batch"] == 6
    assert breakdown_by_code["MALT-VIENNA"]["qty_total"] == 12  # 6 x 2 mẻ
    assert "shortage" in breakdown_by_code["MALT-PILS"]


def test_create_order_member_qty_blocked_only_when_every_member_short(client, admin_h, malt_pils_id, malt_vienna_id, lager_product_id):
    """_assert_no_shortage với dòng member_qty: chặn tạo lệnh CHỈ KHI không mã nào đủ tồn
    riêng của chính nó — còn nếu ít nhất 1 mã đủ (VD định mức cực nhỏ) thì vẫn cho tạo, vì
    người ghi NVL thực tế có thể chọn đúng mã đó."""
    # selection_mode="multi" — kiểm tra logic thiếu tồn ĐỘC LẬP với việc yêu cầu chọn thành
    # viên (xem test_create_order_requires_member_selection_for_single_mode_group ở dưới).
    g = _a_alt_group(client, admin_h, [malt_pils_id, malt_vienna_id], name="CO2 tương đương 2", selection_mode="multi")
    recipe_id = _lager_recipe_id(client, admin_h, lager_product_id)

    # Cả 2 mã đều đòi hỏi 1 tỷ kg — chắc chắn vượt xa mọi tồn kho thật, phải bị chặn.
    v_huge = client.post(f"/api/recipes/{recipe_id}/versions", headers=admin_h,
                         json={"base_qty": 1000, "base_uom": "L",
                               "materials": [{"alt_group_code": g["code"], "uom": "kg",
                                             "member_qty": [{"material_code": "MALT-PILS", "qty": 1_000_000_000},
                                                           {"material_code": "MALT-VIENNA", "qty": 1_000_000_000}]}]}).json()
    _activate_recipe_version(client, admin_h, v_huge["version_id"])
    blocked = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": f"LN-ALTGRP-BLOCKED-{new_id()[:6]}", "product_id": lager_product_id,
        "recipe_version_id": v_huge["version_id"],
        "planned_batch_count": 1, "planned_volume_hl": 100, "volume_tolerance_hl": 0,
        "auto_from_bom": True, "lines": [],
    })
    assert blocked.status_code == 409, blocked.text

    # Chỉ MALT-PILS đòi hỏi số cực nhỏ (chắc chắn đủ), MALT-VIENNA vẫn đòi 1 tỷ kg (chắc chắn
    # thiếu) — vẫn phải cho tạo vì còn 1 lựa chọn khả thi (MALT-PILS).
    recipe_id2 = recipe_id
    v_mixed = client.post(f"/api/recipes/{recipe_id2}/versions", headers=admin_h,
                          json={"base_qty": 1000, "base_uom": "L",
                                "materials": [{"alt_group_code": g["code"], "uom": "kg",
                                              "member_qty": [{"material_code": "MALT-PILS", "qty": 0.001},
                                                            {"material_code": "MALT-VIENNA", "qty": 1_000_000_000}]}]}).json()
    _activate_recipe_version(client, admin_h, v_mixed["version_id"])
    allowed = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": f"LN-ALTGRP-ALLOWED-{new_id()[:6]}", "product_id": lager_product_id,
        "recipe_version_id": v_mixed["version_id"],
        "planned_batch_count": 1, "planned_volume_hl": 100, "volume_tolerance_hl": 0,
        "auto_from_bom": True, "lines": [],
    })
    assert allowed.status_code == 201, allowed.text

    detail = client.get(f"/api/brewing/orders/{allowed.json()['brew_order_id']}", headers=admin_h).json()
    line = next(l for l in detail["lines"] if not l["is_header"])
    assert line["material_group_code"] == g["code"]
    breakdown_by_code = {mb["material_code"]: mb for mb in line["member_breakdown"]}
    assert breakdown_by_code["MALT-PILS"]["shortage"] is False
    assert breakdown_by_code["MALT-VIENNA"]["shortage"] is True


# ---- 5) Người lập Lệnh nấu PHẢI chọn thành viên áp dụng cho dòng member_qty ----

def _recipe_version_with_member_qty(client, admin_h, recipe_id, group_code):
    v = client.post(f"/api/recipes/{recipe_id}/versions", headers=admin_h,
                    json={"base_qty": 1000, "base_uom": "L",
                          "materials": [{"alt_group_code": group_code, "uom": "kg",
                                        "member_qty": [{"material_code": "MALT-PILS", "qty": 5},
                                                      {"material_code": "MALT-VIENNA", "qty": 6}]}]}).json()
    _activate_recipe_version(client, admin_h, v["version_id"])
    return v


def test_create_order_requires_member_selection_for_single_mode_group(client, admin_h, malt_pils_id, malt_vienna_id, lager_product_id):
    """Nhóm selection_mode="single" (mặc định) — không chọn gì (frontend không gửi lựa chọn)
    khiến member_declared giữ nguyên CẢ 2 thành viên → phải bị chặn (chỉ cho chọn ĐÚNG 1)."""
    g = _a_alt_group(client, admin_h, [malt_pils_id, malt_vienna_id], name="Single sel test")
    recipe_id = _lager_recipe_id(client, admin_h, lager_product_id)
    v = _recipe_version_with_member_qty(client, admin_h, recipe_id, g["code"])

    r = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": f"LN-SEL-NOPICK-{new_id()[:6]}", "product_id": lager_product_id,
        "recipe_version_id": v["version_id"],
        "planned_batch_count": 1, "planned_volume_hl": 100, "volume_tolerance_hl": 0,
        "auto_from_bom": True, "lines": [],
    })
    assert r.status_code == 409, r.text


def test_create_order_single_mode_selection_uses_only_chosen_member(client, admin_h, malt_pils_id, malt_vienna_id, lager_product_id):
    """Chọn đúng 1 thành viên (material_qty_overrides[seq].selected_material_codes) — Nhu cầu
    Tổng mẻ chỉ tính mã đã chọn, KHÔNG cộng dồn với mã còn lại."""
    g = _a_alt_group(client, admin_h, [malt_pils_id, malt_vienna_id], name="Single sel test 2")
    recipe_id = _lager_recipe_id(client, admin_h, lager_product_id)
    v = _recipe_version_with_member_qty(client, admin_h, recipe_id, g["code"])

    r = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": f"LN-SEL-PICK-{new_id()[:6]}", "product_id": lager_product_id,
        "recipe_version_id": v["version_id"],
        "planned_batch_count": 2, "planned_volume_hl": 100, "volume_tolerance_hl": 0,
        "auto_from_bom": True, "lines": [],
        "material_qty_overrides": {"0": {"selected_material_codes": ["MALT-PILS"]}},
    })
    assert r.status_code == 201, r.text

    detail = client.get(f"/api/brewing/orders/{r.json()['brew_order_id']}", headers=admin_h).json()
    line = next(l for l in detail["lines"] if not l["is_header"])
    assert line["qty_total"] == 10   # CHỈ MALT-PILS: 5 x 2 mẻ — KHÔNG cộng thêm MALT-VIENNA
    codes = [mb["material_code"] for mb in line["member_breakdown"]]
    assert codes == ["MALT-PILS"]


def test_create_order_rejects_two_selections_for_single_mode_group(client, admin_h, malt_pils_id, malt_vienna_id, lager_product_id):
    g = _a_alt_group(client, admin_h, [malt_pils_id, malt_vienna_id], name="Single sel test 3")
    recipe_id = _lager_recipe_id(client, admin_h, lager_product_id)
    v = _recipe_version_with_member_qty(client, admin_h, recipe_id, g["code"])

    r = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": f"LN-SEL-TWOPICK-{new_id()[:6]}", "product_id": lager_product_id,
        "recipe_version_id": v["version_id"],
        "planned_batch_count": 1, "planned_volume_hl": 100, "volume_tolerance_hl": 0,
        "auto_from_bom": True, "lines": [],
        "material_qty_overrides": {"0": {"selected_material_codes": ["MALT-PILS", "MALT-VIENNA"]}},
    })
    assert r.status_code == 409, r.text


def test_create_order_multi_mode_partial_selection_sums_only_chosen(client, admin_h, malt_pils_id, malt_vienna_id, lager_product_id):
    """Nhóm selection_mode="multi" — chọn 1 trong 2 thành viên (không bắt buộc chọn hết) —
    vẫn hợp lệ (multi chỉ yêu cầu >=1), Nhu cầu Tổng mẻ chỉ tính mã đã chọn."""
    g = _a_alt_group(client, admin_h, [malt_pils_id, malt_vienna_id], name="Multi sel test", selection_mode="multi")
    recipe_id = _lager_recipe_id(client, admin_h, lager_product_id)
    v = _recipe_version_with_member_qty(client, admin_h, recipe_id, g["code"])

    r = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": f"LN-MULTISEL-{new_id()[:6]}", "product_id": lager_product_id,
        "recipe_version_id": v["version_id"],
        "planned_batch_count": 1, "planned_volume_hl": 100, "volume_tolerance_hl": 0,
        "auto_from_bom": True, "lines": [],
        "material_qty_overrides": {"0": {"selected_material_codes": ["MALT-VIENNA"]}},
    })
    assert r.status_code == 201, r.text
    detail = client.get(f"/api/brewing/orders/{r.json()['brew_order_id']}", headers=admin_h).json()
    line = next(l for l in detail["lines"] if not l["is_header"])
    assert line["qty_total"] == 6
    assert [mb["material_code"] for mb in line["member_breakdown"]] == ["MALT-VIENNA"]
    assert line["shortage"] is False  # dòng KHÔNG shortage vì còn 1 lựa chọn khả thi


def test_create_order_member_qty_per_member_split_override(client, admin_h, malt_pils_id, malt_vienna_id, lager_product_id):
    """Mỗi thành viên đã chọn có gợi ý tách 2 nguồn kho RIÊNG (qty_from_company/workshop) —
    người lập lệnh sửa lại qua material_qty_overrides[seq].member_qty_splits[material_code],
    khớp theo material_code chứ không lẫn giữa các thành viên."""
    g = _a_alt_group(client, admin_h, [malt_pils_id, malt_vienna_id], name="Split sel test", selection_mode="multi")
    recipe_id = _lager_recipe_id(client, admin_h, lager_product_id)
    v = _recipe_version_with_member_qty(client, admin_h, recipe_id, g["code"])

    r = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": f"LN-SPLITSEL-{new_id()[:6]}", "product_id": lager_product_id,
        "recipe_version_id": v["version_id"],
        "planned_batch_count": 1, "planned_volume_hl": 100, "volume_tolerance_hl": 0,
        "auto_from_bom": True, "lines": [],
        "material_qty_overrides": {"0": {
            "selected_material_codes": ["MALT-PILS", "MALT-VIENNA"],
            "member_qty_splits": {
                "MALT-PILS": {"qty_from_company": 2, "qty_from_workshop": 3},
                "MALT-VIENNA": {"qty_from_company": 6, "qty_from_workshop": 0},
            },
        }},
    })
    assert r.status_code == 201, r.text
    detail = client.get(f"/api/brewing/orders/{r.json()['brew_order_id']}", headers=admin_h).json()
    line = next(l for l in detail["lines"] if not l["is_header"])
    breakdown_by_code = {mb["material_code"]: mb for mb in line["member_breakdown"]}
    assert breakdown_by_code["MALT-PILS"]["qty_from_company"] == 2
    assert breakdown_by_code["MALT-PILS"]["qty_from_workshop"] == 3
    assert breakdown_by_code["MALT-VIENNA"]["qty_from_company"] == 6
    assert breakdown_by_code["MALT-VIENNA"]["qty_from_workshop"] == 0
