"""Test dòng BOM (Công thức) khai qua Nhóm vật tư thay thế (alt_group_code, models/master.py::
MaterialAltGroup) thay vì 1 material_code cụ thể — trước đây bom.py::compare_batch/availability/
availability_with_alternates/ceiling_for_material chỉ đọc thẳng m.get("material_code") nên dòng
kiểu này luôn ra "Vật tư" RỖNG (material_code=None) ở bảng Định mức↔Thực tế/Gợi ý cấp liệu, và
services/dispense.py không tìm được lô nào để cấp (Material.code == group_code không khớp gì).
Xem services/bom.py::_expand_materials/codes_for_dispense, services/dispense.py::_fefo_lots.
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
from app.common import utcnow


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
                    json={"code": f"AG-{suffix}", "name": f"Vật tư nhóm {suffix}", "uom": "kg"})
    assert r.status_code == 201, r.text
    return r.json()["material_id"], r.json()["code"]


def _receive_workshop_lot(client, admin_h, material_id, qty, days_to_expiry=30):
    r = client.post("/api/warehouse/receive", headers=admin_h, json={
        "material_id": material_id, "quantity": qty, "uom": "kg",
        "location": "Kho phân xưởng",
        "expiry": (utcnow() + timedelta(days=days_to_expiry)).isoformat(),
    })
    assert r.status_code == 200, r.text
    return r.json()["lot_id"]


@pytest.fixture(scope="module")
def group(client, admin_h):
    """Nhóm vật tư thay thế "Malt test" gồm 2 mã cụ thể — dòng BOM chỉ khai qua nhóm này,
    không quan tâm xuất mã nào (mirror "Malt Úc rời/bao" ở models/master.py::MaterialAltGroup)."""
    mid1, code1 = _new_material(client, admin_h, "M1")
    mid2, code2 = _new_material(client, admin_h, "M2")
    g = client.post("/api/material-alt-groups", headers=admin_h, json={
        "code": "AG-GROUP-01", "name": "Malt test (nhóm)", "member_material_ids": [mid1, mid2],
        "unit": "kg", "selection_mode": "single"})
    assert g.status_code == 201, g.text
    return {"group_code": "AG-GROUP-01", "mid1": mid1, "code1": code1, "mid2": mid2, "code2": code2}


def _recipe_version_group(client, admin_h, suffix, group_code, qty, base_qty=100):
    bt = client.post("/api/beer-types", headers=admin_h,
                     json={"code": f"BT-AG-{suffix}", "name": f"Loại AG {suffix}"})
    assert bt.status_code == 201, bt.text
    r = client.post("/api/recipes", headers=admin_h,
                    json={"code": f"CT-AG-{suffix}", "name": "Test recipe alt group",
                         "beer_type_id": bt.json()["beer_type_id"]})
    assert r.status_code == 201, r.text
    recipe_id = r.json()["recipe_id"]
    prod = client.post("/api/products", headers=admin_h,
                       json={"code": f"PRD-AG-{suffix}", "name": f"Dịch AG {suffix}", "uom": "L",
                            "beer_type_id": bt.json()["beer_type_id"]})
    assert prod.status_code == 201, prod.text
    v = client.post(f"/api/recipes/{recipe_id}/versions", headers=admin_h,
                    json={"base_qty": base_qty, "base_uom": "L", "product_id": prod.json()["product_id"],
                         "materials": [{"alt_group_code": group_code, "qty": qty, "uom": "kg", "tol_pct": 0}]})
    assert v.status_code == 201, v.text
    version_id = v.json()["version_id"]
    for target in ("review", "approved", "effective"):
        t = client.post(f"/api/recipes/versions/{version_id}/transition", headers=admin_h,
                        json={"target": target})
        assert t.status_code == 200, t.text
    return version_id


def _new_batch(client, admin_h, version_id, planned_qty, suffix, allow_shortage=True):
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": version_id,
                         "planned_qty": planned_qty,   # batch_code: để tự sinh (giờ bắt buộc số nguyên)
                         "allow_shortage": allow_shortage})
    assert b.status_code == 201, b.text
    return b.json()["batch_id"]


def test_bom_line_shows_group_name_not_blank(client, admin_h, group):
    version_id = _recipe_version_group(client, admin_h, "BOM01", group["group_code"], qty=10)
    batch_id = _new_batch(client, admin_h, version_id, planned_qty=100, suffix="BOM01")

    bom = client.get(f"/api/batches/{batch_id}/bom", headers=admin_h).json()
    assert len(bom["lines"]) == 1
    line = bom["lines"][0]
    assert line["material_code"] == group["group_code"]   # KHÔNG còn None/rỗng
    assert line["material_name"] == "Malt test (nhóm)"
    assert line["planned"] == 10.0


def test_suggest_and_dispense_across_group_members(client, admin_h, group):
    """Nhóm "dùng nhiều mã cùng lúc" (bare group, không member_qty) hiện THÀNH 2 DÒNG riêng
    (1/thành viên) trong gợi ý — để người dùng tự do phân bổ số lượng/lô qua từng mã — vẫn gợi
    ý trước theo FIFO chung (gộp tồn mọi thành viên), tổng 2 dòng không vượt định mức chung."""
    # Chỉ mã thành viên thứ 2 có tồn ở Kho phân xưởng — gợi ý vẫn phải tìm ra được (group-aware).
    lot_id = _receive_workshop_lot(client, admin_h, group["mid2"], 15)
    version_id = _recipe_version_group(client, admin_h, "SUG01", group["group_code"], qty=10)
    batch_id = _new_batch(client, admin_h, version_id, planned_qty=100, suffix="SUG01")

    sug = client.get(f"/api/dispense/{batch_id}/suggest", headers=admin_h).json()
    assert len(sug["lines"]) == 2
    codes = {l["material_code"] for l in sug["lines"]}
    assert codes == {group["code1"], group["code2"]}
    line1 = next(l for l in sug["lines"] if l["material_code"] == group["code1"])
    line2 = next(l for l in sug["lines"] if l["material_code"] == group["code2"])
    assert line1["group_code"] == group["group_code"] == line2["group_code"]
    assert line1["need"] == 10.0 == line2["need"]   # định mức chung của cả nhóm, hiện trên cả 2 dòng
    assert line1["shortfall"] == 0.0 == line2["shortfall"]   # đủ tồn chung -> cả 2 dòng cùng "đủ"
    assert line1["picks"] == []   # mã 1 không có tồn -> FIFO chung tự động phân hết cho mã 2
    assert [p["lot_id"] for p in line2["picks"]] == [lot_id]

    apply = client.post(f"/api/dispense/{batch_id}", headers=admin_h, json={
        "lines": [{"material_code": group["group_code"], "lot_id": lot_id, "quantity": 10}]})
    assert apply.status_code == 200, apply.text

    lots = {l["lot_id"]: l["quantity"] for l in client.get("/api/lots", headers=admin_h).json()}
    assert lots[lot_id] == 5.0

    # Sổ cái cấp liệu ghi mã THẬT (code2), không phải mã nhóm.
    hist = client.get(f"/api/dispense?batch_id={batch_id}", headers=admin_h).json()
    assert hist[0]["lines"][0]["material_code"] == group["code2"]

    # Bảng Định mức↔Thực tế (màn Cấp liệu) cũng hiện đúng mã THẬT + mã lô + FIFO, không phải mã
    # nhóm (xem services/dispense.py::batch_dispense_summary).
    summary = client.get(f"/api/dispense/{batch_id}/summary", headers=admin_h).json()
    assert len(summary) == 1
    row = summary[0]
    assert row["material_code"] == group["code2"]
    assert row["actual"] == 10.0
    assert row["lot_codes"] == [hist[0]["lines"][0]["lot_code"]]
    assert row["fifo_ok"] is True
    assert row["planned"] == 10.0

    bom = client.get(f"/api/batches/{batch_id}/bom", headers=admin_h).json()
    line_bom = bom["lines"][0]
    assert line_bom["actual"] == 10.0 and line_bom["status"] == "dat"


def test_dispense_consumes_from_either_member_and_ceiling_shared_across_group(client, admin_h, group):
    """Ngưỡng vượt định mức BOM tính CHUNG cho cả nhóm — tiêu thụ 6kg qua mã 1 rồi cố tiêu thụ
    thêm 6kg qua mã 2 (tổng 12kg > định mức 10kg) phải bị chặn, dù mỗi mã riêng lẻ mới dùng 6kg."""
    lot1 = _receive_workshop_lot(client, admin_h, group["mid1"], 20)
    lot2 = _receive_workshop_lot(client, admin_h, group["mid2"], 20)
    version_id = _recipe_version_group(client, admin_h, "CEIL01", group["group_code"], qty=10)
    batch_id = _new_batch(client, admin_h, version_id, planned_qty=100, suffix="CEIL01")

    first = client.post(f"/api/batches/{batch_id}/consume", headers=admin_h,
                        json={"lot_id": lot1, "quantity": 6})
    assert first.status_code == 200, first.text

    over = client.post(f"/api/batches/{batch_id}/consume", headers=admin_h,
                       json={"lot_id": lot2, "quantity": 6})
    assert over.status_code == 409, over.text
    assert "Vượt định mức" in over.json()["detail"]

    allowed = client.post(f"/api/batches/{batch_id}/consume", headers=admin_h,
                          json={"lot_id": lot2, "quantity": 6, "allow_over": True})
    assert allowed.status_code == 200, allowed.text


def test_adjust_actual_refunds_across_group_members(client, admin_h, group):
    lot1 = _receive_workshop_lot(client, admin_h, group["mid1"], 20)
    version_id = _recipe_version_group(client, admin_h, "ADJ01", group["group_code"], qty=10)
    batch_id = _new_batch(client, admin_h, version_id, planned_qty=100, suffix="ADJ01")

    consume = client.post(f"/api/batches/{batch_id}/consume", headers=admin_h,
                          json={"lot_id": lot1, "quantity": 8})
    assert consume.status_code == 200, consume.text

    # Sửa Thực tế (qua mã NHÓM) về 3kg -> phải hoàn lại đúng 5kg cho lot1 (đã tiêu thụ qua mã 1).
    adj = client.post(f"/api/dispense/{batch_id}/adjust", headers=admin_h, json={
        "material_code": group["group_code"], "new_actual": 3, "reason": "test hoàn lại qua nhóm"})
    assert adj.status_code == 200, adj.text

    lots = {l["lot_id"]: l["quantity"] for l in client.get("/api/lots", headers=admin_h).json()}
    assert lots[lot1] == 17.0   # 20 - 8 + 5

    bom = client.get(f"/api/batches/{batch_id}/bom", headers=admin_h).json()
    assert bom["lines"][0]["actual"] == 3.0
