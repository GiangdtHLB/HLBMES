"""Test Quy định công nghệ nấu theo dịch bia (Product.spec_json) — GET/PUT
/api/products/{id}/brew-spec, xem services/master_data.py::get_spec_values/update_spec_values.
Trước đây sống trong test_braumat_import.py cùng phần "Thực hiện" (BrewProcessLog, module
Nấu-Lọc-Chiết cũ, đã xóa) — tách riêng vì tính năng này độc lập, không phụ thuộc module đó."""

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


def test_product_brew_spec_get_update_and_admin_gating(client, admin_h):
    """Quy định (Product.spec_json) — chỉ master.manage (admin) sửa được; vanhanh
    (chỉ có batch.execute) bị chặn. Key lạ bị bỏ qua, không lỗi."""
    p = client.post("/api/products", headers=admin_h,
                    json={"code": "SAP-SPEC-TEST", "name": "Sapphire spec test", "uom": "L"})
    assert p.status_code == 201, p.text
    product_id = p.json()["product_id"]

    get1 = client.get(f"/api/products/{product_id}/brew-spec", headers=admin_h)
    assert get1.status_code == 200, get1.text
    assert get1.json()["rc_nuoc_hl"] is None

    vanhanh_h = _login(client, "vanhanh", "123456")
    forbidden = client.put(f"/api/products/{product_id}/brew-spec", headers=vanhanh_h,
                           json={"rc_nuoc_hl": 28})
    assert forbidden.status_code == 403, forbidden.text

    put_resp = client.put(f"/api/products/{product_id}/brew-spec", headers=admin_h,
                          json={"rc_nuoc_hl": 28, "rc_ph_nuoc": 6.2, "unknown_field_xyz": 999})
    assert put_resp.status_code == 200, put_resp.text
    body = put_resp.json()
    assert body["rc_nuoc_hl"] == 28
    assert body["rc_ph_nuoc"] == 6.2
    assert "unknown_field_xyz" not in body

    get2 = client.get(f"/api/products/{product_id}/brew-spec", headers=admin_h)
    assert get2.json()["rc_nuoc_hl"] == 28
