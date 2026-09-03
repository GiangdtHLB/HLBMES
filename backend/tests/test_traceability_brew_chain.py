"""Test Truy xuất nguồn gốc nối vào đúng quy trình sản xuất bia thật (Nấu→Lên men→Lọc→
Chiết→vỉ/keg Kho TP) — trước đây genealogy chỉ biết mã mẻ (BatchExecution) và lô NVL của
module Mẻ sản xuất cũ, không nhận ra mã chiết/mã vỉ-keg thật. Test dựng đủ 1 chuỗi thật:
lô NVL → mẻ nấu → mã nấu → lô LM → mã lọc → mã chiết → vỉ/keg, rồi kiểm tra
find_node/trace_backward/trace_forward/recall đều nhận đúng mọi mã trong chuỗi."""

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


@pytest.fixture(scope="module")
def thukho_h(client):
    return _login(client, "thukho", "123456")


def _a_brewhouse_line(client, admin_h):
    """Dây chuyền nấu (ProductionLine.kind="brewhouse") dùng cho test — lấy lại nếu đã có
    (idempotent), tạo mới nếu chưa có (seed.py không seed sẵn dây chuyền loại brewhouse)."""
    existing = client.get("/api/lines", headers=admin_h, params={"kind": "brewhouse"}).json()
    if existing:
        return existing[0]["line_id"]
    r = client.post("/api/lines", headers=admin_h,
                    json={"code": "BREW-TEST-01", "name": "Nhà nấu test", "kind": "brewhouse"})
    assert r.status_code == 201, r.text
    return r.json()["line_id"]


@pytest.fixture(scope="module")
def brewhouse_line_id(client, admin_h):
    return _a_brewhouse_line(client, admin_h)


def _declare_pending(client, headers, stage, scope_type, scope_id, product_id=None):
    """Khai báo đạt mọi chỉ tiêu bắt buộc đang "pending" cho scope này — cần thiết vì các
    stage "len_men_phu"/"thanh_pham" dùng chung toàn cục, module test khác (VD
    test_stage_qc.py) có thể đã gán thêm nhóm mandatory cho stage này trước đó."""
    q = f"/api/brewing/qc-status?stage={stage}&scope_type={scope_type}&scope_id={scope_id}"
    if product_id:
        q += f"&product_id={product_id}"
    status = client.get(q, headers=headers).json()
    for p in status["required"]:
        if p["code"] in status["pending"]:
            lsl = p["lsl"] if p["lsl"] is not None else 0
            usl = p["usl"] if p["usl"] is not None else lsl + 10
            r = client.post("/api/brewing/qc-results", headers=headers,
                            json={"stage": stage, "scope_type": scope_type, "scope_id": scope_id,
                                  "parameter": p["code"], "value": (lsl + usl) / 2,
                                  "lower_limit": lsl, "upper_limit": usl})
            assert r.status_code == 201, r.text


