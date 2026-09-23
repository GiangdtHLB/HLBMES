"""Sửa phiếu "Đề nghị nhận kho": thêm/sửa "Ngày đề nghị nhận kho" (khác ngày lập phiếu, không
sửa) + sửa vật tư/số lượng của các dòng còn "pending". Chỉ người có quyền tạo đề nghị
(warehouse.request, phía phân xưởng) mới sửa được — không phải thủ kho công ty
(warehouse.issue). Ngày đề nghị nhận kho dùng làm `ts` hiệu lực của StockMovement transfer khi
duyệt (xem services/warehouse.py::update_request/fulfill_request_line/fulfill_all_lines)."""

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


def _receive(client, thukho_h, mat_id, lot_code, qty, received_at=None):
    payload = {"lot_code": lot_code, "material_id": mat_id, "quantity": qty, "uom": "kg"}
    if received_at:
        payload["received_at"] = received_at
    r = client.post("/api/warehouse/receive", headers=thukho_h, json=payload)
    assert r.status_code == 200, r.text
    return r.json()["lot_id"]


def test_create_request_with_receipt_date_and_edit(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "REQEDIT-01")
    # Nhận kho TRƯỚC cả "Ngày đề nghị nhận kho" sẽ khai dưới đây (2026-09-18: fulfill giờ chặn
    # cứng nếu lô chưa Nhập kho tính đến ngày đề nghị — mirror dispense.py as_of), để không lẫn
    # với chính bug đang được test bằng test_material_request_source.py.
    _receive(client, thukho_h, mat_id, "LOT-REQEDIT-01", 100,
             received_at=(utcnow() - timedelta(days=5)).isoformat())

    wanted_date = (utcnow() - timedelta(days=2)).isoformat()
    req = client.post("/api/warehouse/requests", headers=vanhanh_h,
                      json={"lines": [{"material_id": mat_id, "quantity": 20}],
                            "requested_receipt_date": wanted_date})
    assert req.status_code == 201, req.text
    body = req.json()
    request_id = body["request_id"]
    line_id = body["lines"][0]["line_id"]
    assert body["requested_receipt_date"] is not None
    assert body["requested_at"] is not None  # ngày lập phiếu, tự động, không sửa qua create

    # thukho (chỉ warehouse.issue) KHÔNG được sửa phiếu.
    denied = client.put(f"/api/warehouse/requests/{request_id}", headers=thukho_h,
                        json={"requested_receipt_date": wanted_date})
    assert denied.status_code == 403, denied.text

    # vanhanh (warehouse.request) sửa được: đổi ngày đề nghị nhận + số lượng dòng.
    new_date = (utcnow() - timedelta(days=1)).isoformat()
    upd = client.put(f"/api/warehouse/requests/{request_id}", headers=vanhanh_h,
                     json={"requested_receipt_date": new_date,
                           "lines": [{"line_id": line_id, "quantity": 35}]})
    assert upd.status_code == 200, upd.text
    updated = upd.json()
    assert updated["lines"][0]["quantity"] == 35

    # Sửa vượt quá tồn kho công ty hiện có -> chặn.
    over = client.put(f"/api/warehouse/requests/{request_id}", headers=vanhanh_h,
                      json={"lines": [{"line_id": line_id, "quantity": 9999}]})
    assert over.status_code == 409, over.text

    # Duyệt dòng — StockMovement.ts phải khớp đúng "Ngày đề nghị nhận kho" đã sửa, không phải
    # thời điểm bấm Duyệt (mirror approve_sang_ngang).
    lots = client.get("/api/lots", headers=admin_h).json()
    lot = next(l for l in lots if l["lot_code"] == "LOT-REQEDIT-01")
    ful = client.post(f"/api/warehouse/requests/{request_id}/lines/{line_id}/fulfill",
                      headers=thukho_h, json={"lot_id": lot["lot_id"], "quantity": 35})
    assert ful.status_code == 200, ful.text

    request_code = body["request_code"]
    movements = client.get("/api/warehouse/movements?movement_type=transfer", headers=admin_h).json()
    mv = next(m for m in movements if m["mode"] == "xuat_theo_de_nghi" and request_code in (m["reason"] or ""))
    mv_ts = mv["ts"][:10]
    assert mv_ts == new_date[:10]


