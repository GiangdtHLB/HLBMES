"""Test Lệnh lọc (Filter Order) — không phối (1 tank lên men) / phối (2+ tank lên men lọc
chung vào 1 tank BBT, kết thúc riêng từng tank rồi cộng dồn) — mirror test_brew_order.py."""

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


@pytest.fixture(scope="module")
def lager_product_id(client, admin_h):
    products = client.get("/api/products", headers=admin_h).json()
    return next(p["product_id"] for p in products if p["code"] == "BIA-LAGER")


@pytest.fixture(scope="module")
def other_beer_type_id(client, admin_h):
    r = client.post("/api/beer-types", headers=admin_h, json={"code": "OTHERTYPE", "name": "Loại khác"})
    assert r.status_code == 201, r.text
    return r.json()["beer_type_id"]


@pytest.fixture(scope="module")
def other_product_id(client, admin_h, other_beer_type_id):
    """Dịch bia khác Loại bia với BIA-LAGER (seeded, Loại bia 'Lager') — dùng để test phối
    2 tank thuộc 2 Loại bia khác nhau (xem services/filter_order.py::_validate_tanks)."""
    r = client.post("/api/products", headers=admin_h,
                    json={"code": "PRD-FILTERORDER01", "name": "Dịch khác", "uom": "L",
                          "beer_type_id": other_beer_type_id})
    assert r.status_code == 201, r.text
    return r.json()["product_id"]


def _a_brew_order(client, admin_h, order_code):
    r = client.post("/api/brewing/orders", headers=admin_h,
                    json={"order_code": order_code, "auto_from_bom": False, "planned_volume_hl": 100})
    assert r.status_code == 201, r.text
    return r.json()["brew_order_id"]


def _setup_ferment(client, admin_h, vanhanh_h, suffix, product_id=None, approve=True):
    """Tạo 1 mã nấu + lô LM, tùy chọn duyệt KCS luôn — trả về ferment_id."""
    order_id = _a_brew_order(client, admin_h, f"LN-{suffix}")
    b = client.post("/api/brewing/brews", headers=vanhanh_h,
                    json={"brew_code": f"BR-{suffix}", "wort_type": "Dịch test", "volume_hl": 100,
                          "lm_code": f"LM-{suffix}", "tank_lm": f"T-{suffix}",
                          "brew_order_id": order_id, "product_id": product_id})
    assert b.status_code == 201, b.text
    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment = next(f for f in ferments if f["lm_code"] == f"LM-{suffix}")
    if approve:
        ok = client.post(f"/api/brewing/ferments/{ferment['ferment_id']}/approve", headers=admin_h)
        assert ok.status_code == 200, ok.text
    return ferment["ferment_id"]


def _a_filter_order(client, admin_h, order_code, ferment_ids, blend_mode="khong_phoi", lines=None,
                    planned_volume_hl=1000.0, volume_tolerance_hl=0.0, beer_type_id=None,
                    finished_product_id=None):
    payload = {"order_code": order_code, "blend_mode": blend_mode, "tank_ferment_ids": ferment_ids,
               "planned_volume_hl": planned_volume_hl, "volume_tolerance_hl": volume_tolerance_hl}
    if lines is not None:
        payload["lines"] = lines
    if beer_type_id is not None:
        payload["beer_type_id"] = beer_type_id
    if finished_product_id is not None:
        payload["finished_product_id"] = finished_product_id
    return client.post("/api/brewing/filter-orders", headers=admin_h, json=payload)


def _a_material_with_stock(client, admin_h, code, qty_company=0, qty_workshop=0):
    """Tạo 1 vật tư mới + nhập kho (Kho công ty và/hoặc Kho phân xưởng) — trả về material_id."""
    m = client.post("/api/materials", headers=admin_h,
                    json={"code": code, "name": f"Vật tư {code}", "uom": "kg"})
    assert m.status_code == 201, m.text
    material_id = m.json()["material_id"]
    if qty_company:
        r = client.post("/api/warehouse/receive", headers=admin_h,
                        json={"lot_code": f"LOT-{code}-CTY", "material_id": material_id,
                              "quantity": qty_company, "uom": "kg", "location": "Kho công ty"})
        assert r.status_code == 200, r.text
    if qty_workshop:
        r = client.post("/api/warehouse/receive", headers=admin_h,
                        json={"lot_code": f"LOT-{code}-PX", "material_id": material_id,
                              "quantity": qty_workshop, "uom": "kg", "location": "Kho phân xưởng"})
        assert r.status_code == 200, r.text
    return material_id


