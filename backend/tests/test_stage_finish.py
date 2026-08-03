"""Test bắt đầu/kết thúc thực thi cho Nấu (mẻ)/Lọc/Chiết + báo cáo trạng thái lô tổng hợp
(GET /reports/lo-status) — vận hành tạo mới (bắt đầu, chưa có ngày kết thúc) rồi tự bấm
"Kết thúc" khi xong việc, tách biệt với trạng thái suy ra từ tồn kho hiện có."""

import os
import tempfile
from datetime import datetime, timedelta, timezone

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


def _a_brewhouse_line(client, admin_h):
    """Dây chuyền nấu (ProductionLine.kind="brewhouse") dùng cho test — lấy lại nếu đã có
    (idempotent), tạo mới nếu chưa có (seed.py không seed sẵn dây chuyền loại brewhouse)."""
    existing = client.get("/api/lines", headers=admin_h, params={"kind": "brewhouse"}).json()
    if existing:
        return existing[0]["line_id"]
    r = client.post("/api/lines", headers=admin_h,
                    json={"code": "BREW-TEST-01", "name": "Nhà nấu test", "kind": "brewhouse"})
    assert r.status_code == 201, r.text
    return r.json()["line_id"]


@pytest.fixture(scope="module")
def brewhouse_line_id(client, admin_h):
    return _a_brewhouse_line(client, admin_h)


def _a_brew_order(client, admin_h, order_code):
    r = client.post("/api/brewing/orders", headers=admin_h,
                    json={"order_code": order_code, "auto_from_bom": False, "planned_volume_hl": 100})
    assert r.status_code == 201, r.text
    return r.json()["brew_order_id"]


def _a_brew(client, admin_h, vanhanh_h, suffix):
    order_id = _a_brew_order(client, admin_h, f"LN-{suffix}")
    b = client.post("/api/brewing/brews", headers=vanhanh_h,
                    json={"brew_code": f"BR-{suffix}", "wort_type": "Dịch test",
                          "volume_hl": 100, "lm_code": f"LM-{suffix}", "tank_lm": f"T-{suffix}",
                          "brew_order_id": order_id})
    assert b.status_code == 201, b.text
    return b.json()["brew_id"]


def _declare_luong_dich(client, admin_h, brew_id, batch_id, volume_hl=100):
    """"Tổng lượng dịch (hl)" ở Ghi chép nấu > 0 — bắt buộc khai báo trước khi mẻ được phép
    "Kết thúc" (xem routers/brewing.py::finish_brew_batch)."""
    p = client.put(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/process-log", headers=admin_h,
                   json={"whp_tong_luong_dich_hl": volume_hl})
    assert p.status_code == 200, p.text


def test_add_brew_batch_started_at_defaults_to_now(client, admin_h, vanhanh_h, brewhouse_line_id):
    brew_id = _a_brew(client, admin_h, vanhanh_h, "STARTDEFAULT")
    before = datetime.now(timezone.utc)
    r = client.post(f"/api/brewing/brews/{brew_id}/batches", headers=vanhanh_h,
                    json={"batch_code": "801", "line_id": brewhouse_line_id})
    assert r.status_code == 201, r.text
    after = datetime.now(timezone.utc)
    started_at = datetime.fromisoformat(r.json()["started_at"])
    assert before - timedelta(seconds=5) <= started_at <= after + timedelta(seconds=5)


def test_add_brew_batch_started_at_explicit_is_kept(client, admin_h, vanhanh_h, brewhouse_line_id):
    brew_id = _a_brew(client, admin_h, vanhanh_h, "STARTEXPLICIT")
    explicit = "2026-01-15T08:30:00+00:00"
    r = client.post(f"/api/brewing/brews/{brew_id}/batches", headers=vanhanh_h,
                    json={"batch_code": "802", "started_at": explicit, "line_id": brewhouse_line_id})
    assert r.status_code == 201, r.text
    assert r.json()["started_at"] == explicit


