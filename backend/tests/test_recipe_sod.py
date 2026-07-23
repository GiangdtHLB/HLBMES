"""Test segregation of duties (SoD) khi duyệt công thức (BOM): người soạn không được
tự duyệt version do chính mình tạo — TRỪ admin (tài khoản quản trị hệ thống được miễn trừ,
để một mình admin vẫn thao tác được hết vòng đời công thức lúc mới triển khai/thử nghiệm)."""

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
def kysu_h(client):
    return _login(client, "kysu", "123456")


def _a_recipe_version(client, headers, suffix):
    p = client.post("/api/products", headers=headers,
                    json={"code": f"PRD-{suffix}", "name": f"Dịch test {suffix}", "uom": "L"})
    assert p.status_code == 201, p.text
    product_id = p.json()["product_id"]
    r = client.post("/api/recipes", headers=headers,
                    json={"code": f"REC-{suffix}", "name": f"Công thức {suffix}", "product_id": product_id})
    assert r.status_code == 201, r.text
    recipe_id = r.json()["recipe_id"]
    v = client.post(f"/api/recipes/{recipe_id}/versions", headers=headers, json={})
    assert v.status_code == 201, v.text
    return v.json()["version_id"]


def test_non_admin_cannot_approve_own_recipe_version(client, kysu_h):
    version_id = _a_recipe_version(client, kysu_h, "SOD01")
    to_review = client.post(f"/api/recipes/versions/{version_id}/transition", headers=kysu_h,
                            json={"target": "review"})
    assert to_review.status_code == 200, to_review.text

    blocked = client.post(f"/api/recipes/versions/{version_id}/transition", headers=kysu_h,
                          json={"target": "approved"})
    assert blocked.status_code == 403, blocked.text


def test_admin_can_approve_own_recipe_version(client, admin_h):
    version_id = _a_recipe_version(client, admin_h, "SOD02")
    to_review = client.post(f"/api/recipes/versions/{version_id}/transition", headers=admin_h,
                            json={"target": "review"})
    assert to_review.status_code == 200, to_review.text

    approved = client.post(f"/api/recipes/versions/{version_id}/transition", headers=admin_h,
                           json={"target": "approved"})
    assert approved.status_code == 200, approved.text
    assert approved.json()["state"] == "approved"
