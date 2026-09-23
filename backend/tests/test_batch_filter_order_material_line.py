"""Test khai báo vật tư dự kiến NGAY LÚC LẬP "Lệnh lọc" (BatchFilterOrderMaterialLine, pipeline
"Mẻ sản xuất"): mirror BrewOrderMaterialLine nhưng KHÔNG có bước chọn lô/FIFO ở đây (FIFO do vận
hành tự chọn sau, lúc ghi NGUYÊN LIỆU LỌC thật ở Lô lọc — xem
services/batch_pipeline.py::add_filter_lot_material, không đổi).

Bao phủ:
1) Tạo lệnh lọc kèm dòng vật tư dự kiến, ĐỦ tồn kho -> tạo được, GET .../materials trả đúng tên/
   SL đã resolve từ Danh mục.
2) Tạo lệnh lọc với 1 dòng vật tư vượt quá tổng tồn (Kho công ty + Kho phân xưởng) -> bị CHẶN
   (DomainError -> 4xx), không tạo lệnh.
3) "Đề nghị nhận kho" (MaterialRequest) nhận Lệnh lọc làm nguồn (source_type="batch_filter_order")
   — kế thừa/gộp đúng dòng vật tư của lệnh đó, mirror hành vi đã có sẵn của brew_order.
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
def thukho_h(client):
    return _login(client, "thukho", "123456")


@pytest.fixture(scope="module")
def vanhanh_h(client):
    return _login(client, "vanhanh", "123456")


def _create_material(client, admin_h, code):
    r = client.post("/api/materials", headers=admin_h,
                    json={"code": code, "name": f"Vật tư {code}", "uom": "kg", "category": "other"})
    assert r.status_code == 201, r.text
    return r.json()["material_id"]


def _receive(client, thukho_h, lot_code, material_id, quantity, location="Kho công ty"):
    r = client.post("/api/warehouse/receive", headers=thukho_h,
                    json={"lot_code": lot_code, "material_id": material_id, "quantity": quantity,
                          "uom": "kg", "location": location})
    assert r.status_code == 200, r.text
    return r.json()["lot_id"]


def _make_batch(client, admin_h, batch_code):
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(v for v in vers if v["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                          "batch_code": batch_code, "planned_qty": 1000, "allow_shortage": True})
    assert b.status_code == 201, b.text
    return b.json()["batch_id"]


def _run_batch_to_completed(client, admin_h, batch_id, actual_qty=None):
    for target in ("ready", "running"):
        r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": target})
        assert r.status_code == 200, r.text
    if actual_qty is None:
        actual_qty = client.get(f"/api/batches/{batch_id}", headers=admin_h).json()["planned_qty"]
    aq = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": actual_qty})
    assert aq.status_code == 200, aq.text
    fin = client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={})
    assert fin.status_code == 200, fin.text
    r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "completed"})
    assert r.status_code == 200, r.text
    return r.json()


def _make_tank(client, admin_h, batch_code, tank_code):
    batch_id = _make_batch(client, admin_h, batch_code)
    _run_batch_to_completed(client, admin_h, batch_id)
    r = client.post("/api/batch-tanks", headers=admin_h,
                    json={"batch_ids": [batch_id], "tank_code": tank_code})
    assert r.status_code == 201, r.text
    return r.json()


def test_create_filter_order_with_material_lines_enough_stock_succeeds(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "FLOML-OK-MAT")
    _receive(client, thukho_h, "LOT-FLOML-OK-01", mat_id, 100)
    tank = _make_tank(client, admin_h, "101", "TANK-FLOML-01")

    order = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-FLOML-01",
        "sources": [{"source_type": "tank", "source_tank_id": tank["tank_id"], "planned_v_dich_hl": 900}],
        "lines": [{"material_id": mat_id, "uom": "kg", "qty_planned": 30}],
    })
    assert order.status_code == 201, order.text
    order_id = order.json()["order_id"]

    materials = client.get(f"/api/batch-filter-orders/{order_id}/materials", headers=admin_h).json()
    assert len(materials) == 1
    line = materials[0]
    assert line["material_id"] == mat_id
    assert line["material_code"] == "FLOML-OK-MAT"
    assert line["material_name"] == "Vật tư FLOML-OK-MAT"
    assert line["qty_planned"] == 30
    assert line["uom"] == "kg"
    assert line["stock_company_snapshot"] == 100
    assert line["stock_workshop_snapshot"] == 0


def test_create_filter_order_with_free_text_material_line_skips_stock_check(client, admin_h):
    tank = _make_tank(client, admin_h, "102", "TANK-FLOML-02")
    order = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-FLOML-02",
        "sources": [{"source_type": "tank", "source_tank_id": tank["tank_id"], "planned_v_dich_hl": 900}],
        "lines": [{"material_name": "Bột trợ lọc tự do", "uom": "kg", "qty_planned": 999999}],
    })
    assert order.status_code == 201, order.text
    materials = client.get(f"/api/batch-filter-orders/{order.json()['order_id']}/materials", headers=admin_h).json()
    assert len(materials) == 1
    assert materials[0]["material_id"] is None
    assert materials[0]["material_name"] == "Bột trợ lọc tự do"
    assert materials[0]["qty_planned"] == 999999


def test_create_filter_order_blocked_when_material_line_exceeds_stock(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "FLOML-SHORT-MAT")
    _receive(client, thukho_h, "LOT-FLOML-SHORT-01", mat_id, 10)
    tank = _make_tank(client, admin_h, "103", "TANK-FLOML-03")

    order = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-FLOML-03",
        "sources": [{"source_type": "tank", "source_tank_id": tank["tank_id"], "planned_v_dich_hl": 900}],
        "lines": [{"material_id": mat_id, "uom": "kg", "qty_planned": 500}],
    })
    assert order.status_code == 409, order.text

    listed = client.get("/api/batch-filter-orders", headers=admin_h).json()
    assert not any(o["order_code"] == "LOC-FLOML-03" for o in listed)


def test_material_request_source_preview_batch_filter_order(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "FLOML-REQ-MAT")
    _receive(client, thukho_h, "LOT-FLOML-REQ-01", mat_id, 100)
    tank = _make_tank(client, admin_h, "104", "TANK-FLOML-04")

    order = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-FLOML-04",
        "sources": [{"source_type": "tank", "source_tank_id": tank["tank_id"], "planned_v_dich_hl": 900}],
        "lines": [{"material_id": mat_id, "uom": "kg", "qty_planned": 40}],
    })
    assert order.status_code == 201, order.text
    order_id = order.json()["order_id"]

    r = client.get("/api/warehouse/requests/source-preview", headers=admin_h,
                   params={"source_type": "batch_filter_order", "source_id": order_id})
    assert r.status_code == 200, r.text
    lines = r.json()
    assert len(lines) == 1
    assert lines[0]["material_id"] == mat_id
    assert lines[0]["material_code"] == "FLOML-REQ-MAT"
    assert lines[0]["quantity"] == 40
    assert lines[0]["is_group"] is False


def test_create_request_with_batch_filter_order_source_stores_and_shows_label(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "FLOML-REQ2-MAT")
    _receive(client, thukho_h, "LOT-FLOML-REQ2-01", mat_id, 100)
    tank = _make_tank(client, admin_h, "105", "TANK-FLOML-05")

    order = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-FLOML-05",
        "sources": [{"source_type": "tank", "source_tank_id": tank["tank_id"], "planned_v_dich_hl": 900}],
        "lines": [{"material_id": mat_id, "uom": "kg", "qty_planned": 25}],
    })
    assert order.status_code == 201, order.text
    order_id = order.json()["order_id"]

    r = client.post("/api/warehouse/requests", headers=vanhanh_h, json={
        "lines": [{"material_id": mat_id, "quantity": 25, "uom": "kg"}],
        "source_type": "batch_filter_order", "source_id": order_id,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["source_type"] == "batch_filter_order"
    assert body["source_id"] == order_id
    assert body["source_label"] == "Lệnh lọc LOC-FLOML-05"

    listed = client.get("/api/warehouse/requests", headers=thukho_h).json()
    row = next(x for x in listed if x["request_id"] == body["request_id"])
    assert row["source_label"] == "Lệnh lọc LOC-FLOML-05"


def test_create_request_batch_filter_order_source_not_found(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "FLOML-REQ3-MAT")
    _receive(client, thukho_h, "LOT-FLOML-REQ3-01", mat_id, 50)
    r = client.post("/api/warehouse/requests", headers=vanhanh_h, json={
        "lines": [{"material_id": mat_id, "quantity": 5, "uom": "kg"}],
        "source_type": "batch_filter_order", "source_id": "does-not-exist",
    })
    assert r.status_code == 404, r.text


def test_delete_filter_order_with_material_lines(client, admin_h, thukho_h):
    """Xóa lệnh lọc CÒN dòng vật tư dự kiến — batch_filter_order_material_line.order_id là FK
    tới batch_filter_order, phải xóa dòng con + flush TRƯỚC khi xóa lệnh, nếu không MSSQL enforce
    FK sẽ vỡ 547 (nút "Xóa lệnh lọc" trả 500; SQLite bỏ qua FK nên không lộ)."""
    mat_id = _create_material(client, admin_h, "FLOML-DEL-MAT")
    _receive(client, thukho_h, "LOT-FLOML-DEL-01", mat_id, 100)
    tank = _make_tank(client, admin_h, "109", "TANK-FLOML-DEL")

    order = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-FLOML-DEL",
        "sources": [{"source_type": "tank", "source_tank_id": tank["tank_id"], "planned_v_dich_hl": 900}],
        "lines": [{"material_id": mat_id, "uom": "kg", "qty_planned": 30}],
    })
    assert order.status_code == 201, order.text
    order_id = order.json()["order_id"]
    assert len(client.get(f"/api/batch-filter-orders/{order_id}/materials", headers=admin_h).json()) == 1

    d = client.delete(f"/api/batch-filter-orders/{order_id}", headers=admin_h)
    assert d.status_code in (200, 204), d.text
    listed = client.get("/api/batch-filter-orders", headers=admin_h).json()
    assert not any(o["order_id"] == order_id for o in listed)
