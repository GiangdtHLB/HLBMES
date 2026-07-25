"""Test hồ sơ điện tử theo lô (GET /api/brewing/lot-record) — tổng hợp NVL→mẻ nấu→
lên men→lọc→chiết cho 1 lô thành 1 tài liệu, ráp lại từ genealogy.trace_backward +
qc_catalog.stage_qc_status + braumat_import (Ghi chép nấu). Dựng chuỗi y hệt
test_traceability_brew_chain.py::test_full_chain_traceable_from_lot_to_pallet."""

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


def _declare_pending(client, headers, stage, scope_type, scope_id, product_id=None, beer_type_id=None):
    q = f"/api/brewing/qc-status?stage={stage}&scope_type={scope_type}&scope_id={scope_id}"
    if product_id:
        q += f"&product_id={product_id}"
    if beer_type_id:
        q += f"&beer_type_id={beer_type_id}"
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


@pytest.fixture(scope="module")
def chain(client, admin_h, vanhanh_h, thukho_h, brewhouse_line_id):
    suffix = "LOTRECORD01"

    lot_code = f"LOT-{suffix}"
    r = client.post("/api/warehouse/receive", headers=admin_h,
                    json={"lot_code": lot_code, "quantity": 500, "uom": "kg", "location": "Kho phân xưởng"})
    assert r.status_code == 200, r.text
    lots = client.get("/api/lots", headers=admin_h).json()
    lot = next(l for l in lots if l["lot_code"] == lot_code)

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

    batch_code = "502"
    batch = client.post(f"/api/brewing/brews/{brew_id}/batches", headers=vanhanh_h,
                        json={"batch_code": batch_code, "line_id": brewhouse_line_id})
    assert batch.status_code == 201, batch.text
    batch_id = batch.json()["batch_id"]

    mat = client.post(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/materials", headers=vanhanh_h,
                      json={"lot_id": lot["lot_id"], "quantity": 100, "material_name": "NVL test"})
    assert mat.status_code == 201, mat.text

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
    filter_id = f.json()["filter_id"]
    filter_tanks = client.get(f"/api/brewing/filters/{filter_id}/tanks", headers=admin_h).json()
    fin = client.post(f"/api/brewing/filters/{filter_id}/tanks/{filter_tanks[0]['line_id']}/finish",
                      headers=vanhanh_h, json={"v_dich_hl": 100, "nuoc_bai_khi_hl": 0})
    assert fin.status_code == 200, fin.text
    approve_f = client.post(f"/api/brewing/filters/{filter_id}/approve", headers=admin_h)
    assert approve_f.status_code == 200, approve_f.text

    bottle_code = f"CH-{suffix}"
    bo = client.post("/api/brewing/bottles", headers=vanhanh_h,
                     json={"bottle_code": bottle_code, "beer_type": "Bia test", "from_bbt": bbt})
    assert bo.status_code == 201, bo.text
    bo_fin = client.post(f"/api/brewing/bottles/{bo.json()['bottle_id']}/finish", headers=vanhanh_h,
                         json={"v_cap_chiet_hl": 100, "ca1": 50, "ca2": 50})
    assert bo_fin.status_code == 200, bo_fin.text

    _declare_pending(client, admin_h, "thanh_pham", "bottle", f"{bottle_code}__thanh_pham")
    approve_bottle = client.post(f"/api/brewing/bottles/{bo.json()['bottle_id']}/approve", headers=admin_h)
    assert approve_bottle.status_code == 200, approve_bottle.text

    return {"lot_code": lot_code, "brew_code": brew_code, "lm_code": lm_code,
            "batch_code": batch_code, "filter_code": filter_code, "bottle_code": bottle_code,
            "lot_no": bo.json().get("lot_no"), "brew_id": brew_id}


