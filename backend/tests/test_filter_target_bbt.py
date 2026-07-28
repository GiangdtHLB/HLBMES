"""Test chính sách chia sẻ tank BBT đích giữa nhiều Lệnh lọc nhỏ khác nhau — kiểm tra tại
module Lọc (lúc tạo mẻ lọc mới, không phải lúc lập Lệnh lọc nhỏ). Nhiều Lệnh lọc KHÁC NHAU
được phép cùng đổ vào 1 tank vật lý (thể tích cộng dồn) MIỄN chưa có mẻ nào trong tank được
KCS duyệt; sau khi duyệt, tank khoá lại (chặn lọc thêm) tới khi chiết hết. Mẻ lọc sau của CÙNG
1 lệnh bắt buộc dùng lại đúng tank đã dùng ở mẻ trước CHỈ KHI mẻ đó còn dở dang (chưa "kết
thúc") — 1 khi mẻ trước đã kết thúc (tank cũ đầy/xong), được đổi sang tank BBT khác (tank bé,
lọc tràn sang tank khác), batch_number/order_number kế thừa nhưng có thể sửa lại. Xem
services/filter_order.py::_bbt_target_blocked_by, routers/brewing.py::add_filter."""

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
    """Tạo 1 Lệnh lọc lớn với đúng 1 Lệnh lọc nhỏ (không phối, 1 tank CCT) — trả về filter_order_id."""
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


def test_two_different_orders_can_share_unapproved_tank_and_volumes_accumulate(client, admin_h, vanhanh_h):
    """Chính sách MỚI: 2 Lệnh lọc nhỏ KHÁC NHAU được phép cùng đổ vào 1 tank BBT vật lý miễn
    chưa có mẻ nào trong tank được KCS duyệt — thể tích cộng dồn (xem available_bbt_tanks),
    và khi chọn chiết phải lấy TỔNG cả tank, không chia nhỏ theo từng mẻ/lệnh."""
    order1 = _a_filter_order(client, admin_h, vanhanh_h, "TGT-A1", planned_v_dich_hl=100)
    bbt_code = "BBT-TGT-SHARED-1"
    f1 = client.post("/api/brewing/filters", headers=vanhanh_h,
                     json={"filter_code": "FL-TGT-A1", "filter_order_id": order1, "to_bbt": bbt_code})
    assert f1.status_code == 201, f1.text
    tanks1 = client.get(f"/api/brewing/filters/{f1.json()['filter_id']}/tanks", headers=admin_h).json()
    fin1 = client.post(f"/api/brewing/filters/{f1.json()['filter_id']}/tanks/{tanks1[0]['line_id']}/finish",
                       headers=vanhanh_h, json={"v_dich_hl": 40, "nuoc_bai_khi_hl": 0,
                                                 "batch_number": "B-TGT-A1", "order_number": "O-TGT-A1", "batch_seq_no": "1"})
    assert fin1.status_code == 200, fin1.text
    # order1 CHƯA được KCS duyệt — order2 (lệnh KHÁC hẳn) vẫn được phép đổ tiếp vào ĐÚNG tank này.
    order2 = _a_filter_order(client, admin_h, vanhanh_h, "TGT-B1", planned_v_dich_hl=100)
    f2 = client.post("/api/brewing/filters", headers=vanhanh_h,
                     json={"filter_code": "FL-TGT-B1", "filter_order_id": order2, "to_bbt": bbt_code})
    assert f2.status_code == 201, f2.text
    tanks2 = client.get(f"/api/brewing/filters/{f2.json()['filter_id']}/tanks", headers=admin_h).json()
    fin2 = client.post(f"/api/brewing/filters/{f2.json()['filter_id']}/tanks/{tanks2[0]['line_id']}/finish",
                       headers=vanhanh_h, json={"v_dich_hl": 25, "nuoc_bai_khi_hl": 0,
                                                 "batch_number": "B-TGT-B1", "order_number": "O-TGT-B1", "batch_seq_no": "1"})
    assert fin2.status_code == 200, fin2.text

    bbt_status = next(t for t in client.get("/api/brewing/bbt-tanks", headers=admin_h).json()
                     if t["to_bbt"] == bbt_code)
    assert bbt_status["on_hand_bbt"] == 65, "40 (order1) + 25 (order2) cộng dồn đúng vào cùng 1 tank"
    assert bbt_status["eligible_for_chiet"] is False, "chưa mẻ nào được KCS duyệt -> chưa được chiết"


