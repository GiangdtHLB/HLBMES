"""Test "Phát mẻ" (dispatch) tạo NHIỀU Mẻ sản xuất (BatchExecution) liên tiếp, đánh số từ
"Từ mẻ" (VD từ mẻ 120, số mẻ 4 -> mã mẻ 120/121/122/123), gắn work_order_id = Lệnh SX — tích
hợp Điều độ→Mẻ sản xuất, KHÔNG còn tạo Nấu-Lọc-Chiết (BrewRecord/BrewBatch) như trước. Tùy
chọn gộp toàn bộ mẻ vừa phát vào 1 tank lên men (BatchTank) mới nếu chọn `tank_lm`. Xem
services/workorders.py::dispatch.
"""

import os
import re
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
def lager_recipe_version_id(client, admin_h, lager_product_id):
    recipes = client.get("/api/recipes", headers=admin_h).json()
    products = client.get("/api/products", headers=admin_h).json()
    lager = next(p for p in products if p["product_id"] == lager_product_id)
    recipe = next(r for r in recipes if r["beer_type_id"] == lager["beer_type_id"])
    versions = client.get(f"/api/recipes/{recipe['recipe_id']}/versions", headers=admin_h).json()
    return next(v["version_id"] for v in versions if v["state"] == "effective")


@pytest.fixture(scope="module")
def brewhouse_line_id(client, admin_h):
    r = client.post("/api/lines", headers=admin_h,
                    json={"code": "BREW-DISPATCH2-01", "name": "Nhà nấu test dispatch2", "kind": "brewhouse"})
    assert r.status_code == 201, r.text
    return r.json()["line_id"]


def _a_brew_order(client, admin_h, code, product_id, recipe_version_id, planned_volume_hl=100):
    r = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": code, "product_id": product_id, "recipe_version_id": recipe_version_id,
        "planned_volume_hl": planned_volume_hl, "auto_from_bom": False})
    assert r.status_code == 201, r.text
    return r.json()["brew_order_id"]


def _a_wo(client, admin_h, brew_order_id, recipe_version_id, brewhouse_line_id, planned_qty=100):
    r = client.post("/api/workorders", headers=admin_h, json={
        "brew_order_id": brew_order_id, "line": "Nấu A", "brewhouse_line_id": brewhouse_line_id,
        "shift": "A", "priority": 5,
        "recipe_version_id": recipe_version_id, "planned_qty": planned_qty, "uom": "hl"})
    assert r.status_code == 201, r.text
    return r.json()["wo_id"]


def _release(client, admin_h, wo_id):
    r = client.post(f"/api/workorders/{wo_id}/transition", headers=admin_h, json={"target": "released"})
    assert r.status_code == 200, r.text


def test_wo_code_auto_sequential_and_tank_auto_code_from_wo_number(
        client, admin_h, lager_product_id, lager_recipe_version_id, brewhouse_line_id):
    """services/workorders.py::_next_wo_code — mã WO tự sinh dạng "WO-{số thứ tự tăng dần}",
    KHÔNG còn kiểu ngày+random cũ (yêu cầu người dùng 2026-09-01). services/batch_pipeline.py::
    _auto_tank_code — khi gộp mẻ vào tank/lô lên men không nhập tay mã, tự lấy theo số thứ tự
    của Lệnh SX (điều độ) mà các mẻ đó cùng thuộc về, bỏ tiền tố "WO-"."""
    brew_order_id = _a_brew_order(client, admin_h, "LN-DISPATCH2-010", lager_product_id, lager_recipe_version_id)
    wo_id_1 = _a_wo(client, admin_h, brew_order_id, lager_recipe_version_id, brewhouse_line_id, planned_qty=20)
    wo_1 = client.get(f"/api/workorders/{wo_id_1}", headers=admin_h).json()
    assert re.fullmatch(r"WO-\d+", wo_1["wo_code"])
    n1 = int(wo_1["wo_code"].split("-")[1])

    brew_order_id_2 = _a_brew_order(client, admin_h, "LN-DISPATCH2-011", lager_product_id, lager_recipe_version_id)
    wo_id_2 = _a_wo(client, admin_h, brew_order_id_2, lager_recipe_version_id, brewhouse_line_id, planned_qty=20)
    wo_2 = client.get(f"/api/workorders/{wo_id_2}", headers=admin_h).json()
    n2 = int(wo_2["wo_code"].split("-")[1])
    assert n2 == n1 + 1

    _release(client, admin_h, wo_id_2)
    dispatched = client.post(f"/api/workorders/{wo_id_2}/dispatch", headers=admin_h,
                             json={"from_batch": 1100, "batch_count": 1})
    assert dispatched.status_code == 200, dispatched.text
    batch_id = dispatched.json()["batch_ids"][0]

    # Gộp thủ công (không truyền tank_code) vào 1 lô lên men mới -> mã lô tự sinh = số thứ tự WO.
    tank = client.post("/api/batch-tanks", headers=admin_h, json={"batch_ids": [batch_id]})
    assert tank.status_code == 201, tank.text
    assert tank.json()["tank_code"] == str(n2)


