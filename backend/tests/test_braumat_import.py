"""Test import Step Protocol (Braumat) — ghi chép nấu tự động cho 1 mẻ.

Phần state-machine phân tích bảng (parse_step_protocol_pdf/_parse_row_stream) đã được
đối chiếu thủ công với 9 file Step Protocol thật (RiceCooker/MashTun/LauterTun/
WortKettle+2 vòi hoa/SpentGrain/WhirlPool/Start BH) trong phiên làm việc — khớp tuyệt
đối từng giá trị. File PDF thật là tài liệu nội bộ nằm ngoài repo nên không đưa vào đây
làm fixture; các test dưới dùng dữ liệu hàng (binned rows) dựng tay để phủ đúng cấu
trúc đã xác thực, và monkeypatch phần đọc PDF cho lớp HTTP/DB.
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
from app.services import braumat_import as bi


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


# ---- Lõi state-machine (dựng tay dữ liệu hàng, khớp cấu trúc thật đã xác thực) ----

def test_parse_row_stream_primary_and_continuation_params():
    """1 bước với 6 tham số (4 chính + 2 tiếp diễn) — đúng cấu trúc 'RC1 Mash in Rice'
    thật: hàng nhãn (step_no/eop/name/date/time + 4 nhãn cột) -> hàng trên (giá trị
    SETPOINT, không có date) -> hàng dưới (giá trị THỰC TẾ, có date/time kết thúc) ->
    rồi 1 nhóm tiếp diễn (nhãn/setpoint/actual) cho 2 tham số 5-6. Hàng dưới = Thực tế vì
    khớp với elapsed_actual/end_at của bước (cùng hàng) — đã đối chiếu số liệu thật với
    người dùng (VD "Time RC1 [Min.]" hàng dưới = 4.5 ≈ elapsed_actual 00:04:32)."""
    rows = [
        # header cho Order Number/Recipe/Batch Number/Unit
        {"stepno": ["Order Number"], "col4": [":"], "name": ["00171"]},
        {"stepno": ["Batch Number"], "col4": [":"], "name": ["1698"]},
        {"stepno": ["Unit"], "col4": [":"], "name": ["RiceCooker"]},
        # bước 1: header + 4 nhãn cột
        {"stepno": ["1"], "eop": ["14.0"], "name": ["RC1 Mash in Rice"],
         "date": ["10.07.26"], "time": ["03:01:37"], "elapsed": ["Time"],
         "col1": ["Time RC1 [Min.]"], "col2": ["0201.M01_SP [%]"],
         "col3": ["cold_Water Mix [hl]"], "col4": ["Hot_water_rice [hl]"]},
        # hàng trên (giá trị setpoint, elapsed literal, không có date)
        {"elapsed": ["00:00:00"], "col1": ["8.0"], "col2": ["80"], "col3": ["2"], "col4": ["23"]},
        # hàng dưới (giá trị thực tế, có date/time kết thúc + elapsed thực)
        {"date": ["10.07.26"], "time": ["03:06:09"], "elapsed": ["00:04:32"],
         "col1": ["4.5"], "col2": ["0"], "col3": ["2"], "col4": ["23"]},
        # nhóm tiếp diễn: nhãn (tham số 5-6)
        {"col1": ["RC Temperature [oC]"], "col2": ["Rice Weight [Kg]"]},
        # nhóm tiếp diễn: hàng trên (setpoint)
        {"col1": ["0.0"], "col2": ["0.0"]},
        # nhóm tiếp diễn: hàng dưới (actual)
        {"col1": ["70.2"], "col2": ["449.0"]},
    ]
    result = bi._parse_row_stream([rows])
    assert result["order_number"] == "00171"
    assert result["batch_number"] == "1698"
    assert "RiceCooker" in result["units"]
    steps = result["units"]["RiceCooker"]
    assert len(steps) == 1
    s = steps[0]
    assert s["step_no"] == 1 and s["eop"] == "14.0" and s["name"] == "RC1 Mash in Rice"
    assert s["start"] == "10.07.26 03:01:37"
    assert s["end"] == "10.07.26 03:06:09"
    assert s["elapsed_actual"] == "00:04:32"
    assert s["params"]["Time RC1 [Min.]"] == {"setpoint": "8.0", "actual": "4.5"}
    assert s["params"]["0201.M01_SP [%]"] == {"setpoint": "80", "actual": "0"}
    assert s["params"]["cold_Water Mix [hl]"] == {"setpoint": "2", "actual": "2"}
    assert s["params"]["Hot_water_rice [hl]"] == {"setpoint": "23", "actual": "23"}
    assert s["params"]["RC Temperature [oC]"] == {"setpoint": "0.0", "actual": "70.2"}
    assert s["params"]["Rice Weight [Kg]"] == {"setpoint": "0.0", "actual": "449.0"}


def test_parse_row_stream_multiple_steps_and_units():
    rows = [
        {"stepno": ["Unit"], "name": ["Start BH"]},
        {"stepno": ["1"], "eop": ["32700"], "name": ["Start"], "date": ["10.07.26"], "time": ["03:01:30"],
         "elapsed": ["Time"]},
        {"elapsed": ["00:00:00"]},
        {"date": ["10.07.26"], "time": ["03:01:30"], "elapsed": ["00:00:00"]},
        {"stepno": ["2"], "eop": ["13.0"], "name": ["Start_BH"], "date": ["10.07.26"], "time": ["03:01:30"],
         "elapsed": ["Time"]},
        {"elapsed": ["00:00:00"]},
        {"date": ["10.07.26"], "time": ["03:01:37"], "elapsed": ["00:00:07"]},
    ]
    result = bi._parse_row_stream([rows])
    steps = result["units"]["Start BH"]
    assert len(steps) == 2
    assert steps[0]["name"] == "Start" and steps[0]["elapsed_actual"] == "00:00:00"
    assert steps[1]["name"] == "Start_BH" and steps[1]["elapsed_actual"] == "00:00:07"


def test_parse_braumat_dt():
    dt = bi._parse_braumat_dt("10.07.26 03:01:37")
    assert dt is not None
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second) == (2026, 7, 10, 3, 1, 37)
    assert bi._parse_braumat_dt(None) is None
    assert bi._parse_braumat_dt("garbage") is None


# ---- Lớp HTTP/DB: monkeypatch phần đọc PDF, test import/replace/GET/PUT/permission ----

def _fake_parsed(batch_number="1698", unit="RiceCooker", n_steps=2):
    steps = []
    for i in range(1, n_steps + 1):
        steps.append({
            "step_no": i, "eop": f"{i}.0", "name": f"Step {i}",
            "start": "10.07.26 03:00:00", "end": "10.07.26 03:10:00",
            "elapsed_actual": "00:10:00",
            "params": {"Temp [oC]": {"setpoint": "70.0", "actual": "70.5"}},
        })
    return {"order_number": "00171", "recipe_category": "BrewHouse", "recipe": "Bia test",
            "batch_number": batch_number, "units": {unit: steps}}


def _a_brew_order(client, admin_h, order_code, product_id=None):
    r = client.post("/api/brewing/orders", headers=admin_h,
                    json={"order_code": order_code, "product_id": product_id, "auto_from_bom": False, "planned_volume_hl": 100})
    assert r.status_code == 201, r.text
    return r.json()["brew_order_id"]


def _setup_batch(client, admin_h, brew_code, batch_code, line_id):
    order_id = _a_brew_order(client, admin_h, f"LN-{brew_code}")
    b = client.post("/api/brewing/brews", headers=admin_h,
                    json={"brew_code": brew_code, "wort_type": "Dich test", "volume_hl": 100,
                          "brew_order_id": order_id})
    assert b.status_code == 201, b.text
    brew_id = b.json()["brew_id"]
    mb = client.post(f"/api/brewing/brews/{brew_id}/batches", headers=admin_h,
                     json={"batch_code": batch_code, "line_id": line_id})
    assert mb.status_code == 201, mb.text
    return brew_id, mb.json()["batch_id"]


def test_import_creates_steps_and_get_returns_checkpoints(client, admin_h, monkeypatch, brewhouse_line_id):
    brew_id, batch_id = _setup_batch(client, admin_h, "BR-BRAUMAT-1", "401", brewhouse_line_id)
    monkeypatch.setattr(bi, "parse_step_protocol_pdf", lambda data: _fake_parsed(batch_number="401"))

    resp = client.post(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/process-log/import",
                       headers=admin_h, files=[("files", ("unit1.pdf", b"%PDF-fake", "application/pdf"))])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["units"] == {"RiceCooker": 2}
    assert body["warning"] is None

    get_resp = client.get(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/process-log", headers=admin_h)
    assert get_resp.status_code == 200, get_resp.text
    data = get_resp.json()
    assert len(data["steps"]) == 2
    assert data["braumat_order_number"] == "00171"
    assert data["braumat_recipe"] == "Bia test"


def test_reimport_replaces_steps_for_same_unit_not_duplicates(client, admin_h, monkeypatch, brewhouse_line_id):
    brew_id, batch_id = _setup_batch(client, admin_h, "BR-BRAUMAT-2", "402", brewhouse_line_id)
    monkeypatch.setattr(bi, "parse_step_protocol_pdf", lambda data: _fake_parsed(batch_number="BATCH-2", n_steps=3))
    r1 = client.post(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/process-log/import",
                     headers=admin_h, files=[("files", ("a.pdf", b"x", "application/pdf"))])
    assert r1.json()["units"] == {"RiceCooker": 3}

    monkeypatch.setattr(bi, "parse_step_protocol_pdf", lambda data: _fake_parsed(batch_number="BATCH-2", n_steps=5))
    r2 = client.post(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/process-log/import",
                     headers=admin_h, files=[("files", ("a.pdf", b"x", "application/pdf"))])
    assert r2.json()["units"] == {"RiceCooker": 5}

    get_resp = client.get(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/process-log", headers=admin_h)
    assert len(get_resp.json()["steps"]) == 5, "phải thay thế hoàn toàn, không cộng dồn (2 lần import -> vẫn 5, không phải 8)"


def test_import_mismatched_batch_number_warns_but_succeeds(client, admin_h, monkeypatch, brewhouse_line_id):
    brew_id, batch_id = _setup_batch(client, admin_h, "BR-BRAUMAT-3", "403", brewhouse_line_id)
    monkeypatch.setattr(bi, "parse_step_protocol_pdf", lambda data: _fake_parsed(batch_number="9999-BRAUMAT"))
    resp = client.post(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/process-log/import",
                       headers=admin_h, files=[("files", ("a.pdf", b"x", "application/pdf"))])
    assert resp.status_code == 200, resp.text
    assert resp.json()["warning"] is not None
    assert "9999-BRAUMAT" in resp.json()["warning"]


def test_import_conflicting_batch_numbers_across_files_rejected(client, admin_h, monkeypatch, brewhouse_line_id):
    brew_id, batch_id = _setup_batch(client, admin_h, "BR-BRAUMAT-4", "404", brewhouse_line_id)
    calls = {"n": 0}

    def fake_parse(data):
        calls["n"] += 1
        return _fake_parsed(batch_number="A111" if calls["n"] == 1 else "B222", unit=f"Unit{calls['n']}")

    monkeypatch.setattr(bi, "parse_step_protocol_pdf", fake_parse)
    resp = client.post(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/process-log/import",
                       headers=admin_h,
                       files=[("files", ("a.pdf", b"x", "application/pdf")),
                              ("files", ("b.pdf", b"y", "application/pdf"))])
    assert resp.status_code == 409, resp.text
    assert "khác nhau" in resp.json()["detail"]


def test_import_all_files_empty_rejected(client, admin_h, monkeypatch, brewhouse_line_id):
    brew_id, batch_id = _setup_batch(client, admin_h, "BR-BRAUMAT-5", "405", brewhouse_line_id)
    monkeypatch.setattr(bi, "parse_step_protocol_pdf", lambda data: {
        "order_number": "00171", "recipe_category": "BrewHouse", "recipe": None,
        "batch_number": None, "units": {},
    })
    resp = client.post(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/process-log/import",
                       headers=admin_h, files=[("files", ("overview.pdf", b"x", "application/pdf"))])
    assert resp.status_code == 409, resp.text


def test_import_requires_batch_execute_permission(client, admin_h, monkeypatch, brewhouse_line_id):
    """kcs (quality.release only) không được import — chỉ vanhanh/admin (batch.execute)."""
    kcs_h = _login(client, "kcs", "123456")
    brew_id, batch_id = _setup_batch(client, admin_h, "BR-BRAUMAT-6", "406", brewhouse_line_id)
    monkeypatch.setattr(bi, "parse_step_protocol_pdf", lambda data: _fake_parsed(batch_number="BATCH-6"))
    resp = client.post(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/process-log/import",
                       headers=kcs_h, files=[("files", ("a.pdf", b"x", "application/pdf"))])
    assert resp.status_code == 403, resp.text


def test_update_manual_fields(client, admin_h, brewhouse_line_id):
    """Ghi chép nấu (Thực hiện) — manual_json chấp nhận bất kỳ key nào trong
    MANUAL_FIELD_KEYS (bao gồm cả các bước nhiệt độ VD rc_step1_nhietdo)."""
    brew_id, batch_id = _setup_batch(client, admin_h, "BR-BRAUMAT-7", "407", brewhouse_line_id)
    resp = client.put(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/process-log", headers=admin_h,
                      json={"rc_ph_nuoc": 7.1, "wk_houb1_hoacao_kg": 2.5, "whp_maturex_pro_added": True,
                            "rc_step1_nhietdo": 71.3, "rc_step1_batdau": "3:20", "note": "ghi chú thử"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rc_ph_nuoc"] == 7.1
    assert body["wk_houb1_hoacao_kg"] == 2.5
    assert body["whp_maturex_pro_added"] is True
    assert body["rc_step1_nhietdo"] == 71.3
    assert body["rc_step1_batdau"] == "3:20"
    assert body["note"] == "ghi chú thử"

    get_resp = client.get(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/process-log", headers=admin_h)
    data = get_resp.json()
    assert data["manual"]["rc_ph_nuoc"] == 7.1
    assert data["note"] == "ghi chú thử"
    assert "unknown_field_xyz" not in bi.MANUAL_FIELD_KEYS


def test_product_brew_spec_get_update_and_admin_gating(client, admin_h):
    """Quy định (Product.spec_json) — chỉ master.manage (admin) sửa được; vanhanh
    (chỉ có batch.execute) bị chặn. Key lạ bị bỏ qua, không lỗi."""
    p = client.post("/api/products", headers=admin_h,
                    json={"code": "SAP-SPEC-TEST", "name": "Sapphire spec test", "uom": "L"})
    assert p.status_code == 201, p.text
    product_id = p.json()["product_id"]

    get1 = client.get(f"/api/products/{product_id}/brew-spec", headers=admin_h)
    assert get1.status_code == 200, get1.text
    assert get1.json()["rc_nuoc_hl"] is None

    vanhanh_h = _login(client, "vanhanh", "123456")
    forbidden = client.put(f"/api/products/{product_id}/brew-spec", headers=vanhanh_h,
                           json={"rc_nuoc_hl": 28})
    assert forbidden.status_code == 403, forbidden.text

    put_resp = client.put(f"/api/products/{product_id}/brew-spec", headers=admin_h,
                          json={"rc_nuoc_hl": 28, "rc_ph_nuoc": 6.2, "unknown_field_xyz": 999})
    assert put_resp.status_code == 200, put_resp.text
    body = put_resp.json()
    assert body["rc_nuoc_hl"] == 28
    assert body["rc_ph_nuoc"] == 6.2
    assert "unknown_field_xyz" not in body

    get2 = client.get(f"/api/products/{product_id}/brew-spec", headers=admin_h)
    assert get2.json()["rc_nuoc_hl"] == 28


def test_process_log_includes_spec_from_brew_product(client, admin_h, brewhouse_line_id):
    """GET /process-log phải trả spec (Quy định) tra theo product_id của mã nấu, để FE
    hiện Quy định cạnh Thực hiện — dùng chung 1 bộ key giữa spec_json và manual_json."""
    p = client.post("/api/products", headers=admin_h,
                    json={"code": "SAP-SPEC-TEST-2", "name": "Sapphire spec test 2", "uom": "L"})
    product_id = p.json()["product_id"]
    client.put(f"/api/products/{product_id}/brew-spec", headers=admin_h, json={"rc_nuoc_hl": 28})

    order_id = _a_brew_order(client, admin_h, "LN-BR-SPEC-TEST", product_id=product_id)
    b = client.post("/api/brewing/brews", headers=admin_h,
                    json={"brew_code": "BR-SPEC-TEST", "wort_type": "Dich test", "volume_hl": 100,
                          "product_id": product_id, "brew_order_id": order_id})
    brew_id = b.json()["brew_id"]
    mb = client.post(f"/api/brewing/brews/{brew_id}/batches", headers=admin_h,
                     json={"batch_code": "301", "line_id": brewhouse_line_id})
    batch_id = mb.json()["batch_id"]

    get_resp = client.get(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/process-log", headers=admin_h)
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["spec"]["rc_nuoc_hl"] == 28


def test_list_process_steps_orders_by_real_process_sequence(client, admin_h, monkeypatch, brewhouse_line_id):
    """GET phải trả steps theo đúng thứ tự dây nấu thật (RiceCooker -> MashTun -> ... ->
    Whirlpool), không phải alphabet (alphabet sẽ đưa MashTun lên trước RiceCooker). Cũng
    xác nhận tên unit kèm số hiệu nồi/dây (VD 'Holding Vessel 01'/'02' — nhà máy có 2 dây
    nấu, mỗi dây 1 nồi trung gian riêng) được giữ nguyên vẹn, không bị cắt/gộp."""
    brew_id, batch_id = _setup_batch(client, admin_h, "BR-BRAUMAT-9", "409", brewhouse_line_id)

    def fake_parsed():
        step = lambda: {"step_no": 1, "eop": "1.0", "name": "X", "start": "10.07.26 03:00:00",
                        "end": "10.07.26 03:01:00", "elapsed_actual": "00:01:00", "params": {}}
        return {"order_number": "00171", "recipe_category": "BrewHouse", "recipe": "Bia test",
                "batch_number": "BATCH-9", "units": {
                    "WhirlPool": [step()], "Holding Vessel 02": [step()], "RiceCooker": [step()],
                    "MashTun": [step()], "Holding Vessel 01": [step()], "WortKettle": [step()],
                }}

    monkeypatch.setattr(bi, "parse_step_protocol_pdf", lambda data: fake_parsed())
    resp = client.post(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/process-log/import",
                       headers=admin_h, files=[("files", ("a.pdf", b"x", "application/pdf"))])
    assert resp.status_code == 200, resp.text

    get_resp = client.get(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/process-log", headers=admin_h)
    units_in_order = [s["unit"] for s in get_resp.json()["steps"]]
    assert units_in_order == [
        "RiceCooker", "MashTun", "Holding Vessel 01", "Holding Vessel 02", "WortKettle", "WhirlPool",
    ]


def test_delete_batch_cascades_process_log_and_steps(client, admin_h, monkeypatch, brewhouse_line_id):
    brew_id, batch_id = _setup_batch(client, admin_h, "BR-BRAUMAT-8", "408", brewhouse_line_id)
    monkeypatch.setattr(bi, "parse_step_protocol_pdf", lambda data: _fake_parsed(batch_number="BATCH-8"))
    client.post(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/process-log/import",
               headers=admin_h, files=[("files", ("a.pdf", b"x", "application/pdf"))])
    client.put(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/process-log", headers=admin_h,
              json={"note": "sẽ bị xóa"})

    del_resp = client.delete(f"/api/brewing/brews/{brew_id}/batches/{batch_id}", headers=admin_h)
    assert del_resp.status_code == 204, del_resp.text

    from app.database import SessionLocal
    from app.models.brewing import BrewProcessLog, BrewProcessStep
    from sqlalchemy import select
    db = SessionLocal()
    try:
        assert db.execute(select(BrewProcessStep).where(BrewProcessStep.batch_id == batch_id)).first() is None
        assert db.execute(select(BrewProcessLog).where(BrewProcessLog.batch_id == batch_id)).first() is None
    finally:
        db.close()
