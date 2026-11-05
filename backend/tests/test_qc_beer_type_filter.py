"""Test lọc báo cáo "QC theo công đoạn" theo Loại bia (yêu cầu người dùng 2026-11-05: "tôi muốn
xem theo loại bia") trong services/qc_catalog.py::scope_ids_by_beer_type + spc_chart(beer_type_id=).

QualityResult không lưu thẳng beer_type_id — phải suy qua Dịch bia (product_id) của mẻ/tank/WO,
hoặc Loại bia khai trực tiếp trên lô lọc. Dựng 2 mẻ (2 Dịch bia, 2 Loại bia khác nhau) + 1 lô NVL
(không gắn Loại bia nào) để xác nhận: lọc đúng theo Loại bia, và công đoạn NVL bị loại khi có bộ
lọc này (đúng theo thiết kế, không phải lỗi)."""

import os
import tempfile
from datetime import datetime, timezone

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["MES_DATABASE_URL"] = f"sqlite:///{_TMP.name}"
os.environ["MES_DEV_HEADER_AUTH"] = "0"
os.environ["MES_RL_ENABLED"] = "0"
os.environ["MES_ADMIN_PASSWORD"] = "AdminTest123"

import pytest

from app.main import app  # noqa: F401
from app import seed as seed_mod
from app.database import SessionLocal
from app.common import IN_CHUNK, new_id
from app.models.batch_pipeline import BatchFilterLot, BatchPackLot
from app.models.quality import QualityResult
from app.services import qc_catalog
from fastapi.testclient import TestClient

PARAM = "BTFILTER Độ cồn"


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


def _make_beer_type_product_batch(client, admin_h, suffix):
    """Dựng 1 Loại bia + 1 Dịch bia gán Loại bia đó + 1 recipe effective + 1 mẻ — mirror
    test_ai_full_system_tools.py::sample_batch (pattern đã có sẵn trong repo để tạo nhanh 1 mẻ
    tối thiểu không phụ thuộc seed có sẵn mấy recipe)."""
    bt = client.post("/api/beer-types", headers=admin_h,
                     json={"code": f"BTFILTER-{suffix}", "name": f"Loại bia test {suffix}"})
    assert bt.status_code == 201, bt.text
    beer_type_id = bt.json()["beer_type_id"]
    prod = client.post("/api/products", headers=admin_h,
                       json={"code": f"PRD-BTFILTER-{suffix}", "name": f"Dịch bia test {suffix}",
                            "uom": "L", "beer_type_id": beer_type_id})
    assert prod.status_code == 201, prod.text
    product_id = prod.json()["product_id"]
    recipe = client.post("/api/recipes", headers=admin_h,
                         json={"code": f"CT-BTFILTER-{suffix}", "name": f"Recipe test {suffix}",
                              "beer_type_id": beer_type_id})
    assert recipe.status_code == 201, recipe.text
    v = client.post(f"/api/recipes/{recipe.json()['recipe_id']}/versions", headers=admin_h,
                    json={"base_qty": 1000, "base_uom": "L", "product_id": product_id, "materials": []})
    assert v.status_code == 201, v.text
    version_id = v.json()["version_id"]
    for target in ("review", "approved", "effective"):
        t = client.post(f"/api/recipes/versions/{version_id}/transition", headers=admin_h,
                        json={"target": target})
        assert t.status_code == 200, t.text
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": version_id,
                          "planned_qty": 1000, "allow_shortage": True})
    assert b.status_code == 201, b.text
    return b.json()["batch_id"], beer_type_id


@pytest.fixture(scope="module")
def two_beer_type_batches(client, admin_h):
    batch_a, beer_type_a = _make_beer_type_product_batch(client, admin_h, "A")
    batch_b, beer_type_b = _make_beer_type_product_batch(client, admin_h, "B")

    db = SessionLocal()
    now = datetime(2031, 6, 1, tzinfo=timezone.utc)
    db.add(QualityResult(result_id=new_id(), sample_id=new_id(), scope_type="batch",
                         scope_id=batch_a, parameter=PARAM, value=5.0, unit="%",
                         status="pass", recorded_at=now))
    db.add(QualityResult(result_id=new_id(), sample_id=new_id(), scope_type="batch",
                         scope_id=batch_b, parameter=PARAM, value=4.5, unit="%",
                         status="pass", recorded_at=now))
    # 1 dòng NVL (scope_type="lot") cùng parameter — phải KHÔNG xuất hiện khi lọc theo Loại bia
    # (1 lô NVL không gán được cho đúng 1 Loại bia, theo đúng thiết kế của scope_ids_by_beer_type).
    # scope_id không phải FK thật (chỉ Unicode index) nên dùng id giả cũng hợp lệ cho mục đích test.
    db.add(QualityResult(result_id=new_id(), sample_id=new_id(), scope_type="lot",
                         scope_id=new_id(), parameter=PARAM, value=4.8, unit="%",
                         status="pass", recorded_at=now))
    db.commit()
    db.close()
    return {"batch_a": batch_a, "batch_b": batch_b, "beer_type_a": beer_type_a, "beer_type_b": beer_type_b}


