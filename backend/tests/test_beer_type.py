"""Test Loại bia (BeerType) — tách khỏi Dịch bia (Product, phân biệt cả độ oP), dùng để tra
chỉ tiêu QC ở Lọc/Chiết (stage=loc|thanh_pham) thay vì product_id cụ thể. Xem
services/filter_order.py::_validate_tanks (suy luận/yêu cầu chọn Loại bia lúc lập lệnh lọc)
và services/qc_catalog.py::PRODUCT_SCOPED_STAGES (stage nào tra theo product_id vs beer_type_id)."""

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


@pytest.fixture(scope="module")
def vanhanh_h(client):
    return _login(client, "vanhanh", "123456")


def _a_beer_type(client, admin_h, code, name):
    r = client.post("/api/beer-types", headers=admin_h, json={"code": code, "name": name})
    assert r.status_code == 201, r.text
    return r.json()["beer_type_id"]


def _a_product(client, admin_h, code, name, beer_type_id=None):
    r = client.post("/api/products", headers=admin_h,
                    json={"code": code, "name": name, "uom": "L", "beer_type_id": beer_type_id})
    assert r.status_code == 201, r.text
    return r.json()["product_id"]


def _a_brew_order(client, admin_h, order_code):
    r = client.post("/api/brewing/orders", headers=admin_h,
                    json={"order_code": order_code, "auto_from_bom": False, "planned_volume_hl": 100})
    assert r.status_code == 201, r.text
    return r.json()["brew_order_id"]


def _setup_ferment(client, admin_h, vanhanh_h, suffix, product_id=None):
    """Tạo 1 mã nấu + lô LM + duyệt KCS luôn — trả về ferment_id."""
    order_id = _a_brew_order(client, admin_h, f"LN-{suffix}")
    b = client.post("/api/brewing/brews", headers=vanhanh_h,
                    json={"brew_code": f"BR-{suffix}", "wort_type": "Dịch test", "volume_hl": 100,
                          "lm_code": f"LM-{suffix}", "tank_lm": f"T-{suffix}",
                          "brew_order_id": order_id, "product_id": product_id})
    assert b.status_code == 201, b.text
    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment = next(f for f in ferments if f["lm_code"] == f"LM-{suffix}")
    ok = client.post(f"/api/brewing/ferments/{ferment['ferment_id']}/approve", headers=admin_h)
    assert ok.status_code == 200, ok.text
    return ferment["ferment_id"]


def _a_filter_order(client, admin_h, order_code, ferment_ids, blend_mode="khong_phoi", beer_type_id=None,
                    planned_volume_hl=1000.0):
    payload = {"order_code": order_code, "blend_mode": blend_mode, "tank_ferment_ids": ferment_ids,
               "planned_volume_hl": planned_volume_hl, "volume_tolerance_hl": 0.0}
    if beer_type_id is not None:
        payload["beer_type_id"] = beer_type_id
    return client.post("/api/brewing/filter-orders", headers=admin_h, json=payload)


def _make_group_with_param(client, admin_h, suffix):
    p = client.post("/api/qc/parameters", headers=admin_h,
                    json={"code": f"CT_{suffix}", "name": f"Chỉ tiêu {suffix}", "lsl": 1, "usl": 10})
    assert p.status_code == 201, p.text
    param_id = p.json()["param_id"]
    g = client.post("/api/qc/groups", headers=admin_h,
                    json={"code": f"GRP_{suffix}", "name": f"Nhóm {suffix}"})
    assert g.status_code == 201, g.text
    group_id = g.json()["group_id"]
    it = client.post(f"/api/qc/groups/{group_id}/items", headers=admin_h,
                     json={"param_id": param_id, "mandatory": True})
    assert it.status_code == 201, it.text
    return group_id, f"CT_{suffix}"


def test_beer_type_crud(client, admin_h):
    bt_id = _a_beer_type(client, admin_h, "BTCRUD", "Loại bia CRUD test")
    listed = client.get("/api/beer-types", headers=admin_h).json()
    assert any(bt["beer_type_id"] == bt_id for bt in listed)

    upd = client.put(f"/api/beer-types/{bt_id}", headers=admin_h,
                     json={"code": "BTCRUD", "name": "Loại bia CRUD (sửa)", "note": "ghi chú"})
    assert upd.status_code == 200, upd.text
    assert upd.json()["name"] == "Loại bia CRUD (sửa)"
    assert upd.json()["note"] == "ghi chú"

    dup = client.post("/api/beer-types", headers=admin_h, json={"code": "BTCRUD", "name": "Trùng mã"})
    assert dup.status_code == 403, dup.text  # PermissionError_ dùng cho "đã tồn tại", mirror create_product


