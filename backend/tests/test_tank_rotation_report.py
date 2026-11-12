"""BC "Tank lên men" (quay vòng) - yêu cầu người dùng 2026-11-12: "Làm cho tôi 1 báo cáo về tank
lên men như file excel bạn làm, tank lên men thể hiện cả dung tích nhé", tiếp nối hội thoại tính
tay/Excel trước đó (xem services/production_reports.py::tank_rotation_report).

Dùng năm 2031 (tương lai xa) cho mọi fixture để không đụng dữ liệu seed/test khác chạy ở "hiện
tại" thật của môi trường test (mirror test_production_reports.py)."""

import os
import tempfile
from datetime import datetime, timedelta

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


def _make_completed_batch(client, admin_h, batch_code, start_at_iso, end_at_iso, actual_qty):
    """Mẻ nấu đã "Kết thúc" với start_at/end_at TƯỜNG MINH (mirror test_production_reports.py::
    _build_batch_to_pack) — cần kiểm soát chính xác end_at để tính vao_dich_start (-78 phút) và
    khoảng cách quay vòng giữa 2 lượt vào dịch."""
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(x for x in vers if x["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                          "batch_code": batch_code, "planned_qty": actual_qty, "allow_shortage": True})
    assert b.status_code == 201, b.text
    batch_id = b.json()["batch_id"]
    st = client.post(f"/api/batches/{batch_id}/start", headers=admin_h, json={"start_at": start_at_iso})
    assert st.status_code == 200, st.text
    for target in ("ready", "running"):
        r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": target})
        assert r.status_code == 200, r.text
    aq = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": actual_qty})
    assert aq.status_code == 200, aq.text
    fin = client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={"end_at": end_at_iso})
    assert fin.status_code == 200, fin.text
    r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "completed"})
    assert r.status_code == 200, r.text
    return batch_id


def test_tank_rotation_report_capacity_and_turnover(client, admin_h):
    cap = client.post("/api/lines", headers=admin_h, json={
        "code": "ZROT01", "name": "Tank test quay vòng", "kind": "tank",
        "volume": 2000, "volume_uom": "hl", "usable_pct": 90,
    })
    assert cap.status_code == 201, cap.text

    # actual_qty NHỎ (trong ngưỡng dung sai làm rỗng mặc định empty_cct_tolerance_hl=2.0 hl) để
    # có thể "Làm rỗng tank" ngay sau đó, giải phóng tank_lm cho lượt vào dịch thứ 2 tái sử dụng
    # — mirror empty_tank() (không dùng để rút dịch thật, chỉ đưa tồn dư nhỏ về 0).
    b1 = _make_completed_batch(client, admin_h, "90001",
                               "2031-02-01T01:00:00+00:00", "2031-02-01T10:00:00+00:00", 1.5)
    tank_a = client.post("/api/batch-tanks", headers=admin_h, json={
        "batch_ids": [b1], "tank_code": "TANKROT-A", "tank_lm": "ZROT01"})
    assert tank_a.status_code == 201, tank_a.text
    tank_a_id = tank_a.json()["tank_id"]

    empt = client.post(f"/api/batch-tanks/{tank_a_id}/empty", headers=admin_h)
    assert empt.status_code == 200, empt.text

    b2 = _make_completed_batch(client, admin_h, "90002",
                               "2031-02-10T01:00:00+00:00", "2031-02-10T10:00:00+00:00", 600)
    tank_b = client.post("/api/batch-tanks", headers=admin_h, json={
        "batch_ids": [b2], "tank_code": "TANKROT-B", "tank_lm": "ZROT01"})
    assert tank_b.status_code == 201, tank_b.text

    rep = client.get("/api/reports/tank-rotation", headers=admin_h)
    assert rep.status_code == 200, rep.text
    data = rep.json()

    cur = next(r for r in data["current"] if r["tank_lm"] == "ZROT01")
    assert cur["capacity_hl"] == 2000
    assert cur["capacity_usable_hl"] == 1800.0
    assert cur["capacity_usable_pct"] == 90
    assert cur["tank_code"] == "TANKROT-B"   # lượt GẦN NHẤT
    assert cur["on_hand"] == 600
    assert cur["volume_hl"] == 600
    vao_dich_b = datetime.fromisoformat(cur["vao_dich_start"].replace("Z", "+00:00"))
    expected_b = datetime.fromisoformat("2031-02-10T10:00:00+00:00") - timedelta(minutes=78)
    assert abs((vao_dich_b - expected_b).total_seconds()) < 1
    assert cur["last_cycle_days"] == 9.0   # 78 phút trừ đều 2 phía nên triệt tiêu, còn đúng 9 ngày

    summary = next(s for s in data["tank_summaries"] if s["tank_lm"] == "ZROT01")
    assert summary["occurrences"] == 2
    assert summary["cycle_count"] == 1
    assert summary["avg_days"] == 9.0
    assert summary["min_days"] == 9.0
    assert summary["max_days"] == 9.0
    assert summary["cycles"] == [9.0]

    cycles = [c for c in data["cycles"] if c["tank_lm"] == "ZROT01"]
    assert len(cycles) == 1
    assert cycles[0]["cycle_no"] == 1
    assert cycles[0]["from_tank_code"] == "TANKROT-A"
    assert cycles[0]["to_tank_code"] == "TANKROT-B"
    assert cycles[0]["days"] == 9.0

    hist = [h for h in data["history"] if h["tank_lm"] == "ZROT01"]
    assert len(hist) == 2
    assert {h["tank_code"] for h in hist} == {"TANKROT-A", "TANKROT-B"}

    assert data["summary"] is not None
    assert data["summary"]["count"] >= 1


