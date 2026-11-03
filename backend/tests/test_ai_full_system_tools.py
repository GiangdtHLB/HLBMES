"""8 tool AI mới (yêu cầu người dùng 2026-09-18: "mở rộng ra toàn bộ hệ thống") — kiểm tra mỗi
tool thật sự gọi được qua /api/ai/chat (engine luật, không cần ANTHROPIC_API_KEY), đúng route
theo từ khóa (INTENTS) và không lỗi (ImportError/AttributeError sẽ lộ ngay ở đây), cho các khâu
trước đây "Trợ lý AI" chưa hề chạm tới: Lệnh nấu, Cấp liệu/FIFO, Lên men, Lọc, Chiết, Kho TP/WMS,
Công thức, CAPA/Deviation."""

import os
import tempfile

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["MES_DATABASE_URL"] = f"sqlite:///{_TMP.name}"
os.environ["MES_DEV_HEADER_AUTH"] = "0"
os.environ["MES_RL_ENABLED"] = "0"
os.environ["MES_ADMIN_PASSWORD"] = "AdminTest123"
os.environ.setdefault("MES_LLM_ENABLED", "off")   # buộc dùng engine luật, không gọi Claude thật

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app import seed as seed_mod
from app.services import ai_tools


@pytest.fixture(scope="module", autouse=True)
def _seeded():
    seed_mod.seed()
    yield


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def db():
    s = SessionLocal()
    yield s
    s.close()


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture(scope="module")
def admin_h(client):
    return _login(client, "admin", "AdminTest123")


def _ask(client, admin_h, message):
    r = client.post("/api/ai/chat", headers=admin_h, json={"message": message})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def sample_batch(client, admin_h):
    """1 mẻ tối thiểu (có recipe effective + Lệnh nấu) để test các tool cần batch_code thật
    (get_isa88_status/get_ebr_lock_status/get_batch_status chi tiết) — tách riêng khỏi
    test_get_dispense_status_reports_fifo_for_real_batch để không phụ thuộc thứ tự chạy test."""
    bt = client.post("/api/beer-types", headers=admin_h,
                     json={"code": "BT-AISAMPLE", "name": "Loại AI sample"})
    recipe = client.post("/api/recipes", headers=admin_h,
                         json={"code": "CT-AISAMPLE", "name": "Recipe AI sample",
                              "beer_type_id": bt.json()["beer_type_id"]})
    prod = client.post("/api/products", headers=admin_h,
                       json={"code": "PRD-AISAMPLE", "name": "Dich AI sample", "uom": "L",
                            "beer_type_id": bt.json()["beer_type_id"]})
    v = client.post(f"/api/recipes/{recipe.json()['recipe_id']}/versions", headers=admin_h,
                    json={"base_qty": 100, "base_uom": "L", "product_id": prod.json()["product_id"],
                         "materials": []})
    version_id = v.json()["version_id"]
    for target in ("review", "approved", "effective"):
        t = client.post(f"/api/recipes/versions/{version_id}/transition", headers=admin_h,
                        json={"target": target})
        assert t.status_code == 200, t.text
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": version_id,
                         "planned_qty": 100, "allow_shortage": True, "batch_code": "77702"})
    assert b.status_code == 201, b.text
    return "77702"


def test_ai_status_lists_all_16_tools(client, admin_h):
    r = client.get("/api/ai/status", headers=admin_h)
    assert r.status_code == 200, r.text
    tools = r.json()["tools"]
    for name in ("get_brew_order_status", "get_dispense_status", "get_fermentation_status",
                "get_filter_status", "get_pack_status", "get_wms_status", "get_recipe_status",
                "get_capa_status"):
        assert name in tools, f"{name} chưa có trong manifest tool"