def test_product_can_be_assigned_to_beer_type(client, admin_h):
    bt_id = _a_beer_type(client, admin_h, "BTASSIGN", "Loại bia gán Dịch bia")
    product_id = _a_product(client, admin_h, "DB-ASSIGN01", "Dịch bia gán test")

    upd = client.put(f"/api/products/{product_id}", headers=admin_h,
                     json={"code": "DB-ASSIGN01", "name": "Dịch bia gán test", "uom": "L",
                           "beer_type_id": bt_id})
    assert upd.status_code == 200, upd.text
    assert upd.json()["beer_type_id"] == bt_id


def test_khong_phoi_auto_resolves_beer_type_from_single_tank(client, admin_h, vanhanh_h):
    bt_id = _a_beer_type(client, admin_h, "SAPPHIRE1", "Sapphire")
    product_id = _a_product(client, admin_h, "SAP-13OP-01", "Dịch Sapphire 13oP", beer_type_id=bt_id)
    ferment_id = _setup_ferment(client, admin_h, vanhanh_h, "BT-KP01", product_id=product_id)

    r = _a_filter_order(client, admin_h, "LOC-BT-KP01", [ferment_id])
    assert r.status_code == 201, r.text
    order_id = r.json()["filter_order_id"]
    detail = client.get(f"/api/brewing/filter-orders/{order_id}", headers=admin_h).json()
    assert detail["beer_type_id"] == bt_id
    assert detail["beer_type_code"] == "SAPPHIRE1"


def test_phoi_two_different_products_same_beer_type_auto_resolves(client, admin_h, vanhanh_h):
    """Phối 1 tank Sapphire-13oP + 1 tank Sapphire-14oP (2 Dịch bia KHÁC nhau nhưng CÙNG 1
    Loại bia Sapphire) phải tự suy ra đúng Loại bia, KHÔNG còn bị chặn 'khác dịch bia' như
    hành vi cũ."""
    bt_id = _a_beer_type(client, admin_h, "SAPPHIRE2", "Sapphire")
    p13 = _a_product(client, admin_h, "SAP-13OP-02", "Dịch Sapphire 13oP", beer_type_id=bt_id)
    p14 = _a_product(client, admin_h, "SAP-14OP-02", "Dịch Sapphire 14oP", beer_type_id=bt_id)
    f13 = _setup_ferment(client, admin_h, vanhanh_h, "BT-PH01A", product_id=p13)
    f14 = _setup_ferment(client, admin_h, vanhanh_h, "BT-PH01B", product_id=p14)

    r = _a_filter_order(client, admin_h, "LOC-BT-PH01", [f13, f14], blend_mode="phoi")
    assert r.status_code == 201, r.text
    order_id = r.json()["filter_order_id"]
    detail = client.get(f"/api/brewing/filter-orders/{order_id}", headers=admin_h).json()
    assert detail["beer_type_id"] == bt_id


def test_phoi_across_different_beer_types_requires_and_validates_choice(client, admin_h, vanhanh_h):
    bt_a = _a_beer_type(client, admin_h, "TYPEA", "Loại A")
    bt_b = _a_beer_type(client, admin_h, "TYPEB", "Loại B")
    pa = _a_product(client, admin_h, "DB-TYPEA", "Dịch loại A", beer_type_id=bt_a)
    pb = _a_product(client, admin_h, "DB-TYPEB", "Dịch loại B", beer_type_id=bt_b)
    fa = _setup_ferment(client, admin_h, vanhanh_h, "BT-XT01A", product_id=pa)
    fb = _setup_ferment(client, admin_h, vanhanh_h, "BT-XT01B", product_id=pb)

    missing = _a_filter_order(client, admin_h, "LOC-BT-XT01", [fa, fb], blend_mode="phoi")
    assert missing.status_code == 409, missing.text
    assert "chọn 1 Loại bia" in missing.json()["detail"]

    invalid_choice = _a_filter_order(client, admin_h, "LOC-BT-XT01B", [fa, fb], blend_mode="phoi",
                                     beer_type_id="not-a-real-beer-type-id")
    assert invalid_choice.status_code == 409, invalid_choice.text

    ok = _a_filter_order(client, admin_h, "LOC-BT-XT01C", [fa, fb], blend_mode="phoi", beer_type_id=bt_b)
    assert ok.status_code == 201, ok.text
    detail = client.get(f"/api/brewing/filter-orders/{ok.json()['filter_order_id']}", headers=admin_h).json()
    assert detail["beer_type_id"] == bt_b


def test_tank_with_product_missing_beer_type_is_blocked(client, admin_h, vanhanh_h):
    product_id = _a_product(client, admin_h, "DB-NOTYPE01", "Dịch chưa gán loại bia")
    ferment_id = _setup_ferment(client, admin_h, vanhanh_h, "BT-NOTYPE01", product_id=product_id)
    r = _a_filter_order(client, admin_h, "LOC-BT-NOTYPE01", [ferment_id])
    assert r.status_code == 409, r.text
    assert "chưa được gán Loại bia" in r.json()["detail"]


