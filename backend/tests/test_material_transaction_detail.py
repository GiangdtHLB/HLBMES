"""GET /warehouse/report/material-detail — "Sổ chi tiết vật tư" khi bấm vào 1 mã ở BC nhập-xuất-
tồn (yêu cầu người dùng 2026-09-14). Phủ: tổng Nhập/Xuất từng dòng phải khớp đúng với số
"received"/"issued" đã hiển thị ở /warehouse/report (cùng vật tư/kỳ/kho) — kể cả Cấp liệu vào mẻ
Nấu (không tạo StockMovement riêng, chỉ có GenealogyEdge consume, xem
services/warehouse.py::_consumed_lot_edges)."""

import os
import tempfile

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["MES_DATABASE_URL"] = f"sqlite:///{_TMP.name}"
os.environ["MES_DEV_HEADER_AUTH"] = "0"
os.environ["MES_RL_ENABLED"] = "0"
os.environ["MES_ADMIN_PASSWORD"] = "AdminTest123"

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.common import utcnow
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


def _make_batch(client, admin_h):
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(x for x in vers if x["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                          "planned_qty": 1000, "allow_shortage": True})
    assert b.status_code == 201, b.text
    return b.json()["batch_id"]


def _period():
    start = (utcnow() - timedelta(days=1)).isoformat()
    end = (utcnow() + timedelta(days=1)).isoformat()
    return start, end


def test_detail_reconciles_with_report_totals_plain_warehouse_only(client, admin_h):
    mat = client.post("/api/materials", headers=admin_h,
                      json={"code": "MDETAIL01", "name": "M Detail 01", "uom": "kg", "category": "other"})
    material_id = mat.json()["material_id"]
    recv = client.post("/api/warehouse/receive", headers=admin_h,
                       json={"lot_code": "LOT-MDETAIL01", "material_id": material_id, "quantity": 80, "uom": "kg"})
    assert recv.status_code == 200, recv.text
    lot_id = recv.json()["lot_id"]
    tr = client.post("/api/warehouse/transfer", headers=admin_h,
                     json={"lot_id": lot_id, "quantity": 30, "location_to": "Kho phân xưởng"})
    assert tr.status_code == 200, tr.text

    date_from, date_to = _period()
    rep = client.get("/api/warehouse/report", headers=admin_h,
                     params={"date_from": date_from, "date_to": date_to, "location": "Kho công ty"}).json()
    row = next(r for r in rep if r["material_id"] == material_id)

    detail = client.get("/api/warehouse/report/material-detail", headers=admin_h,
                        params={"material_id": material_id, "date_from": date_from, "date_to": date_to,
                               "location": "Kho công ty"}).json()
    total_in = sum(r["in"] for r in detail["rows"])
    total_out = sum(r["out"] for r in detail["rows"])
    assert total_in == pytest.approx(row["received"])
    assert total_out == pytest.approx(row["issued"])
    assert detail["closing_balance"] == pytest.approx(detail["opening_balance"] + total_in - total_out)


def test_detail_includes_dispense_into_batch_reconciles_with_report(client, admin_h):
    mat = client.post("/api/materials", headers=admin_h,
                      json={"code": "MDETAIL02", "name": "M Detail 02", "uom": "kg", "category": "other"})
    mat_code, material_id = "MDETAIL02", mat.json()["material_id"]
    recv = client.post("/api/warehouse/receive", headers=admin_h,
                       json={"lot_code": "LOT-MDETAIL02", "material_id": material_id, "quantity": 50, "uom": "kg"})
    lot_id = recv.json()["lot_id"]
    client.post("/api/warehouse/transfer", headers=admin_h,
               json={"lot_id": lot_id, "quantity": 50, "location_to": "Kho phân xưởng"})

    batch_id = _make_batch(client, admin_h)
    client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "ready"})
    client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "running"})
    disp = client.post(f"/api/dispense/{batch_id}", headers=admin_h,
                       json={"lines": [{"material_code": mat_code, "quantity": 15}]})
    assert disp.status_code == 200, disp.text

    date_from, date_to = _period()
    rep = client.get("/api/warehouse/report", headers=admin_h,
                     params={"date_from": date_from, "date_to": date_to, "location": "Kho phân xưởng"}).json()
    row = next(r for r in rep if r["material_id"] == material_id)
    assert row["issued"] == pytest.approx(15)  # xác nhận Cấp liệu ĐÃ tính vào "Xuất" (baseline hiện có)

    detail = client.get("/api/warehouse/report/material-detail", headers=admin_h,
                        params={"material_id": material_id, "date_from": date_from, "date_to": date_to,
                               "location": "Kho phân xưởng"}).json()
    total_out = sum(r["out"] for r in detail["rows"])
    assert total_out == pytest.approx(row["issued"])
    consume_rows = [r for r in detail["rows"] if r["type"] == "consume"]
    assert len(consume_rows) == 1
    assert consume_rows[0]["out"] == pytest.approx(15)
    assert "Cấp liệu" in consume_rows[0]["reason"]