def test_ai_status_lists_2026_11_03_expansion_tools(client, admin_h):
    """14 tool mới (yêu cầu người dùng 2026-11-03: "mở rộng đầy đủ toàn bộ tính năng") — phủ
    CIP/Bảo trì/OEE chi tiết/Điều độ/Lập lịch/Danh mục/CAPA chi tiết/EBR lock/ISA-88/đề nghị NVL/
    Bao bì/2 báo cáo còn thiếu."""
    r = client.get("/api/ai/status", headers=admin_h)
    assert r.status_code == 200, r.text
    tools = r.json()["tools"]
    for name in ("get_cip_status", "get_maintenance_status", "get_oee_detail", "get_wo_status",
                "get_schedule_conflicts", "get_product_info", "get_material_info",
                "get_capa_detail", "get_ebr_lock_status", "get_isa88_status",
                "get_pending_material_requests", "get_packaging_status",
                "get_filter_production_report", "get_pack_line_report"):
        assert name in tools, f"{name} chưa có trong manifest tool"


def test_ai_tools_manifest_endpoint_includes_new_tools(client, admin_h):
    r = client.get("/api/ai/tools", headers=admin_h)
    assert r.status_code == 200, r.text
    names = [t["name"] for t in r.json()["tools"]]
    assert "get_dispense_status" in names
    assert "get_wms_status" in names


@pytest.mark.parametrize("message,expected_tool", [
    ("cho tôi xem lệnh nấu đang chạy", "get_brew_order_status"),
    ("tank lên men nào sắp đủ ngày", "get_fermentation_status"),
    ("lô lọc nào chưa duyệt KCS", "get_filter_status"),
    ("lô chiết gần nhất thế nào", "get_pack_status"),
    ("kho thành phẩm còn trống bao nhiêu pallet", "get_wms_status"),
    ("công thức nào đang hiệu lực", "get_recipe_status"),
    ("có deviation hay capa nào đang mở không", "get_capa_status"),
])
def test_each_new_tool_routes_and_answers_without_error(client, admin_h, message, expected_tool):
    res = _ask(client, admin_h, message)
    assert res["tools_used"] == [expected_tool], res
    assert res.get("answer"), "Phải có câu trả lời, không được rỗng"
    assert res.get("mode") == "local"


def test_get_dispense_status_reports_fifo_for_real_batch(client, admin_h):
    """Câu hỏi cụ thể "cấp liệu mẻ <mã>" phải trích đúng mã mẻ và trả về đúng dòng định mức/FIFO
    (mirror services/dispense.py::batch_dispense_summary — đã kiểm chứng đúng ở nơi khác, ở đây
    chỉ xác nhận tool AI gọi đúng và không lỗi khi có batch_code thật)."""
    mat = client.post("/api/materials", headers=admin_h,
                      json={"code": "AI-DISP-MAT", "name": "Vật tư AI dispense", "uom": "kg"})
    assert mat.status_code == 201, mat.text
    material_id, code = mat.json()["material_id"], mat.json()["code"]
    lot = client.post("/api/warehouse/receive", headers=admin_h, json={
        "material_id": material_id, "quantity": 20, "uom": "kg", "location": "Kho phân xưởng"})
    assert lot.status_code == 200, lot.text
    lot_id = lot.json()["lot_id"]

    bt = client.post("/api/beer-types", headers=admin_h,
                     json={"code": "BT-AIDISP", "name": "Loại AI dispense"})
    recipe = client.post("/api/recipes", headers=admin_h,
                         json={"code": "CT-AIDISP", "name": "Recipe AI dispense",
                              "beer_type_id": bt.json()["beer_type_id"]})
    prod = client.post("/api/products", headers=admin_h,
                       json={"code": "PRD-AIDISP", "name": "Dich AI dispense", "uom": "L",
                            "beer_type_id": bt.json()["beer_type_id"]})
    v = client.post(f"/api/recipes/{recipe.json()['recipe_id']}/versions", headers=admin_h,
                    json={"base_qty": 100, "base_uom": "L", "product_id": prod.json()["product_id"],
                         "materials": [{"material_code": code, "qty": 5, "uom": "kg", "tol_pct": 5}]})
    version_id = v.json()["version_id"]
    for target in ("review", "approved", "effective"):
        t = client.post(f"/api/recipes/versions/{version_id}/transition", headers=admin_h,
                        json={"target": target})
        assert t.status_code == 200, t.text

    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": version_id,
                         "planned_qty": 100, "allow_shortage": True, "batch_code": "77701"})
    assert b.status_code == 201, b.text
    batch_id = b.json()["batch_id"]
    for target in ("ready", "running"):
        t = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": target})
        assert t.status_code == 200, t.text
    r = client.post(f"/api/batches/{batch_id}/consume", headers=admin_h,
                    json={"lot_id": lot_id, "quantity": 5})
    assert r.status_code == 200, r.text

    res = _ask(client, admin_h, "xem cấp liệu mẻ 77701 fifo có đúng không")
    assert res["tools_used"] == ["get_dispense_status"], res
    data = res["data"]
    assert data["batch_code"] == "77701"
    line = next(l for l in data["lines"] if l["material_code"] == "AI-DISP-MAT")
    assert line["actual"] == 5.0
    assert line["fifo_ok"] is True
    assert line["fifo_computed"] is True   # tiêu thụ qua /consume trực tiếp -> suy luận lại