def test_cannot_edit_already_fulfilled_line(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "REQEDIT-02")
    lot_id = _receive(client, thukho_h, mat_id, "LOT-REQEDIT-02", 100)

    req = client.post("/api/warehouse/requests", headers=vanhanh_h,
                      json={"lines": [{"material_id": mat_id, "quantity": 10}]})
    request_id = req.json()["request_id"]
    line_id = req.json()["lines"][0]["line_id"]

    ful = client.post(f"/api/warehouse/requests/{request_id}/lines/{line_id}/fulfill",
                      headers=thukho_h, json={"lot_id": lot_id, "quantity": 10})
    assert ful.status_code == 200, ful.text

    # Dòng đã fulfilled -> sửa bị chặn (khóa lịch sử đã xử lý).
    edit_fulfilled = client.put(f"/api/warehouse/requests/{request_id}", headers=vanhanh_h,
                                json={"lines": [{"line_id": line_id, "quantity": 5}]})
    assert edit_fulfilled.status_code == 409, edit_fulfilled.text

    # Đã có dòng fulfilled -> ngày đề nghị nhận (header) cũng KHÔNG sửa được nữa (yêu cầu người
    # dùng 2026-09-23: "nếu có ít nhất 1 vật tư đã được xuất thì không cho sửa ngày đề nghị
    # nhận" — đảo lại quyết định cũ, vì ngày này đã ghi cứng vào StockMovement.ts của dòng đã xuất).
    new_date = utcnow().isoformat()
    edit_date = client.put(f"/api/warehouse/requests/{request_id}", headers=vanhanh_h,
                           json={"requested_receipt_date": new_date})
    assert edit_date.status_code == 409, edit_date.text


def test_edit_multi_line_request_only_touches_pending_line(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "REQEDIT-03")
    lot_id = _receive(client, thukho_h, mat_id, "LOT-REQEDIT-03", 100)

    req = client.post("/api/warehouse/requests", headers=vanhanh_h,
                      json={"lines": [{"material_id": mat_id, "quantity": 10},
                                      {"material_id": mat_id, "quantity": 15}]})
    line1_id = req.json()["lines"][0]["line_id"]
    line2_id = req.json()["lines"][1]["line_id"]
    request_id = req.json()["request_id"]

    ful = client.post(f"/api/warehouse/requests/{request_id}/lines/{line1_id}/fulfill",
                      headers=thukho_h, json={"lot_id": lot_id, "quantity": 10})
    assert ful.status_code == 200, ful.text

    # Sửa dòng 2 (còn pending) trong cùng phiếu đã có dòng 1 fulfilled -> vẫn cho phép.
    upd = client.put(f"/api/warehouse/requests/{request_id}", headers=vanhanh_h,
                     json={"lines": [{"line_id": line2_id, "quantity": 22}]})
    assert upd.status_code == 200, upd.text
    line2 = next(l for l in upd.json()["lines"] if l["line_id"] == line2_id)
    assert line2["quantity"] == 22


def test_add_and_delete_request_line(client, admin_h, thukho_h, vanhanh_h):
    """Yêu cầu người dùng 2026-09-23: "sửa đề nghị nhận vật tư thì cho tôi sửa số lượng, hoặc xóa
    hoặc thêm vật tư ... nếu vật tư đó chưa được xuất"."""
    mat1 = _create_material(client, admin_h, "REQEDIT-04A")
    mat2 = _create_material(client, admin_h, "REQEDIT-04B")
    _receive(client, thukho_h, mat1, "LOT-REQEDIT-04A", 100)
    lot2_id = _receive(client, thukho_h, mat2, "LOT-REQEDIT-04B", 50)

    req = client.post("/api/warehouse/requests", headers=vanhanh_h,
                      json={"lines": [{"material_id": mat1, "quantity": 10}]})
    assert req.status_code == 201, req.text
    request_id = req.json()["request_id"]
    line1_id = req.json()["lines"][0]["line_id"]

    # thukho (chỉ warehouse.issue) không được thêm/xóa dòng.
    denied_add = client.post(f"/api/warehouse/requests/{request_id}/lines", headers=thukho_h,
                             json={"material_id": mat2, "quantity": 5})
    assert denied_add.status_code == 403, denied_add.text

    # Thêm 1 dòng vật tư mới vào phiếu đã có sẵn.
    add = client.post(f"/api/warehouse/requests/{request_id}/lines", headers=vanhanh_h,
                      json={"material_id": mat2, "quantity": 5})
    assert add.status_code == 201, add.text
    body = add.json()
    assert len(body["lines"]) == 2
    line2 = next(l for l in body["lines"] if l["material_id"] == mat2)
    assert line2["quantity"] == 5 and line2["status"] == "pending"
    line2_id = line2["line_id"]

    # Thêm vượt quá tồn kho công ty -> chặn, không thêm dòng.
    over = client.post(f"/api/warehouse/requests/{request_id}/lines", headers=vanhanh_h,
                       json={"material_id": mat2, "quantity": 9999})
    assert over.status_code == 409, over.text

    # Duyệt dòng 2 -> không xóa được nữa (đã xuất).
    ful = client.post(f"/api/warehouse/requests/{request_id}/lines/{line2_id}/fulfill",
                      headers=thukho_h, json={"lot_id": lot2_id, "quantity": 5})
    assert ful.status_code == 200, ful.text
    denied_del = client.delete(f"/api/warehouse/requests/{request_id}/lines/{line2_id}", headers=vanhanh_h)
    assert denied_del.status_code == 409, denied_del.text

    # Dòng 1 vẫn "pending" (chưa xuất) -> xóa được.
    delr = client.delete(f"/api/warehouse/requests/{request_id}/lines/{line1_id}", headers=vanhanh_h)
    assert delr.status_code == 200, delr.text
    remaining = [l["line_id"] for l in delr.json()["lines"]]
    assert line1_id not in remaining and line2_id in remaining