def test_full_chain_traceable_from_lot_to_unit(client, admin_h, vanhanh_h, thukho_h, brewhouse_line_id):
    suffix = "TRACECHAIN01"

    # 1) Lô NVL thật trong Kho phân xưởng (điều kiện bắt buộc để dùng cho mẻ nấu).
    lot_code = f"LOT-{suffix}"
    r = client.post("/api/warehouse/receive", headers=admin_h,
                    json={"lot_code": lot_code, "quantity": 500, "uom": "kg", "location": "Kho phân xưởng"})
    assert r.status_code == 200, r.text
    lots = client.get("/api/lots", headers=admin_h).json()
    lot = next(l for l in lots if l["lot_code"] == lot_code)

    # 2) Mã nấu (tự tạo lô LM tương ứng) + mẻ (BrewBatch) + gán nguyên liệu từ lô NVL trên.
    brew_code = f"BR-{suffix}"
    lm_code = f"LM-{suffix}"
    order = client.post("/api/brewing/orders", headers=admin_h,
                        json={"order_code": f"LN-{suffix}", "auto_from_bom": False, "planned_volume_hl": 100})
    assert order.status_code == 201, order.text
    order_id = order.json()["brew_order_id"]
    b = client.post("/api/brewing/brews", headers=vanhanh_h,
                    json={"brew_code": brew_code, "wort_type": "Dịch test", "volume_hl": 100,
                          "lm_code": lm_code, "tank_lm": f"T-{suffix}", "brew_order_id": order_id})
    assert b.status_code == 201, b.text
    brew_id = b.json()["brew_id"]

    batch_code = "501"
    batch = client.post(f"/api/brewing/brews/{brew_id}/batches", headers=vanhanh_h,
                        json={"batch_code": batch_code, "line_id": brewhouse_line_id})
    assert batch.status_code == 201, batch.text
    batch_id = batch.json()["batch_id"]

    mat = client.post(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/materials", headers=vanhanh_h,
                      json={"lot_id": lot["lot_id"], "quantity": 100, "material_name": "NVL test"})
    assert mat.status_code == 201, mat.text

    # 3) KCS duyệt lô LM (điều kiện để lọc).
    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment = next(f for f in ferments if f["lm_code"] == lm_code)
    _declare_pending(client, admin_h, "len_men_phu", "ferment", f"{lm_code}__len_men_phu")
    approve_ferment = client.post(f"/api/brewing/ferments/{ferment['ferment_id']}/approve", headers=admin_h)
    assert approve_ferment.status_code == 200, approve_ferment.text

    # 4) Lọc từ tank LM sang tank BBT — bắt buộc chọn 1 Lệnh lọc (không phối, 1 tank) trước.
    filter_order = client.post("/api/brewing/filter-orders", headers=admin_h,
                               json={"order_code": f"LOC-{suffix}", "blend_mode": "khong_phoi",
                                     "tank_ferment_ids": [ferment["ferment_id"]], "planned_volume_hl": 1000})
    assert filter_order.status_code == 201, filter_order.text
    filter_code = f"FL-{suffix}"
    bbt = f"BBT-{suffix}"
    f = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": filter_code, "beer_type": "Bia test", "wort_type": "Dịch test",
                          "filter_order_id": filter_order.json()["filter_order_id"], "to_bbt": bbt})
    assert f.status_code == 201, f.text
    filter_id = f.json()["filter_id"]
    filter_tanks = client.get(f"/api/brewing/filters/{filter_id}/tanks", headers=admin_h).json()
    fin = client.post(f"/api/brewing/filters/{filter_id}/tanks/{filter_tanks[0]['line_id']}/finish",
                      headers=vanhanh_h, json={"v_dich_hl": 100, "nuoc_bai_khi_hl": 0,
                                                "batch_number": f"B-{suffix}", "order_number": f"O-{suffix}", "batch_seq_no": "1"})
    assert fin.status_code == 200, fin.text
    _declare_pending(client, vanhanh_h, "loc", "filter", filter_code)
    approve_f = client.post(f"/api/brewing/filters/{filter_id}/approve", headers=admin_h)
    assert approve_f.status_code == 200, approve_f.text

    # Danh sách Lọc phải hiện đúng mã nấu nguồn (trước đây luôn trống — không được ghi lại).
    filters = client.get("/api/brewing/filters", headers=admin_h).json()
    filter_row = next(r for r in filters if r["filter_code"] == filter_code)
    assert filter_row["brew_code"] == brew_code

    # 5) Chiết từ tank BBT.
    bottle_code = f"CH-{suffix}"
    bo = client.post("/api/brewing/bottles", headers=vanhanh_h,
                     json={"bottle_code": bottle_code, "beer_type": "Bia test", "from_bbt": bbt})
    assert bo.status_code == 201, bo.text
    bottle_id = bo.json()["bottle_id"]
    bo_fin = client.post(f"/api/brewing/bottles/{bottle_id}/finish", headers=vanhanh_h,
                         json={"v_cap_chiet_hl": 100, "ca1": 50, "ca2": 50})
    assert bo_fin.status_code == 200, bo_fin.text

    # Danh sách Chiết phải hiện đúng mã lọc nguồn (trước đây luôn trống — không được ghi lại).
    bottles = client.get("/api/brewing/bottles", headers=admin_h).json()
    bottle_row = next(r for r in bottles if r["bottle_code"] == bottle_code)
    assert bottle_row["filter_code"] == filter_code

    # 6) KCS duyệt chiết — CHỈ đóng hồ sơ, không còn sinh vỉ/keg Kho TP (WMS) nữa (approve_bottle
    # đã tháo khỏi WMS; Lô thành phẩm là nơi thay thế duy nhất, xem
    # tests/test_batch_pack_lot_wms.py cho phần truy xuất tới finished_goods_unit qua pipeline mới).
    _declare_pending(client, admin_h, "thanh_pham", "bottle", f"{bottle_code}__thanh_pham")
    approve_bottle = client.post(f"/api/brewing/bottles/{bottle_id}/approve", headers=admin_h)
    assert approve_bottle.status_code == 200, approve_bottle.text

    # ---- Truy xuất phải nhận diện ĐÚNG mọi mã trong chuỗi (trước đây chỉ nhận mã mẻ/lô NVL cũ) ----
    back_from_bottle = client.get(f"/api/trace/backward?code={bottle_code}", headers=admin_h)
    assert back_from_bottle.status_code == 200, back_from_bottle.text
    tree = back_from_bottle.json()
    assert tree["type"] == "bottle" and tree["code"] == bottle_code

    def _codes(node):
        out = {node["code"]}
        for c in node.get("children", []):
            out |= _codes(c)
        return out

    def _find(node, code):
        if node["code"] == code:
            return node
        for c in node.get("children", []):
            found = _find(c, code)
            if found:
                return found
        return None

    codes_upstream = _codes(tree)
    assert bottle_code in codes_upstream
    assert filter_code in codes_upstream
    assert lm_code in codes_upstream
    assert brew_code in codes_upstream
    assert batch_code in codes_upstream
    assert lot_code in codes_upstream

    # ---- Mỗi node phải kèm tóm tắt chỉ tiêu chất lượng đúng công đoạn của nó ----
    lot_node = _find(tree, lot_code)
    assert [q["stage"] for q in lot_node["qc"]] == ["lot"]

    batch_node = _find(tree, batch_code)
    assert [q["stage"] for q in batch_node["qc"]] == ["nau"]
    assert batch_node["qc"][0]["can_release"] is True  # không có nhóm mandatory nào áp cho "nau" (product_id=None) trong test này

    ferment_node = _find(tree, lm_code)
    assert {q["stage"] for q in ferment_node["qc"]} == {"len_men_chinh", "len_men_phu"}

    filter_node = _find(tree, filter_code)
    assert [q["stage"] for q in filter_node["qc"]] == ["loc"]

    bottle_node = _find(tree, bottle_code)
    assert {q["stage"] for q in bottle_node["qc"]} == {"thanh_pham"}
    thanh_pham_qc = next(q for q in bottle_node["qc"] if q["stage"] == "thanh_pham")
    assert thanh_pham_qc["can_release"] is True  # vừa khai báo đủ ở bước 6 trước khi duyệt chiết

    # Truy xuôi từ lô NVL phải ra tới tận mã chiết (bottle) — chiết là node cuối module cũ còn
    # với tới (không còn tự sinh vỉ/keg Kho TP, xem ghi chú ở bước 6).
    fwd_from_lot = client.get(f"/api/trace/forward?code={lot_code}", headers=admin_h)
    assert fwd_from_lot.status_code == 200, fwd_from_lot.text
    codes_downstream = _codes(fwd_from_lot.json())
    assert bottle_code in codes_downstream

    # Recall simulation từ lô NVL phải liệt kê đúng mã chiết bị ảnh hưởng.
    recall = client.get(f"/api/trace/recall?code={lot_code}", headers=admin_h)
    assert recall.status_code == 200, recall.text
    recall_codes = {a["code"] for a in recall.json()["affected"]}
    assert bottle_code in recall_codes


