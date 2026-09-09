"""Test cổng khai báo/duyệt chỉ tiêu chất lượng NVL + đề nghị nhận kho.

Phủ: gate on_hold khi nhận lô của nguyên liệu có gán nhóm chỉ tiêu bắt buộc,
hành vi không đổi khi không gán nhóm, chặn release khi thiếu khai báo,
chặn transfer khi đang on_hold, permission quality.release, và luồng đề nghị
nhận kho (tạo/duyệt/từ chối, chặn khi lô on_hold) + lọc báo cáo theo kho.
"""

import os
import tempfile
from datetime import datetime, timedelta, timezone

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
from app.models.materials import GenealogyEdge, MaterialLot


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


def test_release_lot_allowed_even_with_fail_result(client, admin_h, thukho_h, kcs_h):
    """Tạm thời (2026-08-01): duyệt lô NVL không bị chặn bởi chỉ tiêu FAIL — màn hình Kho
    NVL chưa có luồng mở/đóng deviation cho lô, nên vẫn giữ đúng yêu cầu "khai báo đủ chỉ
    tiêu bắt buộc" nhưng bỏ điều kiện phải hết FAIL (mirror test_receive_with_mandatory_group_
    holds_then_release_flow, khác ở chỗ khai giá trị NGOÀI khoảng min/max)."""
    mat_id = _create_material(client, admin_h, "QCT-MALTFAIL")
    p = client.post("/api/qc/parameters", headers=admin_h,
                    json={"code": "DO_AM_FAIL_TEST", "name": "Độ ẩm", "unit": "%", "lsl": 3, "usl": 6})
    param_id = p.json()["param_id"]
    g = client.post("/api/qc/groups", headers=admin_h,
                    json={"code": "GRP-MALTFAIL-TEST", "name": "Chỉ tiêu Malt fail test"})
    group_id = g.json()["group_id"]
    client.post(f"/api/qc/groups/{group_id}/items", headers=admin_h,
               json={"param_id": param_id, "mandatory": True})
    client.post(f"/api/materials/{mat_id}/qc-groups", headers=admin_h,
               json={"group_id": group_id, "mandatory": True})

    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "LOT-MALTFAIL-01", "material_id": mat_id, "quantity": 500, "uom": "kg"})
    lot_id = rc.json()["lot_id"]

    # Khai báo giá trị NGOÀI khoảng min/max → status "fail".
    rec = client.post("/api/quality/results", headers=thukho_h,
                      json={"scope_type": "lot", "scope_id": lot_id, "parameter": "DO_AM_FAIL_TEST",
                            "value": 20, "lower_limit": 3, "upper_limit": 6})
    assert rec.status_code == 201, rec.text
    assert rec.json()["status"] == "fail"

    # Đã khai báo đủ chỉ tiêu bắt buộc (dù fail) → KCS vẫn duyệt được, không bị chặn bởi
    # yêu cầu deviation CLOSED.
    rel_ok = client.post("/api/quality/hold", headers=kcs_h,
                         json={"scope_type": "lot", "scope_id": lot_id, "on_hold": False})
    assert rel_ok.status_code == 200, rel_ok.text
    assert rel_ok.json()["quality_status"] == "released"


