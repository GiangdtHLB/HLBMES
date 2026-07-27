"""Smoke test "đường GHI" cho lô lớn (190.000 vỉ) — bắt buộc theo docs/DEPLOY-CONTRACT.md
trước khi merge thay đổi kho thành phẩm (xem docs/WMS-LOT-LEVEL-REDESIGN.md §7): seed 1 lô
lớn -> duyệt chiết (phải sinh ĐÚNG 1 dòng trong vài giây — đây chính là bug gốc: trước đây
sinh 1 dòng/vỉ, ca_total=190.000 tạo ~190.000 INSERT row-by-row, qua mạng tới SQL Server mất
~1 giờ, Cloudflare cắt ở 100s -> nút Duyệt "treo") -> xuất một phần -> phân rã một phần ->
điều chuyển một phần -> xuất tự do một phần -> hoàn tác từng thao tác -> kiểm số lượng khớp
tuyệt đối và không phát sinh dòng thừa (không quay lại mô hình 1 dòng/vỉ)."""

import os
import tempfile
import time

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["MES_DATABASE_URL"] = f"sqlite:///{_TMP.name}"
os.environ["MES_DEV_HEADER_AUTH"] = "0"
os.environ["MES_RL_ENABLED"] = "0"
os.environ["MES_ADMIN_PASSWORD"] = "AdminTest123"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import seed as seed_mod

CA_TOTAL = 190_000       # vỉ — quy mô thật đã gây treo nút Duyệt trên SQL Server (CH-47773)
PACK_SIZE = 24
LON_TOTAL = CA_TOTAL * PACK_SIZE  # tổng SL nhỏ (lon) của dòng lô duy nhất


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
def kcs_h(client):
    return _login(client, "kcs", "123456")


def _declare_pending(client, headers, stage, scope_type, scope_id):
    status = client.get(f"/api/brewing/qc-status?stage={stage}&scope_type={scope_type}&scope_id={scope_id}",
                        headers=headers).json()
    for p in status["required"]:
        if p["code"] in status["pending"]:
            lsl = p["lsl"] if p["lsl"] is not None else 0
            usl = p["usl"] if p["usl"] is not None else lsl + 10
            r = client.post("/api/brewing/qc-results", headers=headers,
                            json={"stage": stage, "scope_type": scope_type, "scope_id": scope_id,
                                  "parameter": p["code"], "value": (lsl + usl) / 2,
                                  "lower_limit": lsl, "upper_limit": usl})
            assert r.status_code == 201, r.text


def _lot_qty(client, admin_h, lot_code, status=None, unit_type=None):
    """Tổng quantity của lô — LOẠI TRỪ status="decomposed": dòng vỉ nguồn sau khi phân rã
    được GIỮ LẠI (không xóa) để truy vết genealogy/audit, nhưng quantity của nó đã được "nhân
    bản" sang dòng lon mới — cộng dồn cả 2 sẽ đếm trùng, không còn phản ánh tồn kho thật."""
    units = client.get("/api/wms/units", headers=admin_h, params={"limit": 5000}).json()
    return sum(u["quantity"] for u in units
              if u["lot_code"] == lot_code and u["status"] != "decomposed"
              and (status is None or u["status"] == status)
              and (unit_type is None or u["unit_type"] == unit_type))


