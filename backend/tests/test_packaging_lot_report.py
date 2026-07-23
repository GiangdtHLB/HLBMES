"""Test GET /api/packaging/lot-report — báo cáo bao bì TIÊU HAO (nắp, thùng carton, tem
nhãn...) theo lô, lấy trực tiếp từ Kho NVL (Material/MaterialLot) thay vì khai báo tay như
packaging_type (vỏ chai/két/keg tuần hoàn — không đụng tới). Vật tư thuộc 1 Nhóm vật tư đã
đánh dấu is_packaging tự động lọt vào báo cáo; xuất dùng cho mẻ chiết qua BottleMaterialUsage
(cơ chế NVL đã có sẵn, category-agnostic) hiện luôn trong "usages" của đúng lô đó.
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


def test_material_group_is_packaging_flag_crud(client, admin_h):
    g = client.post("/api/material-groups", headers=admin_h,
                    json={"code": "PKGFLAG01", "name": "Bao bì test"})
    assert g.status_code == 201, g.text
    assert g.json()["is_packaging"] is False  # mặc định tắt

    upd = client.put(f"/api/material-groups/{g.json()['group_id']}", headers=admin_h,
                     json={"code": "PKGFLAG01", "name": "Bao bì test", "active": True, "is_packaging": True})
    assert upd.status_code == 200, upd.text
    assert upd.json()["is_packaging"] is True

    groups = client.get("/api/material-groups", headers=admin_h).json()
    row = next(x for x in groups if x["group_id"] == g.json()["group_id"])
    assert row["is_packaging"] is True


def test_lot_report_only_includes_packaging_group_materials(client, admin_h):
    pg = client.post("/api/material-groups", headers=admin_h,
                     json={"code": "PKGGRP01", "name": "Bao bì tiêu hao", "is_packaging": True})
    assert pg.status_code == 201, pg.text
    other = client.post("/api/material-groups", headers=admin_h,
                        json={"code": "NONPKG01", "name": "Không phải bao bì", "is_packaging": False})
    assert other.status_code == 201, other.text

    pkg_mat = client.post("/api/materials", headers=admin_h,
                          json={"code": "NAP01", "name": "Nắp chai 01", "uom": "cái", "category": "PKGGRP01"})
    assert pkg_mat.status_code == 201, pkg_mat.text
    other_mat = client.post("/api/materials", headers=admin_h,
                            json={"code": "MALT01T", "name": "Malt test", "uom": "kg", "category": "NONPKG01"})
    assert other_mat.status_code == 201, other_mat.text

    rc1 = client.post("/api/warehouse/receive", headers=admin_h,
                      json={"lot_code": "LOT-NAP01-PX", "material_id": pkg_mat.json()["material_id"],
                            "quantity": 1000, "uom": "cái", "location": "Kho phân xưởng"})
    assert rc1.status_code == 200, rc1.text
    rc2 = client.post("/api/warehouse/receive", headers=admin_h,
                      json={"lot_code": "LOT-MALT01T", "material_id": other_mat.json()["material_id"],
                            "quantity": 500, "uom": "kg", "location": "Kho công ty"})
    assert rc2.status_code == 200, rc2.text

    report = client.get("/api/packaging/lot-report", headers=admin_h).json()
    lot_codes = {r["lot_code"] for r in report}
    assert "LOT-NAP01-PX" in lot_codes
    assert "LOT-MALT01T" not in lot_codes

    row = next(r for r in report if r["lot_code"] == "LOT-NAP01-PX")
    assert row["material_code"] == "NAP01"
    assert row["quantity"] == 1000
    assert row["uom"] == "cái"
    assert row["usages"] == []
    assert row["last_issued_at"] is None


def test_lot_report_shows_usage_after_bottle_consumes_lot(client, admin_h, vanhanh_h):
    pkg_mat = client.post("/api/materials", headers=admin_h,
                          json={"code": "CARTON01", "name": "Thùng carton 01", "uom": "cái", "category": "PKGGRP01"})
    assert pkg_mat.status_code == 201, pkg_mat.text
    rc = client.post("/api/warehouse/receive", headers=admin_h,
                     json={"lot_code": "LOT-CARTON01-PX", "material_id": pkg_mat.json()["material_id"],
                           "quantity": 200, "uom": "cái", "location": "Kho phân xưởng"})
    assert rc.status_code == 200, rc.text
    lots = client.get("/api/lots", headers=admin_h).json()
    lot = next(l for l in lots if l["lot_code"] == "LOT-CARTON01-PX")

    b = client.post("/api/brewing/bottles", headers=vanhanh_h,
                    json={"bottle_code": "CH-PKGLOT01", "beer_type": "Bia test"})
    assert b.status_code == 201, b.text
    bottle_id = b.json()["bottle_id"]

    add = client.post(f"/api/brewing/bottles/{bottle_id}/materials", headers=vanhanh_h,
                      json={"lot_id": lot["lot_id"], "quantity": 30, "uom": "cái"})
    assert add.status_code == 201, add.text

    report = client.get("/api/packaging/lot-report", headers=admin_h).json()
    row = next(r for r in report if r["lot_code"] == "LOT-CARTON01-PX")
    assert row["quantity"] == 170  # 200 - 30, trừ kho thật
    assert row["last_issued_at"] is not None
    assert len(row["usages"]) == 1
    assert row["usages"][0]["bottle_code"] == "CH-PKGLOT01"
    assert row["usages"][0]["quantity"] == 30