def test_tank_rotation_report_tank_without_catalog_entry_has_null_capacity(client, admin_h):
    """Tank vật lý KHÔNG có trong Danh mục "Tank lên men" (ProductionLine kind=tank) -> Dung
    tích = None thay vì lỗi/0 giả — vẫn phải hiện đủ các trường khác."""
    b = _make_completed_batch(client, admin_h, "90003",
                              "2031-03-01T01:00:00+00:00", "2031-03-01T10:00:00+00:00", 700)
    tank = client.post("/api/batch-tanks", headers=admin_h, json={
        "batch_ids": [b], "tank_code": "TANKROT-NOCAT", "tank_lm": "ZNOCAT01"})
    assert tank.status_code == 201, tank.text

    rep = client.get("/api/reports/tank-rotation", headers=admin_h)
    assert rep.status_code == 200, rep.text
    cur = next(r for r in rep.json()["current"] if r["tank_lm"] == "ZNOCAT01")
    assert cur["capacity_hl"] is None
    assert cur["capacity_usable_hl"] is None
    assert cur["on_hand"] == 700


def test_tank_rotation_report_does_not_mix_up_unnamed_tanks(client, admin_h):
    """2 tank KHÁC NHAU, CẢ 2 ĐỀU không gán tank_lm (tank_lm=None) — bug phát hiện khi test trên
    dev DB thật 2026-11-12: nếu nhóm theo tank_lm trần (NULL coi là 1 giá trị nhóm chung), 2 tank
    không liên quan gì tới nhau sẽ bị tính nhầm thành "cùng 1 tank quay vòng". Phải luôn tách
    riêng mỗi dòng tank_lm=None (occurrences=1 mỗi dòng, không có quay vòng nào)."""
    b1 = _make_completed_batch(client, admin_h, "90004",
                               "2031-04-01T01:00:00+00:00", "2031-04-01T10:00:00+00:00", 100)
    t1 = client.post("/api/batch-tanks", headers=admin_h,
                     json={"batch_ids": [b1], "tank_code": "TANKROT-NONAME-1"})
    assert t1.status_code == 201, t1.text

    b2 = _make_completed_batch(client, admin_h, "90005",
                               "2031-04-20T01:00:00+00:00", "2031-04-20T10:00:00+00:00", 200)
    t2 = client.post("/api/batch-tanks", headers=admin_h,
                     json={"batch_ids": [b2], "tank_code": "TANKROT-NONAME-2"})
    assert t2.status_code == 201, t2.text

    rep = client.get("/api/reports/tank-rotation", headers=admin_h).json()
    rows = [r for r in rep["current"] if r["tank_lm"] is None
           and r["tank_code"] in ("TANKROT-NONAME-1", "TANKROT-NONAME-2")]
    assert len(rows) == 2   # moi tank dung 1 dong rieng, KHONG bi gop lam 1
    for r in rows:
        assert r["last_cycle_days"] is None

    summaries = [s for s in rep["tank_summaries"] if s["tank_lm"] is None]
    assert all(s["occurrences"] == 1 and s["cycle_count"] == 0 for s in summaries)
    assert not any(c["tank_lm"] is None for c in rep["cycles"])
