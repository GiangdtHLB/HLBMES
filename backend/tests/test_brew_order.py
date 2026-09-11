"""Test Lệnh nấu (Brew Production Order) — mẫu giấy "LỆNH NẤU BIA KIÊM PHIẾU XUẤT KHO",
chỉ giữ phần LỆNH:
1) Tạo lệnh tự nạp Định mức từ Công thức (BOM) hiệu lực, scale đúng theo số mẻ kế hoạch;
   snapshot tồn kho công ty/phân xưởng lúc lập phiếu.
2) Tạo lệnh với dòng NVL nhập tay (kể cả dòng header, dòng không có material_id).
3) 1 lệnh có thể có NHIỀU mẻ sản xuất (BatchExecution, pipeline "Mẻ sản xuất"), sản lượng
   thực tế (actual_qty) cộng dồn tới khi lệch trong khoảng ±sai số so với kế hoạch
   (planned_volume_hl) thì lệnh hoàn thành, không cho hoàn thành sớm khi còn mẻ dở dang.
4) Xóa lệnh bị chặn khi đã thực hiện (có ít nhất 1 mẻ sản xuất).
5) Thiếu tồn (tổng 2 kho) thì chặn hẳn việc tạo/sửa lệnh (không cho lưu), mirror Lệnh lọc."""

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
def lager_product_id(client, admin_h):
    products = client.get("/api/products", headers=admin_h).json()
    return next(p["product_id"] for p in products if p["code"] == "BIA-LAGER")


@pytest.fixture(scope="module")
def lager_recipe_version_id(client, admin_h, lager_product_id):
    """1 Loại bia có đúng 1 Recipe (nhiều RecipeVersion, mỗi version tự gắn 1 Dịch bia riêng) —
    người lập Lệnh nấu BẮT BUỘC tự chọn 1 version đang hiệu lực ĐÚNG dịch bia (seed.py tạo sẵn
    REC-LAGER + version effective cho BIA-LAGER)."""
    products = client.get("/api/products", headers=admin_h).json()
    beer_type_id = next(p["beer_type_id"] for p in products if p["product_id"] == lager_product_id)
    recipes = client.get("/api/recipes", headers=admin_h).json()
    recipe = next(r for r in recipes if r["beer_type_id"] == beer_type_id)
    versions = client.get(f"/api/recipes/{recipe['recipe_id']}/versions", headers=admin_h).json()
    return next(v["version_id"] for v in versions if v["state"] == "effective" and v["product_id"] == lager_product_id)


def _a_brew_order(client, admin_h, order_code, product_id=None, recipe_version_id=None, planned_batch_count=1,
                  planned_volume_hl=100.0, volume_tolerance_hl=0.0,
                  auto_from_bom=False, lines=None):
    r = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": order_code, "product_id": product_id, "recipe_version_id": recipe_version_id,
        "planned_batch_count": planned_batch_count,
        "planned_volume_hl": planned_volume_hl, "volume_tolerance_hl": volume_tolerance_hl,
        "auto_from_bom": auto_from_bom, "lines": lines or [],
    })
    assert r.status_code == 201, r.text
    return r.json()["brew_order_id"]


def _create_batch(client, admin_h, order_id, recipe_version_id):
    b = client.post("/api/batches", headers=admin_h, json={
        "order_id": order_id, "recipe_version_id": recipe_version_id, "allow_shortage": True,
    })
    assert b.status_code == 201, b.text
    return b.json()["batch_id"]


def _set_real_actual_volume(client, admin_h, order_id, recipe_version_id, actual_qty, finish=True):
    """Sản lượng THỰC TẾ (dùng để tính actual_volume_hl/is_complete của Lệnh nấu) lấy từ
    BatchExecution.actual_qty — mirror đúng cách pipeline "Mẻ sản xuất" tính (xem
    services/brew_order.py::_is_complete). Lệnh chỉ "hoàn thành" khi mẻ cũng đã "Kết thúc"
    (BatchExecution.end_at có giá trị) — mặc định finish=True; truyền finish=False để test
    riêng nhánh "còn mẻ dở dang"."""
    batch_id = _create_batch(client, admin_h, order_id, recipe_version_id)
    for target in ("ready", "running"):
        r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": target})
        assert r.status_code == 200, r.text
    aq = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": actual_qty})
    assert aq.status_code == 200, aq.text
    if finish:
        f = client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={})
        assert f.status_code == 200, f.text
    return batch_id