def test_get_dispense_status_without_batch_code_asks_for_it(client, admin_h):
    res = _ask(client, admin_h, "xem cấp liệu mẻ này")
    assert res["tools_used"] == []
    assert "mã mẻ" in res["answer"].lower()


@pytest.mark.parametrize("message,expected_tool", [
    ("lịch sử cip thiết bị nào gần đây", "get_cip_status"),
    ("có downtime nào không", "get_maintenance_status"),
    ("xem lệnh sản xuất đang chạy", "get_wo_status"),
    ("lập lịch có xung đột lịch không", "get_schedule_conflicts"),
    ("danh mục dịch bia nào đang có", "get_product_info"),
    ("capa nào có nguyên nhân gốc chưa xử lý", "get_capa_detail"),
    ("phiếu đề nghị nào đang chờ", "get_pending_material_requests"),
    ("tồn kho bao bì vỏ chai còn bao nhiêu", "get_packaging_status"),
    ("báo cáo hệ lọc tháng này", "get_filter_production_report"),
    ("xem gantt dây chuyền chiết", "get_pack_line_report"),
])
def test_2026_11_03_expansion_tools_route_and_answer_without_error(client, admin_h, message, expected_tool):
    res = _ask(client, admin_h, message)
    assert res["tools_used"] == [expected_tool], res
    assert res.get("answer"), "Phải có câu trả lời, không được rỗng"
    assert res.get("mode") == "local"


def test_ai_status_lists_2026_11_03_round2_expansion_tools(client, admin_h):
    """13 tool vòng 2 cùng ngày (yêu cầu người dùng: "còn thiếu gì không, tôi cần AI truy cập
    toàn bộ hệ thống") — phủ Dashboard (Tổng quan)/Log hệ nấu-Thời gian cả mẻ nấu/Realtime SCADA/
    RCFA-Pareto dừng máy/Danh mục chỉ tiêu QC/Audit trail."""
    r = client.get("/api/ai/status", headers=admin_h)
    assert r.status_code == 200, r.text
    tools = r.json()["tools"]
    for name in ("get_dashboard_summary", "get_hold_and_qc_alerts", "get_overdue_actions",
                "get_low_yield_alerts", "get_unapproved_pack_lots", "get_brewhouse_log",
                "get_brew_cycle_time", "get_brewhouse_realtime", "get_filling_realtime",
                "get_rcfa_list", "get_oee_loss_detail", "get_qc_spec_catalog", "get_audit_log"):
        assert name in tools, f"{name} chưa có trong manifest tool"
    assert len(tools) == 43, f"Kỳ vọng đúng 43 tool, thực tế {len(tools)}"


