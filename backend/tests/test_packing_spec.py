"""Test danh mục "Quy cách đóng gói pallet" (PackingSpec, xem app/models/master.py) — khai theo
TỪNG SKU (finished_product_id), dùng ở bước "Duyệt nhập kho thành phẩm"
(services/batch_pipeline.py::release_pack_lot_to_wms, xem test_batch_pack_lot_wms.py) để tách
đúng số pallet thật theo quy cách đã dùng (yêu cầu người dùng 2026-09-20: "quy cách đóng gói
pallet chỉ được chọn ở đó ra")."""

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


def _make_sku(client, admin_h, suffix):
    fp = client.post("/api/finished-products", headers=admin_h,
                     json={"name": f"SKU spec test {suffix}", "code": f"SKU-SPEC-{suffix}",
                          "uom": "lon", "unit_type": "vi", "pack_size": 24})
    assert fp.status_code == 201, fp.text
    return fp.json()["finished_product_id"]


def test_create_list_update_delete_packing_spec(client, admin_h):
    fp_id = _make_sku(client, admin_h, "CRUD")

    create = client.post("/api/packing-specs", headers=admin_h,
                         json={"code": "QC01", "name": "Quy cách 01", "finished_product_id": fp_id,
                              "units_per_pallet": 110, "layers": 10})
    assert create.status_code == 201, create.text
    spec = create.json()
    assert spec["units_per_pallet"] == 110 and spec["layers"] == 10 and spec["active"] is True

    listing = client.get(f"/api/packing-specs?finished_product_id={fp_id}", headers=admin_h).json()
    assert [s["spec_id"] for s in listing] == [spec["spec_id"]]

    upd = client.put(f"/api/packing-specs/{spec['spec_id']}", headers=admin_h,
                     json={"code": "QC01", "name": "Quy cách 01 sửa", "finished_product_id": fp_id,
                          "units_per_pallet": 100, "layers": 10, "active": True})
    assert upd.status_code == 200, upd.text
    assert upd.json()["units_per_pallet"] == 100

    delete = client.delete(f"/api/packing-specs/{spec['spec_id']}", headers=admin_h)
    assert delete.status_code == 204, delete.text
    listing_after = client.get(f"/api/packing-specs?finished_product_id={fp_id}", headers=admin_h).json()
    assert listing_after == []


def test_packing_spec_code_unique_per_sku_not_global(client, admin_h):
    """Cùng mã 'QC01' được phép tồn tại ở 2 SKU khác nhau — chỉ trùng trong CÙNG 1 SKU mới bị chặn."""
    fp_a = _make_sku(client, admin_h, "DUPA")
    fp_b = _make_sku(client, admin_h, "DUPB")

    a1 = client.post("/api/packing-specs", headers=admin_h,
                     json={"code": "QC01", "finished_product_id": fp_a, "units_per_pallet": 110})
    assert a1.status_code == 201, a1.text

    dup_same_sku = client.post("/api/packing-specs", headers=admin_h,
                               json={"code": "QC01", "finished_product_id": fp_a, "units_per_pallet": 90})
    assert dup_same_sku.status_code == 409, dup_same_sku.text

    other_sku_ok = client.post("/api/packing-specs", headers=admin_h,
                               json={"code": "QC01", "finished_product_id": fp_b, "units_per_pallet": 90})
    assert other_sku_ok.status_code == 201, other_sku_ok.text


def test_packing_spec_rejects_non_positive_units_per_pallet(client, admin_h):
    fp_id = _make_sku(client, admin_h, "ZERO")
    bad = client.post("/api/packing-specs", headers=admin_h,
                      json={"code": "QC01", "finished_product_id": fp_id, "units_per_pallet": 0})
    assert bad.status_code == 409, bad.text


def test_packing_spec_rejects_unknown_finished_product(client, admin_h):
    bad = client.post("/api/packing-specs", headers=admin_h,
                      json={"code": "QC01", "finished_product_id": "not-a-real-sku", "units_per_pallet": 110})
    assert bad.status_code == 404, bad.text


def test_packing_spec_requires_master_manage_permission(client, admin_h, vanhanh_h):
    fp_id = _make_sku(client, admin_h, "PERM")
    forbidden = client.post("/api/packing-specs", headers=vanhanh_h,
                            json={"code": "QC01", "finished_product_id": fp_id, "units_per_pallet": 110})
    assert forbidden.status_code == 403, forbidden.text
