"""Test "Gợi ý cấp liệu" (suggest_dispense) cho 1 mẻ nấu (BatchExecution) — xem trước vật tư
nào còn THIẾU theo Định mức (BOM, đã scale theo SL kế hoạch của mẻ) và lô nào (FEFO, CHỈ ở Kho
phân xưởng) sẽ được chọn để bù đủ — CHỈ TÍNH, không trừ tồn cho tới khi áp dụng thật qua
POST /dispense/{batch_id} với đúng lot_id/quantity lấy từ gợi ý. Xem services/dispense.py::
suggest_dispense.
"""

import os
import tempfile
from datetime import timedelta

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["MES_DATABASE_URL"] = f"sqlite:///{_TMP.name}"
os.environ["MES_DEV_HEADER_AUTH"] = "0"
os.environ["MES_RL_ENABLED"] = "0"
os.environ["MES_ADMIN_PASSWORD"] = "AdminTest123"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import seed as seed_mod
from app.common import new_id, utcnow


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


def _new_material(client, admin_h, suffix):
    r = client.post("/api/materials", headers=admin_h,
                    json={"code": f"SUG-{suffix}", "name": f"Vật tư test {suffix}", "uom": "kg"})
    assert r.status_code == 201, r.text
    return r.json()["material_id"], r.json()["code"]


def _receive_workshop_lot(client, admin_h, material_id, qty, days_to_expiry):
    r = client.post("/api/warehouse/receive", headers=admin_h, json={
        "material_id": material_id, "quantity": qty, "uom": "kg",
        "location": "Kho phân xưởng",
        "expiry": (utcnow() + timedelta(days=days_to_expiry)).isoformat(),
    })
    assert r.status_code == 200, r.text
    return r.json()["lot_id"]


def _recipe_version(client, admin_h, suffix, material_code, qty, base_qty=100):
    bt = client.post("/api/beer-types", headers=admin_h,
                     json={"code": f"BT-SUG-{suffix}", "name": f"Loại test {suffix}"})
    assert bt.status_code == 201, bt.text
    r = client.post("/api/recipes", headers=admin_h,
                    json={"code": f"CT-SUG-{suffix}", "name": "Test recipe gợi ý cấp liệu",
                         "beer_type_id": bt.json()["beer_type_id"]})
    assert r.status_code == 201, r.text
    recipe_id = r.json()["recipe_id"]
    prod = client.post("/api/products", headers=admin_h,
                       json={"code": f"PRD-SUG-{suffix}", "name": f"Dịch test {suffix}", "uom": "L",
                            "beer_type_id": bt.json()["beer_type_id"]})
    assert prod.status_code == 201, prod.text
    v = client.post(f"/api/recipes/{recipe_id}/versions", headers=admin_h,
                    json={"base_qty": base_qty, "base_uom": "L", "product_id": prod.json()["product_id"],
                         "materials": [{"material_code": material_code, "qty": qty, "uom": "kg"}]})
    assert v.status_code == 201, v.text
    version_id = v.json()["version_id"]
    for target in ("review", "approved", "effective"):
        t = client.post(f"/api/recipes/versions/{version_id}/transition", headers=admin_h,
                        json={"target": target})
        assert t.status_code == 200, t.text
    return version_id


def _new_batch(client, admin_h, version_id, planned_qty, suffix, allow_shortage=False):
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": version_id,
                         "planned_qty": planned_qty,   # batch_code: để tự sinh (giờ bắt buộc số nguyên)
                         "allow_shortage": allow_shortage})
    assert b.status_code == 201, b.text
    return b.json()["batch_id"]


