"""Test báo cáo "BC hiệu suất chi tiết theo tháng" (Nhóm D, port từ phần mềm QLSX cũ
dma.biahalong.com:88 › Báo cáo sản xuất, yêu cầu người dùng 2026-11-05) trong
services/yield_reports.py::monthly_yield_detail.

Ghi hiệu suất qua đúng API thật (POST /batches/{id}/yield) để có FK hợp lệ, sau đó SỬA THẲNG
recorded_at qua ORM (API luôn tự set = utcnow(), không nhận tham số) để đẩy bản ghi vào đúng
tháng test (2031-06, tương lai xa — không đụng dữ liệu seed/test khác)."""

import os
import tempfile
from datetime import datetime, timezone

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["MES_DATABASE_URL"] = f"sqlite:///{_TMP.name}"
os.environ["MES_DEV_HEADER_AUTH"] = "0"
os.environ["MES_RL_ENABLED"] = "0"
os.environ["MES_ADMIN_PASSWORD"] = "AdminTest123"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import seed as seed_mod
from app.database import SessionLocal
from app.models.recipe_ext import BatchYieldActual


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


def _make_batch(client, admin_h, suffix):
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


def _record_yield_in_month(client, admin_h, batch_id, step_key, input_qty, output_qty, when):
    """API luôn set recorded_at=utcnow() — không truyền được qua payload. Lấy diff
    before/after theo yield_id (KHÔNG dùng order_by recorded_at desc) để tìm đúng dòng vừa tạo,
    vì các lần gọi trước đó trong cùng test đã bị sửa recorded_at sang TƯƠNG LAI (2031), nên thời
    điểm thật (utcnow() lúc tạo) của dòng MỚI luôn "nhỏ hơn" các dòng cũ đã bị sửa — order_by desc
    sẽ chọn nhầm dòng cũ."""
    db = SessionLocal()
    try:
        before_ids = {r.yield_id for r in db.query(BatchYieldActual.yield_id).filter(
            BatchYieldActual.batch_id == batch_id, BatchYieldActual.step_key == step_key)}
    finally:
        db.close()
    r = client.post(f"/api/batches/{batch_id}/yield", headers=admin_h,
                    json={"step_key": step_key, "input_qty": input_qty, "output_qty": output_qty})
    assert r.status_code == 200, r.text
    db = SessionLocal()
    try:
        rows = db.query(BatchYieldActual).filter(
            BatchYieldActual.batch_id == batch_id, BatchYieldActual.step_key == step_key)
        row = next(r for r in rows if r.yield_id not in before_ids)
        row.recorded_at = when
        db.commit()
    finally:
        db.close()


def test_monthly_yield_detail_aggregates_by_step(client, admin_h):
    b1 = _make_batch(client, admin_h, "YLD01")
    b2 = _make_batch(client, admin_h, "YLD02")
    JUN2031 = datetime(2031, 6, 15, tzinfo=timezone.utc)
    JUL2031 = datetime(2031, 7, 1, tzinfo=timezone.utc)

    _record_yield_in_month(client, admin_h, b1, "nau", 1000, 950, JUN2031)   # 95%
    _record_yield_in_month(client, admin_h, b2, "nau", 1000, 900, JUN2031)   # 90%
    _record_yield_in_month(client, admin_h, b1, "loc", 950, 940, JUN2031)    # 98.95%
    _record_yield_in_month(client, admin_h, b1, "nau", 1000, 999, JUL2031)   # ngoài tháng test — phải bị loại

    r = client.get("/api/reports/monthly-yield-detail", headers=admin_h,
                   params={"year": 2031, "month": 6})
    assert r.status_code == 200, r.text
    rep = r.json()

    nau = next(s for s in rep["summary"] if s["step_key"] == "nau")
    assert nau["n"] == 2
    assert nau["avg_pct"] == round((95.0 + 90.0) / 2, 2)

    loc = next(s for s in rep["summary"] if s["step_key"] == "loc")
    assert loc["n"] == 1
    assert loc["avg_pct"] == 98.95

    assert len(rep["items"]) == 3   # 2 nau + 1 loc trong tháng 6 — bản ghi tháng 7 không lọt vào
    assert all(i["step_key"] != "nau" or i["output_qty"] != 999 for i in rep["items"])