def test_second_batch_of_same_order_forced_same_tank_while_unfinished(client, admin_h, vanhanh_h):
    """Mẻ lọc đầu CHƯA "kết thúc" — mẻ lọc thứ 2 của CÙNG lệnh bắt buộc dùng lại đúng tank đó,
    bỏ qua to_bbt client gửi lên (không cho đổi tank giữa chừng khi tank chưa kết thúc)."""
    order1 = _a_filter_order(client, admin_h, vanhanh_h, "TGT-A2", planned_v_dich_hl=100)
    bbt_code = "BBT-TGT-SHARED-2"
    f1 = client.post("/api/brewing/filters", headers=vanhanh_h,
                     json={"filter_code": "FL-TGT-A2-1", "filter_order_id": order1, "to_bbt": bbt_code})
    assert f1.status_code == 201, f1.text

    # Mẻ lọc thứ 2 của CÙNG lệnh, mẻ đầu CHƯA kết thúc — cố gửi to_bbt KHÁC, server phải bỏ
    # qua, dùng lại tank cũ.
    f2 = client.post("/api/brewing/filters", headers=vanhanh_h,
                     json={"filter_code": "FL-TGT-A2-2", "filter_order_id": order1, "to_bbt": "BBT-TGT-WRONG"})
    assert f2.status_code == 201, f2.text
    assert f2.json()["to_bbt"] == bbt_code


def test_second_batch_of_same_order_can_switch_tank_after_first_finished(client, admin_h, vanhanh_h):
    """Tank BBT đầu quá bé so với cả mẻ — sau khi "kết thúc" mẻ lọc trong tank đó, lệnh được
    đổi sang tank BBT khác cho mẻ lọc tiếp theo (lọc tràn sang tank khác); batch_number/
    order_number được tự kế thừa từ mẻ trước (cùng 1 mẻ giấy, chỉ khác tank chứa)."""
    order1 = _a_filter_order(client, admin_h, vanhanh_h, "TGT-A5", planned_v_dich_hl=100)
    bbt_code_a = "BBT-TGT-SWITCH-A"
    bbt_code_b = "BBT-TGT-SWITCH-B"
    f1 = client.post("/api/brewing/filters", headers=vanhanh_h,
                     json={"filter_code": "FL-TGT-A5-1", "filter_order_id": order1, "to_bbt": bbt_code_a})
    assert f1.status_code == 201, f1.text
    tanks1 = client.get(f"/api/brewing/filters/{f1.json()['filter_id']}/tanks", headers=admin_h).json()
    fin1 = client.post(f"/api/brewing/filters/{f1.json()['filter_id']}/tanks/{tanks1[0]['line_id']}/finish",
                       headers=vanhanh_h, json={"v_dich_hl": 30, "nuoc_bai_khi_hl": 0,
                                                 "batch_number": "B-TGT-A5", "order_number": "O-TGT-A5", "batch_seq_no": "1"})
    assert fin1.status_code == 200, fin1.text  # tank A quá bé, chỉ chứa được 30/100 hl -> "kết thúc" tank A

    # Mẻ lọc thứ 2 của CÙNG lệnh — tank A đã kết thúc, được chọn tank B (khác hẳn).
    f2 = client.post("/api/brewing/filters", headers=vanhanh_h,
                     json={"filter_code": "FL-TGT-A5-2", "filter_order_id": order1, "to_bbt": bbt_code_b})
    assert f2.status_code == 201, f2.text
    assert f2.json()["to_bbt"] == bbt_code_b, "tank A đã kết thúc -> được đổi sang tank B"
    assert f2.json()["batch_number"] == "B-TGT-A5", "batch_number kế thừa từ mẻ trước (cùng 1 mẻ giấy)"
    assert f2.json()["order_number"] == "O-TGT-A5"

    # Kết thúc tank B với CÙNG batch_number/order_number như tank A — KHÔNG bị coi là trùng vì
    # cùng 1 filter_order_id (cùng 1 mẻ thật, chỉ tách sang tank khác).
    tanks2 = client.get(f"/api/brewing/filters/{f2.json()['filter_id']}/tanks", headers=admin_h).json()
    fin2 = client.post(f"/api/brewing/filters/{f2.json()['filter_id']}/tanks/{tanks2[0]['line_id']}/finish",
                       headers=vanhanh_h, json={"v_dich_hl": 70, "nuoc_bai_khi_hl": 0,
                                                 "batch_number": "B-TGT-A5", "order_number": "O-TGT-A5", "batch_seq_no": "1"})
    assert fin2.status_code == 200, fin2.text

    # 1 Lệnh lọc KHÁC HẲN dùng lại CÙNG batch_number -- KHÔNG còn bị chặn (batch_number/
    # order_number thực tế có thể lặp lại giữa các lệnh lọc khác nhau, VD reset theo ca/ngày —
    # báo cáo sản lượng theo mẻ lọc số tự gộp các dòng cùng bộ 3 giá trị lại khi tính sản lượng).
    order2 = _a_filter_order(client, admin_h, vanhanh_h, "TGT-B5", planned_v_dich_hl=50)
    f3 = client.post("/api/brewing/filters", headers=vanhanh_h,
                     json={"filter_code": "FL-TGT-B5", "filter_order_id": order2, "to_bbt": "BBT-TGT-SWITCH-C"})
    assert f3.status_code == 201, f3.text
    tanks3 = client.get(f"/api/brewing/filters/{f3.json()['filter_id']}/tanks", headers=admin_h).json()
    reused = client.post(f"/api/brewing/filters/{f3.json()['filter_id']}/tanks/{tanks3[0]['line_id']}/finish",
                        headers=vanhanh_h, json={"v_dich_hl": 50, "nuoc_bai_khi_hl": 0,
                                                  "batch_number": "B-TGT-A5", "order_number": "O-TGT-B5-X", "batch_seq_no": "1"})
    assert reused.status_code == 200, reused.text