def test_create_order_khong_phoi_single_tank(client, admin_h, vanhanh_h):
    ferment_id = _setup_ferment(client, admin_h, vanhanh_h, "FO-KP01")
    r = _a_filter_order(client, admin_h, "LOC-KP01", [ferment_id])
    assert r.status_code == 201, r.text
    order_id = r.json()["filter_order_id"]

    detail = client.get(f"/api/brewing/filter-orders/{order_id}", headers=admin_h).json()
    assert detail["blend_mode"] == "khong_phoi"
    assert len(detail["tanks"]) == 1
    assert detail["tanks"][0]["ferment_id"] == ferment_id
    assert detail["is_executed"] is False


def test_create_order_phoi_multi_tank(client, admin_h, vanhanh_h, lager_product_id):
    f1 = _setup_ferment(client, admin_h, vanhanh_h, "FO-PH01A", product_id=lager_product_id)
    f2 = _setup_ferment(client, admin_h, vanhanh_h, "FO-PH01B", product_id=lager_product_id)
    r = _a_filter_order(client, admin_h, "LOC-PH01", [f1, f2], blend_mode="phoi")
    assert r.status_code == 201, r.text
    order_id = r.json()["filter_order_id"]

    detail = client.get(f"/api/brewing/filter-orders/{order_id}", headers=admin_h).json()
    assert detail["blend_mode"] == "phoi"
    assert len(detail["tanks"]) == 2
    assert {t["ferment_id"] for t in detail["tanks"]} == {f1, f2}
    assert [t["seq"] for t in detail["tanks"]] == [1, 2]


def test_finished_product_id_inherited_from_order_to_filter_record(client, admin_h, vanhanh_h):
    """Sản phẩm đích (SKU, tuỳ chọn) khai báo 1 lần ở Lệnh lọc phải kế thừa xuống mẻ lọc
    (FilterRecord) giống cách beer_type_id đang được kế thừa — xem routers/brewing.py::
    add_filter và services/filter_order.py::_insert_sub_order."""
    fp = client.post("/api/finished-products", headers=admin_h,
                     json={"code": "SKU-FO-INHERIT", "name": "Bia tươi test", "uom": "L"})
    assert fp.status_code == 201, fp.text
    fp_id = fp.json()["finished_product_id"]

    ferment_id = _setup_ferment(client, admin_h, vanhanh_h, "FO-FPID01")
    r = _a_filter_order(client, admin_h, "LOC-FPID01", [ferment_id], finished_product_id=fp_id)
    assert r.status_code == 201, r.text
    order_id = r.json()["filter_order_id"]

    detail = client.get(f"/api/brewing/filter-orders/{order_id}", headers=admin_h).json()
    assert detail["finished_product_id"] == fp_id
    assert detail["finished_product_code"] == "SKU-FO-INHERIT"

    f = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": "FL-FPID01", "beer_type": "Bia test",
                          "filter_order_id": order_id, "to_bbt": "BBT-FPID01"})
    assert f.status_code == 201, f.text
    assert f.json()["finished_product_id"] == fp_id

    rows = client.get("/api/brewing/filters", headers=admin_h).json()
    row = next(x for x in rows if x["filter_code"] == "FL-FPID01")
    assert row["finished_product_id"] == fp_id
    assert row["finished_product_code"] == "SKU-FO-INHERIT"


def test_create_order_phoi_requires_at_least_2_tanks(client, admin_h, vanhanh_h):
    ferment_id = _setup_ferment(client, admin_h, vanhanh_h, "FO-BAD01")
    r = _a_filter_order(client, admin_h, "LOC-BAD01", [ferment_id], blend_mode="phoi")
    assert r.status_code == 409, r.text


def test_create_order_khong_phoi_rejects_multi_tank(client, admin_h, vanhanh_h, lager_product_id):
    f1 = _setup_ferment(client, admin_h, vanhanh_h, "FO-BAD02A", product_id=lager_product_id)
    f2 = _setup_ferment(client, admin_h, vanhanh_h, "FO-BAD02B", product_id=lager_product_id)
    r = _a_filter_order(client, admin_h, "LOC-BAD02", [f1, f2], blend_mode="khong_phoi")
    assert r.status_code == 409, r.text


def test_create_order_rejects_unapproved_tank(client, admin_h, vanhanh_h):
    ferment_id = _setup_ferment(client, admin_h, vanhanh_h, "FO-BAD03", approve=False)
    r = _a_filter_order(client, admin_h, "LOC-BAD03", [ferment_id])
    assert r.status_code == 409, r.text


