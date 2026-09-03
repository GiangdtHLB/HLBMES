"""Vá đợt 2 các phát hiện audit "Lệnh nấu & Điều độ" (2026-09-03):

1. Xóa Lệnh nấu (BrewOrder) phải chặn nếu còn Lệnh SX (WorkOrder) con tham chiếu — kể cả khi
   WO đó CHƯA dispatch (còn "planned") — vì WorkOrder.brew_order_id là FK NOT NULL không
   ondelete, xóa thẳng sẽ vỡ FK 547 trên MSSQL (xem services/brew_order.py::delete_order).
2. WorkOrder không được nhảy thẳng "released" -> "in_progress" qua endpoint transition công
   khai mà bỏ qua "Phát mẻ" (dispatch) — xem services/workorders.py::transition.
3. wo_code nhập tay trùng phải báo lỗi nghiệp vụ rõ ràng (409), không phải 500 thô.
4. BrewOrder.locked (khóa lô) phải chặn create_wo/transition/dispatch/delete_wo — trước đây
   services/workorders.py không kiểm tra cờ này ở đâu cả.
5. Chia SL kế hoạch cho các mẻ khi "Phát mẻ" không được lệch tổng do làm tròn từng phần (xem
   services/workorders.py::_split_planned_qty).
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
def lager_product_id(client, admin_h):
    products = client.get("/api/products", headers=admin_h).json()
    return next(p["product_id"] for p in products if p["code"] == "BIA-LAGER")


@pytest.fixture(scope="module")
def lager_beer_type_id(client, admin_h, lager_product_id):
    products = client.get("/api/products", headers=admin_h).json()
    return next(p["beer_type_id"] for p in products if p["product_id"] == lager_product_id)


@pytest.fixture(scope="module")
def lager_recipe_version_id(client, admin_h, lager_product_id, lager_beer_type_id):
    recipes = client.get("/api/recipes", headers=admin_h).json()
    recipe = next(r for r in recipes if r["beer_type_id"] == lager_beer_type_id)
    versions = client.get(f"/api/recipes/{recipe['recipe_id']}/versions", headers=admin_h).json()
    return next(v["version_id"] for v in versions if v["state"] == "effective" and v["product_id"] == lager_product_id)


@pytest.fixture(scope="module")
def brewhouse_line_id(client, admin_h):
    r = client.post("/api/lines", headers=admin_h,
                    json={"code": "BREW-WOFX2-01", "name": "Nhà nấu test round2", "kind": "brewhouse"})
    assert r.status_code == 201, r.text
    return r.json()["line_id"]


def _a_brew_order(client, admin_h, code, product_id, recipe_version_id, planned_volume_hl=100):
    r = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": code, "product_id": product_id, "recipe_version_id": recipe_version_id,
        "planned_volume_hl": planned_volume_hl, "auto_from_bom": False})
    assert r.status_code == 201, r.text
    return r.json()["brew_order_id"]


def _a_wo(client, admin_h, brew_order_id, brewhouse_line_id, line="Nấu A", recipe_version_id=None, wo_code=None):
    payload = {"brew_order_id": brew_order_id, "line": line, "brewhouse_line_id": brewhouse_line_id,
              "shift": "A", "priority": 5, "recipe_version_id": recipe_version_id}
    if wo_code:
        payload["wo_code"] = wo_code
    r = client.post("/api/workorders", headers=admin_h, json=payload)
    return r


def test_delete_brew_order_blocked_by_planned_work_order(
        client, admin_h, lager_product_id, lager_recipe_version_id, brewhouse_line_id):
    brew_order_id = _a_brew_order(client, admin_h, "LN-RND2-001", lager_product_id, lager_recipe_version_id)
    wo = _a_wo(client, admin_h, brew_order_id, brewhouse_line_id, recipe_version_id=lager_recipe_version_id)
    assert wo.status_code == 201, wo.text

    # WO còn "planned" (chưa dispatch) — _has_any_execution() không chặn, nhưng FK NOT NULL
    # brew_order_id vẫn tham chiếu, phải chặn xóa Lệnh nấu ở tầng nghiệp vụ.
    blocked = client.delete(f"/api/brewing/orders/{brew_order_id}", headers=admin_h)
    assert blocked.status_code == 409, blocked.text
    assert "Lệnh SX" in blocked.json()["detail"]

    # Xóa WO trước rồi mới xóa được Lệnh nấu.
    del_wo = client.delete(f"/api/workorders/{wo.json()['wo_id']}", headers=admin_h)
    assert del_wo.status_code == 204, del_wo.text
    ok = client.delete(f"/api/brewing/orders/{brew_order_id}", headers=admin_h)
    assert ok.status_code == 204, ok.text


def test_wo_transition_in_progress_blocked_without_dispatch(
        client, admin_h, lager_product_id, lager_recipe_version_id, brewhouse_line_id):
    brew_order_id = _a_brew_order(client, admin_h, "LN-RND2-002", lager_product_id, lager_recipe_version_id)
    wo_id = _a_wo(client, admin_h, brew_order_id, brewhouse_line_id, recipe_version_id=lager_recipe_version_id).json()["wo_id"]
    rel = client.post(f"/api/workorders/{wo_id}/transition", headers=admin_h, json={"target": "released"})
    assert rel.status_code == 200, rel.text

    blocked = client.post(f"/api/workorders/{wo_id}/transition", headers=admin_h, json={"target": "in_progress"})
    assert blocked.status_code == 409, blocked.text
    assert "Phát mẻ" in blocked.json()["detail"]

    dispatched = client.post(f"/api/workorders/{wo_id}/dispatch", headers=admin_h,
                             json={"from_batch": 9601, "batch_count": 1})
    assert dispatched.status_code == 200, dispatched.text
    assert dispatched.json()["wo_status"] == "in_progress"


def test_wo_code_duplicate_rejected(client, admin_h, lager_product_id, lager_recipe_version_id, brewhouse_line_id):
    brew_order_id = _a_brew_order(client, admin_h, "LN-RND2-003", lager_product_id, lager_recipe_version_id)
    first = _a_wo(client, admin_h, brew_order_id, brewhouse_line_id,
                  recipe_version_id=lager_recipe_version_id, wo_code="WO-RND2-DUP")
    assert first.status_code == 201, first.text

    dup = _a_wo(client, admin_h, brew_order_id, brewhouse_line_id,
               recipe_version_id=lager_recipe_version_id, wo_code="WO-RND2-DUP")
    assert dup.status_code == 409, dup.text
    assert "đã tồn tại" in dup.json()["detail"]


def test_locked_brew_order_blocks_wo_lifecycle(
        client, admin_h, lager_product_id, lager_recipe_version_id, brewhouse_line_id):
    brew_order_id = _a_brew_order(client, admin_h, "LN-RND2-004", lager_product_id, lager_recipe_version_id)
    wo_id = _a_wo(client, admin_h, brew_order_id, brewhouse_line_id, recipe_version_id=lager_recipe_version_id).json()["wo_id"]
    rel = client.post(f"/api/workorders/{wo_id}/transition", headers=admin_h, json={"target": "released"})
    assert rel.status_code == 200, rel.text

    # Giả lập "khóa lô" (locked=True) trực tiếp qua DB — mirror cách test_batch_pipeline_audit_
    # fixes.py giả lập race condition, vì cờ này bình thường chỉ tự suy ra từ chuỗi BrewRecord
    # (module Nấu-Lọc-Chiết cũ, xem services/lot_lock.py), không có endpoint lock trực tiếp cho
    # BrewOrder khi lệnh chỉ đi qua pipeline "Mẻ sản xuất" mới.
    from app.database import SessionLocal
    from app.models.brewing import BrewOrder
    db = SessionLocal()
    try:
        order = db.get(BrewOrder, brew_order_id)
        order.locked = True
        order.locked_by = "test"
        db.commit()
    finally:
        db.close()

    blocked_dispatch = client.post(f"/api/workorders/{wo_id}/dispatch", headers=admin_h,
                                   json={"from_batch": 9701, "batch_count": 1})
    assert blocked_dispatch.status_code == 409, blocked_dispatch.text

    blocked_transition = client.post(f"/api/workorders/{wo_id}/transition", headers=admin_h,
                                     json={"target": "cancelled"})
    assert blocked_transition.status_code == 409, blocked_transition.text

    blocked_delete = client.delete(f"/api/workorders/{wo_id}", headers=admin_h)
    assert blocked_delete.status_code == 409, blocked_delete.text

    blocked_create = _a_wo(client, admin_h, brew_order_id, brewhouse_line_id, recipe_version_id=lager_recipe_version_id)
    assert blocked_create.status_code == 409, blocked_create.text


def test_dispatch_splits_planned_qty_without_rounding_drift(
        client, admin_h, lager_product_id, lager_recipe_version_id, brewhouse_line_id):
    # 100 / 3 = 33.333... — round() từng phần trước đây làm tổng lệch (99.999), giờ phải khớp
    # ĐÚNG 100 (phần dư 0.001 x 1 dồn cho mẻ đầu tiên).
    brew_order_id = _a_brew_order(client, admin_h, "LN-RND2-005", lager_product_id, lager_recipe_version_id,
                                  planned_volume_hl=100)
    wo_id = _a_wo(client, admin_h, brew_order_id, brewhouse_line_id, recipe_version_id=lager_recipe_version_id).json()["wo_id"]
    rel = client.post(f"/api/workorders/{wo_id}/transition", headers=admin_h, json={"target": "released"})
    assert rel.status_code == 200, rel.text

    dispatched = client.post(f"/api/workorders/{wo_id}/dispatch", headers=admin_h,
                             json={"from_batch": 9801, "batch_count": 3})
    assert dispatched.status_code == 200, dispatched.text
    batch_ids = dispatched.json()["batch_ids"]
    qtys = [client.get(f"/api/batches/{bid}", headers=admin_h).json()["planned_qty"] for bid in batch_ids]
    assert round(sum(qtys), 3) == 100.0
    assert qtys == [33.334, 33.333, 33.333]
