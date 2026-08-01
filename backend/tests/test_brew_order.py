"""Test Lệnh nấu (Brew Production Order) — mẫu giấy "LỆNH NẤU BIA KIÊM PHIẾU XUẤT KHO",
chỉ giữ phần LỆNH:
1) Tạo lệnh tự nạp Định mức từ Công thức (BOM) hiệu lực, scale đúng theo số mẻ kế hoạch;
   snapshot tồn kho công ty/phân xưởng lúc lập phiếu.
2) Tạo lệnh với dòng NVL nhập tay (kể cả dòng header, dòng không có material_id).
3) add_brew bắt buộc brew_order_id hợp lệ — 1 lệnh có thể có NHIỀU mã nấu (nhiều tank lên
   men), sản lượng thực tế (volume_hl) cộng dồn tới khi lệch trong khoảng ±sai số so với kế
   hoạch (planned_volume_hl) thì lệnh hoàn thành, không cho thêm mã nấu mới (mirror Lệnh lọc).
4) Xóa lệnh bị chặn khi đã thực hiện (có ít nhất 1 mã nấu, bất kể đã hoàn thành hay chưa).
5) get_order tính đúng cờ "shortage" (thiếu tồn) theo snapshot đã lưu."""

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


def _a_brew_order(client, admin_h, order_code, product_id=None, planned_batch_count=1,
                  planned_volume_hl=100.0, volume_tolerance_hl=0.0,
                  auto_from_bom=False, lines=None):
    r = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": order_code, "product_id": product_id,
        "planned_batch_count": planned_batch_count,
        "planned_volume_hl": planned_volume_hl, "volume_tolerance_hl": volume_tolerance_hl,
        "auto_from_bom": auto_from_bom, "lines": lines or [],
    })
    assert r.status_code == 201, r.text
    return r.json()["brew_order_id"]


def _set_real_actual_volume(client, admin_h, brew_id, batch_code, volume_hl, line_id, finish=True):
    """Sản lượng nấu THỰC TẾ (dùng để tính actual_volume_hl/is_complete của Lệnh nấu) lấy từ
    "Tổng lượng dịch (hl)" khai báo trong Ghi chép nấu của MẺ, không phải volume_hl nhập tay
    lúc tạo mã nấu — mirror đúng cách vận hành thật (xem services/brew_order.py::
    _real_actual_by_brew). Lệnh chỉ "hoàn thành" khi mẻ cũng đã bấm "Kết thúc" (xem
    services/brew_order.py::_all_batches_finished) — mặc định finish=True để mirror vận
    hành thật; truyền finish=False để test riêng nhánh "còn mẻ dở dang"."""
    b = client.post(f"/api/brewing/brews/{brew_id}/batches", headers=admin_h,
                    json={"batch_code": batch_code, "line_id": line_id})
    assert b.status_code == 201, b.text
    batch_id = b.json()["batch_id"]
    p = client.put(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/process-log", headers=admin_h,
                   json={"whp_tong_luong_dich_hl": volume_hl})
    assert p.status_code == 200, p.text
    if finish:
        f = client.post(f"/api/brewing/brews/{brew_id}/batches/{batch_id}/finish", headers=admin_h)
        assert f.status_code == 200, f.text
    return batch_id


def test_create_order_auto_from_bom(client, admin_h, lager_product_id):
    order_id = _a_brew_order(client, admin_h, "LN-BOM01", product_id=lager_product_id,
                             planned_batch_count=12, planned_volume_hl=1776, auto_from_bom=True)
    detail = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    assert detail["planned_batch_count"] == 12
    lines = {l["material_name"]: l for l in detail["lines"] if not l["is_header"]}
    assert set(lines.keys()) >= {"Malt Pilsner", "Hoa bia Saaz", "Men Lager W-34/70"}

    malt = lines["Malt Pilsner"]
    # Công thức khai báo NVL cho ĐÚNG 1 mẻ (1200 kg) — planned_volume_hl không scale nữa,
    # chỉ planned_batch_count nhân trực tiếp vào tổng nhu cầu.
    assert malt["qty_per_batch"] == pytest.approx(1200)
    assert malt["qty_total"] == pytest.approx(1200 * 12)
    # Snapshot tồn phải được ghi lại (không None) vì Malt Pilsner có material_id thật.
    assert malt["stock_company_snapshot"] is not None or malt["stock_workshop_snapshot"] is not None


