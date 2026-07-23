"""Test Sản phẩm (thành phẩm/SKU đóng gói, FinishedProduct) — khác Dịch bia (Product):
CRUD danh mục, chọn khi chiết (BottleRecord.finished_product_id), và gán chỉ tiêu thành
phẩm theo SKU cụ thể (StageQcGroup.finished_product_id) — vẫn tương thích ngược với các
nhóm chỉ tiêu cũ chỉ gán theo dịch bia (product_id).
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


def test_approve_bottle_scoped_by_finished_product(client, admin_h, vanhanh_h):
    """Nhóm chỉ tiêu thành phẩm gán theo finished_product_id — chỉ chặn duyệt các mã chiết
    đã chọn đúng SKU đó, không ảnh hưởng mã chiết khác/không chọn SKU."""
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

    bottle_code = "CH-FP-TEST-01"
    b = client.post("/api/brewing/bottles", headers=vanhanh_h,
                    json={"bottle_code": bottle_code, "beer_type": "Bia test", "finished_product_id": fp_id})
    assert b.status_code == 201, b.text
    bottle_id = b.json()["bottle_id"]
    b_fin = client.post(f"/api/brewing/bottles/{bottle_id}/finish", headers=vanhanh_h, json={"ca1": 10})
    assert b_fin.status_code == 200, b_fin.text

    st = client.get(f"/api/brewing/qc-status?stage=thanh_pham&scope_type=bottle&"
                    f"scope_id={bottle_code}__thanh_pham&finished_product_id={fp_id}", headers=admin_h).json()
    assert code in st["pending"]

    blocked = client.post(f"/api/brewing/bottles/{bottle_id}/approve", headers=admin_h)
    assert blocked.status_code == 409, blocked.text

    rec = client.post("/api/brewing/qc-results", headers=vanhanh_h,
                      json={"stage": "thanh_pham", "scope_type": "bottle", "scope_id": f"{bottle_code}__thanh_pham",
                            "parameter": code, "value": 5, "lower_limit": 1, "upper_limit": 10})
    assert rec.status_code == 201, rec.text

    ok = client.post(f"/api/brewing/bottles/{bottle_id}/approve", headers=admin_h)
    assert ok.status_code == 200, ok.text
    assert ok.json()["approved"] is True

    # Mã chiết khác không chọn SKU này thì không bị nhóm chỉ tiêu trên chặn.
    other_code = "CH-FP-TEST-OTHER"
    other = client.post("/api/brewing/bottles", headers=vanhanh_h,
                        json={"bottle_code": other_code, "beer_type": "Bia test"})
    assert other.status_code == 201, other.text
    other_st = client.get(f"/api/brewing/qc-status?stage=thanh_pham&scope_type=bottle&"
                          f"scope_id={other_code}__thanh_pham", headers=admin_h).json()
    assert not any(p["code"] == code for p in other_st["required"])


def test_finished_product_scoping_by_beer_type_applies_across_skus(client, admin_h, vanhanh_h):
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

    bottle_code = "CH-COMPAT-01"
    b = client.post("/api/brewing/bottles", headers=vanhanh_h,
                    json={"bottle_code": bottle_code, "beer_type": "Bia test"})
    assert b.status_code == 201, b.text
    bottle_id = b.json()["bottle_id"]
    # beer_type_id không tự gắn qua from_bbt trong test này nên gán thủ công qua qc-status params.

    st = client.get(f"/api/brewing/qc-status?stage=thanh_pham&scope_type=bottle&"
                    f"scope_id={bottle_code}__thanh_pham&beer_type_id={beer_type_id}&finished_product_id={fp_id}",
                    headers=admin_h).json()
    assert any(p["code"] == code for p in st["required"])


def test_same_param_in_common_and_override_group_deduped_override_wins(client, admin_h, vanhanh_h):
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

    bottle_code = "CH-OVERRIDE-01"
    b = client.post("/api/brewing/bottles", headers=vanhanh_h,
                    json={"bottle_code": bottle_code, "beer_type": "Bia test", "finished_product_id": fp_id})
    assert b.status_code == 201, b.text

    st = client.get(f"/api/brewing/qc-status?stage=thanh_pham&scope_type=bottle&"
                    f"scope_id={bottle_code}__thanh_pham&beer_type_id={beer_type_id}&finished_product_id={fp_id}",
                    headers=admin_h).json()
    matches = [p for p in st["required"] if p["code"] == "ABV-OVR"]
    assert len(matches) == 1, f"Phải chỉ có 1 dòng cho mã chỉ tiêu trùng, thấy {len(matches)}"
    assert matches[0]["lsl"] == 4.5 and matches[0]["usl"] == 4.6
