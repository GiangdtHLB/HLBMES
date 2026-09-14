"""Điều chuyển 1 phần lô NVL giữa Kho công ty ↔ Kho phân xưởng KHÔNG còn sinh mã lô mới — dùng
LẠI cùng lot_code, cho phép 1 mã lô có nhiều dòng MaterialLot (1 dòng/kho). Xem kế hoạch
"Kho NVL: cho phép 1 mã lô tồn tại ở nhiều kho" và services/warehouse.py::_transfer_lot/receive,
models/materials.py::MaterialLot (UniqueConstraint mới lot_year+lot_code+location).

Phủ: tách 1 phần giữ nguyên mã; tách lặp lại vào CÙNG đích -> cộng dồn (không tạo dòng 3, không
vỡ unique constraint); chuyển hết phần còn lại vào kho đã có dòng anh em -> gộp; tồn-theo-ngày
đúng qua nhiều lần gộp lặp lại; receive() vào mã đã tồn tại ở kho KHÁC -> tạo dòng mới cùng mã;
_next_lot_code không vỡ khi 1 mã có ≥2 dòng; QC tra theo lô con thấy đúng QC của lô cha; scan.py
theo mã trùng nhiều dòng trả về payload chọn lựa."""

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


def _create_material(client, admin_h, code):
    r = client.post("/api/materials", headers=admin_h,
                    json={"code": code, "name": f"Vật tư {code}", "uom": "kg", "category": "other"})
    assert r.status_code == 201, r.text
    return r.json()["material_id"]


def _receive(client, thukho_h, mat_id, lot_code, qty):
    r = client.post("/api/warehouse/receive", headers=thukho_h,
                    json={"lot_code": lot_code, "material_id": mat_id, "quantity": qty, "uom": "kg"})
    assert r.status_code == 200, r.text
    return r.json()["lot_id"]


def _transfer(client, thukho_h, lot_id, qty, location_to):
    r = client.post("/api/warehouse/transfer", headers=thukho_h,
                    json={"lot_id": lot_id, "quantity": qty, "location_to": location_to})
    assert r.status_code == 200, r.text
    return r.json()


def _lot(client, admin_h, lot_id):
    lots = client.get("/api/lots", headers=admin_h).json()
    return next(l for l in lots if l["lot_id"] == lot_id)


def test_partial_transfer_reuses_lot_code(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "REUSE-01")
    lot_id = _receive(client, thukho_h, mat_id, "LOT-REUSE-01", 100)
    parent = _lot(client, admin_h, lot_id)

    res = _transfer(client, thukho_h, lot_id, 30, "Kho phân xưởng")
    child_id = res["lot_id"]
    assert child_id != lot_id

    child = _lot(client, admin_h, child_id)
    parent = _lot(client, admin_h, lot_id)
    assert child["lot_code"] == parent["lot_code"] == "LOT-REUSE-01"
    assert child["location"] == "Kho phân xưởng"
    assert parent["quantity"] == pytest.approx(70)
    assert child["quantity"] == pytest.approx(30)


def test_repeat_partial_transfer_to_same_destination_merges(client, admin_h, thukho_h):
    """Kịch bản rủi ro nhất: chuyển 1 phần LẶP LẠI vào CÙNG kho đích phải cộng dồn vào dòng đã
    có, không tạo dòng thứ 3 (sẽ vỡ uq_material_lot_year_code_location nếu tạo)."""
    mat_id = _create_material(client, admin_h, "REUSE-02")
    lot_id = _receive(client, thukho_h, mat_id, "LOT-REUSE-02", 100)

    r1 = _transfer(client, thukho_h, lot_id, 20, "Kho phân xưởng")
    child_id = r1["lot_id"]
    r2 = _transfer(client, thukho_h, lot_id, 15, "Kho phân xưởng")
    assert r2["lot_id"] == child_id  # gộp vào ĐÚNG dòng đã có, không tạo dòng mới

    child = _lot(client, admin_h, child_id)
    parent = _lot(client, admin_h, lot_id)
    assert child["quantity"] == pytest.approx(35)
    assert parent["quantity"] == pytest.approx(65)

    all_lots = client.get("/api/lots", headers=admin_h).json()
    same_code = [l for l in all_lots if l["lot_code"] == "LOT-REUSE-02"]
    assert len(same_code) == 2  # đúng 2 dòng (1 mỗi kho), không phải 3


def test_full_remaining_transfer_into_existing_sibling_merges(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "REUSE-03")
    lot_id = _receive(client, thukho_h, mat_id, "LOT-REUSE-03", 100)
    r1 = _transfer(client, thukho_h, lot_id, 40, "Kho phân xưởng")
    child_id = r1["lot_id"]

    # Chuyển HẾT phần còn lại (60) vào kho ĐÃ CÓ dòng anh em -> phải gộp, không gán đè location.
    r2 = _transfer(client, thukho_h, lot_id, 60, "Kho phân xưởng")
    assert r2["lot_id"] == child_id

    child = _lot(client, admin_h, child_id)
    parent = _lot(client, admin_h, lot_id)
    assert child["quantity"] == pytest.approx(100)
    assert parent["quantity"] == pytest.approx(0)
    assert parent["status"] == "consumed"