def test_brew_order_status_released_not_shown_as_in_progress(
        client, admin_h, lager_product_id, lager_recipe_version_id, brewhouse_line_id):
    """services/brew_order.py::_wo_derived_status — Lệnh nấu lấy trạng thái theo Điều độ (WO),
    nhưng "released" (đã phát hành, CHƯA "Phát mẻ") không được coi là "đang thực hiện" — chỉ từ
    "in_progress" (đã dispatch, có mẻ thật) trở lên mới tính is_executed=True (yêu cầu người dùng
    2026-09-01: released phải hiện đúng "released", không lẫn vào is_executed/"Đang nấu")."""
    brew_order_id = _a_brew_order(client, admin_h, "LN-DISPATCH2-009", lager_product_id, lager_recipe_version_id)
    wo_id = _a_wo(client, admin_h, brew_order_id, lager_recipe_version_id, brewhouse_line_id, planned_qty=20)
    _release(client, admin_h, wo_id)

    order = client.get(f"/api/brewing/orders/{brew_order_id}", headers=admin_h).json()
    assert order["wo_status"] == "released"
    assert order["is_executed"] is False
    assert order["is_complete"] is False

    dispatched = client.post(f"/api/workorders/{wo_id}/dispatch", headers=admin_h,
                             json={"from_batch": 1000, "batch_count": 1})
    assert dispatched.status_code == 200, dispatched.text
    order2 = client.get(f"/api/brewing/orders/{brew_order_id}", headers=admin_h).json()
    assert order2["wo_status"] == "in_progress"
    assert order2["is_executed"] is True


def test_dispatch_creates_numbered_batch_execution_rows(
        client, admin_h, lager_product_id, lager_recipe_version_id, brewhouse_line_id):
    brew_order_id = _a_brew_order(client, admin_h, "LN-DISPATCH2-001", lager_product_id, lager_recipe_version_id)
    wo_id = _a_wo(client, admin_h, brew_order_id, lager_recipe_version_id, brewhouse_line_id, planned_qty=40)
    _release(client, admin_h, wo_id)

    r = client.post(f"/api/workorders/{wo_id}/dispatch", headers=admin_h,
                    json={"from_batch": 120, "batch_count": 4})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["wo_status"] == "in_progress"
    assert body["batch_codes"] == ["120", "121", "122", "123"]
    assert body["tank_id"] is None

    b = client.get(f"/api/batches/{body['batch_ids'][0]}", headers=admin_h).json()
    assert b["work_order_id"] == wo_id
    assert b["brewhouse_line_id"] == brewhouse_line_id
    assert b["planned_qty"] == 10.0   # 40 hl / 4 mẻ

    wo = client.get(f"/api/workorders/{wo_id}", headers=admin_h).json()
    assert wo["rollup"]["batches"] == 4
    assert {x["batch_code"] for x in wo["rollup"]["batch_list"]} == {"120", "121", "122", "123"}

    board = client.get("/api/workorders", headers=admin_h).json()
    row = next(w for w in board if w["wo_id"] == wo_id)
    assert row["batches"] == 4