def test_finish_brew_batch_requires_chosen_time_and_is_correctable(client, admin_h, vanhanh_h, brewhouse_line_id):
    brew_id = _a_brew(client, admin_h, vanhanh_h, "FINISHBATCH")
    r = client.post(f"/api/brewing/brews/{brew_id}/batches", headers=vanhanh_h,
                    json={"batch_code": "803", "line_id": brewhouse_line_id})
    batch_id = r.json()["batch_id"]

    rows = client.get(f"/api/brewing/brews/{brew_id}/batches", headers=admin_h).json()
    assert rows[0]["exec_status"] == "dang_thuc_hien"
    assert rows[0]["ended_at"] is None

    _declare_luong_dich(client, admin_h, brew_id, batch_id)
    chosen = "2026-02-01T10:00:00+00:00"
    ok = client.post(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/finish", headers=vanhanh_h,
                     json={"ended_at": chosen})
    assert ok.status_code == 200, ok.text
    assert ok.json()["ended_at"] == chosen

    rows = client.get(f"/api/brewing/brews/{brew_id}/batches", headers=admin_h).json()
    assert rows[0]["exec_status"] == "hoan_thanh"
    assert rows[0]["exec_status_label"] == "Hoàn thành"

    # Vận hành bấm nhầm giờ — sửa lại (gọi lại "Kết thúc" lần 2 không bị chặn).
    corrected = "2026-02-01T11:30:00+00:00"
    fixed = client.post(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/finish", headers=vanhanh_h,
                        json={"ended_at": corrected})
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["ended_at"] == corrected


def test_finish_brew_batch_defaults_to_now_without_explicit_time(client, admin_h, vanhanh_h, brewhouse_line_id):
    brew_id = _a_brew(client, admin_h, vanhanh_h, "FINISHBATCHNOW")
    r = client.post(f"/api/brewing/brews/{brew_id}/batches", headers=vanhanh_h,
                    json={"batch_code": "804", "line_id": brewhouse_line_id})
    batch_id = r.json()["batch_id"]
    _declare_luong_dich(client, admin_h, brew_id, batch_id)
    before = datetime.now(timezone.utc)
    ok = client.post(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/finish", headers=vanhanh_h)
    assert ok.status_code == 200, ok.text
    after = datetime.now(timezone.utc)
    ended_at = datetime.fromisoformat(ok.json()["ended_at"])
    assert before - timedelta(seconds=5) <= ended_at <= after + timedelta(seconds=5)


def _setup_ferment(client, admin_h, vanhanh_h, suffix):
    brew_id = _a_brew(client, admin_h, vanhanh_h, suffix)
    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment = next(f for f in ferments if f["lm_code"] == f"LM-{suffix}")
    ok = client.post(f"/api/brewing/ferments/{ferment['ferment_id']}/approve", headers=admin_h)
    assert ok.status_code == 200, ok.text
    return brew_id, f"T-{suffix}", ferment["ferment_id"]


def _a_filter_order(client, admin_h, order_code, ferment_ids, blend_mode="khong_phoi"):
    r = client.post("/api/brewing/filter-orders", headers=admin_h,
                    json={"order_code": order_code, "blend_mode": blend_mode, "tank_ferment_ids": ferment_ids,
                          "planned_volume_hl": 1000})
    assert r.status_code == 201, r.text
    return r.json()["filter_order_id"]


def _first_tank_line_id(client, admin_h, filter_id):
    tanks = client.get(f"/api/brewing/filters/{filter_id}/tanks", headers=admin_h).json()
    return tanks[0]["line_id"]


def test_finish_filter_is_correctable(client, admin_h, vanhanh_h):
    _, tank, ferment_id = _setup_ferment(client, admin_h, vanhanh_h, "FINISHFILTER")
    order_id = _a_filter_order(client, admin_h, "LOC-FINISHFILTER", [ferment_id])
    f = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": "FL-FINISH-01", "beer_type": "Bia test", "wort_type": "Dịch test",
                          "filter_order_id": order_id, "to_bbt": "BBT-FINISH-01"})
    assert f.status_code == 201, f.text
    filter_id = f.json()["filter_id"]
    line_id = _first_tank_line_id(client, admin_h, filter_id)

    rows = client.get("/api/brewing/filters", headers=admin_h).json()
    row = next(r for r in rows if r["filter_code"] == "FL-FINISH-01")
    assert row["exec_status"] == "dang_thuc_hien"

    ok = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line_id}/finish", headers=vanhanh_h,
                     json={"ended_at": "2026-02-01T09:00:00+00:00", "v_dich_hl": 100, "nuoc_bai_khi_hl": 0,
                           "batch_number": "B-FINISH-01", "order_number": "O-FINISH-01", "batch_seq_no": "1"})
    assert ok.status_code == 200, ok.text

    rows = client.get("/api/brewing/filters", headers=admin_h).json()
    row = next(r for r in rows if r["filter_code"] == "FL-FINISH-01")
    assert row["exec_status"] == "hoan_thanh"
    # trạng thái suy ra từ tồn kho (status) — chưa Duyệt KCS nên phải là "chờ duyệt", KHÔNG
    # phải "chờ chiết" (chưa được phép chiết cho tới khi KCS duyệt, xem derived.filter_status).
    assert row["status"] == "cho_duyet"

    fixed = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line_id}/finish", headers=vanhanh_h,
                        json={"ended_at": "2026-02-01T09:45:00+00:00",
                              "batch_number": "B-FINISH-01", "order_number": "O-FINISH-01", "batch_seq_no": "1"})
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["ended_at"] == "2026-02-01T09:45:00+00:00"