def test_suggest_picks_fefo_across_two_lots_in_workshop_only(client, admin_h):
    material_id, code = _new_material(client, admin_h, "FEFO01")
    lot_soon = _receive_workshop_lot(client, admin_h, material_id, 6, days_to_expiry=10)   # hết hạn sớm hơn
    lot_later = _receive_workshop_lot(client, admin_h, material_id, 10, days_to_expiry=30)
    # 1 lô cùng vật tư nhưng KHÔNG ở Kho phân xưởng -> không được gợi ý dùng dù còn hạn xa hơn.
    company_r = client.post("/api/warehouse/receive", headers=admin_h, json={
        "material_id": material_id, "quantity": 999, "uom": "kg", "location": "Kho công ty",
        "expiry": (utcnow() + timedelta(days=1)).isoformat(),
    })
    assert company_r.status_code == 200, company_r.text

    version_id = _recipe_version(client, admin_h, "FEFO01", code, qty=10, base_qty=100)
    batch_id = _new_batch(client, admin_h, version_id, planned_qty=100, suffix="FEFO01")

    sug1 = client.get(f"/api/dispense/{batch_id}/suggest", headers=admin_h).json()
    assert len(sug1["lines"]) == 1
    line = sug1["lines"][0]
    assert line["material_code"] == code
    assert line["need"] == 10.0
    assert line["shortfall"] == 0.0
    assert [p["lot_id"] for p in line["picks"]] == [lot_soon, lot_later]   # FEFO: hết hạn sớm trước
    assert line["picks"][0]["quantity"] == 6.0 and line["picks"][1]["quantity"] == 4.0
    # Tồn hiện tại theo kho — tham khảo, KHÔNG ảnh hưởng gợi ý (vốn chỉ xét Kho phân xưởng).
    assert line["stock_company"] == 999.0
    assert line["stock_workshop"] == 16.0   # 6 + 10

    # Gọi lại lần 2 phải giống hệt -> suggest KHÔNG trừ tồn (chỉ tính).
    sug2 = client.get(f"/api/dispense/{batch_id}/suggest", headers=admin_h).json()
    assert sug2 == sug1

    lots_before = {l["lot_id"]: l["quantity"] for l in client.get("/api/lots", headers=admin_h).json()}
    assert lots_before[lot_soon] == 6.0 and lots_before[lot_later] == 10.0

    # Áp dụng đúng gợi ý -> trừ tồn thật theo đúng lô/số lượng đã gợi ý.
    apply = client.post(f"/api/dispense/{batch_id}", headers=admin_h, json={
        "lines": [{"material_code": code, "lot_id": p["lot_id"], "quantity": p["quantity"]}
                 for p in line["picks"]],
    })
    assert apply.status_code == 200, apply.text

    lots_after = {l["lot_id"]: l["quantity"] for l in client.get("/api/lots", headers=admin_h).json()}
    assert lots_after[lot_soon] == 0.0 and lots_after[lot_later] == 6.0

    bom = client.get(f"/api/batches/{batch_id}/bom", headers=admin_h).json()
    line_bom = next(l for l in bom["lines"] if l["material_code"] == code)
    assert line_bom["actual"] == 10.0 and line_bom["diff"] == 0.0 and line_bom["status"] == "dat"

    # Đã đủ định mức -> gợi ý không còn dòng nào cho vật tư này nữa.
    sug3 = client.get(f"/api/dispense/{batch_id}/suggest", headers=admin_h).json()
    assert sug3["lines"] == []


def test_suggest_reports_shortfall_when_workshop_stock_insufficient(client, admin_h):
    material_id, code = _new_material(client, admin_h, "SHORT01")
    lot_id = _receive_workshop_lot(client, admin_h, material_id, 3, days_to_expiry=10)

    version_id = _recipe_version(client, admin_h, "SHORT01", code, qty=10, base_qty=100)
    batch_id = _new_batch(client, admin_h, version_id, planned_qty=100, suffix="SHORT01", allow_shortage=True)

    sug = client.get(f"/api/dispense/{batch_id}/suggest", headers=admin_h).json()
    line = sug["lines"][0]
    assert line["need"] == 10.0
    assert line["picks"] == [{"lot_id": lot_id, "lot_code": line["picks"][0]["lot_code"],
                              "quantity": 3.0, "uom": "kg", "expiry": line["picks"][0]["expiry"]}]
    assert line["shortfall"] == 7.0