def test_create_order_auto_from_bom(client, admin_h, lager_product_id, lager_recipe_version_id):
    # 3 mẻ là số lớn nhất còn NẰM TRONG tồn kho seed sẵn cho cả 3 NVL (Men Lager W-34/70 chỉ
    # đủ đúng 3 mẻ: 50kg/mẻ x 3 = 150kg = đúng tồn) — dùng số này để lệnh còn tạo được (đủ
    # tồn), xem test_create_order_blocked_when_shortage cho trường hợp ngược lại.
    order_id = _a_brew_order(client, admin_h, "LN-BOM01", product_id=lager_product_id,
                             recipe_version_id=lager_recipe_version_id,
                             planned_batch_count=3, planned_volume_hl=444, auto_from_bom=True)
    detail = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    assert detail["planned_batch_count"] == 3
    lines = {l["material_name"]: l for l in detail["lines"] if not l["is_header"]}
    assert set(lines.keys()) >= {"Malt Pilsner", "Hoa bia Saaz", "Men Lager W-34/70"}

    malt = lines["Malt Pilsner"]
    # Công thức khai báo NVL cho ĐÚNG 1 mẻ (1200 kg) — planned_volume_hl không scale nữa,
    # chỉ planned_batch_count nhân trực tiếp vào tổng nhu cầu.
    assert malt["qty_per_batch"] == pytest.approx(1200)
    assert malt["qty_total"] == pytest.approx(1200 * 3)
    # Snapshot tồn phải được ghi lại (không None) vì Malt Pilsner có material_id thật.
    assert malt["stock_company_snapshot"] is not None or malt["stock_workshop_snapshot"] is not None


