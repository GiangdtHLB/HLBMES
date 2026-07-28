"""Test lọc lại tank thành phẩm (BBT) trong Lệnh lọc — nguồn có thể là tank lên men HOẶC
1 tank BBT ĐÃ LỌC XONG (tank_type="bbt"), có thể phối 2 loại nguồn trong cùng 1 lệnh nhỏ,
bắt buộc nhập lý do lọc lại. Chặn chiết ngay từ lúc lập lệnh (giữ chỗ) + siết điều kiện
chiết chung (phải đã lọc xong + KCS duyệt hết, không riêng lọc lại) — xem
services/filter_order.py::available_bbt_tanks, routers/brewing.py::add_bottle."""

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


def _a_brew_order(client, admin_h, order_code):
    r = client.post("/api/brewing/orders", headers=admin_h,
                    json={"order_code": order_code, "auto_from_bom": False, "planned_volume_hl": 100})
    assert r.status_code == 201, r.text
    return r.json()["brew_order_id"]


def _setup_ferment(client, admin_h, vanhanh_h, suffix):
    order_id = _a_brew_order(client, admin_h, f"LN-{suffix}")
    b = client.post("/api/brewing/brews", headers=vanhanh_h,
                    json={"brew_code": f"BR-{suffix}", "wort_type": "Dịch test", "volume_hl": 100,
                          "lm_code": f"LM-{suffix}", "tank_lm": f"T-{suffix}", "brew_order_id": order_id})
    assert b.status_code == 201, b.text
    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment = next(f for f in ferments if f["lm_code"] == f"LM-{suffix}")
    ok = client.post(f"/api/brewing/ferments/{ferment['ferment_id']}/approve", headers=admin_h)
    assert ok.status_code == 200, ok.text
    return ferment["ferment_id"]


def _declare_pending(client, headers, stage, scope_type, scope_id):
    """Khai báo đạt mọi chỉ tiêu bắt buộc đang "pending" — cần thiết vì stage "loc" dùng
    chung toàn cục, module test khác có thể đã gán thêm nhóm mandatory trước đó."""
    status = client.get(f"/api/brewing/qc-status?stage={stage}&scope_type={scope_type}&scope_id={scope_id}",
                        headers=headers).json()
    for p in status["required"]:
        if p["code"] in status["pending"]:
            lsl = p["lsl"] if p["lsl"] is not None else 0
            usl = p["usl"] if p["usl"] is not None else lsl + 10
            r = client.post("/api/brewing/qc-results", headers=headers,
                            json={"stage": stage, "scope_type": scope_type, "scope_id": scope_id,
                                  "parameter": p["code"], "value": (lsl + usl) / 2,
                                  "lower_limit": lsl, "upper_limit": usl})
            assert r.status_code == 201, r.text


def _finished_bbt_tank(client, admin_h, vanhanh_h, suffix, volume_hl=100.0):
    """Dựng 1 tank BBT ĐÃ LỌC XONG + KCS duyệt (đủ điều kiện làm nguồn lọc lại) — trả về
    (bbt_code, filter_id)."""
    ferment_id = _setup_ferment(client, admin_h, vanhanh_h, suffix)
    order = client.post("/api/brewing/filter-master-orders", headers=admin_h,
                       json={"order_code": f"LOC-{suffix}",
                             "children": [{"blend_mode": "khong_phoi",
                                          "tanks": [{"tank_type": "cct", "ferment_id": ferment_id,
                                                    "planned_v_dich_hl": volume_hl}]}]})
    assert order.status_code == 201, order.text
    master = client.get(f"/api/brewing/filter-master-orders/{order.json()['filter_master_order_id']}",
                        headers=admin_h).json()
    order_id = master["children"][0]["filter_order_id"]
    bbt_code = f"BBT-{suffix}"
    f = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": f"FL-{suffix}", "filter_order_id": order_id, "to_bbt": bbt_code})
    assert f.status_code == 201, f.text
    filter_id = f.json()["filter_id"]
    tanks = client.get(f"/api/brewing/filters/{filter_id}/tanks", headers=admin_h).json()
    fin = client.post(f"/api/brewing/filters/{filter_id}/tanks/{tanks[0]['line_id']}/finish",
                      headers=vanhanh_h, json={"v_dich_hl": volume_hl, "nuoc_bai_khi_hl": 0,
                                                "batch_number": f"B-{suffix}", "order_number": f"O-{suffix}", "batch_seq_no": "1"})
    assert fin.status_code == 200, fin.text
    _declare_pending(client, vanhanh_h, "loc", "filter", f"FL-{suffix}")
    approve = client.post(f"/api/brewing/filters/{filter_id}/approve", headers=admin_h)
    assert approve.status_code == 200, approve.text
    return bbt_code, filter_id