def test_suggest_exposes_planned_norm_and_alternatives(client, admin_h):
    material_id, code = _new_material(client, admin_h, "ALT01")
    lot_a = _receive_workshop_lot(client, admin_h, material_id, 6, days_to_expiry=10)
    lot_b = _receive_workshop_lot(client, admin_h, material_id, 10, days_to_expiry=30)
    version_id = _recipe_version(client, admin_h, "ALT01", code, qty=10, base_qty=100)
    batch_id = _new_batch(client, admin_h, version_id, planned_qty=100, suffix="ALT01")

    sug = client.get(f"/api/dispense/{batch_id}/suggest", headers=admin_h).json()
    line = sug["lines"][0]
    assert line["planned"] == 10.0
    assert {a["lot_id"] for a in line["alternatives"]} == {lot_a, lot_b}


def test_apply_non_fifo_lot_requires_reason_then_succeeds_with_it(client, admin_h):
    material_id, code = _new_material(client, admin_h, "NONFIFO01")
    lot_soon = _receive_workshop_lot(client, admin_h, material_id, 20, days_to_expiry=10)
    lot_later = _receive_workshop_lot(client, admin_h, material_id, 20, days_to_expiry=30)
    version_id = _recipe_version(client, admin_h, "NONFIFO01", code, qty=5, base_qty=100)
    batch_id = _new_batch(client, admin_h, version_id, planned_qty=100, suffix="NONFIFO01")

    # Chọn lô hết hạn XA HƠN (lot_later) trong khi lot_soon (FEFO gợi ý) còn nguyên tồn -> lệch FIFO.
    no_reason = client.post(f"/api/dispense/{batch_id}", headers=admin_h,
                            json={"lines": [{"material_code": code, "lot_id": lot_later, "quantity": 5}]})
    assert no_reason.status_code == 409, no_reason.text
    assert "lý do" in no_reason.json()["detail"]

    lots_untouched = {l["lot_id"]: l["quantity"] for l in client.get("/api/lots", headers=admin_h).json()}
    assert lots_untouched[lot_soon] == 20.0 and lots_untouched[lot_later] == 20.0   # chưa trừ gì (bị chặn trước khi trừ)

    ok = client.post(f"/api/dispense/{batch_id}", headers=admin_h,
                     json={"lines": [{"material_code": code, "lot_id": lot_later, "quantity": 5,
                                     "reason": "Lô lot_soon đã đặt trước cho mẻ khác"}]})
    assert ok.status_code == 200, ok.text

    lots_after = {l["lot_id"]: l["quantity"] for l in client.get("/api/lots", headers=admin_h).json()}
    assert lots_after[lot_soon] == 20.0 and lots_after[lot_later] == 15.0

    hist = client.get(f"/api/dispense?batch_id={batch_id}", headers=admin_h).json()
    line = hist[0]["lines"][0]
    assert line["fifo_ok"] is False and line["reason"] == "Lô lot_soon đã đặt trước cho mẻ khác"


def test_dispense_all_or_nothing_across_multiple_materials(client, admin_h):
    ok_id, ok_code = _new_material(client, admin_h, "AON_OK")
    short_id, short_code = _new_material(client, admin_h, "AON_SHORT")
    ok_lot = _receive_workshop_lot(client, admin_h, ok_id, 50, days_to_expiry=10)
    short_lot = _receive_workshop_lot(client, admin_h, short_id, 3, days_to_expiry=10)

    bt = client.post("/api/beer-types", headers=admin_h, json={"code": "BT-AON", "name": "Loại AON"})
    assert bt.status_code == 201, bt.text
    recipe = client.post("/api/recipes", headers=admin_h,
                        json={"code": "CT-AON", "name": "Test AON", "beer_type_id": bt.json()["beer_type_id"]})
    assert recipe.status_code == 201, recipe.text
    prod = client.post("/api/products", headers=admin_h,
                       json={"code": "PRD-AON", "name": "Dich AON", "uom": "L",
                            "beer_type_id": bt.json()["beer_type_id"]})
    assert prod.status_code == 201, prod.text
    v = client.post(f"/api/recipes/{recipe.json()['recipe_id']}/versions", headers=admin_h,
                    json={"base_qty": 100, "base_uom": "L", "product_id": prod.json()["product_id"],
                         "materials": [{"material_code": ok_code, "qty": 20, "uom": "kg"},
                                      {"material_code": short_code, "qty": 10, "uom": "kg"}]})
    assert v.status_code == 201, v.text
    version_id = v.json()["version_id"]
    for target in ("review", "approved", "effective"):
        t = client.post(f"/api/recipes/versions/{version_id}/transition", headers=admin_h, json={"target": target})
        assert t.status_code == 200, t.text
    batch_id = _new_batch(client, admin_h, version_id, planned_qty=100, suffix="AON01", allow_shortage=True)

    apply = client.post(f"/api/dispense/{batch_id}", headers=admin_h, json={
        "lines": [{"material_code": ok_code, "quantity": 20},
                 {"material_code": short_code, "quantity": 10}],
    })
    assert apply.status_code == 409, apply.text

    lots = {l["lot_id"]: l["quantity"] for l in client.get("/api/lots", headers=admin_h).json()}
    assert lots[ok_lot] == 50.0   # KHÔNG bị trừ dù dòng này đủ tồn -> all-or-nothing
    assert lots[short_lot] == 3.0

    hist = client.get(f"/api/dispense?batch_id={batch_id}", headers=admin_h).json()
    assert hist == []   # không tạo phiếu cấp liệu nào