def test_lot_record_by_bottle_code(client, admin_h, chain):
    r = client.get(f"/api/brewing/lot-record?code={chain['bottle_code']}", headers=admin_h)
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["root"]["code"] == chain["bottle_code"]
    assert len(data["lots"]) == 1 and data["lots"][0]["lot_code"] == chain["lot_code"]
    assert data["lots"][0]["qc"]["lot_code"] == chain["lot_code"]

    assert len(data["brew_batches"]) == 1
    batch = data["brew_batches"][0]
    assert batch["batch_code"] == chain["batch_code"]
    assert batch["brew_code"] == chain["brew_code"]
    assert len(batch["materials"]) == 1 and batch["materials"][0]["quantity"] == 100
    assert batch["qc"]["stage"] == "nau"
    assert "manual" in batch["process_log"] and "spec" in batch["process_log"]
    assert "checkpoints" in batch["process_log"]
    assert batch["started_at"] is not None and batch["ended_at"] is None  # chưa bấm Kết thúc mẻ

    assert len(data["brews"]) == 1 and data["brews"][0]["brew_code"] == chain["brew_code"]

    assert len(data["ferments"]) == 1
    ferment = data["ferments"][0]
    assert ferment["lm_code"] == chain["lm_code"]
    assert set(ferment["qc"].keys()) == {"len_men_chinh", "len_men_phu"}
    assert ferment["qc"]["len_men_phu"]["can_release"] is True
    assert ferment["started_at"] is not None  # brew_date kế từ mã nấu

    assert len(data["filters"]) == 1 and data["filters"][0]["filter_code"] == chain["filter_code"]
    assert data["filters"][0]["started_at"] is not None

    assert len(data["bottles"]) == 1
    bottle = data["bottles"][0]
    assert bottle["bottle_code"] == chain["bottle_code"]
    assert set(bottle["qc"].keys()) == {"thanh_pham"}
    assert bottle["qc"]["thanh_pham"]["can_release"] is True
    assert bottle["started_at"] is not None and bottle["ended_at"] is not None  # đã finish() chiết