def test_dispatch_again_adds_more_numbered_batches(
        client, admin_h, lager_product_id, lager_recipe_version_id, brewhouse_line_id):
    brew_order_id = _a_brew_order(client, admin_h, "LN-DISPATCH2-002", lager_product_id, lager_recipe_version_id)
    wo_id = _a_wo(client, admin_h, brew_order_id, lager_recipe_version_id, brewhouse_line_id)
    _release(client, admin_h, wo_id)

    first = client.post(f"/api/workorders/{wo_id}/dispatch", headers=admin_h,
                        json={"from_batch": 200, "batch_count": 2})
    assert first.status_code == 200, first.text
    assert first.json()["batch_codes"] == ["200", "201"]

    second = client.post(f"/api/workorders/{wo_id}/dispatch", headers=admin_h,
                         json={"from_batch": 202, "batch_count": 1})
    assert second.status_code == 200, second.text
    assert second.json()["batch_codes"] == ["202"]

    wo = client.get(f"/api/workorders/{wo_id}", headers=admin_h).json()
    assert wo["rollup"]["batches"] == 3


def test_dispatch_blocked_on_duplicate_batch_code_all_or_nothing(
        client, admin_h, lager_product_id, lager_recipe_version_id, brewhouse_line_id):
    brew_order_id = _a_brew_order(client, admin_h, "LN-DISPATCH2-003", lager_product_id, lager_recipe_version_id)
    wo_id = _a_wo(client, admin_h, brew_order_id, lager_recipe_version_id, brewhouse_line_id)
    _release(client, admin_h, wo_id)

    first = client.post(f"/api/workorders/{wo_id}/dispatch", headers=admin_h,
                        json={"from_batch": 300, "batch_count": 1})
    assert first.status_code == 200, first.text

    # Phát mẻ khác nhưng dải số TRÙNG mã 300 đã có -> chặn toàn bộ, không tạo mẻ nào thêm.
    dup = client.post(f"/api/workorders/{wo_id}/dispatch", headers=admin_h,
                      json={"from_batch": 300, "batch_count": 2})
    assert dup.status_code == 409, dup.text

    wo = client.get(f"/api/workorders/{wo_id}", headers=admin_h).json()
    assert wo["rollup"]["batches"] == 1   # vẫn chỉ có mẻ 300 từ lần phát đầu


def test_wo_and_dispatch_do_not_require_brewhouse_line(
        client, admin_h, lager_product_id, lager_recipe_version_id):
    """Dây chuyền nấu không còn bắt buộc ở Work Order (bỏ theo yêu cầu 2026-08-31) — tạo lệnh
    và Phát mẻ vẫn chạy được khi brewhouse_line_id = None, mẻ tạo ra cũng brewhouse_line_id = None."""
    brew_order_id = _a_brew_order(client, admin_h, "LN-DISPATCH2-004", lager_product_id, lager_recipe_version_id)
    r = client.post("/api/workorders", headers=admin_h, json={
        "brew_order_id": brew_order_id, "line": "Nấu A", "brewhouse_line_id": None,
        "shift": "A", "priority": 5, "recipe_version_id": lager_recipe_version_id, "planned_qty": 20})
    assert r.status_code == 201, r.text
    wo_id = r.json()["wo_id"]
    _release(client, admin_h, wo_id)

    dispatched = client.post(f"/api/workorders/{wo_id}/dispatch", headers=admin_h,
                             json={"from_batch": 500, "batch_count": 1})
    assert dispatched.status_code == 200, dispatched.text
    b = client.get(f"/api/batches/{dispatched.json()['batch_ids'][0]}", headers=admin_h).json()
    assert b["brewhouse_line_id"] is None


def test_dispatch_requires_recipe_version(client, admin_h, lager_product_id, lager_recipe_version_id, brewhouse_line_id):
    brew_order_id = _a_brew_order(client, admin_h, "LN-DISPATCH2-006", lager_product_id, lager_recipe_version_id)
    # WO không gắn recipe_version_id (Lệnh nấu đã có product_id sẵn nên không bắt buộc lúc lập).
    r = client.post("/api/workorders", headers=admin_h, json={
        "brew_order_id": brew_order_id, "line": "Nấu A", "brewhouse_line_id": brewhouse_line_id,
        "shift": "A", "priority": 5})
    assert r.status_code == 201, r.text
    wo_id = r.json()["wo_id"]
    _release(client, admin_h, wo_id)

    dispatched = client.post(f"/api/workorders/{wo_id}/dispatch", headers=admin_h,
                             json={"from_batch": 600, "batch_count": 1})
    assert dispatched.status_code == 409, dispatched.text


