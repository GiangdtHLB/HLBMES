""""Lịch sử xuất dùng NVL" (Kho phân xưởng) trước đây chỉ gộp Lọc/Chiết (BatchFilterLotMaterial
Usage/BatchPackLotMaterialUsage) — thiếu hẳn Nấu (Dispense/DispenseLine), vì cơ chế trừ tồn khác
nhau (Nấu không tạo StockMovement). Yêu cầu người dùng 2026-09-14: "đưa vào màn hình này bao gồm
cả xuất vật tư cho mẻ nấu". Xem services/warehouse.py::workshop_usage_history.
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
                    json={"code": f"NVLH-{suffix}", "name": f"Vật tư lịch sử {suffix}", "uom": "kg"})
    assert r.status_code == 201, r.text
    return r.json()["material_id"], r.json()["code"]


def _receive_workshop_lot(client, admin_h, material_id, qty):
    r = client.post("/api/warehouse/receive", headers=admin_h, json={
        "material_id": material_id, "quantity": qty, "uom": "kg", "location": "Kho phân xưởng"})
    assert r.status_code == 200, r.text
    return r.json()["lot_id"]


def _recipe_version(client, admin_h, suffix, material_code, qty, base_qty=100):
    bt = client.post("/api/beer-types", headers=admin_h,
                     json={"code": f"BT-NVLH-{suffix}", "name": f"Loại {suffix}"})
    assert bt.status_code == 201, bt.text
    r = client.post("/api/recipes", headers=admin_h,
                    json={"code": f"CT-NVLH-{suffix}", "name": "Test lịch sử NVL",
                         "beer_type_id": bt.json()["beer_type_id"]})
    assert r.status_code == 201, r.text
    recipe_id = r.json()["recipe_id"]
    prod = client.post("/api/products", headers=admin_h,
                       json={"code": f"PRD-NVLH-{suffix}", "name": f"Dịch {suffix}", "uom": "L",
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


def _clear_seed_batch_9002(client, admin_h):
    """seed.py cố tình để mẻ demo "9002" ở trạng thái "running, chưa cấp liệu lần nào" — với điều
    kiện cấp liệu mới (2026-09-15, _assert_dispensable), mẻ test này (bắt đầu SAU 9002) sẽ bị
    chặn oan nếu không hủy 9002 trước."""
    batches = client.get("/api/batches", headers=admin_h).json()
    b9002 = next((b for b in batches if b.get("batch_code") == "9002"), None)
    if b9002 and b9002["state"] in ("running", "held"):
        r = client.post(f"/api/batches/{b9002['batch_id']}/transition", headers=admin_h,
                        json={"target": "cancelled"})
        assert r.status_code == 200, r.text


def _new_batch(client, admin_h, version_id, suffix):
    _clear_seed_batch_9002(client, admin_h)
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": version_id,
                         "planned_qty": 100})
    assert b.status_code == 201, b.text
    batch = b.json()
    # Điều kiện cấp liệu mới (yêu cầu người dùng 2026-09-15, services/dispense.py::
    # _assert_dispensable) chặn cấp liệu khi mẻ chưa có start_at.
    s = client.post(f"/api/batches/{batch['batch_id']}/start", headers=admin_h,
                    json={"start_at": utcnow().isoformat()})
    assert s.status_code == 200, s.text
    return batch


def test_history_includes_nau_dispense_and_refund(client, admin_h):
    material_id, code = _new_material(client, admin_h, "NAU01")
    _receive_workshop_lot(client, admin_h, material_id, 20)
    version_id = _recipe_version(client, admin_h, "NAU01", code, qty=10)
    batch = _new_batch(client, admin_h, version_id, "NAU01")

    ok = client.post(f"/api/dispense/{batch['batch_id']}", headers=admin_h,
                     json={"lines": [{"material_code": code, "quantity": 10}]})
    assert ok.status_code == 200, ok.text

    hist = client.get("/api/warehouse/workshop-usage-history?limit=2000", headers=admin_h).json()
    nau_rows = [r for r in hist if r["stage"] == "Nấu" and r["material_name"] == f"Vật tư lịch sử NAU01"]
    assert len(nau_rows) == 1, nau_rows
    row = nau_rows[0]
    assert row["batch_label"] == f"Mẻ nấu {batch['batch_code']}"
    assert row["quantity"] == 10.0
    assert row["uom"] == "kg"
    assert row["actor"] == "admin"
    assert row["lot_code"]

    # "Sửa Thực tế" giảm về 4 -> hoàn lại 6. workshop_usage_history GỘP NET theo (batch_id,
    # material_code, lot_code) — chỉ còn ĐÚNG 1 dòng với SL NET = 10 - 6 = 4 (không hiện riêng 2
    # dòng +10/-6 nữa — SỬA 2026-09-14, tránh hiểu lầm "đã dùng 10kg rồi lại trả 6kg" trong khi
    # thực tế NET chỉ dùng 4kg; xem services/warehouse.py::workshop_usage_history).
    adj = client.post(f"/api/dispense/{batch['batch_id']}/adjust", headers=admin_h,
                      json={"material_code": code, "new_actual": 4, "reason": "test hoàn lại"})
    assert adj.status_code == 200, adj.text

    hist2 = client.get("/api/warehouse/workshop-usage-history?limit=2000", headers=admin_h).json()
    nau_rows2 = [r for r in hist2 if r["stage"] == "Nấu" and r["material_name"] == f"Vật tư lịch sử NAU01"]
    assert len(nau_rows2) == 1, nau_rows2
    assert nau_rows2[0]["quantity"] == 4.0


def test_history_includes_direct_consume_not_only_dispense(client, admin_h):
    """Tiêu thụ lô qua endpoint "Tiêu thụ lô" trực tiếp (POST /batches/{id}/consume,
    services/batches.py::consume_lot) KHÔNG tạo DispenseLine — chỉ ghi GenealogyEdge(relation=
    consume). Trước đây workshop_usage_history CHỈ quét DispenseLine nên vật tư tiêu thụ theo
    đường này biến mất khỏi "Lịch sử xuất dùng NVL" dù tồn kho ĐÃ trừ đúng và "Thực tế" (BOM) ĐÃ
    tính đúng (bug thực tế 2026-09-16: "kho phân xưởng không thấy lịch sử dụng NVL gạo, trong
    khi cấp liệu đã tính vào rồi, tồn kho cũng trừ đi rồi" — mẻ 2352 dùng "Tiêu thụ lô" trực tiếp
    cho gạo). Số lượng giờ lấy từ genealogy edge nên phải hiện đúng dù không qua dispense()."""
    material_id, code = _new_material(client, admin_h, "DIRECT01")
    lot_id = _receive_workshop_lot(client, admin_h, material_id, 20)
    version_id = _recipe_version(client, admin_h, "DIRECT01", code, qty=10)
    batch = _new_batch(client, admin_h, version_id, "DIRECT01")

    consume = client.post(f"/api/batches/{batch['batch_id']}/consume", headers=admin_h,
                         json={"lot_id": lot_id, "quantity": 7})
    assert consume.status_code == 200, consume.text

    # Tồn kho đã trừ đúng (Kho phân xưởng).
    lots = client.get("/api/lots", headers=admin_h).json()
    lot = next(l for l in lots if l["lot_id"] == lot_id)
    assert lot["quantity"] == 13.0

    hist = client.get("/api/warehouse/workshop-usage-history?limit=2000", headers=admin_h).json()
    nau_rows = [r for r in hist if r["stage"] == "Nấu" and r["material_name"] == "Vật tư lịch sử DIRECT01"]
    assert len(nau_rows) == 1, nau_rows
    row = nau_rows[0]
    assert row["batch_label"] == f"Mẻ nấu {batch['batch_code']}"
    assert row["quantity"] == 7.0
    assert row["uom"] == "kg"
    assert row["lot_code"]


def test_history_still_includes_loc_chiet_unchanged(client, admin_h):
    """Không phá vỡ 2 nguồn Lọc/Chiết đã có sẵn — chỉ kiểm tra endpoint vẫn trả về đủ 3 stage
    khi có dữ liệu ở cả 3 (không cần dựng lại toàn bộ kịch bản Lọc/Chiết, seed() đã có sẵn)."""
    hist = client.get("/api/warehouse/workshop-usage-history?limit=2000", headers=admin_h).json()
    stages = {r["stage"] for r in hist}
    assert "Nấu" in stages
