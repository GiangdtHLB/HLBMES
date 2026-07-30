"""Test gợi ý "Mẻ lọc số" kế tiếp + danh sách số đã dùng (GET /api/brewing/next-batch-seq-no)
— quét TOÀN BỘ các lô lọc trong hệ thống (không giới hạn theo 1 lệnh lọc cụ thể), lấy số lớn
nhất +1, dùng cho modal Kết thúc mẻ tự động gợi ý số tiếp theo và hỏi xác nhận khi vận hành gõ
trùng số đã dùng ở BẤT KỲ đâu. Xem services/filter_order.py::next_batch_seq_no.

Các test dưới đây PHỤ THUỘC thứ tự chạy trong file (module-scoped client/db dùng chung, số liệu
cộng dồn qua từng test) — pytest chạy tuần tự theo thứ tự khai báo trong file nên giả định này
an toàn."""

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
                    json={"order_code": order_code, "auto_from_bom": False, "planned_volume_hl": 200})
    assert r.status_code == 201, r.text
    return r.json()["brew_order_id"]


def _setup_ferment(client, admin_h, vanhanh_h, suffix):
    order_id = _a_brew_order(client, admin_h, f"LN-{suffix}")
    b = client.post("/api/brewing/brews", headers=vanhanh_h,
                    json={"brew_code": f"BR-{suffix}", "wort_type": "Dịch test", "volume_hl": 200,
                          "lm_code": f"LM-{suffix}", "tank_lm": f"T-{suffix}", "brew_order_id": order_id})
    assert b.status_code == 201, b.text
    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment = next(f for f in ferments if f["lm_code"] == f"LM-{suffix}")
    ok = client.post(f"/api/brewing/ferments/{ferment['ferment_id']}/approve", headers=admin_h)
    assert ok.status_code == 200, ok.text
    return ferment["ferment_id"]


def _a_filter_order(client, admin_h, vanhanh_h, suffix, planned_v_dich_hl=200.0):
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


def test_next_seq_no_is_1_when_nothing_finished_yet(client, admin_h):
    r = client.get("/api/brewing/next-batch-seq-no", headers=admin_h)
    assert r.status_code == 200, r.text
    assert r.json() == {"next_batch_seq_no": "1", "used_batch_seq_nos": []}


def test_next_seq_no_reflects_global_max_across_different_lo_loc(client, admin_h, vanhanh_h):
    # 2 lệnh lọc HOÀN TOÀN khác nhau — gợi ý phải quét cả 2, không chỉ 1 lệnh.
    order_a = _a_filter_order(client, admin_h, vanhanh_h, "SUGG-INC")
    fr_a = client.post("/api/brewing/filters", headers=vanhanh_h,
                       json={"filter_code": "FL-SUGG-INC", "filter_order_id": order_a, "to_bbt": "BBT-SUGG-INC"})
    assert fr_a.status_code == 201, fr_a.text
    tanks_a = client.get(f"/api/brewing/filters/{fr_a.json()['filter_id']}/tanks", headers=admin_h).json()
    fin_a = client.post(f"/api/brewing/filters/{fr_a.json()['filter_id']}/tanks/{tanks_a[0]['line_id']}/finish",
                       headers=vanhanh_h, json={"v_dich_hl": 10, "nuoc_bai_khi_hl": 0,
                             "batch_number": "B-SUGG-INC", "order_number": "O-SUGG-INC", "batch_seq_no": "1"})
    assert fin_a.status_code == 200, fin_a.text

    r1 = client.get("/api/brewing/next-batch-seq-no", headers=admin_h)
    assert r1.status_code == 200, r1.text
    assert r1.json() == {"next_batch_seq_no": "2", "used_batch_seq_nos": ["1"]}

    order_b = _a_filter_order(client, admin_h, vanhanh_h, "SUGG-INC2")
    fr_b = client.post("/api/brewing/filters", headers=vanhanh_h,
                       json={"filter_code": "FL-SUGG-INC2", "filter_order_id": order_b, "to_bbt": "BBT-SUGG-INC2"})
    assert fr_b.status_code == 201, fr_b.text
    tanks_b = client.get(f"/api/brewing/filters/{fr_b.json()['filter_id']}/tanks", headers=admin_h).json()
    fin_b = client.post(f"/api/brewing/filters/{fr_b.json()['filter_id']}/tanks/{tanks_b[0]['line_id']}/finish",
                       headers=vanhanh_h, json={"v_dich_hl": 10, "nuoc_bai_khi_hl": 0,
                             "batch_number": "B-SUGG-INC2", "order_number": "O-SUGG-INC2", "batch_seq_no": "3"})
    assert fin_b.status_code == 200, fin_b.text

    r2 = client.get("/api/brewing/next-batch-seq-no", headers=admin_h)
    assert r2.status_code == 200, r2.text
    assert r2.json() == {"next_batch_seq_no": "4", "used_batch_seq_nos": ["1", "3"]}


