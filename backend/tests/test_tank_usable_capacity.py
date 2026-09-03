"""Test chặn tổng thể tích chứa ở Tank lên men (BatchTank)/Tank thành phẩm (BBT, BatchFilterLot)
vượt quá "thể tích khả dụng" (ProductionLine.volume * usable_pct/100) trong quá trình nấu/lọc —
yêu cầu người dùng 2026-09-01. Xem services/batch_pipeline.py::usable_capacity_for_code/
_assert_within_capacity, dùng ở merge_batches_into_tank, services/batches.py::set_actual_qty,
và finish_filter_lot_batch.
"""

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


def _make_batch(client, admin_h, batch_code, planned_qty=1000):
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(v for v in vers if v["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                          "batch_code": batch_code, "planned_qty": planned_qty, "allow_shortage": True})
    assert b.status_code == 201, b.text
    return b.json()["batch_id"]


def _run_batch_to_completed(client, admin_h, batch_id, actual_qty):
    for target in ("ready", "running"):
        r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": target})
        assert r.status_code == 200, r.text
    aq = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": actual_qty})
    assert aq.status_code == 200, aq.text
    fin = client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={})
    assert fin.status_code == 200, fin.text
    r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "completed"})
    assert r.status_code == 200, r.text


def test_merge_batches_into_tank_blocked_over_usable_capacity(client, admin_h):
    line = client.post("/api/lines", headers=admin_h,
                       json={"code": "FV-CAP-01", "name": "Tank cap 01", "kind": "tank",
                             "volume": 100, "volume_uom": "hl", "usable_pct": 90})
    assert line.status_code == 201, line.text

    batch_id = _make_batch(client, admin_h, "1")
    _run_batch_to_completed(client, admin_h, batch_id, actual_qty=95)  # > 90 hl khả dụng

    over = client.post("/api/batch-tanks", headers=admin_h,
                       json={"batch_ids": [batch_id], "tank_code": "TANK-CAP-01", "tank_lm": "FV-CAP-01"})
    assert over.status_code == 409, over.text
    assert "khả dụng" in over.json()["detail"].lower()


def test_merge_batches_into_tank_ok_within_usable_capacity(client, admin_h):
    line = client.post("/api/lines", headers=admin_h,
                       json={"code": "FV-CAP-02", "name": "Tank cap 02", "kind": "tank",
                             "volume": 100, "volume_uom": "hl", "usable_pct": 90})
    assert line.status_code == 201, line.text

    batch_id = _make_batch(client, admin_h, "2")
    _run_batch_to_completed(client, admin_h, batch_id, actual_qty=80)  # <= 90 hl khả dụng

    ok = client.post("/api/batch-tanks", headers=admin_h,
                     json={"batch_ids": [batch_id], "tank_code": "TANK-CAP-02", "tank_lm": "FV-CAP-02"})
    assert ok.status_code == 201, ok.text
    tank_id = ok.json()["tank_id"]

    # set_actual_qty tăng thêm vượt khả dụng -> chặn, tồn tank giữ nguyên (không rollback dở).
    batch_id_2 = _make_batch(client, admin_h, "3")
    for target in ("ready", "running"):
        client.post(f"/api/batches/{batch_id_2}/transition", headers=admin_h, json={"target": target})
    link = client.post("/api/batch-tanks", headers=admin_h,
                       json={"batch_ids": [batch_id_2], "tank_code": "TANK-CAP-02B"})
    # mẻ 2 gộp vào tank RIÊNG (không liên quan capacity) chỉ để có 1 batch "planned" khác test dưới
    assert link.status_code == 201, link.text

    over_aq = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": 95})
    assert over_aq.status_code == 409, over_aq.text
    assert "khả dụng" in over_aq.json()["detail"].lower()

    tank_after = client.get(f"/api/batch-tanks/{tank_id}", headers=admin_h).json()
    assert tank_after["on_hand"] == 80.0   # không bị thay đổi bởi lần set_actual_qty bị chặn

    within_aq = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": 88})
    assert within_aq.status_code == 200, within_aq.text
    tank_final = client.get(f"/api/batch-tanks/{tank_id}", headers=admin_h).json()
    assert tank_final["on_hand"] == 88.0


def _make_bbt_line(client, admin_h, code, volume, usable_pct):
    r = client.post("/api/lines", headers=admin_h,
                    json={"code": code, "name": f"BBT {code}", "kind": "tank_bbt",
                          "volume": volume, "volume_uom": "hl", "usable_pct": usable_pct})
    assert r.status_code == 201, r.text
    return code


def _make_source_tank(client, admin_h, suffix, actual_qty):
    batch_id = _make_batch(client, admin_h, None)
    _run_batch_to_completed(client, admin_h, batch_id, actual_qty=actual_qty)
    tank = client.post("/api/batch-tanks", headers=admin_h,
                       json={"batch_ids": [batch_id], "tank_code": f"TANK-CAPSRC-{suffix}"})
    assert tank.status_code == 201, tank.text
    return tank.json()["tank_id"]


def test_finish_filter_lot_batch_blocked_over_bbt_usable_capacity(client, admin_h):
    bbt_code = _make_bbt_line(client, admin_h, "BBT-CAP-01", volume=30, usable_pct=80)  # khả dụng 24 hl
    tank_id = _make_source_tank(client, admin_h, "01", actual_qty=50)

    order = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-CAP-01",
        "sources": [{"source_type": "tank", "source_tank_id": tank_id, "planned_v_dich_hl": 50}]})
    assert order.status_code == 201, order.text

    fl = client.post(f"/api/batch-filter-orders/{order.json()['order_id']}/filter-lots", headers=admin_h,
                     json={"filter_lot_code": "FLOT-CAP-01", "to_bbt": bbt_code})
    assert fl.status_code == 201, fl.text
    filter_lot_id = fl.json()["filter_lot_id"]

    sources = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()

    over = client.put(f"/api/batch-filter-lots/batches/{batches[0]['batch_link_id']}/finish", headers=admin_h,
                      json={"draws": [{"source_link_id": sources[0]["link_id"], "dich_nha_hl": 28}],
                            "nuoc_bai_khi_hl": 0})
    assert over.status_code == 409, over.text
    assert "khả dụng" in over.json()["detail"].lower()

    # Chặn xong -> tồn tank nguồn KHÔNG bị trừ (rollback đúng, chưa rút thật).
    tank_after = client.get(f"/api/batch-tanks/{tank_id}", headers=admin_h).json()
    assert tank_after["on_hand"] == 50.0

    ok = client.put(f"/api/batch-filter-lots/batches/{batches[0]['batch_link_id']}/finish", headers=admin_h,
                    json={"draws": [{"source_link_id": sources[0]["link_id"], "dich_nha_hl": 20}],
                          "nuoc_bai_khi_hl": 2})
    assert ok.status_code == 200, ok.text
    assert ok.json()["on_hand"] == 22.0  # <= 24 hl khả dụng, hợp lệ
