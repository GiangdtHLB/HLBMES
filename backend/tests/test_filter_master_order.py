"""Test Lệnh lọc LỚN (FilterMasterOrder) chứa nhiều "lệnh lọc nhỏ" (FilterOrder) bên
trong — mỗi lệnh nhỏ tự chọn phối/không phối + tank riêng + vật tư riêng + thể tích kế
hoạch riêng; thực hiện lọc (POST /brewing/filters) trên 1 lệnh nhỏ không ảnh hưởng lệnh
nhỏ còn lại; sửa/xóa lệnh lớn chặn khi bất kỳ lệnh nhỏ nào đã thực hiện."""

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


def _a_material_with_stock(client, admin_h, code, qty_company=100):
    m = client.post("/api/materials", headers=admin_h,
                    json={"code": code, "name": f"Vật tư {code}", "uom": "kg"})
    assert m.status_code == 201, m.text
    material_id = m.json()["material_id"]
    r = client.post("/api/warehouse/receive", headers=admin_h,
                    json={"lot_code": f"LOT-{code}", "material_id": material_id, "quantity": qty_company,
                          "uom": "kg", "location": "Kho công ty"})
    assert r.status_code == 200, r.text
    return material_id


@pytest.fixture(scope="module")
def lager_product_id(client, admin_h):
    products = client.get("/api/products", headers=admin_h).json()
    return next(p["product_id"] for p in products if p["code"] == "BIA-LAGER")


def _child(blend_mode, tank_ferment_ids, planned_volume_hl=50.0, volume_tolerance_hl=0.0, lines=None, kcs_lot_no=None):
    """Mỗi tank lên men trong lệnh nhỏ tự có thể tích dịch lọc kế hoạch riêng (schema mới) —
    helper này chia đều planned_volume_hl cho các tank được chọn (mặc định 50hl/tank, luôn
    trong hạn mức 100hl tồn CCT của 1 ferment mới tạo qua _setup_ferment)."""
    per_tank = planned_volume_hl / len(tank_ferment_ids)
    return {"blend_mode": blend_mode,
            "tanks": [{"ferment_id": fid, "planned_v_dich_hl": per_tank} for fid in tank_ferment_ids],
            "volume_tolerance_hl": volume_tolerance_hl,
            "lines": lines or [], "kcs_lot_no": kcs_lot_no}


def test_create_master_order_with_two_different_children(client, admin_h, vanhanh_h, lager_product_id):
    f1 = _setup_ferment(client, admin_h, vanhanh_h, "FMO-A")
    f2 = _setup_ferment(client, admin_h, vanhanh_h, "FMO-B", product_id=lager_product_id)
    f3 = _setup_ferment(client, admin_h, vanhanh_h, "FMO-C", product_id=lager_product_id)
    mat1 = _a_material_with_stock(client, admin_h, "FMO-MAT1")
    mat2 = _a_material_with_stock(client, admin_h, "FMO-MAT2")

    payload = {"order_code": "LOC-LON-01", "note": "Lệnh lớn test",
               "children": [
                   _child("khong_phoi", [f1], planned_volume_hl=80, lines=[{"material_id": mat1, "quantity": 5}]),
                   _child("phoi", [f2, f3], planned_volume_hl=150, volume_tolerance_hl=10,
                          lines=[{"material_id": mat2, "quantity": 8}], kcs_lot_no="KCS-99"),
               ]}
    created = client.post("/api/brewing/filter-master-orders", headers=admin_h, json=payload)
    assert created.status_code == 201, created.text
    master_id = created.json()["filter_master_order_id"]
    assert created.json()["order_code"] == "LOC-LON-01"

    listed = client.get("/api/brewing/filter-master-orders", headers=admin_h).json()
    row = next(m for m in listed if m["filter_master_order_id"] == master_id)
    assert len(row["children"]) == 2
    assert row["is_complete_all"] is False
    assert row["planned_total_hl"] == 230

    detail = client.get(f"/api/brewing/filter-master-orders/{master_id}", headers=admin_h).json()
    c1, c2 = detail["children"]
    assert c1["seq"] == 1 and c1["blend_mode"] == "khong_phoi" and len(c1["tanks"]) == 1
    assert c1["planned_volume_hl"] == 80
    assert len(c1["lines"]) == 1 and c1["lines"][0]["material_id"] == mat1
    assert c2["seq"] == 2 and c2["blend_mode"] == "phoi" and len(c2["tanks"]) == 2
    assert c2["planned_volume_hl"] == 150 and c2["kcs_lot_no"] == "KCS-99"
    assert len(c2["lines"]) == 1 and c2["lines"][0]["material_id"] == mat2

    # order_code của lệnh nhỏ tự sinh, khác mã lệnh lớn, và khác nhau giữa 2 lệnh nhỏ.
    orders = client.get("/api/brewing/filter-orders", headers=admin_h).json()
    child_orders = [o for o in orders if o["master_order_id"] == master_id]
    assert len(child_orders) == 2
    codes = {o["order_code"] for o in child_orders}
    assert "LOC-LON-01" not in codes
    assert len(codes) == 2
    for o in child_orders:
        assert o["master_order_code"] == "LOC-LON-01"


