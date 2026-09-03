"""Test báo cáo "Đã chiết nhưng chưa duyệt" (GET /api/reports/bottled-not-approved) — lô thành
phẩm (BatchPackLot, pipeline "Mẻ sản xuất" mới) đã tách nhưng chưa được KCS duyệt
(approved=False). Xem services/dashboard.py::bottled_not_approved_report.

Báo cáo này đã đổi nguồn từ BottleRecord (module Nấu-Lọc-Chiết cũ) sang BatchPackLot
(2026-09-02, theo yêu cầu người dùng: "duyệt từ chiết bây giờ chỉ lấy từ nguồn mới là Chiết mới
tạo ra, không lấy từ nguồn cũ Nấu lọc chiết nữa") — test trước đây vẫn dựng dữ liệu qua
BottleRecord (/api/brewing/bottles) và assert theo `bottle_id`, nên luôn thấy báo cáo rỗng vì
báo cáo không còn đọc BottleRecord nữa. Sửa lại dựng dữ liệu qua chuỗi mới: BatchExecution ->
BatchTank -> BatchFilterLot -> BatchPackLot, assert theo `pack_lot_id`.
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


def _a_finished_product(client, admin_h, code, pack_size=1):
    fp = client.post("/api/finished-products", headers=admin_h,
                     json={"code": code, "name": f"SP {code}", "uom": "lon",
                           "unit_type": "vi", "pack_size": pack_size})
    assert fp.status_code == 201, fp.text
    return fp.json()["finished_product_id"]


def _make_batch(client, admin_h):
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(x for x in vers if x["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                          "planned_qty": 1000, "allow_shortage": True})
    assert b.status_code == 201, b.text
    return b.json()["batch_id"]


def _run_batch_to_completed(client, admin_h, batch_id):
    for target in ("ready", "running"):
        r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": target})
        assert r.status_code == 200, r.text
    aq = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": 1000})
    assert aq.status_code == 200, aq.text
    fin = client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={})
    assert fin.status_code == 200, fin.text
    r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "completed"})
    assert r.status_code == 200, r.text


def _make_tank(client, admin_h, tank_code):
    batch_id = _make_batch(client, admin_h)
    _run_batch_to_completed(client, admin_h, batch_id)
    t = client.post("/api/batch-tanks", headers=admin_h,
                    json={"batch_ids": [batch_id], "tank_code": tank_code})
    assert t.status_code == 201, t.text
    return t.json()["tank_id"]


def _make_filter_lot(client, admin_h, suffix):
    tank_id = _make_tank(client, admin_h, f"TANK-{suffix}")
    bbt = client.post("/api/lines", headers=admin_h,
                      json={"code": f"BBT-{suffix}", "name": f"Tank thành phẩm {suffix}", "kind": "tank_bbt"})
    assert bbt.status_code == 201, bbt.text
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": f"FLOT-{suffix}", "to_bbt": bbt.json()["code"],
        "sources": [{"source_type": "tank", "source_tank_id": tank_id}],
    })
    assert draw.status_code == 201, draw.text
    return draw.json()["filter_lot_id"]


def _finish_only_source(client, admin_h, filter_lot_id, v_drawn=900):
    src = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()[0]
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    fin = client.put(f"/api/batch-filter-lots/batches/{batches[0]['batch_link_id']}/finish", headers=admin_h,
                     json={"draws": [{"source_link_id": src["link_id"], "dich_nha_hl": v_drawn}],
                          "nuoc_bai_khi_hl": 0})
    assert fin.status_code == 200, fin.text


def _make_pack_lot(client, admin_h, filter_lot_id, suffix, finished_product_id=None, qty=500):
    pack = client.post(f"/api/batch-filter-lots/{filter_lot_id}/pack-lots", headers=admin_h,
                       json={"qty": qty, "pack_lot_code": f"PKG-BNA-{suffix}", "lot_no": f"LOT-BNA-{suffix}",
                             "finished_product_id": finished_product_id})
    assert pack.status_code == 201, pack.text
    return pack.json()["pack_lot_id"]


def test_bottled_not_approved_report(client, admin_h):
    fp_id = _a_finished_product(client, admin_h, "SKU-BNA-01")

    # Chỉ lọc, CHƯA tách lô thành phẩm nào -> không có gì để báo cáo thấy (báo cáo chỉ đọc
    # BatchPackLot) — dựng riêng 1 lô lọc không đụng tới để chắc chắn không lẫn vào kết quả.
    _make_filter_lot(client, admin_h, "BNA-UNFINISHED")

    # Đã tách lô thành phẩm nhưng chưa duyệt KCS -> PHẢI xuất hiện.
    pending_fl = _make_filter_lot(client, admin_h, "BNA-PENDING")
    _finish_only_source(client, admin_h, pending_fl)
    pending_id = _make_pack_lot(client, admin_h, pending_fl, "PENDING", finished_product_id=fp_id)

    # Đã tách lô thành phẩm VÀ đã duyệt KCS -> không được xuất hiện nữa.
    approved_fl = _make_filter_lot(client, admin_h, "BNA-APPROVED")
    _finish_only_source(client, admin_h, approved_fl)
    approved_id = _make_pack_lot(client, admin_h, approved_fl, "APPROVED", finished_product_id=fp_id)
    ok = client.post(f"/api/batch-pack-lots/{approved_id}/approve", headers=admin_h)
    assert ok.status_code == 200, ok.text

    r = client.get("/api/reports/bottled-not-approved", headers=admin_h)
    assert r.status_code == 200, r.text
    data = r.json()
    ids = {it["pack_lot_id"] for it in data["items"]}
    assert pending_id in ids
    assert approved_id not in ids

    item = next(it for it in data["items"] if it["pack_lot_id"] == pending_id)
    assert item["finished_product_code"] == "SKU-BNA-01"
    assert item["hours_waiting"] >= 0
    assert item["pack_lot_code"] == "PKG-BNA-PENDING"
    assert data["total"] == len(data["items"])

    # Duyệt lô đang chờ -> phải biến mất khỏi báo cáo.
    ok2 = client.post(f"/api/batch-pack-lots/{pending_id}/approve", headers=admin_h)
    assert ok2.status_code == 200, ok2.text
    r2 = client.get("/api/reports/bottled-not-approved", headers=admin_h)
    ids2 = {it["pack_lot_id"] for it in r2.json()["items"]}
    assert pending_id not in ids2
