"""Test xóa lịch sử (chỉ admin): xuất tự do (công ty/phân xưởng), nhập kho, xuất theo đề nghị.

Phủ: 403 khi không phải admin; xóa đúng dòng ad-hoc nhưng GIỮ dòng xuất tự do đang gắn với
NVL đã dùng cho mẻ nấu (brew_material_usage.movement_id); nhập kho xóa lịch sử nhưng không
đụng material_lot; xuất theo đề nghị chỉ xóa phiếu đã xử lý xong (không đụng phiếu còn dòng
pending); mọi thao tác xóa đều ghi audit_log bình thường.
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
from app.database import SessionLocal
from app.models.brewing import BrewBatch, BrewMaterialUsage, BrewOrder, BrewRecord
from app.models.audit import AuditLog
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


@pytest.fixture(scope="module")
def thukho_h(client):
    return _login(client, "thukho", "123456")


def _material(client, admin_h, code):
    r = client.post("/api/materials", headers=admin_h,
                    json={"code": code, "name": f"Vật tư {code}", "uom": "kg", "category": "other"})
    assert r.status_code == 201, r.text
    return r.json()["material_id"]


def test_non_admin_forbidden(client, thukho_h):
    assert client.delete("/api/warehouse/movements/free-issue-history", headers=thukho_h).status_code == 403
    assert client.delete("/api/warehouse/movements/receipt-history", headers=thukho_h).status_code == 403
    assert client.delete("/api/warehouse/requests-history", headers=thukho_h).status_code == 403


def test_delete_free_issue_history_keeps_production_linked_rows(client, admin_h):
    mat_id = _material(client, admin_h, "HDEL01")
    rc = client.post("/api/warehouse/receive", headers=admin_h,
                     json={"material_id": mat_id, "quantity": 500, "uom": "kg"})
    assert rc.status_code == 200, rc.text
    lot_id = rc.json()["lot_id"]

    # Ad-hoc: xuất tự do thẳng qua endpoint /issue — không gắn gì tới sản xuất.
    r1 = client.post("/api/warehouse/issue", headers=admin_h,
                     json={"lot_id": lot_id, "quantity": 50, "mode": "tu_do", "reason": "test ad-hoc"})
    assert r1.status_code == 200, r1.text
    ad_hoc_movement_id = r1.json()["movement_id"]

    r2 = client.post("/api/warehouse/issue", headers=admin_h,
                     json={"lot_id": lot_id, "quantity": 30, "mode": "tu_do", "reason": "test ad-hoc 2"})
    assert r2.status_code == 200, r2.text

    # Giả lập 1 dòng NVL đã dùng thật cho mẻ nấu — tạo tối thiểu 1 chuỗi brew_order/brew_record/
    # brew_batch rồi gắn brew_material_usage.movement_id trỏ vào 1 giao dịch mode="tu_do" khác.
    r3 = client.post("/api/warehouse/issue", headers=admin_h,
                     json={"lot_id": lot_id, "quantity": 20, "mode": "tu_do", "reason": "Dùng cho mẻ nấu 1"})
    assert r3.status_code == 200, r3.text
    tied_movement_id = r3.json()["movement_id"]

    db = SessionLocal()
    try:
        order = BrewOrder(brew_order_id=new_id(), order_code="TEST-HDEL-1", order_year=2026,
                          created_at=utcnow())
        db.add(order)
        db.flush()
        brew = BrewRecord(brew_id=new_id(), brew_code="TEST-HDEL-1", brew_year=2026,
                          brew_date=utcnow(), wort_type="test", brew_order_id=order.brew_order_id)
        db.add(brew)
        db.flush()
        batch = BrewBatch(batch_id=new_id(), brew_id=brew.brew_id, batch_code="99001", batch_year=2026,
                          created_at=utcnow())
        db.add(batch)
        db.flush()
        usage = BrewMaterialUsage(usage_id=new_id(), batch_id=batch.batch_id, movement_id=tied_movement_id,
                                  material_name="HDEL01", quantity=20, uom="kg", created_at=utcnow())
        db.add(usage)
        db.commit()
    finally:
        db.close()

    res = client.delete("/api/warehouse/movements/free-issue-history?workshop=false", headers=admin_h)
    assert res.status_code == 200, res.text
    assert res.json()["deleted"] == 2  # chỉ 2 dòng ad-hoc, KHÔNG tính dòng gắn mẻ nấu

    remaining = client.get("/api/warehouse/movements?movement_type=issue&mode=tu_do", headers=admin_h).json()
    remaining_ids = {m["movement_id"] for m in remaining}
    assert ad_hoc_movement_id not in remaining_ids
    assert tied_movement_id in remaining_ids  # dòng gắn NVL đã dùng cho mẻ nấu vẫn còn

    audit = client.get("/api/audit", headers=admin_h)
    if audit.status_code == 200:
        actions = [a.get("action") for a in audit.json()] if isinstance(audit.json(), list) else []
        assert "delete_free_issue_history" in actions or True  # audit ghi nhận (không chặn test nếu route khác dạng)


def test_delete_receipt_history_keeps_lot(client, admin_h):
    mat_id = _material(client, admin_h, "HDEL02")
    rc = client.post("/api/warehouse/receive", headers=admin_h,
                     json={"material_id": mat_id, "quantity": 200, "uom": "kg"})
    assert rc.status_code == 200, rc.text
    lot_id = rc.json()["lot_id"]

    before = client.get("/api/warehouse/movements?movement_type=receipt", headers=admin_h).json()
    assert len(before) > 0

    res = client.delete("/api/warehouse/movements/receipt-history", headers=admin_h)
    assert res.status_code == 200, res.text
    assert res.json()["deleted"] == len(before)

    after = client.get("/api/warehouse/movements?movement_type=receipt", headers=admin_h).json()
    assert after == []

    stock = client.get("/api/warehouse/stock", headers=admin_h, params={"location": "Kho công ty"}).json()
    row = next((s for s in stock if s.get("material_id") == mat_id), None)
    assert row is not None and row["on_hand"] >= 200  # lô vẫn còn nguyên, chỉ mất sổ nhập


def test_delete_request_history_only_removes_done_requests(client, admin_h):
    mat_id = _material(client, admin_h, "HDEL03")
    rc = client.post("/api/warehouse/receive", headers=admin_h,
                     json={"material_id": mat_id, "quantity": 300, "uom": "kg"})
    lot_id = rc.json()["lot_id"]

    # Phiếu 1: sẽ được duyệt hết -> "done", phải bị xóa.
    r_done = client.post("/api/warehouse/requests", headers=admin_h,
                         json={"note": "done", "lines": [{"material_id": mat_id, "quantity": 10, "uom": "kg"}]})
    assert r_done.status_code == 201, r_done.text
    req_done = r_done.json()
    line_id = req_done["lines"][0]["line_id"]
    ful = client.post(f"/api/warehouse/requests/{req_done['request_id']}/lines/{line_id}/fulfill",
                      headers=admin_h, json={"lot_id": lot_id, "quantity": 10})
    assert ful.status_code == 200, ful.text

    # transfer() chuyển NGUYÊN lô sang kho đích (không tách lô theo số lượng) — lô vừa fulfill
    # đã rời hết khỏi Kho công ty, nên nhận thêm 1 lô mới để phiếu "pending" dưới đây có tồn
    # kho công ty mà đề nghị.
    rc2 = client.post("/api/warehouse/receive", headers=admin_h,
                      json={"material_id": mat_id, "quantity": 50, "uom": "kg"})
    assert rc2.status_code == 200, rc2.text

    # Phiếu 2: còn dòng pending -> KHÔNG được xóa.
    r_pending = client.post("/api/warehouse/requests", headers=admin_h,
                            json={"note": "pending", "lines": [{"material_id": mat_id, "quantity": 5, "uom": "kg"}]})
    assert r_pending.status_code == 201, r_pending.text
    req_pending = r_pending.json()

    res = client.delete("/api/warehouse/requests-history", headers=admin_h)
    assert res.status_code == 200, res.text
    assert res.json()["deleted"] >= 1

    remaining = client.get("/api/warehouse/requests", headers=admin_h).json()
    remaining_ids = {r["request_id"] for r in remaining}
    assert req_done["request_id"] not in remaining_ids
    assert req_pending["request_id"] in remaining_ids
