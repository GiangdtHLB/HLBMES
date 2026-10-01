"""Test cờ "Loại bia không phải Dịch bia gốc" (BatchFilterOrder/BatchFilterLot.beer_type_mismatch)
+ "Loại sản phẩm" (category) tra chỉ tiêu Lọc — xem services/batch_pipeline.py::create_filter_order
(yêu cầu người dùng 2026-09-30): chọn 1 Loại bia KHÁC với Loại bia suy được từ chính Dịch bia của
(các) tank nguồn (kể cả không phối hay phối, kể cả khi nguồn lẫn nhiều Loại bia khác nhau không
suy ra được 1 giá trị) phải bị chặn (409) trừ khi xác nhận lại (confirm_beer_type_mismatch), và
lưu lại cờ mismatch=True để biết đây KHÔNG phải Dịch bia gốc thật.
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


def _make_batch(client, admin_h, batch_code):
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(v for v in vers if v["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                          "batch_code": batch_code, "planned_qty": 1000, "allow_shortage": True})
    assert b.status_code == 201, b.text
    return b.json()["batch_id"]


def _run_batch_to_completed(client, admin_h, batch_id, actual_qty=None):
    for target in ("ready", "running"):
        r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": target})
        assert r.status_code == 200, r.text
    if actual_qty is None:
        actual_qty = client.get(f"/api/batches/{batch_id}", headers=admin_h).json()["planned_qty"]
    aq = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": actual_qty})
    assert aq.status_code == 200, aq.text
    fin = client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={})
    assert fin.status_code == 200, fin.text
    r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "completed"})
    assert r.status_code == 200, r.text


def _make_tank(client, admin_h, batch_code, tank_code):
    batch_id = _make_batch(client, admin_h, batch_code)
    _run_batch_to_completed(client, admin_h, batch_id)
    r = client.post("/api/batch-tanks", headers=admin_h,
                    json={"batch_ids": [batch_id], "tank_code": tank_code})
    assert r.status_code == 201, r.text
    return r.json()


def _make_bbt_line(client, admin_h, suffix):
    r = client.post("/api/lines", headers=admin_h,
                    json={"code": f"BBT-MISMATCH-{suffix}", "name": f"BBT {suffix}", "kind": "tank_bbt"})
    assert r.status_code == 201, r.text
    return r.json()["code"]


def _other_beer_type_id(client, admin_h, suffix="A"):
    """Tạo 1 Loại bia + Dịch bia MỚI, khác hẳn Loại bia mặc định trong seed (Lager)."""
    bt = client.post("/api/beer-types", headers=admin_h,
                     json={"code": f"PILS-MM-{suffix}", "name": f"Pilsner Mismatch {suffix}"})
    assert bt.status_code == 201, bt.text
    beer_type_id = bt.json()["beer_type_id"]
    p = client.post("/api/products", headers=admin_h,
                    json={"code": f"BIA-PILS-MM-{suffix}", "name": f"Bia Pilsner Mismatch {suffix}", "uom": "L",
                          "beer_type_id": beer_type_id})
    assert p.status_code == 201, p.text
    return beer_type_id, p.json()["product_id"]


def _make_tank_with_product(client, admin_h, batch_code, tank_code, product_id):
    """Tạo tank bình thường (kế thừa Loại bia mặc định trong seed) rồi ĐỔI THẲNG product_id qua
    DB session sang 1 Dịch bia khác — mô phỏng tank chứa dịch thuộc Loại bia khác hẳn seed mặc
    định (mirror pattern direct-DB-write đã dùng ở test_batch_tank_gaps.py, vì tạo hẳn 1 Lệnh
    nấu/Version/Recipe mới cho 1 Loại bia thứ 2 tốn kém không cần thiết cho test này)."""
    tank = _make_tank(client, admin_h, batch_code, tank_code)
    from app.database import SessionLocal
    from app.models.batch_pipeline import BatchTank
    db = SessionLocal()
    t = db.get(BatchTank, tank["tank_id"])
    t.product_id = product_id
    db.commit()
    db.close()
    return tank


def test_khong_phoi_beer_type_mismatch_blocked_then_confirmed(client, admin_h):
    """Không phối (1 nguồn): chọn 1 Loại bia KHÁC Loại bia suy được từ chính tank nguồn -> 409
    trừ khi confirm_beer_type_mismatch=True, lúc đó tạo được và lưu cờ mismatch=True."""
    tank = _make_tank(client, admin_h, "101", "TANK-MM-01")
    other_beer_type_id, _ = _other_beer_type_id(client, admin_h, "01")

    blocked = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-MM-01", "beer_type_id": other_beer_type_id,
        "sources": [{"source_type": "tank", "source_tank_id": tank["tank_id"], "planned_v_dich_hl": 500}],
    })
    assert blocked.status_code == 409, blocked.text
    assert "không phải Dịch bia gốc" in blocked.json()["detail"]

    ok = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-MM-01", "beer_type_id": other_beer_type_id,
        "confirm_beer_type_mismatch": True,
        "sources": [{"source_type": "tank", "source_tank_id": tank["tank_id"], "planned_v_dich_hl": 500}],
    })
    assert ok.status_code == 201, ok.text
    assert ok.json()["beer_type_id"] == other_beer_type_id
    assert ok.json()["beer_type_mismatch"] is True


def test_khong_phoi_matching_beer_type_no_confirm_needed(client, admin_h):
    """Chọn ĐÚNG Loại bia suy được từ tank nguồn -> không cần confirm, mismatch=False."""
    tank = _make_tank(client, admin_h, "102", "TANK-MM-02")
    from app.database import SessionLocal
    from app.models.batch_pipeline import BatchTank
    from app.models.master import Product
    db = SessionLocal()
    t = db.get(BatchTank, tank["tank_id"])
    prod = db.get(Product, t.product_id)
    derived_beer_type_id = prod.beer_type_id
    db.close()

    ok = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-MM-02", "beer_type_id": derived_beer_type_id,
        "sources": [{"source_type": "tank", "source_tank_id": tank["tank_id"], "planned_v_dich_hl": 500}],
    })
    assert ok.status_code == 201, ok.text
    assert ok.json()["beer_type_mismatch"] is False


def test_phoi_2_loai_bia_khac_nhau_any_choice_needs_confirm(client, admin_h):
    """Phối 2 tank khác hẳn Loại bia (không suy ra được 1 giá trị chung) — để trống Loại bia vẫn
    tạo được bình thường (không chặn), nhưng CHỌN 1 trong 2 Loại bia đó vẫn phải xác nhận lại vì
    không đại diện đúng cho cả mẻ phối (yêu cầu người dùng 2026-09-30: "chọn 1 trong 2 loại bia
    đó...kể cả lọc phối hoặc không phối, thì sẽ đều có cảnh báo")."""
    tank_a = _make_tank(client, admin_h, "103", "TANK-MM-03A")
    other_beer_type_id, other_product_id = _other_beer_type_id(client, admin_h, "03")
    tank_b = _make_tank_with_product(client, admin_h, "104", "TANK-MM-03B", other_product_id)

    left_blank = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-MM-03-BLANK",
        "sources": [{"source_type": "tank", "source_tank_id": tank_a["tank_id"], "planned_v_dich_hl": 500},
                    {"source_type": "tank", "source_tank_id": tank_b["tank_id"], "planned_v_dich_hl": 500}],
    })
    assert left_blank.status_code == 201, left_blank.text
    assert left_blank.json()["beer_type_id"] is None
    assert left_blank.json()["beer_type_mismatch"] is False

    blocked = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-MM-03-PICK", "beer_type_id": other_beer_type_id,
        "sources": [{"source_type": "tank", "source_tank_id": tank_a["tank_id"], "planned_v_dich_hl": 500},
                    {"source_type": "tank", "source_tank_id": tank_b["tank_id"], "planned_v_dich_hl": 500}],
    })
    assert blocked.status_code == 409, blocked.text

    confirmed = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-MM-03-PICK", "beer_type_id": other_beer_type_id,
        "confirm_beer_type_mismatch": True,
        "sources": [{"source_type": "tank", "source_tank_id": tank_a["tank_id"], "planned_v_dich_hl": 500},
                    {"source_type": "tank", "source_tank_id": tank_b["tank_id"], "planned_v_dich_hl": 500}],
    })
    assert confirmed.status_code == 201, confirmed.text
    assert confirmed.json()["beer_type_mismatch"] is True