def test_bom_preview_matches_created_order_without_creating_it(client, admin_h, lager_product_id):
    """Xem trước NVL (nút "Xem NVL") phải cho đúng số liệu như lúc tạo lệnh thật — nhưng
    KHÔNG tạo ra lệnh nào (chỉ để kiểm tra đủ/thiếu tồn trước khi bấm Tạo lệnh nấu)."""
    before = client.get("/api/brewing/orders", headers=admin_h).json()
    preview = client.get("/api/brewing/orders/bom-preview", headers=admin_h,
                        params={"product_id": lager_product_id, "planned_batch_count": 12,
                               "planned_volume_hl": 1776})
    assert preview.status_code == 200, preview.text
    lines = {l["material_name"]: l for l in preview.json() if not l["is_header"]}
    assert set(lines.keys()) >= {"Malt Pilsner", "Hoa bia Saaz", "Men Lager W-34/70"}

    malt = lines["Malt Pilsner"]
    assert malt["qty_per_batch"] == pytest.approx(1200)
    assert malt["qty_total"] == pytest.approx(1200 * 12)
    assert malt["material_id"]
    assert isinstance(malt["shortage"], bool)
    assert malt["stock_company_snapshot"] is not None or malt["stock_workshop_snapshot"] is not None

    after = client.get("/api/brewing/orders", headers=admin_h).json()
    assert len(after) == len(before), "Xem trước không được tạo ra lệnh nấu nào"


def test_bom_preview_flags_shortage_for_huge_batch(client, admin_h, lager_product_id):
    """planned_volume_hl không còn ảnh hưởng nhu cầu NVL — số mẻ kế hoạch cực lớn mới
    khiến tổng nhu cầu vượt tồn kho (Nhu cầu Tổng mẻ = Nhu cầu 1 mẻ x Số mẻ kế hoạch)."""
    preview = client.get("/api/brewing/orders/bom-preview", headers=admin_h,
                        params={"product_id": lager_product_id, "planned_batch_count": 999999,
                               "planned_volume_hl": 100})
    assert preview.status_code == 200, preview.text
    lines = [l for l in preview.json() if not l["is_header"]]
    assert any(l["shortage"] for l in lines), "Số mẻ kế hoạch cực lớn phải bị đánh dấu thiếu tồn"


def test_create_order_manual_lines(client, admin_h):
    order_id = _a_brew_order(client, admin_h, "LN-MANUAL01", auto_from_bom=False, lines=[
        {"stt_label": "A", "is_header": True, "material_name": "Nguyên liệu chính"},
        {"stt_label": "1", "material_name": "Đường Việt Nam", "uom": "Kg",
         "qty_per_batch": 0, "qty_total": 0},
    ])
    detail = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    assert len(detail["lines"]) == 2
    assert detail["lines"][0]["is_header"] is True
    assert detail["lines"][1]["material_name"] == "Đường Việt Nam"
    assert detail["lines"][1]["material_id"] is None


