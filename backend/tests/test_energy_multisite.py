"""Test đa nhà máy (site) cho báo cáo điện SCADA ngoài: mỗi site dùng 1 purpose token riêng
(SITE_PURPOSE) nên không được xung đột với kết nối "energy" hiện có của nhà máy khác."""

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


def test_external_sites_lists_hl_and_dm(client, admin_h):
    r = client.get("/api/energy/external-sites", headers=admin_h)
    assert r.status_code == 200, r.text
    sites = {row["site"]: row["label"] for row in r.json()}
    assert sites == {"hl": "Hạ Long", "dm": "Đông Mai"}


def test_invalid_site_returns_domain_error(client, admin_h):
    r = client.get("/api/energy/external-bounds?site=xx", headers=admin_h)
    assert r.status_code == 409, r.text
    assert "Nhà máy không hợp lệ" in r.json()["detail"]


def test_dm_site_without_connection_gives_labeled_error(client, admin_h):
    """Chưa có SqlConnection nào gán purpose 'energy_dm' -> lỗi phải nêu rõ tên nhà máy Đông Mai
    (không phải thông báo chung chung của Hạ Long), để không gây nhầm lẫn khi cấu hình."""
    r = client.get("/api/energy/external-bounds?site=dm", headers=admin_h)
    assert r.status_code == 409, r.text
    assert "Đông Mai" in r.json()["detail"]


def test_hl_and_dm_purposes_do_not_collide(client, admin_h):
    """Tạo 1 kết nối cho Đông Mai (purpose=energy_dm) và xác nhận nó không được trả về khi
    site=hl (purpose=energy) resolve — mỗi site phải lấy đúng kết nối của mình."""
    c = client.post("/api/integration/connections", headers=admin_h, json={
        "name": "CSDL_NL_DM_TEST", "host": "127.0.0.1", "port": 1433,
        "database_name": "WINCC_DMA_TEST", "username": "sa", "password": "x",
        "purpose": "energy_dm", "active": True,
    })
    assert c.status_code == 201, c.text

    # site=dm giờ resolve được kết nối (dù connect thật sự sẽ fail vì host giả, nhưng bounds
    # phải đi xa hơn bước resolve connection và không còn báo "chưa có kết nối nào được gán").
    r_dm = client.get("/api/energy/external-bounds?site=dm", headers=admin_h)
    assert "Chưa có kết nối SQL nào được gán" not in r_dm.json().get("detail", "")

    # site=hl vẫn phải báo thiếu kết nối riêng của nó (không bị nhầm sang kết nối energy_dm).
    r_hl = client.get("/api/energy/external-bounds?site=hl", headers=admin_h)
    assert r_hl.status_code == 409, r_hl.text
    assert "Hạ Long" in r_hl.json()["detail"]
