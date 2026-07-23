"""Test cổng khai báo/duyệt chỉ tiêu chất lượng NVL + đề nghị nhận kho.

Phủ: gate on_hold khi nhận lô của nguyên liệu có gán nhóm chỉ tiêu bắt buộc,
hành vi không đổi khi không gán nhóm, chặn release khi thiếu khai báo,
chặn transfer khi đang on_hold, permission quality.release, và luồng đề nghị
nhận kho (tạo/duyệt/từ chối, chặn khi lô on_hold) + lọc báo cáo theo kho.
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
from app.database import SessionLocal
from app.models.materials import GenealogyEdge


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
def kcs_h(client):
    return _login(client, "kcs", "123456")


@pytest.fixture(scope="module")
def vanhanh_h(client):
    return _login(client, "vanhanh", "123456")


def _create_material(client, admin_h, code):
    r = client.post("/api/materials", headers=admin_h,
                    json={"code": code, "name": f"Vật tư {code}", "uom": "kg", "category": "other"})
    assert r.status_code == 201, r.text
    return r.json()["material_id"]


def test_receive_without_qc_group_stays_available(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "QCT-NOGROUP")
    r = client.post("/api/warehouse/receive", headers=thukho_h,
                    json={"lot_code": "LOT-NOGROUP-01", "material_id": mat_id, "quantity": 100, "uom": "kg"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "available"


def test_receive_with_mandatory_group_holds_then_release_flow(client, admin_h, thukho_h, kcs_h):
    mat_id = _create_material(client, admin_h, "QCT-MALT")

    # Danh mục: tạo chỉ tiêu + nhóm + gán chỉ tiêu vào nhóm + gán nhóm cho nguyên liệu.
    p = client.post("/api/qc/parameters", headers=admin_h,
                    json={"code": "DO_AM_TEST", "name": "Độ ẩm", "unit": "%", "lsl": 3, "usl": 6})
    assert p.status_code == 201, p.text
    param_id = p.json()["param_id"]

    g = client.post("/api/qc/groups", headers=admin_h,
                    json={"code": "GRP-MALT-TEST", "name": "Chỉ tiêu Malt test"})
    assert g.status_code == 201, g.text
    group_id = g.json()["group_id"]

    it = client.post(f"/api/qc/groups/{group_id}/items", headers=admin_h,
                     json={"param_id": param_id, "mandatory": True})
    assert it.status_code == 201, it.text

    link = client.post(f"/api/materials/{mat_id}/qc-groups", headers=admin_h,
                       json={"group_id": group_id, "mandatory": True})
    assert link.status_code == 201, link.text

    # Nhập kho lô mới → phải HOLD ngay (chưa khai báo chỉ tiêu).
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "LOT-MALT-01", "material_id": mat_id, "quantity": 500, "uom": "kg"})
    assert rc.status_code == 200, rc.text
    assert rc.json()["status"] == "on_hold"
    lot_id = rc.json()["lot_id"]

    # qc-status: còn thiếu khai báo → can_release False.
    st = client.get(f"/api/lots/{lot_id}/qc-status", headers=thukho_h).json()
    assert st["pending"] == ["DO_AM_TEST"]
    assert st["can_release"] is False

    # Xuất/chuyển kho khi đang HOLD → 409.
    xfer_blocked = client.post("/api/warehouse/transfer", headers=thukho_h,
                               json={"lot_id": lot_id, "quantity": 500, "location_to": "Kho phân xưởng"})
    assert xfer_blocked.status_code == 409, xfer_blocked.text

    # KCS duyệt khi chưa khai báo đủ → 409.
    rel_blocked = client.post("/api/quality/hold", headers=kcs_h,
                              json={"scope_type": "lot", "scope_id": lot_id, "on_hold": False})
    assert rel_blocked.status_code == 409, rel_blocked.text

    # Thủ kho (operator) khai báo giá trị trong khoảng min/max.
    rec = client.post("/api/quality/results", headers=thukho_h,
                      json={"scope_type": "lot", "scope_id": lot_id, "parameter": "DO_AM_TEST",
                            "value": 4.5, "lower_limit": 3, "upper_limit": 6})
    assert rec.status_code == 201, rec.text
    assert rec.json()["status"] == "pass"

    # Thủ kho không có quyền quality.release → không tự duyệt được.
    rel_noperm = client.post("/api/quality/hold", headers=thukho_h,
                             json={"scope_type": "lot", "scope_id": lot_id, "on_hold": False})
    assert rel_noperm.status_code == 403, rel_noperm.text

    # KCS duyệt sau khi đã khai báo đủ → OK.
    rel_ok = client.post("/api/quality/hold", headers=kcs_h,
                         json={"scope_type": "lot", "scope_id": lot_id, "on_hold": False})
    assert rel_ok.status_code == 200, rel_ok.text
    assert rel_ok.json()["quality_status"] == "released"

    # Sau khi duyệt: chuyển sang kho phân xưởng phải thành công.
    xfer_ok = client.post("/api/warehouse/transfer", headers=thukho_h,
                          json={"lot_id": lot_id, "quantity": 500, "location_to": "Kho phân xưởng"})
    assert xfer_ok.status_code == 200, xfer_ok.text
    assert xfer_ok.json()["location"] == "Kho phân xưởng"


def test_material_request_permission_required(client, thukho_h):
    # thủ kho không có quyền warehouse.request → không tạo được đề nghị.
    r = client.post("/api/warehouse/requests", headers=thukho_h,
                    json={"lines": [{"material_id": "x", "quantity": 10}]})
    assert r.status_code == 403, r.text


def test_material_request_multi_line_fulfill_flow(client, admin_h, thukho_h, vanhanh_h):
    """1 phiếu gồm NHIỀU dòng vật tư khác nhau — mỗi dòng xử lý độc lập."""
    mat_a = _create_material(client, admin_h, "REQ-MALT")
    mat_b = _create_material(client, admin_h, "REQ-HOP")
    rc_a = client.post("/api/warehouse/receive", headers=thukho_h,
                       json={"lot_code": "LOT-REQ-A", "material_id": mat_a, "quantity": 200, "uom": "kg"})
    lot_a = rc_a.json()["lot_id"]
    assert rc_a.json()["status"] == "available"   # không gán nhóm chỉ tiêu → available ngay
    rc_b = client.post("/api/warehouse/receive", headers=thukho_h,
                       json={"lot_code": "LOT-REQ-B", "material_id": mat_b, "quantity": 60, "uom": "kg"})
    lot_b = rc_b.json()["lot_id"]

    # Phân xưởng (vanhanh) tạo 1 phiếu duy nhất gồm 2 dòng vật tư khác nhau.
    req = client.post("/api/warehouse/requests", headers=vanhanh_h,
                      json={"lines": [
                          {"material_id": mat_a, "quantity": 50, "uom": "kg", "preferred_lot_id": lot_a},
                          {"material_id": mat_b, "quantity": 20, "uom": "kg", "preferred_lot_id": lot_b},
                      ], "note": "Cần cho mẻ nấu"})
    assert req.status_code == 201, req.text
    body = req.json()
    request_id = body["request_id"]
    assert len(body["lines"]) == 2   # 1 phiếu, 2 dòng — không tách thành 2 phiếu riêng
    line_a, line_b = body["lines"][0], body["lines"][1]
    assert line_a["material_id"] == mat_a and line_a["status"] == "pending"
    assert line_b["material_id"] == mat_b and line_b["status"] == "pending"

    lst = client.get("/api/warehouse/requests?status=pending", headers=thukho_h).json()
    found = next(r for r in lst if r["request_id"] == request_id)
    assert len(found["lines"]) == 2

    # Thủ kho duyệt dòng A: chuyển lô sang Kho phân xưởng (transfer, không phải issue).
    ful_a = client.post(f"/api/warehouse/requests/{request_id}/lines/{line_a['line_id']}/fulfill",
                        headers=thukho_h, json={"lot_id": lot_a, "quantity": 50})
    assert ful_a.status_code == 200, ful_a.text
    assert ful_a.json()["location"] == "Kho phân xưởng"

    lot_after = client.get("/api/lots", headers=thukho_h).json()
    lot_row = next(l for l in lot_after if l["lot_id"] == lot_a)
    assert lot_row["location"] == "Kho phân xưởng"
    assert lot_row["quantity"] == 200   # transfer không đổi tổng tồn của lô

    # Dòng B vẫn đang pending, độc lập với dòng A đã fulfilled.
    after_a = next(r for r in client.get("/api/warehouse/requests", headers=thukho_h).json()
                   if r["request_id"] == request_id)
    statuses = {l["line_id"]: l["status"] for l in after_a["lines"]}
    assert statuses[line_a["line_id"]] == "fulfilled"
    assert statuses[line_b["line_id"]] == "pending"

    # Xử lý lại dòng đã fulfilled → 409.
    again = client.post(f"/api/warehouse/requests/{request_id}/lines/{line_a['line_id']}/fulfill",
                        headers=thukho_h, json={"lot_id": lot_a, "quantity": 50})
    assert again.status_code == 409, again.text

    # Từ chối dòng B với lý do.
    rej_b = client.post(f"/api/warehouse/requests/{request_id}/lines/{line_b['line_id']}/reject",
                        headers=thukho_h, json={"reason": "Hết tồn phù hợp"})
    assert rej_b.status_code == 200, rej_b.text
    assert rej_b.json()["status"] == "rejected"


def test_material_request_fulfill_custom_destination(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "REQ-DEST")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "LOT-DEST-01", "material_id": mat_id, "quantity": 80, "uom": "kg"})
    lot_id = rc.json()["lot_id"]
    req = client.post("/api/warehouse/requests", headers=vanhanh_h,
                      json={"lines": [{"material_id": mat_id, "quantity": 30}]})
    request_id = req.json()["request_id"]
    line_id = req.json()["lines"][0]["line_id"]

    # Thủ kho chọn kho đích khác mặc định "Kho phân xưởng" — vd 1 phân xưởng cụ thể.
    ful = client.post(f"/api/warehouse/requests/{request_id}/lines/{line_id}/fulfill", headers=thukho_h,
                      json={"lot_id": lot_id, "quantity": 30, "location_to": "Kho phân xưởng Nấu A"})
    assert ful.status_code == 200, ful.text
    assert ful.json()["location"] == "Kho phân xưởng Nấu A"


def test_material_request_fulfill_blocked_on_hold(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "REQ-ONHOLD")
    p = client.post("/api/qc/parameters", headers=admin_h,
                    json={"code": "CT_ONHOLD_TEST", "name": "Chỉ tiêu test"})
    g = client.post("/api/qc/groups", headers=admin_h, json={"code": "GRP-ONHOLD-TEST", "name": "Nhóm test"})
    group_id = g.json()["group_id"]
    client.post(f"/api/qc/groups/{group_id}/items", headers=admin_h,
               json={"param_id": p.json()["param_id"], "mandatory": True})
    client.post(f"/api/materials/{mat_id}/qc-groups", headers=admin_h,
               json={"group_id": group_id, "mandatory": True})

    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "LOT-ONHOLD-REQ", "material_id": mat_id, "quantity": 100, "uom": "kg"})
    lot_id = rc.json()["lot_id"]
    assert rc.json()["status"] == "on_hold"

    req = client.post("/api/warehouse/requests", headers=vanhanh_h,
                      json={"lines": [{"material_id": mat_id, "quantity": 10}]})
    request_id = req.json()["request_id"]
    line_id = req.json()["lines"][0]["line_id"]

    ful = client.post(f"/api/warehouse/requests/{request_id}/lines/{line_id}/fulfill", headers=thukho_h,
                      json={"lot_id": lot_id, "quantity": 10})
    assert ful.status_code == 409, ful.text


def test_inventory_report_location_filter(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "REP-LOC")
    client.post("/api/warehouse/receive", headers=thukho_h,
               json={"lot_code": "LOT-REP-01", "material_id": mat_id, "quantity": 300, "uom": "kg"})

    rep_all = client.get("/api/warehouse/report?days=1", headers=thukho_h).json()
    row_all = next(r for r in rep_all if r["material_id"] == mat_id)
    assert row_all["on_hand"] == 300

    rep_ct = client.get("/api/warehouse/report?days=1&location=" + "Kho công ty", headers=thukho_h).json()
    row_ct = next(r for r in rep_ct if r["material_id"] == mat_id)
    assert row_ct["on_hand"] == 300

    rep_px = client.get("/api/warehouse/report?days=1&location=" + "Kho phân xưởng", headers=thukho_h).json()
    assert not any(r["material_id"] == mat_id for r in rep_px)


def test_material_request_rejects_qty_over_stock(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "REQ-OVERQTY")
    client.post("/api/warehouse/receive", headers=thukho_h,
               json={"lot_code": "LOT-OVERQTY-01", "material_id": mat_id, "quantity": 40, "uom": "kg"})
    # Đề nghị 100kg trong khi kho công ty chỉ có 40kg → phải bị chặn.
    r = client.post("/api/warehouse/requests", headers=vanhanh_h,
                    json={"lines": [{"material_id": mat_id, "quantity": 100, "uom": "kg"}]})
    assert r.status_code == 409, r.text
    # Đề nghị đúng bằng tồn (40kg) thì hợp lệ.
    ok = client.post("/api/warehouse/requests", headers=vanhanh_h,
                     json={"lines": [{"material_id": mat_id, "quantity": 40, "uom": "kg"}]})
    assert ok.status_code == 201, ok.text


def test_material_request_fulfill_all(client, admin_h, thukho_h, vanhanh_h):
    mat_a = _create_material(client, admin_h, "REQALL-A")
    mat_b = _create_material(client, admin_h, "REQALL-B")
    client.post("/api/warehouse/receive", headers=thukho_h,
               json={"lot_code": "LOT-REQALL-A", "material_id": mat_a, "quantity": 90, "uom": "kg"})
    client.post("/api/warehouse/receive", headers=thukho_h,
               json={"lot_code": "LOT-REQALL-B", "material_id": mat_b, "quantity": 40, "uom": "kg"})

    req = client.post("/api/warehouse/requests", headers=vanhanh_h,
                      json={"lines": [
                          {"material_id": mat_a, "quantity": 30, "uom": "kg"},
                          {"material_id": mat_b, "quantity": 15, "uom": "kg"},
                      ]})
    request_id = req.json()["request_id"]

    ful = client.post(f"/api/warehouse/requests/{request_id}/fulfill-all", headers=thukho_h, json={})
    assert ful.status_code == 200, ful.text
    body = ful.json()
    assert len(body["fulfilled"]) == 2 and not body["skipped"]

    after = next(r for r in client.get("/api/warehouse/requests", headers=thukho_h).json()
                if r["request_id"] == request_id)
    assert all(l["status"] == "fulfilled" for l in after["lines"])

    lots = client.get("/api/lots", headers=thukho_h).json()
    lot_a = next(l for l in lots if l["lot_code"] == "LOT-REQALL-A")
    lot_b = next(l for l in lots if l["lot_code"] == "LOT-REQALL-B")
    assert lot_a["location"] == "Kho phân xưởng"
    assert lot_b["location"] == "Kho phân xưởng"


def test_material_request_fulfill_all_skips_on_hold_line(client, admin_h, thukho_h, vanhanh_h):
    mat_ok = _create_material(client, admin_h, "REQALL-OK")
    mat_hold = _create_material(client, admin_h, "REQALL-HOLD")
    client.post("/api/warehouse/receive", headers=thukho_h,
               json={"lot_code": "LOT-REQALL-OK", "material_id": mat_ok, "quantity": 50, "uom": "kg"})

    p = client.post("/api/qc/parameters", headers=admin_h,
                    json={"code": "CT_FULFILLALL_HOLD", "name": "Chỉ tiêu test"})
    g = client.post("/api/qc/groups", headers=admin_h, json={"code": "GRP-FULFILLALL-HOLD", "name": "Nhóm test"})
    group_id = g.json()["group_id"]
    client.post(f"/api/qc/groups/{group_id}/items", headers=admin_h,
               json={"param_id": p.json()["param_id"], "mandatory": True})
    client.post(f"/api/materials/{mat_hold}/qc-groups", headers=admin_h,
               json={"group_id": group_id, "mandatory": True})
    client.post("/api/warehouse/receive", headers=thukho_h,
               json={"lot_code": "LOT-REQALL-HOLD", "material_id": mat_hold, "quantity": 20, "uom": "kg"})

    req = client.post("/api/warehouse/requests", headers=vanhanh_h,
                      json={"lines": [
                          {"material_id": mat_ok, "quantity": 10, "uom": "kg"},
                          {"material_id": mat_hold, "quantity": 5, "uom": "kg"},
                      ]})
    request_id = req.json()["request_id"]

    ful = client.post(f"/api/warehouse/requests/{request_id}/fulfill-all", headers=thukho_h, json={})
    assert ful.status_code == 200, ful.text
    body = ful.json()
    assert len(body["fulfilled"]) == 1
    assert len(body["skipped"]) == 1

    after = next(r for r in client.get("/api/warehouse/requests", headers=thukho_h).json()
                if r["request_id"] == request_id)
    statuses = {l["material_id"]: l["status"] for l in after["lines"]}
    assert statuses[mat_ok] == "fulfilled"
    assert statuses[mat_hold] == "pending"   # bị bỏ qua, vẫn chờ xử lý thủ công


def test_cancel_request_when_all_pending(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "CANCEL-OK")
    client.post("/api/warehouse/receive", headers=thukho_h,
               json={"lot_code": "LOT-CANCEL-OK", "material_id": mat_id, "quantity": 50, "uom": "kg"})
    req = client.post("/api/warehouse/requests", headers=vanhanh_h,
                      json={"lines": [{"material_id": mat_id, "quantity": 10}]})
    request_id = req.json()["request_id"]

    r = client.delete(f"/api/warehouse/requests/{request_id}", headers=vanhanh_h)
    assert r.status_code == 200, r.text
    after = next(x for x in client.get("/api/warehouse/requests", headers=thukho_h).json()
                if x["request_id"] == request_id)
    assert all(l["status"] == "cancelled" for l in after["lines"])


def test_cancel_request_blocked_when_a_line_fulfilled(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "CANCEL-BLOCK")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "LOT-CANCEL-BLOCK", "material_id": mat_id, "quantity": 50, "uom": "kg"})
    lot_id = rc.json()["lot_id"]
    req = client.post("/api/warehouse/requests", headers=vanhanh_h,
                      json={"lines": [{"material_id": mat_id, "quantity": 10}]})
    request_id = req.json()["request_id"]
    line_id = req.json()["lines"][0]["line_id"]
    ful = client.post(f"/api/warehouse/requests/{request_id}/lines/{line_id}/fulfill",
                      headers=thukho_h, json={"lot_id": lot_id, "quantity": 10})
    assert ful.status_code == 200, ful.text

    r = client.delete(f"/api/warehouse/requests/{request_id}", headers=vanhanh_h)
    assert r.status_code == 409, r.text


def test_undo_fulfill_line_success(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "UNDO-OK")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "LOT-UNDO-OK", "material_id": mat_id, "quantity": 50, "uom": "kg"})
    lot_id = rc.json()["lot_id"]
    req = client.post("/api/warehouse/requests", headers=vanhanh_h,
                      json={"lines": [{"material_id": mat_id, "quantity": 20}]})
    request_id = req.json()["request_id"]
    line_id = req.json()["lines"][0]["line_id"]
    ful = client.post(f"/api/warehouse/requests/{request_id}/lines/{line_id}/fulfill",
                      headers=thukho_h, json={"lot_id": lot_id, "quantity": 20})
    assert ful.status_code == 200, ful.text

    undo = client.post(f"/api/warehouse/requests/{request_id}/lines/{line_id}/undo-fulfill", headers=thukho_h)
    assert undo.status_code == 200, undo.text
    assert undo.json()["status"] == "pending"

    lots = client.get("/api/lots", headers=thukho_h).json()
    lot_row = next(l for l in lots if l["lot_id"] == lot_id)
    assert lot_row["location"] == "Kho công ty"
    assert lot_row["quantity"] == 50


def test_undo_fulfill_line_blocked_when_consumed(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "UNDO-BLOCK")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "LOT-UNDO-BLOCK", "material_id": mat_id, "quantity": 50, "uom": "kg"})
    lot_id = rc.json()["lot_id"]
    req = client.post("/api/warehouse/requests", headers=vanhanh_h,
                      json={"lines": [{"material_id": mat_id, "quantity": 20}]})
    request_id = req.json()["request_id"]
    line_id = req.json()["lines"][0]["line_id"]
    ful = client.post(f"/api/warehouse/requests/{request_id}/lines/{line_id}/fulfill",
                      headers=thukho_h, json={"lot_id": lot_id, "quantity": 20})
    assert ful.status_code == 200, ful.text

    # Giả lập lô đã được dùng cho mẻ sản xuất (genealogy consume edge) — tái dùng bảng
    # có sẵn thay vì dựng toàn bộ pipeline work-order/recipe/batch chỉ để test cờ chặn.
    db = SessionLocal()
    try:
        db.add(GenealogyEdge(from_type="lot", from_id=lot_id, to_type="batch", to_id="fake-batch",
                             relation="consume", quantity=20, uom="kg"))
        db.commit()
    finally:
        db.close()

    undo = client.post(f"/api/warehouse/requests/{request_id}/lines/{line_id}/undo-fulfill", headers=thukho_h)
    assert undo.status_code == 409, undo.text


def test_transfer_to_company_blocked_when_not_at_workshop(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "DC-BLOCK")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "LOT-DC-BLOCK", "material_id": mat_id, "quantity": 30, "uom": "kg"})
    lot_id = rc.json()["lot_id"]
    r = client.post("/api/warehouse/transfer-to-company", headers=thukho_h,
                    json={"lot_id": lot_id, "quantity": 30})
    assert r.status_code == 409, r.text


def test_transfer_to_company_ok(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "DC-OK")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "LOT-DC-OK", "material_id": mat_id, "quantity": 30, "uom": "kg"})
    lot_id = rc.json()["lot_id"]
    client.post("/api/warehouse/transfer", headers=thukho_h,
               json={"lot_id": lot_id, "quantity": 30, "location_to": "Kho phân xưởng"})

    r = client.post("/api/warehouse/transfer-to-company", headers=thukho_h,
                    json={"lot_id": lot_id, "quantity": 30, "reason": "Nhận thừa"})
    assert r.status_code == 200, r.text
    assert r.json()["location"] == "Kho công ty"

    hist = client.get("/api/warehouse/movements?movement_type=transfer&mode=dieu_chuyen", headers=thukho_h).json()
    assert any(m["lot_id"] == lot_id for m in hist)


def test_return_to_supplier_requires_reason(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "NCC-NOREASON")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "LOT-NCC-NOREASON", "material_id": mat_id, "quantity": 40, "uom": "kg"})
    lot_id = rc.json()["lot_id"]
    r = client.post("/api/warehouse/return-to-supplier", headers=thukho_h,
                    json={"lot_id": lot_id, "quantity": 10, "reason": ""})
    assert r.status_code == 409, r.text


def test_return_to_supplier_ok(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "NCC-OK")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "LOT-NCC-OK", "material_id": mat_id, "quantity": 40, "uom": "kg"})
    lot_id = rc.json()["lot_id"]
    r = client.post("/api/warehouse/return-to-supplier", headers=thukho_h,
                    json={"lot_id": lot_id, "quantity": 10, "reason": "Hàng hỏng"})
    assert r.status_code == 200, r.text
    assert r.json()["on_hand"] == 30

    hist = client.get("/api/warehouse/movements?movement_type=issue&mode=tra_ncc", headers=thukho_h).json()
    assert any(m["lot_id"] == lot_id and m["quantity"] == 10 for m in hist)


def test_free_issue_undo_flow(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "FREE-UNDO")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "LOT-FREE-UNDO", "material_id": mat_id, "quantity": 60, "uom": "kg"})
    lot_id = rc.json()["lot_id"]

    issue = client.post("/api/warehouse/issue", headers=admin_h,
                        json={"lot_id": lot_id, "quantity": 20, "mode": "tu_do", "reason": "Thử nghiệm"})
    assert issue.status_code == 200, issue.text
    movement_id = issue.json()["movement_id"]

    lots = client.get("/api/lots", headers=thukho_h).json()
    assert next(l for l in lots if l["lot_id"] == lot_id)["quantity"] == 40

    undo = client.post(f"/api/warehouse/movements/{movement_id}/undo-issue", headers=thukho_h)
    assert undo.status_code == 200, undo.text

    lots2 = client.get("/api/lots", headers=thukho_h).json()
    assert next(l for l in lots2 if l["lot_id"] == lot_id)["quantity"] == 60

    # Hoàn 2 lần cùng 1 giao dịch → bị chặn.
    undo_again = client.post(f"/api/warehouse/movements/{movement_id}/undo-issue", headers=thukho_h)
    assert undo_again.status_code == 409, undo_again.text


def test_free_issue_admin_only(client, admin_h, thukho_h):
    """Xuất tự do (mode=tu_do) chỉ dành cho admin — thủ kho (dù có quyền warehouse.issue)
    không được thực hiện, phải qua đề nghị nhận kho (Kho công ty) hoặc admin thao tác hộ."""
    mat_id = _create_material(client, admin_h, "FREE-ADMIN-ONLY")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "LOT-FREE-ADMIN-ONLY", "material_id": mat_id, "quantity": 30, "uom": "kg"})
    lot_id = rc.json()["lot_id"]
    r = client.post("/api/warehouse/issue", headers=thukho_h,
                    json={"lot_id": lot_id, "quantity": 5, "mode": "tu_do"})
    assert r.status_code == 403, r.text


def test_free_issue_workshop_location_tracked(client, admin_h, thukho_h):
    """Xuất tự do có thể thực hiện từ lô đang ở kho phân xưởng (không chỉ kho công ty) — FE tách
    lịch sử theo location_from nên movement phải ghi đúng vị trí thực tế của lô lúc xuất."""
    mat_id = _create_material(client, admin_h, "FREE-PX")
    rc = client.post("/api/warehouse/receive", headers=admin_h,
                     json={"lot_code": "LOT-FREE-PX", "material_id": mat_id, "quantity": 40, "uom": "kg",
                           "location": "Kho phân xưởng"})
    lot_id = rc.json()["lot_id"]

    issue = client.post("/api/warehouse/issue", headers=admin_h,
                        json={"lot_id": lot_id, "quantity": 15, "mode": "tu_do", "reason": "Thử nghiệm"})
    assert issue.status_code == 200, issue.text

    hist = client.get("/api/warehouse/movements?movement_type=issue&mode=tu_do", headers=thukho_h).json()
    m = next(m for m in hist if m["lot_id"] == lot_id)
    assert m["location_from"] == "Kho phân xưởng"


def test_undo_issue_blocked_for_return_to_supplier(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "NCC-UNDO-BLOCK")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "LOT-NCC-UNDO-BLOCK", "material_id": mat_id, "quantity": 30, "uom": "kg"})
    lot_id = rc.json()["lot_id"]
    ret = client.post("/api/warehouse/return-to-supplier", headers=thukho_h,
                      json={"lot_id": lot_id, "quantity": 10, "reason": "Hỏng"})
    movement_id = ret.json()["movement_id"]

    undo = client.post(f"/api/warehouse/movements/{movement_id}/undo-issue", headers=thukho_h)
    assert undo.status_code == 409, undo.text


def test_list_movements_filters_by_type_and_mode(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "MV-FILTER")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "LOT-MV-FILTER", "material_id": mat_id, "quantity": 25, "uom": "kg"})
    lot_id = rc.json()["lot_id"]
    client.post("/api/warehouse/issue", headers=admin_h,
               json={"lot_id": lot_id, "quantity": 5, "mode": "tu_do"})

    all_issue = client.get("/api/warehouse/movements?movement_type=issue", headers=thukho_h).json()
    assert any(m["lot_id"] == lot_id for m in all_issue)
    tu_do_only = client.get("/api/warehouse/movements?movement_type=issue&mode=tu_do", headers=thukho_h).json()
    assert any(m["lot_id"] == lot_id for m in tu_do_only)
    receipts_only = client.get("/api/warehouse/movements?movement_type=receipt", headers=thukho_h).json()
    assert not any(m["lot_id"] == lot_id and m["movement_type"] != "receipt" for m in receipts_only)
