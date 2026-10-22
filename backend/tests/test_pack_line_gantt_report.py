"""BC "Day chuyen chiet" (pack_line_gantt_report) - yeu cau nguoi dung 2026-10-21: "can cu vao
gio bat dau va gio ket thuc cua day chuyen chiet, ve cho toi 1 bieu do cho tung line chiet, the
hien khoang thoi gian chiet va thoi gian khong chiet. them tham so, tong thoi gian da chiet, so
lan chiet (moi lan line do tinh la 1 lo chiet cua line do)".
Xem services/dashboard.py::pack_line_gantt_report."""

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


def _build_pack_lot(client, admin_h, suffix, line_code, pack_date, shifts):
    """Tao 1 lo chiet moi tren dung line_code - me nau -> tank -> lo loc (hoan thanh loc + duyet
    KCS het de du dieu kien eligible_bbt_lines_for_pack) -> lo thanh pham -> khai shifts (ca1/2/3
    start/end/qty) chi dinh."""
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
    aq = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": 1000})
    assert aq.status_code == 200, aq.text
    fin = client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={})
    assert fin.status_code == 200, fin.text
    r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "completed"})
    assert r.status_code == 200, r.text
    tank = client.post("/api/batch-tanks", headers=admin_h,
                       json={"batch_ids": [batch_id], "tank_code": f"TANK-PLG-{suffix}"})
    assert tank.status_code == 201, tank.text
    bbt = client.post("/api/lines", headers=admin_h,
                      json={"code": f"BBT-PLG-{suffix}", "name": f"BBT {suffix}", "kind": "tank_bbt"})
    assert bbt.status_code == 201, bbt.text
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": f"FLOT-PLG-{suffix}", "to_bbt": bbt.json()["code"],
        "sources": [{"source_type": "tank", "source_tank_id": tank.json()["tank_id"]}],
        "category": "Bia lon"})
    assert draw.status_code == 201, draw.text
    filter_lot_id = draw.json()["filter_lot_id"]

    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    batch_link_id = batches[0]["batch_link_id"]
    sources = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()
    source_link_id = sources[0]["link_id"]
    fb = client.put(f"/api/batch-filter-lots/batches/{batch_link_id}/finish", headers=admin_h, json={
        "draws": [{"source_link_id": source_link_id, "dich_nha_hl": 100}], "nuoc_bai_khi_hl": 0})
    assert fb.status_code == 200, fb.text

    fin2 = client.post(f"/api/batch-filter-lots/{filter_lot_id}/finish-filtering", headers=admin_h)
    assert fin2.status_code == 200, fin2.text
    appr = client.post(f"/api/batch-filter-lots/{filter_lot_id}/approve", headers=admin_h)
    assert appr.status_code == 200, appr.text

    fps = client.get("/api/finished-products", headers=admin_h).json()
    if fps:
        fp_id = fps[0]["finished_product_id"]
    else:
        fp = client.post("/api/finished-products", headers=admin_h,
                         json={"code": "FP-PLG-TEST", "name": "FP PLG test"})
        assert fp.status_code == 201, fp.text
        fp_id = fp.json()["finished_product_id"]
    pack = client.post("/api/batch-pack-lots", headers=admin_h, json={
        "from_bbt": bbt.json()["code"], "qty": 1000, "pack_lot_code": f"PKG-PLG-{suffix}",
        "finished_product_id": fp_id, "lot_no": f"LOT-PLG-{suffix}", "line": line_code,
        "pack_date": pack_date})
    assert pack.status_code == 201, pack.text
    pack_lot_id = pack.json()["pack_lot_id"]

    sh = client.put(f"/api/batch-pack-lots/{pack_lot_id}/shifts", headers=admin_h, json=shifts)
    assert sh.status_code == 200, sh.text
    return pack_lot_id


def test_lot_count_duration_and_idle_gap_computed_per_line(client, admin_h):
    line_code = "PLG-LINE-A"
    client.post("/api/lines", headers=admin_h, json={"code": line_code, "name": "PLG test line", "kind": "line"})

    # Lo 1: ca1 06:00-14:00 (8h), ca2 BO TRONG (khong khai) -> chi 1 doan tren bieu do, khong
    # lien tuc voi lo 2 (test "khoang khong chiet" giua cac doan).
    _build_pack_lot(client, admin_h, "A1", line_code, "2026-10-01T06:00:00Z", {
        "ca1_qty": 100, "ca1_start_at": "2026-10-01T06:00:00Z", "ca1_end_at": "2026-10-01T14:00:00Z"})
    # Lo 2 (cung line): ca1 22:00-23:00 CHI co start, THIEU end -> khong tinh vao doan nao (mirror
    # dieu kien ended_at property: thieu 1 trong 2 khong tinh).
    _build_pack_lot(client, admin_h, "A2", line_code, "2026-10-02T06:00:00Z", {
        "ca1_qty": 50, "ca1_start_at": "2026-10-02T22:00:00Z"})

    rep = client.get("/api/reports/pack-line-gantt",
                     params={"date_from": "2026-09-30", "date_to": "2026-10-03"}, headers=admin_h).json()
    row = next(l for l in rep["lines"] if l["line"] == line_code)
    # So lan chiet = SO LO (2), khong phai so doan ca hop le (chi 1).
    assert row["lot_count"] == 2
    assert row["total_duration_hours"] == 8.0
    assert len(row["segments"]) == 1
    assert row["segments"][0]["pack_lot_code"] == "PKG-PLG-A1"


def test_line_with_no_activity_in_window_still_listed_with_zero(client, admin_h):
    line_code = "PLG-LINE-EMPTY"
    client.post("/api/lines", headers=admin_h, json={"code": line_code, "name": "PLG empty line", "kind": "line"})
    rep = client.get("/api/reports/pack-line-gantt",
                     params={"date_from": "2026-01-01", "date_to": "2026-01-02"}, headers=admin_h).json()
    row = next(l for l in rep["lines"] if l["line"] == line_code)
    assert row["lot_count"] == 0
    assert row["total_duration_hours"] == 0
    assert row["segments"] == []