def test_add_brew_requires_valid_order(client, admin_h, vanhanh_h, lager_product_id):
    missing = client.post("/api/brewing/brews", headers=vanhanh_h,
                          json={"brew_code": "BR-NOORDER", "wort_type": "Dịch test"})
    assert missing.status_code == 422, missing.text

    bogus = client.post("/api/brewing/brews", headers=vanhanh_h,
                        json={"brew_code": "BR-BOGUSORDER", "wort_type": "Dịch test",
                              "brew_order_id": "does-not-exist"})
    assert bogus.status_code == 404, bogus.text

    order_id = _a_brew_order(client, admin_h, "LN-EXEC01", product_id=lager_product_id,
                             planned_batch_count=1)
    ok = client.post("/api/brewing/brews", headers=vanhanh_h,
                     json={"brew_code": "BR-EXEC01", "wort_type": "Dịch test",
                           "product_id": lager_product_id, "brew_order_id": order_id})
    assert ok.status_code == 201, ok.text

    detail = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    assert detail["is_executed"] is True
    assert detail["records"][0]["brew_code"] == "BR-EXEC01"

    # Lệnh chưa hoàn thành (kế hoạch 100hl, mẻ 1 chưa khai volume_hl nên thực tế vẫn = 0)
    # -> vẫn thêm được mã nấu thứ 2 (tank lên men khác, tự do chọn) — mirror Lệnh lọc.
    again = client.post("/api/brewing/brews", headers=vanhanh_h,
                        json={"brew_code": "BR-EXEC02", "wort_type": "Dịch test",
                              "brew_order_id": order_id})
    assert again.status_code == 201, again.text


def test_create_order_requires_positive_planned_volume(client, admin_h):
    zero = client.post("/api/brewing/orders", headers=admin_h,
                       json={"order_code": "LN-VOL01", "auto_from_bom": False, "planned_volume_hl": 0})
    assert zero.status_code == 409, zero.text

    negative_tol = client.post("/api/brewing/orders", headers=admin_h,
                               json={"order_code": "LN-VOL02", "auto_from_bom": False,
                                     "planned_volume_hl": 100, "volume_tolerance_hl": -1})
    assert negative_tol.status_code == 409, negative_tol.text


def test_order_completes_when_actual_volume_within_tolerance(client, admin_h, vanhanh_h, brewhouse_line_id):
    order_id = _a_brew_order(client, admin_h, "LN-VOL03", planned_volume_hl=100, volume_tolerance_hl=5)

    b1 = client.post("/api/brewing/brews", headers=vanhanh_h,
                     json={"brew_code": "BR-VOL03-A", "wort_type": "Dịch test", "volume_hl": 96,
                           "brew_order_id": order_id})
    assert b1.status_code == 201, b1.text
    _set_real_actual_volume(client, admin_h, b1.json()["brew_id"], "550", 96, brewhouse_line_id)

    detail = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    assert detail["actual_volume_hl"] == 96
    assert detail["is_complete"] is True

    # Đã hoàn thành -> không tạo thêm mã nấu được nữa.
    blocked = client.post("/api/brewing/brews", headers=vanhanh_h,
                          json={"brew_code": "BR-VOL03-B", "wort_type": "Dịch test",
                                "brew_order_id": order_id})
    assert blocked.status_code == 409, blocked.text


def test_multiple_brews_accumulate_volume_independently(client, admin_h, vanhanh_h, brewhouse_line_id):
    order_id = _a_brew_order(client, admin_h, "LN-VOL04", planned_volume_hl=100, volume_tolerance_hl=5)

    b1 = client.post("/api/brewing/brews", headers=vanhanh_h,
                     json={"brew_code": "BR-VOL04-A", "wort_type": "Dịch test", "volume_hl": 40,
                           "brew_order_id": order_id})
    assert b1.status_code == 201, b1.text
    _set_real_actual_volume(client, admin_h, b1.json()["brew_id"], "551", 40, brewhouse_line_id)

    detail = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    assert detail["actual_volume_hl"] == 40
    assert detail["is_complete"] is False, "40hl còn cách xa 100hl kế hoạch -> chưa hoàn thành"

    b2 = client.post("/api/brewing/brews", headers=vanhanh_h,
                     json={"brew_code": "BR-VOL04-B", "wort_type": "Dịch test", "volume_hl": 55,
                           "brew_order_id": order_id})
    assert b2.status_code == 201, b2.text
    _set_real_actual_volume(client, admin_h, b2.json()["brew_id"], "552", 55, brewhouse_line_id)

    detail2 = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    assert detail2["actual_volume_hl"] == 95
    assert detail2["is_complete"] is True