def test_filter_volumes_deferred_to_finish_and_auto_computed(client, admin_h, vanhanh_h):
    """Dịch nha lọc/Sản lượng lọc không bắt buộc lúc tạo — điền (kèm Nước bài khí) khi bấm
    "Kết thúc"; Sản lượng lọc tự tính = Dịch nha lọc + Nước bài khí; on_hand_cct (tank LM
    nguồn) chỉ bị trừ SAU khi kết thúc, theo đúng số Dịch nha lọc thật."""
    _, tank, ferment_id = _setup_ferment(client, admin_h, vanhanh_h, "FILTERVOL")
    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment = next(f for f in ferments if f["tank_lm"] == tank)
    cct_before = ferment["on_hand_cct"]

    order_id = _a_filter_order(client, admin_h, "LOC-FILTERVOL", [ferment_id])
    f = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": "FL-VOL-01", "beer_type": "Bia test", "wort_type": "Dịch test",
                          "filter_order_id": order_id, "to_bbt": "BBT-VOL-01"})
    assert f.status_code == 201, f.text
    filter_id = f.json()["filter_id"]
    line_id = _first_tank_line_id(client, admin_h, filter_id)
    assert f.json()["v_dich_hl"] == 0
    assert f.json()["v_beer_hl"] == 0

    rows = client.get("/api/brewing/filters", headers=admin_h).json()
    row = next(r for r in rows if r["filter_code"] == "FL-VOL-01")
    assert row["status"] == "dang_loc"  # chưa bấm Kết thúc — không được báo "chờ chiết" (dễ hiểu nhầm là đã lọc xong)

    ok = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line_id}/finish", headers=vanhanh_h,
                     json={"ended_at": "2026-02-05T09:00:00+00:00", "v_dich_hl": 90, "nuoc_bai_khi_hl": 10,
                           "batch_number": "B-VOL-01", "order_number": "O-VOL-01", "batch_seq_no": "1"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["v_dich_hl"] == 90
    assert ok.json()["nuoc_bai_khi_hl"] == 10
    assert ok.json()["v_beer_hl"] == 100
    assert ok.json()["on_hand_bbt"] == 100

    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment = next(f for f in ferments if f["tank_lm"] == tank)
    assert ferment["on_hand_cct"] == cct_before - 90

    # Sửa lại số liệu (bấm nhầm) — chênh lệch phải áp dụng đúng, không cộng dồn sai.
    fixed = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line_id}/finish", headers=vanhanh_h,
                        json={"ended_at": "2026-02-05T09:00:00+00:00", "v_dich_hl": 80, "nuoc_bai_khi_hl": 20,
                              "batch_number": "B-VOL-01", "order_number": "O-VOL-01", "batch_seq_no": "1"})
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["v_beer_hl"] == 100
    assert fixed.json()["on_hand_bbt"] == 100
    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment = next(f for f in ferments if f["tank_lm"] == tank)
    assert ferment["on_hand_cct"] == cct_before - 80