def test_dispatch_auto_merges_into_new_tank_when_tank_lm_given(
        client, admin_h, lager_product_id, lager_recipe_version_id, brewhouse_line_id):
    """tank_lm ở dispatch() tự động gộp các mẻ VỪA TẠO vào 1 BatchTank mới ngay lập tức — các mẻ
    này luôn ở state "planned" (chưa hề chạy) lúc gộp, mirror thực tế nấu bia: nhiều mẻ liên tiếp
    cùng đổ vào 1 tank, mẻ nào nấu xong bơm vào mẻ đó, không đợi hết cả đợt mới có tank (xem
    services/batch_pipeline.py::merge_batches_into_tank — cho gộp ở bất kỳ trạng thái nào, on_hand
    chỉ cộng theo actual_qty đã ghi, mẻ chưa xong đóng góp 0). Tank vừa tạo có on_hand/volume_hl=0
    (chưa mẻ nào có SL thực tế) — cộng dần lên khi từng mẻ được ghi actual_qty sau này (xem
    test_batch_pipeline.py cho phần tồn cộng dồn theo delta)."""
    tank_line = client.post("/api/lines", headers=admin_h,
                            json={"code": "FV-DISPATCH2-01", "name": "Tank LM test dispatch2", "kind": "tank"})
    assert tank_line.status_code == 201, tank_line.text

    brew_order_id = _a_brew_order(client, admin_h, "LN-DISPATCH2-005", lager_product_id, lager_recipe_version_id)
    wo_id = _a_wo(client, admin_h, brew_order_id, lager_recipe_version_id, brewhouse_line_id, planned_qty=30)
    _release(client, admin_h, wo_id)

    r = client.post(f"/api/workorders/{wo_id}/dispatch", headers=admin_h,
                    json={"from_batch": 400, "batch_count": 3, "tank_lm": "FV-DISPATCH2-01"})
    assert r.status_code == 200, r.text
    tank_id = r.json()["tank_id"]
    assert tank_id and r.json()["tank_code"]

    tank = client.get(f"/api/batch-tanks/{tank_id}", headers=admin_h).json()
    assert tank["on_hand"] == 0.0 and tank["volume_hl"] == 0.0
    links = client.get(f"/api/batch-tanks/{tank_id}/batches", headers=admin_h).json()
    assert len(links["batch_ids"]) == 3

    wo = client.get(f"/api/workorders/{wo_id}", headers=admin_h).json()
    assert wo["rollup"]["batches"] == 3
    assert wo["status"] == "in_progress"

    # Mẻ 1 (400) nấu xong, ghi SL thực tế -> on_hand tank cộng thêm đúng số đó ngay (delta).
    batch_400_id = links["batch_ids"][0]
    for target in ("ready", "running"):
        t = client.post(f"/api/batches/{batch_400_id}/transition", headers=admin_h, json={"target": target})
        assert t.status_code == 200, t.text
    aq = client.post(f"/api/batches/{batch_400_id}/actual-qty", headers=admin_h, json={"actual_qty": 9.5})
    assert aq.status_code == 200, aq.text
    tank_after = client.get(f"/api/batch-tanks/{tank_id}", headers=admin_h).json()
    assert tank_after["on_hand"] == 9.5 and tank_after["volume_hl"] == 9.5

    # Không truyền tank_lm thì dispatch vẫn hoạt động bình thường (chỉ tạo mẻ, không tự gộp tank).
    plain = client.post(f"/api/workorders/{wo_id}/dispatch", headers=admin_h,
                        json={"from_batch": 700, "batch_count": 3})
    assert plain.status_code == 200, plain.text
    assert plain.json()["tank_id"] is None


def _finish_batch(client, admin_h, batch_id, actual_qty=10):
    for target in ("ready", "running"):
        t = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": target})
        assert t.status_code == 200, t.text
    aq = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": actual_qty})
    assert aq.status_code == 200, aq.text
    fin = client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={})
    assert fin.status_code == 200, fin.text
    r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "completed"})
    assert r.status_code == 200, r.text
    return r.json()