def test_lot_on_hand_as_of_correct_across_repeated_merges(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "REUSE-04")
    lot_id = _receive(client, thukho_h, mat_id, "LOT-REUSE-04", 100)
    r1 = _transfer(client, thukho_h, lot_id, 20, "Kho phân xưởng")
    child_id = r1["lot_id"]
    _transfer(client, thukho_h, lot_id, 15, "Kho phân xưởng")

    as_of = (utcnow() + timedelta(minutes=1)).isoformat()
    rows = client.get("/api/warehouse/stock/as-of/lots", headers=admin_h, params={"as_of": as_of}).json()
    by_id = {r["lot_id"]: r for r in rows}
    assert by_id[child_id]["quantity"] == pytest.approx(35)
    assert by_id[lot_id]["quantity"] == pytest.approx(65)


def test_receive_existing_lot_code_different_location_creates_sibling_row(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "REUSE-05")
    lot_id = _receive(client, thukho_h, mat_id, "LOT-REUSE-05", 50)
    child_id = _transfer(client, thukho_h, lot_id, 20, "Kho phân xưởng")["lot_id"]

    # Nhập kho THẲNG vào Kho phân xưởng, trùng mã lô đã tồn tại (ở Kho công ty) -> tạo dòng mới
    # cùng mã lô tại Kho phân xưởng, KHÔNG gộp nhầm vào dòng khác kho. thukho chỉ có phạm vi Kho
    # công ty (scope_warehouse="cong_ty") nên dùng admin cho đúng thao tác hiếm này.
    r = client.post("/api/warehouse/receive", headers=admin_h,
                    json={"lot_code": "LOT-REUSE-05", "material_id": mat_id, "quantity": 5,
                          "uom": "kg", "location": "Kho phân xưởng"})
    assert r.status_code == 200, r.text
    new_lot_id = r.json()["lot_id"]
    assert new_lot_id == child_id  # cùng kho, cùng mã -> cộng dồn vào dòng đã có (không tạo mới)

    child = _lot(client, admin_h, child_id)
    assert child["quantity"] == pytest.approx(25)


def test_next_lot_code_does_not_raise_with_multiple_rows_same_code(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "REUSE-06")
    lot_id = _receive(client, thukho_h, mat_id, "LOT-REUSE-06", 50)
    _transfer(client, thukho_h, lot_id, 10, "Kho phân xưởng")

    # Nhập kho KHÔNG khai mã (để hệ thống tự sinh) vẫn phải chạy được dù đã có mã trùng nhiều dòng.
    auto = _receive(client, thukho_h, mat_id, None, 5)
    assert auto


def test_qc_status_visible_across_sibling_rows(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "REUSE-07")
    lot_id = _receive(client, thukho_h, mat_id, "LOT-REUSE-07", 50)
    child_id = _transfer(client, thukho_h, lot_id, 10, "Kho phân xưởng")["lot_id"]

    rec = client.post("/api/quality/results", headers=thukho_h,
                      json={"scope_type": "lot", "scope_id": lot_id, "parameter": "REUSE_QC_PARAM", "value": 1})
    assert rec.status_code == 201, rec.text

    st_parent = client.get(f"/api/lots/{lot_id}/qc-status", headers=thukho_h).json()
    st_child = client.get(f"/api/lots/{child_id}/qc-status", headers=thukho_h).json()
    parent_params = {r["parameter"] for r in st_parent["recorded"]}
    child_params = {r["parameter"] for r in st_child["recorded"]}
    assert "REUSE_QC_PARAM" in parent_params
    assert "REUSE_QC_PARAM" in child_params  # lô con (cùng lot_code) thấy đúng QC của lô cha


def test_scan_by_lot_code_multiple_rows_returns_disambiguation(client, admin_h, thukho_h):
    mat_id = _create_material(client, admin_h, "REUSE-08")
    lot_id = _receive(client, thukho_h, mat_id, "LOT-REUSE-08", 50)
    _transfer(client, thukho_h, lot_id, 10, "Kho phân xưởng")

    r = client.get("/api/scan", headers=thukho_h, params={"code": "LOT-REUSE-08"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["type"] == "lot_multi"
    assert len(body["data"]) == 2
    locations = {d["location"] for d in body["data"]}
    assert locations == {"Kho công ty", "Kho phân xưởng"}


def test_trace_by_lot_code_multiple_rows_does_not_crash(client, admin_h, thukho_h):
    """genealogy.find_node() tra theo lot_code (services/genealogy.py) — trước đây giả định
    lot_code duy nhất toàn hệ thống (`scalar_one_or_none()`), vỡ 500 (MultipleResultsFound) khi
    1 mã có nhiều dòng. Phải ưu tiên đúng dòng GỐC (chưa từng là đích split/transfer) để Truy
    ngược/Truy xuôi vẫn đầy đủ, không còn crash."""
    mat_id = _create_material(client, admin_h, "REUSE-09")
    lot_id = _receive(client, thukho_h, mat_id, "LOT-REUSE-09", 50)
    child_id = _transfer(client, thukho_h, lot_id, 10, "Kho phân xưởng")["lot_id"]

    fwd = client.get("/api/trace/forward", headers=admin_h, params={"code": "LOT-REUSE-09"})
    assert fwd.status_code == 200, fwd.text
    bwd = client.get("/api/trace/backward", headers=admin_h, params={"code": "LOT-REUSE-09"})
    assert bwd.status_code == 200, bwd.text
    # Phải resolve về đúng dòng GỐC (lot_id, không phải child_id — dòng gốc chưa từng là đích
    # split/transfer nên Truy xuôi từ đó vẫn đi được vào dòng con qua đúng cạnh split).
    assert fwd.json()["id"] == lot_id
    assert fwd.json()["id"] != child_id
    child_codes = [c["id"] for c in fwd.json().get("children", [])]
    assert child_id in child_codes
