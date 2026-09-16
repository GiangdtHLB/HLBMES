"""BC nhập-xuất-tồn (inventory_report/lot_inventory_report) VÀ Sổ chi tiết vật tư
(material_transaction_detail) phải tính NVL đã cấp cho mẻ Nấu vào đúng kỳ theo "Ngày cấp"
(batch.start_at) — KHÔNG phải giờ bấm nút cấp liệu thật (GenealogyEdge.event_time). Trước đây cả
3 hàm đều dùng chung _consumed_lot_edges lọc/hiển thị theo event_time — cùng lỗi vừa phát hiện và
sửa ở _material_balances_as_of/_lot_balances_as_of (yêu cầu người dùng 2026-09-15: "ngày trừ tồn
kho là ngày cấp liệu... bạn đã tính vào bảng tồn kho chưa, tính cả vào báo cáo xuất nhập tồn
chưa")."""

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

from app.common import utcnow
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


def _clear_seed_batch_9002(client, admin_h):
    batches = client.get("/api/batches", headers=admin_h).json()
    b9002 = next((b for b in batches if b.get("batch_code") == "9002"), None)
    if b9002 and b9002["state"] in ("running", "held"):
        r = client.post(f"/api/batches/{b9002['batch_id']}/transition", headers=admin_h,
                        json={"target": "cancelled"})
        assert r.status_code == 200, r.text