def test_create_master_order_requires_at_least_one_child(client, admin_h, vanhanh_h):
    f1 = _setup_ferment(client, admin_h, vanhanh_h, "FMO-EMPTY")
    r = client.post("/api/brewing/filter-master-orders", headers=admin_h,
                    json={"order_code": "LOC-LON-EMPTY", "children": []})
    assert r.status_code == 409, r.text


def test_create_master_order_duplicate_code_blocked(client, admin_h, vanhanh_h):
    f1 = _setup_ferment(client, admin_h, vanhanh_h, "FMO-DUP1")
    ok = client.post("/api/brewing/filter-master-orders", headers=admin_h,
                     json={"order_code": "LOC-LON-DUP", "children": [_child("khong_phoi", [f1])]})
    assert ok.status_code == 201, ok.text

    f2 = _setup_ferment(client, admin_h, vanhanh_h, "FMO-DUP2")
    dup = client.post("/api/brewing/filter-master-orders", headers=admin_h,
                      json={"order_code": "LOC-LON-DUP", "children": [_child("khong_phoi", [f2])]})
    assert dup.status_code == 409, dup.text


def test_executing_one_child_does_not_complete_sibling(client, admin_h, vanhanh_h):
    f1 = _setup_ferment(client, admin_h, vanhanh_h, "FMO-EXEC1")
    f2 = _setup_ferment(client, admin_h, vanhanh_h, "FMO-EXEC2")
    payload = {"order_code": "LOC-LON-EXEC", "children": [
        _child("khong_phoi", [f1], planned_volume_hl=100),
        _child("khong_phoi", [f2], planned_volume_hl=100),
    ]}
    created = client.post("/api/brewing/filter-master-orders", headers=admin_h, json=payload)
    assert created.status_code == 201, created.text
    master_id = created.json()["filter_master_order_id"]
    detail = client.get(f"/api/brewing/filter-master-orders/{master_id}", headers=admin_h).json()
    child0_id, child1_id = detail["children"][0]["filter_order_id"], detail["children"][1]["filter_order_id"]

    filt = client.post("/api/brewing/filters", headers=vanhanh_h,
                       json={"filter_code": "FL-FMOEXEC1", "beer_type": "Bia test",
                             "filter_order_id": child0_id, "to_bbt": "BBT-FMOEXEC1"})
    assert filt.status_code == 201, filt.text
    filter_id = filt.json()["filter_id"]
    tanks = client.get(f"/api/brewing/filters/{filter_id}/tanks", headers=admin_h).json()
    fin = client.post(f"/api/brewing/filters/{filter_id}/tanks/{tanks[0]['line_id']}/finish", headers=vanhanh_h,
                      json={"v_dich_hl": 100, "nuoc_bai_khi_hl": 0,
                            "batch_number": "B-FMOEXEC1", "order_number": "O-FMOEXEC1", "batch_seq_no": "1"})
    assert fin.status_code == 200, fin.text

    mid = client.get(f"/api/brewing/filter-master-orders/{master_id}", headers=admin_h).json()
    c0, c1 = mid["children"]
    assert c0["is_complete"] is True and c0["is_executed"] is True
    assert c1["is_complete"] is False and c1["is_executed"] is False
    assert mid["is_complete_all"] is False

    filt2 = client.post("/api/brewing/filters", headers=vanhanh_h,
                        json={"filter_code": "FL-FMOEXEC2", "beer_type": "Bia test",
                              "filter_order_id": child1_id, "to_bbt": "BBT-FMOEXEC2"})
    assert filt2.status_code == 201, filt2.text
    filter_id2 = filt2.json()["filter_id"]
    tanks2 = client.get(f"/api/brewing/filters/{filter_id2}/tanks", headers=admin_h).json()
    fin2 = client.post(f"/api/brewing/filters/{filter_id2}/tanks/{tanks2[0]['line_id']}/finish", headers=vanhanh_h,
                       json={"v_dich_hl": 100, "nuoc_bai_khi_hl": 0,
                             "batch_number": "B-FMOEXEC2", "order_number": "O-FMOEXEC2", "batch_seq_no": "1"})
    assert fin2.status_code == 200, fin2.text

    final = client.get(f"/api/brewing/filter-master-orders/{master_id}", headers=admin_h).json()
    assert final["is_complete_all"] is True