def test_create_order_with_bbt_source_requires_reason(client, admin_h, vanhanh_h):
    bbt_code, _ = _finished_bbt_tank(client, admin_h, vanhanh_h, "REFILTER-REASON")
    missing_reason = client.post("/api/brewing/filter-master-orders", headers=admin_h,
                                 json={"order_code": "LOC-NOREASON",
                                       "children": [{"blend_mode": "khong_phoi",
                                                    "tanks": [{"tank_type": "bbt", "source_bbt_code": bbt_code,
                                                              "planned_v_dich_hl": 50}]}]})
    assert missing_reason.status_code == 409, missing_reason.text
    assert "lý do" in missing_reason.json()["detail"].lower()

    ok = client.post("/api/brewing/filter-master-orders", headers=admin_h,
                     json={"order_code": "LOC-REFILTER-01",
                           "children": [{"blend_mode": "khong_phoi",
                                        "tanks": [{"tank_type": "bbt", "source_bbt_code": bbt_code,
                                                  "reason": "Chưa đạt độ đục", "planned_v_dich_hl": 50}]}]})
    assert ok.status_code == 201, ok.text
    master = client.get(f"/api/brewing/filter-master-orders/{ok.json()['filter_master_order_id']}",
                        headers=admin_h).json()
    tank = master["children"][0]["tanks"][0]
    assert tank["tank_type"] == "bbt"
    assert tank["source_bbt_code"] == bbt_code
    assert tank["reason"] == "Chưa đạt độ đục"


def test_blend_ferment_tank_with_bbt_refilter_tank(client, admin_h, vanhanh_h):
    ferment_id = _setup_ferment(client, admin_h, vanhanh_h, "REFILTER-BLEND-CCT")
    bbt_code, _ = _finished_bbt_tank(client, admin_h, vanhanh_h, "REFILTER-BLEND-BBT")
    created = client.post("/api/brewing/filter-master-orders", headers=admin_h,
                         json={"order_code": "LOC-BLEND-REFILTER",
                               "children": [{"blend_mode": "phoi",
                                            "tanks": [
                                                {"tank_type": "cct", "ferment_id": ferment_id, "planned_v_dich_hl": 50},
                                                {"tank_type": "bbt", "source_bbt_code": bbt_code,
                                                 "reason": "Phối bù thiếu", "planned_v_dich_hl": 30},
                                            ]}]})
    assert created.status_code == 201, created.text
    master = client.get(f"/api/brewing/filter-master-orders/{created.json()['filter_master_order_id']}",
                        headers=admin_h).json()
    tanks = master["children"][0]["tanks"]
    assert {t["tank_type"] for t in tanks} == {"cct", "bbt"}