def test_finish_bottle_is_correctable(client, admin_h, vanhanh_h):
    b = client.post("/api/brewing/bottles", headers=vanhanh_h,
                    json={"bottle_code": "CH-FINISH-01", "beer_type": "Bia test"})
    assert b.status_code == 201, b.text
    bottle_id = b.json()["bottle_id"]

    ok = client.post(f"/api/brewing/bottles/{bottle_id}/finish", headers=vanhanh_h,
                     json={"ended_at": "2026-02-01T09:00:00+00:00"})
    assert ok.status_code == 200, ok.text
    rows = client.get("/api/brewing/bottles", headers=admin_h).json()
    row = next(r for r in rows if r["bottle_code"] == "CH-FINISH-01")
    assert row["exec_status"] == "hoan_thanh"

    fixed = client.post(f"/api/brewing/bottles/{bottle_id}/finish", headers=vanhanh_h,
                        json={"ended_at": "2026-02-01T09:45:00+00:00"})
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["ended_at"] == "2026-02-01T09:45:00+00:00"


def test_lo_status_report_full_chain(client, admin_h, vanhanh_h, brewhouse_line_id):
    brew_id, tank, ferment_id = _setup_ferment(client, admin_h, vanhanh_h, "LOSTATUS")

    def _row():
        rows = client.get("/api/reports/lo-status", headers=admin_h).json()
        return next(r for r in rows if r["brew_id"] == brew_id)

    # Chưa có mẻ nào → "chua_co_me"; chưa mẻ nào bấm Kết thúc nên lô LM vẫn "đang nấu"
    # (kt_date rỗng, xem services/derived.py::ferment_status), CHƯA phải "đang lên men".
    row = _row()
    assert row["nau"] == "chua_co_me"
    assert row["len_men"] == "dang_nau"
    assert row["loc"] == "chua_loc"
    assert row["chiet"] == "chua_chiet"

    batch = client.post(f"/api/brewing/brews/{brew_id}/batches", headers=vanhanh_h,
                        json={"batch_code": "805", "line_id": brewhouse_line_id}).json()
    row = _row()
    assert row["nau"] == "dang_thuc_hien"
    assert row["len_men"] == "dang_nau"

    _declare_luong_dich(client, admin_h, brew_id, batch["batch_id"])
    client.post(f"/api/brewing/brews/{brew_id}/batches/{batch['batch_id']}/finish", headers=vanhanh_h)
    row = _row()
    assert row["nau"] == "hoan_thanh"
    # Mẻ duy nhất đã kết thúc → kt_date được set → chuyển sang "đang lên men".
    assert row["len_men"] == "len_men"

    order_id = _a_filter_order(client, admin_h, "LOC-LOSTATUS", [ferment_id])
    f = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": "FL-LOSTATUS-01", "beer_type": "Bia test", "wort_type": "Dịch test",
                          "filter_order_id": order_id, "to_bbt": "BBT-LOSTATUS-01"}).json()
    row = _row()
    assert row["loc"] == "dang_loc"
    assert row["chiet"] == "chua_chiet"

    line_id = _first_tank_line_id(client, admin_h, f["filter_id"])
    client.post(f"/api/brewing/filters/{f['filter_id']}/tanks/{line_id}/finish", headers=vanhanh_h,
               json={"v_dich_hl": 100, "nuoc_bai_khi_hl": 0,
                     "batch_number": "B-LOSTATUS-01", "order_number": "O-LOSTATUS-01", "batch_seq_no": "1"})
    row = _row()
    assert row["loc"] == "da_ket_thuc"

    approve_f = client.post(f"/api/brewing/filters/{f['filter_id']}/approve", headers=admin_h)
    assert approve_f.status_code == 200, approve_f.text

    bo = client.post("/api/brewing/bottles", headers=vanhanh_h,
                     json={"bottle_code": "CH-LOSTATUS-01", "beer_type": "Bia test",
                           "from_bbt": "BBT-LOSTATUS-01", "v_cap_chiet_hl": 50}).json()
    row = _row()
    assert row["chiet"] == "dang_chiet"

    client.post(f"/api/brewing/bottles/{bo['bottle_id']}/finish", headers=vanhanh_h)
    row = _row()
    assert row["chiet"] == "da_ket_thuc"


