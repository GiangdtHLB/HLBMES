"""Kiểm tra CẢ CHUỖI thật: Nhập kho (Kho công ty) → Xuất theo đề nghị (Kho công ty → Kho phân
xưởng, dùng lại đúng lot_code — xem services/warehouse.py::_transfer_lot) → Cấp liệu vào mẻ
sản xuất (Nấu) → NVL dùng cho Lô lọc → NVL dùng cho Lô thành phẩm (Chiết).

Câu hỏi người dùng đặt ra 2026-09-14: "có sinh ra lô mới không" ở TỪNG bước tiêu thụ (Cấp liệu/
Lọc/Chiết) — không phải chỉ riêng bước điều chuyển kho. Test này xác nhận: CHỈ bước điều chuyển
(Xuất theo đề nghị) tạo thêm 1 dòng MaterialLot (dùng lại cùng lot_code, không phải mã mới) — 3
bước tiêu thụ sau đó (dispense/add_filter_lot_material/add_pack_lot_material) chỉ trừ dần
quantity trên ĐÚNG dòng đó, KHÔNG tạo thêm dòng MaterialLot nào, dù lô nào cả năm."""

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


def _lots_by_code(client, admin_h, lot_code):
    lots = client.get("/api/lots?limit=5000", headers=admin_h).json()
    return [l for l in lots if l["lot_code"] == lot_code]


def _make_batch(client, admin_h, batch_code=None):
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(x for x in vers if x["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                          "batch_code": batch_code, "planned_qty": 1000, "allow_shortage": True})
    assert b.status_code == 201, b.text
    return b.json()["batch_id"]


def _run_batch_to_completed(client, admin_h, batch_id, actual_qty=None):
    for target in ("ready", "running"):
        client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": target})
    if actual_qty is None:
        actual_qty = client.get(f"/api/batches/{batch_id}", headers=admin_h).json()["planned_qty"]
    client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": actual_qty})
    client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={})
    return client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "completed"})


def _finish_only_source(client, admin_h, filter_lot_id, v_drawn=900):
    src = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()[0]
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    fin = client.put(f"/api/batch-filter-lots/batches/{batches[0]['batch_link_id']}/finish", headers=admin_h,
                     json={"draws": [{"source_link_id": src["link_id"], "dich_nha_hl": v_drawn}],
                          "nuoc_bai_khi_hl": 0})
    assert fin.status_code == 200, fin.text


def _make_filter_lot(client, admin_h, suffix):
    tank_batch_id = _make_batch(client, admin_h)
    _run_batch_to_completed(client, admin_h, tank_batch_id)
    tank = client.post("/api/batch-tanks", headers=admin_h,
                       json={"batch_ids": [tank_batch_id], "tank_code": f"TANK-{suffix}"})
    assert tank.status_code == 201, tank.text
    bbt = client.post("/api/lines", headers=admin_h,
                      json={"code": f"BBT-{suffix}", "name": f"Tank TP {suffix}", "kind": "tank_bbt"})
    assert bbt.status_code == 201, bbt.text
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": f"FLOT-{suffix}", "to_bbt": bbt.json()["code"],
        "sources": [{"source_type": "tank", "source_tank_id": tank.json()["tank_id"]}]})
    assert draw.status_code == 201, draw.text
    return draw.json()["filter_lot_id"]