def test_delete_receipt_row_blocked_by_qc_or_usage(client, admin_h, thukho_h):
    """Nút "Xóa" từng dòng trong lịch sử Nhập kho (DELETE /warehouse/movements/{id}) — chỉ
    xóa được khi lô CHƯA có chỉ tiêu chất lượng nào khai báo (QualityResult) VÀ chưa bị dùng
    (xuất/chuyển). Khác với "Xóa lịch sử" (bulk), nút này thật sự hủy lô nếu đủ điều kiện."""
    mat_id = _create_material(client, admin_h, "DELRC-QC")

    # Case 1: chưa khai báo QC, chưa dùng -> xóa OK, lô bị xóa luôn (lượt receipt duy nhất).
    rc1 = client.post("/api/warehouse/receive", headers=thukho_h,
                      json={"lot_code": "LOT-DELRC-01", "material_id": mat_id, "quantity": 100, "uom": "kg"})
    assert rc1.status_code == 200, rc1.text
    lot1 = rc1.json()["lot_id"]
    mv1 = next(m for m in client.get("/api/warehouse/movements?movement_type=receipt",
                                     headers=thukho_h).json() if m["lot_id"] == lot1)
    del1 = client.delete(f"/api/warehouse/movements/{mv1['movement_id']}", headers=thukho_h)
    assert del1.status_code == 200, del1.text
    assert del1.json()["lot_deleted"] is True

    # Case 2: đã khai báo 1 chỉ tiêu (dù chưa duyệt, dù chưa dùng) -> chặn xóa.
    rc2 = client.post("/api/warehouse/receive", headers=thukho_h,
                      json={"lot_code": "LOT-DELRC-02", "material_id": mat_id, "quantity": 100, "uom": "kg"})
    lot2 = rc2.json()["lot_id"]
    rec = client.post("/api/quality/results", headers=thukho_h,
                      json={"scope_type": "lot", "scope_id": lot2, "parameter": "ANY_PARAM", "value": 1})
    assert rec.status_code == 201, rec.text
    mv2 = next(m for m in client.get("/api/warehouse/movements?movement_type=receipt",
                                     headers=thukho_h).json() if m["lot_id"] == lot2)
    del2 = client.delete(f"/api/warehouse/movements/{mv2['movement_id']}", headers=thukho_h)
    assert del2.status_code == 409, del2.text

    # Case 3: chưa khai báo QC nhưng đã dùng (transfer) -> vẫn chặn xóa như trước.
    rc3 = client.post("/api/warehouse/receive", headers=thukho_h,
                      json={"lot_code": "LOT-DELRC-03", "material_id": mat_id, "quantity": 100, "uom": "kg"})
    lot3 = rc3.json()["lot_id"]
    xfer = client.post("/api/warehouse/transfer", headers=thukho_h,
                       json={"lot_id": lot3, "quantity": 100, "location_to": "Kho phân xưởng"})
    assert xfer.status_code == 200, xfer.text
    mv3 = next(m for m in client.get("/api/warehouse/movements?movement_type=receipt",
                                     headers=thukho_h).json() if m["lot_id"] == lot3)
    del3 = client.delete(f"/api/warehouse/movements/{mv3['movement_id']}", headers=thukho_h)
    assert del3.status_code == 409, del3.text


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

    # Dòng B vẫn đang pending, độc lập với dòng A đã fulfilled.
    after_a = next(r for r in client.get("/api/warehouse/requests", headers=thukho_h).json()
                   if r["request_id"] == request_id)
    statuses = {l["line_id"]: l["status"] for l in after_a["lines"]}
    assert statuses[line_a["line_id"]] == "fulfilled"
    assert statuses[line_b["line_id"]] == "pending"

    # Xuất 50/200 (một phần) — transfer() tách lô mới mang đúng 50 sang Kho phân xưởng, lô gốc
    # còn lại 150 vẫn ở Kho công ty (xem services/warehouse.py::transfer split-lot).
    fulfilled_lot_id = next(l for l in after_a["lines"] if l["line_id"] == line_a["line_id"])["fulfilled_lot_id"]
    assert fulfilled_lot_id != lot_a
    lot_after = client.get("/api/lots", headers=thukho_h).json()
    fulfilled_lot = next(l for l in lot_after if l["lot_id"] == fulfilled_lot_id)
    assert fulfilled_lot["location"] == "Kho phân xưởng"
    assert fulfilled_lot["quantity"] == 50
    original_lot = next(l for l in lot_after if l["lot_id"] == lot_a)
    assert original_lot["location"] == "Kho công ty"
    assert original_lot["quantity"] == 150

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

    # Tồn "đủ để tạo phiếu" giờ loại trừ lô đang HOLD (xem services/warehouse.py::stock_on_hand)
    # — lô duy nhất đang hold nên phiếu bị chặn ngay từ lúc TẠO, không cần đợi tới lúc duyệt.
    req = client.post("/api/warehouse/requests", headers=vanhanh_h,
                      json={"lines": [{"material_id": mat_id, "quantity": 10}]})
    assert req.status_code == 409, req.text


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


def test_inventory_report_tracks_first_last_movement_dates(client, admin_h, thukho_h):
    """services/warehouse.py::inventory_report/lot_inventory_report — BC nhập-xuất-tồn phải kèm
    mốc ngày nhập/xuất đầu-cuối trong kỳ (yêu cầu người dùng 2026-09-06: "thiếu ngày tháng nhập,
    xuất" — trước đây chỉ cộng dồn số lượng cả kỳ, không biết giao dịch xảy ra khoảng nào)."""
    mat_id = _create_material(client, admin_h, "REP-DATE")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "LOT-REP-DATE-01", "material_id": mat_id, "quantity": 100, "uom": "kg"})
    assert rc.status_code == 200, rc.text
    lot_id = rc.json()["lot_id"]
    issue = client.post("/api/warehouse/issue", headers=admin_h,
                       json={"lot_id": lot_id, "quantity": 30, "mode": "tu_do", "reason": "Thử nghiệm"})
    assert issue.status_code == 200, issue.text

    rep = client.get("/api/warehouse/report?days=1", headers=thukho_h).json()
    row = next(r for r in rep if r["material_id"] == mat_id)
    assert row["receipt_first"] is not None and row["receipt_last"] is not None
    assert row["issue_first"] is not None and row["issue_last"] is not None

    rep_lot = client.get("/api/warehouse/report/by-lot?days=1", headers=thukho_h).json()
    row_lot = next(r for r in rep_lot if r["lot_id"] == lot_id)
    assert row_lot["receipt_first"] is not None and row_lot["receipt_last"] is not None
    assert row_lot["issue_first"] is not None and row_lot["issue_last"] is not None

    # Vật tư chưa từng xuất (chỉ mới nhập) — issue_first/issue_last phải là None, không phải 0
    # hay ngày giả nào khác.
    mat_id2 = _create_material(client, admin_h, "REP-DATE-2")
    client.post("/api/warehouse/receive", headers=thukho_h,
               json={"lot_code": "LOT-REP-DATE-02", "material_id": mat_id2, "quantity": 50, "uom": "kg"})
    rep2 = client.get("/api/warehouse/report?days=1", headers=thukho_h).json()
    row2 = next(r for r in rep2 if r["material_id"] == mat_id2)
    assert row2["receipt_first"] is not None
    assert row2["issue_first"] is None and row2["issue_last"] is None


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

    # Xuất 1 phần (30/90, 15/40) — transfer() tách lô mới cho đúng phần đã fulfilled, lô gốc
    # (LOT-REQALL-A/B) vẫn ở Kho công ty với phần dư (xem services/warehouse.py::transfer).
    lots = client.get("/api/lots", headers=thukho_h).json()
    for line in after["lines"]:
        fulfilled_lot = next(l for l in lots if l["lot_id"] == line["fulfilled_lot_id"])
        assert fulfilled_lot["location"] == "Kho phân xưởng"