def test_order_not_complete_while_any_batch_unfinished(client, admin_h, vanhanh_h, brewhouse_line_id):
    """Sản lượng đã khớp kế hoạch (±sai số) KHÔNG đủ để lệnh hoàn thành — còn mẻ nào chưa
    bấm "Kết thúc" thì lệnh vẫn coi như đang thực hiện; chỉ hoàn thành khi TẤT CẢ mẻ của
    TẤT CẢ mã nấu thuộc lệnh đã kết thúc."""
    order_id = _a_brew_order(client, admin_h, "LN-VOL05", planned_volume_hl=100, volume_tolerance_hl=5)

    b1 = client.post("/api/brewing/brews", headers=vanhanh_h,
                     json={"brew_code": "BR-VOL05-A", "wort_type": "Dịch test", "volume_hl": 98,
                           "brew_order_id": order_id})
    assert b1.status_code == 201, b1.text
    batch_id = _set_real_actual_volume(client, admin_h, b1.json()["brew_id"], "553", 98, brewhouse_line_id, finish=False)

    detail = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    assert detail["actual_volume_hl"] == 98
    assert detail["is_complete"] is False, "sản lượng khớp nhưng mẻ chưa Kết thúc -> chưa hoàn thành"

    # Chưa hoàn thành -> vẫn thêm được mã nấu khác bình thường.
    still_open = client.post("/api/brewing/brews", headers=vanhanh_h,
                             json={"brew_code": "BR-VOL05-B", "wort_type": "Dịch test",
                                   "brew_order_id": order_id})
    assert still_open.status_code == 201, still_open.text

    finish = client.post(f"/api/brewing/brews/{b1.json()['brew_id']}/batches/{batch_id}/finish", headers=admin_h)
    assert finish.status_code == 200, finish.text

    detail2 = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    assert detail2["is_complete"] is True, "đủ sản lượng VÀ tất cả mẻ đã kết thúc -> hoàn thành"


def test_order_completes_when_actual_volume_exceeds_plan(client, admin_h, vanhanh_h, brewhouse_line_id):
    """Vượt kế hoạch (dù vượt xa hơn sai số cho phép) vẫn phải coi là hoàn thành — chỉ chặn
    hoàn thành khi HỤT quá sai số, không còn chặn khi VƯỢT (một chiều, khác hành vi cũ
    ±sai số 2 chiều)."""
    order_id = _a_brew_order(client, admin_h, "LN-VOL06", planned_volume_hl=50, volume_tolerance_hl=5)

    b1 = client.post("/api/brewing/brews", headers=vanhanh_h,
                     json={"brew_code": "BR-VOL06-A", "wort_type": "Dịch test", "volume_hl": 200,
                           "brew_order_id": order_id})
    assert b1.status_code == 201, b1.text
    _set_real_actual_volume(client, admin_h, b1.json()["brew_id"], "554", 200, brewhouse_line_id)

    detail = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    assert detail["actual_volume_hl"] == 200
    assert detail["is_complete"] is True, "200hl vượt xa 50hl kế hoạch nhưng vẫn phải hoàn thành"


