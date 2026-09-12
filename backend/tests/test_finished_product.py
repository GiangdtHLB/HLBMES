"""Test Sản phẩm (thành phẩm/SKU đóng gói, FinishedProduct) — khác Dịch bia (Product):
CRUD danh mục, chọn khi chiết (BatchPackLot.finished_product_id, pipeline "Mẻ sản xuất"), và
gán chỉ tiêu thành phẩm theo SKU cụ thể (StageQcGroup.finished_product_id) — vẫn tương thích
ngược với các nhóm chỉ tiêu cũ chỉ gán theo dịch bia (product_id).
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


def _make_batch(client, admin_h):
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(x for x in vers if x["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                          "planned_qty": 1000, "allow_shortage": True})
    assert b.status_code == 201, b.text
    return b.json()["batch_id"]


def _run_batch_to_completed(client, admin_h, batch_id):
    for target in ("ready", "running"):
        r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": target})
        assert r.status_code == 200, r.text
    aq = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": 1000})
    assert aq.status_code == 200, aq.text
    fin = client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={})
    assert fin.status_code == 200, fin.text
    r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "completed"})
    assert r.status_code == 200, r.text


def _make_filter_lot(client, admin_h, suffix):
    batch_id = _make_batch(client, admin_h)
    _run_batch_to_completed(client, admin_h, batch_id)
    t = client.post("/api/batch-tanks", headers=admin_h,
                    json={"batch_ids": [batch_id], "tank_code": f"TANK-{suffix}"})
    assert t.status_code == 201, t.text
    tank_id = t.json()["tank_id"]
    bbt = client.post("/api/lines", headers=admin_h,
                      json={"code": f"BBT-{suffix}", "name": f"Tank thành phẩm {suffix}", "kind": "tank_bbt"})
    assert bbt.status_code == 201, bbt.text
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": f"FLOT-{suffix}", "to_bbt": bbt.json()["code"],
        "sources": [{"source_type": "tank", "source_tank_id": tank_id}],
    })
    assert draw.status_code == 201, draw.text
    return draw.json()["filter_lot_id"]


def _finish_only_source(client, admin_h, filter_lot_id, v_drawn=900):
    src = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()[0]
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    fin = client.put(f"/api/batch-filter-lots/batches/{batches[0]['batch_link_id']}/finish", headers=admin_h,
                     json={"draws": [{"source_link_id": src["link_id"], "dich_nha_hl": v_drawn}],
                          "nuoc_bai_khi_hl": 0})
    assert fin.status_code == 200, fin.text


def _make_pack_lot(client, admin_h, filter_lot_id, suffix, finished_product_id=None, qty=500):
    pack = client.post(f"/api/batch-filter-lots/{filter_lot_id}/pack-lots", headers=admin_h,
                       json={"qty": qty, "pack_lot_code": f"PKG-{suffix}", "lot_no": f"LOT-{suffix}",
                             "finished_product_id": finished_product_id})
    assert pack.status_code == 201, pack.text
    return pack.json()["pack_lot_id"]


def test_finished_product_crud(client, admin_h):
    create = client.post("/api/finished-products", headers=admin_h,
                         json={"code": "SKU-LON-330", "name": "Lon 330ml", "uom": "lon"})
    assert create.status_code == 201, create.text
    fp_id = create.json()["finished_product_id"]

    listed = client.get("/api/finished-products", headers=admin_h).json()
    assert any(fp["finished_product_id"] == fp_id for fp in listed)

    update = client.put(f"/api/finished-products/{fp_id}", headers=admin_h,
                        json={"code": "SKU-LON-330", "name": "Lon 330ml (sửa)", "uom": "lon"})
    assert update.status_code == 200, update.text
    assert update.json()["name"] == "Lon 330ml (sửa)"


def test_approve_pack_lot_scoped_by_finished_product(client, admin_h):
    """Nhóm chỉ tiêu thành phẩm gán theo finished_product_id — chỉ chặn duyệt các lô thành
    phẩm (BatchPackLot) đã chọn đúng SKU đó, không ảnh hưởng lô khác/không chọn SKU."""
    fp = client.post("/api/finished-products", headers=admin_h,
                     json={"code": "SKU-CHAI-500", "name": "Chai 500ml", "uom": "chai"})
    assert fp.status_code == 201, fp.text
    fp_id = fp.json()["finished_product_id"]

    group_id, code = _make_group_with_param(client, admin_h, "FPSCOPED")
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": "thanh_pham", "group_id": group_id,
                             "finished_product_id": fp_id, "mandatory": True})
    assert link.status_code == 201, link.text
    assert link.json()["finished_product_id"] == fp_id

    fl = _make_filter_lot(client, admin_h, "FP-TEST-01")
    _finish_only_source(client, admin_h, fl)
    pack_lot_id = _make_pack_lot(client, admin_h, fl, "FP-TEST-01", finished_product_id=fp_id)

    st = client.get(f"/api/brewing/qc-status?stage=thanh_pham&scope_type=batch_pack_lot&"
                    f"scope_id={pack_lot_id}&finished_product_id={fp_id}", headers=admin_h).json()
    assert code in st["pending"]

    blocked = client.post(f"/api/batch-pack-lots/{pack_lot_id}/approve", headers=admin_h)
    assert blocked.status_code == 409, blocked.text

    rec = client.post("/api/brewing/qc-results", headers=admin_h,
                      json={"stage": "thanh_pham", "scope_type": "batch_pack_lot", "scope_id": pack_lot_id,
                            "parameter": code, "value": 5, "lower_limit": 1, "upper_limit": 10})
    assert rec.status_code == 201, rec.text

    ok = client.post(f"/api/batch-pack-lots/{pack_lot_id}/approve", headers=admin_h)
    assert ok.status_code == 200, ok.text
    assert ok.json()["approved"] is True

    # Lô khác không chọn SKU này thì không bị nhóm chỉ tiêu trên chặn.
    fl2 = _make_filter_lot(client, admin_h, "FP-TEST-OTHER")
    _finish_only_source(client, admin_h, fl2)
    other_pack_lot_id = _make_pack_lot(client, admin_h, fl2, "FP-TEST-OTHER")
    other_st = client.get(f"/api/brewing/qc-status?stage=thanh_pham&scope_type=batch_pack_lot&"
                          f"scope_id={other_pack_lot_id}", headers=admin_h).json()
    assert not any(p["code"] == code for p in other_st["required"])


def test_finished_product_scoping_by_beer_type_applies_across_skus(client, admin_h):
    """Nhóm chỉ tiêu thành phẩm gán theo Loại bia (beer_type_id, finished_product_id để
    trống) phải áp dụng cho MỌI SKU thuộc Loại bia đó — không cần khớp finished_product_id
    tuyệt đối. Đây là chỗ thay thế hành vi cũ (gán theo product_id/Dịch bia): stage=thanh_pham
    giờ tra theo Loại bia (KHÔNG còn theo product_id — xem
    services/qc_catalog.py::PRODUCT_SCOPED_STAGES), vì 1 Loại bia có thể ra nhiều Dịch bia
    khác oP nhưng vẫn phải chung 1 bộ chỉ tiêu thành phẩm."""
    bt = client.post("/api/beer-types", headers=admin_h, json={"code": "COMPATTYPE", "name": "Loại bia compat"})
    assert bt.status_code == 201, bt.text
    beer_type_id = bt.json()["beer_type_id"]

    prod = client.post("/api/products", headers=admin_h,
                       json={"code": "DICHBIA-COMPAT", "name": "Dịch bia compat test", "uom": "L",
                             "beer_type_id": beer_type_id})
    assert prod.status_code == 201, prod.text
    product_id = prod.json()["product_id"]

    fp = client.post("/api/finished-products", headers=admin_h,
                     json={"code": "SKU-COMPAT-01", "name": "SKU compat 01", "uom": "chai",
                           "product_id": product_id})
    assert fp.status_code == 201, fp.text
    fp_id = fp.json()["finished_product_id"]

    group_id, code = _make_group_with_param(client, admin_h, "COMPATLEGACY")
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": "thanh_pham", "group_id": group_id,
                             "beer_type_id": beer_type_id, "mandatory": True})
    assert link.status_code == 201, link.text
    assert link.json()["finished_product_id"] is None
    assert link.json()["beer_type_id"] == beer_type_id

    fl = _make_filter_lot(client, admin_h, "COMPAT-01")
    _finish_only_source(client, admin_h, fl)
    pack_lot_id = _make_pack_lot(client, admin_h, fl, "COMPAT-01")
    # beer_type_id không tự gắn qua nguồn trong test này nên gán thủ công qua qc-status params.

    st = client.get(f"/api/brewing/qc-status?stage=thanh_pham&scope_type=batch_pack_lot&"
                    f"scope_id={pack_lot_id}&beer_type_id={beer_type_id}&finished_product_id={fp_id}",
                    headers=admin_h).json()
    assert any(p["code"] == code for p in st["required"])


def test_same_param_in_common_and_override_group_deduped_override_wins(client, admin_h):
    """Cùng 1 mã chỉ tiêu (VD "Độ cồn") được gán qua CẢ nhóm áp dụng chung (theo Loại bia) LẪN
    nhóm gán riêng cho 1 SKU cụ thể (finished_product_id), mỗi nhóm đặt ngưỡng khác nhau —
    required_params_for_stage phải CHỈ trả về 1 dòng duy nhất cho mã đó (không trùng lặp),
    và ngưỡng phải lấy theo nhóm gán riêng (cụ thể hơn), không phải nhóm chung."""
    bt = client.post("/api/beer-types", headers=admin_h, json={"code": "OVERRIDETYPE", "name": "Loại bia override"})
    assert bt.status_code == 201, bt.text
    beer_type_id = bt.json()["beer_type_id"]

    fp = client.post("/api/finished-products", headers=admin_h,
                     json={"code": "SKU-OVERRIDE-01", "name": "SKU override 01", "uom": "chai"})
    assert fp.status_code == 201, fp.text
    fp_id = fp.json()["finished_product_id"]

    param = client.post("/api/qc/parameters", headers=admin_h,
                        json={"code": "ABV-OVR", "name": "Độ cồn", "lsl": 4.0, "usl": 5.0})
    assert param.status_code == 201, param.text
    param_id = param.json()["param_id"]

    common_group = client.post("/api/qc/groups", headers=admin_h,
                               json={"code": "TP-COMMON-OVR", "name": "Thành phẩm chung (override test)"})
    assert common_group.status_code == 201, common_group.text
    common_group_id = common_group.json()["group_id"]
    common_item = client.post(f"/api/qc/groups/{common_group_id}/items", headers=admin_h,
                              json={"param_id": param_id, "mandatory": True,
                                    "lsl_override": 4.0, "usl_override": 4.5})
    assert common_item.status_code == 201, common_item.text
    link_common = client.post("/api/qc/stage-groups", headers=admin_h,
                              json={"stage": "thanh_pham", "group_id": common_group_id,
                                    "beer_type_id": beer_type_id, "mandatory": True})
    assert link_common.status_code == 201, link_common.text

    override_group = client.post("/api/qc/groups", headers=admin_h,
                                 json={"code": "TP-OVERRIDE-SKU", "name": "Thành phẩm riêng SKU"})
    assert override_group.status_code == 201, override_group.text
    override_group_id = override_group.json()["group_id"]
    override_item = client.post(f"/api/qc/groups/{override_group_id}/items", headers=admin_h,
                                json={"param_id": param_id, "mandatory": True,
                                      "lsl_override": 4.5, "usl_override": 4.6})
    assert override_item.status_code == 201, override_item.text
    link_override = client.post("/api/qc/stage-groups", headers=admin_h,
                                json={"stage": "thanh_pham", "group_id": override_group_id,
                                      "finished_product_id": fp_id, "mandatory": True})
    assert link_override.status_code == 201, link_override.text

    fl = _make_filter_lot(client, admin_h, "OVERRIDE-01")
    _finish_only_source(client, admin_h, fl)
    pack_lot_id = _make_pack_lot(client, admin_h, fl, "OVERRIDE-01", finished_product_id=fp_id)

    st = client.get(f"/api/brewing/qc-status?stage=thanh_pham&scope_type=batch_pack_lot&"
                    f"scope_id={pack_lot_id}&beer_type_id={beer_type_id}&finished_product_id={fp_id}",
                    headers=admin_h).json()
    matches = [p for p in st["required"] if p["code"] == "ABV-OVR"]
    assert len(matches) == 1, f"Phải chỉ có 1 dòng cho mã chỉ tiêu trùng, thấy {len(matches)}"
    assert matches[0]["lsl"] == 4.5 and matches[0]["usl"] == 4.6