def test_filter_lot_inherits_category_and_mismatch_flag(client, admin_h):
    """Lô lọc tạo từ Lệnh lọc phải kế thừa NGUYÊN category + beer_type_mismatch của lệnh gốc,
    và chỉ tiêu Lọc phải tra đúng theo category đó (mirror finished_product_id/beer_type_id đã
    kế thừa từ trước) — xem services/batch_pipeline.py::draw_from_filter_order."""
    tank = _make_tank(client, admin_h, "105", "TANK-MM-04")
    from app.database import SessionLocal
    from app.models.batch_pipeline import BatchTank
    from app.models.master import Product
    db = SessionLocal()
    t = db.get(BatchTank, tank["tank_id"])
    prod = db.get(Product, t.product_id)
    beer_type_id = prod.beer_type_id
    db.close()

    # 2 nhóm chỉ tiêu Lọc khác nhau cho CÙNG Loại bia — 1 gán category="Bia lon", 1 áp dụng chung
    # (category rỗng) — mirror ví dụ thực tế Legend keg/lon,chai của người dùng.
    param_lon = client.post("/api/qc/parameters", headers=admin_h,
                            json={"code": "CT_MM_LON", "name": "Chỉ tiêu lon", "lsl": 1, "usl": 10})
    assert param_lon.status_code == 201, param_lon.text
    group_lon = client.post("/api/qc/groups", headers=admin_h,
                            json={"code": "GRP_MM_LON", "name": "Nhóm lon"})
    assert group_lon.status_code == 201, group_lon.text
    group_lon_id = group_lon.json()["group_id"]
    it = client.post(f"/api/qc/groups/{group_lon_id}/items", headers=admin_h,
                     json={"param_id": param_lon.json()["param_id"], "mandatory": True})
    assert it.status_code == 201, it.text

    param_chung = client.post("/api/qc/parameters", headers=admin_h,
                              json={"code": "CT_MM_CHUNG", "name": "Chỉ tiêu chung", "lsl": 1, "usl": 10})
    assert param_chung.status_code == 201, param_chung.text
    group_chung = client.post("/api/qc/groups", headers=admin_h,
                              json={"code": "GRP_MM_CHUNG", "name": "Nhóm chung"})
    assert group_chung.status_code == 201, group_chung.text
    group_chung_id = group_chung.json()["group_id"]
    it2 = client.post(f"/api/qc/groups/{group_chung_id}/items", headers=admin_h,
                      json={"param_id": param_chung.json()["param_id"], "mandatory": True})
    assert it2.status_code == 201, it2.text

    link_lon = client.post("/api/qc/stage-groups", headers=admin_h,
                           json={"stage": "loc", "beer_type_id": beer_type_id, "category": "Bia lon",
                                "group_id": group_lon_id, "mandatory": True})
    assert link_lon.status_code == 201, link_lon.text
    link_chung = client.post("/api/qc/stage-groups", headers=admin_h,
                             json={"stage": "loc", "beer_type_id": beer_type_id,
                                  "group_id": group_chung_id, "mandatory": True})
    assert link_chung.status_code == 201, link_chung.text

    order = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-MM-04", "beer_type_id": beer_type_id, "category": "Bia lon",
        "sources": [{"source_type": "tank", "source_tank_id": tank["tank_id"], "planned_v_dich_hl": 900}],
    })
    assert order.status_code == 201, order.text
    assert order.json()["category"] == "Bia lon"
    order_id = order.json()["order_id"]

    fl = client.post(f"/api/batch-filter-orders/{order_id}/filter-lots", headers=admin_h,
                     json={"filter_lot_code": "FLOT-MM-04", "to_bbt": _make_bbt_line(client, admin_h, "MM04")})
    assert fl.status_code == 201, fl.text
    fl_body = fl.json()
    assert fl_body["category"] == "Bia lon"
    assert fl_body["beer_type_mismatch"] is False

    qc = client.get("/api/brewing/qc-status", headers=admin_h, params={
        "stage": "loc", "scope_type": "batch_filter_lot", "scope_id": fl_body["filter_lot_id"],
        "beer_type_id": beer_type_id, "category": "Bia lon",
    })
    assert qc.status_code == 200, qc.text
    codes = {p["code"] for p in qc.json()["required"]}
    assert "CT_MM_LON" in codes
    assert "CT_MM_CHUNG" in codes
