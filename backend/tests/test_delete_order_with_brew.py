"""PROBE: xóa Lệnh SX (ERP) khi còn mã nấu (BrewRecord) — chưa có mẻ (BatchExecution).
FK mới brew_record.production_order_id → production_order: delete_order chỉ chặn BatchExecution
nên có thể lọt guard rồi vỡ FK 547 trên MSSQL."""
import os, tempfile
_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ.setdefault("MES_DATABASE_URL", f"sqlite:///{_TMP.name}")
os.environ["MES_DEV_HEADER_AUTH"] = "0"; os.environ["MES_RL_ENABLED"] = "0"; os.environ["MES_ADMIN_PASSWORD"] = "AdminTest123"
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import seed as seed_mod

@pytest.fixture(scope="module", autouse=True)
def _s():
    seed_mod.seed(); yield

@pytest.fixture(scope="module")
def client(): return TestClient(app)

def _login(c,u,p):
    r=c.post("/api/auth/login",json={"username":u,"password":p}); assert r.status_code==200,r.text
    return {"Authorization":"Bearer "+r.json()["token"]}

@pytest.fixture(scope="module")
def admin_h(client): return _login(client,"admin","AdminTest123")

def test_delete_order_with_brew(client, admin_h):
    prods = client.get("/api/products", headers=admin_h).json()
    pid = next(p["product_id"] for p in prods if p["code"]=="BIA-LAGER")
    o = client.post("/api/orders", headers=admin_h, json={
        "order_code":"PO-PROBE-DEL","product_id":pid,"planned_qty":10000,"uom":"L"})
    assert o.status_code==201,o.text
    oid=o.json()["order_id"]
    b = client.post("/api/brewing/brews", headers=admin_h, json={
        "brew_code":"BR-PROBE-DEL","wort_type":"Dịch test","production_order_id":oid})
    assert b.status_code==201,b.text
    brew_id = b.json()["brew_id"]
    # order giờ in_progress, có brew_record → xóa order phải BỊ CHẶN 409 (không 500 FK)
    d = client.delete(f"/api/orders/{oid}", headers=admin_h)
    assert d.status_code == 409, f"phải chặn 409, gặp {d.status_code}: {d.text}"
    # xóa mã nấu trước (order tự lùi released) → giờ xóa order OK
    assert client.delete(f"/api/brewing/brews/{brew_id}", headers=admin_h).status_code in (200, 204)
    d2 = client.delete(f"/api/orders/{oid}", headers=admin_h)
    assert d2.status_code == 204, f"xóa order sau khi hết brew phải 204, gặp {d2.status_code}: {d2.text}"
