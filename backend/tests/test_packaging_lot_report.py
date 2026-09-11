"""Test GET /api/packaging/lot-report — báo cáo bao bì TIÊU HAO (nắp, thùng carton, tem
nhãn...) theo lô, lấy trực tiếp từ Kho NVL (Material/MaterialLot) thay vì khai báo tay như
packaging_type (vỏ chai/két/keg tuần hoàn — không đụng tới). Vật tư thuộc 1 Nhóm vật tư đã
đánh dấu is_packaging tự động lọt vào báo cáo; xuất dùng cho lô thành phẩm (BatchPackLot,
pipeline "Mẻ sản xuất") qua BatchPackLotMaterialUsage (cơ chế NVL đã có sẵn, category-agnostic)
hiện luôn trong "usages" của đúng lô đó.
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


def _make_pack_lot(client, admin_h, suffix):
    """Dựng nhanh 1 BatchPackLot: mẻ nấu (BatchExecution) hoàn thành -> gộp tank -> lô lọc ->
    lô thành phẩm — mirror test_bottled_not_approved_report.py."""
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(x for x in vers if x["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                          "planned_qty": 1000, "allow_shortage": True})
    assert b.status_code == 201, b.text
    batch_id = b.json()["batch_id"]
    for target in ("ready", "running"):
        r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": target})
        assert r.status_code == 200, r.text
    aq = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": 1000})
    assert aq.status_code == 200, aq.text
    fin = client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={})
    assert fin.status_code == 200, fin.text
    r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "completed"})
    assert r.status_code == 200, r.text
    t = client.post("/api/batch-tanks", headers=admin_h,
                    json={"batch_ids": [batch_id], "tank_code": f"TANK-{suffix}"})
    assert t.status_code == 201, t.text
    tank_id = t.json()["tank_id"]
    bbt = client.post("/api/lines", headers=admin_h,
                      json={"code": f"BBT-{suffix}", "name": f"Tank thành phẩm {suffix}", "kind": "tank_bbt"})
    assert bbt.status_code == 201, bbt.text
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": f"FLOT-{suffix}", "to_bbt": bbt.json()["code"],
        "sources": [{"source_type": "tank", "source_tank_id": tank_id}],
    })
    assert draw.status_code == 201, draw.text
    filter_lot_id = draw.json()["filter_lot_id"]
    src = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()[0]
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    finfl = client.put(f"/api/batch-filter-lots/batches/{batches[0]['batch_link_id']}/finish", headers=admin_h,
                       json={"draws": [{"source_link_id": src["link_id"], "dich_nha_hl": 900}],
                            "nuoc_bai_khi_hl": 0})
    assert finfl.status_code == 200, finfl.text
    pack = client.post(f"/api/batch-filter-lots/{filter_lot_id}/pack-lots", headers=admin_h,
                       json={"qty": 500, "pack_lot_code": f"PKG-{suffix}", "lot_no": f"LOT-{suffix}"})
    assert pack.status_code == 201, pack.text
    return pack.json()["pack_lot_id"], pack.json()["pack_lot_code"]


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


def test_lot_report_shows_usage_after_pack_lot_consumes_lot(client, admin_h):
    pkg_mat = client.post("/api/materials", headers=admin_h,
                          json={"code": "CARTON01", "name": "Thùng carton 01", "uom": "cái", "category": "PKGGRP01"})
    assert pkg_mat.status_code == 201, pkg_mat.text
    rc = client.post("/api/warehouse/receive", headers=admin_h,
                     json={"lot_code": "LOT-CARTON01-PX", "material_id": pkg_mat.json()["material_id"],
                           "quantity": 200, "uom": "cái", "location": "Kho phân xưởng"})
    assert rc.status_code == 200, rc.text
    lots = client.get("/api/lots", headers=admin_h).json()
    lot = next(l for l in lots if l["lot_code"] == "LOT-CARTON01-PX")

    pack_lot_id, pack_lot_code = _make_pack_lot(client, admin_h, "PKGLOT01")

    add = client.post(f"/api/batch-pack-lots/{pack_lot_id}/materials", headers=admin_h,
                      json={"lot_id": lot["lot_id"], "quantity": 30, "uom": "cái"})
    assert add.status_code == 201, add.text

    report = client.get("/api/packaging/lot-report", headers=admin_h).json()
    row = next(r for r in report if r["lot_code"] == "LOT-CARTON01-PX")
    assert row["quantity"] == 170  # 200 - 30, trừ kho thật
    assert row["last_issued_at"] is not None
    assert len(row["usages"]) == 1
    assert row["usages"][0]["pack_lot_code"] == pack_lot_code
    assert row["usages"][0]["quantity"] == 30