def test_material_request_fulfill_all_skips_on_hold_line(client, admin_h, thukho_h, vanhanh_h, kcs_h):
    mat_ok = _create_material(client, admin_h, "REQALL-OK")
    mat_hold = _create_material(client, admin_h, "REQALL-HOLD")
    client.post("/api/warehouse/receive", headers=thukho_h,
               json={"lot_code": "LOT-REQALL-OK", "material_id": mat_ok, "quantity": 50, "uom": "kg"})
    # Nhận kho TRƯỚC khi gán nhóm chỉ tiêu bắt buộc — lô available ngay (không hold), đủ tồn để
    # TẠO phiếu (xem stock_on_hand loại trừ HOLD, task #805) — hold được áp dụng SAU đó để test
    # đúng nhánh "fulfill-all bỏ qua dòng đang hold", tách biệt khỏi check tồn lúc tạo phiếu.
    rc_hold = client.post("/api/warehouse/receive", headers=thukho_h,
                          json={"lot_code": "LOT-REQALL-HOLD", "material_id": mat_hold, "quantity": 20, "uom": "kg"})
    lot_hold_id = rc_hold.json()["lot_id"]

    req = client.post("/api/warehouse/requests", headers=vanhanh_h,
                      json={"lines": [
                          {"material_id": mat_ok, "quantity": 10, "uom": "kg"},
                          {"material_id": mat_hold, "quantity": 5, "uom": "kg"},
                      ]})
    assert req.status_code == 201, req.text
    request_id = req.json()["request_id"]

    hold_it = client.post("/api/quality/hold", headers=kcs_h,
                          json={"scope_type": "lot", "scope_id": lot_hold_id, "on_hold": True})
    assert hold_it.status_code == 200, hold_it.text

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
    # Xuất 20/50 (một phần) — transfer() tách lô mới mang đúng 20 sang Kho phân xưởng, lô gốc
    # còn lại 30 vẫn ở Kho công ty (xem services/warehouse.py::transfer split-lot).
    fulfilled_lot_id = next(l for l in client.get("/api/warehouse/requests", headers=thukho_h).json()
                           if l["request_id"] == request_id)["lines"][0]["fulfilled_lot_id"]
    assert fulfilled_lot_id != lot_id

    undo = client.post(f"/api/warehouse/requests/{request_id}/lines/{line_id}/undo-fulfill", headers=thukho_h)
    assert undo.status_code == 200, undo.text
    assert undo.json()["status"] == "pending"

    # Hoàn tác trả lô tách (20) về lại Kho công ty — KHÔNG gộp ngược vào lô gốc (transfer()
    # không tự gộp lô), nên giờ có 2 lô riêng cùng ở Kho công ty, tổng vẫn đúng 50.
    lots = client.get("/api/lots", headers=thukho_h).json()
    original_lot = next(l for l in lots if l["lot_id"] == lot_id)
    returned_lot = next(l for l in lots if l["lot_id"] == fulfilled_lot_id)
    assert original_lot["location"] == "Kho công ty"
    assert returned_lot["location"] == "Kho công ty"
    assert original_lot["quantity"] + returned_lot["quantity"] == 50


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
    # Lô THẬT đã fulfilled là lô tách (xuất 1 phần 20/50), không phải lot_id gốc — xem
    # services/warehouse.py::transfer split-lot + fulfill_request_line lưu result["lot_id"].
    fulfilled_lot_id = next(l for l in client.get("/api/warehouse/requests", headers=thukho_h).json()
                           if l["request_id"] == request_id)["lines"][0]["fulfilled_lot_id"]

    # Giả lập lô đã được dùng cho mẻ sản xuất (genealogy consume edge) — tái dùng bảng
    # có sẵn thay vì dựng toàn bộ pipeline work-order/recipe/batch chỉ để test cờ chặn.
    db = SessionLocal()
    try:
        db.add(GenealogyEdge(from_type="lot", from_id=fulfilled_lot_id, to_type="batch", to_id="fake-batch",
                             relation="consume", quantity=20, uom="kg"))
        db.commit()
    finally:
        db.close()

    undo = client.post(f"/api/warehouse/requests/{request_id}/lines/{line_id}/undo-fulfill", headers=thukho_h)
    assert undo.status_code == 409, undo.text


