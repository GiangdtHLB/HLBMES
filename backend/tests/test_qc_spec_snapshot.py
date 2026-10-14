"""Test chụp (snapshot) chỉ tiêu bắt buộc + ngưỡng (Min/Max) NGAY LÚC TẠO tank lên men/lô lọc/
lô thành phẩm — yêu cầu người dùng 2026-10-13: Danh mục sửa Min/Max của 1 chỉ tiêu SAU KHI 1 mẻ
đã tạo/ghi nhận giá trị không còn được đổi ngược cách đánh giá của mẻ đó — chỉ mẻ MỚI tạo SAU
mới áp ngưỡng mới. Xem services/qc_catalog.py::_snapshot_required_params/stage_qc_status,
models/batch_pipeline.py::BatchTank/BatchFilterLot/BatchPackLot.qc_spec_snapshot.
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


def _make_group_with_param(client, admin_h, suffix, lsl=1, usl=10):
    p = client.post("/api/qc/parameters", headers=admin_h,
                    json={"code": f"CT_{suffix}", "name": f"Chỉ tiêu {suffix}", "lsl": lsl, "usl": usl})
    assert p.status_code == 201, p.text
    param_id = p.json()["param_id"]
    g = client.post("/api/qc/groups", headers=admin_h,
                    json={"code": f"GRP_{suffix}", "name": f"Nhóm {suffix}"})
    assert g.status_code == 201, g.text
    group_id = g.json()["group_id"]
    it = client.post(f"/api/qc/groups/{group_id}/items", headers=admin_h,
                     json={"param_id": param_id, "mandatory": True})
    assert it.status_code == 201, it.text
    item_id = it.json()["item_id"]
    return group_id, item_id, param_id, f"CT_{suffix}"


def _reconfigure_item(client, admin_h, group_id, item_id, param_id, lsl_override, usl_override):
    upd = client.put(f"/api/qc/groups/{group_id}/items/{item_id}", headers=admin_h,
                     json={"param_id": param_id, "mandatory": True,
                          "lsl_override": lsl_override, "usl_override": usl_override})
    assert upd.status_code == 200, upd.text


def _make_batch(client, admin_h):
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(x for x in vers if x["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                          "planned_qty": 1000, "allow_shortage": True})
    assert b.status_code == 201, b.text
    return b.json()["batch_id"], v["product_id"]


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


def _make_tank(client, admin_h, suffix):
    batch_id, product_id = _make_batch(client, admin_h)
    _run_batch_to_completed(client, admin_h, batch_id)
    t = client.post("/api/batch-tanks", headers=admin_h,
                    json={"batch_ids": [batch_id], "tank_code": f"TANK-{suffix}"})
    assert t.status_code == 201, t.text
    return t.json()["tank_id"], product_id


def _make_filter_lot(client, admin_h, suffix, tank_id):
    bbt = client.post("/api/lines", headers=admin_h,
                      json={"code": f"BBT-{suffix}", "name": f"Tank thành phẩm {suffix}", "kind": "tank_bbt"})
    assert bbt.status_code == 201, bbt.text
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": f"FLOT-{suffix}", "to_bbt": bbt.json()["code"],
        "sources": [{"source_type": "tank", "source_tank_id": tank_id}],
        "category": "Bia lon",
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


def _make_pack_lot(client, admin_h, filter_lot_id, suffix, qty=500):
    pack = client.post(f"/api/batch-filter-lots/{filter_lot_id}/pack-lots", headers=admin_h,
                       json={"qty": qty, "pack_lot_code": f"PKG-{suffix}", "lot_no": f"LOT-{suffix}"})
    assert pack.status_code == 201, pack.text
    return pack.json()["pack_lot_id"]


def _lsl_usl_for_code(required, code):
    row = next(p for p in required if p["code"] == code)
    return row["lsl"], row["usl"]


def test_len_men_chinh_snapshot_frozen_at_tank_creation(client, admin_h):
    group_id, item_id, param_id, code = _make_group_with_param(client, admin_h, "LMCSNAP01", lsl=1, usl=10)
    tank_id, product_id = _make_tank(client, admin_h, "LMCSNAP01")
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": "len_men_chinh", "group_id": group_id,
                             "product_id": product_id, "mandatory": True})
    assert link.status_code == 201, link.text

    # Tank đã tạo TRƯỚC link gán nhóm -> snapshot của nó rỗng THẬT (không phải giả lập bằng
    # scope_id không tồn tại) -> required rỗng, KHÔNG tra Danh mục sống để "vớt" ra chỉ tiêu vừa
    # gán sau (mirror đúng ca thực tế lô lọc cũ 2026-10-14: tạo trước khi Danh mục có nhóm/ngưỡng
    # -> không được hiện Min/Max của Danh mục hiện tại).
    scope_id1 = f"{tank_id}__len_men_chinh"
    st1 = client.get(f"/api/brewing/qc-status?stage=len_men_chinh&scope_type=batch_tank&"
                     f"scope_id={scope_id1}&product_id={product_id}", headers=admin_h).json()
    assert st1["required"] == []

    # Tank MỚI (tạo SAU khi đã gán nhóm) mới có chỉ tiêu này trong snapshot.
    tank_id2, _ = _make_tank(client, admin_h, "LMCSNAP02")
    scope_id2 = f"{tank_id2}__len_men_chinh"
    st2 = client.get(f"/api/brewing/qc-status?stage=len_men_chinh&scope_type=batch_tank&"
                     f"scope_id={scope_id2}&product_id={product_id}", headers=admin_h).json()
    assert _lsl_usl_for_code(st2["required"], code) == (1, 10)

    # Sửa ngưỡng trong Danh mục SAU khi tank2 đã tạo.
    _reconfigure_item(client, admin_h, group_id, item_id, param_id, lsl_override=2, usl_override=8)

    # Tank KHÔNG tồn tại (mirror "tạo trước khi có snapshot", snapshot=None/rỗng) -> required
    # rỗng, KHÔNG tra Danh mục sống nữa (yêu cầu người dùng 2026-10-14: "lô cũ cũng không được
    # tra sống... không có thì thôi" — phát hiện sau khi thấy 117 lô lọc cũ hiện Min/Max MỚI
    # nhất dù lúc ghi nhận hoàn toàn chưa có ngưỡng nào).
    no_snapshot_check = client.get(f"/api/brewing/qc-status?stage=len_men_chinh&scope_type=batch_tank&"
                                   f"scope_id=KHONGTONTAI__len_men_chinh&product_id={product_id}",
                                   headers=admin_h).json()
    assert no_snapshot_check["required"] == []

    # ...nhưng tank2 (đã tạo TRƯỚC khi sửa) vẫn phải giữ nguyên snapshot cũ (1/10).
    st2_after = client.get(f"/api/brewing/qc-status?stage=len_men_chinh&scope_type=batch_tank&"
                           f"scope_id={scope_id2}&product_id={product_id}", headers=admin_h).json()
    assert _lsl_usl_for_code(st2_after["required"], code) == (1, 10)

    # Tank MỚI tạo SAU khi sửa -> áp ngưỡng MỚI (2/8).
    tank_id3, _ = _make_tank(client, admin_h, "LMCSNAP03")
    scope_id3 = f"{tank_id3}__len_men_chinh"
    st3 = client.get(f"/api/brewing/qc-status?stage=len_men_chinh&scope_type=batch_tank&"
                     f"scope_id={scope_id3}&product_id={product_id}", headers=admin_h).json()
    assert _lsl_usl_for_code(st3["required"], code) == (2, 8)


def test_len_men_phu_uses_same_tank_snapshot_separate_stage_key(client, admin_h):
    """BatchTank.qc_spec_snapshot là dict {"len_men_chinh": [...], "len_men_phu": [...]} — xác
    nhận 2 stage trên CÙNG 1 tank không lẫn vào nhau."""
    group_chinh_id, item_chinh_id, param_chinh_id, code_chinh = _make_group_with_param(
        client, admin_h, "LMPSNAPCHINH01", lsl=1, usl=10)
    group_phu_id, item_phu_id, param_phu_id, code_phu = _make_group_with_param(
        client, admin_h, "LMPSNAPPHU01", lsl=3, usl=6)
    tank_id, product_id = _make_tank(client, admin_h, "LMPSNAP01")
    lc = client.post("/api/qc/stage-groups", headers=admin_h,
                     json={"stage": "len_men_chinh", "group_id": group_chinh_id,
                          "product_id": product_id, "mandatory": True})
    assert lc.status_code == 201, lc.text
    lp = client.post("/api/qc/stage-groups", headers=admin_h,
                     json={"stage": "len_men_phu", "group_id": group_phu_id,
                          "product_id": product_id, "mandatory": True})
    assert lp.status_code == 201, lp.text

    tank_id2, _ = _make_tank(client, admin_h, "LMPSNAP02")
    chinh_scope = f"{tank_id2}__len_men_chinh"
    phu_scope = f"{tank_id2}__len_men_phu"
    st_chinh = client.get(f"/api/brewing/qc-status?stage=len_men_chinh&scope_type=batch_tank&"
                          f"scope_id={chinh_scope}&product_id={product_id}", headers=admin_h).json()
    st_phu = client.get(f"/api/brewing/qc-status?stage=len_men_phu&scope_type=batch_tank&"
                        f"scope_id={phu_scope}&product_id={product_id}", headers=admin_h).json()
    assert code_chinh in {p["code"] for p in st_chinh["required"]}
    assert code_chinh not in {p["code"] for p in st_phu["required"]}
    assert code_phu in {p["code"] for p in st_phu["required"]}
    assert code_phu not in {p["code"] for p in st_chinh["required"]}


def test_loc_snapshot_frozen_at_filter_lot_creation(client, admin_h):
    group_id, item_id, param_id, code = _make_group_with_param(client, admin_h, "LOCSNAP01", lsl=4.4, usl=4.6)
    tank_id, _product_id = _make_tank(client, admin_h, "LOCSNAP01")
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": "loc", "group_id": group_id, "category": "Bia lon", "mandatory": True})
    assert link.status_code == 201, link.text

    filter_lot_id = _make_filter_lot(client, admin_h, "LOCSNAP01", tank_id)
    st = client.get(f"/api/brewing/qc-status?stage=loc&scope_type=batch_filter_lot&"
                    f"scope_id={filter_lot_id}&category=Bia%20lon", headers=admin_h).json()
    assert _lsl_usl_for_code(st["required"], code) == (4.4, 4.6)

    _reconfigure_item(client, admin_h, group_id, item_id, param_id, lsl_override=5.0, usl_override=5.5)

    # Lô lọc này ghi nhận ngay 4.75 — với ngưỡng CŨ đã chụp (4.4-4.6) thì FAIL (vượt max 4.6),
    # đúng ca thực tế người dùng báo (lô 1420, Độ cồn 4.75 > 4.6 phải fail, không được "pass").
    rec = client.post("/api/brewing/qc-results", headers=admin_h,
                      json={"stage": "loc", "scope_type": "batch_filter_lot", "scope_id": filter_lot_id,
                            "parameter": code, "value": 4.75, "lower_limit": 4.4, "upper_limit": 4.6})
    assert rec.status_code == 201, rec.text
    assert rec.json()["status"] == "fail"

    st_after = client.get(f"/api/brewing/qc-status?stage=loc&scope_type=batch_filter_lot&"
                          f"scope_id={filter_lot_id}&category=Bia%20lon", headers=admin_h).json()
    assert _lsl_usl_for_code(st_after["required"], code) == (4.4, 4.6)   # không bị đổi theo Danh mục mới
    assert st_after["has_fail"] is True

    tank_id2, _ = _make_tank(client, admin_h, "LOCSNAP02")
    filter_lot_id2 = _make_filter_lot(client, admin_h, "LOCSNAP02", tank_id2)
    st2 = client.get(f"/api/brewing/qc-status?stage=loc&scope_type=batch_filter_lot&"
                     f"scope_id={filter_lot_id2}&category=Bia%20lon", headers=admin_h).json()
    assert _lsl_usl_for_code(st2["required"], code) == (5.0, 5.5)   # lô MỚI áp ngưỡng mới


def test_thanh_pham_snapshot_frozen_at_pack_lot_creation(client, admin_h):
    group_id, item_id, param_id, code = _make_group_with_param(client, admin_h, "TPSNAP01", lsl=1, usl=10)
    tank_id, _product_id = _make_tank(client, admin_h, "TPSNAP01")
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": "thanh_pham", "group_id": group_id,
                            "category": "Bia lon", "mandatory": True})
    assert link.status_code == 201, link.text

    filter_lot_id = _make_filter_lot(client, admin_h, "TPSNAP01", tank_id)
    _finish_only_source(client, admin_h, filter_lot_id)
    pack_lot_id = _make_pack_lot(client, admin_h, filter_lot_id, "TPSNAP01")

    st = client.get(f"/api/brewing/qc-status?stage=thanh_pham&scope_type=batch_pack_lot&"
                    f"scope_id={pack_lot_id}&category=Bia%20lon", headers=admin_h).json()
    assert _lsl_usl_for_code(st["required"], code) == (1, 10)

    _reconfigure_item(client, admin_h, group_id, item_id, param_id, lsl_override=2, usl_override=9)

    st_after = client.get(f"/api/brewing/qc-status?stage=thanh_pham&scope_type=batch_pack_lot&"
                          f"scope_id={pack_lot_id}&category=Bia%20lon", headers=admin_h).json()
    assert _lsl_usl_for_code(st_after["required"], code) == (1, 10)   # không bị đổi theo Danh mục mới

    tank_id2, _ = _make_tank(client, admin_h, "TPSNAP02")
    filter_lot_id2 = _make_filter_lot(client, admin_h, "TPSNAP02", tank_id2)
    _finish_only_source(client, admin_h, filter_lot_id2)
    pack_lot_id2 = _make_pack_lot(client, admin_h, filter_lot_id2, "TPSNAP02")
    st2 = client.get(f"/api/brewing/qc-status?stage=thanh_pham&scope_type=batch_pack_lot&"
                     f"scope_id={pack_lot_id2}&category=Bia%20lon", headers=admin_h).json()
    assert _lsl_usl_for_code(st2["required"], code) == (2, 9)   # lô MỚI áp ngưỡng mới


def test_nau_stage_not_affected_still_uses_live_catalog(client, admin_h):
    """Yêu cầu người dùng 2026-10-13 CHỈ áp dụng lên men chính/phụ, lọc, chiết — mẻ nấu (stage
    "nau", scope_type "batch") KHÔNG có snapshot, vẫn tra Danh mục SỐNG như trước (không đổi
    hành vi)."""
    group_id, item_id, param_id, code = _make_group_with_param(client, admin_h, "NAUNOSNAP01", lsl=1, usl=10)
    batch_id, product_id = _make_batch(client, admin_h)
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": "nau", "group_id": group_id,
                            "product_id": product_id, "mandatory": True})
    assert link.status_code == 201, link.text

    st = client.get(f"/api/brewing/qc-status?stage=nau&scope_type=batch&"
                    f"scope_id={batch_id}&product_id={product_id}", headers=admin_h).json()
    assert _lsl_usl_for_code(st["required"], code) == (1, 10)

    _reconfigure_item(client, admin_h, group_id, item_id, param_id, lsl_override=2, usl_override=8)

    st_after = client.get(f"/api/brewing/qc-status?stage=nau&scope_type=batch&"
                          f"scope_id={batch_id}&product_id={product_id}", headers=admin_h).json()
    assert _lsl_usl_for_code(st_after["required"], code) == (2, 8)   # KHÔNG snapshot -> theo Danh mục mới ngay
