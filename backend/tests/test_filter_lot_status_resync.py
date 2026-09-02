"""Test tự "chữa lành" trạng thái Lô lọc (BatchFilterLot.status) khi bị lệch so với on_hand/
volume_hl thật — trước đây status chỉ được đồng bộ (cho_chiet<->chiet_1_phan<->da_chiet_het) tại
đúng 3 điểm mutate (services/batch_pipeline.py::split_filter_lot_to_pack_lot/update_pack_lot_qty/
delete_pack_lot). Lô lọc nào đã tách lô thành phẩm TỪ TRƯỚC KHI có logic đồng bộ này (dữ liệu cũ)
sẽ mãi hiện sai (VD lô lọc "1" đã tách PKG-934995, tồn 26.99/28.1 hl nhưng vẫn hiện "Chờ chiết")
— giờ services/batch_pipeline.py::list_filter_lots/get_filter_lot tự tính lại VÀ lưu lại mỗi lần
đọc nếu phát hiện lệch (yêu cầu người dùng 2026-09-01: "tại sao BBT 01 đang chiết 1 phần rồi, mà
vẫn hiện trạng thái là chờ chiết").
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


def _build_chain(client, admin_h, suffix):
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(x for x in vers if x["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                          "planned_qty": 1000, "allow_shortage": True})   # batch_code: để tự sinh (giờ bắt buộc số nguyên)
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
                       json={"batch_ids": [batch_id], "tank_code": f"TANK-FLRESYNC-{suffix}"})
    assert tank.status_code == 201, tank.text
    tank_id = tank.json()["tank_id"]
    bbt = client.post("/api/lines", headers=admin_h,
                      json={"code": f"BBT-FLRESYNC-{suffix}", "name": f"BBT {suffix}", "kind": "tank_bbt"})
    assert bbt.status_code == 201, bbt.text
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": f"FLOT-FLRESYNC-{suffix}", "to_bbt": bbt.json()["code"],
        "sources": [{"source_type": "tank", "source_tank_id": tank_id}]})
    assert draw.status_code == 201, draw.text
    filter_lot_id = draw.json()["filter_lot_id"]
    src = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()[0]
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    fin2 = client.put(f"/api/batch-filter-lots/batches/{batches[0]['batch_link_id']}/finish", headers=admin_h,
                      json={"draws": [{"source_link_id": src["link_id"], "dich_nha_hl": 900}],
                           "nuoc_bai_khi_hl": 0})
    assert fin2.status_code == 200, fin2.text
    return filter_lot_id


def test_filter_lot_status_self_heals_when_stale_after_partial_pack(client, admin_h):
    filter_lot_id = _build_chain(client, admin_h, "HEAL1")

    pack = client.post(f"/api/batch-filter-lots/{filter_lot_id}/pack-lots", headers=admin_h,
                       json={"qty": 10000, "pack_lot_code": "PKG-FLRESYNC-HEAL1", "lot_no": "LOT-FLRESYNC-HEAL1"})
    assert pack.status_code == 201, pack.text

    fl = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()
    assert fl["status"] == "chiet_1_phan"   # đồng bộ đúng ngay khi tách (đường mutate bình thường)

    # Giả lập dữ liệu CŨ (tạo lô thành phẩm từ TRƯỚC khi có đồng bộ) — ghi thẳng status sai vào
    # DB, bỏ qua _sync_filter_lot_chiet_status (mirror đúng cách lệch đã xảy ra thật ở lô lọc "1"/
    # PKG-934995).
    from app.database import SessionLocal
    from app.models.batch_pipeline import BatchFilterLot
    db2 = SessionLocal()
    row = db2.get(BatchFilterLot, filter_lot_id)
    row.status = "cho_chiet"
    db2.commit()
    db2.close()

    stale_check = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()
    assert stale_check["status"] == "chiet_1_phan"   # tự sửa lại đúng ngay lần đọc kế tiếp
    assert stale_check["status_label"] == "Đang chiết"

    listed = client.get("/api/batch-filter-lots", headers=admin_h).json()
    row2 = next(r for r in listed if r["filter_lot_id"] == filter_lot_id)
    assert row2["status"] == "chiet_1_phan"

    # Xác nhận đã LƯU LẠI thật (không chỉ đúng trong response) bằng cách đọc thẳng DB.
    db3 = SessionLocal()
    persisted = db3.get(BatchFilterLot, filter_lot_id)
    assert persisted.status == "chiet_1_phan"
    db3.close()


def test_freshly_created_filter_lot_stays_dang_loc_not_da_chiet_het(client, admin_h):
    """Lô lọc VỪA TẠO (chưa "Kết thúc" mẻ lọc nào — on_hand=0 VÀ volume_hl=0) phải giữ nguyên
    "dang_loc" (Đang lọc) — KHÔNG được _resync_filter_lot_status_if_stale tự "chữa" nhầm thành
    "da_chiet_het" (Đã chiết hết) ngay lần đọc đầu tiên (yêu cầu người dùng 2026-09-02: "tôi vừa
    mới tạo lô lọc 03 mà tự nhiên lại hiện đã chiết hết, là sao vậy"). Root cause: nhánh
    da_chiet_het trong _sync_filter_lot_chiet_status thiếu điều kiện volume_hl > 0 (đã có ở
    _tank_status tương ứng nhưng bị bỏ sót ở đây) — on_hand=0 (chưa có gì) bị hiểu nhầm thành
    on_hand=0 (đã rút hết) dù volume_hl cũng đang là 0 (chưa từng có gì để rút)."""
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(x for x in vers if x["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                          "planned_qty": 1000, "allow_shortage": True})   # batch_code: để tự sinh (giờ bắt buộc số nguyên)
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
                       json={"batch_ids": [batch_id], "tank_code": "TANK-FLRESYNC-FRESH1"})
    assert tank.status_code == 201, tank.text
    tank_id = tank.json()["tank_id"]
    bbt = client.post("/api/lines", headers=admin_h,
                      json={"code": "BBT-FLRESYNC-FRESH1", "name": "BBT fresh1", "kind": "tank_bbt"})
    assert bbt.status_code == 201, bbt.text
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": "FLOT-FLRESYNC-FRESH1", "to_bbt": bbt.json()["code"],
        "sources": [{"source_type": "tank", "source_tank_id": tank_id}]})
    assert draw.status_code == 201, draw.text
    filter_lot_id = draw.json()["filter_lot_id"]
    assert draw.json()["status"] == "dang_loc"

    # Đọc lại (get) NGAY sau khi tạo — trước đây bug khiến _resync tự sửa nhầm thành da_chiet_het.
    fresh = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()
    assert fresh["status"] == "dang_loc"
    assert fresh["status_label"] == "Đang lọc"

    # Đọc qua list (màn "Lọc" hiển thị bảng danh sách) cũng phải đúng.
    listed = client.get("/api/batch-filter-lots", headers=admin_h).json()
    row = next(r for r in listed if r["filter_lot_id"] == filter_lot_id)
    assert row["status"] == "dang_loc"
