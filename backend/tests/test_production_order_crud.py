"""Lệnh SX (ERP) — production_order: CRUD (Xem/Sửa/Xóa), các trường hành chính (issued_by/
executor_unit/warehouse_keeper/reference_note/start_date/end_date/safety_note), chặn sửa/xóa
khi đã có Mẻ sản xuất (BatchExecution), mã lệnh không được trùng."""

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
def recipe_ctx(client, admin_h):
    """Sản phẩm + version công thức đang hiệu lực có sẵn từ seed data — dùng để test
    recipe_version_id (mirror cách test_depth.py::test_recipe_suspend_resume lấy dữ liệu)."""
    recipe = client.get("/api/recipes", headers=admin_h).json()[0]
    vers = client.get(f"/api/recipes/{recipe['recipe_id']}/versions", headers=admin_h).json()
    vid = next(v["version_id"] for v in vers if v["state"] == "effective")
    return {"product_id": recipe["product_id"], "recipe_version_id": vid}


def _create_order(client, admin_h, code, recipe_ctx, **extra):
    payload = {"order_code": code, "product_id": recipe_ctx["product_id"], "planned_qty": 1000,
               "uom": "L", "priority": 5, "recipe_version_id": recipe_ctx["recipe_version_id"],
               "planned_batch_count": 2, **extra}
    r = client.post("/api/orders", headers=admin_h, json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_order_with_admin_fields(client, admin_h, recipe_ctx):
    o = _create_order(client, admin_h, "PO-CRUD-001", recipe_ctx,
                      issued_by="Nguyễn Văn A", executor_unit="Phân xưởng bia Đông Mai",
                      warehouse_keeper="Thủ kho B", reference_note="Căn cứ kế hoạch tháng 8",
                      start_date="2026-08-21T08:00:00", end_date="2026-08-21T17:00:00",
                      safety_note="Tuân thủ quy trình vận hành.")
    assert o["issued_by"] == "Nguyễn Văn A"
    assert o["executor_unit"] == "Phân xưởng bia Đông Mai"
    assert o["warehouse_keeper"] == "Thủ kho B"
    assert o["reference_note"] == "Căn cứ kế hoạch tháng 8"
    assert o["safety_note"] == "Tuân thủ quy trình vận hành."
    assert o["created_by"] == "admin"
    assert o["is_executed"] is False


def test_duplicate_order_code_blocked(client, admin_h, recipe_ctx):
    _create_order(client, admin_h, "PO-CRUD-002", recipe_ctx)
    dup = client.post("/api/orders", headers=admin_h, json={
        "order_code": "PO-CRUD-002", "product_id": recipe_ctx["product_id"], "planned_qty": 500})
    assert dup.status_code == 409, dup.text


def test_update_order(client, admin_h, recipe_ctx):
    o = _create_order(client, admin_h, "PO-CRUD-003", recipe_ctx, issued_by="A")
    # Giữ nguyên planned_batch_count=2 (không tăng lên) — tăng số mẻ sẽ kéo nhu cầu NVL vượt
    # tồn kho demo hiện có, bị chặn 409 (đúng hành vi mới — _assert_no_shortage, xem
    # services/orders.py::_persist_lines), không liên quan gì tới việc test PUT các trường khác.
    r = client.put(f"/api/orders/{o['order_id']}", headers=admin_h, json={
        "order_code": "PO-CRUD-003", "product_id": recipe_ctx["product_id"], "planned_qty": 2000,
        "uom": "L", "priority": 3, "recipe_version_id": recipe_ctx["recipe_version_id"],
        "planned_batch_count": 2, "issued_by": "B", "reference_note": "Sửa lại kế hoạch"})
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["planned_qty"] == 2000
    assert updated["priority"] == 3
    assert updated["issued_by"] == "B"
    assert updated["reference_note"] == "Sửa lại kế hoạch"


def test_delete_order(client, admin_h, recipe_ctx):
    o = _create_order(client, admin_h, "PO-CRUD-004", recipe_ctx)
    r = client.delete(f"/api/orders/{o['order_id']}", headers=admin_h)
    assert r.status_code == 204, r.text
    assert client.get(f"/api/orders/{o['order_id']}", headers=admin_h).status_code == 404


def test_update_and_delete_blocked_after_batch_created(client, admin_h, recipe_ctx):
    o = _create_order(client, admin_h, "PO-CRUD-005", recipe_ctx)
    batch = client.post("/api/batches", headers=admin_h, json={
        "order_id": o["order_id"], "recipe_version_id": recipe_ctx["recipe_version_id"],
        "planned_qty": 1000, "allow_shortage": True})
    assert batch.status_code == 201, batch.text

    got = client.get(f"/api/orders/{o['order_id']}", headers=admin_h).json()
    assert got["is_executed"] is True

    blocked_edit = client.put(f"/api/orders/{o['order_id']}", headers=admin_h, json={
        "order_code": "PO-CRUD-005", "product_id": recipe_ctx["product_id"], "planned_qty": 999})
    assert blocked_edit.status_code == 409, blocked_edit.text

    blocked_delete = client.delete(f"/api/orders/{o['order_id']}", headers=admin_h)
    assert blocked_delete.status_code == 409, blocked_delete.text


def test_order_lines_persisted_and_visible_in_get(client, admin_h, recipe_ctx):
    """Xem NVL của Lệnh SX (ERP) phải LƯU LẠI (không phải preview sống) — mirror Lệnh nấu:
    material_qty_overrides sửa SL lấy tại Kho công ty/phân xưởng của 1 dòng, GET lại đúng
    giá trị đã sửa (không phải gợi ý mặc định), và có đủ 3 dòng NVL của công thức."""
    o = _create_order(client, admin_h, "PO-CRUD-007", recipe_ctx,
                      material_qty_overrides={"0": {"qty_from_company": 100, "qty_from_workshop": 2300}})
    got = client.get(f"/api/orders/{o['order_id']}", headers=admin_h).json()
    assert len(got["lines"]) == 3
    line0 = next(l for l in got["lines"] if l["seq"] == 0)
    assert line0["material_name"] == "Malt Pilsner"
    assert line0["qty_from_company"] == 100
    assert line0["qty_from_workshop"] == 2300


def test_order_without_recipe_has_no_lines(client, admin_h, recipe_ctx):
    o = _create_order(client, admin_h, "PO-CRUD-008", recipe_ctx, recipe_version_id=None)
    got = client.get(f"/api/orders/{o['order_id']}", headers=admin_h).json()
    assert got["lines"] == []


def test_create_blocked_when_bom_exceeds_stock(client, admin_h, recipe_ctx):
    """Tăng planned_batch_count đủ lớn để nhu cầu NVL vượt tồn kho demo (Malt Pilsner chỉ có
    3800kg, 1200kg/mẻ -> quá 3 mẻ là thiếu tồn) — phải bị chặn tạo lệnh, không lưu dòng nào."""
    payload = {"order_code": "PO-CRUD-009", "product_id": recipe_ctx["product_id"], "planned_qty": 100000,
              "uom": "L", "priority": 5, "recipe_version_id": recipe_ctx["recipe_version_id"],
              "planned_batch_count": 50}
    r = client.post("/api/orders", headers=admin_h, json=payload)
    assert r.status_code == 409, r.text


def test_update_delete_require_order_create_perm(client, recipe_ctx, admin_h):
    vanhanh_h = _login(client, "vanhanh", "123456")
    o = _create_order(client, admin_h, "PO-CRUD-006", recipe_ctx)
    assert client.put(f"/api/orders/{o['order_id']}", headers=vanhanh_h, json={
        "order_code": "PO-CRUD-006", "product_id": recipe_ctx["product_id"], "planned_qty": 1}).status_code == 403
    assert client.delete(f"/api/orders/{o['order_id']}", headers=vanhanh_h).status_code == 403