def test_transfer_px_request_blocked_when_not_at_workshop(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "DC-BLOCK")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "LOT-DC-BLOCK", "material_id": mat_id, "quantity": 30, "uom": "kg"})
    lot_id = rc.json()["lot_id"]
    r = client.post("/api/warehouse/transfer-px-requests", headers=vanhanh_h,
                    json={"lot_id": lot_id, "quantity": 30})
    assert r.status_code == 409, r.text


def test_transfer_px_request_approve_ok(client, admin_h, thukho_h, vanhanh_h):
    mat_id = _create_material(client, admin_h, "DC-OK")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "LOT-DC-OK", "material_id": mat_id, "quantity": 30, "uom": "kg"})
    lot_id = rc.json()["lot_id"]
    client.post("/api/warehouse/transfer", headers=thukho_h,
               json={"lot_id": lot_id, "quantity": 30, "location_to": "Kho phân xưởng"})

    req = client.post("/api/warehouse/transfer-px-requests", headers=vanhanh_h,
                      json={"lot_id": lot_id, "quantity": 30, "reason": "Nhận thừa"})
    assert req.status_code == 201, req.text
    request_id = req.json()["request_id"]
    assert req.json()["status"] == "pending"

    # thủ kho công ty duyệt — lúc này mới thật sự chuyển kho
    r = client.post(f"/api/warehouse/transfer-px-requests/{request_id}/approve", headers=thukho_h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"

    hist = client.get("/api/warehouse/movements?movement_type=transfer&mode=dieu_chuyen", headers=thukho_h).json()
    assert any(m["lot_id"] == lot_id for m in hist)

    # sau khi duyệt, chỉ ADMIN mới hoàn tác được
    undo_denied = client.post(f"/api/warehouse/transfer-px-requests/{request_id}/undo", headers=thukho_h)
    assert undo_denied.status_code == 403, undo_denied.text
    undo = client.post(f"/api/warehouse/transfer-px-requests/{request_id}/undo", headers=admin_h)
    assert undo.status_code == 200, undo.text
    assert undo.json()["reversed"] is True


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


def test_free_issue_issued_at_backdates_ts_but_created_at_stays_now(client, admin_h, thukho_h):
    """"Ngày xuất tự do" (issued_at) chỉ khai lùi `ts` (ngày hiệu lực) — `created_at` (ngày tạo
    phiếu thật) vẫn luôn là thời điểm gọi API, không đổi theo issued_at."""
    mat_id = _create_material(client, admin_h, "FREE-ISSUED-AT")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "LOT-FREE-ISSUED-AT", "material_id": mat_id, "quantity": 50, "uom": "kg"})
    lot_id = rc.json()["lot_id"]

    backdated = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    before_call = datetime.now(timezone.utc)
    issue = client.post("/api/warehouse/issue", headers=admin_h,
                        json={"lot_id": lot_id, "quantity": 10, "mode": "tu_do", "reason": "Thử nghiệm",
                              "issued_at": backdated})
    assert issue.status_code == 200, issue.text

    hist = client.get("/api/warehouse/movements?movement_type=issue&mode=tu_do", headers=thukho_h).json()
    m = next(m for m in hist if m["lot_id"] == lot_id)
    ts = datetime.fromisoformat(m["ts"].replace("Z", "+00:00"))
    created_at = datetime.fromisoformat(m["created_at"].replace("Z", "+00:00"))
    assert ts < before_call - timedelta(days=29)
    assert created_at >= before_call - timedelta(seconds=5)


def test_free_issue_issued_at_cannot_be_future(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "FREE-ISSUED-FUTURE")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "LOT-FREE-ISSUED-FUTURE", "material_id": mat_id, "quantity": 20, "uom": "kg"})
    lot_id = rc.json()["lot_id"]
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    r = client.post("/api/warehouse/issue", headers=admin_h,
                    json={"lot_id": lot_id, "quantity": 5, "mode": "tu_do", "issued_at": future})
    assert r.status_code == 409, r.text


def test_movements_filter_is_opening_balance(client, admin_h, thukho_h):
    """GET /warehouse/movements?is_opening_balance=true chỉ trả các lượt "Nhập tồn đầu" (nhận
    diện qua `reason` bắt đầu bằng "Nhập tồn đầu"), bỏ qua Nhập kho thường."""
    mat_id = _create_material(client, admin_h, "OB-FILTER")
    rc_normal = client.post("/api/warehouse/receive", headers=thukho_h,
                            json={"lot_code": "LOT-OB-FILTER-NORMAL", "material_id": mat_id, "quantity": 10,
                                  "uom": "kg", "reason": "Nhập kho"})
    rc_ob = client.post("/api/warehouse/receive", headers=admin_h,
                        json={"lot_code": "LOT-OB-FILTER-OB", "material_id": mat_id, "quantity": 20, "uom": "kg",
                              "reason": "Nhập tồn đầu", "is_opening_balance": True})
    assert rc_normal.status_code == 200 and rc_ob.status_code == 200

    hist = client.get("/api/warehouse/movements?movement_type=receipt&is_opening_balance=true",
                      headers=thukho_h).json()
    lot_ids = {m["lot_id"] for m in hist}
    assert rc_ob.json()["lot_id"] in lot_ids
    assert rc_normal.json()["lot_id"] not in lot_ids


