"""Bug thuc te 2026-10-22: mo deviation KHONG bat buoc tick chi tieu FAIL nao (parameter hoan
toan tuy chon) - cho mo (va dong) deviation "trong" khong gan voi chi tieu FAIL cu the nao, du
Ly do/Dieu tra co ghi ro ten chi tieu bang chu. Hau qua: deviation do du dong xong van khong
cover duoc gi o _assert_releasable (so khop theo ma chi tieu da tick, khong doc noi dung chu) -
Release van bi chan du nguoi xem tuong da xu ly xong (vi du thuc te: DEV-20261019-BDF92 ghi ro
"Bx" trong Dieu tra nhung khong tick o Bx luc mo).
Sua: bat buoc tick it nhat 1 chi tieu khi mo deviation NEU pham vi dang co FAIL nao - khong
chan khi pham vi khong co FAIL nao (khong co gi de tick).
Xem services/quality.py::open_deviation."""

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


def _make_batch(client, admin_h):
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
    return batch_id


def _create_material(client, admin_h, code):
    r = client.post("/api/materials", headers=admin_h,
                    json={"code": code, "name": f"Vat tu {code}", "uom": "kg", "category": "other"})
    assert r.status_code == 201, r.text
    return r.json()["material_id"]


def _receive_lot(client, admin_h, code, mat_id):
    r = client.post("/api/warehouse/receive", headers=admin_h,
                    json={"lot_code": code, "material_id": mat_id, "quantity": 10, "uom": "kg"})
    assert r.status_code == 200, r.text
    return r.json()["lot_id"]


def test_open_deviation_blocked_without_parameter_when_scope_has_fail(client, admin_h):
    batch_id = _make_batch(client, admin_h)
    r = client.post("/api/quality/results", headers=admin_h, json={
        "scope_type": "batch", "scope_id": batch_id, "parameter": "DEVREQ1",
        "value": 99, "lower_limit": 1, "upper_limit": 10})
    assert r.status_code == 201 and r.json()["status"] == "fail", r.text

    r = client.post("/api/quality/deviations", headers=admin_h,
                    json={"scope_type": "batch", "scope_id": batch_id, "reason": "Khong tick", "severity": "minor"})
    assert r.status_code == 409, r.text
    assert "bắt buộc tick" in r.json()["detail"]

    # parameter rong/chi khoang trang cung phai bi chan nhu khong co.
    r2 = client.post("/api/quality/deviations", headers=admin_h,
                     json={"scope_type": "batch", "scope_id": batch_id, "reason": "Rong",
                           "severity": "minor", "parameter": "   "})
    assert r2.status_code == 409, r2.text


def test_open_deviation_succeeds_with_parameter_when_scope_has_fail(client, admin_h):
    batch_id = _make_batch(client, admin_h)
    r = client.post("/api/quality/results", headers=admin_h, json={
        "scope_type": "batch", "scope_id": batch_id, "parameter": "DEVREQ2",
        "value": 99, "lower_limit": 1, "upper_limit": 10})
    assert r.status_code == 201, r.text

    r = client.post("/api/quality/deviations", headers=admin_h,
                    json={"scope_type": "batch", "scope_id": batch_id, "reason": "Co tick",
                          "severity": "minor", "parameter": "DEVREQ2"})
    assert r.status_code == 201, r.text


def test_open_deviation_not_blocked_when_scope_has_no_fail(client, admin_h):
    """Pham vi khong co chi tieu FAIL nao (chua ghi ket qua gi) -> khong co gi de tick, khong
    chan - mirror cac test co san o test_deviation_capa.py (mo deviation cho lo NVL moi nhan,
    chua tung ghi ket qua QC nao)."""
    mat_id = _create_material(client, admin_h, "DEVREQ-MAT-1")
    lot_id = _receive_lot(client, admin_h, "DEVREQ-LOT-1", mat_id)
    r = client.post("/api/quality/deviations", headers=admin_h,
                    json={"scope_type": "lot", "scope_id": lot_id, "reason": "Khong co fail nao", "severity": "minor"})
    assert r.status_code == 201, r.text