def test_wo_auto_completes_when_all_dispatched_batches_are_done(
        client, admin_h, lager_product_id, lager_recipe_version_id, brewhouse_line_id):
    """services/batches.py::_auto_complete_work_order — khi TẤT CẢ mẻ (BatchExecution) của 1
    Lệnh SX (Điều độ) đều hoàn thành (hoặc hủy), Lệnh SX tự động chuyển "completed", không cần
    người dùng vào Điều độ bấm tay (yêu cầu người dùng 2026-09-01)."""
    brew_order_id = _a_brew_order(client, admin_h, "LN-DISPATCH2-007", lager_product_id, lager_recipe_version_id)
    wo_id = _a_wo(client, admin_h, brew_order_id, lager_recipe_version_id, brewhouse_line_id, planned_qty=20)
    _release(client, admin_h, wo_id)

    dispatched = client.post(f"/api/workorders/{wo_id}/dispatch", headers=admin_h,
                             json={"from_batch": 800, "batch_count": 2})
    assert dispatched.status_code == 200, dispatched.text
    batch_ids = dispatched.json()["batch_ids"]

    wo = client.get(f"/api/workorders/{wo_id}", headers=admin_h).json()
    assert wo["status"] == "in_progress"

    _finish_batch(client, admin_h, batch_ids[0])
    # Còn mẻ 2 chưa xong -> lệnh SX vẫn "in_progress", chưa tự hoàn thành.
    wo_mid = client.get(f"/api/workorders/{wo_id}", headers=admin_h).json()
    assert wo_mid["status"] == "in_progress"

    _finish_batch(client, admin_h, batch_ids[1])
    # Cả 2 mẻ đã hoàn thành -> lệnh SX tự động chuyển "completed".
    wo_done = client.get(f"/api/workorders/{wo_id}", headers=admin_h).json()
    assert wo_done["status"] == "completed"

    # Lệnh nấu (BrewOrder) giờ "is_complete" (suy theo trạng thái Điều độ) -> không cho lập thêm
    # Lệnh SX (điều độ) MỚI cho lệnh nấu này nữa (yêu cầu người dùng 2026-09-01).
    order = client.get(f"/api/brewing/orders/{brew_order_id}", headers=admin_h).json()
    assert order["is_complete"] is True
    blocked = client.post("/api/workorders", headers=admin_h, json={
        "brew_order_id": brew_order_id, "line": "Nấu A", "brewhouse_line_id": brewhouse_line_id,
        "shift": "A", "priority": 5, "recipe_version_id": lager_recipe_version_id, "planned_qty": 10})
    assert blocked.status_code == 409, blocked.text


def test_wo_auto_completes_when_remaining_batch_is_cancelled_not_finished(
        client, admin_h, lager_product_id, lager_recipe_version_id, brewhouse_line_id):
    """Mẻ bị hủy (cancelled) không tính là "chưa xong" — vẫn cho lệnh SX tự hoàn thành miễn còn
    ít nhất 1 mẻ thật sự hoàn thành/đóng (không phải mọi mẻ đều hủy)."""
    brew_order_id = _a_brew_order(client, admin_h, "LN-DISPATCH2-008", lager_product_id, lager_recipe_version_id)
    wo_id = _a_wo(client, admin_h, brew_order_id, lager_recipe_version_id, brewhouse_line_id, planned_qty=20)
    _release(client, admin_h, wo_id)

    dispatched = client.post(f"/api/workorders/{wo_id}/dispatch", headers=admin_h,
                             json={"from_batch": 900, "batch_count": 2})
    assert dispatched.status_code == 200, dispatched.text
    batch_ids = dispatched.json()["batch_ids"]

    _finish_batch(client, admin_h, batch_ids[0])
    cancel = client.post(f"/api/batches/{batch_ids[1]}/transition", headers=admin_h, json={"target": "cancelled"})
    assert cancel.status_code == 200, cancel.text

    wo = client.get(f"/api/workorders/{wo_id}", headers=admin_h).json()
    assert wo["status"] == "completed"