def test_full_chain_receive_request_dispense_filter_pack_no_extra_lot(client, admin_h):
    mat_code = "E2ECHAIN01"
    mat = client.post("/api/materials", headers=admin_h,
                      json={"code": mat_code, "name": "E2E Chain Test", "uom": "kg", "category": "other"})
    assert mat.status_code == 201, mat.text
    material_id = mat.json()["material_id"]
    lot_code = "LOT-E2ECHAIN01"

    # 1. Nhập kho — Kho công ty, 100kg.
    recv = client.post("/api/warehouse/receive", headers=admin_h,
                       json={"lot_code": lot_code, "material_id": material_id, "quantity": 100, "uom": "kg"})
    assert recv.status_code == 200, recv.text
    company_lot_id = recv.json()["lot_id"]

    # 2. Đề nghị nhận kho — 50kg.
    req = client.post("/api/warehouse/requests", headers=admin_h,
                      json={"lines": [{"material_id": material_id, "quantity": 50, "uom": "kg"}]})
    assert req.status_code == 201, req.text
    request_id, line_id = req.json()["request_id"], req.json()["lines"][0]["line_id"]

    # 3. Xuất theo đề nghị — 50kg < 100kg tồn -> TÁCH dòng mới nhưng DÙNG LẠI đúng lot_code.
    ful = client.post(f"/api/warehouse/requests/{request_id}/lines/{line_id}/fulfill",
                      headers=admin_h, json={"lot_id": company_lot_id, "quantity": 50, "location_to": "Kho phân xưởng"})
    assert ful.status_code == 200, ful.text
    workshop_lot_id = ful.json()["lot_id"]
    assert workshop_lot_id != company_lot_id

    rows = _lots_by_code(client, admin_h, lot_code)
    assert len(rows) == 2, f"Sau điều chuyển phải đúng 2 dòng (1 mỗi kho), thấy {len(rows)}"
    by_id = {r["lot_id"]: r for r in rows}
    assert by_id[company_lot_id]["quantity"] == 50
    assert by_id[workshop_lot_id]["quantity"] == 50
    assert by_id[workshop_lot_id]["location"] == "Kho phân xưởng"

    # 4. Cấp liệu vào mẻ sản xuất (Nấu) — 20kg, tự chọn FEFO (chỉ có đúng lô này ở PX).
    batch_id = _make_batch(client, admin_h)
    client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "ready"})
    client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "running"})
    disp = client.post(f"/api/dispense/{batch_id}", headers=admin_h,
                       json={"lines": [{"material_code": mat_code, "quantity": 20}]})
    assert disp.status_code == 200, disp.text

    rows = _lots_by_code(client, admin_h, lot_code)
    assert len(rows) == 2, f"Sau Cấp liệu KHÔNG được sinh thêm dòng nào, thấy {len(rows)}"
    by_id = {r["lot_id"]: r for r in rows}
    assert by_id[workshop_lot_id]["quantity"] == 30, "Phải trừ đúng 20kg trên ĐÚNG dòng PX cũ"
    assert by_id[company_lot_id]["quantity"] == 50, "Dòng ở Kho công ty không bị đụng tới"

    # 5. NVL dùng cho Lô lọc — 10kg từ đúng lô PX đó.
    filter_lot_id = _make_filter_lot(client, admin_h, "E2E")
    fl_usage = client.post(f"/api/batch-filter-lots/{filter_lot_id}/materials", headers=admin_h,
                           json={"lot_id": workshop_lot_id, "quantity": 10, "uom": "kg"})
    assert fl_usage.status_code == 201, fl_usage.text

    rows = _lots_by_code(client, admin_h, lot_code)
    assert len(rows) == 2, f"Sau NVL Lọc KHÔNG được sinh thêm dòng nào, thấy {len(rows)}"
    by_id = {r["lot_id"]: r for r in rows}
    assert by_id[workshop_lot_id]["quantity"] == 20, "Phải trừ đúng 10kg trên ĐÚNG dòng PX cũ"

    # 6. NVL dùng cho Lô thành phẩm (Chiết) — 5kg từ đúng lô PX đó, tạo từ lô lọc vừa dùng NVL ở
    # trên (cần khai "dịch nhà HL" đã rút trước thì mới tách được Lô thành phẩm — không liên
    # quan tới NVL/lô, chỉ là điều kiện tiên quyết của nghiệp vụ Lọc/Chiết).
    _finish_only_source(client, admin_h, filter_lot_id, v_drawn=900)
    pack = client.post(f"/api/batch-filter-lots/{filter_lot_id}/pack-lots", headers=admin_h,
                       json={"qty": 200, "pack_lot_code": "PKG-E2E", "lot_no": "LOT-E2E-PKG"})
    assert pack.status_code == 201, pack.text
    pack_lot_id = pack.json()["pack_lot_id"]
    pl_usage = client.post(f"/api/batch-pack-lots/{pack_lot_id}/materials", headers=admin_h,
                           json={"lot_id": workshop_lot_id, "quantity": 5, "uom": "kg"})
    assert pl_usage.status_code == 201, pl_usage.text

    rows = _lots_by_code(client, admin_h, lot_code)
    assert len(rows) == 2, f"Sau NVL Chiết KHÔNG được sinh thêm dòng nào, thấy {len(rows)}"
    by_id = {r["lot_id"]: r for r in rows}
    assert by_id[workshop_lot_id]["quantity"] == 15, "Phải trừ đúng 5kg trên ĐÚNG dòng PX cũ"
    assert by_id[company_lot_id]["quantity"] == 50, "Dòng ở Kho công ty vẫn nguyên suốt cả chuỗi"

    # Tổng kết: CẢ CHUỖI (nhập kho -> đề nghị -> cấp liệu -> lọc -> chiết) chỉ có ĐÚNG 1 lần sinh
    # dòng mới (bước điều chuyển, dùng lại cùng lot_code) — 3 bước tiêu thụ sau đó không sinh gì.
    assert len(rows) == 2