def test_190k_lot_write_path_smoke(client, admin_h, vanhanh_h, kcs_h):
    fp = client.post("/api/finished-products", headers=admin_h,
                     json={"code": "SKU-SMOKE190K", "name": "SKU smoke 190k", "uom": "lon",
                           "unit_type": "vi", "pack_size": PACK_SIZE})
    assert fp.status_code == 201, fp.text
    fp_id = fp.json()["finished_product_id"]

    bottle_code = "CH-SMOKE190K"
    b = client.post("/api/brewing/bottles", headers=vanhanh_h,
                    json={"bottle_code": bottle_code, "beer_type": "Bia smoke test",
                          "finished_product_id": fp_id})
    assert b.status_code == 201, b.text
    bottle_id = b.json()["bottle_id"]

    fin = client.post(f"/api/brewing/bottles/{bottle_id}/finish", headers=vanhanh_h,
                      json={"ca1": CA_TOTAL})
    assert fin.status_code == 200, fin.text
    _declare_pending(client, admin_h, "thanh_pham", "bottle", f"{bottle_code}__thanh_pham")

    t0 = time.perf_counter()
    # Duyệt nhập kho thành phẩm nay thuộc quyền Giám đốc/Phó GĐ Sản xuất (production.release_to_wms),
    # tách khỏi quality.release của KCS — dùng admin_h (bypass mọi permission) thay vì kcs_h ở đây.
    approve = client.post(f"/api/brewing/bottles/{bottle_id}/approve", headers=admin_h)
    elapsed = time.perf_counter() - t0
    assert approve.status_code == 200, approve.text
    assert elapsed < 5, (f"Duyệt chiết lô {CA_TOTAL} vỉ mất {elapsed:.2f}s — phải O(1) theo quy mô lô "
                        "(1 INSERT duy nhất), không phải O(n) như mô hình 1 dòng/vỉ cũ")

    body = approve.json()
    assert body["count"] == CA_TOTAL

    all_units = client.get("/api/wms/units", headers=admin_h, params={"limit": 5000}).json()
    created_unit = next(u for u in all_units if u["unit_code"] == body["unit_codes"][0])
    lot_code = created_unit["lot_code"]  # tự sinh (lot_no auto-gen ở add_bottle), không đoán trước
    lot_units = [u for u in all_units if u["lot_code"] == lot_code]
    assert len(lot_units) == 1, "Duyệt chiết phải sinh ĐÚNG 1 dòng bất kể quy mô lô lớn cỡ nào"
    assert lot_units[0]["quantity"] == LON_TOTAL

    # ---- Xuất MỘT PHẦN (5.000/190.000 vỉ) ----
    ship_to = client.post("/api/wms/ship-to", headers=admin_h,
                          json={"code": "SMOKE-ST", "name": "NPP smoke test"})
    assert ship_to.status_code == 201, ship_to.text
    ship = client.post("/api/wms/shipments", headers=admin_h,
                       json={"ship_to_id": ship_to.json()["ship_to_id"],
                             "lines": [{"product_name": "SKU-SMOKE190K", "lot_code": lot_code,
                                       "unit_type": "vi", "quantity": 5_000}]})
    assert ship.status_code == 201, ship.text

    # ---- Phân rã MỘT PHẦN (2.000/185.000 vỉ còn lại) ----
    decompose = client.post("/api/wms/units/decompose-batch", headers=admin_h,
                            json={"product_name": "SKU-SMOKE190K", "lot_code": lot_code, "count": 2_000})
    assert decompose.status_code == 201, decompose.text
    assert decompose.json()["vi_decomposed"] == 2_000
    decompose_audit_id = decompose.json()["audit_id"]

    # ---- Điều chuyển MỘT PHẦN (3.000/183.000 vỉ còn lại, chưa có vị trí) ----
    loc = client.post("/api/wms/locations", headers=admin_h,
                      json={"code": "SMOKE-LOC", "name": "Vị trí smoke", "zone": "test",
                            "kind": "bin", "capacity": 1_000_000})
    assert loc.status_code == 201, loc.text
    relocate = client.post("/api/wms/units/relocate-batch", headers=admin_h,
                           json={"product_name": "SKU-SMOKE190K", "lot_code": lot_code, "unit_type": "vi",
                                 "from_loc_id": None, "to_loc_id": loc.json()["loc_id"], "count": 3_000})
    assert relocate.status_code == 200, relocate.text
    assert relocate.json()["moved"] == 3_000

    # ---- Xuất tự do MỘT PHẦN (1.000/180.000 vỉ còn lại) ----
    free_issue = client.post("/api/wms/units/free-issue", headers=admin_h,
                             json={"product_name": "SKU-SMOKE190K", "lot_code": lot_code, "unit_type": "vi",
                                   "count": 1_000, "reason": "Smoke test hủy hàng"})
    assert free_issue.status_code == 201, free_issue.text
    assert free_issue.json()["issued"] == 1_000
    free_issue_audit_id = free_issue.json()["audit_id"]

    # ---- Tổng SL toàn lô (mọi trạng thái/loại) luôn = SL gốc — không mất/thừa lon do tách dòng ----
    assert _lot_qty(client, admin_h, lot_code) == LON_TOTAL

    # ---- Hoàn tác xuất tự do + phân rã (thứ tự ngược) ----
    undo_free = client.post(f"/api/wms/units/free-issue/{free_issue_audit_id}/undo", headers=admin_h)
    assert undo_free.status_code == 200, undo_free.text
    assert undo_free.json() == {"restored": 1_000}

    undo_decompose = client.post(f"/api/wms/units/decompose-batch/{decompose_audit_id}/undo", headers=admin_h)
    assert undo_decompose.status_code == 200, undo_decompose.text
    assert undo_decompose.json()["vi_restored"] == 2_000

    # ---- Sau hoàn tác: vỉ "stored" phải về đúng (190.000-5.000) vỉ — chỉ thiếu đúng phần đã
    # XUẤT THẬT qua shipment (không có undo), điều chuyển không tiêu thụ nên không ảnh hưởng ----
    stored_vi_qty = _lot_qty(client, admin_h, lot_code, status="stored", unit_type="vi")
    assert stored_vi_qty == (CA_TOTAL - 5_000) * PACK_SIZE

    assert _lot_qty(client, admin_h, lot_code) == LON_TOTAL, "Tổng SL toàn lô vẫn phải khớp tuyệt đối sau hoàn tác"

    # ---- Không đẻ dòng thừa: 1 lô 190.000 vỉ chỉ nên sinh vài dòng do tách một phần
    # (xuất/phân rã/điều chuyển/xuất tự do), tuyệt đối không phải hàng trăm nghìn dòng ----
    final_lot_units = [u for u in client.get("/api/wms/units", headers=admin_h, params={"limit": 5000}).json()
                       if u["lot_code"] == lot_code]
    assert len(final_lot_units) < 20, (
        f"Lô 190.000 vỉ chỉ nên sinh vài dòng (tách/điều chuyển/xuất một phần), phát hiện "
        f"{len(final_lot_units)} dòng — nghi ngờ quay lại mô hình 1 dòng/vỉ (scale bomb cũ)")
