"""Sửa chỉ tiêu QC đã khai (2026-09-21) — cả 2 màn hình dùng chung QualityResult:

1. "Chỉ tiêu Mẻ nấu" (record_stage_result, ghi đè tại chỗ) — sửa vẫn ghi đè 1 dòng, nhưng giờ
   recorded_by/recorded_at (ngày giờ TẠO) không đổi nữa, updated_by/updated_at (ngày giờ SỬA
   gần nhất) ghi riêng, và giá trị CŨ được chụp lại vào QualityResultHistory trước khi ghi đè.
   Cũng thêm được `sampled_at` ("Ngày giờ lấy mẫu") cho các stage này.
2. "CT chính/CT phụ — tank" (record_qc_sample/update_qc_sample) — mỗi "lần lấy mẫu" gồm nhiều
   dòng cùng sample_id; sửa CHỈ 1 chỉ tiêu chỉ đóng dấu sửa cho đúng dòng đó, còn sửa
   "Ngày giờ lấy mẫu" (chung cho cả nhóm) đóng dấu sửa cho MỌI dòng trong nhóm.

Xem services/qc_catalog.py::record_stage_result/update_qc_sample/get_qc_result_history."""

import os
import tempfile

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["MES_DATABASE_URL"] = f"sqlite:///{_TMP.name}"
os.environ["MES_DEV_HEADER_AUTH"] = "0"
os.environ["MES_RL_ENABLED"] = "0"
os.environ["MES_ADMIN_PASSWORD"] = "AdminTest123"

import pytest
from fastapi.testclient import TestClient

from app.common import utcnow
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
def kcs_h(client):
    return _login(client, "kcs", "123456")


@pytest.fixture(scope="module")
def vanhanh_h(client):
    return _login(client, "vanhanh", "123456")