def test_order_not_complete_when_shortfall_exceeds_tolerance(client, admin_h, vanhanh_h, brewhouse_line_id):
    """Hụt quá sai số cho phép (dưới kế hoạch - sai số) vẫn phải chặn hoàn thành như cũ."""
    order_id = _a_brew_order(client, admin_h, "LN-VOL07", planned_volume_hl=50, volume_tolerance_hl=5)

    b1 = client.post("/api/brewing/brews", headers=vanhanh_h,
                     json={"brew_code": "BR-VOL07-A", "wort_type": "Dịch test", "volume_hl": 40,
                           "brew_order_id": order_id})
    assert b1.status_code == 201, b1.text
    _set_real_actual_volume(client, admin_h, b1.json()["brew_id"], "555", 40, brewhouse_line_id)

    detail = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    assert detail["actual_volume_hl"] == 40
    assert detail["is_complete"] is False, "40hl hụt hơn 5hl sai số so với 50hl kế hoạch -> chưa hoàn thành"


def test_order_shows_actual_tank_and_batch_range(client, admin_h, vanhanh_h, brewhouse_line_id):
    """Danh sách Lệnh nấu phải hiện tank lên men + khoảng số mẻ THỰC TẾ đã nấu (suy ra từ
    lô lên men liên kết + các mẻ đã tạo), không phải tank_lm/batch_range nhập tay lúc lập
    lệnh (thường bỏ trống vì chỉ là dự kiến)."""
    order_id = _a_brew_order(client, admin_h, "LN-TANKRANGE01", planned_volume_hl=200, volume_tolerance_hl=50)

    empty = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    assert empty["actual_tank_lm"] is None
    assert empty["actual_batch_range"] is None

    b1 = client.post("/api/brewing/brews", headers=vanhanh_h,
                     json={"brew_code": "BR-TANKRANGE-A", "wort_type": "Dịch test", "volume_hl": 100,
                           "lm_code": "LM-TANKRANGE-A", "tank_lm": "FV-TR-01", "brew_order_id": order_id})
    assert b1.status_code == 201, b1.text
    batch_a1 = client.post(f"/api/brewing/brews/{b1.json()['brew_id']}/batches", headers=admin_h,
                           json={"batch_code": "201", "line_id": brewhouse_line_id})
    assert batch_a1.status_code == 201, batch_a1.text

    b2 = client.post("/api/brewing/brews", headers=vanhanh_h,
                     json={"brew_code": "BR-TANKRANGE-B", "wort_type": "Dịch test", "volume_hl": 100,
                           "lm_code": "LM-TANKRANGE-B", "tank_lm": "FV-TR-02", "brew_order_id": order_id})
    assert b2.status_code == 201, b2.text
    batch_b1 = client.post(f"/api/brewing/brews/{b2.json()['brew_id']}/batches", headers=admin_h,
                           json={"batch_code": "202", "line_id": brewhouse_line_id})
    assert batch_b1.status_code == 201, batch_b1.text

    detail = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    assert detail["actual_tank_lm"] == "FV-TR-01, FV-TR-02"
    assert detail["actual_batch_range"] == "201-202"

    listing = client.get("/api/brewing/orders", headers=admin_h).json()
    row = next(o for o in listing if o["brew_order_id"] == order_id)
    assert row["actual_tank_lm"] == "FV-TR-01, FV-TR-02"
    assert row["actual_batch_range"] == "201-202"


def test_add_brew_derives_product_id_from_order(client, admin_h, vanhanh_h, lager_product_id):
    """Dịch bia phải trích từ Lệnh nấu (nguồn xác thực duy nhất) — nếu client gửi kèm một
    product_id khác, server phải ghi đè lại theo đúng order.product_id, không cho lệch."""
    other = client.post("/api/products", headers=admin_h,
                       json={"code": "PRD-WORTDERIVE01", "name": "Dịch khác", "uom": "L"})
    assert other.status_code == 201, other.text
    other_product_id = other.json()["product_id"]

    order_id = _a_brew_order(client, admin_h, "LN-WORTDERIVE01", product_id=lager_product_id,
                             planned_batch_count=1)
    created = client.post("/api/brewing/brews", headers=vanhanh_h,
                         json={"brew_code": "BR-WORTDERIVE01", "wort_type": "Dịch test",
                               "product_id": other_product_id, "brew_order_id": order_id})
    assert created.status_code == 201, created.text
    assert created.json()["product_id"] == lager_product_id