def test_second_order_blocked_while_tank_has_unfinished_batch(client, admin_h, vanhanh_h):
    """Tank BBT đang có mẻ lọc CHƯA kết thúc (đang lọc dở) — về mặt vật lý không thể vừa rót mẻ
    này vừa cho mẻ khác (của Lệnh lọc khác) vào cùng lúc, phải chặn tới khi mẻ đang dở kết thúc,
    dù chưa duyệt KCS và chưa ghi nhận thể tích (on_hand_bbt vẫn = 0 lúc này)."""
    order1 = _a_filter_order(client, admin_h, vanhanh_h, "TGT-A6", planned_v_dich_hl=100)
    bbt_code = "BBT-TGT-UNFINISHED-1"
    f1 = client.post("/api/brewing/filters", headers=vanhanh_h,
                     json={"filter_code": "FL-TGT-A6", "filter_order_id": order1, "to_bbt": bbt_code})
    assert f1.status_code == 201, f1.text  # f1 CHƯA "kết thúc" — vẫn đang lọc dở.

    order2 = _a_filter_order(client, admin_h, vanhanh_h, "TGT-B6", planned_v_dich_hl=50)
    blocked = client.post("/api/brewing/filters", headers=vanhanh_h,
                         json={"filter_code": "FL-TGT-B6", "filter_order_id": order2, "to_bbt": bbt_code})
    assert blocked.status_code == 409, blocked.text
    assert "chưa kết thúc" in blocked.json()["detail"]

    # Sau khi f1 "kết thúc" (dù chưa duyệt KCS) — tank tự do trở lại cho lệnh khác (chính sách
    # nhiều lệnh cùng chia sẻ tank MIỄN chưa duyệt KCS vẫn giữ nguyên).
    tanks1 = client.get(f"/api/brewing/filters/{f1.json()['filter_id']}/tanks", headers=admin_h).json()
    fin1 = client.post(f"/api/brewing/filters/{f1.json()['filter_id']}/tanks/{tanks1[0]['line_id']}/finish",
                       headers=vanhanh_h, json={"v_dich_hl": 40, "nuoc_bai_khi_hl": 0,
                                                 "batch_number": "B-TGT-A6", "order_number": "O-TGT-A6", "batch_seq_no": "1"})
    assert fin1.status_code == 200, fin1.text
    now_ok = client.post("/api/brewing/filters", headers=vanhanh_h,
                        json={"filter_code": "FL-TGT-B6", "filter_order_id": order2, "to_bbt": bbt_code})
    assert now_ok.status_code == 201, now_ok.text