def test_stock_as_of_reflects_balance_before_and_after_issue(client, admin_h, thukho_h):
    """GET /warehouse/stock/as-of dựng lại tồn kho tính đến 1 ngày trong quá khứ từ lịch sử
    StockMovement (yêu cầu người dùng 2026-09-08: "xem ngày đó còn tồn bao nhiêu") — khác /stock
    (đọc thẳng MaterialLot.quantity hiện tại, không lùi được quá khứ)."""
    mat_id = _create_material(client, admin_h, "ASOF-BASIC")
    day1 = (datetime.now(timezone.utc) - timedelta(days=10))
    day2 = (datetime.now(timezone.utc) - timedelta(days=5))
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "LOT-ASOF-BASIC", "material_id": mat_id, "quantity": 100, "uom": "kg",
                           "received_at": day1.isoformat()})
    lot_id = rc.json()["lot_id"]
    issue = client.post("/api/warehouse/issue", headers=admin_h,
                        json={"lot_id": lot_id, "quantity": 30, "mode": "tu_do", "issued_at": day2.isoformat()})
    assert issue.status_code == 200, issue.text

    before_receipt = (day1 - timedelta(days=1)).isoformat()
    r0 = client.get("/api/warehouse/stock/as-of", params={"as_of": before_receipt}, headers=thukho_h).json()
    assert not any(r["material_id"] == mat_id for r in r0)

    between = (day1 + timedelta(hours=1)).isoformat()
    r1 = client.get("/api/warehouse/stock/as-of", params={"as_of": between}, headers=thukho_h).json()
    row1 = next(r for r in r1 if r["material_id"] == mat_id)
    assert row1["on_hand"] == 100
    assert row1["material_code"] == "ASOF-BASIC"

    after_issue = (day2 + timedelta(hours=1)).isoformat()
    r2 = client.get("/api/warehouse/stock/as-of", params={"as_of": after_issue}, headers=thukho_h).json()
    row2 = next(r for r in r2 if r["material_id"] == mat_id)
    assert row2["on_hand"] == 70

    now_iso = datetime.now(timezone.utc).isoformat()
    r3 = client.get("/api/warehouse/stock/as-of", params={"as_of": now_iso}, headers=thukho_h).json()
    row3 = next(r for r in r3 if r["material_id"] == mat_id)
    assert row3["on_hand"] == 70


def test_stock_as_of_transfer_splits_by_location_but_nets_zero_overall(client, admin_h, thukho_h):
    """transfer() không đổi TỔNG công ty (chỉ đổi vị trí) — lọc theo "Kho công ty"/"Kho phân
    xưởng" phải phản ánh đúng vị trí tại thời điểm đó, nhưng lọc "Tất cả" (không truyền location)
    phải ra đúng tổng ban đầu, không bị giảm/tăng do transfer."""
    mat_id = _create_material(client, admin_h, "ASOF-TRANSFER")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "LOT-ASOF-TRANSFER", "material_id": mat_id, "quantity": 50, "uom": "kg"})
    lot_id = rc.json()["lot_id"]
    tr = client.post("/api/warehouse/transfer", headers=admin_h,
                     json={"lot_id": lot_id, "quantity": 20, "location_to": "Kho phân xưởng"})
    assert tr.status_code == 200, tr.text

    now_iso = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    r_all = client.get("/api/warehouse/stock/as-of", params={"as_of": now_iso}, headers=thukho_h).json()
    assert next(r for r in r_all if r["material_id"] == mat_id)["on_hand"] == 50

    r_kc = client.get("/api/warehouse/stock/as-of", params={"as_of": now_iso, "location": "Kho công ty"},
                      headers=thukho_h).json()
    assert next(r for r in r_kc if r["material_id"] == mat_id)["on_hand"] == 30

    r_px = client.get("/api/warehouse/stock/as-of", params={"as_of": now_iso, "location": "Kho phân xưởng"},
                      headers=thukho_h).json()
    assert next(r for r in r_px if r["material_id"] == mat_id)["on_hand"] == 20


