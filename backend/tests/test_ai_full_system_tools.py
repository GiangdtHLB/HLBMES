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


def _ask(client, admin_h, message):
    r = client.post("/api/ai/chat", headers=admin_h, json={"message": message})
    assert r.status_code == 200, r.text
    return r.json()


def test_ai_status_lists_all_16_tools(client, admin_h):
    r = client.get("/api/ai/status", headers=admin_h)
    assert r.status_code == 200, r.text
    tools = r.json()["tools"]
    for name in ("get_brew_order_status", "get_dispense_status", "get_fermentation_status",
                "get_filter_status", "get_pack_status", "get_wms_status", "get_recipe_status",
                "get_capa_status"):
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