def test_add_filter_from_bbt_source_sets_refilter_metadata_and_genealogy_edge(client, admin_h, vanhanh_h):
    bbt_code, source_filter_id = _finished_bbt_tank(client, admin_h, vanhanh_h, "REFILTER-METADATA")
    order = client.post("/api/brewing/filter-master-orders", headers=admin_h,
                       json={"order_code": "LOC-METADATA",
                             "children": [{"blend_mode": "khong_phoi",
                                          "tanks": [{"tank_type": "bbt", "source_bbt_code": bbt_code,
                                                    "reason": "Kiểm tra lại", "planned_v_dich_hl": 100}]}]})
    assert order.status_code == 201, order.text
    master = client.get(f"/api/brewing/filter-master-orders/{order.json()['filter_master_order_id']}",
                        headers=admin_h).json()
    order_id = master["children"][0]["filter_order_id"]

    new_bbt_code = "BBT-METADATA-DEST"
    f = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": "FL-REFILTER-METADATA-2", "filter_order_id": order_id, "to_bbt": new_bbt_code})
    assert f.status_code == 201, f.text
    detail = f.json()
    assert detail["filter_type"] == "loc_lai"
    assert detail["source_filter_id"] == source_filter_id
    assert "lọc lại" in detail["from_cct"].lower()

    trace = client.get("/api/trace/backward", headers=admin_h,
                       params={"node_type": "filter", "node_id": detail["filter_id"]})
    assert trace.status_code == 200, trace.text
    assert "lọc lại" in str(trace.json())


def test_bbt_tank_reserved_at_order_creation_blocks_chiet(client, admin_h, vanhanh_h):
    bbt_code, _ = _finished_bbt_tank(client, admin_h, vanhanh_h, "REFILTER-RESERVE")
    bbt_status_before = next(t for t in client.get("/api/brewing/bbt-tanks", headers=admin_h).json()
                             if t["to_bbt"] == bbt_code)
    assert bbt_status_before["eligible_for_chiet"] is True

    order = client.post("/api/brewing/filter-master-orders", headers=admin_h,
                       json={"order_code": "LOC-RESERVE",
                             "children": [{"blend_mode": "khong_phoi",
                                          "tanks": [{"tank_type": "bbt", "source_bbt_code": bbt_code,
                                                    "reason": "Giữ chỗ", "planned_v_dich_hl": 100}]}]})
    assert order.status_code == 201, order.text

    bbt_status_after = next(t for t in client.get("/api/brewing/bbt-tanks", headers=admin_h).json()
                            if t["to_bbt"] == bbt_code)
    assert bbt_status_after["reserved_hl"] == 100
    assert bbt_status_after["eligible_for_chiet"] is False

    blocked = client.post("/api/brewing/bottles", headers=vanhanh_h,
                          json={"bottle_code": "CH-RESERVE-BLOCKED", "from_bbt": bbt_code})
    assert blocked.status_code == 409, blocked.text


def test_chiet_blocked_when_qc_approved_but_not_finished(client, admin_h, vanhanh_h):
    """Yêu cầu #5 (siết chung, không riêng lọc lại): mẻ lọc chưa kết thúc (ended_at=None)
    không được KCS duyệt (approve_filter tự chặn ở đây, xem test_stage_finish.py-style gate
    trong routers/brewing.py::approve_filter) — nên "qc_approved=True nhưng chưa kết thúc"
    không còn là trạng thái có thể đạt được qua API nữa; test giờ xác nhận approve bị chặn
    VÀ (do đó) chiết cũng không thể tới lượt vì tank chưa đủ điều kiện."""
    ferment_id = _setup_ferment(client, admin_h, vanhanh_h, "REFILTER-NOTFINISHED")
    order = client.post("/api/brewing/filter-orders", headers=admin_h,
                       json={"order_code": "LOC-NOTFINISHED", "blend_mode": "khong_phoi",
                             "tank_ferment_ids": [ferment_id], "planned_volume_hl": 100})
    assert order.status_code == 201, order.text
    bbt_code = "BBT-NOTFINISHED"
    f = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": "FL-NOTFINISHED", "filter_order_id": order.json()["filter_order_id"],
                          "to_bbt": bbt_code})
    assert f.status_code == 201, f.text
    _declare_pending(client, vanhanh_h, "loc", "filter", "FL-NOTFINISHED")
    approve = client.post(f"/api/brewing/filters/{f.json()['filter_id']}/approve", headers=admin_h)
    assert approve.status_code == 409, approve.text
    # KHÔNG bấm "Kết thúc" tank — filter vẫn "dang_loc" (ended_at=None), và (như trên) không
    # thể được KCS duyệt trong trạng thái này.

    bbt_status = next(t for t in client.get("/api/brewing/bbt-tanks", headers=admin_h).json()
                     if t["to_bbt"] == bbt_code)
    assert bbt_status["all_qc_approved"] is False
    assert bbt_status["all_finished"] is False
    assert bbt_status["eligible_for_chiet"] is False

    blocked = client.post("/api/brewing/bottles", headers=vanhanh_h,
                          json={"bottle_code": "CH-NOTFINISHED", "from_bbt": bbt_code})
    assert blocked.status_code == 409, blocked.text