def test_spc_filters_by_beer_type_with_explicit_scope_type(client, admin_h, two_beer_type_batches):
    r = client.get("/api/qc/spc", headers=admin_h, params={
        "parameter": PARAM, "scope_type": "batch", "beer_type_id": two_beer_type_batches["beer_type_a"]})
    assert r.status_code == 200, r.text
    spc = r.json()
    assert spc["n"] == 1
    assert spc["points"][0]["value"] == 5.0


def test_spc_filters_by_beer_type_across_all_scope_types_excludes_nvl(client, admin_h, two_beer_type_batches):
    """Không truyền scope_type ("Tất cả công đoạn") + beer_type_id -> vẫn chỉ ra đúng 1 điểm của
    Loại bia B, và dòng NVL (scope_type="lot") cùng parameter phải KHÔNG lọt vào dù giá trị có
    nằm trong dữ liệu thật."""
    r = client.get("/api/qc/spc", headers=admin_h, params={
        "parameter": PARAM, "beer_type_id": two_beer_type_batches["beer_type_b"]})
    assert r.status_code == 200, r.text
    spc = r.json()
    assert spc["n"] == 1
    assert spc["points"][0]["value"] == 4.5


def test_spc_without_beer_type_filter_sees_all_including_nvl(client, admin_h, two_beer_type_batches):
    r = client.get("/api/qc/spc", headers=admin_h, params={"parameter": PARAM})
    assert r.status_code == 200, r.text
    assert r.json()["n"] == 3  # 2 mẻ + 1 NVL — không lọc Loại bia thì thấy hết


def test_scope_ids_by_beer_type_chunks_in_clause_past_in_chunk_lots(client, admin_h, two_beer_type_batches):
    """Audit prod 2026-11 phát hiện qc_catalog.scope_ids_by_beer_type() đưa TOÀN BỘ filter_lot_ids
    của 1 Loại bia (không giới hạn, không lọc ngày) thẳng vào .in_() khi tra batch_pack_lot — Loại
    bia lớn nhất đã 256 lô lọc, tăng ~250/tháng, sẽ vượt trần 2100 tham số SQL Server giữa 2027,
    vỡ báo cáo "QC theo công đoạn" (SQLite dev không bao giờ lộ lỗi này). Dựng trực tiếp qua ORM
    (bỏ qua lifecycle đầy đủ — hàm chỉ đọc thẳng BatchFilterLot/BatchPackLot, không quan tâm
    on_hand/trạng thái, mirror test_qc_stat_reports.py) > IN_CHUNK (900) lô lọc để xác nhận
    execute_in_chunks() đã thay .in_() trần, không chỉ xử lý đúng 1 mẻ đầu rồi bỏ sót phần còn lại
    (mirror test_dispense_order_rule_chunking.py)."""
    beer_type_id = two_beer_type_batches["beer_type_a"]
    count = IN_CHUNK + 50   # > 1 mẻ, không chia hết IN_CHUNK để lộ lỗi chia dư nếu có
    db = SessionLocal()
    try:
        for i in range(count):
            fl = BatchFilterLot(filter_lot_id=new_id(), filter_lot_code=f"BTSCALE-{i}",
                                filter_lot_year=2031, beer_type_id=beer_type_id)
            db.add(fl)
            db.add(BatchPackLot(pack_lot_id=new_id(), pack_lot_code=f"BTSCALE-PKG-{i}",
                                pack_lot_year=2031, filter_lot_id=fl.filter_lot_id, qty=100.0))
        db.commit()
    finally:
        db.close()

    db2 = SessionLocal()
    try:
        scopes = qc_catalog.scope_ids_by_beer_type(db2, beer_type_id)
    finally:
        db2.close()
    assert len(scopes["batch_filter_lot"]) == count
    assert len(scopes["batch_pack_lot"]) == count   # phải thấy ĐỦ, không chỉ 1 mẻ IN_CHUNK đầu