def test_cancel_wo_cascades_cancel_active_batches_and_refunds_material(
        client, admin_h, lager_product_id, lager_recipe_version_id, brewhouse_line_id):
    """services/workorders.py::_cancel_active_batches — trước đây "Hủy" Lệnh SX chỉ đổi status
    của WorkOrder, không đụng gì tới các mẻ con: mẻ vẫn "chạy" bình thường (cấp liệu/hoàn thành
    được) dù lệnh cha đã "Đã hủy". Giờ hủy Lệnh SX phải cascade hủy MỌI mẻ còn active (planned/
    ready/running/held), và hoàn lại NVL đã cấp cho mẻ đó (mirror batches.py::
    _refund_consumed_materials, 2026-09-06)."""
    brew_order_id = _a_brew_order(client, admin_h, "LN-DISPATCH2-012", lager_product_id, lager_recipe_version_id)
    wo_id = _a_wo(client, admin_h, brew_order_id, lager_recipe_version_id, brewhouse_line_id, planned_qty=20)
    _release(client, admin_h, wo_id)

    dispatched = client.post(f"/api/workorders/{wo_id}/dispatch", headers=admin_h,
                             json={"from_batch": 2000, "batch_count": 2})
    assert dispatched.status_code == 200, dispatched.text
    batch_ids = dispatched.json()["batch_ids"]

    mat = client.post("/api/materials", headers=admin_h,
                      json={"code": "NVL-WOCANCEL-01", "name": "NVL test hủy WO", "uom": "kg"})
    assert mat.status_code == 201, mat.text
    lot = client.post("/api/lots", headers=admin_h,
                      json={"lot_code": "LOT-WOCANCEL-01", "material_id": mat.json()["material_id"],
                            "quantity": 500, "uom": "kg", "location": "Kho phân xưởng"})
    assert lot.status_code == 201, lot.text
    lot_id = lot.json()["lot_id"]
    consume = client.post(f"/api/batches/{batch_ids[0]}/consume", headers=admin_h,
                          json={"lot_id": lot_id, "quantity": 120})
    assert consume.status_code == 200, consume.text

    cancel = client.post(f"/api/workorders/{wo_id}/transition", headers=admin_h,
                         json={"target": "cancelled", "reason": "Test cascade hủy WO"})
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["status"] == "cancelled"

    for bid in batch_ids:
        b = client.get(f"/api/batches/{bid}", headers=admin_h).json()
        assert b["state"] == "cancelled", b

    lot_after = next(l for l in client.get("/api/lots", headers=admin_h).json() if l["lot_id"] == lot_id)
    assert lot_after["quantity"] == 500
    assert lot_after["status"] == "available"


def test_cancel_wo_leaves_completed_batches_untouched(
        client, admin_h, lager_product_id, lager_recipe_version_id, brewhouse_line_id):
    """Hủy Lệnh SX chỉ cascade hủy mẻ CÒN ACTIVE — mẻ đã completed (có kết quả thật) không bị
    đụng tới (BATCH_TRANSITIONS cũng không cho phép completed -> cancelled)."""
    brew_order_id = _a_brew_order(client, admin_h, "LN-DISPATCH2-013", lager_product_id, lager_recipe_version_id)
    wo_id = _a_wo(client, admin_h, brew_order_id, lager_recipe_version_id, brewhouse_line_id, planned_qty=20)
    _release(client, admin_h, wo_id)

    dispatched = client.post(f"/api/workorders/{wo_id}/dispatch", headers=admin_h,
                             json={"from_batch": 2100, "batch_count": 2})
    assert dispatched.status_code == 200, dispatched.text
    batch_ids = dispatched.json()["batch_ids"]

    _finish_batch(client, admin_h, batch_ids[0])

    cancel = client.post(f"/api/workorders/{wo_id}/transition", headers=admin_h, json={"target": "cancelled"})
    assert cancel.status_code == 200, cancel.text

    done = client.get(f"/api/batches/{batch_ids[0]}", headers=admin_h).json()
    assert done["state"] == "completed"
    still_active = client.get(f"/api/batches/{batch_ids[1]}", headers=admin_h).json()
    assert still_active["state"] == "cancelled"


