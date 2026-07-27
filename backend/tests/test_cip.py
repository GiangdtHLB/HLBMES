"""Test CIP (vệ sinh thiết bị) — khai báo/nghiệm thu bản ghi CIP, gợi ý theo thiết bị+khu vực
(suggest_for_scope, KHÔNG tự động gán), và gắn/hủy gắn TAY với mẻ/lô sản xuất. Xem
services/cip.py và models/cip.py cho thiết kế đầy đủ (steps JSON linh hoạt, permission
cip.manage cho khai báo, tái dùng quality.release cho nghiệm thu KCS)."""

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
def kcs_h(client):
    return _login(client, "kcs", "123456")


@pytest.fixture(scope="module")
def thukho_h(client):
    return _login(client, "thukho", "123456")


def _form_type(client, admin_h, code):
    types = client.get("/api/cip/form-types", headers=admin_h).json()
    return next(f for f in types if f["code"] == code)


def _equipment(client, admin_h, code):
    eq = client.get("/api/cip/equipment", headers=admin_h).json()
    return next(e for e in eq if e["code"] == code)


def _a_brew_order(client, admin_h, order_code):
    r = client.post("/api/brewing/orders", headers=admin_h,
                    json={"order_code": order_code, "auto_from_bom": False, "planned_volume_hl": 100})
    assert r.status_code == 201, r.text
    return r.json()["brew_order_id"]


def test_seed_creates_21_form_types_and_equipment(client, admin_h):
    form_types = client.get("/api/cip/form-types", headers=admin_h).json()
    assert len(form_types) >= 21
    equipment = client.get("/api/cip/equipment", headers=admin_h).json()
    assert len(equipment) >= 17


def test_seeded_form_types_use_real_codes_with_template_steps(client, admin_h):
    """Mã/tên/bảng bước MẪU phải khớp nguyên văn biểu mẫu giấy gốc (QT-KCS-QT-BM) — không
    phải mã tự đặt — và default_steps phải sẵn có để "Khai báo biểu mẫu" tự điền."""
    ft = _form_type(client, admin_h, "2.1.2/2025/QT-KCS-QT-BM-01")
    assert "TANK LÊN MEN" in ft["name"]
    assert len(ft["default_steps"]) == 11
    assert ft["default_steps"][0]["content"] == "Thu hồi CO2"


def test_form_type_template_steps_editable(client, admin_h):
    """Khu vực "Khai báo biểu mẫu": sửa bảng bước mẫu qua PUT phải lưu lại được."""
    ft = _form_type(client, admin_h, "2.4.2/2025-QT-KCS-QT-BM-03")
    upd = client.put(f"/api/cip/form-types/{ft['form_type_id']}", headers=admin_h, json={
        "code": ft["code"], "name": ft["name"], "area": ft["area"], "kind": ft["kind"],
        "default_steps": [{"step_no": "1", "content": "Bước test sửa mẫu", "time_spec": "10 phút"}],
    })
    assert upd.status_code == 200, upd.text
    assert len(upd.json()["default_steps"]) == 1
    assert upd.json()["default_steps"][0]["content"] == "Bước test sửa mẫu"

    refetched = _form_type(client, admin_h, "2.4.2/2025-QT-KCS-QT-BM-03")
    assert refetched["default_steps"][0]["content"] == "Bước test sửa mẫu"


def test_cip_manage_permission_gates_record_creation(client, vanhanh_h, thukho_h, admin_h):
    ft = _form_type(client, admin_h, "2.4.2/2025-QT-KCS-QT-BM-01(01)")
    eq = _equipment(client, admin_h, "EQ-NAU-01")
    payload = {"form_type_id": ft["form_type_id"], "equipment_id": eq["equipment_id"],
               "batch_number": "B-001", "order_number": "O-001",
               "started_at": "2026-07-01T08:00:00",
               "steps": [{"step_no": "1", "content": "Xút 2%", "time_spec": "20p", "temp": "80C"}]}

    blocked = client.post("/api/cip/records", headers=thukho_h, json=payload)
    assert blocked.status_code == 403, blocked.text

    ok = client.post("/api/cip/records", headers=vanhanh_h, json=payload)
    assert ok.status_code == 201, ok.text
    rec = ok.json()
    assert rec["cip_code"].startswith("CIP-2026-")
    assert rec["steps"][0]["content"] == "Xút 2%"
    assert rec["result"] is None
    assert rec["batch_number"] == "B-001"
    assert rec["order_number"] == "O-001"