def test_ferment_kt_date_blank_until_all_batches_finished(client, admin_h, vanhanh_h, brewhouse_line_id):
    """Ngày KT (nạp đầy tank) không nhập tay — PHẢI để trống chừng nào còn mẻ nào chưa bấm
    "Kết thúc" (tank chưa thật sự đầy); chỉ có giá trị khi TẤT CẢ mẻ đã xong, và giá trị đó
    là giờ kết thúc mẻ CUỐI CÙNG (lớn nhất), cập nhật lại nếu sửa giờ kết thúc sau đó."""
    brew_id, _, _ = _setup_ferment(client, admin_h, vanhanh_h, "KTDATE")

    def _brew_row():
        rows = client.get("/api/brewing/brews", headers=admin_h).json()
        return next(r for r in rows if r["brew_id"] == brew_id)

    def _ferment_row():
        items = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
        return next(f for f in items if f["lm_code"] == "LM-KTDATE")

    assert _brew_row()["kt_date"] is None

    b1 = client.post(f"/api/brewing/brews/{brew_id}/batches", headers=vanhanh_h,
                     json={"batch_code": "806", "line_id": brewhouse_line_id}).json()
    b2 = client.post(f"/api/brewing/brews/{brew_id}/batches", headers=vanhanh_h,
                     json={"batch_code": "807", "line_id": brewhouse_line_id}).json()

    _declare_luong_dich(client, admin_h, brew_id, b1["batch_id"])
    _declare_luong_dich(client, admin_h, brew_id, b2["batch_id"])

    # Mẻ 1 xong nhưng mẻ 2 CHƯA — kt_date phải vẫn để trống, không được lấy giờ mẻ 1.
    client.post(f"/api/brewing/brews/{brew_id}/batches/{b1['batch_id']}/finish", headers=vanhanh_h,
               json={"ended_at": "2026-03-01T08:00:00+00:00"})
    assert _brew_row()["kt_date"] is None
    assert _ferment_row()["kt_date"] is None

    # Mẻ 2 kết thúc SAU — giờ cả 2 mẻ đã xong, kt_date = mẻ cuối cùng (giờ lớn nhất).
    client.post(f"/api/brewing/brews/{brew_id}/batches/{b2['batch_id']}/finish", headers=vanhanh_h,
               json={"ended_at": "2026-03-01T10:30:00+00:00"})
    assert _brew_row()["kt_date"] == "2026-03-01T10:30:00+00:00"
    assert _ferment_row()["kt_date"] == "2026-03-01T10:30:00+00:00"

    # Sửa lại giờ mẻ 2 về SỚM hơn mẻ 1 — kt_date phải lùi lại đúng theo mẻ 1 (vẫn là max thật).
    client.post(f"/api/brewing/brews/{brew_id}/batches/{b2['batch_id']}/finish", headers=vanhanh_h,
               json={"ended_at": "2026-03-01T07:00:00+00:00"})
    assert _brew_row()["kt_date"] == "2026-03-01T08:00:00+00:00"