@pytest.mark.parametrize("message,expected_tool", [
    ("cho tôi kpi tổng quan", "get_dashboard_summary"),
    ("đang bị giữ những lô nào", "get_hold_and_qc_alerts"),
    ("có gì quá hạn xử lý không", "get_overdue_actions"),
    ("sản lượng lọc thấp gần đây", "get_low_yield_alerts"),
    ("chiết chưa duyệt còn bao nhiêu", "get_unapproved_pack_lots"),
    ("xem log hệ nấu", "get_brewhouse_log"),
    ("thời gian cả mẻ nấu gần nhất", "get_brew_cycle_time"),
    ("hệ nấu realtime đang chạy gì", "get_brewhouse_realtime"),
    ("máy chiết lon đang chạy không", "get_filling_realtime"),
    ("có rcfa nào không", "get_rcfa_list"),
    ("xem pareto top lý do dừng", "get_oee_loss_detail"),
    ("nhật ký thao tác gần đây", "get_audit_log"),
])
def test_round2_expansion_tools_route_and_answer_without_error(client, admin_h, message, expected_tool):
    res = _ask(client, admin_h, message)
    assert res["tools_used"] == [expected_tool], res
    assert res.get("answer"), "Phải có câu trả lời, không được rỗng"
    assert res.get("mode") == "local"


def test_get_qc_spec_catalog_without_filter_asks_for_it(client, admin_h):
    res = _ask(client, admin_h, "ngưỡng chỉ tiêu nào bắt buộc")
    assert res["tools_used"] == ["get_qc_spec_catalog"], res
    assert "material_code" in res["answer"] or "stage" in res["answer"]


def test_get_qc_spec_catalog_direct_call_with_material(db):
    from app.models.master import Material
    from sqlalchemy import select
    m = db.execute(select(Material)).scalars().first()
    if m is None:
        pytest.skip("Không có vật tư nào trong seed data")
    r = ai_tools.call_tool(db, "get_qc_spec_catalog", {"material_code": m.code})
    assert "error" not in r, r
    assert "material_params" in r


def test_get_isa88_status_routes_with_batch_code_in_message(client, admin_h, sample_batch):
    res = _ask(client, admin_h, f"isa-88 mẻ {sample_batch} tới đâu rồi")
    assert res["tools_used"] == ["get_isa88_status"], res
    assert res.get("answer")


def test_get_batch_status_single_batch_includes_ebr_detail(db, sample_batch):
    """get_batch_status(batch_code=...) phải trả thêm order_code/recipe/start_at/end_at/
    ebr_locked/signatures (enrich 2026-11-03), không chỉ state/quality_status/planned/actual
    như trước."""
    data = ai_tools.call_tool(db, "get_batch_status", {"batch_code": sample_batch})
    assert "error" not in data, data
    for key in ("order_code", "recipe", "start_at", "end_at", "ebr_locked", "signatures"):
        assert key in data, f"Thiếu field {key}"


def test_new_tools_without_clean_local_keyword_callable_directly(db, sample_batch):
    """Tool cần tham số bắt buộc khó trích từ câu tự nhiên (get_ebr_lock_status, get_material_info,
    get_oee_detail) — không có trong engine luật offline, kiểm tra trực tiếp qua call_tool() thay
    vì qua /api/ai/chat (mirror cách Claude tool-use thật sẽ gọi, với tham số đầy đủ)."""
    r = ai_tools.call_tool(db, "get_ebr_lock_status", {"scope_type": "batch", "code": sample_batch})
    assert "error" not in r, r
    assert "locked" in r and "signatures" in r
    r = ai_tools.call_tool(db, "get_material_info", {})
    assert "materials" in r
    r = ai_tools.call_tool(db, "get_oee_detail", {"line_code": "Line-1 (chai)"})
    assert "monthly" in r and "quarterly" in r