def test_create_order_phoi_across_beer_types_requires_explicit_choice(client, admin_h, vanhanh_h,
                                                                       lager_product_id, other_product_id,
                                                                       other_beer_type_id):
    """Phối 2 tank thuộc 2 Dịch bia KHÁC Loại bia (Lager vs OTHERTYPE) vẫn được phép (khác
    hành vi cũ chặn hẳn 'khác dịch bia') nhưng bắt buộc người lập chọn 1 trong 2 Loại bia
    đó — không chọn thì chặn, chọn thì tạo được và lệnh lưu đúng Loại bia đã chọn."""
    f1 = _setup_ferment(client, admin_h, vanhanh_h, "FO-BAD04A", product_id=lager_product_id)
    f2 = _setup_ferment(client, admin_h, vanhanh_h, "FO-BAD04B", product_id=other_product_id)

    missing_choice = _a_filter_order(client, admin_h, "LOC-BAD04", [f1, f2], blend_mode="phoi")
    assert missing_choice.status_code == 409, missing_choice.text
    assert "chọn 1 Loại bia" in missing_choice.json()["detail"]

    ok = _a_filter_order(client, admin_h, "LOC-BAD04B", [f1, f2], blend_mode="phoi",
                         beer_type_id=other_beer_type_id)
    assert ok.status_code == 201, ok.text
    order_id = ok.json()["filter_order_id"]
    detail = client.get(f"/api/brewing/filter-orders/{order_id}", headers=admin_h).json()
    assert detail["beer_type_id"] == other_beer_type_id
    assert detail["beer_type_code"] == "OTHERTYPE"


def test_add_filter_requires_valid_order(client, admin_h, vanhanh_h):
    missing = client.post("/api/brewing/filters", headers=vanhanh_h,
                          json={"filter_code": "FL-NOORDER", "beer_type": "Bia test"})
    assert missing.status_code == 422, missing.text

    bogus = client.post("/api/brewing/filters", headers=vanhanh_h,
                        json={"filter_code": "FL-BOGUSORDER", "beer_type": "Bia test",
                              "filter_order_id": "does-not-exist"})
    assert bogus.status_code == 404, bogus.text

    ferment_id = _setup_ferment(client, admin_h, vanhanh_h, "FO-EXEC01")
    order_id = _a_filter_order(client, admin_h, "LOC-EXEC01", [ferment_id]).json()["filter_order_id"]
    ok = client.post("/api/brewing/filters", headers=vanhanh_h,
                     json={"filter_code": "FL-EXEC01", "beer_type": "Bia test",
                           "filter_order_id": order_id, "to_bbt": "ANY-TANK-FREE-CHOICE"})
    assert ok.status_code == 201, ok.text

    detail = client.get(f"/api/brewing/filter-orders/{order_id}", headers=admin_h).json()
    assert detail["is_executed"] is True
    assert detail["records"][0]["filter_code"] == "FL-EXEC01"
    assert detail["records"][0]["to_bbt"] == "ANY-TANK-FREE-CHOICE"

    # Lệnh chưa hoàn thành (thể tích kế hoạch mặc định 1000hl, mẻ 1 chưa "Kết thúc" nên
    # v_beer_hl vẫn = 0) -> vẫn thêm được mẻ lọc thứ 2, tank BBT tự do chọn không bị giới hạn.
    again = client.post("/api/brewing/filters", headers=vanhanh_h,
                        json={"filter_code": "FL-EXEC02", "beer_type": "Bia test",
                              "filter_order_id": order_id, "to_bbt": "ANOTHER-TANK"})
    assert again.status_code == 201, again.text


def test_delete_order_blocked_once_executed(client, admin_h, vanhanh_h):
    ferment_id = _setup_ferment(client, admin_h, vanhanh_h, "FO-DEL01")
    order_id = _a_filter_order(client, admin_h, "LOC-DEL01", [ferment_id]).json()["filter_order_id"]
    deletable = client.delete(f"/api/brewing/filter-orders/{order_id}", headers=admin_h)
    assert deletable.status_code == 204, deletable.text

    ferment_id2 = _setup_ferment(client, admin_h, vanhanh_h, "FO-DEL02")
    order_id2 = _a_filter_order(client, admin_h, "LOC-DEL02", [ferment_id2]).json()["filter_order_id"]
    used = client.post("/api/brewing/filters", headers=vanhanh_h,
                       json={"filter_code": "FL-DEL02", "beer_type": "Bia test", "filter_order_id": order_id2,
                             "to_bbt": "BBT-DEL02"})
    assert used.status_code == 201, used.text
    blocked = client.delete(f"/api/brewing/filter-orders/{order_id2}", headers=admin_h)
    assert blocked.status_code == 409, blocked.text