def test_lot_record_by_lot_no_alias(client, admin_h, chain):
    """Tra bằng số lô bia (lot_no, bí danh không unique) phải ra đúng kết quả như bottle_code."""
    r = client.get(f"/api/brewing/lot-record?code={chain['lot_no']}", headers=admin_h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["bottles"][0]["bottle_code"] == chain["bottle_code"]


def test_lot_record_unknown_code_404(client, admin_h):
    r = client.get("/api/brewing/lot-record?code=DOES-NOT-EXIST", headers=admin_h)
    assert r.status_code == 404, r.text


def test_brew_forward_record_stops_at_bottle(client, admin_h, chain):
    """Truy xuôi theo nấu: từ 1 lô nấu, lấy xuôi chiều mẻ/lên men/lọc/chiết — KHÔNG có
    trường pallet/thành phẩm nào trong kết quả (dừng ở chiết), khác genealogy.trace_forward
    thông thường vốn đi tới tận pallet đã tạo ở fixture chain (approve_bottle)."""
    r = client.get(f"/api/brewing/brew-forward-record?brew_id={chain['brew_id']}", headers=admin_h)
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["root"]["code"] == chain["brew_code"]
    assert data["lots"] == []
    assert "pallets" not in data and "bottle_pallets" not in data
    assert data["tree"]["type"] == "brew" and data["tree"]["code"] == chain["brew_code"]
    # "brew" không có started_at/ended_at riêng — tính từ (các) mẻ con; mẻ chưa bấm Kết thúc
    # nên end phải là None dù start đã có (auto lúc tạo mẻ).
    assert data["tree"]["period"]["start"] is not None
    assert data["tree"]["period"]["end"] is None

    ferment_node = data["tree"]["children"][0]
    assert ferment_node["type"] == "ferment" and ferment_node["period"]["start"] is not None
    filter_node = ferment_node["children"][0]
    assert filter_node["type"] == "filter" and filter_node["period"]["start"] is not None
    bottle_node = filter_node["children"][0]
    assert bottle_node["type"] == "bottle" and bottle_node["period"]["end"] is not None  # đã finish() chiết

    assert len(data["brew_batches"]) == 1
    assert data["brew_batches"][0]["batch_code"] == chain["batch_code"]

    assert len(data["ferments"]) == 1 and data["ferments"][0]["lm_code"] == chain["lm_code"]
    assert len(data["filters"]) == 1 and data["filters"][0]["filter_code"] == chain["filter_code"]
    assert len(data["bottles"]) == 1 and data["bottles"][0]["bottle_code"] == chain["bottle_code"]


def test_brew_forward_record_unknown_brew_id_404(client, admin_h):
    r = client.get("/api/brewing/brew-forward-record?brew_id=does-not-exist", headers=admin_h)
    assert r.status_code == 404, r.text


def _a_beer_type(client, admin_h, code, name):
    r = client.post("/api/beer-types", headers=admin_h, json={"code": code, "name": name})
    assert r.status_code == 201, r.text
    return r.json()["beer_type_id"]


def _a_product(client, admin_h, code, name, beer_type_id=None):
    r = client.post("/api/products", headers=admin_h,
                    json={"code": code, "name": name, "uom": "L", "beer_type_id": beer_type_id})
    assert r.status_code == 201, r.text
    return r.json()["product_id"]


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


def test_lot_record_filter_and_bottle_qc_scoped_by_beer_type(client, admin_h, vanhanh_h):
    """_filter_detail/_bottle_detail phải tra chỉ tiêu Lọc/Chiết/Thành phẩm theo beer_type_id
    (Loại bia) — không phải product_id (Dịch bia) — mirror
    test_beer_type.py::test_beer_type_inherits_through_filter_and_bottle_and_scopes_qc_across_products.
    Trước fix, lot_record.py truyền product_id vào stage_qc_status cho stage loc/chiet/
    thanh_pham nên nhóm chỉ tiêu gán theo beer_type_id (không gán product_id) không hiện lên
    trong hồ sơ điện tử — pending sẽ rỗng sai."""
    suffix = "LOTRECBT01"
    bt_id = _a_beer_type(client, admin_h, f"BT-{suffix}", "Loại bia test")
    product_id = _a_product(client, admin_h, f"PRD-{suffix}", "Dịch test", beer_type_id=bt_id)

    loc_group_id, loc_code = _make_group_with_param(client, admin_h, f"LOC{suffix}")
    link_loc = client.post("/api/qc/stage-groups", headers=admin_h,
                           json={"stage": "loc", "group_id": loc_group_id, "beer_type_id": bt_id,
                                 "mandatory": True})
    assert link_loc.status_code == 201, link_loc.text

    tp_group_id, tp_code = _make_group_with_param(client, admin_h, f"TP{suffix}")
    link_tp = client.post("/api/qc/stage-groups", headers=admin_h,
                          json={"stage": "thanh_pham", "group_id": tp_group_id, "beer_type_id": bt_id,
                                "mandatory": True})
    assert link_tp.status_code == 201, link_tp.text

    order = client.post("/api/brewing/orders", headers=admin_h,
                        json={"order_code": f"LN-{suffix}", "auto_from_bom": False, "planned_volume_hl": 100})
    assert order.status_code == 201, order.text
    b = client.post("/api/brewing/brews", headers=vanhanh_h,
                    json={"brew_code": f"BR-{suffix}", "wort_type": "Dịch test", "volume_hl": 100,
                          "lm_code": f"LM-{suffix}", "tank_lm": f"T-{suffix}",
                          "brew_order_id": order.json()["brew_order_id"], "product_id": product_id})
    assert b.status_code == 201, b.text
    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment = next(f for f in ferments if f["lm_code"] == f"LM-{suffix}")
    _declare_pending(client, admin_h, "len_men_phu", "ferment", f"{ferment['lm_code']}__len_men_phu")
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
    assert f.json()["beer_type_id"] == bt_id
    filter_id = f.json()["filter_id"]
    filter_tanks = client.get(f"/api/brewing/filters/{filter_id}/tanks", headers=admin_h).json()
    fin = client.post(f"/api/brewing/filters/{filter_id}/tanks/{filter_tanks[0]['line_id']}/finish",
                      headers=vanhanh_h, json={"v_dich_hl": 100, "nuoc_bai_khi_hl": 0})
    assert fin.status_code == 200, fin.text
    # Duyệt mẻ lọc để tank BBT đủ điều kiện chiết (eligible_for_chiet đòi qc_approved) —
    # khai chỉ tiêu Lọc trước khi duyệt, nên required (không phải pending) là nơi chứng
    # minh việc tra theo beer_type_id (nhóm vẫn match dù đã khai xong).
    _declare_pending(client, admin_h, "loc", "filter", filter_code, beer_type_id=bt_id)
    approve_f = client.post(f"/api/brewing/filters/{filter_id}/approve", headers=admin_h)
    assert approve_f.status_code == 200, approve_f.text

    bottle_code = f"CH-{suffix}"
    bo = client.post("/api/brewing/bottles", headers=vanhanh_h,
                     json={"bottle_code": bottle_code, "beer_type": "Bia test", "from_bbt": bbt})
    assert bo.status_code == 201, bo.text
    assert bo.json()["beer_type_id"] == bt_id
    bo_fin = client.post(f"/api/brewing/bottles/{bo.json()['bottle_id']}/finish", headers=vanhanh_h,
                         json={"v_cap_chiet_hl": 100, "ca1": 50, "ca2": 50})
    assert bo_fin.status_code == 200, bo_fin.text

    r = client.get(f"/api/brewing/lot-record?code={bottle_code}", headers=admin_h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["filters"]) == 1
    # Nhóm gán theo beer_type_id (không có product_id) phải hiện ra trong required — trước
    # fix, lot_record.py truyền product_id nên required_params_for_stage lọc theo nhánh
    # beer_type_id.is_(None), bỏ sót nhóm này (required sẽ không chứa loc_code/tp_code).
    assert loc_code in {p["code"] for p in data["filters"][0]["qc"]["required"]}
    assert len(data["bottles"]) == 1
    tp_qc = data["bottles"][0]["qc"]["thanh_pham"]
    assert tp_code in {p["code"] for p in tp_qc["required"]}
    assert tp_code in tp_qc["pending"]


def test_delete_filter_removes_stale_genealogy_edge(client, admin_h, vanhanh_h):
    """delete_filter phải dọn cạnh phả hệ ferment->filter — nếu không, cạnh còn trỏ tới
    filter_id đã xóa hẳn, hiện thành node mã ngẫu nhiên vô nghĩa mãi mãi khi truy xuôi lại
    từ lô lên men đó (bug thực tế gặp phải khi xóa-tạo lại lọc nhiều lần lúc phát triển)."""
    suffix = "DELEDGE01"
    order = client.post("/api/brewing/orders", headers=admin_h,
                        json={"order_code": f"LN-{suffix}", "auto_from_bom": False, "planned_volume_hl": 100})
    assert order.status_code == 201, order.text
    b = client.post("/api/brewing/brews", headers=vanhanh_h,
                    json={"brew_code": f"BR-{suffix}", "wort_type": "Dịch test", "volume_hl": 100,
                          "lm_code": f"LM-{suffix}", "tank_lm": f"T-{suffix}",
                          "brew_order_id": order.json()["brew_order_id"]})
    assert b.status_code == 201, b.text
    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment = next(f for f in ferments if f["lm_code"] == f"LM-{suffix}")
    _declare_pending(client, admin_h, "len_men_phu", "ferment", f"{ferment['lm_code']}__len_men_phu")
    approve = client.post(f"/api/brewing/ferments/{ferment['ferment_id']}/approve", headers=admin_h)
    assert approve.status_code == 200, approve.text

    filter_order = client.post("/api/brewing/filter-orders", headers=admin_h,
                               json={"order_code": f"LOC-{suffix}", "blend_mode": "khong_phoi",
                                     "tank_ferment_ids": [ferment["ferment_id"]], "planned_volume_hl": 1000})
    assert filter_order.status_code == 201, filter_order.text
    f = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": f"FL-{suffix}", "beer_type": "Bia test", "wort_type": "Dịch test",
                          "filter_order_id": filter_order.json()["filter_order_id"], "to_bbt": f"BBT-{suffix}"})
    assert f.status_code == 201, f.text
    filter_id = f.json()["filter_id"]

    before = client.get(f"/api/trace/forward?node_type=ferment&node_id={ferment['ferment_id']}",
                        headers=admin_h).json()
    assert any(c["type"] == "filter" and c["code"] == f"FL-{suffix}" for c in before["children"])

    delete = client.delete(f"/api/brewing/filters/{filter_id}", headers=vanhanh_h)
    assert delete.status_code == 204, delete.text

    after = client.get(f"/api/trace/forward?node_type=ferment&node_id={ferment['ferment_id']}",
                       headers=admin_h).json()
    assert after["children"] == []


def test_workshop_usage_history_shows_stage_batch_lot(client, admin_h, chain):
    """NVL gán cho mẻ nấu (qua chain fixture) phải xuất hiện trong lịch sử xuất dùng NVL của
    Kho phân xưởng với đúng công đoạn/mẻ/lô — khác "Xuất tự do" (StockMovement mode="tu_do")
    vốn không phân biệt được xuất tay và xuất dùng sản xuất."""
    r = client.get("/api/warehouse/workshop-usage-history", headers=admin_h)
    assert r.status_code == 200, r.text
    rows = r.json()
    row = next(x for x in rows if x["lot_code"] == chain["lot_code"] and x["stage"] == "Nấu")
    assert chain["batch_code"] in row["batch_label"]
    assert chain["brew_code"] in row["batch_label"]
    assert row["quantity"] == 100
    assert row["actor"] == "vanhanh"