def test_lot_on_hand_as_of_original_lot_reflects_partial_transfer_split(client, admin_h, thukho_h):
    """Lô GỐC sau khi bị transfer() TÁCH MỘT PHẦN (quantity < tồn lô gốc) không có StockMovement
    riêng ghi nhận phần đã giảm (chỉ lô MỚI có) — lot_on_hand_as_of phải bù đúng qua GenealogyEdge
    (relation=split), không được hiện lô gốc như CHƯA hề giảm (bug đã phát hiện & sửa 2026-09-08)."""
    mat_id = _create_material(client, admin_h, "ASOF-SPLIT-LOT")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "LOT-ASOF-SPLIT", "material_id": mat_id, "quantity": 50, "uom": "kg"})
    original_lot_id = rc.json()["lot_id"]
    tr = client.post("/api/warehouse/transfer", headers=admin_h,
                     json={"lot_id": original_lot_id, "quantity": 20, "location_to": "Kho phân xưởng"})
    assert tr.status_code == 200, tr.text

    now_iso = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    rows = client.get("/api/warehouse/stock/as-of/lots", params={"as_of": now_iso}, headers=thukho_h).json()
    original_row = next(r for r in rows if r["lot_id"] == original_lot_id)
    assert original_row["quantity"] == 30   # 50 - 20 tách sang phân xưởng, KHÔNG phải 50
    moved_row = next(r for r in rows if r["lot_id"] != original_lot_id and r["material_id"] == mat_id)
    assert moved_row["quantity"] == 20

    rows_kc = client.get("/api/warehouse/stock/as-of/lots", params={"as_of": now_iso, "location": "Kho công ty"},
                         headers=thukho_h).json()
    kc_lot_ids = {r["lot_id"] for r in rows_kc}
    assert original_lot_id in kc_lot_ids
    assert moved_row["lot_id"] not in kc_lot_ids

    rows_px = client.get("/api/warehouse/stock/as-of/lots", params={"as_of": now_iso, "location": "Kho phân xưởng"},
                         headers=thukho_h).json()
    px_lot_ids = {r["lot_id"] for r in rows_px}
    assert moved_row["lot_id"] in px_lot_ids
    assert original_lot_id not in px_lot_ids


def test_lot_on_hand_as_of_lists_matching_lots(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "ASOF-LOTLIST")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "LOT-ASOF-LOTLIST", "material_id": mat_id, "quantity": 40, "uom": "kg"})
    lot_id = rc.json()["lot_id"]
    now_iso = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    rows = client.get("/api/warehouse/stock/as-of/lots", params={"as_of": now_iso}, headers=thukho_h).json()
    row = next(r for r in rows if r["lot_id"] == lot_id)
    assert row["quantity"] == 40
    assert row["lot_code"] == "LOT-ASOF-LOTLIST"


def test_stock_as_of_includes_lots_with_no_stock_movement_history(client, admin_h, thukho_h):
    """Lô nạp thẳng vào DB (VD di chuyển dữ liệu từ hệ thống cũ) không có StockMovement nào —
    stock_on_hand_as_of/lot_on_hand_as_of phải lấy MaterialLot.quantity/created_at hiện tại làm
    phương án dự phòng, không được trả về trống (bug phát hiện & sửa 2026-09-08, người dùng báo
    "chỉ 1 ngày thì lại mất, từ ngày đến ngày lại hiện ra" cho dữ liệu kho công ty có sẵn)."""
    mat_id = _create_material(client, admin_h, "ASOF-NOMOVEMENT")
    old_created = datetime(2026, 6, 1, 8, 0, 0, tzinfo=timezone.utc)
    db = SessionLocal()
    try:
        lot = MaterialLot(lot_code="LOT-NOMOVEMENT", lot_year=2026, material_id=mat_id, lot_type="material",
                          quantity=75, uom="kg", location="Kho công ty", created_at=old_created)
        db.add(lot)
        db.commit()
        lot_id = lot.lot_id
    finally:
        db.close()

    before_creation = datetime(2026, 5, 1, tzinfo=timezone.utc).isoformat()
    r0 = client.get("/api/warehouse/stock/as-of", params={"as_of": before_creation}, headers=thukho_h).json()
    assert not any(r["material_id"] == mat_id for r in r0)

    now_iso = datetime.now(timezone.utc).isoformat()
    r1 = client.get("/api/warehouse/stock/as-of", params={"as_of": now_iso}, headers=thukho_h).json()
    row1 = next(r for r in r1 if r["material_id"] == mat_id)
    assert row1["on_hand"] == 75

    r2 = client.get("/api/warehouse/stock/as-of", params={"as_of": now_iso, "location": "Kho công ty"},
                    headers=thukho_h).json()
    assert next(r for r in r2 if r["material_id"] == mat_id)["on_hand"] == 75

    lots = client.get("/api/warehouse/stock/as-of/lots", params={"as_of": now_iso}, headers=thukho_h).json()
    lot_row = next(r for r in lots if r["lot_id"] == lot_id)
    assert lot_row["quantity"] == 75
    assert lot_row["location"] == "Kho công ty"