def test_khong_phoi_finish_updates_record_and_deducts_on_hand_cct(client, admin_h, vanhanh_h):
    ferment_id = _setup_ferment(client, admin_h, vanhanh_h, "FO-KPFIN01")
    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment = next(f for f in ferments if f["ferment_id"] == ferment_id)
    cct_before = ferment["on_hand_cct"]

    order_id = _a_filter_order(client, admin_h, "LOC-KPFIN01", [ferment_id]).json()["filter_order_id"]
    f = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": "FL-KPFIN01", "beer_type": "Bia test",
                          "filter_order_id": order_id, "to_bbt": "BBT-KPFIN01"})
    assert f.status_code == 201, f.text
    filter_id = f.json()["filter_id"]
    assert f.json()["ferment_id"] == ferment_id
    assert f.json()["from_cct"] == f"T-FO-KPFIN01"

    tanks = client.get(f"/api/brewing/filters/{filter_id}/tanks", headers=admin_h).json()
    assert len(tanks) == 1
    line_id = tanks[0]["line_id"]

    fin = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line_id}/finish", headers=vanhanh_h,
                      json={"v_dich_hl": 90, "nuoc_bai_khi_hl": 10})
    assert fin.status_code == 200, fin.text
    assert fin.json()["v_dich_hl"] == 90
    assert fin.json()["nuoc_bai_khi_hl"] == 10
    assert fin.json()["v_beer_hl"] == 100
    assert fin.json()["on_hand_bbt"] == 100
    assert fin.json()["ended_at"] is not None

    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment = next(f for f in ferments if f["ferment_id"] == ferment_id)
    assert ferment["on_hand_cct"] == cct_before - 90


def test_phoi_two_tanks_finish_separately_then_aggregate(client, admin_h, vanhanh_h, lager_product_id):
    f1 = _setup_ferment(client, admin_h, vanhanh_h, "FO-PHFIN01A", product_id=lager_product_id)
    f2 = _setup_ferment(client, admin_h, vanhanh_h, "FO-PHFIN01B", product_id=lager_product_id)
    order_id = _a_filter_order(client, admin_h, "LOC-PHFIN01", [f1, f2], blend_mode="phoi").json()["filter_order_id"]

    filt = client.post("/api/brewing/filters", headers=vanhanh_h,
                       json={"filter_code": "FL-PHFIN01", "beer_type": "Bia test",
                             "filter_order_id": order_id, "to_bbt": "BBT-PHFIN01"})
    assert filt.status_code == 201, filt.text
    filter_id = filt.json()["filter_id"]
    assert filt.json()["ferment_id"] is None
    assert filt.json()["v_dich_hl"] == 0

    tanks = client.get(f"/api/brewing/filters/{filter_id}/tanks", headers=admin_h).json()
    assert len(tanks) == 2
    line1 = next(t for t in tanks if t["ferment_id"] == f1)
    line2 = next(t for t in tanks if t["ferment_id"] == f2)

    # Kết thúc tank 1 — bản ghi tổng CHƯA hoàn thành (tank 2 chưa xong), số liệu chỉ phản ánh tank 1.
    fin1 = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line1['line_id']}/finish", headers=vanhanh_h,
                       json={"v_dich_hl": 60, "nuoc_bai_khi_hl": 0})
    assert fin1.status_code == 200, fin1.text
    assert fin1.json()["ended_at"] is None
    assert fin1.json()["v_dich_hl"] == 60
    assert fin1.json()["v_beer_hl"] == 60

    rows = client.get("/api/brewing/filters", headers=admin_h).json()
    row = next(r for r in rows if r["filter_code"] == "FL-PHFIN01")
    assert row["exec_status"] == "dang_thuc_hien"

    # Kết thúc tank 2 — giờ tổng đúng bằng tổng 2 tank, bản ghi hoàn thành.
    fin2 = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line2['line_id']}/finish", headers=vanhanh_h,
                       json={"v_dich_hl": 40, "nuoc_bai_khi_hl": 0})
    assert fin2.status_code == 200, fin2.text
    assert fin2.json()["ended_at"] is not None
    assert fin2.json()["v_dich_hl"] == 100
    assert fin2.json()["v_beer_hl"] == 100
    assert fin2.json()["on_hand_bbt"] == 100

    rows = client.get("/api/brewing/filters", headers=admin_h).json()
    row = next(r for r in rows if r["filter_code"] == "FL-PHFIN01")
    assert row["exec_status"] == "hoan_thanh"

    # Sửa lại số liệu tank 1 (bấm nhầm) — tổng cập nhật đúng theo delta, không cộng dồn sai.
    fixed = client.post(f"/api/brewing/filters/{filter_id}/tanks/{line1['line_id']}/finish", headers=vanhanh_h,
                        json={"v_dich_hl": 50, "nuoc_bai_khi_hl": 0})
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["v_dich_hl"] == 90
    assert fixed.json()["v_beer_hl"] == 90
    assert fixed.json()["on_hand_bbt"] == 90

    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment1 = next(f for f in ferments if f["ferment_id"] == f1)
    ferment2 = next(f for f in ferments if f["ferment_id"] == f2)
    assert ferment1["on_hand_cct"] == 100 - 50
    assert ferment2["on_hand_cct"] == 100 - 40


