"""Test chỉ tiêu theo công đoạn sản xuất (mẻ nấu/lên men/lọc/chiết/thành phẩm) — gán nhóm
chỉ tiêu (StageQcGroup) cùng cơ chế NVL, khai báo qua QualityResult dùng chung, chặn "Duyệt
chiết" khi còn thiếu/FAIL chỉ tiêu thành phẩm — và liên kết thật nhiều mẻ nấu vào 1 lô lên men
(FermentBrewLink) thay cho gõ tay số mẻ.
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


def test_stage_qc_group_link_and_list(client, admin_h):
    group_id, _ = _make_group_with_param(client, admin_h, "STAGE1")
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": "chiet", "group_id": group_id, "mandatory": True})
    assert link.status_code == 201, link.text
    assert link.json()["stage"] == "chiet"

    groups = client.get("/api/qc/stage-groups?stage=chiet", headers=admin_h).json()
    assert any(g["group_id"] == group_id for g in groups)

    unlink = client.delete(f"/api/qc/stage-groups/{link.json()['link_id']}", headers=admin_h)
    assert unlink.status_code == 204, unlink.text
    groups_after = client.get("/api/qc/stage-groups?stage=chiet", headers=admin_h).json()
    assert not any(g["link_id"] == link.json()["link_id"] for g in groups_after)


def test_stage_qc_group_update(client, admin_h):
    group_a, _ = _make_group_with_param(client, admin_h, "SGEDIT-A")
    group_b, _ = _make_group_with_param(client, admin_h, "SGEDIT-B")
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": "chiet", "group_id": group_a, "mandatory": True})
    assert link.status_code == 201, link.text
    link_id = link.json()["link_id"]

    # Đổi cờ bắt buộc, giữ nguyên nhóm/phạm vi -> thành công bình thường
    upd = client.put(f"/api/qc/stage-groups/{link_id}", headers=admin_h,
                     json={"stage": "chiet", "group_id": group_a, "mandatory": False})
    assert upd.status_code == 200, upd.text
    assert upd.json()["group_id"] == group_a
    assert upd.json()["mandatory"] is False

    groups = client.get("/api/qc/stage-groups?stage=chiet", headers=admin_h).json()
    updated = next(g for g in groups if g["link_id"] == link_id)
    assert updated["group_id"] == group_a and updated["mandatory"] is False

    # Sửa thành trùng (stage/phạm vi/nhóm) với 1 gán khác đang active -> báo lỗi 409
    other_link = client.post("/api/qc/stage-groups", headers=admin_h,
                             json={"stage": "chiet", "group_id": group_b, "mandatory": True})
    assert other_link.status_code == 201, other_link.text
    dup = client.put(f"/api/qc/stage-groups/{link_id}", headers=admin_h,
                     json={"stage": "chiet", "group_id": group_b, "mandatory": True})
    assert dup.status_code == 409, dup.text

    client.delete(f"/api/qc/stage-groups/{link_id}", headers=admin_h)
    client.delete(f"/api/qc/stage-groups/{other_link.json()['link_id']}", headers=admin_h)


def _a_filter_order_with_tank(client, admin_h, vanhanh_h, suffix, product_id=None, finished_product_id=None):
    """Tạo 1 mã nấu + lô LM đã KCS duyệt + 1 Lệnh lọc (không phối) tối thiểu — dùng cho các
    test chỉ cần 1 FilterRecord tồn tại, không quan tâm số liệu lọc thật. `product_id` (tuỳ
    chọn, phải đã gán Loại bia) để Lệnh lọc tự suy đúng beer_type_id cần test."""
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
    ok = client.post(f"/api/brewing/ferments/{ferment['ferment_id']}/approve", headers=admin_h)
    assert ok.status_code == 200, ok.text
    payload = {"order_code": f"LOC-{suffix}", "blend_mode": "khong_phoi",
               "tank_ferment_ids": [ferment["ferment_id"]], "planned_volume_hl": 1000}
    if finished_product_id is not None:
        payload["finished_product_id"] = finished_product_id
    fo = client.post("/api/brewing/filter-orders", headers=admin_h, json=payload)
    assert fo.status_code == 201, fo.text
    return fo.json()["filter_order_id"]


def test_stage_qc_status_pending_then_declared(client, admin_h, vanhanh_h):
    group_id, code = _make_group_with_param(client, admin_h, "LOCTEST")
    client.post("/api/qc/stage-groups", headers=admin_h,
               json={"stage": "loc", "group_id": group_id, "mandatory": True})

    filter_order_id = _a_filter_order_with_tank(client, admin_h, vanhanh_h, "LOCTEST")
    filter_code = "FL-TEST-01"
    f = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": filter_code, "beer_type": "Bia test", "wort_type": "Dịch test",
                          "filter_order_id": filter_order_id, "to_bbt": f"BBT-{filter_code}"})
    assert f.status_code == 201, f.text

    st = client.get(f"/api/brewing/qc-status?stage=loc&scope_type=filter&scope_id={filter_code}",
                    headers=vanhanh_h).json()
    assert st["pending"] == [code]
    assert st["can_release"] is False

    ok = client.post("/api/brewing/qc-results", headers=vanhanh_h,
                     json={"stage": "loc", "scope_type": "filter", "scope_id": filter_code,
                           "parameter": code, "value": 5, "lower_limit": 1, "upper_limit": 10})
    assert ok.status_code == 201, ok.text
    assert ok.json()["status"] == "pass"

    st2 = client.get(f"/api/brewing/qc-status?stage=loc&scope_type=filter&scope_id={filter_code}",
                     headers=vanhanh_h).json()
    assert st2["pending"] == []
    assert st2["can_release"] is True


def test_loc_common_beertype_and_sku_override_group_deduped_end_to_end(client, admin_h, vanhanh_h):
    """Lọc gán chỉ tiêu theo Loại bia (chung) — nhưng cùng 1 Loại bia vẫn có thể cần chỉ tiêu
    Lọc khác nhau theo Sản phẩm đích (VD Legend chai lọc khác Legend tươi, khai báo 1 lần ở
    Lệnh lọc qua finished_product_id, kế thừa xuống mẻ lọc — xem
    services/filter_order.py::_insert_sub_order + routers/brewing.py::add_filter). Test đi
    trọn đường (Lệnh lọc → mẻ lọc thật) chứ không chỉ gọi thẳng GET qc-status."""
    bt = client.post("/api/beer-types", headers=admin_h, json={"code": "LOCSKUTYPE", "name": "Loại bia lọc SKU"})
    assert bt.status_code == 201, bt.text
    beer_type_id = bt.json()["beer_type_id"]

    prod = client.post("/api/products", headers=admin_h,
                       json={"code": "DICHBIA-LOCSKU", "name": "Dịch bia lọc SKU test", "uom": "L",
                             "beer_type_id": beer_type_id})
    assert prod.status_code == 201, prod.text
    product_id = prod.json()["product_id"]

    fp = client.post("/api/finished-products", headers=admin_h,
                     json={"code": "SKU-LOCSKU-TUOI", "name": "Bia tươi test", "uom": "L"})
    assert fp.status_code == 201, fp.text
    fp_id = fp.json()["finished_product_id"]

    param = client.post("/api/qc/parameters", headers=admin_h,
                        json={"code": "BX-LOCSKU", "name": "Độ Brix", "lsl": 10, "usl": 12})
    assert param.status_code == 201, param.text
    param_id = param.json()["param_id"]

    common_group = client.post("/api/qc/groups", headers=admin_h,
                               json={"code": "LOC-COMMON-SKU", "name": "Lọc chung theo Loại bia"})
    assert common_group.status_code == 201, common_group.text
    common_item = client.post(f"/api/qc/groups/{common_group.json()['group_id']}/items", headers=admin_h,
                              json={"param_id": param_id, "mandatory": True,
                                    "lsl_override": 10, "usl_override": 11})
    assert common_item.status_code == 201, common_item.text
    link_common = client.post("/api/qc/stage-groups", headers=admin_h,
                              json={"stage": "loc", "group_id": common_group.json()["group_id"],
                                    "beer_type_id": beer_type_id, "mandatory": True})
    assert link_common.status_code == 201, link_common.text

    override_group = client.post("/api/qc/groups", headers=admin_h,
                                 json={"code": "LOC-OVERRIDE-SKU", "name": "Lọc riêng theo Sản phẩm"})
    assert override_group.status_code == 201, override_group.text
    override_item = client.post(f"/api/qc/groups/{override_group.json()['group_id']}/items", headers=admin_h,
                                json={"param_id": param_id, "mandatory": True,
                                      "lsl_override": 11, "usl_override": 12})
    assert override_item.status_code == 201, override_item.text
    link_override = client.post("/api/qc/stage-groups", headers=admin_h,
                                json={"stage": "loc", "group_id": override_group.json()["group_id"],
                                      "finished_product_id": fp_id, "mandatory": True})
    assert link_override.status_code == 201, link_override.text

    filter_order_id = _a_filter_order_with_tank(client, admin_h, vanhanh_h, "LOCSKU",
                                                product_id=product_id, finished_product_id=fp_id)
    order_detail = client.get(f"/api/brewing/filter-orders/{filter_order_id}", headers=admin_h).json()
    assert order_detail["beer_type_id"] == beer_type_id
    assert order_detail["finished_product_id"] == fp_id

    filter_code = "FL-LOCSKU-01"
    f = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": filter_code, "beer_type": "Bia test",
                          "filter_order_id": filter_order_id, "to_bbt": "BBT-LOCSKU-01"})
    assert f.status_code == 201, f.text
    assert f.json()["beer_type_id"] == beer_type_id
    assert f.json()["finished_product_id"] == fp_id

    st = client.get(f"/api/brewing/qc-status?stage=loc&scope_type=filter&scope_id={filter_code}&"
                    f"beer_type_id={beer_type_id}&finished_product_id={fp_id}", headers=admin_h).json()
    matches = [p for p in st["required"] if p["code"] == "BX-LOCSKU"]
    assert len(matches) == 1, f"Phải chỉ có 1 dòng cho mã chỉ tiêu trùng, thấy {len(matches)}"
    assert matches[0]["lsl"] == 11 and matches[0]["usl"] == 12

    client.delete(f"/api/qc/stage-groups/{link_common.json()['link_id']}", headers=admin_h)
    client.delete(f"/api/qc/stage-groups/{link_override.json()['link_id']}", headers=admin_h)


def test_nau_common_and_product_scoped_group_deduped_override_wins(client, admin_h):
    """PRODUCT_SCOPED_STAGES (nau/len_men_chinh/len_men_phu) gán theo Dịch bia (product_id),
    không phải Loại bia/SKU — cùng cơ chế "nhóm riêng theo Dịch bia thắng nhóm áp dụng chung"
    phải áp dụng ở đây y hệt Lọc/Thành phẩm (sửa 1 chỗ dùng chung ở
    qc_catalog.py::required_params_for_stage, không phải code riêng từng công đoạn)."""
    prod = client.post("/api/products", headers=admin_h,
                       json={"code": "DICHBIA-NAUOVR", "name": "Dịch bia nấu override test", "uom": "L"})
    assert prod.status_code == 201, prod.text
    product_id = prod.json()["product_id"]

    param = client.post("/api/qc/parameters", headers=admin_h,
                        json={"code": "BX-NAUOVR", "name": "Độ Balling ban đầu", "lsl": 12.0, "usl": 13.0})
    assert param.status_code == 201, param.text
    param_id = param.json()["param_id"]

    common_group = client.post("/api/qc/groups", headers=admin_h,
                               json={"code": "NAU-COMMON-OVR", "name": "Nấu chung (override test)"})
    assert common_group.status_code == 201, common_group.text
    common_item = client.post(f"/api/qc/groups/{common_group.json()['group_id']}/items", headers=admin_h,
                              json={"param_id": param_id, "mandatory": True,
                                    "lsl_override": 12.0, "usl_override": 12.5})
    assert common_item.status_code == 201, common_item.text
    link_common = client.post("/api/qc/stage-groups", headers=admin_h,
                              json={"stage": "nau", "group_id": common_group.json()["group_id"],
                                    "mandatory": True})
    assert link_common.status_code == 201, link_common.text
    assert link_common.json()["product_id"] is None

    override_group = client.post("/api/qc/groups", headers=admin_h,
                                 json={"code": "NAU-OVERRIDE-PROD", "name": "Nấu riêng Dịch bia"})
    assert override_group.status_code == 201, override_group.text
    override_item = client.post(f"/api/qc/groups/{override_group.json()['group_id']}/items", headers=admin_h,
                                json={"param_id": param_id, "mandatory": True,
                                      "lsl_override": 12.5, "usl_override": 13.0})
    assert override_item.status_code == 201, override_item.text
    link_override = client.post("/api/qc/stage-groups", headers=admin_h,
                                json={"stage": "nau", "group_id": override_group.json()["group_id"],
                                      "product_id": product_id, "mandatory": True})
    assert link_override.status_code == 201, link_override.text
    assert link_override.json()["product_id"] == product_id

    st = client.get(f"/api/brewing/qc-status?stage=nau&scope_type=brew_batch&"
                    f"scope_id=MB-NAUOVR-01&product_id={product_id}", headers=admin_h).json()
    matches = [p for p in st["required"] if p["code"] == "BX-NAUOVR"]
    assert len(matches) == 1, f"Phải chỉ có 1 dòng cho mã chỉ tiêu trùng, thấy {len(matches)}"
    assert matches[0]["lsl"] == 12.5 and matches[0]["usl"] == 13.0

    # Dọn dẹp: gỡ liên kết để không làm "ô nhiễm" trạng thái global của stage "nau"
    # cho các module test khác chạy chung 1 DB trong cùng phiên pytest.
    client.delete(f"/api/qc/stage-groups/{link_common.json()['link_id']}", headers=admin_h)
    client.delete(f"/api/qc/stage-groups/{link_override.json()['link_id']}", headers=admin_h)


def test_stage_qc_status_blocked_when_fail(client, admin_h, vanhanh_h):
    group_id, code = _make_group_with_param(client, admin_h, "FAILTEST")
    client.post("/api/qc/stage-groups", headers=admin_h,
               json={"stage": "loc", "group_id": group_id, "mandatory": True})

    filter_order_id = _a_filter_order_with_tank(client, admin_h, vanhanh_h, "FAILTEST")
    filter_code = "FL-TEST-FAIL"
    client.post("/api/brewing/filters", headers=vanhanh_h,
               json={"filter_code": filter_code, "beer_type": "Bia test", "wort_type": "Dịch test",
                     "filter_order_id": filter_order_id, "to_bbt": f"BBT-{filter_code}"})

    fail = client.post("/api/brewing/qc-results", headers=vanhanh_h,
                       json={"stage": "loc", "scope_type": "filter", "scope_id": filter_code,
                             "parameter": code, "value": 20, "lower_limit": 1, "upper_limit": 10})
    assert fail.status_code == 201, fail.text
    assert fail.json()["status"] == "fail"

    st = client.get(f"/api/brewing/qc-status?stage=loc&scope_type=filter&scope_id={filter_code}",
                    headers=vanhanh_h).json()
    assert code not in st["pending"]     # đã khai báo (không còn thiếu chỉ tiêu này)
    assert st["can_release"] is False    # nhưng FAIL nên vẫn không release được


def test_approve_filter_blocked_until_stage_qc_satisfied(client, admin_h, vanhanh_h):
    group_id, code = _make_group_with_param(client, admin_h, "APPROVEFILTER")
    client.post("/api/qc/stage-groups", headers=admin_h,
               json={"stage": "loc", "group_id": group_id, "mandatory": True})

    filter_order_id = _a_filter_order_with_tank(client, admin_h, vanhanh_h, "APPROVEFILTER")
    filter_code = "FL-TEST-APPROVE"
    f = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": filter_code, "beer_type": "Bia test", "wort_type": "Dịch test",
                          "filter_order_id": filter_order_id, "to_bbt": f"BBT-{filter_code}"})
    assert f.status_code == 201, f.text
    filter_id = f.json()["filter_id"]
    # filter_code chỉ duy nhất TRONG 1 năm — scope_id thật (qc_catalog.filter_scope_id) phải kèm
    # năm để khớp đúng bản ghi approve_filter tra cứu, không lẫn với mã trùng ở năm khác.
    filter_scope_id = f"{f.json()['filter_year']}-{filter_code}"

    # KCS ký duyệt (quyền quality.release) — vanhanh (operator) không có quyền này.
    forbidden = client.post(f"/api/brewing/filters/{filter_id}/approve", headers=vanhanh_h)
    assert forbidden.status_code == 403, forbidden.text

    blocked = client.post(f"/api/brewing/filters/{filter_id}/approve", headers=admin_h)
    assert blocked.status_code == 409, blocked.text

    # Khai báo hết TẤT CẢ chỉ tiêu bắt buộc hiện có cho stage "loc" (nhóm này cộng dồn với
    # LOCTEST/FAILTEST khai báo ở các test trước trong cùng file/DB module-scoped).
    st = client.get(f"/api/brewing/qc-status?stage=loc&scope_type=filter&scope_id={filter_scope_id}",
                    headers=vanhanh_h).json()
    for p in st["required"]:
        rec = client.post("/api/brewing/qc-results", headers=vanhanh_h,
                          json={"stage": "loc", "scope_type": "filter", "scope_id": filter_scope_id,
                                "parameter": p["code"], "value": 5,
                                "lower_limit": p["lsl"] or 1, "upper_limit": p["usl"] or 10})
        assert rec.status_code == 201, rec.text

    # approve_filter yêu cầu đã kết thúc hết tank (xem routers/brewing.py::approve_filter) —
    # phải "Kết thúc" tank TRƯỚC khi duyệt KCS.
    tanks = client.get(f"/api/brewing/filters/{filter_id}/tanks", headers=admin_h).json()
    fin = client.post(f"/api/brewing/filters/{filter_id}/tanks/{tanks[0]['line_id']}/finish",
                      headers=vanhanh_h, json={"v_dich_hl": 100, "nuoc_bai_khi_hl": 0,
                                                "batch_number": "B-TEST-APPROVE", "order_number": "O-TEST-APPROVE", "batch_seq_no": "1"})
    assert fin.status_code == 200, fin.text

    ok = client.post(f"/api/brewing/filters/{filter_id}/approve", headers=admin_h)
    assert ok.status_code == 200, ok.text
    assert ok.json()["qc_approved"] is True

    already_approved = client.post(f"/api/brewing/filters/{filter_id}/approve", headers=admin_h)
    assert already_approved.status_code == 409, already_approved.text

    listed = client.get("/api/brewing/filters", headers=admin_h).json()
    row = next(r for r in listed if r["filter_id"] == filter_id)
    assert row["qc_approved"] is True
    assert row["qc_approved_by"] == "admin"


def test_approve_bottle_blocked_until_stage_qc_satisfied(client, admin_h, vanhanh_h):
    group_id, code = _make_group_with_param(client, admin_h, "THANHPHAM")
    client.post("/api/qc/stage-groups", headers=admin_h,
               json={"stage": "thanh_pham", "group_id": group_id, "mandatory": True})

    bottle_code = "CH-TEST-01"
    b = client.post("/api/brewing/bottles", headers=vanhanh_h,
                    json={"bottle_code": bottle_code, "beer_type": "Bia test"})
    assert b.status_code == 201, b.text
    bottle_id = b.json()["bottle_id"]
    bottle_year = b.json()["bottle_year"]
    b_fin = client.post(f"/api/brewing/bottles/{bottle_id}/finish", headers=vanhanh_h, json={"ca1": 10})
    assert b_fin.status_code == 200, b_fin.text

    # KCS ký duyệt (quyền quality.release) — vanhanh (operator) không có quyền này.
    forbidden = client.post(f"/api/brewing/bottles/{bottle_id}/approve", headers=vanhanh_h)
    assert forbidden.status_code == 403, forbidden.text

    blocked = client.post(f"/api/brewing/bottles/{bottle_id}/approve", headers=admin_h)
    assert blocked.status_code == 409, blocked.text

    # bottle_code chỉ duy nhất TRONG 1 năm — scope_id thật (qc_catalog.bottle_scope_id) phải
    # kèm năm để khớp đúng bản ghi approve_bottle tra cứu.
    rec = client.post("/api/brewing/qc-results", headers=vanhanh_h,
                      json={"stage": "thanh_pham", "scope_type": "bottle",
                            "scope_id": f"{bottle_year}-{bottle_code}__thanh_pham",
                            "parameter": code, "value": 5, "lower_limit": 1, "upper_limit": 10})
    assert rec.status_code == 201, rec.text

    ok = client.post(f"/api/brewing/bottles/{bottle_id}/approve", headers=admin_h)
    assert ok.status_code == 200, ok.text
    assert ok.json()["approved"] is True
    assert ok.json()["unit_codes"]


def _a_brew_order(client, admin_h, order_code, product_id=None):
    r = client.post("/api/brewing/orders", headers=admin_h,
                    json={"order_code": order_code, "product_id": product_id, "auto_from_bom": False, "planned_volume_hl": 100})
    assert r.status_code == 201, r.text
    return r.json()["brew_order_id"]


def test_ferment_with_brew_ids_creates_real_links(client, admin_h, vanhanh_h):
    order1 = _a_brew_order(client, admin_h, "LN-TEST-01")
    order2 = _a_brew_order(client, admin_h, "LN-TEST-02")
    b1 = client.post("/api/brewing/brews", headers=vanhanh_h,
                     json={"brew_code": "BR-TEST-01", "wort_type": "Dịch test", "volume_hl": 100,
                           "brew_order_id": order1})
    b2 = client.post("/api/brewing/brews", headers=vanhanh_h,
                     json={"brew_code": "BR-TEST-02", "wort_type": "Dịch test", "volume_hl": 100,
                           "brew_order_id": order2})
    assert b1.status_code == 201 and b2.status_code == 201, (b1.text, b2.text)
    brew_id1, brew_id2 = b1.json()["brew_id"], b2.json()["brew_id"]

    f = client.post("/api/brewing/ferments", headers=vanhanh_h,
                    json={"lm_code": "LM-TEST-01", "wort_type": "Dịch test", "tank_lm": "T-TEST",
                          "volume_hl": 200, "brew_ids": [brew_id1, brew_id2]})
    assert f.status_code == 201, f.text

    ferments = client.get("/api/brewing/ferments", headers=vanhanh_h).json()
    row = next(x for x in ferments["items"] if x["lm_code"] == "LM-TEST-01")
    assert set(row["brew_ids"]) == {brew_id1, brew_id2}
    assert "BR-TEST-01" in row["batch_numbers"] and "BR-TEST-02" in row["batch_numbers"]


def test_required_params_for_stage_product_scoping(client, admin_h):
    group_id, code = _make_group_with_param(client, admin_h, "PRODSCOPED")
    prod = client.post("/api/products", headers=admin_h,
                       json={"code": "BIA-TEST-STAGE", "name": "Bia test stage", "uom": "L"})
    assert prod.status_code == 201, prod.text
    product_id = prod.json()["product_id"]

    client.post("/api/qc/stage-groups", headers=admin_h,
               json={"stage": "nau", "group_id": group_id, "product_id": product_id, "mandatory": True})

    generic = client.get("/api/brewing/qc-status?stage=nau&scope_type=brew&scope_id=BR-NOPROD",
                         headers=admin_h).json()
    assert not any(p["code"] == code for p in generic["required"])

    scoped = client.get(
        f"/api/brewing/qc-status?stage=nau&scope_type=brew&scope_id=BR-PROD&product_id={product_id}",
        headers=admin_h).json()
    assert any(p["code"] == code for p in scoped["required"])


def test_len_men_chinh_and_phu_do_not_share_recorded_values(client, admin_h, vanhanh_h):
    """len_men_chinh và len_men_phu áp cho cùng 1 lô LM nhưng là 2 bộ chỉ tiêu khác nhau —
    khai báo bên này không được tự tính là đã khai báo bên kia (bug đã gặp: dùng chung
    scope_id=lm_code khiến QualityResult lẫn giữa 2 stage)."""
    chinh_group, chinh_code = _make_group_with_param(client, admin_h, "LMCHINH")
    phu_group, phu_code = _make_group_with_param(client, admin_h, "LMPHU")
    client.post("/api/qc/stage-groups", headers=admin_h,
               json={"stage": "len_men_chinh", "group_id": chinh_group, "mandatory": True})
    client.post("/api/qc/stage-groups", headers=admin_h,
               json={"stage": "len_men_phu", "group_id": phu_group, "mandatory": True})

    lm_code = "LM-ISOLATION-TEST"
    scope_chinh = f"{lm_code}__len_men_chinh"
    scope_phu = f"{lm_code}__len_men_phu"

    rec = client.post("/api/brewing/qc-results", headers=vanhanh_h,
                      json={"stage": "len_men_chinh", "scope_type": "ferment", "scope_id": scope_chinh,
                            "parameter": chinh_code, "value": 5, "lower_limit": 1, "upper_limit": 10})
    assert rec.status_code == 201, rec.text

    st_chinh = client.get(f"/api/brewing/qc-status?stage=len_men_chinh&scope_type=ferment&scope_id={scope_chinh}",
                          headers=admin_h).json()
    assert st_chinh["can_release"] is True

    st_phu = client.get(f"/api/brewing/qc-status?stage=len_men_phu&scope_type=ferment&scope_id={scope_phu}",
                        headers=admin_h).json()
    assert st_phu["pending"] == [phu_code]
    assert st_phu["can_release"] is False


def test_stage_qc_result_upserts_not_accumulates_history(client, admin_h, vanhanh_h):
    """Khai lại 1 chỉ tiêu (cùng scope + parameter) phải ĐÈ lên giá trị cũ, không được cộng
    dồn — nếu không, 1 lần khai FAIL cũ sẽ mãi chặn duyệt dù giá trị mới đã đạt (bug đã gặp)."""
    group_id, code = _make_group_with_param(client, admin_h, "UPSERTTEST")
    client.post("/api/qc/stage-groups", headers=admin_h,
               json={"stage": "len_men_phu", "group_id": group_id, "mandatory": True})

    scope_id = "LM-UPSERT-TEST__len_men_phu"
    fail = client.post("/api/brewing/qc-results", headers=vanhanh_h,
                       json={"stage": "len_men_phu", "scope_type": "ferment", "scope_id": scope_id,
                             "parameter": code, "value": 20, "lower_limit": 1, "upper_limit": 10})
    assert fail.status_code == 201 and fail.json()["status"] == "fail", fail.text

    st1 = client.get(f"/api/brewing/qc-status?stage=len_men_phu&scope_type=ferment&scope_id={scope_id}",
                     headers=admin_h).json()
    assert st1["can_release"] is False

    fixed = client.post("/api/brewing/qc-results", headers=vanhanh_h,
                        json={"stage": "len_men_phu", "scope_type": "ferment", "scope_id": scope_id,
                              "parameter": code, "value": 5, "lower_limit": 1, "upper_limit": 10})
    assert fixed.status_code == 201 and fixed.json()["status"] == "pass", fixed.text

    st2 = client.get(f"/api/brewing/qc-status?stage=len_men_phu&scope_type=ferment&scope_id={scope_id}",
                     headers=admin_h).json()
    recorded_for_code = [r for r in st2["recorded"] if r["parameter"] == code]
    assert len(recorded_for_code) == 1, "phải chỉ có 1 bản ghi cho tham số này, không tích lũy lịch sử"
    assert recorded_for_code[0]["status"] == "pass"
    assert code not in st2["pending"]
    # "len_men_phu" là stage dùng chung — module test có thể đã gán thêm nhóm mandatory khác
    # cho stage này ở test trước, nên chỉ kiểm tra riêng tham số của test này, không kiểm can_release toàn cục.


def test_qc_group_delete_blocked_when_linked_to_stage(client, admin_h):
    group_id, code = _make_group_with_param(client, admin_h, "DELBLOCKED")
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": "loc", "group_id": group_id, "mandatory": True})
    assert link.status_code == 201, link.text

    blocked = client.delete(f"/api/qc/groups/{group_id}", headers=admin_h)
    assert blocked.status_code == 409, blocked.text
    assert "công đoạn sản xuất" in blocked.json()["detail"]

    client.delete(f"/api/qc/stage-groups/{link.json()['link_id']}", headers=admin_h)
    ok = client.delete(f"/api/qc/groups/{group_id}", headers=admin_h)
    assert ok.status_code == 204, ok.text

    groups = client.get("/api/qc/groups", headers=admin_h).json()
    assert not any(g["group_id"] == group_id for g in groups)


def test_nuoc_nau_stage_universal_scope_not_beer_type_scoped(client, admin_h):
    """"nuoc_nau" (chỉ tiêu nước nấu bia) dùng chung cho MỌI dịch bia/loại bia — không nằm
    trong PRODUCT_SCOPED_STAGES lẫn BEER_TYPE_SCOPED_STAGES, nên server phải LUÔN ép cả
    product_id lẫn beer_type_id về NULL kể cả khi client cố tình gửi kèm (phòng trường hợp
    gán nhầm phạm vi làm mất tính "áp dụng chung" của nhóm)."""
    bt = client.post("/api/beer-types", headers=admin_h, json={"code": "NUOCNAUBT", "name": "Loại bia test nước nấu"})
    assert bt.status_code == 201, bt.text
    beer_type_id = bt.json()["beer_type_id"]
    prod = client.post("/api/products", headers=admin_h,
                       json={"code": "DICHBIA-NUOCNAU", "name": "Dịch bia test nước nấu", "uom": "L"})
    assert prod.status_code == 201, prod.text
    product_id = prod.json()["product_id"]

    group_id, code = _make_group_with_param(client, admin_h, "NUOCNAU")
    # Cố tình gửi kèm product_id/beer_type_id — server phải bỏ qua cả 2, lưu NULL.
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": "nuoc_nau", "group_id": group_id,
                             "product_id": product_id, "beer_type_id": beer_type_id, "mandatory": True})
    assert link.status_code == 201, link.text
    assert link.json()["product_id"] is None
    assert link.json()["beer_type_id"] is None

    # Sửa cũng phải scrub lại đúng như vậy.
    upd = client.put(f"/api/qc/stage-groups/{link.json()['link_id']}", headers=admin_h,
                     json={"stage": "nuoc_nau", "group_id": group_id,
                           "product_id": product_id, "beer_type_id": beer_type_id, "mandatory": True})
    assert upd.status_code == 200, upd.text
    assert upd.json()["product_id"] is None
    assert upd.json()["beer_type_id"] is None

    # Áp dụng cho CẢ LÔ NẤU (mã nấu/BrewRecord) — 1 khai báo dùng chung cho mọi mẻ bên trong,
    # không truyền product_id vẫn thấy chỉ tiêu (khác PRODUCT_SCOPED_STAGES).
    st1 = client.get("/api/brewing/qc-status?stage=nuoc_nau&scope_type=brew&scope_id=BR-NUOCNAU-01",
                     headers=admin_h).json()
    assert st1["pending"] == [code]

    rec = client.post("/api/brewing/qc-results", headers=admin_h,
                      json={"stage": "nuoc_nau", "scope_type": "brew", "scope_id": "BR-NUOCNAU-01",
                            "parameter": code, "value": 5, "lower_limit": 1, "upper_limit": 10})
    assert rec.status_code == 201, rec.text
    assert rec.json()["status"] == "pass"

    st2 = client.get("/api/brewing/qc-status?stage=nuoc_nau&scope_type=brew&scope_id=BR-NUOCNAU-01",
                     headers=admin_h).json()
    assert st2["pending"] == []
    assert st2["can_release"] is True

    client.delete(f"/api/qc/stage-groups/{link.json()['link_id']}", headers=admin_h)


def test_qc_group_delete_blocked_when_linked_to_material(client, admin_h):
    group_id, code = _make_group_with_param(client, admin_h, "DELBLOCKEDMAT")
    materials = client.get("/api/materials", headers=admin_h).json()
    material_id = materials[0]["material_id"]
    link = client.post(f"/api/materials/{material_id}/qc-groups", headers=admin_h,
                       json={"group_id": group_id, "mandatory": True})
    assert link.status_code == 201, link.text

    blocked = client.delete(f"/api/qc/groups/{group_id}", headers=admin_h)
    assert blocked.status_code == 409, blocked.text
    assert "nguyên liệu" in blocked.json()["detail"]

    client.delete(f"/api/materials/{material_id}/qc-groups/{group_id}", headers=admin_h)
    ok = client.delete(f"/api/qc/groups/{group_id}", headers=admin_h)
    assert ok.status_code == 204, ok.text
