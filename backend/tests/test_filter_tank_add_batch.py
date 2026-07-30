"""Test tính năng thêm nhiều mẻ (nhiều đợt rút dịch) cho CÙNG 1 tank nguồn trong 1 bản ghi
lọc — theo yêu cầu người dùng: 1 tank lên men có thể được rút dịch thành nhiều đợt, mỗi đợt
kết thúc riêng (Số mẻ/Dịch nha lọc/Nước bài khí/Giờ kết thúc); tổng thể tích của tank đó =
tổng các đợt cộng lại. Xem routers/brewing.py::add_filter_tank_batch/finish_filter_tank."""

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


def _a_filter_order(client, admin_h, vanhanh_h, suffix, planned_v_dich_hl=100.0):
    ferment_id = _setup_ferment(client, admin_h, vanhanh_h, suffix)
    order = client.post("/api/brewing/filter-master-orders", headers=admin_h,
                       json={"order_code": f"LOC-{suffix}",
                             "children": [{"blend_mode": "khong_phoi",
                                          "tanks": [{"tank_type": "cct", "ferment_id": ferment_id,
                                                    "planned_v_dich_hl": planned_v_dich_hl}]}]})
    assert order.status_code == 201, order.text
    master = client.get(f"/api/brewing/filter-master-orders/{order.json()['filter_master_order_id']}",
                        headers=admin_h).json()
    return master["children"][0]["filter_order_id"]


def _get_filter(client, admin_h, filter_id):
    items = client.get("/api/brewing/filters", headers=admin_h).json()
    return next(f for f in items if f["filter_id"] == filter_id)


def _declare_pending(client, headers, stage, scope_type, scope_id):
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


def test_add_batch_blocked_while_previous_line_unfinished(client, admin_h, vanhanh_h):
    order_id = _a_filter_order(client, admin_h, vanhanh_h, "ADDB-1")
    r = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": "FL-ADDB-1", "filter_order_id": order_id, "to_bbt": "BBT-ADDB-1"})
    assert r.status_code == 201, r.text
    filter_id = r.json()["filter_id"]
    tanks = client.get(f"/api/brewing/filters/{filter_id}/tanks", headers=admin_h).json()
    assert len(tanks) == 1
    line_id = tanks[0]["line_id"]

    blocked = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line_id}/add-batch", headers=vanhanh_h)
    assert blocked.status_code == 409, blocked.text
    assert "chưa kết thúc" in blocked.json()["detail"]


def test_add_batch_after_finish_sums_volume(client, admin_h, vanhanh_h):
    order_id = _a_filter_order(client, admin_h, vanhanh_h, "ADDB-2")
    r = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": "FL-ADDB-2", "filter_order_id": order_id, "to_bbt": "BBT-ADDB-2"})
    assert r.status_code == 201, r.text
    filter_id = r.json()["filter_id"]
    tanks = client.get(f"/api/brewing/filters/{filter_id}/tanks", headers=admin_h).json()
    line1 = tanks[0]["line_id"]

    fin1 = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line1}/finish", headers=vanhanh_h,
                       json={"v_dich_hl": 30, "nuoc_bai_khi_hl": 3,
                             "batch_number": "B-ADDB-2", "order_number": "O-ADDB-2", "batch_seq_no": "1"})
    assert fin1.status_code == 200, fin1.text
    f = _get_filter(client, admin_h, filter_id)
    assert f["ended_at"] is not None
    assert f["v_dich_hl"] == 30

    added = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line1}/add-batch", headers=vanhanh_h)
    assert added.status_code == 200, added.text
    line2 = added.json()["line_id"]
    assert line2 != line1

    # bản ghi trở lại "chưa kết thúc" vì dòng mới chưa xong, dù dòng cũ đã xong trước đó.
    f2 = _get_filter(client, admin_h, filter_id)
    assert f2["ended_at"] is None

    # chưa thể thêm mẻ thứ 3 khi mẻ thứ 2 (line2) còn dở.
    blocked = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line1}/add-batch", headers=vanhanh_h)
    assert blocked.status_code == 409, blocked.text

    fin2 = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line2}/finish", headers=vanhanh_h,
                       json={"v_dich_hl": 15, "nuoc_bai_khi_hl": 1.5,
                             "batch_number": "B-ADDB-2", "order_number": "O-ADDB-2", "batch_seq_no": "1"})
    assert fin2.status_code == 200, fin2.text

    tanks_final = client.get(f"/api/brewing/filters/{filter_id}/tanks", headers=admin_h).json()
    assert len(tanks_final) == 2
    assert all(t["ferment_id"] == tanks[0]["ferment_id"] for t in tanks_final)

    f3 = _get_filter(client, admin_h, filter_id)
    assert f3["v_dich_hl"] == pytest.approx(45)
    assert f3["nuoc_bai_khi_hl"] == pytest.approx(4.5)
    assert f3["v_beer_hl"] == pytest.approx(49.5)
    assert f3["ended_at"] is not None