def test_finish_filter_tank_and_delete_symmetric_on_hand_bbt_for_refilter_source(client, admin_h, vanhanh_h):
    bbt_code, source_filter_id = _finished_bbt_tank(client, admin_h, vanhanh_h, "REFILTER-ONHAND", volume_hl=100.0)
    order = client.post("/api/brewing/filter-master-orders", headers=admin_h,
                       json={"order_code": "LOC-ONHAND",
                             "children": [{"blend_mode": "khong_phoi",
                                          "tanks": [{"tank_type": "bbt", "source_bbt_code": bbt_code,
                                                    "reason": "Kiểm tra tồn", "planned_v_dich_hl": 100}]}]})
    assert order.status_code == 201, order.text
    master = client.get(f"/api/brewing/filter-master-orders/{order.json()['filter_master_order_id']}",
                        headers=admin_h).json()
    order_id = master["children"][0]["filter_order_id"]
    dest_bbt = "BBT-ONHAND-DEST"
    f = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": "FL-ONHAND-REFILTER", "filter_order_id": order_id, "to_bbt": dest_bbt})
    assert f.status_code == 201, f.text
    filter_id = f.json()["filter_id"]

    tanks = client.get(f"/api/brewing/filters/{filter_id}/tanks", headers=admin_h).json()
    line_id = tanks[0]["line_id"]
    fin = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line_id}/finish", headers=vanhanh_h,
                      json={"v_dich_hl": 60, "nuoc_bai_khi_hl": 0,
                            "batch_number": "B-ONHAND-REFILTER", "order_number": "O-ONHAND-REFILTER", "batch_seq_no": "1"})
    assert fin.status_code == 200, fin.text

    source_after_finish = next(r for r in client.get("/api/brewing/filters", headers=admin_h).json()
                               if r["filter_id"] == source_filter_id)
    assert source_after_finish["on_hand_bbt"] == 40  # 100 - 60

    delete = client.delete(f"/api/brewing/filters/{filter_id}", headers=vanhanh_h)
    assert delete.status_code == 204, delete.text
    source_after_delete = next(r for r in client.get("/api/brewing/filters", headers=admin_h).json()
                              if r["filter_id"] == source_filter_id)
    assert source_after_delete["on_hand_bbt"] == 100  # khôi phục lại đủ


def test_second_order_cannot_exceed_remaining_volume_of_same_bbt_tank(client, admin_h, vanhanh_h):
    bbt_code, _ = _finished_bbt_tank(client, admin_h, vanhanh_h, "REFILTER-OVERCOMMIT", volume_hl=100.0)
    first = client.post("/api/brewing/filter-master-orders", headers=admin_h,
                       json={"order_code": "LOC-OVERCOMMIT-1",
                             "children": [{"blend_mode": "khong_phoi",
                                          "tanks": [{"tank_type": "bbt", "source_bbt_code": bbt_code,
                                                    "reason": "Lệnh 1", "planned_v_dich_hl": 70}]}]})
    assert first.status_code == 201, first.text

    second = client.post("/api/brewing/filter-master-orders", headers=admin_h,
                        json={"order_code": "LOC-OVERCOMMIT-2",
                              "children": [{"blend_mode": "khong_phoi",
                                           "tanks": [{"tank_type": "bbt", "source_bbt_code": bbt_code,
                                                     "reason": "Lệnh 2", "planned_v_dich_hl": 50}]}]})
    assert second.status_code == 409, second.text