def test_cip_record_requires_batch_and_order_number(client, vanhanh_h, admin_h):
    """Batch Number/Order Number (đối chiếu Braumat) là trường bắt buộc khi khai báo CIP."""
    ft = _form_type(client, admin_h, "2.4.2/2025-QT-KCS-QT-BM-02")
    eq = _equipment(client, admin_h, "EQ-NAU-03")
    base = {"form_type_id": ft["form_type_id"], "equipment_id": eq["equipment_id"],
            "started_at": "2026-07-01T08:00:00", "steps": []}

    missing_both = client.post("/api/cip/records", headers=vanhanh_h, json=base)
    assert missing_both.status_code == 422, missing_both.text

    missing_order = client.post("/api/cip/records", headers=vanhanh_h,
                                json={**base, "batch_number": "B-003"})
    assert missing_order.status_code == 422, missing_order.text

    missing_batch = client.post("/api/cip/records", headers=vanhanh_h,
                                json={**base, "order_number": "O-003"})
    assert missing_batch.status_code == 422, missing_batch.text


def test_cip_record_list_and_approve(client, vanhanh_h, kcs_h, thukho_h, admin_h):
    ft = _form_type(client, admin_h, "2.4.2/2025-QT-KCS-QT-BM-01(02)")
    eq = _equipment(client, admin_h, "EQ-NAU-02")

    created = client.post("/api/cip/records", headers=vanhanh_h, json={
        "form_type_id": ft["form_type_id"], "equipment_id": eq["equipment_id"],
        "batch_number": "B-002", "order_number": "O-002",
        "started_at": "2026-07-02T08:00:00", "steps": []})
    assert created.status_code == 201, created.text
    cip_id = created.json()["cip_id"]

    listed = client.get("/api/cip/records", headers=admin_h,
                       params={"equipment_id": eq["equipment_id"]}).json()
    assert any(r["cip_id"] == cip_id and r["linked_count"] == 0 for r in listed)

    blocked_approve = client.post(f"/api/cip/records/{cip_id}/approve", headers=thukho_h,
                                  json={"result": "dat", "checked_by": "Ai đó"})
    assert blocked_approve.status_code == 403, blocked_approve.text

    approve = client.post(f"/api/cip/records/{cip_id}/approve", headers=kcs_h,
                          json={"result": "dat", "checked_by": "KCS Test"})
    assert approve.status_code == 200, approve.text
    assert approve.json()["result"] == "dat"
    assert approve.json()["checked_by"] == "KCS Test"
    assert approve.json()["approved_at"] is not None


