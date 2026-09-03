"""Test trạng thái Lọc (chờ chiết/đang chiết/đã chiết hết) suy ra từ tồn BBT thật
(on_hand_bbt), và việc duyệt chiết (approve_bottle) tự động nhập kho thành phẩm (WMS)
— cùng cơ chế đã làm cho trạng thái Lên men (on_hand_cct).
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
def vanhanh_h(client):
    return _login(client, "vanhanh", "123456")


def _a_brew_order(client, admin_h, order_code, product_id=None):
    r = client.post("/api/brewing/orders", headers=admin_h,
                    json={"order_code": order_code, "product_id": product_id, "auto_from_bom": False, "planned_volume_hl": 100})
    assert r.status_code == 201, r.text
    return r.json()["brew_order_id"]


def _setup_ferment(client, admin_h, vanhanh_h, suffix):
    """Tạo 1 mã nấu + lô LM đã được KCS duyệt, sẵn sàng để tạo bản ghi lọc."""
    brew_code = f"BR-{suffix}"
    order_id = _a_brew_order(client, admin_h, f"LN-{suffix}")
    b = client.post("/api/brewing/brews", headers=vanhanh_h,
                    json={"brew_code": brew_code, "wort_type": "Dịch test", "volume_hl": 100,
                          "lm_code": f"LM-{suffix}", "tank_lm": f"T-{suffix}", "brew_order_id": order_id})
    assert b.status_code == 201, b.text
    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment = next(f for f in ferments if f["lm_code"] == f"LM-{suffix}")
    ok = client.post(f"/api/brewing/ferments/{ferment['ferment_id']}/approve", headers=admin_h)
    assert ok.status_code == 200, ok.text
    return f"T-{suffix}", ferment["ferment_id"]


def _a_filter_order(client, admin_h, order_code, ferment_ids, blend_mode="khong_phoi"):
    r = client.post("/api/brewing/filter-orders", headers=admin_h,
                    json={"order_code": order_code, "blend_mode": blend_mode, "tank_ferment_ids": ferment_ids,
                          "planned_volume_hl": 1000})
    assert r.status_code == 201, r.text
    return r.json()["filter_order_id"]


def test_filter_status_transitions_with_real_on_hand_bbt(client, admin_h, vanhanh_h):
    tank, ferment_id = _setup_ferment(client, admin_h, vanhanh_h, "FILTERSTATUS")
    order_id = _a_filter_order(client, admin_h, "LOC-FILTERSTATUS", [ferment_id])
    filter_code = "FL-STATUS-01"
    f = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": filter_code, "beer_type": "Bia test", "wort_type": "Dịch test",
                          "filter_order_id": order_id, "to_bbt": "BBT-STATUS-01"})
    assert f.status_code == 201, f.text
    tanks = client.get(f"/api/brewing/filters/{f.json()['filter_id']}/tanks", headers=admin_h).json()
    fin = client.post(f"/api/brewing/filters/{f.json()['filter_id']}/tanks/{tanks[0]['line_id']}/finish",
                      headers=vanhanh_h, json={"v_dich_hl": 100, "nuoc_bai_khi_hl": 0,
                                                "batch_number": "B-STATUS-01", "order_number": "O-STATUS-01", "batch_seq_no": "1"})
    assert fin.status_code == 200, fin.text
    approve_f = client.post(f"/api/brewing/filters/{f.json()['filter_id']}/approve", headers=admin_h)
    assert approve_f.status_code == 200, approve_f.text

    rows = client.get("/api/brewing/filters", headers=admin_h).json()
    row = next(r for r in rows if r["filter_code"] == filter_code)
    assert row["status"] == "cho_chiet"
    assert row["on_hand_bbt"] == 100

    bottle_code1 = "CH-STATUS-01"
    bo1 = client.post("/api/brewing/bottles", headers=vanhanh_h,
                      json={"bottle_code": bottle_code1, "beer_type": "Bia test",
                            "from_bbt": "BBT-STATUS-01"})
    assert bo1.status_code == 201, bo1.text
    # V cấp chiết/hl chưa biết lúc tạo — on_hand_bbt chỉ trừ khi bấm "Kết thúc".
    fin1 = client.post(f"/api/brewing/bottles/{bo1.json()['bottle_id']}/finish", headers=vanhanh_h,
                       json={"v_cap_chiet_hl": 40})
    assert fin1.status_code == 200, fin1.text

    rows = client.get("/api/brewing/filters", headers=admin_h).json()
    row = next(r for r in rows if r["filter_code"] == filter_code)
    assert row["status"] == "chiet_1_phan"
    assert row["status_label"] == "Đang chiết"
    assert row["on_hand_bbt"] == 60

    bottle_code2 = "CH-STATUS-02"
    bo2 = client.post("/api/brewing/bottles", headers=vanhanh_h,
                      json={"bottle_code": bottle_code2, "beer_type": "Bia test",
                            "from_bbt": "BBT-STATUS-01"})
    assert bo2.status_code == 201, bo2.text
    fin2 = client.post(f"/api/brewing/bottles/{bo2.json()['bottle_id']}/finish", headers=vanhanh_h,
                       json={"v_cap_chiet_hl": 60})
    assert fin2.status_code == 200, fin2.text

    rows = client.get("/api/brewing/filters", headers=admin_h).json()
    row = next(r for r in rows if r["filter_code"] == filter_code)
    assert row["status"] == "da_chiet_het"
    assert row["status_label"] == "Đã chiết hết"
    assert row["on_hand_bbt"] == 0

    # Xóa bản ghi chiết phải hoàn lại tồn BBT.
    del_resp = client.delete(f"/api/brewing/bottles/{bo2.json()['bottle_id']}", headers=vanhanh_h)
    assert del_resp.status_code == 204, del_resp.text
    rows = client.get("/api/brewing/filters", headers=admin_h).json()
    row = next(r for r in rows if r["filter_code"] == filter_code)
    assert row["on_hand_bbt"] == 60
    assert row["status"] == "chiet_1_phan"


def test_approve_bottle_requires_quality_release(client, admin_h, vanhanh_h):
    bottle_code = "CH-PERM-TEST"
    b = client.post("/api/brewing/bottles", headers=vanhanh_h,
                    json={"bottle_code": bottle_code, "beer_type": "Bia test", "ca1": 5})
    assert b.status_code == 201, b.text
    denied = client.post(f"/api/brewing/bottles/{b.json()['bottle_id']}/approve", headers=vanhanh_h)
    assert denied.status_code == 403, denied.text


def test_approve_bottle_blocked_when_no_output(client, admin_h, vanhanh_h):
    bottle_code = "CH-NOOUTPUT-TEST"
    b = client.post("/api/brewing/bottles", headers=vanhanh_h,
                    json={"bottle_code": bottle_code, "beer_type": "Bia test"})
    assert b.status_code == 201, b.text
    blocked = client.post(f"/api/brewing/bottles/{b.json()['bottle_id']}/approve", headers=admin_h)
    assert blocked.status_code == 409, blocked.text
    assert "sản lượng" in blocked.json()["detail"].lower()


def test_approve_bottle_no_longer_creates_wms_units(client, admin_h, vanhanh_h):
    """Hồi quy xác nhận đã tháo khỏi WMS (module Nấu-Lọc-Chiết cũ) — approve_bottle chỉ còn
    đóng hồ sơ (approved), KHÔNG còn tự sinh FinishedGoodsUnit/đánh dấu stocked nữa. Lô thành
    phẩm (services/batch_pipeline.py::release_pack_lot_to_wms) là nơi thay thế duy nhất, xem
    tests/test_batch_pack_lot_wms.py."""
    fp = client.post("/api/finished-products", headers=admin_h,
                     json={"code": "SKU-WMS-TEST", "name": "SKU WMS test", "uom": "chai"})
    assert fp.status_code == 201, fp.text
    fp_id = fp.json()["finished_product_id"]

    bottle_code = "CH-WMS-TEST"
    b = client.post("/api/brewing/bottles", headers=vanhanh_h,
                    json={"bottle_code": bottle_code, "beer_type": "Bia test",
                          "finished_product_id": fp_id})
    assert b.status_code == 201, b.text
    bottle_id = b.json()["bottle_id"]
    fin = client.post(f"/api/brewing/bottles/{bottle_id}/finish", headers=vanhanh_h,
                      json={"ca1": 12, "ca2": 3})
    assert fin.status_code == 200, fin.text

    before_units = {u["unit_code"] for u in client.get("/api/wms/units", headers=admin_h).json()}

    ok = client.post(f"/api/brewing/bottles/{bottle_id}/approve", headers=admin_h)
    assert ok.status_code == 200, ok.text
    assert "unit_codes" not in ok.json()
    assert "count" not in ok.json()

    units = client.get("/api/wms/units", headers=admin_h).json()
    new_units = {u["unit_code"] for u in units} - before_units
    assert new_units == set()   # không sinh thêm dòng nào trong Kho TP

    rows = client.get("/api/brewing/bottles", headers=admin_h).json()
    row = next(r for r in rows if r["bottle_code"] == bottle_code)
    assert row["stocked"] is False   # KHÔNG còn tự đánh dấu đã nhập kho
    assert row["approved"] is True
    assert row["approved_by"] == "admin"
    assert row["approved_at"]

    # Duyệt lần 2 phải báo lỗi (đã duyệt rồi).
    twice = client.post(f"/api/brewing/bottles/{bottle_id}/approve", headers=admin_h)
    assert twice.status_code == 409, twice.text