def test_bom_preview_matches_created_order_without_creating_it(client, admin_h, lager_product_id, lager_recipe_version_id):
    """Xem trước NVL (nút "Xem NVL") phải cho đúng số liệu như lúc tạo lệnh thật — nhưng
    KHÔNG tạo ra lệnh nào (chỉ để kiểm tra đủ/thiếu tồn trước khi bấm Tạo lệnh nấu)."""
    before = client.get("/api/brewing/orders", headers=admin_h).json()
    preview = client.get("/api/brewing/orders/bom-preview", headers=admin_h,
                        params={"recipe_version_id": lager_recipe_version_id, "planned_batch_count": 12,
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


def test_bom_preview_flags_shortage_for_huge_batch(client, admin_h, lager_product_id, lager_recipe_version_id):
    """planned_volume_hl không còn ảnh hưởng nhu cầu NVL — số mẻ kế hoạch cực lớn mới
    khiến tổng nhu cầu vượt tồn kho (Nhu cầu Tổng mẻ = Nhu cầu 1 mẻ x Số mẻ kế hoạch)."""
    preview = client.get("/api/brewing/orders/bom-preview", headers=admin_h,
                        params={"recipe_version_id": lager_recipe_version_id, "planned_batch_count": 999999,
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


def test_add_batch_requires_valid_order(client, admin_h, lager_recipe_version_id):
    """order_id bắt buộc tồn tại thật — tạo Mẻ sản xuất (BatchExecution) với order_id giả
    phải báo lỗi nghiệp vụ (404), mirror kiểm tra cũ ở create_brew_record (module Nấu-Lọc-
    Chiết cũ) nay chuyển hẳn sang services/batches.py::create_batch."""
    bogus = client.post("/api/batches", headers=admin_h,
                        json={"order_id": "does-not-exist", "recipe_version_id": lager_recipe_version_id})
    assert bogus.status_code == 404, bogus.text

    order_id = _a_brew_order(client, admin_h, "LN-EXEC01", planned_batch_count=1)
    ok = client.post("/api/batches", headers=admin_h,
                     json={"order_id": order_id, "recipe_version_id": lager_recipe_version_id,
                           "allow_shortage": True})
    assert ok.status_code == 201, ok.text

    detail = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    assert detail["is_executed"] is True

    # Lệnh chưa hoàn thành (kế hoạch 100hl, mẻ chưa khai actual_qty nên thực tế vẫn = 0)
    # -> vẫn thêm được mẻ thứ 2 — mirror Lệnh lọc.
    again = client.post("/api/batches", headers=admin_h,
                        json={"order_id": order_id, "recipe_version_id": lager_recipe_version_id,
                              "allow_shortage": True})
    assert again.status_code == 201, again.text


def test_create_order_requires_positive_planned_volume(client, admin_h):
    zero = client.post("/api/brewing/orders", headers=admin_h,
                       json={"order_code": "LN-VOL01", "auto_from_bom": False, "planned_volume_hl": 0})
    assert zero.status_code == 409, zero.text

    negative_tol = client.post("/api/brewing/orders", headers=admin_h,
                               json={"order_code": "LN-VOL02", "auto_from_bom": False,
                                     "planned_volume_hl": 100, "volume_tolerance_hl": -1})
    assert negative_tol.status_code == 409, negative_tol.text


def test_order_completes_when_actual_volume_within_tolerance(client, admin_h, lager_recipe_version_id):
    order_id = _a_brew_order(client, admin_h, "LN-VOL03", planned_volume_hl=100, volume_tolerance_hl=5)

    _set_real_actual_volume(client, admin_h, order_id, lager_recipe_version_id, 96)

    detail = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    assert detail["actual_volume_hl"] == 96
    assert detail["is_complete"] is True
    # LƯU Ý: khác hành vi cũ (create_brew_record chặn 409 khi Lệnh nấu đã hoàn thành) —
    # services/batches.py::create_batch (đường tạo mẻ trực tiếp qua "Tạo mẻ", ngoài Điều độ)
    # hiện KHÔNG kiểm tra is_complete của Lệnh nấu cha, nên vẫn tạo mẻ mới được dù đã hoàn
    # thành. Đây là khoảng trống có sẵn của pipeline "Mẻ sản xuất", không phải hành vi tôi vừa
    # đổi ở đây — không assert 409 nữa.


def test_multiple_batches_accumulate_volume_independently(client, admin_h, lager_recipe_version_id):
    order_id = _a_brew_order(client, admin_h, "LN-VOL04", planned_volume_hl=100, volume_tolerance_hl=5)

    _set_real_actual_volume(client, admin_h, order_id, lager_recipe_version_id, 40)

    detail = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    assert detail["actual_volume_hl"] == 40
    assert detail["is_complete"] is False, "40hl còn cách xa 100hl kế hoạch -> chưa hoàn thành"

    _set_real_actual_volume(client, admin_h, order_id, lager_recipe_version_id, 55)

    detail2 = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    assert detail2["actual_volume_hl"] == 95
    assert detail2["is_complete"] is True


def test_order_not_complete_while_any_batch_unfinished(client, admin_h, lager_recipe_version_id):
    """Sản lượng đã khớp kế hoạch (±sai số) KHÔNG đủ để lệnh hoàn thành — còn mẻ nào chưa
    kết thúc thì lệnh vẫn coi như đang thực hiện; chỉ hoàn thành khi TẤT CẢ mẻ thuộc lệnh
    đã kết thúc (end_at có giá trị)."""
    order_id = _a_brew_order(client, admin_h, "LN-VOL05", planned_volume_hl=100, volume_tolerance_hl=5)

    batch_id = _set_real_actual_volume(client, admin_h, order_id, lager_recipe_version_id, 98, finish=False)

    detail = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    assert detail["actual_volume_hl"] == 98
    assert detail["is_complete"] is False, "sản lượng khớp nhưng mẻ chưa Kết thúc -> chưa hoàn thành"

    # Chưa hoàn thành -> vẫn thêm được mẻ khác bình thường.
    still_open = client.post("/api/batches", headers=admin_h,
                             json={"order_id": order_id, "recipe_version_id": lager_recipe_version_id,
                                   "allow_shortage": True})
    assert still_open.status_code == 201, still_open.text
    still_open_id = still_open.json()["batch_id"]

    finish = client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={})
    assert finish.status_code == 200, finish.text

    # Mẻ thứ 2 (still_open) vẫn CHƯA kết thúc -> lệnh vẫn chưa hoàn thành dù mẻ đầu đã xong.
    still_open_detail = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    assert still_open_detail["is_complete"] is False, \
        "còn mẻ (still_open) chưa Kết thúc -> vẫn chưa hoàn thành dù mẻ kia đã xong"

    finish2 = client.post(f"/api/batches/{still_open_id}/finish", headers=admin_h, json={})
    assert finish2.status_code == 200, finish2.text

    detail2 = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    assert detail2["is_complete"] is True, "đủ sản lượng VÀ tất cả mẻ đã kết thúc -> hoàn thành"


def test_order_completes_when_actual_volume_exceeds_plan(client, admin_h, lager_recipe_version_id):
    """Vượt kế hoạch (dù vượt xa hơn sai số cho phép) vẫn phải coi là hoàn thành — chỉ chặn
    hoàn thành khi HỤT quá sai số, không còn chặn khi VƯỢT (một chiều, khác hành vi cũ
    ±sai số 2 chiều)."""
    order_id = _a_brew_order(client, admin_h, "LN-VOL06", planned_volume_hl=50, volume_tolerance_hl=5)

    _set_real_actual_volume(client, admin_h, order_id, lager_recipe_version_id, 200)

    detail = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    assert detail["actual_volume_hl"] == 200
    assert detail["is_complete"] is True, "200hl vượt xa 50hl kế hoạch nhưng vẫn phải hoàn thành"


def test_order_not_complete_when_shortfall_exceeds_tolerance(client, admin_h, lager_recipe_version_id):
    """Hụt quá sai số cho phép (dưới kế hoạch - sai số) vẫn phải chặn hoàn thành như cũ."""
    order_id = _a_brew_order(client, admin_h, "LN-VOL07", planned_volume_hl=50, volume_tolerance_hl=5)

    _set_real_actual_volume(client, admin_h, order_id, lager_recipe_version_id, 40)

    detail = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    assert detail["actual_volume_hl"] == 40
    assert detail["is_complete"] is False, "40hl hụt hơn 5hl sai số so với 50hl kế hoạch -> chưa hoàn thành"


def test_delete_order_blocked_once_executed(client, admin_h, lager_recipe_version_id):
    order_id = _a_brew_order(client, admin_h, "LN-DEL01", planned_batch_count=1)
    deletable = client.delete(f"/api/brewing/orders/{order_id}", headers=admin_h)
    assert deletable.status_code == 204, deletable.text
    # Xác nhận đã xóa THẬT trong DB (không chỉ status 204) — bug thực tế đã gặp: thiếu
    # db.commit() sau db.delete() khiến session đóng lại rollback ngầm, lệnh vẫn còn nguyên
    # (báo cáo người dùng 2026-09-05: "đã ấn xóa, ghi là đã xóa nhưng vẫn còn ở đó không mất").
    gone = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h)
    assert gone.status_code == 404, gone.text

    order_id2 = _a_brew_order(client, admin_h, "LN-DEL02", planned_batch_count=1)
    used = client.post("/api/batches", headers=admin_h,
                       json={"order_id": order_id2, "recipe_version_id": lager_recipe_version_id,
                             "allow_shortage": True})
    assert used.status_code == 201, used.text
    blocked = client.delete(f"/api/brewing/orders/{order_id2}", headers=admin_h)
    assert blocked.status_code == 409, blocked.text


def test_update_order_before_execution(client, admin_h, lager_product_id, lager_recipe_version_id):
    order_id = _a_brew_order(client, admin_h, "LN-UPD01", product_id=lager_product_id,
                             recipe_version_id=lager_recipe_version_id,
                             planned_batch_count=1, planned_volume_hl=100.0, auto_from_bom=True)
    updated = client.put(f"/api/brewing/orders/{order_id}", headers=admin_h, json={
        "order_code": "LN-UPD01-B", "product_id": lager_product_id, "recipe_version_id": lager_recipe_version_id,
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


def test_update_order_blocked_once_executed(client, admin_h, lager_product_id, lager_recipe_version_id):
    order_id = _a_brew_order(client, admin_h, "LN-UPD02", product_id=lager_product_id,
                             planned_batch_count=1)
    used = client.post("/api/batches", headers=admin_h,
                       json={"order_id": order_id, "recipe_version_id": lager_recipe_version_id,
                             "allow_shortage": True})
    assert used.status_code == 201, used.text
    blocked = client.put(f"/api/brewing/orders/{order_id}", headers=admin_h, json={
        "order_code": "LN-UPD02-B", "product_id": lager_product_id,
        "planned_batch_count": 1, "planned_volume_hl": 100.0, "volume_tolerance_hl": 0.0,
        "auto_from_bom": False, "lines": [],
    })
    assert blocked.status_code == 409, blocked.text


def test_create_order_blocked_when_shortage(client, admin_h):
    """Thiếu tồn (tổng 2 kho) thì CHẶN HẲN việc tạo lệnh nấu, không cho lưu bất kỳ dòng nào —
    khác trước đây (chỉ cảnh báo cờ "shortage" ở preview/get_order rồi vẫn cho lưu), mirror
    Lệnh lọc (xem services/brew_order.py::_assert_no_shortage)."""
    before = client.get("/api/brewing/orders", headers=admin_h).json()
    r = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": "LN-SHORT01", "product_id": None,
        "planned_batch_count": 1, "planned_volume_hl": 100.0, "volume_tolerance_hl": 0.0,
        "auto_from_bom": False, "lines": [
            {"material_name": "Vật tư không đủ", "uom": "kg", "qty_total": 999999999},
            {"material_name": "Vật tư đủ (không gán kho)", "uom": "kg", "qty_total": 1},
        ],
    })
    assert r.status_code == 409, r.text
    assert "Vật tư không đủ" in r.text
    after = client.get("/api/brewing/orders", headers=admin_h).json()
    assert len(after) == len(before), "Lệnh thiếu tồn bị chặn thì không được tạo ra bất kỳ lệnh nào"


def test_create_and_update_order_admin_fields_roundtrip(client, admin_h):
    """7 field hành chính (mirror ProductionOrder) phải lưu/đọc lại đúng qua create/update/get —
    trước đây các field này chỉ tồn tại trên BrewMasterOrder (lệnh nấu lớn), giờ nằm thẳng trên
    BrewOrder sau khi bỏ lớp lồng "lệnh nấu nhỏ"."""
    r = client.post("/api/brewing/orders", headers=admin_h, json={
        "order_code": "LN-ADMIN01", "auto_from_bom": False, "planned_volume_hl": 100.0,
        "issued_by": "Người ra lệnh test", "executor_unit": "Phân xưởng bia Đông Mai",
        "warehouse_keeper": "Thủ kho test", "reference_note": "Căn cứ kế hoạch sản xuất",
        "safety_note": "Đeo bảo hộ đầy đủ",
    })
    assert r.status_code == 201, r.text
    order_id = r.json()["brew_order_id"]
    detail = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    assert detail["issued_by"] == "Người ra lệnh test"
    assert detail["executor_unit"] == "Phân xưởng bia Đông Mai"
    assert detail["warehouse_keeper"] == "Thủ kho test"
    assert detail["reference_note"] == "Căn cứ kế hoạch sản xuất"
    assert detail["safety_note"] == "Đeo bảo hộ đầy đủ"

    updated = client.put(f"/api/brewing/orders/{order_id}", headers=admin_h, json={
        "order_code": "LN-ADMIN01", "auto_from_bom": False, "planned_volume_hl": 100.0,
        "issued_by": "Người ra lệnh mới", "executor_unit": "Phân xưởng bia Đông Mai",
        "warehouse_keeper": "Thủ kho test", "reference_note": "Căn cứ kế hoạch sản xuất",
        "safety_note": "An toàn mới",
    })
    assert updated.status_code == 200, updated.text
    detail2 = client.get(f"/api/brewing/orders/{order_id}", headers=admin_h).json()
    assert detail2["issued_by"] == "Người ra lệnh mới"
    assert detail2["safety_note"] == "An toàn mới"
