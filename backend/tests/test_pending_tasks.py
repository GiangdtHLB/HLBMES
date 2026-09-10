"""Việc cần làm (chuông thông báo) — mỗi tài khoản chỉ thấy đúng phần việc thuộc quyền/phạm vi
của mình (services/pending_tasks.py). Test theo 2 cách:
- Qua HTTP thật (TestClient) với tài khoản demo có sẵn quyền phù hợp — phủ đúng luồng thật.
- Gọi thẳng service với User dựng tay (bypass HTTP) cho các quyền không có tài khoản demo nào
  giữ (VD maintenance.manage) — vẫn cần test đúng cơ chế lọc quyền, không phải test tài khoản đó.
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
from app.database import SessionLocal
from app.security import User as SecurityUser
from app.services import pending_tasks as svc


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
def thukho_h(client):
    return _login(client, "thukho", "123456")


@pytest.fixture(scope="module")
def vanhanh_h(client):
    return _login(client, "vanhanh", "123456")


@pytest.fixture(scope="module")
def kysu_h(client):
    return _login(client, "kysu", "123456")


def _create_material(client, admin_h, code):
    r = client.post("/api/materials", headers=admin_h,
                    json={"code": code, "name": f"Vật tư {code}", "uom": "kg", "category": "other"})
    assert r.status_code == 201, r.text
    return r.json()["material_id"]


def _items_by_key(payload):
    return {i["key"]: i for i in payload["items"]}


def test_endpoint_requires_auth(client):
    r = client.get("/api/pending-tasks")
    assert r.status_code == 403, r.text


def test_sang_ngang_only_counted_for_workshop_approver(client, admin_h, thukho_h, vanhanh_h):
    """sang-ngang pending phải hiện cho vanhanh (warehouse.request + scope phan_xuong) — KHÔNG
    hiện cho thukho (người tạo, chỉ có warehouse.receive/issue, không duyệt được chính đề nghị
    mình tạo — maker-checker, mirror test_sang_ngang.py)."""
    mat_id = _create_material(client, admin_h, "PT-SNG-01")
    before_van = _items_by_key(client.get("/api/pending-tasks", headers=vanhanh_h).json())
    before_n = before_van.get("sng_approve", {}).get("count", 0)

    r = client.post("/api/warehouse/sang-ngang", headers=thukho_h,
                    json={"lot_code": "PT-SNG-LOT-01", "material_id": mat_id, "quantity": 10, "uom": "kg"})
    assert r.status_code == 201, r.text

    after_van = client.get("/api/pending-tasks", headers=vanhanh_h).json()
    van_items = _items_by_key(after_van)
    assert van_items["sng_approve"]["count"] == before_n + 1
    assert van_items["sng_approve"]["view"] == "warehouse_px"
    assert van_items["sng_approve"]["sub"] == "sangngang"
    assert after_van["total"] >= van_items["sng_approve"]["count"]

    thukho_items = _items_by_key(client.get("/api/pending-tasks", headers=thukho_h).json())
    assert "sng_approve" not in thukho_items


def test_material_request_only_counted_for_company_fulfiller(client, admin_h, thukho_h, vanhanh_h):
    """Đề nghị nhận kho pending phải hiện cho thukho (warehouse.issue) — KHÔNG hiện cho vanhanh
    (người tạo, không có warehouse.issue)."""
    mat_id = _create_material(client, admin_h, "PT-REQ-01")
    rc = client.post("/api/warehouse/receive", headers=thukho_h,
                     json={"lot_code": "PT-REQ-LOT-01", "material_id": mat_id, "quantity": 50, "uom": "kg"})
    assert rc.status_code == 200, rc.text
    r = client.post("/api/warehouse/requests", headers=vanhanh_h,
                    json={"lines": [{"material_id": mat_id, "quantity": 5, "uom": "kg"}]})
    assert r.status_code == 201, r.text

    thukho_items = _items_by_key(client.get("/api/pending-tasks", headers=thukho_h).json())
    assert thukho_items["material_request"]["count"] >= 1
    assert thukho_items["material_request"]["view"] == "warehouse_kc"
    assert thukho_items["material_request"]["sub"] == "xtdn"

    vanhanh_items = _items_by_key(client.get("/api/pending-tasks", headers=vanhanh_h).json())
    assert "material_request" not in vanhanh_items


def test_recipe_review_only_counted_for_recipe_approver(client, admin_h, thukho_h, kysu_h):
    """Recipe version ở trạng thái 'review' phải hiện cho kysu (recipe.approve) — KHÔNG hiện cho
    thukho (không có recipe.approve)."""
    bt = client.post("/api/beer-types", headers=admin_h, json={"code": "PT-BT-01", "name": "Loại PT"})
    assert bt.status_code == 201, bt.text
    beer_type_id = bt.json()["beer_type_id"]
    p = client.post("/api/products", headers=admin_h,
                    json={"code": "PT-PRD-01", "name": "Dịch PT", "uom": "L", "beer_type_id": beer_type_id})
    assert p.status_code == 201, p.text
    product_id = p.json()["product_id"]
    rec = client.post("/api/recipes", headers=admin_h,
                      json={"code": "PT-REC-01", "name": "CT PT", "beer_type_id": beer_type_id})
    assert rec.status_code == 201, rec.text
    recipe_id = rec.json()["recipe_id"]
    v = client.post(f"/api/recipes/{recipe_id}/versions", headers=admin_h, json={"product_id": product_id})
    assert v.status_code == 201, v.text
    version_id = v.json()["version_id"]

    before = _items_by_key(client.get("/api/pending-tasks", headers=kysu_h).json())
    before_n = before.get("recipe_review", {}).get("count", 0)

    tr = client.post(f"/api/recipes/versions/{version_id}/transition", headers=admin_h, json={"target": "review"})
    assert tr.status_code == 200, tr.text

    kysu_items = _items_by_key(client.get("/api/pending-tasks", headers=kysu_h).json())
    assert kysu_items["recipe_review"]["count"] == before_n + 1
    assert kysu_items["recipe_review"]["view"] == "recipeadv"

    thukho_items = _items_by_key(client.get("/api/pending-tasks", headers=thukho_h).json())
    assert "recipe_review" not in thukho_items


def test_admin_sees_everything_zero_count_categories_hidden(client, admin_h):
    """Admin bypass mọi quyền — total = tổng count của mọi mục đang hiện; mục count=0 không
    được liệt kê (chỉ hiện việc THẬT SỰ đang chờ)."""
    payload = client.get("/api/pending-tasks", headers=admin_h).json()
    assert payload["total"] == sum(i["count"] for i in payload["items"])
    assert all(i["count"] > 0 for i in payload["items"])


def test_maintenance_category_gated_by_permission_not_role():
    """Không có tài khoản demo nào giữ maintenance.manage — gọi thẳng service với User dựng tay
    để xác nhận đúng cơ chế lọc: có quyền mới thấy, không có quyền thì không, bất kể role gì."""
    db = SessionLocal()
    try:
        from app.models.maintenance import Incident
        from app.common import new_id, utcnow
        inc = Incident(incident_id=new_id(), incident_code=f"PT-INC-{new_id()[:6]}",
                       title="Sự cố test", status="open", reported_at=utcnow())
        db.add(inc)
        db.commit()

        with_perm = SecurityUser(username="maint_tester", role="operator", permissions={"maintenance.manage"})
        without_perm = SecurityUser(username="other_tester", role="operator", permissions={"batch.execute"})

        items_with = {i["key"]: i for i in svc.get_pending_tasks(db, with_perm)}
        items_without = {i["key"]: i for i in svc.get_pending_tasks(db, without_perm)}

        assert items_with["incident_open"]["count"] >= 1
        assert items_with["incident_open"]["view"] == "maint"
        assert items_with["incident_open"]["sub"] == "incidents"
        assert "incident_open" not in items_without
        assert "plan_open" not in items_without
    finally:
        db.close()