def test_beer_type_inherits_through_filter_and_bottle_and_scopes_qc_across_products(
        client, admin_h, vanhanh_h):
    """Chứng minh mục tiêu chính của tính năng: 2 mẻ lọc xuất phát từ 2 Dịch bia KHÁC nhau
    (13oP/14oP) nhưng CÙNG 1 Loại bia phải kế thừa đúng beer_type_id qua chuỗi lọc→chiết, và
    1 nhóm chỉ tiêu gán theo Loại bia đó (stage loc/thanh_pham) phải áp dụng cho CẢ HAI —
    không phân biệt oP."""
    bt_id = _a_beer_type(client, admin_h, "SAPPHIRE3", "Sapphire")
    p13 = _a_product(client, admin_h, "SAP-13OP-03", "Dịch Sapphire 13oP", beer_type_id=bt_id)
    p14 = _a_product(client, admin_h, "SAP-14OP-03", "Dịch Sapphire 14oP", beer_type_id=bt_id)

    loc_group_id, loc_code = _make_group_with_param(client, admin_h, "LOCBEERTYPE")
    link_loc = client.post("/api/qc/stage-groups", headers=admin_h,
                           json={"stage": "loc", "group_id": loc_group_id, "beer_type_id": bt_id, "mandatory": True})
    assert link_loc.status_code == 201, link_loc.text
    assert link_loc.json()["beer_type_id"] == bt_id
    assert link_loc.json()["product_id"] is None

    def _run_one_ferment(suffix, product_id):
        ferment_id = _setup_ferment(client, admin_h, vanhanh_h, suffix, product_id=product_id)
        order = _a_filter_order(client, admin_h, f"LOC-{suffix}", [ferment_id])
        assert order.status_code == 201, order.text
        order_id = order.json()["filter_order_id"]
        f = client.post("/api/brewing/filters", headers=vanhanh_h,
                        json={"filter_code": f"FL-{suffix}", "filter_order_id": order_id,
                              "to_bbt": f"BBT-{suffix}"})
        assert f.status_code == 201, f.text
        assert f.json()["beer_type_id"] == bt_id
        return f.json()["filter_id"], f"FL-{suffix}"

    filter_id_13, filter_code_13 = _run_one_ferment("BT-QC13", p13)
    filter_id_14, filter_code_14 = _run_one_ferment("BT-QC14", p14)

    # Chỉ tiêu Lọc gán theo Loại bia áp dụng cho CẢ HAI mẻ lọc dù khác Dịch bia (oP).
    for fcode in (filter_code_13, filter_code_14):
        st = client.get(f"/api/brewing/qc-status?stage=loc&scope_type=filter&scope_id={fcode}"
                        f"&beer_type_id={bt_id}", headers=admin_h).json()
        assert loc_code in st["pending"]

    approve_13_blocked = client.post(f"/api/brewing/filters/{filter_id_13}/approve", headers=admin_h)
    assert approve_13_blocked.status_code == 409, approve_13_blocked.text

    rec = client.post("/api/brewing/qc-results", headers=vanhanh_h,
                      json={"stage": "loc", "scope_type": "filter", "scope_id": filter_code_13,
                            "parameter": loc_code, "value": 5, "lower_limit": 1, "upper_limit": 10})
    assert rec.status_code == 201, rec.text
    # approve_filter yêu cầu đã kết thúc hết tank (xem routers/brewing.py::approve_filter) —
    # phải "Kết thúc" tank TRƯỚC khi duyệt KCS.
    tanks_13 = client.get(f"/api/brewing/filters/{filter_id_13}/tanks", headers=admin_h).json()
    fin_13 = client.post(f"/api/brewing/filters/{filter_id_13}/tanks/{tanks_13[0]['line_id']}/finish",
                         headers=vanhanh_h, json={"v_dich_hl": 100, "nuoc_bai_khi_hl": 0})
    assert fin_13.status_code == 200, fin_13.text
    approve_13_ok = client.post(f"/api/brewing/filters/{filter_id_13}/approve", headers=admin_h)
    assert approve_13_ok.status_code == 200, approve_13_ok.text

    # Mẻ lọc 14oP vẫn bị chặn riêng (chưa khai chỉ tiêu cho CHÍNH nó) — chứng tỏ nhóm áp
    # dụng theo Loại bia (đúng cho cả 2) chứ không phải do trùng mã lọc.
    approve_14_blocked = client.post(f"/api/brewing/filters/{filter_id_14}/approve", headers=admin_h)
    assert approve_14_blocked.status_code == 409, approve_14_blocked.text

    # --- Chiết: BottleRecord kế thừa beer_type_id từ FilterRecord nguồn (13oP) ---
    b = client.post("/api/brewing/bottles", headers=vanhanh_h,
                    json={"bottle_code": "CH-BT-QC13", "from_bbt": "BBT-BT-QC13"})
    assert b.status_code == 201, b.text
    assert b.json()["beer_type_id"] == bt_id