def test_second_order_blocked_once_tank_qc_approved(client, admin_h, vanhanh_h):
    """Ngay khi 1 mẻ lọc trong tank được KCS duyệt, tank coi như khoá lại — Lệnh lọc khác
    không còn được đổ thêm vào nữa (dù vẫn còn dịch chưa chiết, on_hand_bbt>0)."""
    order1 = _a_filter_order(client, admin_h, vanhanh_h, "TGT-A3", planned_v_dich_hl=50)
    bbt_code = "BBT-TGT-SHARED-3"
    f1 = client.post("/api/brewing/filters", headers=vanhanh_h,
                     json={"filter_code": "FL-TGT-A3", "filter_order_id": order1, "to_bbt": bbt_code})
    assert f1.status_code == 201, f1.text
    filter_id = f1.json()["filter_id"]
    tanks = client.get(f"/api/brewing/filters/{filter_id}/tanks", headers=admin_h).json()
    fin = client.post(f"/api/brewing/filters/{filter_id}/tanks/{tanks[0]['line_id']}/finish",
                      headers=vanhanh_h, json={"v_dich_hl": 50, "nuoc_bai_khi_hl": 0,
                                                "batch_number": "B-TGT-A3", "order_number": "O-TGT-A3", "batch_seq_no": "1"})
    assert fin.status_code == 200, fin.text
    _declare_pending(client, vanhanh_h, "loc", "filter", "FL-TGT-A3")
    approve = client.post(f"/api/brewing/filters/{filter_id}/approve", headers=admin_h)
    assert approve.status_code == 200, approve.text  # đã duyệt KCS, còn 50 hl chưa chiết

    order2 = _a_filter_order(client, admin_h, vanhanh_h, "TGT-B3", planned_v_dich_hl=50)
    blocked = client.post("/api/brewing/filters", headers=vanhanh_h,
                         json={"filter_code": "FL-TGT-B3", "filter_order_id": order2, "to_bbt": bbt_code})
    assert blocked.status_code == 409, blocked.text
    assert "đã được KCS duyệt" in blocked.json()["detail"]


def test_tank_free_again_after_fully_chiet_het(client, admin_h, vanhanh_h):
    order1 = _a_filter_order(client, admin_h, vanhanh_h, "TGT-A4", planned_v_dich_hl=50)
    bbt_code = "BBT-TGT-SHARED-4"
    f1 = client.post("/api/brewing/filters", headers=vanhanh_h,
                     json={"filter_code": "FL-TGT-A4", "filter_order_id": order1, "to_bbt": bbt_code})
    assert f1.status_code == 201, f1.text
    filter_id = f1.json()["filter_id"]
    tanks = client.get(f"/api/brewing/filters/{filter_id}/tanks", headers=admin_h).json()
    fin = client.post(f"/api/brewing/filters/{filter_id}/tanks/{tanks[0]['line_id']}/finish",
                      headers=vanhanh_h, json={"v_dich_hl": 50, "nuoc_bai_khi_hl": 0,
                                                "batch_number": "B-TGT-A4", "order_number": "O-TGT-A4", "batch_seq_no": "1"})
    assert fin.status_code == 200, fin.text
    _declare_pending(client, vanhanh_h, "loc", "filter", "FL-TGT-A4")
    approve = client.post(f"/api/brewing/filters/{filter_id}/approve", headers=admin_h)
    assert approve.status_code == 200, approve.text

    # Trước khi chiết hết — vẫn còn bị chặn (đã KCS duyệt, chưa chiết hết).
    order2 = _a_filter_order(client, admin_h, vanhanh_h, "TGT-B4", planned_v_dich_hl=50)
    still_blocked = client.post("/api/brewing/filters", headers=vanhanh_h,
                               json={"filter_code": "FL-TGT-B4-early", "filter_order_id": order2, "to_bbt": bbt_code})
    assert still_blocked.status_code == 409, still_blocked.text
    assert "đã được KCS duyệt" in still_blocked.json()["detail"]

    bottle = client.post("/api/brewing/bottles", headers=vanhanh_h,
                         json={"bottle_code": "CH-TGT-A4", "from_bbt": bbt_code})
    assert bottle.status_code == 201, bottle.text
    fin_bottle = client.post(f"/api/brewing/bottles/{bottle.json()['bottle_id']}/finish", headers=vanhanh_h,
                             json={"v_cap_chiet_hl": 50, "ca1": 50})
    assert fin_bottle.status_code == 200, fin_bottle.text

    source_after = next(r for r in client.get("/api/brewing/filters", headers=admin_h).json()
                       if r["filter_id"] == filter_id)
    assert source_after["on_hand_bbt"] == 0

    now_ok = client.post("/api/brewing/filters", headers=vanhanh_h,
                        json={"filter_code": "FL-TGT-B4", "filter_order_id": order2, "to_bbt": bbt_code})
    assert now_ok.status_code == 201, now_ok.text
