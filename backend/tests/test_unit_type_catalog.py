"""Test Danh mục Loại đơn vị tồn kho (UnitTypeCatalog) — thay Vỉ/Keg hardcode trong
services/wms.py bằng danh mục admin tự khai báo thêm được (VD "Thùng"). Bao trùm:
- CRUD cơ bản + chặn trùng mã + chặn đổi mã của loại hệ thống (vi/keg/lon).
- Guarded delete: chặn xóa loại hệ thống, chặn xóa loại đang có SKU/tồn kho dùng.
- Loại tự khai báo với divide_by_pack_size=True hoạt động ĐÚNG như Vỉ (quy đổi qua
  FinishedProduct.pack_size) — chứng minh _pack_divisor không còn hardcode "vi".
- Hồi quy: vi/keg vẫn hoạt động đúng như trước (build_units + list_units + capacity)."""

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


def test_seeded_builtin_types_present(client, admin_h):
    types = client.get("/api/unit-types", headers=admin_h).json()
    by_code = {t["code"]: t for t in types}
    assert by_code["vi"]["divide_by_pack_size"] is True
    assert by_code["vi"]["selectable"] is True
    assert by_code["keg"]["divide_by_pack_size"] is False
    assert by_code["keg"]["selectable"] is True
    assert by_code["lon"]["divide_by_pack_size"] is False
    assert by_code["lon"]["selectable"] is False


def test_unit_type_crud_and_duplicate_code_blocked(client, admin_h):
    r = client.post("/api/unit-types", headers=admin_h,
                    json={"code": "thungtest", "name": "Thùng test", "divide_by_pack_size": True})
    assert r.status_code == 201, r.text
    ut_id = r.json()["unit_type_id"]

    listed = client.get("/api/unit-types", headers=admin_h).json()
    assert any(t["unit_type_id"] == ut_id for t in listed)

    upd = client.put(f"/api/unit-types/{ut_id}", headers=admin_h,
                     json={"code": "thungtest", "name": "Thùng test (sửa)",
                           "divide_by_pack_size": True, "selectable": True, "active": True})
    assert upd.status_code == 200, upd.text
    assert upd.json()["name"] == "Thùng test (sửa)"

    dup = client.post("/api/unit-types", headers=admin_h,
                      json={"code": "thungtest", "name": "Trùng mã"})
    assert dup.status_code == 403, dup.text

    delete = client.delete(f"/api/unit-types/{ut_id}", headers=admin_h)
    assert delete.status_code == 204, delete.text
    listed_after = client.get("/api/unit-types", headers=admin_h).json()
    assert not any(t["unit_type_id"] == ut_id for t in listed_after)


def test_builtin_types_cannot_be_deleted_or_recoded(client, admin_h):
    types = {t["code"]: t for t in client.get("/api/unit-types", headers=admin_h).json()}
    vi_id = types["vi"]["unit_type_id"]

    delete = client.delete(f"/api/unit-types/{vi_id}", headers=admin_h)
    assert delete.status_code == 409, delete.text
    assert "hệ thống" in delete.json()["detail"]

    recode = client.put(f"/api/unit-types/{vi_id}", headers=admin_h,
                        json={"code": "vi-renamed", "name": "Vỉ", "divide_by_pack_size": True,
                              "selectable": True, "active": True})
    assert recode.status_code == 403, recode.text

    # Vẫn sửa được tên/cờ (không đổi mã) cho loại hệ thống.
    rename_ok = client.put(f"/api/unit-types/{vi_id}", headers=admin_h,
                           json={"code": "vi", "name": "Vỉ (đã sửa tên)", "divide_by_pack_size": True,
                                 "selectable": True, "active": True})
    assert rename_ok.status_code == 200, rename_ok.text
    assert rename_ok.json()["name"] == "Vỉ (đã sửa tên)"


def test_unit_type_in_use_by_sku_cannot_be_deleted(client, admin_h):
    r = client.post("/api/unit-types", headers=admin_h,
                    json={"code": "inusetest", "name": "Đang dùng test", "divide_by_pack_size": False})
    assert r.status_code == 201, r.text
    ut_id = r.json()["unit_type_id"]

    fp = client.post("/api/finished-products", headers=admin_h,
                     json={"code": "SKU-INUSE-TEST", "name": "SKU đang dùng loại này",
                           "uom": "cái", "unit_type": "inusetest", "pack_size": 1})
    assert fp.status_code == 201, fp.text

    delete = client.delete(f"/api/unit-types/{ut_id}", headers=admin_h)
    assert delete.status_code == 409, delete.text
    assert "đang được dùng" in delete.json()["detail"]