def test_suggest_and_link_for_ferment_uses_matching_tank_equipment(client, admin_h, vanhanh_h):
    """Tank FV-01 đã được seed sẵn 1 CipEquipment gắn production_line_id — suggest_for_scope
    cho 1 lô lên men dùng đúng tank FV-01 phải hiện thiết bị đó, và CHỈ thiết bị đó trong số
    các tank lên men (không lẫn FV-02/03/04) — đúng nguyên tắc lọc theo mã tank cụ thể; thiết
    bị dùng chung (không gắn tank cụ thể) vẫn luôn hiện bất kể tank nào."""
    order_id = _a_brew_order(client, admin_h, "LN-CIP01")
    b = client.post("/api/brewing/brews", headers=vanhanh_h,
                    json={"brew_code": "BR-CIP01", "wort_type": "Dịch test", "volume_hl": 100,
                          "lm_code": "LM-CIP01", "tank_lm": "FV-01", "brew_order_id": order_id})
    assert b.status_code == 201, b.text
    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment_id = next(f for f in ferments if f["lm_code"] == "LM-CIP01")["ferment_id"]

    ft = _form_type(client, admin_h, "2.1.2/2025/QT-KCS-QT-BM-01")
    eq_fv01 = _equipment(client, admin_h, "EQ-LM-TANK-FV-01")

    rec = client.post("/api/cip/records", headers=vanhanh_h, json={
        "form_type_id": ft["form_type_id"], "equipment_id": eq_fv01["equipment_id"],
        "batch_number": "LM-CIP01", "order_number": "LN-CIP01",
        "started_at": "2026-06-25T08:00:00", "steps": []})
    assert rec.status_code == 201, rec.text
    cip_id = rec.json()["cip_id"]

    suggestions = client.get("/api/cip/suggest", headers=admin_h,
                             params={"scope_type": "ferment", "scope_id": ferment_id}).json()
    matched_groups = [g for g in suggestions if g["equipment_code"] == "EQ-LM-TANK-FV-01"]
    assert len(matched_groups) == 1
    assert any(r["cip_id"] == cip_id for r in matched_groups[0]["records"])
    other_tank_groups = [g for g in suggestions if g["equipment_code"] in
                         ("EQ-LM-TANK-FV-02", "EQ-LM-TANK-FV-03", "EQ-LM-TANK-FV-04")]
    assert other_tank_groups == []
    shared_groups = [g for g in suggestions if g["equipment_code"] == "EQ-LM-05"]
    assert len(shared_groups) == 1

    link = client.post("/api/cip/links", headers=vanhanh_h,
                       json={"scope_type": "ferment", "scope_id": ferment_id, "cip_ids": [cip_id]})
    assert link.status_code == 201, link.text
    assert link.json()["linked"] == 1

    linked = client.get("/api/cip/links", headers=admin_h,
                        params={"scope_type": "ferment", "scope_id": ferment_id}).json()
    assert len(linked) == 1
    assert linked[0]["cip_id"] == cip_id
    link_id = linked[0]["link_id"]

    listed = client.get("/api/cip/records", headers=admin_h,
                        params={"equipment_id": eq_fv01["equipment_id"]}).json()
    assert next(r for r in listed if r["cip_id"] == cip_id)["linked_count"] == 1

    # Gắn lại lần 2 (trùng) phải được BỎ QUA êm ái — không lỗi, không tạo thêm link.
    relink = client.post("/api/cip/links", headers=vanhanh_h,
                         json={"scope_type": "ferment", "scope_id": ferment_id, "cip_ids": [cip_id]})
    assert relink.status_code == 201, relink.text
    assert relink.json()["linked"] == 0
    still_linked = client.get("/api/cip/links", headers=admin_h,
                              params={"scope_type": "ferment", "scope_id": ferment_id}).json()
    assert len(still_linked) == 1

    unlink = client.delete(f"/api/cip/links/{link_id}", headers=vanhanh_h)
    assert unlink.status_code == 204, unlink.text
    after_unlink = client.get("/api/cip/links", headers=admin_h,
                              params={"scope_type": "ferment", "scope_id": ferment_id}).json()
    assert after_unlink == []

    # Gắn lại để bài test hồ sơ điện tử phía sau xác nhận CIP hiện đúng trong Hồ sơ điện tử.
    relink2 = client.post("/api/cip/links", headers=vanhanh_h,
                          json={"scope_type": "ferment", "scope_id": ferment_id, "cip_ids": [cip_id]})
    assert relink2.status_code == 201, relink2.text


def test_lot_record_includes_cip_links(client, admin_h):
    """Hồ sơ điện tử (services/lot_record.py) phải hiển thị CIP đã gắn cho lô lên men."""
    r = client.get("/api/brewing/lot-record", headers=admin_h, params={"code": "LM-CIP01"})
    assert r.status_code == 200, r.text
    ferments = r.json()["ferments"]
    assert len(ferments) == 1
    assert len(ferments[0]["cip"]) == 1
    assert ferments[0]["cip"][0]["equipment_name"]


def test_form_type_and_equipment_guarded_delete(client, admin_h):
    ft = client.post("/api/cip/form-types", headers=admin_h,
                     json={"code": "QT-CIP-TESTDEL", "name": "Xóa test", "area": "nau", "kind": "full"})
    assert ft.status_code == 201, ft.text
    ft_id = ft.json()["form_type_id"]

    eq = client.post("/api/cip/equipment", headers=admin_h,
                     json={"code": "EQ-TESTDEL", "name": "Thiết bị xóa test", "area": "nau"})
    assert eq.status_code == 201, eq.text
    eq_id = eq.json()["equipment_id"]

    rec = client.post("/api/cip/records", headers=admin_h, json={
        "form_type_id": ft_id, "equipment_id": eq_id,
        "batch_number": "B-DEL", "order_number": "O-DEL",
        "started_at": "2026-07-03T08:00:00", "steps": []})
    assert rec.status_code == 201, rec.text

    assert client.delete(f"/api/cip/form-types/{ft_id}", headers=admin_h).status_code == 409
    assert client.delete(f"/api/cip/equipment/{eq_id}", headers=admin_h).status_code == 409

    ft2 = client.post("/api/cip/form-types", headers=admin_h,
                      json={"code": "QT-CIP-TESTDEL2", "name": "Xóa test 2", "area": "nau", "kind": "full"})
    assert ft2.status_code == 201, ft2.text
    assert client.delete(f"/api/cip/form-types/{ft2.json()['form_type_id']}", headers=admin_h).status_code == 204
