"""Test Lệnh nấu LỚN (BrewMasterOrder) chứa nhiều "lệnh nấu nhỏ" (BrewOrder) bên trong —
mỗi lệnh nhỏ ứng với đúng 1 dịch bia, tự có sản lượng kế hoạch/sai số/định mức NVL riêng;
tạo mã nấu (POST /brewing/brews) trên 1 lệnh nhỏ không ảnh hưởng lệnh nhỏ còn lại; sửa/xóa
lệnh lớn chặn khi bất kỳ lệnh nhỏ nào đã thực hiện; khóa lô tự suy từ lệnh nhỏ lên lệnh lớn;
picker Tank lên men chỉ hiện tank đang trống."""

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


@pytest.fixture(scope="module")
def lager_product_id(client, admin_h):
    products = client.get("/api/products", headers=admin_h).json()
    return next(p["product_id"] for p in products if p["code"] == "BIA-LAGER")


def _a_brewhouse_line(client, admin_h):
    """Dây chuyền nấu (ProductionLine.kind="brewhouse") dùng cho test — lấy lại nếu đã có
    (idempotent), tạo mới nếu chưa có (seed.py không seed sẵn dây chuyền loại brewhouse)."""
    existing = client.get("/api/lines", headers=admin_h, params={"kind": "brewhouse"}).json()
    if existing:
        return existing[0]["line_id"]
    r = client.post("/api/lines", headers=admin_h,
                    json={"code": "BREW-TEST-01", "name": "Nhà nấu test", "kind": "brewhouse"})
    assert r.status_code == 201, r.text
    return r.json()["line_id"]


@pytest.fixture(scope="module")
def brewhouse_line_id(client, admin_h):
    return _a_brewhouse_line(client, admin_h)


def _child(product_id=None, planned_volume_hl=100.0, volume_tolerance_hl=0.0, lines=None):
    return {"product_id": product_id, "planned_batch_count": 1,
            "planned_volume_hl": planned_volume_hl, "volume_tolerance_hl": volume_tolerance_hl,
            "auto_from_bom": False, "lines": lines or []}


def _declare_pending(client, headers, stage, scope_type, scope_id):
    status = client.get(f"/api/brewing/qc-status?stage={stage}&scope_type={scope_type}&scope_id={scope_id}",
                        headers=headers).json()
    for p in status["required"]:
        if p["code"] in status["pending"]:
            lsl = p["lsl"] if p["lsl"] is not None else 0
            usl = p["usl"] if p["usl"] is not None else lsl + 10
            r = client.post("/api/brewing/qc-results", headers=headers,
                            json={"stage": stage, "scope_type": scope_type, "scope_id": scope_id,
                                  "parameter": p["code"], "value": (lsl + usl) / 2,
                                  "lower_limit": lsl, "upper_limit": usl})
            assert r.status_code == 201, r.text


def _a_brew_record(client, vanhanh_h, brew_order_id, suffix, tank_lm=None):
    """Tạo 1 mã nấu (không gắn tank lên men trừ khi truyền tank_lm) dưới 1 lệnh nấu nhỏ."""
    payload = {"brew_code": f"BR-{suffix}", "wort_type": "Dịch test", "volume_hl": 100,
              "brew_order_id": brew_order_id}
    if tank_lm:
        payload["tank_lm"] = tank_lm
        payload["lm_code"] = f"LM-{suffix}"
    r = client.post("/api/brewing/brews", headers=vanhanh_h, json=payload)
    assert r.status_code == 201, r.text
    return r.json()["brew_id"]