def test_update_master_order_blocked_once_any_child_executed(client, admin_h, vanhanh_h):
    f1 = _setup_ferment(client, admin_h, vanhanh_h, "FMO-UPD1")
    f2 = _setup_ferment(client, admin_h, vanhanh_h, "FMO-UPD2")
    created = client.post("/api/brewing/filter-master-orders", headers=admin_h,
                          json={"order_code": "LOC-LON-UPD", "children": [
                              _child("khong_phoi", [f1]), _child("khong_phoi", [f2])]})
    assert created.status_code == 201, created.text
    master_id = created.json()["filter_master_order_id"]

    # Chưa thực hiện gì -> sửa được (đổi thành 1 lệnh nhỏ khác thể tích).
    f3 = _setup_ferment(client, admin_h, vanhanh_h, "FMO-UPD3")
    edited = client.put(f"/api/brewing/filter-master-orders/{master_id}", headers=admin_h,
                        json={"order_code": "LOC-LON-UPD", "children": [_child("khong_phoi", [f3], planned_volume_hl=77)]})
    assert edited.status_code == 200, edited.text
    detail = client.get(f"/api/brewing/filter-master-orders/{master_id}", headers=admin_h).json()
    assert len(detail["children"]) == 1
    assert detail["children"][0]["planned_volume_hl"] == 77

    child_id = detail["children"][0]["filter_order_id"]
    filt = client.post("/api/brewing/filters", headers=vanhanh_h,
                       json={"filter_code": "FL-FMOUPD", "beer_type": "Bia test", "filter_order_id": child_id,
                             "to_bbt": "BBT-FMOUPD"})
    assert filt.status_code == 201, filt.text

    blocked = client.put(f"/api/brewing/filter-master-orders/{master_id}", headers=admin_h,
                         json={"order_code": "LOC-LON-UPD", "children": [_child("khong_phoi", [f3])]})
    assert blocked.status_code == 409, blocked.text


def test_delete_master_order_cascade_when_not_executed(client, admin_h, vanhanh_h):
    f1 = _setup_ferment(client, admin_h, vanhanh_h, "FMO-DEL1")
    f2 = _setup_ferment(client, admin_h, vanhanh_h, "FMO-DEL2")
    created = client.post("/api/brewing/filter-master-orders", headers=admin_h,
                          json={"order_code": "LOC-LON-DEL", "children": [
                              _child("khong_phoi", [f1]), _child("khong_phoi", [f2])]})
    assert created.status_code == 201, created.text
    master_id = created.json()["filter_master_order_id"]
    detail = client.get(f"/api/brewing/filter-master-orders/{master_id}", headers=admin_h).json()
    child_ids = [c["filter_order_id"] for c in detail["children"]]

    deleted = client.delete(f"/api/brewing/filter-master-orders/{master_id}", headers=admin_h)
    assert deleted.status_code == 204, deleted.text

    gone = client.get(f"/api/brewing/filter-master-orders/{master_id}", headers=admin_h)
    assert gone.status_code == 404, gone.text
    for cid in child_ids:
        child_gone = client.get(f"/api/brewing/filter-orders/{cid}", headers=admin_h)
        assert child_gone.status_code == 404, child_gone.text


