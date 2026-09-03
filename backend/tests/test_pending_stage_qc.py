"""Test GET /api/quality/pending-stage-qc — panel "Công đoạn chờ khai báo chỉ tiêu chất
lượng" ở tab Chất lượng (mirror của Lô NVL chờ khai báo, nhưng gộp cả 4 công đoạn sản xuất:
mẻ nấu/lô lên men chính+phụ/mẻ lọc/mã chiết). Xem services/qc_catalog.py::list_pending_stage_declarations.
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


@pytest.fixture(scope="module")
def vanhanh_h(client):
    return _login(client, "vanhanh", "123456")


def _make_group_with_param(client, admin_h, suffix):
    p = client.post("/api/qc/parameters", headers=admin_h,
                    json={"code": f"CT_{suffix}", "name": f"Chỉ tiêu {suffix}", "lsl": 1, "usl": 10})
    assert p.status_code == 201, p.text
    param_id = p.json()["param_id"]
    g = client.post("/api/qc/groups", headers=admin_h,
                    json={"code": f"GRP_{suffix}", "name": f"Nhóm {suffix}"})
    assert g.status_code == 201, g.text
    group_id = g.json()["group_id"]
    it = client.post(f"/api/qc/groups/{group_id}/items", headers=admin_h,
                     json={"param_id": param_id, "mandatory": True})
    assert it.status_code == 201, it.text
    return group_id, f"CT_{suffix}"


def test_bottle_shows_pending_then_disappears_after_declare(client, admin_h, vanhanh_h):
    group_id, code = _make_group_with_param(client, admin_h, "PENDINGBTL")
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": "thanh_pham", "group_id": group_id, "mandatory": True})
    assert link.status_code == 201, link.text

    bottle_code = "CH-PENDING-01"
    b = client.post("/api/brewing/bottles", headers=vanhanh_h,
                    json={"bottle_code": bottle_code, "beer_type": "Bia test"})
    assert b.status_code == 201, b.text

    # bottle_code chỉ duy nhất TRONG 1 năm — scope_id thật (qc_catalog.bottle_scope_id) phải
    # kèm năm.
    scope_id = f"{b.json()['bottle_year']}-{bottle_code}__thanh_pham"
    pending = client.get("/api/quality/pending-stage-qc", headers=admin_h).json()
    row = next(p for p in pending if p["scope_type"] == "bottle" and p["scope_id"] == scope_id)
    assert row["stage"] == "thanh_pham"
    assert code in row["pending"]
    assert bottle_code in row["label"]

    rec = client.post("/api/brewing/qc-results", headers=vanhanh_h,
                      json={"stage": "thanh_pham", "scope_type": "bottle", "scope_id": scope_id,
                            "parameter": code, "value": 5, "lower_limit": 1, "upper_limit": 10})
    assert rec.status_code == 201, rec.text

    pending_after = client.get("/api/quality/pending-stage-qc", headers=admin_h).json()
    assert not any(p["scope_type"] == "bottle" and p["scope_id"] == scope_id for p in pending_after)

    client.delete(f"/api/qc/stage-groups/{link.json()['link_id']}", headers=admin_h)


def test_records_without_any_stage_group_are_never_pending(client, admin_h, vanhanh_h):
    """Mã chiết không có nhóm chỉ tiêu bắt buộc nào gán vào stage đó thì KHÔNG được liệt
    kê (required rỗng -> pending luôn rỗng) — tránh làm phiền panel với dữ liệu vô hạn."""
    bottle_code = "CH-NOGROUP-01"
    b = client.post("/api/brewing/bottles", headers=vanhanh_h,
                    json={"bottle_code": bottle_code, "beer_type": "Bia test"})
    assert b.status_code == 201, b.text
    scope_id = f"{bottle_code}__thanh_pham"

    pending = client.get("/api/quality/pending-stage-qc", headers=admin_h).json()
    assert not any(p["scope_type"] == "bottle" and p["scope_id"] == scope_id for p in pending)


def _make_batch_tank(client, admin_h, batch_code, tank_code, tank_lm=None):
    """Mirror test_batch_filter_order.py — gộp 1 mẻ nấu (BatchExecution) đã hoàn thành vào 1
    BatchTank mới, dùng làm nguồn cho BatchFilterLot bên dưới."""
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(x for x in vers if x["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                          "batch_code": batch_code, "planned_qty": 1000, "allow_shortage": True})
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
    t = client.post("/api/batch-tanks", headers=admin_h,
                    json={"batch_ids": [batch_id], "tank_code": tank_code, "tank_lm": tank_lm})
    assert t.status_code == 201, t.text
    return t.json()


def test_batch_filter_lot_shows_pending_then_stays_listed_after_declare(client, admin_h):
    """Lô lọc (Mẻ SX, BatchFilterLot) phải xuất hiện ở panel "chờ khai báo" y hệt Mẻ lọc
    (FilterRecord) cũ — trước bản sửa này list_pending_stage_declarations chỉ quét FilterRecord,
    bỏ sót toàn bộ pipeline mới (yêu cầu người dùng 2026-09-01: tạo lô lọc xong không thấy khai
    báo chỉ tiêu bên Chất lượng). Khác FilterRecord cũ (biến mất khi khai đủ) — TOÀN BỘ pipeline
    "Mẻ SX" giờ LUÔN ở lại panel này kể cả sau khi khai đủ, chỉ đổi `pending` thành rỗng (yêu cầu
    người dùng 2026-09-02: "khi khai xong công đoạn đó thì không cần ẩn đi nhé")."""
    group_id, code = _make_group_with_param(client, admin_h, "PENDINGBFL")
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": "loc", "group_id": group_id, "mandatory": True})
    assert link.status_code == 201, link.text

    tank = _make_batch_tank(client, admin_h, None, "TANK-PENDINGBFL")
    order = client.post("/api/batch-filter-orders", headers=admin_h, json={
        "order_code": "LOC-PENDINGBFL",
        "sources": [{"source_type": "tank", "source_tank_id": tank["tank_id"], "planned_v_dich_hl": 900}],
    })
    assert order.status_code == 201, order.text
    bbt = client.post("/api/lines", headers=admin_h,
                      json={"code": "BBT-PENDINGBFL", "name": "Tank thành phẩm PENDINGBFL", "kind": "tank_bbt"})
    assert bbt.status_code == 201, bbt.text
    fl = client.post(f"/api/batch-filter-orders/{order.json()['order_id']}/filter-lots", headers=admin_h,
                     json={"filter_lot_code": "FLOT-PENDINGBFL", "to_bbt": bbt.json()["code"]})
    assert fl.status_code == 201, fl.text
    filter_lot_id = fl.json()["filter_lot_id"]

    pending = client.get("/api/quality/pending-stage-qc", headers=admin_h).json()
    row = next(p for p in pending if p["scope_type"] == "batch_filter_lot" and p["scope_id"] == filter_lot_id)
    assert row["stage"] == "loc"
    assert code in row["pending"]
    assert "FLOT-PENDINGBFL" in row["label"]

    rec = client.post("/api/brewing/qc-results", headers=admin_h,
                      json={"stage": "loc", "scope_type": "batch_filter_lot", "scope_id": filter_lot_id,
                            "parameter": code, "value": 5, "lower_limit": 1, "upper_limit": 10})
    assert rec.status_code == 201, rec.text

    pending_after = client.get("/api/quality/pending-stage-qc", headers=admin_h).json()
    row_after = next((p for p in pending_after if p["scope_type"] == "batch_filter_lot" and p["scope_id"] == filter_lot_id), None)
    assert row_after is not None   # KHÔNG bị loại khỏi danh sách dù đã khai đủ (pipeline mới)
    assert row_after["pending"] == []

    client.delete(f"/api/qc/stage-groups/{link.json()['link_id']}", headers=admin_h)


def test_len_men_chinh_stays_listed_after_fully_declared(client, admin_h):
    """Lên men chính/phụ (MULTI_SAMPLE_STAGES — lấy mẫu LẶP LẠI) KHÔNG được biến mất khỏi panel
    "chờ khai báo" sau khi đã khai đủ (khác mọi stage khác, vốn biến mất ngay khi hết pending)
    — đây phải LUÔN là nơi có thể bấm "+Thêm lần lấy mẫu" thêm lần mới, kể cả khi đã đủ (yêu cầu
    người dùng 2026-09-02: "vẫn tại chỗ công đoạn đó sẽ hiển thị toàn bộ công đoạn đã khai báo,
    không ẩn đi... có 1 nút bên cạnh là thêm lần lấy mẫu")."""
    group_id, code = _make_group_with_param(client, admin_h, "LMCHINHSTAY1")
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": "len_men_chinh", "group_id": group_id, "mandatory": True})
    assert link.status_code == 201, link.text

    tank = _make_batch_tank(client, admin_h, None, "TANK-LMCHINHSTAY1", tank_lm="TANK A1")
    scope_id = f"{tank['tank_id']}__len_men_chinh"

    before = client.get("/api/quality/pending-stage-qc", headers=admin_h).json()
    row_before = next(p for p in before if p["scope_type"] == "batch_tank" and p["scope_id"] == scope_id)
    assert row_before["stage"] == "len_men_chinh"
    assert code in row_before["pending"]
    # Nhãn phải hiển thị TÊN TANK VẬT LÝ (Danh mục "Tank lên men"), không phải mã lô tự sinh
    # (yêu cầu người dùng 2026-09-02: "không rõ tank 01, 02, 04 là gì, tank men phải là lấy từ
    # danh mục tank men chứ").
    assert "TANK A1" in row_before["label"]
    assert row_before["sample_round_count"] == 0

    sample = client.post("/api/brewing/qc-samples", headers=admin_h,
                         json={"stage": "len_men_chinh", "scope_type": "batch_tank", "scope_id": scope_id,
                               "results": [{"parameter": code, "value": 5, "lower_limit": 1, "upper_limit": 10}]})
    assert sample.status_code == 201, sample.text

    after = client.get("/api/quality/pending-stage-qc", headers=admin_h).json()
    row_after = next((p for p in after if p["scope_type"] == "batch_tank" and p["scope_id"] == scope_id), None)
    assert row_after is not None   # KHÔNG bị loại khỏi danh sách dù đã khai đủ
    assert row_after["pending"] == []
    # Đã lấy 1 lần -> lần TIẾP THEO (hiển thị ở nút "+ Thêm lần lấy mẫu") phải là lần 2 (yêu cầu
    # người dùng 2026-09-02: "Ghi rõ thêm lấy mẫu lần mấy").
    assert row_after["sample_round_count"] == 1

    client.delete(f"/api/qc/stage-groups/{link.json()['link_id']}", headers=admin_h)