def test_suggest_includes_released_lots_not_just_available(client, admin_h):
    """Lô trạng thái "released" (VD đã duyệt chỉ tiêu chất lượng ở Kho công ty và chuyển tới
    Kho phân xưởng — xem frontend "Xem tồn kho") PHẢI được gợi ý cấp liệu như lô "available",
    mirror đúng warehouse.py::stock_on_hand (coi cả 2 trạng thái là "khả dụng"). Trước đây
    services/dispense.py::_fefo_lots chỉ chọn status=="available", bỏ sót lô "released" dù
    tồn kho thật vẫn còn — khiến gợi ý báo "thiếu" sai dù còn hàng."""
    from app.database import SessionLocal
    from app.models.materials import MaterialLot

    material_id, code = _new_material(client, admin_h, "RELSTAT01")
    r = client.post("/api/warehouse/receive", headers=admin_h, json={
        "material_id": material_id, "quantity": 30, "uom": "kg", "location": "Kho phân xưởng"})
    assert r.status_code == 200, r.text
    lot_id = r.json()["lot_id"]

    db = SessionLocal()
    lot = db.get(MaterialLot, lot_id)
    lot.status = "released"
    db.commit()
    db.close()

    version_id = _recipe_version(client, admin_h, "RELSTAT01", code, qty=10, base_qty=100)
    batch_id = _new_batch(client, admin_h, version_id, planned_qty=100, suffix="RELSTAT01")

    sug = client.get(f"/api/dispense/{batch_id}/suggest", headers=admin_h).json()
    line = sug["lines"][0]
    assert line["stock_workshop"] == 30.0
    assert [p["lot_id"] for p in line["picks"]] == [lot_id]
    assert line["shortfall"] == 0.0

    avail = client.get(
        f"/api/batches/availability?recipe_version_id={version_id}&planned_qty=100",
        headers=admin_h).json()
    assert avail["rows"][0]["available"] == 30.0
    assert avail["rows"][0]["ok"] is True


def test_suggest_expired_workshop_lot_excluded(client, admin_h):
    material_id, code = _new_material(client, admin_h, "EXP01")
    # Lô đã hết hạn (expiry trong quá khứ) không được gợi ý.
    expired = client.post("/api/warehouse/receive", headers=admin_h, json={
        "material_id": material_id, "quantity": 50, "uom": "kg", "location": "Kho phân xưởng",
        "expiry": (utcnow() - timedelta(days=1)).isoformat(),
    })
    assert expired.status_code == 200, expired.text
    fresh_lot = _receive_workshop_lot(client, admin_h, material_id, 20, days_to_expiry=15)

    version_id = _recipe_version(client, admin_h, "EXP01", code, qty=5, base_qty=100)
    batch_id = _new_batch(client, admin_h, version_id, planned_qty=100, suffix="EXP01")

    sug = client.get(f"/api/dispense/{batch_id}/suggest", headers=admin_h).json()
    line = sug["lines"][0]
    assert [p["lot_id"] for p in line["picks"]] == [fresh_lot]
    assert line["shortfall"] == 0.0
