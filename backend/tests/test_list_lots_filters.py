"""Test GET /api/lots với các filter mới (material_id/status/location) — thêm 2026-11-12 sau khi
phát hiện bug thực tế: endpoint mặc định chỉ trả 500 lô mới tạo gần nhất toàn nhà máy (created_at
desc), nên nhiều màn hình (Tạo đề nghị nhận kho, FIFO picker, hàng chờ QC duyệt...) tự lọc ở trình
duyệt trên danh sách đã bị cắt trang có thể bỏ sót lô CÒN TỒN THẬT nếu lô đó cũ hơn 500 lô gần nhất
(vật tư 2NP73 trên production: còn 40kg available ở Kho công ty nhưng bị báo tồn=0). Các filter
mới phải lọc TRƯỚC KHI áp limit/offset để không tái diễn lỗi này."""

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


def _create_material(client, admin_h, code):
    r = client.post("/api/materials", headers=admin_h,
                    json={"code": code, "name": f"Vật tư {code}", "uom": "kg", "category": "other"})
    assert r.status_code == 201, r.text
    return r.json()["material_id"]


def test_material_id_filter_returns_only_that_material(client, admin_h, thukho_h):
    mat_a = _create_material(client, admin_h, "LOTF-A")
    mat_b = _create_material(client, admin_h, "LOTF-B")
    client.post("/api/warehouse/receive", headers=thukho_h,
               json={"lot_code": "LOTF-A-01", "material_id": mat_a, "quantity": 10, "uom": "kg"})
    client.post("/api/warehouse/receive", headers=thukho_h,
               json={"lot_code": "LOTF-B-01", "material_id": mat_b, "quantity": 20, "uom": "kg"})

    r = client.get(f"/api/lots?material_id={mat_a}", headers=admin_h)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) >= 1
    assert all(row["material_id"] == mat_a for row in rows)
    assert any(row["lot_code"] == "LOTF-A-01" for row in rows)


def test_material_id_filter_accepts_comma_separated_list(client, admin_h, thukho_h):
    mat_a = _create_material(client, admin_h, "LOTF-MULTI-A")
    mat_b = _create_material(client, admin_h, "LOTF-MULTI-B")
    mat_c = _create_material(client, admin_h, "LOTF-MULTI-C")
    client.post("/api/warehouse/receive", headers=thukho_h,
               json={"lot_code": "LOTF-MULTI-A-01", "material_id": mat_a, "quantity": 1, "uom": "kg"})
    client.post("/api/warehouse/receive", headers=thukho_h,
               json={"lot_code": "LOTF-MULTI-B-01", "material_id": mat_b, "quantity": 1, "uom": "kg"})
    client.post("/api/warehouse/receive", headers=thukho_h,
               json={"lot_code": "LOTF-MULTI-C-01", "material_id": mat_c, "quantity": 1, "uom": "kg"})

    r = client.get(f"/api/lots?material_id={mat_a},{mat_b}", headers=admin_h)
    assert r.status_code == 200, r.text
    rows = r.json()
    returned_mat_ids = {row["material_id"] for row in rows}
    assert returned_mat_ids == {mat_a, mat_b}


def test_status_filter_returns_only_on_hold_lots(client, admin_h, thukho_h):
    mat_free = _create_material(client, admin_h, "LOTF-STATUS-FREE")
    mat_hold = _create_material(client, admin_h, "LOTF-STATUS-HOLD")

    p = client.post("/api/qc/parameters", headers=admin_h,
                    json={"code": "LOTF_PARAM", "name": "Độ ẩm", "unit": "%", "lsl": 3, "usl": 6})
    assert p.status_code == 201, p.text
    param_id = p.json()["param_id"]
    g = client.post("/api/qc/groups", headers=admin_h,
                    json={"code": "LOTF-GRP", "name": "Chỉ tiêu test lotf"})
    assert g.status_code == 201, g.text
    group_id = g.json()["group_id"]
    it = client.post(f"/api/qc/groups/{group_id}/items", headers=admin_h,
                     json={"param_id": param_id, "mandatory": True})
    assert it.status_code == 201, it.text
    link = client.post(f"/api/materials/{mat_hold}/qc-groups", headers=admin_h,
                       json={"group_id": group_id, "mandatory": True})
    assert link.status_code == 201, link.text

    client.post("/api/warehouse/receive", headers=thukho_h,
               json={"lot_code": "LOTF-STATUS-FREE-01", "material_id": mat_free, "quantity": 5, "uom": "kg"})
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "LOTF-STATUS-HOLD-01", "material_id": mat_hold, "quantity": 7, "uom": "kg"})
    assert rc.status_code == 200, rc.text
    assert rc.json()["status"] == "on_hold"

    r = client.get(f"/api/lots?material_id={mat_free},{mat_hold}&status=on_hold", headers=admin_h)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["lot_code"] == "LOTF-STATUS-HOLD-01"
    assert rows[0]["status"] == "on_hold"


def test_location_filter_distinguishes_company_vs_workshop(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "LOTF-LOC")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "LOTF-LOC-CT-01", "material_id": mat_id, "quantity": 30, "uom": "kg"})
    assert rc.status_code == 200, rc.text
    lot_id_ct = rc.json()["lot_id"]
    rc2 = client.post("/api/warehouse/receive", headers=thukho_h,
                      json={"lot_code": "LOTF-LOC-CT-02", "material_id": mat_id, "quantity": 15, "uom": "kg"})
    assert rc2.status_code == 200, rc2.text
    lot_id_px = rc2.json()["lot_id"]

    xfer = client.post("/api/warehouse/transfer", headers=thukho_h,
                       json={"lot_id": lot_id_px, "quantity": 15, "location_to": "Kho phân xưởng"})
    assert xfer.status_code == 200, xfer.text

    r_ct = client.get(f"/api/lots?material_id={mat_id}&location=Kho+c%C3%B4ng+ty", headers=admin_h)
    assert r_ct.status_code == 200, r_ct.text
    codes_ct = {row["lot_code"] for row in r_ct.json()}
    assert "LOTF-LOC-CT-01" in codes_ct
    assert "LOTF-LOC-CT-02" not in codes_ct

    r_px = client.get(f"/api/lots?material_id={mat_id}&location=Kho+ph%C3%A2n+x%C6%B0%E1%BB%9Fng", headers=admin_h)
    assert r_px.status_code == 200, r_px.text
    codes_px = {row["lot_code"] for row in r_px.json()}
    assert "LOTF-LOC-CT-02" in codes_px
    assert "LOTF-LOC-CT-01" not in codes_px


def test_no_filter_keeps_previous_default_behavior(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "LOTF-NOFILTER")
    client.post("/api/warehouse/receive", headers=thukho_h,
               json={"lot_code": "LOTF-NOFILTER-01", "material_id": mat_id, "quantity": 1, "uom": "kg"})
    r = client.get("/api/lots", headers=admin_h)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)
    assert len(r.json()) <= 500