def test_brew_and_ferment_delete_blocked_for_phoi_sourced_filter(client, admin_h, vanhanh_h, lager_product_id):
    f1 = _setup_ferment(client, admin_h, vanhanh_h, "FO-PHDEL01A", product_id=lager_product_id)
    f2 = _setup_ferment(client, admin_h, vanhanh_h, "FO-PHDEL01B", product_id=lager_product_id)
    order_id = _a_filter_order(client, admin_h, "LOC-PHDEL01", [f1, f2], blend_mode="phoi").json()["filter_order_id"]
    filt = client.post("/api/brewing/filters", headers=vanhanh_h,
                       json={"filter_code": "FL-PHDEL01", "beer_type": "Bia test",
                             "filter_order_id": order_id, "to_bbt": "BBT-PHDEL01"})
    assert filt.status_code == 201, filt.text

    brews = client.get("/api/brewing/brews", headers=admin_h).json()
    brew1 = next(b for b in brews if b["brew_code"] == "BR-FO-PHDEL01A")
    blocked_brew = client.delete(f"/api/brewing/brews/{brew1['brew_id']}", headers=vanhanh_h)
    assert blocked_brew.status_code == 409, blocked_brew.text

    blocked_ferment = client.delete(f"/api/brewing/ferments/{f2}", headers=vanhanh_h)
    assert blocked_ferment.status_code == 409, blocked_ferment.text

    ok = client.delete(f"/api/brewing/filters/{filt.json()['filter_id']}", headers=vanhanh_h)
    assert ok.status_code == 204, ok.text
    allowed_ferment = client.delete(f"/api/brewing/ferments/{f2}", headers=vanhanh_h)
    assert allowed_ferment.status_code == 204, allowed_ferment.text


def test_lo_status_reflects_phoi_filter(client, admin_h, vanhanh_h, lager_product_id):
    f1 = _setup_ferment(client, admin_h, vanhanh_h, "FO-PHLOS01A", product_id=lager_product_id)
    f2 = _setup_ferment(client, admin_h, vanhanh_h, "FO-PHLOS01B", product_id=lager_product_id)
    brews = client.get("/api/brewing/brews", headers=admin_h).json()
    brew1 = next(b for b in brews if b["brew_code"] == "BR-FO-PHLOS01A")
    brew2 = next(b for b in brews if b["brew_code"] == "BR-FO-PHLOS01B")

    def _row(brew_id):
        rows = client.get("/api/reports/lo-status", headers=admin_h).json()
        return next(r for r in rows if r["brew_id"] == brew_id)

    assert _row(brew1["brew_id"])["loc"] == "chua_loc"
    assert _row(brew2["brew_id"])["loc"] == "chua_loc"

    order_id = _a_filter_order(client, admin_h, "LOC-PHLOS01", [f1, f2], blend_mode="phoi").json()["filter_order_id"]
    filt = client.post("/api/brewing/filters", headers=vanhanh_h,
                       json={"filter_code": "FL-PHLOS01", "beer_type": "Bia test",
                             "filter_order_id": order_id, "to_bbt": "BBT-PHLOS01"}).json()
    assert _row(brew1["brew_id"])["loc"] == "dang_loc"
    assert _row(brew2["brew_id"])["loc"] == "dang_loc"

    tanks = client.get(f"/api/brewing/filters/{filt['filter_id']}/tanks", headers=admin_h).json()
    for t in tanks:
        client.post(f"/api/brewing/filters/{filt['filter_id']}/tanks/{t['line_id']}/finish", headers=vanhanh_h,
                   json={"v_dich_hl": 50, "nuoc_bai_khi_hl": 0})
    assert _row(brew1["brew_id"])["loc"] == "da_ket_thuc"
    assert _row(brew2["brew_id"])["loc"] == "da_ket_thuc"


def test_create_order_with_material_line_sufficient_stock(client, admin_h, vanhanh_h):
    ferment_id = _setup_ferment(client, admin_h, vanhanh_h, "FO-MAT01")
    material_id = _a_material_with_stock(client, admin_h, "MAT-FO01", qty_company=20, qty_workshop=10)
    r = _a_filter_order(client, admin_h, "LOC-MAT01", [ferment_id],
                        lines=[{"material_id": material_id, "quantity": 25}])
    assert r.status_code == 201, r.text
    order_id = r.json()["filter_order_id"]

    detail = client.get(f"/api/brewing/filter-orders/{order_id}", headers=admin_h).json()
    assert len(detail["lines"]) == 1
    line = detail["lines"][0]
    assert line["material_id"] == material_id
    assert line["quantity"] == 25
    assert line["stock_company_snapshot"] == 20
    assert line["stock_workshop_snapshot"] == 10


def test_create_order_with_material_line_uses_total_of_both_warehouses(client, admin_h, vanhanh_h):
    """Đủ tồn nếu TỔNG 2 kho đủ, dù từng kho riêng lẻ không đủ."""
    ferment_id = _setup_ferment(client, admin_h, vanhanh_h, "FO-MAT02")
    material_id = _a_material_with_stock(client, admin_h, "MAT-FO02", qty_company=5, qty_workshop=5)
    r = _a_filter_order(client, admin_h, "LOC-MAT02", [ferment_id],
                        lines=[{"material_id": material_id, "quantity": 10}])
    assert r.status_code == 201, r.text