def test_delete_batch_line_reverses_stock_and_recomputes(client, admin_h, vanhanh_h):
    order_id = _a_filter_order(client, admin_h, vanhanh_h, "DELB-1")
    r = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": "FL-DELB-1", "filter_order_id": order_id, "to_bbt": "BBT-DELB-1"})
    assert r.status_code == 201, r.text
    filter_id = r.json()["filter_id"]
    tanks = client.get(f"/api/brewing/filters/{filter_id}/tanks", headers=admin_h).json()
    line1 = tanks[0]["line_id"]
    ferment_id = tanks[0]["ferment_id"]

    # Không thể xóa dòng mẻ duy nhất — phải xóa cả mẻ lọc (endpoint delete_filter).
    only_line = client.delete(f"/api/brewing/filters/{filter_id}/tanks/{line1}", headers=vanhanh_h)
    assert only_line.status_code == 409, only_line.text
    assert "duy nhất" in only_line.json()["detail"]

    fin1 = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line1}/finish", headers=vanhanh_h,
                       json={"v_dich_hl": 20, "nuoc_bai_khi_hl": 2,
                             "batch_number": "B-DELB-1", "order_number": "O-DELB-1", "batch_seq_no": "1"})
    assert fin1.status_code == 200, fin1.text
    ferment_after_finish = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment_row = next(f for f in ferment_after_finish if f["ferment_id"] == ferment_id)
    on_hand_after_finish = ferment_row["on_hand_cct"]

    added = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line1}/add-batch", headers=vanhanh_h)
    assert added.status_code == 200, added.text
    line2 = added.json()["line_id"]

    # Giờ có 2 dòng — xóa dòng 2 (chưa kết thúc, chưa có thể tích) phải thành công, không đổi tồn CCT.
    del2 = client.delete(f"/api/brewing/filters/{filter_id}/tanks/{line2}", headers=vanhanh_h)
    assert del2.status_code == 204, del2.text
    ferment_after_del2 = next(f for f in client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
                              if f["ferment_id"] == ferment_id)
    assert ferment_after_del2["on_hand_cct"] == pytest.approx(on_hand_after_finish)

    # Chỉ còn 1 dòng lại — không xóa được nữa.
    only_left = client.delete(f"/api/brewing/filters/{filter_id}/tanks/{line1}", headers=vanhanh_h)
    assert only_left.status_code == 409, only_left.text

    # Thêm 1 dòng khác rồi kết thúc, sau đó xóa dòng 1 (đã có thể tích) — tồn CCT phải hoàn lại.
    added2 = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line1}/add-batch", headers=vanhanh_h)
    line3 = added2.json()["line_id"]
    fin3 = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line3}/finish", headers=vanhanh_h,
                       json={"v_dich_hl": 5, "nuoc_bai_khi_hl": 0.5,
                             "batch_number": "B-DELB-1", "order_number": "O-DELB-1", "batch_seq_no": "1"})
    assert fin3.status_code == 200, fin3.text

    del1 = client.delete(f"/api/brewing/filters/{filter_id}/tanks/{line1}", headers=vanhanh_h)
    assert del1.status_code == 204, del1.text
    ferment_after_del1 = next(f for f in client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
                              if f["ferment_id"] == ferment_id)
    # Từ on_hand_after_finish (sau khi trừ 20hl của line1): trừ thêm 5hl của line3 khi kết
    # thúc, rồi cộng lại đúng 20hl của line1 khi xóa dòng đó.
    assert ferment_after_del1["on_hand_cct"] == pytest.approx(on_hand_after_finish - 5 + 20)

    f_final = _get_filter(client, admin_h, filter_id)
    assert f_final["v_dich_hl"] == pytest.approx(5)
    assert f_final["nuoc_bai_khi_hl"] == pytest.approx(0.5)