def test_qc_required_params_only_excludes_raw_material_without_group(client, admin_h, thukho_h):
    """GET /materials/qc-required?params_only=true chỉ trả material_id có >=1 chỉ tiêu THẬT SỰ
    gán — khác với ?params_only mặc định (false) vốn CŨNG gồm Nguyên liệu chính/phụ chỉ cần Số
    lô KCS/Số LOT NCC (is_raw_material) dù chưa gán chỉ tiêu nào. Dùng để ẩn nút "Xem chỉ tiêu" ở
    "Danh sách lô (FIFO)" cho các lô chỉ cần Số lô KCS/Số LOT NCC (yêu cầu người dùng 2026-09-08)."""
    grp = client.post("/api/material-groups", headers=admin_h,
                      json={"code": "GRP-RAWONLY-TEST", "name": "Nhóm NVL chính test", "is_raw_material": True})
    assert grp.status_code == 201, grp.text

    mat_raw_only = client.post("/api/materials", headers=admin_h,
                               json={"code": "QCT-RAWONLY", "name": "NVL chỉ cần Số lô KCS", "uom": "kg",
                                     "category": "GRP-RAWONLY-TEST"}).json()["material_id"]

    mat_with_param = _create_material(client, admin_h, "QCT-REALPARAM")
    p = client.post("/api/qc/parameters", headers=admin_h,
                    json={"code": "REALPARAM_TEST", "name": "Độ ẩm", "unit": "%", "lsl": 3, "usl": 6})
    param_id = p.json()["param_id"]
    g = client.post("/api/qc/groups", headers=admin_h,
                    json={"code": "GRP-REALPARAM-TEST", "name": "Chỉ tiêu thật test"})
    group_id = g.json()["group_id"]
    client.post(f"/api/qc/groups/{group_id}/items", headers=admin_h,
               json={"param_id": param_id, "mandatory": True})
    client.post(f"/api/materials/{mat_with_param}/qc-groups", headers=admin_h,
               json={"group_id": group_id, "mandatory": True})

    all_required = client.get("/api/materials/qc-required", headers=thukho_h).json()
    assert mat_raw_only in all_required
    assert mat_with_param in all_required

    params_only = client.get("/api/materials/qc-required", params={"params_only": "true"}, headers=thukho_h).json()
    assert mat_raw_only not in params_only
    assert mat_with_param in params_only


def test_sang_ngang_received_at_backdated_distinct_from_created_at(client, admin_h, thukho_h):
    """"Xuất sang ngang" thêm ô "Ngày xuất sang ngang" — gửi received_at (đã hỗ trợ sẵn qua
    ReceiptIn/receive(), không cần đổi backend) phải phản ánh đúng vào StockMovement receipt gốc,
    tách biệt với "Ngày lập phiếu" (created_at, luôn là lúc submit form thật) — yêu cầu người
    dùng 2026-09-08."""
    mat_id = _create_material(client, admin_h, "SNG-DATE-TEST")
    backdated = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    before_call = datetime.now(timezone.utc)
    r = client.post("/api/warehouse/sang-ngang", headers=thukho_h,
                    json={"lot_code": "LOT-SNG-DATE", "material_id": mat_id, "quantity": 30, "uom": "kg",
                          "received_at": backdated})
    assert r.status_code == 201, r.text
    data = r.json()
    received_at = datetime.fromisoformat(data["received_at"].replace("Z", "+00:00"))
    created_at = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
    assert received_at < before_call - timedelta(days=4)
    assert created_at >= before_call - timedelta(seconds=5)

    listed = client.get("/api/warehouse/sang-ngang", headers=thukho_h).json()
    row = next(x for x in listed if x["request_id"] == data["request_id"])
    assert row["received_at"] == data["received_at"]


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


def test_copy_qc_group_items(client, admin_h):
    p1 = client.post("/api/qc/parameters", headers=admin_h,
                     json={"code": "COPY_P1", "name": "Chỉ tiêu 1", "unit": "%"})
    p2 = client.post("/api/qc/parameters", headers=admin_h,
                     json={"code": "COPY_P2", "name": "Chỉ tiêu 2", "unit": "%"})
    p1_id, p2_id = p1.json()["param_id"], p2.json()["param_id"]

    src = client.post("/api/qc/groups", headers=admin_h,
                      json={"code": "GRP-COPY-SRC", "name": "Nhóm nguồn"}).json()
    dst = client.post("/api/qc/groups", headers=admin_h,
                      json={"code": "GRP-COPY-DST", "name": "Nhóm đích"}).json()

    client.post(f"/api/qc/groups/{src['group_id']}/items", headers=admin_h,
               json={"param_id": p1_id, "mandatory": True, "lsl_override": 1, "usl_override": 5})
    client.post(f"/api/qc/groups/{src['group_id']}/items", headers=admin_h,
               json={"param_id": p2_id, "mandatory": False})

    # Nhóm đích đang rỗng -> copy thành công, giữ nguyên min/max/bắt buộc của nhóm nguồn.
    r = client.post(f"/api/qc/groups/{dst['group_id']}/items/copy", headers=admin_h,
                    json={"source_group_id": src["group_id"]})
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) == 2
    p1_item = next(it for it in items if it["param_id"] == p1_id)
    p2_item = next(it for it in items if it["param_id"] == p2_id)
    assert p1_item["usl_override"] == 5
    assert p2_item["mandatory"] is False
    assert p2_item["lsl_override"] is None

    # Nhóm đích giờ đã có chỉ tiêu -> copy lần nữa (kể cả từ nhóm khác) phải bị chặn.
    src2 = client.post("/api/qc/groups", headers=admin_h,
                       json={"code": "GRP-COPY-SRC2", "name": "Nhóm nguồn 2"}).json()
    blocked = client.post(f"/api/qc/groups/{dst['group_id']}/items/copy", headers=admin_h,
                          json={"source_group_id": src2["group_id"]})
    assert blocked.status_code == 409, blocked.text

    same = client.post(f"/api/qc/groups/{dst['group_id']}/items/copy", headers=admin_h,
                       json={"source_group_id": dst["group_id"]})
    assert same.status_code == 409, same.text