def test_delete_master_order_blocked_once_any_child_executed(client, admin_h, vanhanh_h):
    f1 = _setup_ferment(client, admin_h, vanhanh_h, "FMO-DELBLK1")
    f2 = _setup_ferment(client, admin_h, vanhanh_h, "FMO-DELBLK2")
    created = client.post("/api/brewing/filter-master-orders", headers=admin_h,
                          json={"order_code": "LOC-LON-DELBLK", "children": [
                              _child("khong_phoi", [f1]), _child("khong_phoi", [f2])]})
    assert created.status_code == 201, created.text
    master_id = created.json()["filter_master_order_id"]
    detail = client.get(f"/api/brewing/filter-master-orders/{master_id}", headers=admin_h).json()
    child0_id = detail["children"][0]["filter_order_id"]

    filt = client.post("/api/brewing/filters", headers=vanhanh_h,
                       json={"filter_code": "FL-FMODELBLK", "beer_type": "Bia test", "filter_order_id": child0_id,
                             "to_bbt": "BBT-FMODELBLK"})
    assert filt.status_code == 201, filt.text

    blocked = client.delete(f"/api/brewing/filter-master-orders/{master_id}", headers=admin_h)
    assert blocked.status_code == 409, blocked.text


def test_flat_filter_order_endpoint_still_works_standalone(client, admin_h, vanhanh_h):
    """Endpoint phẳng cũ (POST /brewing/filter-orders) vẫn tạo được lệnh KHÔNG có lệnh
    lớn cha (master_order_id = None) — bảo đảm tương thích ngược với toàn bộ test cũ."""
    f1 = _setup_ferment(client, admin_h, vanhanh_h, "FMO-FLAT")
    r = client.post("/api/brewing/filter-orders", headers=admin_h,
                    json={"order_code": "LOC-FLAT-STANDALONE", "blend_mode": "khong_phoi",
                          "tank_ferment_ids": [f1], "planned_volume_hl": 100, "volume_tolerance_hl": 0})
    assert r.status_code == 201, r.text
    order_id = r.json()["filter_order_id"]
    detail = client.get(f"/api/brewing/filter-orders/{order_id}", headers=admin_h).json()
    assert detail["master_order_id"] is None
    assert detail["master_order_code"] is None


def test_child_planned_volume_is_sum_of_per_tank_volumes(client, admin_h, vanhanh_h):
    """Mỗi tank trong 1 lệnh nhỏ tự khai báo thể tích riêng (không đều nhau) — thể tích
    tổng của lệnh nhỏ phải bằng tổng các thể tích tank, và mỗi tank trả về đúng
    planned_v_dich_hl riêng của nó (không phải chia đều)."""
    f1 = _setup_ferment(client, admin_h, vanhanh_h, "FMO-PERTANK1")
    f2 = _setup_ferment(client, admin_h, vanhanh_h, "FMO-PERTANK2")
    payload = {"order_code": "LOC-LON-PERTANK", "children": [
        {"blend_mode": "phoi",
         "tanks": [{"ferment_id": f1, "planned_v_dich_hl": 30}, {"ferment_id": f2, "planned_v_dich_hl": 90}],
         "volume_tolerance_hl": 0, "lines": [], "kcs_lot_no": None},
    ]}
    created = client.post("/api/brewing/filter-master-orders", headers=admin_h, json=payload)
    assert created.status_code == 201, created.text
    master_id = created.json()["filter_master_order_id"]

    detail = client.get(f"/api/brewing/filter-master-orders/{master_id}", headers=admin_h).json()
    child = detail["children"][0]
    assert child["planned_volume_hl"] == 120
    by_ferment = {t["ferment_id"]: t["planned_v_dich_hl"] for t in child["tanks"]}
    assert by_ferment[f1] == 30
    assert by_ferment[f2] == 90


def test_create_master_order_blocks_cross_child_overcommit_on_same_tank(client, admin_h, vanhanh_h):
    """2 lệnh nhỏ trong CÙNG 1 lần tạo lệnh lớn, cả hai cùng chọn 1 tank lên men — nếu tổng
    thể tích kế hoạch của cả hai vượt quá lượng CCT thực đang tồn trong tank đó, server phải
    chặn (409), không cho tạo, giống cách vật tư bị chặn khi vượt tồn kho."""
    f1 = _setup_ferment(client, admin_h, vanhanh_h, "FMO-OVERCOMMIT")
    payload = {"order_code": "LOC-LON-OVERCOMMIT", "children": [
        _child("khong_phoi", [f1], planned_volume_hl=60),
        _child("khong_phoi", [f1], planned_volume_hl=60),
    ]}
    r = client.post("/api/brewing/filter-master-orders", headers=admin_h, json=payload)
    assert r.status_code == 409, r.text

    listed = client.get("/api/brewing/filter-master-orders", headers=admin_h).json()
    assert all(m["order_code"] != "LOC-LON-OVERCOMMIT" for m in listed)