def test_delete_order_blocked_once_executed(client, admin_h, vanhanh_h, lager_product_id):
    order_id = _a_brew_order(client, admin_h, "LN-DEL01", product_id=lager_product_id,
                             planned_batch_count=1)
    deletable = client.delete(f"/api/brewing/orders/{order_id}", headers=admin_h)
    assert deletable.status_code == 204, deletable.text

    order_id2 = _a_brew_order(client, admin_h, "LN-DEL02", product_id=lager_product_id,
                              planned_batch_count=1)
    used = client.post("/api/brewing/brews", headers=vanhanh_h,
                       json={"brew_code": "BR-DEL02", "wort_type": "Dịch test", "brew_order_id": order_id2})
    assert used.status_code == 201, used.text
    blocked = client.delete(f"/api/brewing/orders/{order_id2}", headers=admin_h)
    assert blocked.status_code == 409, blocked.text


def test_update_order_before_execution(client, admin_h, lager_product_id):
    order_id = _a_brew_order(client, admin_h, "LN-UPD01", product_id=lager_product_id,
                             planned_batch_count=1, planned_volume_hl=100.0, auto_from_bom=True)
    updated = client.put(f"/api/brewing/orders/{order_id}", headers=admin_h, json={
        "order_code": "LN-UPD01-B", "product_id": lager_product_id,
        "planned_batch_count": 3, "planned_volume_hl": 300.0, "volume_tolerance_hl": 5.0,
        "auto_from_bom": True, "lines": [],
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["order_code"] == "LN-UPD01-B"

    detail = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    assert detail["order_code"] == "LN-UPD01-B"
    assert detail["planned_batch_count"] == 3
    assert detail["planned_volume_hl"] == 300.0
    assert detail["volume_tolerance_hl"] == 5.0
    # Định mức NVL phải được nạp lại từ BOM theo sản lượng/số mẻ MỚI (không giữ lại số cũ).
    lines = {l["material_name"]: l for l in detail["lines"] if not l["is_header"]}
    assert set(lines.keys()) >= {"Malt Pilsner", "Hoa bia Saaz", "Men Lager W-34/70"}


def test_update_order_blocked_once_executed(client, admin_h, vanhanh_h, lager_product_id):
    order_id = _a_brew_order(client, admin_h, "LN-UPD02", product_id=lager_product_id,
                             planned_batch_count=1)
    used = client.post("/api/brewing/brews", headers=vanhanh_h,
                       json={"brew_code": "BR-UPD02", "wort_type": "Dịch test", "brew_order_id": order_id})
    assert used.status_code == 201, used.text
    blocked = client.put(f"/api/brewing/orders/{order_id}", headers=admin_h, json={
        "order_code": "LN-UPD02-B", "product_id": lager_product_id,
        "planned_batch_count": 1, "planned_volume_hl": 100.0, "volume_tolerance_hl": 0.0,
        "auto_from_bom": False, "lines": [],
    })
    assert blocked.status_code == 409, blocked.text


def test_get_order_shortage_flag(client, admin_h):
    order_id = _a_brew_order(client, admin_h, "LN-SHORT01", auto_from_bom=False, lines=[
        {"material_name": "Vật tư không đủ", "uom": "kg", "qty_total": 999999999},
        {"material_name": "Vật tư đủ (không gán kho)", "uom": "kg", "qty_total": 1},
    ])
    detail = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    over = next(l for l in detail["lines"] if l["material_name"] == "Vật tư không đủ")
    under = next(l for l in detail["lines"] if l["material_name"] == "Vật tư đủ (không gán kho)")
    assert over["shortage"] is True
    # Không có material_id -> không snapshot được tồn -> qty_total > 0 vẫn coi là shortage
    # theo đúng ngưỡng (0 + 0 = 0 < qty_total).
    assert under["shortage"] is True
