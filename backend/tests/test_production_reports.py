"""Test 3 báo cáo Nhóm A (port từ phần mềm QLSX cũ dma.biahalong.com:88 › Báo cáo sản xuất,
yêu cầu người dùng 2026-11-05) trong services/production_reports.py:
- pack_output_by_category: BC sản lượng chiết theo tháng (theo Loại bia + hiệu suất thu hồi%)
- pack_output_cumulative: BC sản lượng chiết lũy kế (ngày/tuần/tháng/năm song song, theo SKU)
- brew_volume_by_product: BC sản lượng nấu theo tháng (theo Dịch bia)

Dùng năm 2031 (tương lai xa) cho mọi fixture để không đụng dữ liệu seed/test khác chạy ở "hiện
tại" thật của môi trường test.
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


def _build_batch_to_pack(client, admin_h, suffix, start_at_iso, dich_nha_hl, pack_qty,
                         finished_product_id=None, pack_date_iso=None, category="Bia lon"):
    """Dựng 1 chuỗi: mẻ nấu -> gộp tank -> lô lọc -> tách lô thành phẩm — mirror
    test_packaging_lot_report.py::_make_pack_lot, thêm tham số start_at/pack_date/
    finished_product_id để kiểm soát được MỐC THỜI GIAN (báo cáo đang test lọc theo kỳ)."""
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(x for x in vers if x["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                          "planned_qty": dich_nha_hl * 100, "allow_shortage": True})
    assert b.status_code == 201, b.text
    batch_id = b.json()["batch_id"]
    st = client.post(f"/api/batches/{batch_id}/start", headers=admin_h, json={"start_at": start_at_iso})
    assert st.status_code == 200, st.text
    for target in ("ready", "running"):
        r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": target})
        assert r.status_code == 200, r.text
    aq = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h,
                     json={"actual_qty": dich_nha_hl * 100})
    assert aq.status_code == 200, aq.text
    fin = client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={})
    assert fin.status_code == 200, fin.text
    r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "completed"})
    assert r.status_code == 200, r.text
    t = client.post("/api/batch-tanks", headers=admin_h,
                    json={"batch_ids": [batch_id], "tank_code": f"TANK-{suffix}"})
    assert t.status_code == 201, t.text
    tank_id = t.json()["tank_id"]
    bbt = client.post("/api/lines", headers=admin_h,
                      json={"code": f"BBT-{suffix}", "name": f"Tank thành phẩm {suffix}", "kind": "tank_bbt"})
    assert bbt.status_code == 201, bbt.text
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": f"FLOT-{suffix}", "to_bbt": bbt.json()["code"],
        "sources": [{"source_type": "tank", "source_tank_id": tank_id}],
        "category": category,
    })
    assert draw.status_code == 201, draw.text
    filter_lot_id = draw.json()["filter_lot_id"]
    src = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()[0]
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    finfl = client.put(f"/api/batch-filter-lots/batches/{batches[0]['batch_link_id']}/finish", headers=admin_h,
                       json={"draws": [{"source_link_id": src["link_id"], "dich_nha_hl": dich_nha_hl}],
                            "nuoc_bai_khi_hl": 0})
    assert finfl.status_code == 200, finfl.text
    pack_payload = {"qty": pack_qty, "pack_lot_code": f"PKG-{suffix}", "lot_no": f"LOT-{suffix}"}
    if finished_product_id:
        pack_payload["finished_product_id"] = finished_product_id
    if pack_date_iso:
        pack_payload["pack_date"] = pack_date_iso
    pack = client.post(f"/api/batch-filter-lots/{filter_lot_id}/pack-lots", headers=admin_h, json=pack_payload)
    assert pack.status_code == 201, pack.text
    return {"batch_id": batch_id, "filter_lot_id": filter_lot_id,
            "pack_lot_id": pack.json()["pack_lot_id"], "pack_lot_code": pack.json()["pack_lot_code"]}


def test_pack_output_by_category_full_drain_matches_lifecycle_volume(client, admin_h):
    """volume_hl (= v_dich_hl + nuoc_bai_khi_hl) của CẢ lô lọc phải khớp 1:1 với tổng output khi
    lô được rút hết trong 1 lượt — xác nhận lại bug đã fix (input phải dùng volume_hl, KHÔNG phải
    v_dich_hl riêng) không bị regress."""
    _build_batch_to_pack(client, admin_h, "RPTCAT01", "2031-06-01T08:00:00+00:00",
                         dich_nha_hl=21, pack_qty=2100, category="Bia lon test cat",
                         pack_date_iso="2031-06-15T10:00:00+00:00")
    rpt = client.get("/api/reports/pack-output-by-category", headers=admin_h,
                     params={"year": 2031, "month": 6}).json()
    row = next(i for i in rpt["items"] if i["category"] == "Bia lon test cat")
    assert row["filter_batch_count"] == 1
    assert row["input_hl"] == 21
    assert row["output_l"] == 2100
    assert row["yield_pct"] == 100.0


def test_pack_output_by_category_partial_drain_excluded_until_fully_packed(client, admin_h):
    """Lô lọc CHƯA rút hết (on_hand > 0) không được tính vào báo cáo tháng nào — tránh gán input
    cả lô vào tháng mới có 1 phần output (bug round 1 đã fix)."""
    built = _build_batch_to_pack(client, admin_h, "RPTCAT02", "2031-06-02T08:00:00+00:00",
                                 dich_nha_hl=30, pack_qty=1000, category="Bia lon test cat partial",
                                 pack_date_iso="2031-06-16T10:00:00+00:00")
    rpt = client.get("/api/reports/pack-output-by-category", headers=admin_h,
                     params={"year": 2031, "month": 6}).json()
    cats = {i["category"] for i in rpt["items"]}
    assert "Bia lon test cat partial" not in cats

    fl = client.get(f"/api/batch-filter-lots/{built['filter_lot_id']}", headers=admin_h).json()
    assert fl["on_hand"] > 0  # còn dở, đúng như kỳ vọng — chưa "chiết xong"


def test_pack_output_cumulative_day_week_month_year_windows(client, admin_h):
    fp = client.post("/api/finished-products", headers=admin_h,
                     json={"code": "RPTFP01", "name": "SP test báo cáo lũy kế", "uom": "L",
                           "unit_type": "vi", "pack_size": 24, "unit_volume_l": 0.33})
    assert fp.status_code == 201, fp.text
    fp_id = fp.json()["finished_product_id"]

    # Lô 1: trong ngày as_of (2031-06-23) — phải vào CẢ 4 cửa sổ (ngày/tuần/tháng/năm).
    _build_batch_to_pack(client, admin_h, "RPTCUM01", "2031-06-03T08:00:00+00:00",
                         dich_nha_hl=2, pack_qty=20, finished_product_id=fp_id,
                         pack_date_iso="2031-06-23T14:40:00+00:00")
    # Lô 2: cùng tháng/năm nhưng khác tuần (cách 13 ngày, chắc chắn khác tuần ISO) — chỉ vào
    # tháng/năm, KHÔNG vào ngày/tuần của as_of.
    _build_batch_to_pack(client, admin_h, "RPTCUM02", "2031-06-04T08:00:00+00:00",
                         dich_nha_hl=100, pack_qty=1000, finished_product_id=fp_id,
                         pack_date_iso="2031-06-10T09:00:00+00:00")

    rpt = client.get("/api/reports/pack-output-cumulative", headers=admin_h,
                     params={"as_of": "2031-06-23"}).json()
    row = next(i for i in rpt["items"] if i["finished_product_code"] == "RPTFP01")
    assert row["day"]["l"] == 20
    assert row["week"]["l"] == 20
    assert row["month"]["l"] == 1020
    assert row["year"]["l"] == 1020
    # case = lít / (pack_size * unit_volume_l) = 20 / (24*0.33) = 20/7.92 ≈ 3 (làm tròn)
    assert row["day"]["case"] == round(20 / (24 * 0.33))


def test_pack_output_cumulative_excludes_future_dates_after_as_of(client, admin_h):
    fp = client.post("/api/finished-products", headers=admin_h,
                     json={"code": "RPTFP02", "name": "SP test tương lai", "uom": "L",
                           "unit_type": "vi", "pack_size": 24})
    assert fp.status_code == 201, fp.text
    fp_id = fp.json()["finished_product_id"]
    _build_batch_to_pack(client, admin_h, "RPTCUM03", "2031-06-05T08:00:00+00:00",
                         dich_nha_hl=5, pack_qty=500, finished_product_id=fp_id,
                         pack_date_iso="2031-06-30T10:00:00+00:00")
    rpt = client.get("/api/reports/pack-output-cumulative", headers=admin_h,
                     params={"as_of": "2031-06-23"}).json()
    codes = {i["finished_product_code"] for i in rpt["items"]}
    assert "RPTFP02" not in codes  # pack_date (30/6) SAU as_of (23/6) — chưa xảy ra tại mốc xem


def test_brew_volume_by_product_groups_and_subtotals(client, admin_h):
    built1 = _build_batch_to_pack(client, admin_h, "RPTBV01", "2031-06-06T08:00:00+00:00",
                                  dich_nha_hl=10, pack_qty=1000, category="Bia lon test bv")
    built2 = _build_batch_to_pack(client, admin_h, "RPTBV02", "2031-06-07T08:00:00+00:00",
                                  dich_nha_hl=15, pack_qty=1500, category="Bia lon test bv")

    rpt = client.get("/api/reports/brew-volume-by-product", headers=admin_h,
                     params={"year": 2031, "month": 6}).json()
    batch_ids_in_report = set()
    for row in rpt["items"]:
        if row.get("v_dich") in (1000, 1500):
            batch_ids_in_report.add(row["v_dich"])
    assert {1000, 1500} <= batch_ids_in_report

    # Cả 2 mẻ dùng chung 1 recipe/product (seed) — phải gộp subtotal theo đúng product đó.
    product_names = {s["product_name"] for s in rpt["subtotals"]}
    assert len(product_names) >= 1
    matching = [s for s in rpt["subtotals"] if s["batch_count"] >= 2]
    assert matching, rpt["subtotals"]
    total_v_dich_for_product = next(s["v_dich"] for s in matching)
    assert total_v_dich_for_product >= 1000 + 1500 - 1e-6


def test_pack_output_by_category_group_by_sku_allocates_input_proportionally(client, admin_h):
    """yêu cầu người dùng 2026-11-05 "báo cáo theo từng SKU" — group_by="sku" phải tách output
    theo SKU và PHÂN BỔ input_hl của lô lọc theo tỷ trọng output lít giữa các SKU (không có input
    riêng từng SKU ở nguồn), tổng lại đúng bằng input_hl thật của lô lọc."""
    fp_a = client.post("/api/finished-products", headers=admin_h,
                       json={"code": "RPTSKU-A", "name": "SKU A test", "uom": "L",
                             "unit_type": "vi", "pack_size": 24, "unit_volume_l": 0.33})
    assert fp_a.status_code == 201, fp_a.text
    fp_a_id = fp_a.json()["finished_product_id"]
    fp_b = client.post("/api/finished-products", headers=admin_h,
                       json={"code": "RPTSKU-B", "name": "SKU B test", "uom": "L",
                             "unit_type": "vi", "pack_size": 20, "unit_volume_l": 0.5})
    assert fp_b.status_code == 201, fp_b.text
    fp_b_id = fp_b.json()["finished_product_id"]

    # 1 lô lọc volume_hl=20 (= 2000 lít) tách ra 2 SKU: A=1500l (75%), B=500l (25%).
    built = _build_batch_to_pack(client, admin_h, "RPTSKU01", "2031-06-09T08:00:00+00:00",
                                 dich_nha_hl=20, pack_qty=1500, finished_product_id=fp_a_id,
                                 pack_date_iso="2031-06-20T10:00:00+00:00",
                                 category="Bia lon test sku")
    pack2 = client.post(f"/api/batch-filter-lots/{built['filter_lot_id']}/pack-lots", headers=admin_h,
                        json={"qty": 500, "pack_lot_code": "PKG-RPTSKU01-B", "lot_no": "LOT-RPTSKU01-B",
                             "finished_product_id": fp_b_id, "pack_date": "2031-06-21T10:00:00+00:00"})
    assert pack2.status_code == 201, pack2.text

    rpt = client.get("/api/reports/pack-output-by-category", headers=admin_h,
                     params={"year": 2031, "month": 6, "group_by": "sku"}).json()
    assert rpt["group_by"] == "sku"
    row_a = next(i for i in rpt["items"] if i["finished_product_code"] == "RPTSKU-A")
    row_b = next(i for i in rpt["items"] if i["finished_product_code"] == "RPTSKU-B")
    assert row_a["output_l"] == 1500
    assert row_b["output_l"] == 500
    assert row_a["input_hl"] == 15.0   # 20 hl * 75%
    assert row_b["input_hl"] == 5.0    # 20 hl * 25%
    assert row_a["yield_pct"] == 100.0
    assert row_b["yield_pct"] == 100.0
    assert row_a["filter_batch_count"] == 1
    assert row_b["filter_batch_count"] == 1
    # Tổng input_hl giữa các SKU phải khớp đúng tổng theo category (không mất/đếm trùng input).
    assert round(row_a["input_hl"] + row_b["input_hl"], 2) == 20.0


def test_pack_output_by_category_invalid_group_by_rejected(client, admin_h):
    r = client.get("/api/reports/pack-output-by-category", headers=admin_h,
                   params={"year": 2031, "month": 6, "group_by": "nonsense"})
    assert r.status_code == 409, r.text