def test_report_and_detail_count_nau_dispense_by_batch_start_at(client, admin_h):
    _clear_seed_batch_9002(client, admin_h)
    now = utcnow()

    mat = client.post("/api/materials", headers=admin_h,
                      json={"code": "RPT-NAU01", "name": "Vật tư report Nấu", "uom": "kg"})
    assert mat.status_code == 201, mat.text
    material_id, code = mat.json()["material_id"], mat.json()["code"]

    recv = client.post("/api/warehouse/receive", headers=admin_h, json={
        "material_id": material_id, "quantity": 100, "uom": "kg", "location": "Kho phân xưởng",
        "received_at": (now - timedelta(hours=3)).isoformat()})
    assert recv.status_code == 200, recv.text
    lot_id = recv.json()["lot_id"]

    bt = client.post("/api/beer-types", headers=admin_h, json={"code": "BT-RPTNAU", "name": "Loại report Nấu"})
    assert bt.status_code == 201, bt.text
    recipe = client.post("/api/recipes", headers=admin_h,
                         json={"code": "CT-RPTNAU", "name": "Recipe report Nấu",
                              "beer_type_id": bt.json()["beer_type_id"]})
    assert recipe.status_code == 201, recipe.text
    prod = client.post("/api/products", headers=admin_h,
                       json={"code": "PRD-RPTNAU", "name": "Dich report Nấu", "uom": "L",
                            "beer_type_id": bt.json()["beer_type_id"]})
    assert prod.status_code == 201, prod.text
    v = client.post(f"/api/recipes/{recipe.json()['recipe_id']}/versions", headers=admin_h,
                    json={"base_qty": 100, "base_uom": "L", "product_id": prod.json()["product_id"],
                         "materials": [{"material_code": code, "qty": 40, "uom": "kg", "tol_pct": 5}]})
    assert v.status_code == 201, v.text
    version_id = v.json()["version_id"]
    for target in ("review", "approved", "effective"):
        t = client.post(f"/api/recipes/versions/{version_id}/transition", headers=admin_h,
                        json={"target": target})
        assert t.status_code == 200, t.text

    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": version_id,
                         "planned_qty": 100, "allow_shortage": True})
    assert b.status_code == 201, b.text
    batch_id = b.json()["batch_id"]

    batch_start_at = now - timedelta(hours=2)
    s = client.post(f"/api/batches/{batch_id}/start", headers=admin_h,
                    json={"start_at": batch_start_at.isoformat()})
    assert s.status_code == 200, s.text

    disp = client.post(f"/api/dispense/{batch_id}", headers=admin_h,
                       json={"lines": [{"material_code": code, "quantity": 40}]})
    assert disp.status_code == 200, disp.text

    # Kỳ báo cáo CHỈ phủ tới batch_start_at + 5 phút — KHÔNG phủ tới "now" (giờ bấm cấp liệu
    # thật, muộn hơn ~2 tiếng). Nếu báo cáo vẫn lọc theo event_time (giờ bấm thật) thì dòng NVL
    # này sẽ bị lọt ra ngoài kỳ, "Xuất" báo sai = 0.
    date_from = (now - timedelta(hours=4)).isoformat()
    date_to = (batch_start_at + timedelta(minutes=5)).isoformat()

    rep = client.get("/api/warehouse/report", headers=admin_h, params={
        "date_from": date_from, "date_to": date_to, "location": "Kho phân xưởng"}).json()
    row = next(r for r in rep if r["material_id"] == material_id)
    assert row["issued"] == pytest.approx(40.0)

    rep_lot = client.get("/api/warehouse/report/by-lot", headers=admin_h, params={
        "date_from": date_from, "date_to": date_to, "location": "Kho phân xưởng"}).json()
    lot_row = next(r for r in rep_lot if r["lot_id"] == lot_id)
    assert lot_row["issued"] == pytest.approx(40.0)

    detail = client.get("/api/warehouse/report/material-detail", headers=admin_h, params={
        "material_id": material_id, "date_from": date_from, "date_to": date_to,
        "location": "Kho phân xưởng"}).json()
    consume_row = next(r for r in detail["rows"] if r["type"] == "consume")
    assert consume_row["out"] == pytest.approx(40.0)
    total_out = sum(r["out"] for r in detail["rows"])
    assert total_out == pytest.approx(row["issued"])   # khớp đúng giữa 2 báo cáo, mirror test cũ

    # Ngược lại: kỳ báo cáo CHỈ phủ đúng lúc "now" (giờ bấm thật) trở đi, KHÔNG phủ batch_start_at
    # -> dòng NVL này phải BIẾN MẤT khỏi kỳ (đã tính vào kỳ TRƯỚC rồi, không tính lại lần 2).
    date_from2 = (now - timedelta(minutes=1)).isoformat()
    date_to2 = (now + timedelta(hours=1)).isoformat()
    rep2 = client.get("/api/warehouse/report", headers=admin_h, params={
        "date_from": date_from2, "date_to": date_to2, "location": "Kho phân xưởng"}).json()
    row2 = next((r for r in rep2 if r["material_id"] == material_id), None)
    assert row2 is None or row2["issued"] == 0.0

    # Frontend (bcReportSectionHtml) gửi date_from/date_to KHÔNG kèm offset (toDTLocal(), khác
    # test ở trên dùng .isoformat() của datetime AWARE) — naive string này parse ra datetime
    # naive, trong khi batch.start_at đọc từ CSDL (UTCDateTime()) luôn aware. So sánh trực tiếp
    # (_consumed_lot_edges/_nau_consume_as_of) từng raise "can't compare offset-naive and
    # offset-aware datetimes" (500), sập cả 3 báo cáo bất cứ khi nào kỳ lọc phủ tới 1 mẻ đã cấp
    # liệu qua pipeline "Mẻ sản xuất" (bug thực tế 2026-09-16: "Nút báo cáo xuất nhập tồn kho
    # phân xưởng không chạy được"). Test bằng chuỗi naive y hệt frontend để không tái diễn.
    naive_from = (now - timedelta(hours=4)).replace(tzinfo=None).isoformat()
    naive_to = (batch_start_at + timedelta(minutes=5)).replace(tzinfo=None).isoformat()
    assert "+" not in naive_from and "Z" not in naive_from

    rep3 = client.get("/api/warehouse/report", headers=admin_h, params={
        "date_from": naive_from, "date_to": naive_to, "location": "Kho phân xưởng"})
    assert rep3.status_code == 200, rep3.text
    row3 = next(r for r in rep3.json() if r["material_id"] == material_id)
    assert row3["issued"] == pytest.approx(40.0)

    rep3_lot = client.get("/api/warehouse/report/by-lot", headers=admin_h, params={
        "date_from": naive_from, "date_to": naive_to, "location": "Kho phân xưởng"})
    assert rep3_lot.status_code == 200, rep3_lot.text

    detail3 = client.get("/api/warehouse/report/material-detail", headers=admin_h, params={
        "material_id": material_id, "date_from": naive_from, "date_to": naive_to,
        "location": "Kho phân xưởng"})
    assert detail3.status_code == 200, detail3.text

    stock_asof = client.get("/api/warehouse/stock/as-of", headers=admin_h,
                            params={"as_of": naive_to, "location": "Kho phân xưởng"})
    assert stock_asof.status_code == 200, stock_asof.text
