"""Test "Ghi chép lên men" (biểu mẫu BM 1.11 (06)) — bảng thông tin đầu (manual_json,
mirror BrewProcessLog) + bảng theo ngày (FermentDailyReading, bảng con riêng để vẽ biểu đồ).
Xem services/ferment_log.py, routers/brewing.py::get_ferment_process_log/
update_ferment_process_log/update_ferment_daily_readings."""

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
from app.database import SessionLocal
from app.models.brewing import FermentRecord


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


@pytest.fixture(scope="module")
def kcs_h(client):
    return _login(client, "kcs", "123456")


def _make_ferment(client, admin_h, vanhanh_h, suffix):
    """Dựng 1 lô LM tối thiểu (Lệnh nấu -> mã nấu với lm_code/tank_lm -> FermentRecord tự
    tạo) — đủ để test Ghi chép lên men, không cần đi hết chuỗi lọc/chiết."""
    order = client.post("/api/brewing/orders", headers=admin_h,
                        json={"order_code": f"LN-FL-{suffix}", "auto_from_bom": False,
                              "planned_volume_hl": 100})
    assert order.status_code == 201, order.text
    brew_order_id = order.json()["brew_order_id"]

    brew = client.post("/api/brewing/brews", headers=vanhanh_h,
                       json={"brew_code": f"BR-FL-{suffix}", "wort_type": "Dịch test", "volume_hl": 100,
                             "lm_code": f"LM-FL-{suffix}", "tank_lm": f"T-FL-{suffix}",
                             "brew_order_id": brew_order_id})
    assert brew.status_code == 201, brew.text

    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment = next(f for f in ferments if f["lm_code"] == f"LM-FL-{suffix}")
    return ferment["ferment_id"]