def _finish_batch_ready_to_lock(client, vanhanh_h, brew_id, batch_code, line_id):
    """Tạo 1 mẻ, bấm Kết thúc, khai báo đủ chỉ tiêu bắt buộc "nau" — đủ điều kiện (a) để
    lock_brew (xem services/lot_lock.py::lock_brew)."""
    batch = client.post(f"/api/brewing/brews/{brew_id}/batches", headers=vanhanh_h,
                        json={"batch_code": batch_code, "line_id": line_id})
    assert batch.status_code == 201, batch.text
    batch_id = batch.json()["batch_id"]
    pl = client.put(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/process-log", headers=vanhanh_h,
                   json={"whp_tong_luong_dich_hl": 100})
    assert pl.status_code == 200, pl.text
    fin = client.post(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/finish", headers=vanhanh_h)
    assert fin.status_code == 200, fin.text
    _declare_pending(client, vanhanh_h, "nau", "brew_batch", batch_id)
    return batch_id


def _set_real_actual_volume(client, admin_h, brew_id, batch_code, volume_hl, line_id, finish=True):
    b = client.post(f"/api/brewing/brews/{brew_id}/batches", headers=admin_h,
                    json={"batch_code": batch_code, "line_id": line_id})
    assert b.status_code == 201, b.text
    batch_id = b.json()["batch_id"]
    p = client.put(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/process-log", headers=admin_h,
                   json={"whp_tong_luong_dich_hl": volume_hl})
    assert p.status_code == 200, p.text
    if finish:
        f = client.post(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/finish", headers=admin_h)
        assert f.status_code == 200, f.text
    return batch_id


def test_create_master_order_with_two_children(client, admin_h, lager_product_id):
    mat = client.post("/api/materials", headers=admin_h,
                      json={"code": "BMO-MAT1", "name": "Vật tư BMO-MAT1", "uom": "kg"})
    assert mat.status_code == 201, mat.text
    material_id = mat.json()["material_id"]

    payload = {"order_code": "LN-LON-01", "issued_by": "Người ra lệnh test",
              "executor_unit": "Phân xưởng bia Đông Mai", "warehouse_keeper": "Thủ kho",
              "reference_note": "Căn cứ kế hoạch sản xuất", "safety_note": "Đeo bảo hộ đầy đủ",
              "children": [
                  _child(planned_volume_hl=80, lines=[{"material_id": material_id, "quantity": 5}]),
                  _child(product_id=lager_product_id, planned_volume_hl=150, volume_tolerance_hl=10),
              ]}
    created = client.post("/api/brewing/brew-master-orders", headers=admin_h, json=payload)
    assert created.status_code == 201, created.text
    master_id = created.json()["brew_master_order_id"]
    assert created.json()["order_code"] == "LN-LON-01"

    listed = client.get("/api/brewing/brew-master-orders", headers=admin_h).json()
    row = next(m for m in listed if m["brew_master_order_id"] == master_id)
    assert len(row["children"]) == 2
    assert row["is_complete_all"] is False
    assert row["planned_total_hl"] == 230
    assert row["issued_by"] == "Người ra lệnh test"
    assert row["safety_note"] == "Đeo bảo hộ đầy đủ"

    detail = client.get(f"/api/brewing/brew-master-orders/{master_id}", headers=admin_h).json()
    c1, c2 = detail["children"]
    assert c1["seq"] == 1 and c1["planned_volume_hl"] == 80
    assert len(c1["lines"]) == 1 and c1["lines"][0]["material_id"] == material_id
    assert c2["seq"] == 2 and c2["planned_volume_hl"] == 150 and c2["volume_tolerance_hl"] == 10
    assert c2["product_id"] == lager_product_id

    # order_code của lệnh nhỏ tự sinh, khác mã lệnh lớn, và khác nhau giữa 2 lệnh nhỏ.
    orders = client.get("/api/brewing/orders", headers=admin_h).json()
    child_orders = [o for o in orders if o["master_order_id"] == master_id]
    assert len(child_orders) == 2
    codes = {o["order_code"] for o in child_orders}
    assert "LN-LON-01" not in codes
    assert len(codes) == 2
    for o in child_orders:
        assert o["master_order_code"] == "LN-LON-01"


def test_create_master_order_requires_at_least_one_child(client, admin_h):
    r = client.post("/api/brewing/brew-master-orders", headers=admin_h,
                    json={"order_code": "LN-LON-EMPTY", "children": []})
    assert r.status_code == 409, r.text


def test_create_master_order_duplicate_code_blocked(client, admin_h):
    ok = client.post("/api/brewing/brew-master-orders", headers=admin_h,
                     json={"order_code": "LN-LON-DUP", "children": [_child()]})
    assert ok.status_code == 201, ok.text

    dup = client.post("/api/brewing/brew-master-orders", headers=admin_h,
                      json={"order_code": "LN-LON-DUP", "children": [_child()]})
    assert dup.status_code == 409, dup.text


def test_executing_one_child_does_not_complete_sibling(client, admin_h, vanhanh_h, brewhouse_line_id):
    payload = {"order_code": "LN-LON-EXEC", "children": [
        _child(planned_volume_hl=100), _child(planned_volume_hl=100)]}
    created = client.post("/api/brewing/brew-master-orders", headers=admin_h, json=payload)
    assert created.status_code == 201, created.text
    master_id = created.json()["brew_master_order_id"]
    detail = client.get(f"/api/brewing/brew-master-orders/{master_id}", headers=admin_h).json()
    child0_id, child1_id = detail["children"][0]["brew_order_id"], detail["children"][1]["brew_order_id"]

    brew0 = _a_brew_record(client, vanhanh_h, child0_id, "BMOEXEC1")
    _set_real_actual_volume(client, admin_h, brew0, "911", 100, brewhouse_line_id)

    mid = client.get(f"/api/brewing/brew-master-orders/{master_id}", headers=admin_h).json()
    c0, c1 = mid["children"]
    assert c0["is_complete"] is True and c0["is_executed"] is True
    assert c1["is_complete"] is False and c1["is_executed"] is False
    assert mid["is_complete_all"] is False

    brew1 = _a_brew_record(client, vanhanh_h, child1_id, "BMOEXEC2")
    _set_real_actual_volume(client, admin_h, brew1, "912", 100, brewhouse_line_id)

    final = client.get(f"/api/brewing/brew-master-orders/{master_id}", headers=admin_h).json()
    assert final["is_complete_all"] is True


def test_update_master_order_blocked_once_any_child_executed(client, admin_h, vanhanh_h):
    created = client.post("/api/brewing/brew-master-orders", headers=admin_h,
                          json={"order_code": "LN-LON-UPD", "children": [_child(), _child()]})
    assert created.status_code == 201, created.text
    master_id = created.json()["brew_master_order_id"]

    # Chưa thực hiện gì -> sửa được (đổi thành 1 lệnh nhỏ khác thể tích).
    edited = client.put(f"/api/brewing/brew-master-orders/{master_id}", headers=admin_h,
                        json={"order_code": "LN-LON-UPD", "children": [_child(planned_volume_hl=77)]})
    assert edited.status_code == 200, edited.text
    detail = client.get(f"/api/brewing/brew-master-orders/{master_id}", headers=admin_h).json()
    assert len(detail["children"]) == 1
    assert detail["children"][0]["planned_volume_hl"] == 77

    child_id = detail["children"][0]["brew_order_id"]
    _a_brew_record(client, vanhanh_h, child_id, "BMOUPD")

    blocked = client.put(f"/api/brewing/brew-master-orders/{master_id}", headers=admin_h,
                         json={"order_code": "LN-LON-UPD", "children": [_child()]})
    assert blocked.status_code == 409, blocked.text


def test_delete_master_order_cascade_when_not_executed(client, admin_h):
    created = client.post("/api/brewing/brew-master-orders", headers=admin_h,
                          json={"order_code": "LN-LON-DEL", "children": [_child(), _child()]})
    assert created.status_code == 201, created.text
    master_id = created.json()["brew_master_order_id"]
    detail = client.get(f"/api/brewing/brew-master-orders/{master_id}", headers=admin_h).json()
    child_ids = [c["brew_order_id"] for c in detail["children"]]

    deleted = client.delete(f"/api/brewing/brew-master-orders/{master_id}", headers=admin_h)
    assert deleted.status_code == 204, deleted.text

    gone = client.get(f"/api/brewing/brew-master-orders/{master_id}", headers=admin_h)
    assert gone.status_code == 404, gone.text
    for cid in child_ids:
        child_gone = client.get(f"/api/brewing/orders/{cid}", headers=admin_h)
        assert child_gone.status_code == 404, child_gone.text


def test_delete_master_order_blocked_once_any_child_executed(client, admin_h, vanhanh_h):
    created = client.post("/api/brewing/brew-master-orders", headers=admin_h,
                          json={"order_code": "LN-LON-DELBLK", "children": [_child(), _child()]})
    assert created.status_code == 201, created.text
    master_id = created.json()["brew_master_order_id"]
    detail = client.get(f"/api/brewing/brew-master-orders/{master_id}", headers=admin_h).json()
    child0_id = detail["children"][0]["brew_order_id"]

    _a_brew_record(client, vanhanh_h, child0_id, "BMODELBLK")

    blocked = client.delete(f"/api/brewing/brew-master-orders/{master_id}", headers=admin_h)
    assert blocked.status_code == 409, blocked.text


def test_flat_brew_order_endpoint_still_works_standalone(client, admin_h):
    """Endpoint phẳng cũ (POST /brewing/orders) vẫn tạo được lệnh KHÔNG có lệnh lớn cha
    (master_order_id = None) — bảo đảm tương thích ngược với toàn bộ test cũ."""
    r = client.post("/api/brewing/orders", headers=admin_h,
                    json={"order_code": "LN-FLAT-STANDALONE", "auto_from_bom": False,
                          "planned_volume_hl": 100})
    assert r.status_code == 201, r.text
    order_id = r.json()["brew_order_id"]
    detail = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    assert detail["master_order_id"] is None
    assert detail["master_order_code"] is None


def test_lock_cascade_from_brew_to_master(client, admin_h, vanhanh_h, brewhouse_line_id):
    created = client.post("/api/brewing/brew-master-orders", headers=admin_h,
                          json={"order_code": "LN-LON-LOCK", "children": [_child(), _child()]})
    assert created.status_code == 201, created.text
    master_id = created.json()["brew_master_order_id"]
    detail = client.get(f"/api/brewing/brew-master-orders/{master_id}", headers=admin_h).json()
    child0_id, child1_id = detail["children"][0]["brew_order_id"], detail["children"][1]["brew_order_id"]

    brew0 = _a_brew_record(client, vanhanh_h, child0_id, "BMOLOCK1")
    _finish_batch_ready_to_lock(client, vanhanh_h, brew0, "901", brewhouse_line_id)
    brew1 = _a_brew_record(client, vanhanh_h, child1_id, "BMOLOCK2")
    _finish_batch_ready_to_lock(client, vanhanh_h, brew1, "902", brewhouse_line_id)

    lock0 = client.post(f"/api/brewing/brews/{brew0}/lock-lot", headers=admin_h)
    assert lock0.status_code == 200, lock0.text
    mid = client.get(f"/api/brewing/brew-master-orders/{master_id}", headers=admin_h).json()
    assert mid["locked"] is False, "Chỉ 1 trong 2 lệnh nhỏ khóa — lệnh lớn chưa được tự khóa."

    lock1 = client.post(f"/api/brewing/brews/{brew1}/lock-lot", headers=admin_h)
    assert lock1.status_code == 200, lock1.text
    mid = client.get(f"/api/brewing/brew-master-orders/{master_id}", headers=admin_h).json()
    assert mid["locked"] is True, "Cả 2 lệnh nhỏ đã khóa — lệnh lớn phải tự khóa theo."

    unlock0 = client.post(f"/api/brewing/brews/{brew0}/unlock-lot", headers=admin_h)
    assert unlock0.status_code == 200, unlock0.text
    mid = client.get(f"/api/brewing/brew-master-orders/{master_id}", headers=admin_h).json()
    assert mid["locked"] is False, "Mở khóa 1 lệnh nhỏ — lệnh lớn phải tự mở khóa ngay."


def test_available_ferment_tanks_excludes_occupied(client, admin_h, vanhanh_h):
    free = client.post("/api/lines", headers=admin_h,
                       json={"code": "TANK-AFT-FREE", "name": "Tank AFT trống", "kind": "tank"})
    assert free.status_code == 201, free.text
    occ = client.post("/api/lines", headers=admin_h,
                      json={"code": "TANK-AFT-OCC", "name": "Tank AFT bận", "kind": "tank"})
    assert occ.status_code == 201, occ.text

    order = client.post("/api/brewing/orders", headers=admin_h,
                       json={"order_code": "LN-AFT", "auto_from_bom": False, "planned_volume_hl": 100})
    assert order.status_code == 201, order.text
    _a_brew_record(client, vanhanh_h, order.json()["brew_order_id"], "AFT", tank_lm="TANK-AFT-OCC")

    tanks = client.get("/api/brewing/ferment-tanks", headers=admin_h).json()
    by_code = {t["code"]: t for t in tanks}
    assert by_code["TANK-AFT-FREE"]["occupied"] is False
    assert by_code["TANK-AFT-OCC"]["occupied"] is True