def test_find_node_prefers_lot_no_over_unrelated_brew_batch_code(client, admin_h, vanhanh_h, brewhouse_line_id):
    """Bug thực tế: BrewBatch.batch_code ("số mẻ", VD "1") chỉ duy nhất TRONG 1 NĂM, không
    duy nhất toàn hệ thống (xem models/brewing.py::BrewBatch) — nếu find_node tra nó ngang
    hàng các mã thật-sự-duy-nhất (brew_code, lm_code, filter_code, bottle_code...) thì gõ
    "số lô bia" (BottleRecord.lot_no) trùng với 1 số mẻ của 1 mã nấu KHÁC hoàn toàn không
    liên quan sẽ bị nuốt nhầm sang mẻ nấu mồ côi đó (Truy ngược/Hồ sơ điện tử ra rỗng ở
    Lên men/Lọc/Chiết dù dữ liệu thật vẫn nối đầy đủ — xem FIND_NODE_ORDER/ALIAS_LOOKUP)."""
    collision_code = "42"

    # 1) Mẻ nấu MỒ CÔI dùng đúng batch_code trùng với lot_no sẽ đặt cho chiết bên dưới —
    # không lên men/lọc/chiết gì tiếp, để lộ rõ nếu find_node resolve nhầm sang đây.
    decoy_order = client.post("/api/brewing/orders", headers=admin_h,
                              json={"order_code": "LN-COLLIDE-DECOY", "auto_from_bom": False, "planned_volume_hl": 50})
    assert decoy_order.status_code == 201, decoy_order.text
    decoy_brew = client.post("/api/brewing/brews", headers=vanhanh_h,
                             json={"brew_code": "BR-COLLIDE-DECOY", "wort_type": "Dịch mồ côi", "volume_hl": 50,
                                   "lm_code": "LM-COLLIDE-DECOY", "tank_lm": "T-COLLIDE-DECOY",
                                   "brew_order_id": decoy_order.json()["brew_order_id"]})
    assert decoy_brew.status_code == 201, decoy_brew.text
    decoy_batch = client.post(f"/api/brewing/brews/{decoy_brew.json()['brew_id']}/batches", headers=vanhanh_h,
                              json={"batch_code": collision_code, "line_id": brewhouse_line_id})
    assert decoy_batch.status_code == 201, decoy_batch.text

    # 2) Chuỗi thật (Nấu→Lên men→Lọc→Chiết) — mã chiết đặt "số lô bia" (lot_no) TRÙNG với
    # batch_code mồ côi ở trên.
    suffix = "TRACECOLLIDE"
    order = client.post("/api/brewing/orders", headers=admin_h,
                        json={"order_code": f"LN-{suffix}", "auto_from_bom": False, "planned_volume_hl": 100})
    assert order.status_code == 201, order.text
    brew_code = f"BR-{suffix}"
    lm_code = f"LM-{suffix}"
    b = client.post("/api/brewing/brews", headers=vanhanh_h,
                    json={"brew_code": brew_code, "wort_type": "Dịch test", "volume_hl": 100,
                          "lm_code": lm_code, "tank_lm": f"T-{suffix}", "brew_order_id": order.json()["brew_order_id"]})
    assert b.status_code == 201, b.text
    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment = next(f for f in ferments if f["lm_code"] == lm_code)
    _declare_pending(client, admin_h, "len_men_phu", "ferment", f"{lm_code}__len_men_phu")
    approve_ferment = client.post(f"/api/brewing/ferments/{ferment['ferment_id']}/approve", headers=admin_h)
    assert approve_ferment.status_code == 200, approve_ferment.text

    filter_order = client.post("/api/brewing/filter-orders", headers=admin_h,
                               json={"order_code": f"LOC-{suffix}", "blend_mode": "khong_phoi",
                                     "tank_ferment_ids": [ferment["ferment_id"]], "planned_volume_hl": 1000})
    assert filter_order.status_code == 201, filter_order.text
    filter_code = f"FL-{suffix}"
    bbt = f"BBT-{suffix}"
    f = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": filter_code, "beer_type": "Bia test", "wort_type": "Dịch test",
                          "filter_order_id": filter_order.json()["filter_order_id"], "to_bbt": bbt})
    assert f.status_code == 201, f.text
    filter_tanks = client.get(f"/api/brewing/filters/{f.json()['filter_id']}/tanks", headers=admin_h).json()
    fin = client.post(f"/api/brewing/filters/{f.json()['filter_id']}/tanks/{filter_tanks[0]['line_id']}/finish",
                      headers=vanhanh_h, json={"v_dich_hl": 100, "nuoc_bai_khi_hl": 0,
                                                "batch_number": f"B-{suffix}", "order_number": f"O-{suffix}", "batch_seq_no": "1"})
    assert fin.status_code == 200, fin.text
    _declare_pending(client, vanhanh_h, "loc", "filter", filter_code)
    approve_f = client.post(f"/api/brewing/filters/{f.json()['filter_id']}/approve", headers=admin_h)
    assert approve_f.status_code == 200, approve_f.text

    bottle_code = f"CH-{suffix}"
    bo = client.post("/api/brewing/bottles", headers=vanhanh_h,
                     json={"bottle_code": bottle_code, "beer_type": "Bia test", "from_bbt": bbt,
                           "lot_no": collision_code})
    assert bo.status_code == 201, bo.text

    # find_node("TRACE-COLLIDE-42") phải ra ĐÚNG mã chiết (bottle, qua ALIAS_LOOKUP lot_no),
    # KHÔNG phải mẻ nấu mồ côi (brew_batch) — Truy ngược phải thấy đủ lm_code/brew_code/
    # filter_code của chuỗi thật, không rỗng.
    back = client.get(f"/api/trace/backward?code={collision_code}", headers=admin_h)
    assert back.status_code == 200, back.text
    tree = back.json()
    assert tree["type"] == "bottle" and tree["code"] == bottle_code

    def _codes(node):
        out = {node["code"]}
        for c in node.get("children", []):
            out |= _codes(c)
        return out

    codes_upstream = _codes(tree)
    assert filter_code in codes_upstream
    assert lm_code in codes_upstream
    assert brew_code in codes_upstream
    assert "BR-COLLIDE-DECOY" not in codes_upstream