def test_next_seq_no_excludes_current_line_when_editing(client, admin_h, vanhanh_h):
    # Sửa lại chính mẻ vừa kết thúc (line_id đó) không nên tự báo trùng với chính nó — số của
    # dòng đang sửa bị loại khỏi "used", nhưng vẫn thấy các số khác đang dùng ở nơi khác.
    order_id = _a_filter_order(client, admin_h, vanhanh_h, "SUGG-EXCL")
    fr = client.post("/api/brewing/filters", headers=vanhanh_h,
                     json={"filter_code": "FL-SUGG-EXCL", "filter_order_id": order_id, "to_bbt": "BBT-SUGG-EXCL"})
    assert fr.status_code == 201, fr.text
    filter_id = fr.json()["filter_id"]
    tanks = client.get(f"/api/brewing/filters/{filter_id}/tanks", headers=admin_h).json()
    line_id = tanks[0]["line_id"]
    fin = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line_id}/finish", headers=vanhanh_h,
                      json={"v_dich_hl": 10, "nuoc_bai_khi_hl": 0,
                            "batch_number": "B-SUGG-EXCL", "order_number": "O-SUGG-EXCL", "batch_seq_no": "5"})
    assert fin.status_code == 200, fin.text

    r = client.get(f"/api/brewing/next-batch-seq-no?exclude_line_id={line_id}", headers=admin_h)
    assert r.status_code == 200, r.text
    # "5" (dòng đang sửa) bị loại — global vẫn còn "1" và "3" từ test trước, nên gợi ý là 4.
    assert r.json() == {"next_batch_seq_no": "4", "used_batch_seq_nos": ["1", "3"]}


def test_duplicate_batch_seq_no_still_allowed_by_backend(client, admin_h, vanhanh_h):
    # finish_filter_tank KHÔNG chặn trùng batch_seq_no (đã relax từ trước) — endpoint gợi ý chỉ
    # hỗ trợ UX hỏi lại ở FE, không thêm ràng buộc mới ở BE.
    order_id = _a_filter_order(client, admin_h, vanhanh_h, "SUGG-DUP")
    fr1 = client.post("/api/brewing/filters", headers=vanhanh_h,
                      json={"filter_code": "FL-SUGG-DUP-1", "filter_order_id": order_id, "to_bbt": "BBT-SUGG-DUP"})
    assert fr1.status_code == 201, fr1.text
    filter_id1 = fr1.json()["filter_id"]
    tanks1 = client.get(f"/api/brewing/filters/{filter_id1}/tanks", headers=admin_h).json()
    fin1 = client.post(f"/api/brewing/filters/{filter_id1}/tanks/{tanks1[0]['line_id']}/finish", headers=vanhanh_h,
                       json={"v_dich_hl": 5, "nuoc_bai_khi_hl": 0,
                             "batch_number": "B-SUGG-DUP", "order_number": "O-SUGG-DUP", "batch_seq_no": "1"})
    assert fin1.status_code == 200, fin1.text

    add_batch = client.post(f"/api/brewing/filters/{filter_id1}/tanks/{tanks1[0]['line_id']}/add-batch",
                            headers=vanhanh_h)
    assert add_batch.status_code == 200, add_batch.text
    tanks1b = client.get(f"/api/brewing/filters/{filter_id1}/tanks", headers=admin_h).json()
    new_line = next(t for t in tanks1b if not t["ended_at"])
    fin2 = client.post(f"/api/brewing/filters/{filter_id1}/tanks/{new_line['line_id']}/finish", headers=vanhanh_h,
                       json={"v_dich_hl": 3, "nuoc_bai_khi_hl": 0,
                             "batch_number": "B-SUGG-DUP", "order_number": "O-SUGG-DUP", "batch_seq_no": "1"})
    assert fin2.status_code == 200, fin2.text

    r = client.get("/api/brewing/next-batch-seq-no", headers=admin_h)
    assert r.status_code == 200, r.text
    # "1" đã dùng (lặp lại, không sao) + "3" và "5" đã dùng ở các lệnh lọc khác trước đó.
    assert r.json() == {"next_batch_seq_no": "6", "used_batch_seq_nos": ["1", "3", "5"]}
