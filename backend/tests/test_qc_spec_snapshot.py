"""Test chỉ tiêu bắt buộc theo công đoạn sản xuất (mẻ nấu/lên men chính-phụ/lọc/chiết/thành
phẩm) LUÔN tra Danh mục SỐNG — kể cả với tank/lô lọc/lô thành phẩm đã tạo TRƯỚC khi nhóm chỉ tiêu
được gán hoặc Min/Max được sửa.

Lịch sử: 2026-10-13 từng đổi sang "chụp ảnh" (snapshot) 1 LẦN DUY NHẤT lúc tạo tank/lô, để Danh
mục sửa Min/Max sau đó không ảnh hưởng ngược các bản ghi đã tạo. Nhưng bug thực tế 2026-10-15 (lô
285/tank B27): tank ĐANG lên men (chưa khóa, chưa xong), nhóm chỉ tiêu "Lên men phụ" được gán VÀO
Danh mục SAU lúc tank được tạo -> snapshot chụp lúc tạo rỗng -> hệ thống báo "Đạt đủ chỉ tiêu bắt
buộc" dù 0 mẫu được nhập, dù nhóm chỉ tiêu ĐANG áp dụng thật ở Danh mục. Việc 1 công đoạn CHƯA XẢY
RA có bắt buộc khai hay không phải luôn phản ánh đúng cấu hình HIỆN TẠI (không phải lịch sử cần
giữ nguyên) — quay lại tra sống hoàn toàn cho `required` (mọi scope_type, không riêng "nau").

Việc KHÔNG được đổi ngược là Min/Max HIỂN THỊ kèm 1 giá trị ĐÃ GHI — nhưng việc đó lấy thẳng từ
`lower_limit`/`upper_limit` đã đóng băng trên CHÍNH QualityResult lúc ghi (xem
qc_catalog.record_stage_result), độc lập hoàn toàn với `required`/Danh mục, không cần snapshot gì
thêm (xem test_recorded_result_keeps_original_bounds_after_catalog_change bên dưới + frontend
app.js::qcMinMaxCellsHtml cho phần hiển thị).

Xem services/qc_catalog.py::stage_qc_status, required_params_for_stage.
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


def _lsl_usl_for_code(required, code):
    row = next(p for p in required if p["code"] == code)
    return row["lsl"], row["usl"]


def test_tank_created_before_group_assigned_still_sees_requirement_once_assigned(client, admin_h):
    """Mirror đúng bug thực tế 2026-10-15 (lô 285/tank B27): tank tạo TRƯỚC khi nhóm "Lên men
    phụ" được gán vào Danh mục -> ngay sau khi gán, required PHẢI thấy chỉ tiêu đó (không được
    rỗng mãi mãi) vì tank chưa khóa/chưa xong công đoạn này."""
    tank_id, product_id = _make_tank(client, admin_h, "LATEGRP01")
    scope_id = f"{tank_id}__len_men_phu"

    # Trước khi gán nhóm: chưa có gì bắt buộc.
    st_before = client.get(f"/api/brewing/qc-status?stage=len_men_phu&scope_type=batch_tank&"
                           f"scope_id={scope_id}&product_id={product_id}", headers=admin_h).json()
    assert st_before["required"] == []
    assert st_before["can_release"] is True   # đúng — chưa có chỉ tiêu nào để thiếu

    # Gán nhóm SAU KHI tank đã tồn tại.
    group_id, item_id, param_id, code = _make_group_with_param(client, admin_h, "LATEGRP01", lsl=1, usl=10)
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": "len_men_phu", "group_id": group_id,
                             "product_id": product_id, "mandatory": True})
    assert link.status_code == 201, link.text

    # Phải thấy NGAY — tank vẫn đang chạy, công đoạn len_men_phu chưa hoàn thành.
    st_after = client.get(f"/api/brewing/qc-status?stage=len_men_phu&scope_type=batch_tank&"
                          f"scope_id={scope_id}&product_id={product_id}", headers=admin_h).json()
    assert code in {p["code"] for p in st_after["required"]}
    assert code in st_after["pending"]
    assert st_after["can_release"] is False   # KHÔNG được "Đạt đủ chỉ tiêu bắt buộc" khi 0 mẫu


def test_reconfigured_threshold_applies_immediately_to_existing_unrecorded_tank(client, admin_h):
    """Sửa Min/Max của 1 chỉ tiêu ĐANG áp dụng cho 1 tank CHƯA ghi chỉ tiêu đó -> required phải
    đổi theo ngay (không còn "đóng băng" theo lúc tank tạo như bản 2026-10-13 cũ)."""
    group_id, item_id, param_id, code = _make_group_with_param(client, admin_h, "LIVEUPD01", lsl=1, usl=10)
    tank_id, product_id = _make_tank(client, admin_h, "LIVEUPD01")
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": "len_men_chinh", "group_id": group_id,
                             "product_id": product_id, "mandatory": True})
    assert link.status_code == 201, link.text
    scope_id = f"{tank_id}__len_men_chinh"

    st1 = client.get(f"/api/brewing/qc-status?stage=len_men_chinh&scope_type=batch_tank&"
                     f"scope_id={scope_id}&product_id={product_id}", headers=admin_h).json()
    assert _lsl_usl_for_code(st1["required"], code) == (1, 10)

    _reconfigure_item(client, admin_h, group_id, item_id, param_id, lsl_override=2, usl_override=8)

    st2 = client.get(f"/api/brewing/qc-status?stage=len_men_chinh&scope_type=batch_tank&"
                     f"scope_id={scope_id}&product_id={product_id}", headers=admin_h).json()
    assert _lsl_usl_for_code(st2["required"], code) == (2, 8)   # đổi ngay, không còn giữ (1,10)


def test_recorded_result_keeps_original_bounds_after_catalog_change(client, admin_h):
    """Giá trị ĐÃ GHI (lô lọc 1487/lô 1420 thực tế) phải giữ NGUYÊN lower_limit/upper_limit/status
    đã đóng băng lúc ghi, dù Danh mục sửa ngưỡng sau đó — xem `recorded` (không phải `required`)
    trong stage_qc_status. required_params_for_stage() không liên quan gì tới việc này (luôn tra
    sống, xem 2 test trên) — lịch sử ĐÃ GHI chỉ đọc đúng cột lưu sẵn trên QualityResult."""
    group_id, item_id, param_id, code = _make_group_with_param(client, admin_h, "FROZEN01", lsl=4.4, usl=4.6)
    tank_id, _product_id = _make_tank(client, admin_h, "FROZEN01")
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": "loc", "group_id": group_id, "category": "Bia lon", "mandatory": True})
    assert link.status_code == 201, link.text
    filter_lot_id = _make_filter_lot(client, admin_h, "FROZEN01", tank_id)

    # Ghi nhận 4.75 với ngưỡng ĐANG áp dụng lúc đó (4.4-4.6) -> vượt max -> fail.
    rec = client.post("/api/brewing/qc-results", headers=admin_h,
                      json={"stage": "loc", "scope_type": "batch_filter_lot", "scope_id": filter_lot_id,
                            "parameter": code, "value": 4.75, "lower_limit": 4.4, "upper_limit": 4.6})
    assert rec.status_code == 201, rec.text
    assert rec.json()["status"] == "fail"

    # Danh mục đổi ngưỡng SAU KHI đã ghi.
    _reconfigure_item(client, admin_h, group_id, item_id, param_id, lsl_override=4.0, usl_override=5.0)

    st_after = client.get(f"/api/brewing/qc-status?stage=loc&scope_type=batch_filter_lot&"
                          f"scope_id={filter_lot_id}&category=Bia%20lon", headers=admin_h).json()
    # `required` (chuẩn hiện tại, để biết còn thiếu gì) đổi theo Danh mục mới ngay.
    assert _lsl_usl_for_code(st_after["required"], code) == (4.0, 5.0)
    # Nhưng giá trị ĐÃ GHI vẫn hiện đúng ngưỡng lúc ghi + kết quả đã chốt — không bị tính lại.
    recorded_row = next(r for r in st_after["recorded"] if r["parameter"] == code)
    assert (recorded_row["lower_limit"], recorded_row["upper_limit"]) == (4.4, 4.6)
    assert recorded_row["status"] == "fail"
    assert st_after["has_fail"] is True


def test_nau_stage_live_catalog_unchanged_behavior(client, admin_h):
    """Mẻ nấu (stage "nau", scope_type "batch") vẫn tra Danh mục sống như trước — hành vi này nay
    áp dụng chung cho MỌI stage, không còn là ngoại lệ riêng của "nau" nữa."""
    group_id, item_id, param_id, code = _make_group_with_param(client, admin_h, "NAULIVE01", lsl=1, usl=10)
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
    assert _lsl_usl_for_code(st_after["required"], code) == (2, 8)