def test_opening_balance_receive_requires_admin(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "OB-NVL-TEST")

    denied = client.post("/api/warehouse/receive", headers=thukho_h,
                         json={"material_id": mat_id, "quantity": 100, "uom": "kg",
                               "location": "Kho công ty", "is_opening_balance": True})
    assert denied.status_code == 403, denied.text

    ok = client.post("/api/warehouse/receive", headers=admin_h,
                     json={"material_id": mat_id, "quantity": 100, "uom": "kg",
                           "location": "Kho phân xưởng", "is_opening_balance": True})
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "available"

    # Nhập kho thường (không đánh dấu tồn đầu) vẫn mở cho thủ kho như trước.
    normal = client.post("/api/warehouse/receive", headers=thukho_h,
                         json={"material_id": mat_id, "quantity": 50, "uom": "kg",
                               "location": "Kho công ty"})
    assert normal.status_code == 200, normal.text


def test_opening_balance_wms_build_units_requires_admin(client, admin_h, thukho_h):
    fp = client.post("/api/finished-products", headers=admin_h,
                     json={"code": "OB-FP-TEST", "name": "Test tồn đầu TP", "uom": "lon",
                           "unit_type": "vi", "pack_size": 24})
    assert fp.status_code == 201, fp.text
    fp_id = fp.json()["finished_product_id"]
    loc = client.post("/api/wms/locations", headers=admin_h,
                      json={"code": "OB-LOC-01", "name": "Vị trí tồn đầu test", "capacity": 1000})
    assert loc.status_code == 201, loc.text
    loc_id = loc.json()["loc_id"]

    denied = client.post("/api/wms/units", headers=thukho_h,
                         json={"finished_product_id": fp_id, "product_name": "OB-FP-TEST",
                               "lot_code": "OB-LOT-01", "total": 240, "pack_size": 24,
                               "unit_type": "vi", "is_opening_balance": True, "loc_id": loc_id})
    assert denied.status_code == 403, denied.text

    ok = client.post("/api/wms/units", headers=admin_h,
                     json={"finished_product_id": fp_id, "product_name": "OB-FP-TEST",
                           "lot_code": "OB-LOT-01", "total": 240, "pack_size": 24,
                           "unit_type": "vi", "is_opening_balance": True, "loc_id": loc_id})
    assert ok.status_code == 201, ok.text

    # Nhập kho thủ công thường (không đánh dấu tồn đầu) vẫn mở cho ai có quyền warehouse.receive.
    normal = client.post("/api/wms/units", headers=thukho_h,
                        json={"finished_product_id": fp_id, "product_name": "OB-FP-TEST",
                              "lot_code": "OB-LOT-02", "total": 48, "pack_size": 24, "unit_type": "vi",
                              "loc_id": loc_id})
    assert normal.status_code == 201, normal.text


def test_delete_qc_parameter_ok_when_unused(client, admin_h):
    p = client.post("/api/qc/parameters", headers=admin_h,
                    json={"code": "DELPARAM-UNUSED", "name": "Chỉ tiêu chưa gán", "unit": "%"})
    assert p.status_code == 201, p.text
    param_id = p.json()["param_id"]
    r = client.delete(f"/api/qc/parameters/{param_id}", headers=admin_h)
    assert r.status_code == 204, r.text
    assert not any(x["param_id"] == param_id for x in client.get("/api/qc/parameters?active_only=false", headers=admin_h).json())


def test_delete_qc_parameter_blocked_when_assigned_to_group(client, admin_h):
    p = client.post("/api/qc/parameters", headers=admin_h,
                    json={"code": "DELPARAM-USED", "name": "Chỉ tiêu đã gán", "unit": "%"})
    param_id = p.json()["param_id"]
    g = client.post("/api/qc/groups", headers=admin_h,
                    json={"code": "DELPARAM-GRP", "name": "Nhóm test xóa chỉ tiêu"})
    group_id = g.json()["group_id"]
    it = client.post(f"/api/qc/groups/{group_id}/items", headers=admin_h,
                     json={"param_id": param_id, "mandatory": True})
    assert it.status_code == 201, it.text

    r = client.delete(f"/api/qc/parameters/{param_id}", headers=admin_h)
    assert r.status_code == 409, r.text