def test_create_order_with_material_line_insufficient_stock_is_blocked(client, admin_h, vanhanh_h):
    ferment_id = _setup_ferment(client, admin_h, vanhanh_h, "FO-MAT03")
    material_id = _a_material_with_stock(client, admin_h, "MAT-FO03", qty_company=5, qty_workshop=5)
    r = _a_filter_order(client, admin_h, "LOC-MAT03", [ferment_id],
                        lines=[{"material_id": material_id, "quantity": 999999}])
    assert r.status_code == 409, r.text

    # Không được để lại lệnh lọc "một nửa" — order_code phải dùng lại được (không unique-conflict).
    retry = _a_filter_order(client, admin_h, "LOC-MAT03", [ferment_id],
                            lines=[{"material_id": material_id, "quantity": 1}])
    assert retry.status_code == 201, retry.text


def test_material_fifo_endpoint_sorted_oldest_first(client, admin_h):
    material_id = _a_material_with_stock(client, admin_h, "MAT-FIFO01", qty_company=3, qty_workshop=7)
    r = client.get(f"/api/warehouse/materials/{material_id}/fifo", headers=admin_h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["stock_company"] == 3
    assert data["stock_workshop"] == 7
    assert data["stock_total"] == 10
    assert len(data["lots"]) == 2
    received = [l["received_at"] for l in data["lots"]]
    assert received == sorted(received)


def test_delete_order_cleans_up_material_lines(client, admin_h, vanhanh_h):
    ferment_id = _setup_ferment(client, admin_h, vanhanh_h, "FO-MAT04")
    material_id = _a_material_with_stock(client, admin_h, "MAT-FO04", qty_company=10)
    order_id = _a_filter_order(client, admin_h, "LOC-MAT04", [ferment_id],
                               lines=[{"material_id": material_id, "quantity": 5}]).json()["filter_order_id"]
    deleted = client.delete(f"/api/brewing/filter-orders/{order_id}", headers=admin_h)
    assert deleted.status_code == 204, deleted.text
    missing = client.get(f"/api/brewing/filter-orders/{order_id}", headers=admin_h)
    assert missing.status_code == 404, missing.text


def test_create_order_without_material_lines_still_works(client, admin_h, vanhanh_h):
    """Không bắt buộc chọn vật tư — tương thích ngược với các lệnh lọc không kèm dòng nào."""
    ferment_id = _setup_ferment(client, admin_h, vanhanh_h, "FO-MAT05")
    r = _a_filter_order(client, admin_h, "LOC-MAT05", [ferment_id])
    assert r.status_code == 201, r.text
    detail = client.get(f"/api/brewing/filter-orders/{r.json()['filter_order_id']}", headers=admin_h).json()
    assert detail["lines"] == []


def _update_filter_order(client, admin_h, order_id, order_code, ferment_ids, blend_mode="khong_phoi", lines=None,
                         planned_volume_hl=1000.0, volume_tolerance_hl=0.0):
    payload = {"order_code": order_code, "blend_mode": blend_mode, "tank_ferment_ids": ferment_ids,
               "planned_volume_hl": planned_volume_hl, "volume_tolerance_hl": volume_tolerance_hl}
    if lines is not None:
        payload["lines"] = lines
    return client.put(f"/api/brewing/filter-orders/{order_id}", headers=admin_h, json=payload)


def test_update_order_can_change_code_tank_and_materials(client, admin_h, vanhanh_h):
    f1 = _setup_ferment(client, admin_h, vanhanh_h, "FO-UPD01A")
    f2 = _setup_ferment(client, admin_h, vanhanh_h, "FO-UPD01B")
    mat1 = _a_material_with_stock(client, admin_h, "MAT-UPD01A", qty_company=50)
    mat2 = _a_material_with_stock(client, admin_h, "MAT-UPD01B", qty_company=30)
    order_id = _a_filter_order(client, admin_h, "LOC-UPD01", [f1],
                               lines=[{"material_id": mat1, "quantity": 10}]).json()["filter_order_id"]

    r = _update_filter_order(client, admin_h, order_id, "LOC-UPD01-EDITED", [f2],
                             lines=[{"material_id": mat2, "quantity": 20}])
    assert r.status_code == 200, r.text

    detail = client.get(f"/api/brewing/filter-orders/{order_id}", headers=admin_h).json()
    assert detail["order_code"] == "LOC-UPD01-EDITED"
    assert [t["ferment_id"] for t in detail["tanks"]] == [f2]
    assert len(detail["lines"]) == 1
    assert detail["lines"][0]["material_id"] == mat2
    assert detail["lines"][0]["quantity"] == 20
    assert detail["lines"][0]["stock_company_snapshot"] == 30


def test_update_order_blocked_once_executed(client, admin_h, vanhanh_h):
    ferment_id = _setup_ferment(client, admin_h, vanhanh_h, "FO-UPD02")
    order_id = _a_filter_order(client, admin_h, "LOC-UPD02", [ferment_id]).json()["filter_order_id"]
    filt = client.post("/api/brewing/filters", headers=vanhanh_h,
                       json={"filter_code": "FL-UPD02", "beer_type": "Bia test", "filter_order_id": order_id,
                             "to_bbt": "BBT-UPD02"})
    assert filt.status_code == 201, filt.text

    r = _update_filter_order(client, admin_h, order_id, "LOC-UPD02-EDITED", [ferment_id])
    assert r.status_code == 409, r.text


def test_update_order_material_shortage_is_blocked_and_keeps_old_data(client, admin_h, vanhanh_h):
    ferment_id = _setup_ferment(client, admin_h, vanhanh_h, "FO-UPD03")
    mat = _a_material_with_stock(client, admin_h, "MAT-UPD03", qty_company=10)
    order_id = _a_filter_order(client, admin_h, "LOC-UPD03", [ferment_id],
                               lines=[{"material_id": mat, "quantity": 5}]).json()["filter_order_id"]

    r = _update_filter_order(client, admin_h, order_id, "LOC-UPD03", [ferment_id],
                             lines=[{"material_id": mat, "quantity": 999999}])
    assert r.status_code == 409, r.text

    detail = client.get(f"/api/brewing/filter-orders/{order_id}", headers=admin_h).json()
    assert len(detail["lines"]) == 1
    assert detail["lines"][0]["quantity"] == 5


def test_update_order_duplicate_code_blocked(client, admin_h, vanhanh_h):
    f1 = _setup_ferment(client, admin_h, vanhanh_h, "FO-UPD04A")
    f2 = _setup_ferment(client, admin_h, vanhanh_h, "FO-UPD04B")
    _a_filter_order(client, admin_h, "LOC-UPD04-TAKEN", [f1])
    order_id = _a_filter_order(client, admin_h, "LOC-UPD04", [f2]).json()["filter_order_id"]

    r = _update_filter_order(client, admin_h, order_id, "LOC-UPD04-TAKEN", [f2])
    assert r.status_code == 409, r.text


def test_update_order_not_found(client, admin_h):
    r = _update_filter_order(client, admin_h, "does-not-exist", "LOC-UPD05", [])
    assert r.status_code == 404, r.text


def test_create_order_requires_positive_planned_volume(client, admin_h, vanhanh_h):
    ferment_id = _setup_ferment(client, admin_h, vanhanh_h, "FO-VOL01")
    zero = _a_filter_order(client, admin_h, "LOC-VOL01", [ferment_id], planned_volume_hl=0)
    assert zero.status_code == 409, zero.text

    ferment_id2 = _setup_ferment(client, admin_h, vanhanh_h, "FO-VOL02")
    negative_tol = _a_filter_order(client, admin_h, "LOC-VOL02", [ferment_id2],
                                   planned_volume_hl=100, volume_tolerance_hl=-1)
    assert negative_tol.status_code == 409, negative_tol.text


def test_update_order_requires_positive_planned_volume(client, admin_h, vanhanh_h):
    ferment_id = _setup_ferment(client, admin_h, vanhanh_h, "FO-VOL03")
    order_id = _a_filter_order(client, admin_h, "LOC-VOL03", [ferment_id]).json()["filter_order_id"]
    r = _update_filter_order(client, admin_h, order_id, "LOC-VOL03", [ferment_id], planned_volume_hl=0)
    assert r.status_code == 409, r.text


def test_order_completes_when_actual_volume_within_tolerance(client, admin_h, vanhanh_h):
    ferment_id = _setup_ferment(client, admin_h, vanhanh_h, "FO-VOL04")
    order_id = _a_filter_order(client, admin_h, "LOC-VOL04", [ferment_id],
                               planned_volume_hl=100, volume_tolerance_hl=5).json()["filter_order_id"]

    f = client.post("/api/brewing/filters", headers=vanhanh_h,
                    json={"filter_code": "FL-VOL04", "beer_type": "Bia test",
                          "filter_order_id": order_id, "to_bbt": "BBT-VOL04"})
    assert f.status_code == 201, f.text
    filter_id = f.json()["filter_id"]

    detail = client.get(f"/api/brewing/filter-orders/{order_id}", headers=admin_h).json()
    assert detail["is_complete"] is False, "chưa Kết thúc, sản lượng vẫn = 0"

    tanks = client.get(f"/api/brewing/filters/{filter_id}/tanks", headers=admin_h).json()
    fin = client.post(f"/api/brewing/filters/{filter_id}/tanks/{tanks[0]['line_id']}/finish",
                      headers=vanhanh_h, json={"v_dich_hl": 91, "nuoc_bai_khi_hl": 5})
    assert fin.status_code == 200, fin.text
    assert fin.json()["v_beer_hl"] == 96

    detail = client.get(f"/api/brewing/filter-orders/{order_id}", headers=admin_h).json()
    assert detail["actual_volume_hl"] == 96
    assert detail["is_complete"] is True

    # Đã hoàn thành -> không tạo thêm mẻ lọc được nữa.
    blocked = client.post("/api/brewing/filters", headers=vanhanh_h,
                          json={"filter_code": "FL-VOL04-2", "beer_type": "Bia test",
                                "filter_order_id": order_id, "to_bbt": "BBT-VOL04-2"})
    assert blocked.status_code == 409, blocked.text


def test_multiple_batches_accumulate_volume_independently(client, admin_h, vanhanh_h):
    """Nhiều mẻ lọc của cùng 1 lệnh cộng dồn v_beer_hl đúng — và mỗi mẻ "Kết thúc" độc lập,
    không double-count vào mẻ kia (đúng bug đã phát hiện khi thiết kế cơ chế nhân bản
    FilterOrderTank theo filter_id)."""
    ferment_id = _setup_ferment(client, admin_h, vanhanh_h, "FO-VOL05")
    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment = next(f for f in ferments if f["ferment_id"] == ferment_id)
    cct_before = ferment["on_hand_cct"]

    order_id = _a_filter_order(client, admin_h, "LOC-VOL05", [ferment_id],
                               planned_volume_hl=100, volume_tolerance_hl=5).json()["filter_order_id"]

    r1 = client.post("/api/brewing/filters", headers=vanhanh_h,
                     json={"filter_code": "FL-VOL05-A", "beer_type": "Bia test",
                           "filter_order_id": order_id, "to_bbt": "BBT-VOL05-A"})
    assert r1.status_code == 201, r1.text
    filter_id_a = r1.json()["filter_id"]
    tanks_a = client.get(f"/api/brewing/filters/{filter_id_a}/tanks", headers=admin_h).json()
    fin_a = client.post(f"/api/brewing/filters/{filter_id_a}/tanks/{tanks_a[0]['line_id']}/finish",
                        headers=vanhanh_h, json={"v_dich_hl": 35, "nuoc_bai_khi_hl": 5})
    assert fin_a.status_code == 200, fin_a.text
    assert fin_a.json()["v_beer_hl"] == 40

    detail = client.get(f"/api/brewing/filter-orders/{order_id}", headers=admin_h).json()
    assert detail["actual_volume_hl"] == 40
    assert detail["is_complete"] is False, "40hl còn cách xa 100hl kế hoạch -> chưa hoàn thành"

    # Chưa hoàn thành -> vẫn thêm được mẻ lọc thứ 2 (tank BBT khác, tự do chọn).
    r2 = client.post("/api/brewing/filters", headers=vanhanh_h,
                     json={"filter_code": "FL-VOL05-B", "beer_type": "Bia test",
                           "filter_order_id": order_id, "to_bbt": "BBT-VOL05-B"})
    assert r2.status_code == 201, r2.text
    filter_id_b = r2.json()["filter_id"]
    assert filter_id_b != filter_id_a

    tanks_b = client.get(f"/api/brewing/filters/{filter_id_b}/tanks", headers=admin_h).json()
    assert tanks_a[0]["line_id"] != tanks_b[0]["line_id"], "mỗi mẻ lọc phải có dòng Kết thúc riêng"
    fin_b = client.post(f"/api/brewing/filters/{filter_id_b}/tanks/{tanks_b[0]['line_id']}/finish",
                        headers=vanhanh_h, json={"v_dich_hl": 50, "nuoc_bai_khi_hl": 5})
    assert fin_b.status_code == 200, fin_b.text
    assert fin_b.json()["v_beer_hl"] == 55, "mẻ B độc lập, không cộng nhầm số của mẻ A"

    detail = client.get(f"/api/brewing/filter-orders/{order_id}", headers=admin_h).json()
    assert detail["actual_volume_hl"] == 95, "40 + 55 = 95, cộng dồn đúng qua 2 mẻ lọc"
    assert detail["is_complete"] is True, "|95-100| = 5 <= sai số 5 -> hoàn thành"
    assert len(detail["records"]) == 2

    ferments = client.get("/api/brewing/ferments", headers=admin_h).json()["items"]
    ferment = next(f for f in ferments if f["ferment_id"] == ferment_id)
    assert ferment["on_hand_cct"] == cct_before - 35 - 50, "trừ đúng tổng cả 2 mẻ, không double-count"

    # Đã hoàn thành -> không tạo thêm được mẻ lọc thứ 3.
    blocked = client.post("/api/brewing/filters", headers=vanhanh_h,
                          json={"filter_code": "FL-VOL05-C", "beer_type": "Bia test",
                                "filter_order_id": order_id, "to_bbt": "BBT-VOL05-C"})
    assert blocked.status_code == 409, blocked.text