def test_finish_requires_v_dich_hl_greater_than_zero(client, admin_h, vanhanh_h):
    """Mẻ lọc kết thúc phải có Dịch nha lọc > 0 — không cho lưu mẻ rỗng (dữ liệu rác)."""
    order_id = _a_filter_order(client, admin_h, vanhanh_h, "VDICH0-1")
    r = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": "FL-VDICH0-1", "filter_order_id": order_id, "to_bbt": "BBT-VDICH0-1"})
    assert r.status_code == 201, r.text
    filter_id = r.json()["filter_id"]
    tanks = client.get(f"/api/brewing/filters/{filter_id}/tanks", headers=admin_h).json()
    line_id = tanks[0]["line_id"]

    blocked = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line_id}/finish", headers=vanhanh_h,
                          json={"v_dich_hl": 0, "nuoc_bai_khi_hl": 0,
                                "batch_number": "B-VDICH0-1", "order_number": "O-VDICH0-1", "batch_seq_no": "1"})
    assert blocked.status_code == 409, blocked.text
    assert "Dịch nha lọc" in blocked.json()["detail"]

    # Không gửi v_dich_hl (None) khi dòng CHƯA từng có giá trị nào -> vẫn coi là 0, vẫn chặn.
    blocked2 = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line_id}/finish", headers=vanhanh_h,
                           json={"batch_number": "B-VDICH0-1", "order_number": "O-VDICH0-1", "batch_seq_no": "1"})
    assert blocked2.status_code == 409, blocked2.text

    ok = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line_id}/finish", headers=vanhanh_h,
                     json={"v_dich_hl": 10, "nuoc_bai_khi_hl": 0,
                           "batch_number": "B-VDICH0-1", "order_number": "O-VDICH0-1", "batch_seq_no": "1"})
    assert ok.status_code == 200, ok.text


def test_add_batch_blocked_after_chiet_started(client, admin_h, vanhanh_h):
    """Cùng quy tắc với add_filter — lệnh lọc đã bắt đầu chiết thì không cho "+ Thêm mẻ" nữa
    cho tank BBT nào của lệnh đó, kể cả tank khác tank vừa được chiết."""
    order_id = _a_filter_order(client, admin_h, vanhanh_h, "CHIETADD-1")
    bbt_code = "BBT-CHIETADD-1"
    r = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": "FL-CHIETADD-1", "filter_order_id": order_id, "to_bbt": bbt_code})
    assert r.status_code == 201, r.text
    filter_id = r.json()["filter_id"]
    tanks = client.get(f"/api/brewing/filters/{filter_id}/tanks", headers=admin_h).json()
    line_id = tanks[0]["line_id"]

    fin = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line_id}/finish", headers=vanhanh_h,
                      json={"v_dich_hl": 30, "nuoc_bai_khi_hl": 0,
                            "batch_number": "B-CHIETADD-1", "order_number": "O-CHIETADD-1", "batch_seq_no": "1"})
    assert fin.status_code == 200, fin.text

    # Còn "đang lọc" (chưa chiết) — thêm mẻ vẫn được phép.
    still_ok = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line_id}/add-batch", headers=vanhanh_h)
    assert still_ok.status_code == 200, still_ok.text
    line2 = still_ok.json()["line_id"]
    fin2 = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line2}/finish", headers=vanhanh_h,
                       json={"v_dich_hl": 20, "nuoc_bai_khi_hl": 0,
                             "batch_number": "B-CHIETADD-1", "order_number": "O-CHIETADD-1", "batch_seq_no": "1"})
    assert fin2.status_code == 200, fin2.text

    _declare_pending(client, vanhanh_h, "loc", "filter", "FL-CHIETADD-1")
    approve = client.post(f"/api/brewing/filters/{filter_id}/approve", headers=admin_h)
    assert approve.status_code == 200, approve.text

    bottle = client.post("/api/brewing/bottles", headers=vanhanh_h,
                         json={"bottle_code": "CH-CHIETADD-1", "from_bbt": bbt_code})
    assert bottle.status_code == 201, bottle.text

    blocked = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line2}/add-batch", headers=vanhanh_h)
    assert blocked.status_code == 409, blocked.text
    assert "đã bắt đầu chiết" in blocked.json()["detail"]