def test_get_or_create_returns_all_keys_none(client, admin_h, vanhanh_h):
    ferment_id = _make_ferment(client, admin_h, vanhanh_h, "A")
    r = client.get(f"/api/brewing/ferments/{ferment_id}/process-log", headers=admin_h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["auto"] == {"so_me": "BR-FL-A", "so_tank": "T-FL-A", "the_tich_tank": 100.0,
                            "the_he": None, "kt_date": None,
                            "braumat_order_number": None, "braumat_batch_number": None}
    assert data["manual"]["kieu_men"] is None
    assert data["manual"]["mat_do_ml_b"] is None
    assert data["ha_phu_events"] == []
    assert data["readings"] == []


def test_update_manual_header_roundtrip_and_none_deletes_key(client, admin_h, vanhanh_h):
    ferment_id = _make_ferment(client, admin_h, vanhanh_h, "B")
    r = client.put(f"/api/brewing/ferments/{ferment_id}/process-log", headers=vanhanh_h,
                  json={"kieu_men": "B15.282", "mat_do_ml_b": 1585, "pct_song_c": 97.6, "note": "ghi chú test"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kieu_men"] == "B15.282"
    assert body["mat_do_ml_b"] == 1585
    assert body["note"] == "ghi chú test"

    got = client.get(f"/api/brewing/ferments/{ferment_id}/process-log", headers=admin_h).json()
    assert got["manual"]["kieu_men"] == "B15.282"
    assert got["manual"]["pct_song_c"] == 97.6
    assert got["note"] == "ghi chú test"

    r2 = client.put(f"/api/brewing/ferments/{ferment_id}/process-log", headers=vanhanh_h,
                    json={"kieu_men": None})
    assert r2.status_code == 200, r2.text
    got2 = client.get(f"/api/brewing/ferments/{ferment_id}/process-log", headers=admin_h).json()
    assert got2["manual"]["kieu_men"] is None
    assert got2["manual"]["pct_song_c"] == 97.6  # field khác không bị ảnh hưởng


def test_ha_phu_events_roundtrip_as_full_list(client, admin_h, vanhanh_h):
    ferment_id = _make_ferment(client, admin_h, vanhanh_h, "C")
    events = [{"at": "12h30 24/11/25", "nguoi_lenh": "Đang", "nguoi_nhan_lenh": "Phương",
               "truc_ca": "1", "note": ""}]
    r = client.put(f"/api/brewing/ferments/{ferment_id}/process-log", headers=vanhanh_h,
                  json={"ha_phu_events": events})
    assert r.status_code == 200, r.text
    assert r.json()["ha_phu_events"] == events

    got = client.get(f"/api/brewing/ferments/{ferment_id}/process-log", headers=admin_h).json()
    assert got["ha_phu_events"] == events

    r2 = client.put(f"/api/brewing/ferments/{ferment_id}/process-log", headers=vanhanh_h,
                    json={"ha_phu_events": []})
    assert r2.status_code == 200, r2.text
    assert r2.json()["ha_phu_events"] == []


def test_upsert_daily_readings_create_update_and_order(client, admin_h, vanhanh_h):
    ferment_id = _make_ferment(client, admin_h, vanhanh_h, "D")
    rows = [
        {"day_no": 2, "reading_date": "2025-11-25", "nhiet_do_c": 9.5, "do_s": 10.9, "mat_do_tb": None},
        {"day_no": 1, "reading_date": "2025-11-24", "nhiet_do_c": 9.5, "do_s": 13.10, "mat_do_tb": 9.4},
    ]
    r = client.put(f"/api/brewing/ferments/{ferment_id}/process-log/readings", headers=vanhanh_h,
                  json={"readings": rows})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [x["day_no"] for x in body] == [1, 2]  # thứ tự trả về theo day_no
    assert body[0]["mat_do_tb"] == 9.4
    assert body[1]["mat_do_tb"] is None

    # Cập nhật đè ngày 1 — không tạo dòng mới (unique ferment_id+day_no).
    r2 = client.put(f"/api/brewing/ferments/{ferment_id}/process-log/readings", headers=vanhanh_h,
                   json={"readings": [{"day_no": 1, "nhiet_do_c": 9.6}]})
    assert r2.status_code == 200, r2.text
    got = client.get(f"/api/brewing/ferments/{ferment_id}/process-log", headers=admin_h).json()
    assert len(got["readings"]) == 2
    day1 = next(x for x in got["readings"] if x["day_no"] == 1)
    assert day1["nhiet_do_c"] == 9.6


def test_daily_reading_audit_stamps_per_field_group(client, admin_h, vanhanh_h):
    """Không nhập tay tên người/giờ — mỗi nhóm trường (đo đạc/KCS/trực ca) tự ghi by/at khi có
    giá trị, và tự xoá khi người dùng xoá hết giá trị của nhóm đó (xem services/ferment_log.py::
    upsert_daily_readings)."""
    ferment_id = _make_ferment(client, admin_h, vanhanh_h, "G")
    r = client.put(f"/api/brewing/ferments/{ferment_id}/process-log/readings", headers=vanhanh_h,
                  json={"readings": [{"day_no": 1, "nhiet_do_c": 9.5, "kcs": "dat", "truc_ca": "1"}]})
    assert r.status_code == 200, r.text
    row = r.json()[0]
    assert row["measured_by"] == "vanhanh" and row["measured_at"] is not None
    assert row["kcs_by"] == "vanhanh" and row["kcs_at"] is not None
    assert row["truc_ca_by"] == "vanhanh" and row["truc_ca_at"] is not None

    # Xoá hết giá trị đo đạc (nhiet_do_c/do_s/mat_do_tb đều null) -> audit đo đạc bị xoá theo,
    # KCS/trực ca không đổi vì vẫn còn giá trị.
    r2 = client.put(f"/api/brewing/ferments/{ferment_id}/process-log/readings", headers=vanhanh_h,
                   json={"readings": [{"day_no": 1, "kcs": "dat", "truc_ca": "1"}]})
    assert r2.status_code == 200, r2.text
    row2 = r2.json()[0]
    assert row2["measured_by"] is None and row2["measured_at"] is None
    assert row2["kcs_by"] == "vanhanh"
    assert row2["truc_ca_by"] == "vanhanh"


def test_permission_denied_for_kcs(client, admin_h, vanhanh_h, kcs_h):
    ferment_id = _make_ferment(client, admin_h, vanhanh_h, "E")
    r1 = client.put(f"/api/brewing/ferments/{ferment_id}/process-log", headers=kcs_h,
                    json={"kieu_men": "X"})
    assert r1.status_code == 403, r1.text
    r2 = client.put(f"/api/brewing/ferments/{ferment_id}/process-log/readings", headers=kcs_h,
                    json={"readings": [{"day_no": 1, "nhiet_do_c": 9.5}]})
    assert r2.status_code == 403, r2.text


def test_locked_ferment_blocks_process_log_edits(client, admin_h, vanhanh_h):
    ferment_id = _make_ferment(client, admin_h, vanhanh_h, "F")
    db = SessionLocal()
    f = db.get(FermentRecord, ferment_id)
    f.locked = True
    f.locked_by = "admin"
    db.commit()
    db.close()

    r1 = client.put(f"/api/brewing/ferments/{ferment_id}/process-log", headers=vanhanh_h,
                    json={"kieu_men": "X"})
    assert r1.status_code == 409, r1.text
    assert "khóa" in r1.json()["detail"].lower()

    r2 = client.put(f"/api/brewing/ferments/{ferment_id}/process-log/readings", headers=vanhanh_h,
                    json={"readings": [{"day_no": 1, "nhiet_do_c": 9.5}]})
    assert r2.status_code == 409, r2.text


def test_auto_header_includes_real_braumat_order_and_batch_number(client, admin_h, vanhanh_h):
    """Ghi chép lên men không tự nhập Order Number/Batch Number — lấy THẬT từ dữ liệu Braumat
    đã import ở mẻ nấu nguồn (BrewProcessLog.braumat_order_number/braumat_batch_number), gộp
    qua chuỗi FermentBrewLink -> BrewRecord -> BrewBatch -> BrewProcessLog (xem
    services/ferment_log.py::_braumat_fields_for_ferment)."""
    order = client.post("/api/brewing/orders", headers=admin_h,
                        json={"order_code": "LN-FL-BRAUMAT", "auto_from_bom": False, "planned_volume_hl": 100})
    assert order.status_code == 201, order.text
    brew = client.post("/api/brewing/brews", headers=vanhanh_h,
                       json={"brew_code": "BR-FL-BRAUMAT", "wort_type": "Dịch test", "volume_hl": 100,
                             "lm_code": "LM-FL-BRAUMAT", "tank_lm": "T-FL-BRAUMAT",
                             "brew_order_id": order.json()["brew_order_id"]})
    assert brew.status_code == 201, brew.text
    batch = client.post(f"/api/brewing/brews/{brew.json()['brew_id']}/batches", headers=vanhanh_h,
                        json={"batch_code": "9001"})
    assert batch.status_code == 201, batch.text

    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment = next(f for f in ferments if f["lm_code"] == "LM-FL-BRAUMAT")

    from app.services.braumat_import import get_or_create_process_log
    db = SessionLocal()
    log = get_or_create_process_log(db, batch.json()["batch_id"])
    log.braumat_order_number = "ON-12345"
    log.braumat_batch_number = "BN-987"
    db.commit()
    db.close()

    r = client.get(f"/api/brewing/ferments/{ferment['ferment_id']}/process-log", headers=admin_h)
    assert r.status_code == 200, r.text
    auto = r.json()["auto"]
    assert auto["braumat_order_number"] == "ON-12345"
    assert auto["braumat_batch_number"] == "BN-987"