def _make_batch(client, admin_h, batch_code):
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(v for v in vers if v["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                          "batch_code": batch_code, "planned_qty": 1000, "allow_shortage": True})
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


def _make_tank(client, admin_h, batch_code, tank_code):
    batch_id = _make_batch(client, admin_h, batch_code)
    _run_batch_to_completed(client, admin_h, batch_id)
    r = client.post("/api/batch-tanks", headers=admin_h,
                    json={"batch_ids": [batch_id], "tank_code": tank_code})
    assert r.status_code == 201, r.text
    return r.json()


def test_record_stage_result_edit_preserves_created_at_sets_updated_and_history(client, admin_h):
    batch_id = _make_batch(client, admin_h, "101")
    first = client.post("/api/brewing/qc-results", headers=admin_h,
                        json={"stage": "nau", "scope_type": "batch", "scope_id": batch_id,
                             "parameter": "CT_EDIT01", "value": 5, "lower_limit": 1, "upper_limit": 10})
    assert first.status_code == 201, first.text
    body1 = first.json()
    result_id = body1["result_id"]
    assert body1["updated_by"] is None and body1["updated_at"] is None
    created_at = body1["recorded_at"]
    created_by = body1["recorded_by"]

    sampled_at = "2026-09-20T08:00:00Z"
    second = client.post("/api/brewing/qc-results", headers=admin_h,
                         json={"stage": "nau", "scope_type": "batch", "scope_id": batch_id,
                              "parameter": "CT_EDIT01", "value": 7, "lower_limit": 1, "upper_limit": 10,
                              "sampled_at": sampled_at})
    assert second.status_code == 201, second.text
    body2 = second.json()
    assert body2["result_id"] == result_id
    assert body2["value"] == 7
    assert body2["recorded_at"] == created_at   # ngày giờ TẠO không đổi
    assert body2["recorded_by"] == created_by
    assert body2["updated_by"] == "admin"
    assert body2["updated_at"] is not None
    assert body2["sampled_at"].startswith("2026-09-20T08:00:00")

    hist = client.get(f"/api/brewing/qc-results/{result_id}/history", headers=admin_h).json()
    assert len(hist["items"]) == 1
    assert hist["items"][0]["value"] == 5   # giá trị CŨ trước khi sửa
    assert hist["items"][0]["changed_by"] == "admin"


def test_qc_result_history_empty_when_never_edited(client, admin_h):
    batch_id = _make_batch(client, admin_h, "102")
    rec = client.post("/api/brewing/qc-results", headers=admin_h,
                      json={"stage": "nau", "scope_type": "batch", "scope_id": batch_id,
                           "parameter": "CT_NOEDIT01", "value": 5, "lower_limit": 1, "upper_limit": 10})
    assert rec.status_code == 201, rec.text
    hist = client.get(f"/api/brewing/qc-results/{rec.json()['result_id']}/history", headers=admin_h).json()
    assert hist["items"] == []


def test_qc_sample_update_edits_only_touched_result(client, admin_h, kcs_h):
    tank = _make_tank(client, admin_h, "103", "TANK-EDIT01")
    scope_id = f"{tank['tank_id']}__len_men_chinh"
    created = client.post("/api/brewing/qc-samples", headers=kcs_h,
                          json={"stage": "len_men_chinh", "scope_type": "batch_tank", "scope_id": scope_id,
                               "results": [{"parameter": "Bx", "value": 12}, {"parameter": "pH", "value": 5.3}]})
    assert created.status_code == 201, created.text
    body = created.json()
    sample_id = body["sample_id"]
    bx_id = next(r["result_id"] for r in body["results"] if r["parameter"] == "Bx")
    ph_id = next(r["result_id"] for r in body["results"] if r["parameter"] == "pH")

    upd = client.put(f"/api/brewing/qc-samples/{sample_id}", headers=kcs_h,
                     json={"results": [{"result_id": bx_id, "value": 13}]})
    assert upd.status_code == 200, upd.text

    samples = client.get("/api/brewing/qc-samples", headers=admin_h,
                         params={"scope_type": "batch_tank", "scope_id": scope_id}).json()["items"]
    s = next(s for s in samples if s["sample_id"] == sample_id)
    bx = next(r for r in s["results"] if r["result_id"] == bx_id)
    ph = next(r for r in s["results"] if r["result_id"] == ph_id)
    assert bx["value"] == 13
    assert bx["updated_by"] == "kcs"
    assert ph["updated_by"] is None   # chỉ tiêu KHÔNG sửa không bị đụng tới

    hist_bx = client.get(f"/api/brewing/qc-results/{bx_id}/history", headers=admin_h).json()
    assert len(hist_bx["items"]) == 1 and hist_bx["items"][0]["value"] == 12
    hist_ph = client.get(f"/api/brewing/qc-results/{ph_id}/history", headers=admin_h).json()
    assert hist_ph["items"] == []


def test_qc_sample_update_sampled_at_stamps_whole_group(client, admin_h, kcs_h):
    tank = _make_tank(client, admin_h, "104", "TANK-EDIT02")
    scope_id = f"{tank['tank_id']}__len_men_chinh"
    created = client.post("/api/brewing/qc-samples", headers=kcs_h,
                          json={"stage": "len_men_chinh", "scope_type": "batch_tank", "scope_id": scope_id,
                               "results": [{"parameter": "Bx", "value": 12}, {"parameter": "pH", "value": 5.3}]})
    assert created.status_code == 201, created.text
    sample_id = created.json()["sample_id"]

    new_sampled_at = "2026-09-19T09:00:00Z"
    upd = client.put(f"/api/brewing/qc-samples/{sample_id}", headers=kcs_h,
                     json={"sampled_at": new_sampled_at})
    assert upd.status_code == 200, upd.text
    assert upd.json()["sampled_at"].startswith("2026-09-19T09:00:00")

    samples = client.get("/api/brewing/qc-samples", headers=admin_h,
                         params={"scope_type": "batch_tank", "scope_id": scope_id}).json()["items"]
    s = next(s for s in samples if s["sample_id"] == sample_id)
    assert all(r["updated_by"] == "kcs" for r in s["results"])   # sửa mốc chung -> cả nhóm bị đóng dấu


def test_update_qc_sample_requires_quality_release_for_batch_tank(client, admin_h, kcs_h, vanhanh_h):
    tank = _make_tank(client, admin_h, "105", "TANK-EDIT03")
    scope_id = f"{tank['tank_id']}__len_men_chinh"
    created = client.post("/api/brewing/qc-samples", headers=kcs_h,
                          json={"stage": "len_men_chinh", "scope_type": "batch_tank", "scope_id": scope_id,
                               "results": [{"parameter": "Bx", "value": 12}]})
    assert created.status_code == 201, created.text
    sample_id = created.json()["sample_id"]

    blocked = client.put(f"/api/brewing/qc-samples/{sample_id}", headers=vanhanh_h,
                         json={"sampled_at": utcnow().isoformat()})
    assert blocked.status_code == 403, blocked.text

    ok = client.put(f"/api/brewing/qc-samples/{sample_id}", headers=kcs_h,
                    json={"sampled_at": utcnow().isoformat()})
    assert ok.status_code == 200, ok.text


def test_update_qc_sample_not_found(client, admin_h):
    r = client.put("/api/brewing/qc-samples/NOPE", headers=admin_h, json={"sampled_at": utcnow().isoformat()})
    assert r.status_code == 404, r.text


def test_record_qc_sample_with_client_sample_id_appends_to_same_group(client, admin_h, kcs_h):
    """Yêu cầu người dùng 2026-09-21: "mỗi chỉ tiêu sẽ có thêm nút Lưu... mỗi lần thêm thì sẽ
    hiện ra toàn bộ các chỉ tiêu cần thêm" — mỗi chỉ tiêu lưu riêng lẻ (gọi record_qc_sample
    nhiều lần, mỗi lần 1 chỉ tiêu) nhưng vẫn phải NỐI đúng vào 1 "lần lấy mẫu" (không tách vụn
    thành nhiều sample_id như bug cũ đã phải viết merge_duplicate_qc_samples để dọn)."""
    tank = _make_tank(client, admin_h, "106", "TANK-EDIT04")
    scope_id = f"{tank['tank_id']}__len_men_chinh"
    draft_id = "S-DRAFT-TEST-01"

    first = client.post("/api/brewing/qc-samples", headers=kcs_h,
                        json={"stage": "len_men_chinh", "scope_type": "batch_tank", "scope_id": scope_id,
                             "sample_id": draft_id, "results": [{"parameter": "Bx", "value": 12}]})
    assert first.status_code == 201, first.text
    assert first.json()["sample_id"] == draft_id

    second = client.post("/api/brewing/qc-samples", headers=kcs_h,
                         json={"stage": "len_men_chinh", "scope_type": "batch_tank", "scope_id": scope_id,
                              "sample_id": draft_id, "results": [{"parameter": "pH", "value": 5.3}]})
    assert second.status_code == 201, second.text
    assert second.json()["sample_id"] == draft_id
    # 2 dòng nối vào ĐÚNG mốc sampled_at của lần ghi ĐẦU TIÊN (không đổi theo lần thêm sau).
    assert second.json()["sampled_at"] == first.json()["sampled_at"]

    samples = client.get("/api/brewing/qc-samples", headers=admin_h,
                         params={"scope_type": "batch_tank", "scope_id": scope_id}).json()["items"]
    group = [s for s in samples if s["sample_id"] == draft_id]
    assert len(group) == 1   # KHÔNG bị tách thành 2 nhóm riêng
    assert {r["parameter"] for r in group[0]["results"]} == {"Bx", "pH"}


def test_record_qc_sample_rejects_duplicate_parameter_in_same_group(client, admin_h, kcs_h):
    tank = _make_tank(client, admin_h, "107", "TANK-EDIT05")
    scope_id = f"{tank['tank_id']}__len_men_chinh"
    draft_id = "S-DRAFT-TEST-02"
    first = client.post("/api/brewing/qc-samples", headers=kcs_h,
                        json={"stage": "len_men_chinh", "scope_type": "batch_tank", "scope_id": scope_id,
                             "sample_id": draft_id, "results": [{"parameter": "Bx", "value": 12}]})
    assert first.status_code == 201, first.text

    dup = client.post("/api/brewing/qc-samples", headers=kcs_h,
                      json={"stage": "len_men_chinh", "scope_type": "batch_tank", "scope_id": scope_id,
                           "sample_id": draft_id, "results": [{"parameter": "Bx", "value": 13}]})
    assert dup.status_code == 409, dup.text
    assert "Bx" in dup.json()["detail"]


def test_record_qc_sample_rejects_sample_id_from_different_scope(client, admin_h, kcs_h):
    tank1 = _make_tank(client, admin_h, "108", "TANK-EDIT06")
    tank2 = _make_tank(client, admin_h, "109", "TANK-EDIT07")
    scope1 = f"{tank1['tank_id']}__len_men_chinh"
    scope2 = f"{tank2['tank_id']}__len_men_chinh"
    draft_id = "S-DRAFT-TEST-03"
    first = client.post("/api/brewing/qc-samples", headers=kcs_h,
                        json={"stage": "len_men_chinh", "scope_type": "batch_tank", "scope_id": scope1,
                             "sample_id": draft_id, "results": [{"parameter": "Bx", "value": 12}]})
    assert first.status_code == 201, first.text

    wrong_scope = client.post("/api/brewing/qc-samples", headers=kcs_h,
                              json={"stage": "len_men_chinh", "scope_type": "batch_tank", "scope_id": scope2,
                                   "sample_id": draft_id, "results": [{"parameter": "pH", "value": 5}]})
    assert wrong_scope.status_code == 409, wrong_scope.text


def test_delete_stage_qc_result(client, admin_h):
    """Yêu cầu người dùng 2026-09-21: mỗi hàng "Chỉ tiêu Mẻ nấu" thêm nút Xóa — record_stage_result
    (ghi đè tại chỗ) giờ xóa được hẳn, giá trị cũ vẫn tra lại được qua history (result_id cũ)."""
    batch_id = _make_batch(client, admin_h, "110")
    rec = client.post("/api/brewing/qc-results", headers=admin_h,
                      json={"stage": "nau", "scope_type": "batch", "scope_id": batch_id,
                           "parameter": "CT_DEL01", "value": 5, "lower_limit": 1, "upper_limit": 10})
    assert rec.status_code == 201, rec.text
    result_id = rec.json()["result_id"]

    status_before = client.get("/api/brewing/qc-status", headers=admin_h,
                               params={"stage": "nau", "scope_type": "batch", "scope_id": batch_id}).json()
    assert any(r["result_id"] == result_id for r in status_before["recorded"])

    delete = client.delete(f"/api/brewing/qc-results/{result_id}", headers=admin_h)
    assert delete.status_code == 204, delete.text

    status_after = client.get("/api/brewing/qc-status", headers=admin_h,
                              params={"stage": "nau", "scope_type": "batch", "scope_id": batch_id}).json()
    assert not any(r["result_id"] == result_id for r in status_after["recorded"])

    # Giá trị đã xóa vẫn tra được qua history (result_id cũ) — không mất dấu vết.
    hist = client.get(f"/api/brewing/qc-results/{result_id}/history", headers=admin_h).json()
    assert len(hist["items"]) == 1
    assert hist["items"][0]["value"] == 5


def test_delete_qc_result_not_found(client, admin_h):
    r = client.delete("/api/brewing/qc-results/NOPE", headers=admin_h)
    assert r.status_code == 404, r.text


def test_delete_one_result_from_qc_sample_group_leaves_others(client, admin_h, kcs_h):
    tank = _make_tank(client, admin_h, "111", "TANK-EDIT08")
    scope_id = f"{tank['tank_id']}__len_men_chinh"
    created = client.post("/api/brewing/qc-samples", headers=kcs_h,
                          json={"stage": "len_men_chinh", "scope_type": "batch_tank", "scope_id": scope_id,
                               "results": [{"parameter": "Bx", "value": 12}, {"parameter": "pH", "value": 5.3}]})
    assert created.status_code == 201, created.text
    body = created.json()
    sample_id = body["sample_id"]
    bx_id = next(r["result_id"] for r in body["results"] if r["parameter"] == "Bx")

    delete = client.delete(f"/api/brewing/qc-results/{bx_id}", headers=kcs_h)
    assert delete.status_code == 204, delete.text

    samples = client.get("/api/brewing/qc-samples", headers=admin_h,
                         params={"scope_type": "batch_tank", "scope_id": scope_id}).json()["items"]
    group = next(s for s in samples if s["sample_id"] == sample_id)
    assert {r["parameter"] for r in group["results"]} == {"pH"}   # Bx đã xóa, pH vẫn còn


def test_delete_last_result_from_qc_sample_group_removes_group(client, admin_h, kcs_h):
    tank = _make_tank(client, admin_h, "112", "TANK-EDIT09")
    scope_id = f"{tank['tank_id']}__len_men_chinh"
    created = client.post("/api/brewing/qc-samples", headers=kcs_h,
                          json={"stage": "len_men_chinh", "scope_type": "batch_tank", "scope_id": scope_id,
                               "results": [{"parameter": "Bx", "value": 12}]})
    assert created.status_code == 201, created.text
    body = created.json()
    result_id = body["results"][0]["result_id"]

    delete = client.delete(f"/api/brewing/qc-results/{result_id}", headers=kcs_h)
    assert delete.status_code == 204, delete.text

    samples = client.get("/api/brewing/qc-samples", headers=admin_h,
                         params={"scope_type": "batch_tank", "scope_id": scope_id}).json()["items"]
    assert not any(s["sample_id"] == body["sample_id"] for s in samples)


def test_delete_qc_result_requires_quality_release_for_batch_tank(client, admin_h, kcs_h, vanhanh_h):
    tank = _make_tank(client, admin_h, "113", "TANK-EDIT10")
    scope_id = f"{tank['tank_id']}__len_men_chinh"
    created = client.post("/api/brewing/qc-samples", headers=kcs_h,
                          json={"stage": "len_men_chinh", "scope_type": "batch_tank", "scope_id": scope_id,
                               "results": [{"parameter": "Bx", "value": 12}]})
    assert created.status_code == 201, created.text
    result_id = created.json()["results"][0]["result_id"]

    blocked = client.delete(f"/api/brewing/qc-results/{result_id}", headers=vanhanh_h)
    assert blocked.status_code == 403, blocked.text

    ok = client.delete(f"/api/brewing/qc-results/{result_id}", headers=kcs_h)
    assert ok.status_code == 204, ok.text
