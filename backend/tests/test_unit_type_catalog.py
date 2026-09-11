"""Test Danh mục Loại đơn vị tồn kho (UnitTypeCatalog). Bao trùm:
- CRUD cơ bản + chặn trùng mã + chặn đổi mã của loại hệ thống (vi/keg/lon).
- Guarded delete: chặn xóa loại hệ thống, chặn xóa loại đang có SKU/tồn kho dùng.
(Các test build_units/quy đổi qua Kho TP đã bị gỡ khi Kho TP hạ cấp về hệ pallet/case —
Pallet/Case không còn khái niệm unit_type/pack_size divisor như FinishedGoodsUnit cũ.)"""

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