def test_custom_divide_type_scales_by_pack_size_like_vi(client, admin_h):
    """Loại tự khai báo "thùng" (divide_by_pack_size=True) với 1 SKU pack_size=6 phải quy đổi
    count<->quantity giống hệt Vỉ: build total=18 (SL nhỏ) -> build_units trả count=3 (18/6),
    và GET /wms/units/GET /wms/summary đọc lại đúng qua _pack_divisor_expr — không còn
    hardcode "vi" ở cả service lẫn router."""
    ut = client.post("/api/unit-types", headers=admin_h,
                     json={"code": "thungcustom", "name": "Thùng custom", "divide_by_pack_size": True})
    assert ut.status_code == 201, ut.text

    fp = client.post("/api/finished-products", headers=admin_h,
                     json={"code": "SKU-THUNG-CUSTOM", "name": "SKU thùng custom",
                           "uom": "thùng", "unit_type": "thungcustom", "pack_size": 6})
    assert fp.status_code == 201, fp.text
    fp_id = fp.json()["finished_product_id"]
    loc = client.post("/api/wms/locations", headers=admin_h,
                      json={"code": "LOC-THUNG-CUSTOM", "name": "Vị trí thùng custom", "capacity": 100})
    assert loc.status_code == 201, loc.text

    built = client.post("/api/wms/units", headers=admin_h,
                        json={"finished_product_id": fp_id, "product_name": "SKU-THUNG-CUSTOM",
                              "lot_code": "LOT-THUNG-01", "total": 18, "pack_size": 6,
                              "unit_type": "thungcustom", "loc_id": loc.json()["loc_id"]})
    assert built.status_code == 201, built.text
    assert built.json()["count"] == 3  # 18 (SL nhỏ) / 6 (pack_size) = 3 "thùng" — như Vỉ
    unit_code = built.json()["unit_codes"][0]
    assert unit_code.startswith("THUNGCUSTOM-")

    units = client.get("/api/wms/units", headers=admin_h).json()
    row = next(u for u in units if u["unit_code"] == unit_code)
    assert row["quantity"] == 18  # SL nhỏ lưu nguyên trên dòng

    summary = client.get("/api/wms/summary", headers=admin_h).json()
    assert summary["by_type"].get("thungcustom", 0) >= 3  # quy đổi đúng số "thùng", không phải 18

    # list_lot_summaries (GET /wms/units/by-lot) trước đây hardcode 3 loại vi/keg/lon khi gộp
    # theo (sản phẩm, lô) — lô chỉ có loại tự khai báo "thungcustom" bị đếm rỗng nên biến mất
    # hoàn toàn khỏi bảng Kho TP/picker Xuất kho dù tồn kho thật vẫn còn.
    by_lot = client.get("/api/wms/units/by-lot", headers=admin_h).json()
    row = next(g for g in by_lot if g["product_name"] == "SKU-THUNG-CUSTOM" and g["lot_code"] == "LOT-THUNG-01")
    assert "thungcustom" in row["unit_types"]
    assert row["thungcustom_count"] == 3
    assert row["thungcustom_unplaced"] == 0
    assert row["thungcustom_locations"] and row["thungcustom_locations"][0]["count"] == 3


def test_regression_vi_keg_unchanged_behavior(client, admin_h):
    """Hồi quy: vi/keg vẫn quy đổi đúng như trước sau khi _pack_divisor chuyển sang tra danh
    mục động thay vì so sánh chuỗi "vi" hardcode."""
    loc = client.post("/api/wms/locations", headers=admin_h,
                      json={"code": "LOC-REG-VIKEG", "name": "Vị trí hồi quy vi/keg", "capacity": 1000})
    assert loc.status_code == 201, loc.text
    loc_id = loc.json()["loc_id"]
    fp_vi = client.post("/api/finished-products", headers=admin_h,
                        json={"code": "SKU-REG-VI", "name": "SKU hồi quy vỉ", "uom": "lon",
                              "unit_type": "vi", "pack_size": 24})
    assert fp_vi.status_code == 201, fp_vi.text
    built_vi = client.post("/api/wms/units", headers=admin_h,
                           json={"finished_product_id": fp_vi.json()["finished_product_id"],
                                 "product_name": "SKU-REG-VI", "lot_code": "LOT-REG-VI",
                                 "total": 2400, "pack_size": 24, "unit_type": "vi", "loc_id": loc_id})
    assert built_vi.status_code == 201, built_vi.text
    assert built_vi.json()["count"] == 100  # 2400 lon / 24 lon/vỉ = 100 vỉ
    units = client.get("/api/wms/units", headers=admin_h).json()
    row_vi = next(u for u in units if u["unit_code"] == built_vi.json()["unit_codes"][0])
    assert row_vi["quantity"] == 2400
    assert row_vi["unit_code"].startswith("VI-")

    fp_keg = client.post("/api/finished-products", headers=admin_h,
                         json={"code": "SKU-REG-KEG", "name": "SKU hồi quy keg", "uom": "keg",
                               "unit_type": "keg", "pack_size": 1})
    assert fp_keg.status_code == 201, fp_keg.text
    built_keg = client.post("/api/wms/units", headers=admin_h,
                            json={"finished_product_id": fp_keg.json()["finished_product_id"],
                                  "product_name": "SKU-REG-KEG", "lot_code": "LOT-REG-KEG",
                                  "total": 5, "pack_size": 1, "unit_type": "keg", "loc_id": loc_id})
    assert built_keg.status_code == 201, built_keg.text
    assert built_keg.json()["count"] == 5  # keg không nhân pack_size
    units2 = client.get("/api/wms/units", headers=admin_h).json()
    row_keg = next(u for u in units2 if u["unit_code"] == built_keg.json()["unit_codes"][0])
    assert row_keg["quantity"] == 5
    assert row_keg["unit_code"].startswith("KEG-")
