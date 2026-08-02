"""Test báo cáo "Đã chiết nhưng chưa duyệt" (GET /api/reports/bottled-not-approved) — mẻ
chiết đã bấm "Kết thúc" (ended_at có giá trị) nhưng chưa được Giám đốc SX duyệt nhập kho
(approved=False). Xem services/dashboard.py::bottled_not_approved_report."""

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


def _a_finished_product(client, admin_h, code, pack_size=1):
    fp = client.post("/api/finished-products", headers=admin_h,
                     json={"code": code, "name": f"SP {code}", "uom": "lon",
                           "unit_type": "vi", "pack_size": pack_size})
    assert fp.status_code == 201, fp.text
    return fp.json()["finished_product_id"]


def _a_bottle(client, vanhanh_h, code, fp_id):
    b = client.post("/api/brewing/bottles", headers=vanhanh_h,
                    json={"bottle_code": code, "beer_type": "Bia test", "finished_product_id": fp_id})
    assert b.status_code == 201, b.text
    return b.json()["bottle_id"]


def test_bottled_not_approved_report(client, admin_h, vanhanh_h):
    fp_id = _a_finished_product(client, admin_h, "SKU-BNA-01")

    # Chưa bấm "Kết thúc" -> không xuất hiện trong báo cáo dù chưa duyệt.
    unfinished_id = _a_bottle(client, vanhanh_h, "CH-BNA-UNFINISHED", fp_id)

    # Đã "Kết thúc" nhưng chưa duyệt -> PHẢI xuất hiện.
    pending_id = _a_bottle(client, vanhanh_h, "CH-BNA-PENDING", fp_id)
    fin = client.post(f"/api/brewing/bottles/{pending_id}/finish", headers=vanhanh_h, json={"ca1": 5})
    assert fin.status_code == 200, fin.text

    # Đã "Kết thúc" VÀ đã duyệt -> không được xuất hiện nữa.
    approved_id = _a_bottle(client, vanhanh_h, "CH-BNA-APPROVED", fp_id)
    fin2 = client.post(f"/api/brewing/bottles/{approved_id}/finish", headers=vanhanh_h, json={"ca1": 5})
    assert fin2.status_code == 200, fin2.text
    ok = client.post(f"/api/brewing/bottles/{approved_id}/approve", headers=admin_h)
    assert ok.status_code == 200, ok.text

    r = client.get("/api/reports/bottled-not-approved", headers=admin_h)
    assert r.status_code == 200, r.text
    data = r.json()
    ids = {it["bottle_id"] for it in data["items"]}
    assert pending_id in ids
    assert unfinished_id not in ids
    assert approved_id not in ids

    item = next(it for it in data["items"] if it["bottle_id"] == pending_id)
    assert item["finished_product_code"] == "SKU-BNA-01"
    assert item["hours_waiting"] >= 0
    assert data["total"] == len(data["items"])

    # Duyệt mẻ đang chờ -> phải biến mất khỏi báo cáo.
    ok2 = client.post(f"/api/brewing/bottles/{pending_id}/approve", headers=admin_h)
    assert ok2.status_code == 200, ok2.text
    r2 = client.get("/api/reports/bottled-not-approved", headers=admin_h)
    ids2 = {it["bottle_id"] for it in r2.json()["items"]}
    assert pending_id not in ids2
