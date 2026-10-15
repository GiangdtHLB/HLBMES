"""Test chặn gán 2 nhóm chỉ tiêu CÙNG phạm vi (stage + product_id/beer_type_id/category/
finished_product_id) nếu chúng TRÙNG mã chỉ tiêu — xem qc_catalog.py::_assert_no_qc_param_overlap.
Trước bản sửa này, required_params_for_stage() gộp cả 2 nhóm rồi dedup theo param.code, nên 1
ngưỡng Min/Max bị bỏ ÂM THẦM mà không ai biết nhóm nào thắng (yêu cầu người dùng 2026-10-14: hỏi
"2 công đoạn thành phẩm gán cùng 1 SKU thì sao" rồi chọn hướng chặn ngay lúc gán).
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


def _make_group_with_param(client, admin_h, suffix, param_code=None):
    """Tạo 1 nhóm chỉ tiêu mới chứa đúng 1 chỉ tiêu. Nếu `param_code` được truyền, dùng lại
    chỉ tiêu ĐÃ TỒN TẠI (để test 2 nhóm khác nhau cùng chứa 1 mã) thay vì tạo chỉ tiêu mới."""
    if param_code:
        code = param_code
    else:
        p = client.post("/api/qc/parameters", headers=admin_h,
                        json={"code": f"CT_{suffix}", "name": f"Chỉ tiêu {suffix}", "lsl": 1, "usl": 10})
        assert p.status_code == 201, p.text
        code = f"CT_{suffix}"
    param_id = client.get("/api/qc/parameters", headers=admin_h).json()
    param_id = next(x["param_id"] for x in param_id if x["code"] == code)
    g = client.post("/api/qc/groups", headers=admin_h,
                    json={"code": f"GRP_{suffix}", "name": f"Nhóm {suffix}"})
    assert g.status_code == 201, g.text
    group_id = g.json()["group_id"]
    it = client.post(f"/api/qc/groups/{group_id}/items", headers=admin_h,
                     json={"param_id": param_id, "mandatory": True})
    assert it.status_code == 201, it.text
    return group_id, code


def test_overlapping_param_blocked_on_create(client, admin_h):
    """2 nhóm cùng chứa 1 mã chỉ tiêu, gán cùng (stage=thanh_pham, mọi loại bia/SKU) -> nhóm thứ
    2 phải bị chặn khi tạo mới (POST)."""
    group_a, code = _make_group_with_param(client, admin_h, "OVERLAPA")
    group_b, _ = _make_group_with_param(client, admin_h, "OVERLAPB", param_code=code)

    link_a = client.post("/api/qc/stage-groups", headers=admin_h,
                         json={"stage": "thanh_pham", "group_id": group_a, "mandatory": True})
    assert link_a.status_code == 201, link_a.text

    link_b = client.post("/api/qc/stage-groups", headers=admin_h,
                         json={"stage": "thanh_pham", "group_id": group_b, "mandatory": True})
    assert link_b.status_code == 409, link_b.text
    assert code in link_b.json()["detail"]
    assert "GRP_OVERLAPA" in link_b.json()["detail"]

    client.delete(f"/api/qc/stage-groups/{link_a.json()['link_id']}", headers=admin_h)


def test_non_overlapping_groups_allowed(client, admin_h):
    """2 nhóm KHÔNG trùng mã chỉ tiêu nào, gán cùng phạm vi -> cho phép (gộp lại), không bị chặn."""
    group_a, code_a = _make_group_with_param(client, admin_h, "MERGEOKA")
    group_b, code_b = _make_group_with_param(client, admin_h, "MERGEOKB")

    link_a = client.post("/api/qc/stage-groups", headers=admin_h,
                         json={"stage": "thanh_pham", "group_id": group_a, "mandatory": True})
    assert link_a.status_code == 201, link_a.text
    link_b = client.post("/api/qc/stage-groups", headers=admin_h,
                         json={"stage": "thanh_pham", "group_id": group_b, "mandatory": True})
    assert link_b.status_code == 201, link_b.text

    # scope_type="batch" không thuộc cơ chế snapshot (xem _snapshot_required_params) nên vẫn
    # tra Danh mục sống qua required_params_for_stage() — dùng để kiểm tra việc GỘP 2 nhóm,
    # scope_id không cần tồn tại thật (không ảnh hưởng tính "required").
    required = client.get("/api/brewing/qc-status", headers=admin_h, params={
        "stage": "thanh_pham", "scope_type": "batch", "scope_id": "KHONGTONTAI",
    }).json()["required"]
    codes = {p["code"] for p in required}
    assert code_a in codes and code_b in codes

    client.delete(f"/api/qc/stage-groups/{link_a.json()['link_id']}", headers=admin_h)
    client.delete(f"/api/qc/stage-groups/{link_b.json()['link_id']}", headers=admin_h)


def test_overlapping_param_blocked_on_update(client, admin_h):
    """Sửa 1 dòng gán đang KHÔNG trùng, đổi Nhóm chỉ tiêu sang 1 nhóm trùng mã với nhóm khác
    đang active cùng phạm vi -> phải bị chặn (PUT)."""
    group_a, code = _make_group_with_param(client, admin_h, "UPDOVERLAPA")
    group_b, _ = _make_group_with_param(client, admin_h, "UPDOVERLAPB", param_code=code)
    group_c, _ = _make_group_with_param(client, admin_h, "UPDOVERLAPC")

    link_a = client.post("/api/qc/stage-groups", headers=admin_h,
                         json={"stage": "thanh_pham", "group_id": group_a, "mandatory": True})
    assert link_a.status_code == 201, link_a.text
    link_c = client.post("/api/qc/stage-groups", headers=admin_h,
                         json={"stage": "thanh_pham", "group_id": group_c, "mandatory": True})
    assert link_c.status_code == 201, link_c.text

    upd = client.put(f"/api/qc/stage-groups/{link_c.json()['link_id']}", headers=admin_h,
                     json={"stage": "thanh_pham", "group_id": group_b, "mandatory": True})
    assert upd.status_code == 409, upd.text
    assert code in upd.json()["detail"]

    client.delete(f"/api/qc/stage-groups/{link_a.json()['link_id']}", headers=admin_h)
    client.delete(f"/api/qc/stage-groups/{link_c.json()['link_id']}", headers=admin_h)


def test_overlap_check_scoped_to_same_finished_product(client, admin_h):
    """2 nhóm trùng mã chỉ tiêu nhưng gán cho 2 SKU KHÁC nhau (finished_product_id khác) ở
    cùng stage=thanh_pham -> KHÔNG bị chặn, vì không cùng phạm vi áp dụng."""
    fp1 = client.post("/api/finished-products", headers=admin_h,
                      json={"code": "FPSCOPEDA", "name": "SP test scoped A"})
    assert fp1.status_code == 201, fp1.text
    fp2 = client.post("/api/finished-products", headers=admin_h,
                      json={"code": "FPSCOPEDB", "name": "SP test scoped B"})
    assert fp2.status_code == 201, fp2.text
    fp1, fp2 = fp1.json()["finished_product_id"], fp2.json()["finished_product_id"]

    group_a, code = _make_group_with_param(client, admin_h, "SCOPEDA")
    group_b, _ = _make_group_with_param(client, admin_h, "SCOPEDB", param_code=code)

    link_a = client.post("/api/qc/stage-groups", headers=admin_h,
                         json={"stage": "thanh_pham", "group_id": group_a, "mandatory": True,
                               "finished_product_id": fp1})
    assert link_a.status_code == 201, link_a.text
    link_b = client.post("/api/qc/stage-groups", headers=admin_h,
                         json={"stage": "thanh_pham", "group_id": group_b, "mandatory": True,
                               "finished_product_id": fp2})
    assert link_b.status_code == 201, link_b.text

    client.delete(f"/api/qc/stage-groups/{link_a.json()['link_id']}", headers=admin_h)
    client.delete(f"/api/qc/stage-groups/{link_b.json()['link_id']}", headers=admin_h)
