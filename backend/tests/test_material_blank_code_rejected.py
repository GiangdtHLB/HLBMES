"""Vật tư mã/tên rỗng trước đây lọt qua được (MaterialIn không có ràng buộc gì ngoài kiểu `str`,
chấp nhận "") — phát hiện thực tế 2026-09-29: 1 vật tư mã rỗng tồn tại trên production, do
`list_materials` sắp theo `Material.code` nên nó luôn đứng ĐẦU danh sách, âm thầm trở thành lựa
chọn mặc định ở các form chọn nhanh (VD "Nhập tồn đầu" kho phân xưởng), khiến 1 lô bị nhập nhầm
vào đúng vật tư rỗng này mà không ai để ý."""

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


@pytest.fixture(scope="module")
def admin_h(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "AdminTest123"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.mark.parametrize("code,name", [("", "Tên hợp lệ"), ("MTB-01", ""), ("   ", "Tên hợp lệ"), ("MTB-02", "   ")])
def test_blank_code_or_name_rejected(client, admin_h, code, name):
    r = client.post("/api/materials", headers=admin_h,
                    json={"code": code, "name": name, "uom": "kg"})
    assert r.status_code == 422, r.text


def test_valid_code_and_name_still_accepted(client, admin_h):
    r = client.post("/api/materials", headers=admin_h,
                    json={"code": "MTB-VALID01", "name": "Vật tư hợp lệ", "uom": "kg"})
    assert r.status_code == 201, r.text