def test_cancel_wo_blocked_when_active_batch_ebr_locked(
        client, admin_h, lager_product_id, lager_recipe_version_id, brewhouse_line_id):
    """Không cascade-hủy mẻ đã khóa hồ sơ (EBR) — chặn hủy cả Lệnh SX, bắt xử lý riêng mẻ đó
    (amendment) trước, giống mọi chỗ khác đang tôn trọng ebr_locked."""
    brew_order_id = _a_brew_order(client, admin_h, "LN-DISPATCH2-014", lager_product_id, lager_recipe_version_id)
    wo_id = _a_wo(client, admin_h, brew_order_id, lager_recipe_version_id, brewhouse_line_id, planned_qty=20)
    _release(client, admin_h, wo_id)

    dispatched = client.post(f"/api/workorders/{wo_id}/dispatch", headers=admin_h,
                             json={"from_batch": 2200, "batch_count": 1})
    assert dispatched.status_code == 200, dispatched.text
    batch_id = dispatched.json()["batch_ids"][0]

    sign = client.post(f"/api/batches/{batch_id}/ebr/sign", headers=admin_h,
                       json={"password": "AdminTest123", "meaning": "Xác nhận thực thi"})
    assert sign.status_code == 200, sign.text
    lock = client.post(f"/api/batches/{batch_id}/ebr/lock", headers=admin_h,
                       json={"password": "AdminTest123", "reason": "Phê duyệt release"})
    assert lock.status_code == 200, lock.text

    cancel = client.post(f"/api/workorders/{wo_id}/transition", headers=admin_h, json={"target": "cancelled"})
    assert cancel.status_code == 409, cancel.text

    wo = client.get(f"/api/workorders/{wo_id}", headers=admin_h).json()
    assert wo["status"] == "in_progress"


def test_ebr_shows_water_qc_declared_at_work_order_level(
        client, admin_h, lager_product_id, lager_recipe_version_id, brewhouse_line_id):
    """services/ebr.py::assemble — hồ sơ EBR của 1 mẻ nấu (BatchExecution) phải hiện luôn Chỉ
    tiêu Nước nấu bia (stage "nuoc_nau") đã khai theo Mã điều độ (WorkOrder) của mẻ đó — trước
    đây popup EBR HOÀN TOÀN không có mục này dù đã khai qua tab Điều độ (yêu cầu người dùng
    2026-09-06: "Thêm chỉ tiêu chất lượng nước vào trong pop up hồ sơ EBR này")."""
    brew_order_id = _a_brew_order(client, admin_h, "LN-DISPATCH2-015", lager_product_id, lager_recipe_version_id)
    wo_id2 = _a_wo(client, admin_h, brew_order_id, lager_recipe_version_id, brewhouse_line_id, planned_qty=20)
    _release(client, admin_h, wo_id2)
    dispatched = client.post(f"/api/workorders/{wo_id2}/dispatch", headers=admin_h,
                             json={"from_batch": 2300, "batch_count": 1})
    assert dispatched.status_code == 200, dispatched.text
    batch_id = dispatched.json()["batch_ids"][0]

    param = client.post("/api/qc/parameters", headers=admin_h,
                       json={"code": "CT_NUOCNAU_EBR", "name": "Độ cứng nước nấu", "lsl": 1, "usl": 10})
    assert param.status_code == 201, param.text
    rec = client.post("/api/brewing/qc-results", headers=admin_h,
                      json={"stage": "nuoc_nau", "scope_type": "work_order", "scope_id": wo_id2,
                            "parameter": "CT_NUOCNAU_EBR", "value": 5, "lower_limit": 1, "upper_limit": 10})
    assert rec.status_code == 201, rec.text

    ebr = client.get(f"/api/batches/{batch_id}/ebr", headers=admin_h).json()
    rows = ebr.get("nuoc_nau_display") or []
    row = next((r for r in rows if r["parameter"] == "CT_NUOCNAU_EBR"), None)
    assert row is not None, rows
    assert row["parameter_name"] == "Độ cứng nước nấu"
    assert row["value"] == 5
    assert row["status"] == "pass"
    assert row["work_order_id"] == wo_id2
