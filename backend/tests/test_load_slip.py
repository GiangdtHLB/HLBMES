"""Test nhập "Lệnh đóng hàng" (Excel, sheet HL/ĐM) → tách thành Biên bản bàn giao hàng hóa
theo xe (LoadSlip/LoadSlipLine):
1) Gộp đúng theo SỐ XE (kể cả dòng tiếp theo bỏ trống SỐ XE — kế thừa xe ngay trên).
2) Dòng "LON ... KM" (khuyến mại rời, chưa đủ 1 vỉ) tách thành dòng riêng is_promo=True,
   ĐVT "Lon" — không cộng gộp vào dòng "Vỉ" chính.
3) Dừng đúng tại mốc "TỔNG KEG" — không lấy nhầm dòng tổng/ghi chú/chữ ký ở cuối sheet.
4) CRUD qua API: import (multipart), list, get, update header (Bên giao/Bên nhận), delete."""

import io
import os
import tempfile

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["MES_DATABASE_URL"] = f"sqlite:///{_TMP.name}"
os.environ["MES_DEV_HEADER_AUTH"] = "0"
os.environ["MES_RL_ENABLED"] = "0"
os.environ["MES_ADMIN_PASSWORD"] = "AdminTest123"

import openpyxl
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


HEADERS = ["SỐ XE", "TÊN LX", "TỔ LX", "TỔ NPP/NVBH", "NPP VÀ NVBH", "GHI CHÚ", "SỐ QĐ KM",
          "Bia hơi 30L", "PL", "Vỉ Legend ", "LON Legend (Lon tết) KM"]


def _build_workbook(sheet_name="HL", shift="Ca 2", date_text="Ngày 5 tháng 3 năm 2026"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws["A1"] = f"LỆNH ĐÓNG HÀNG {sheet_name}"
    ws["A2"] = f"{shift}  -  {date_text}"
    for c, h in enumerate(HEADERS, start=1):
        ws.cell(row=6, column=c, value=h)
    # dòng rác ngay dưới header (giống file thật) — SỐ XE để trống, không được lấy nhầm.
    ws.cell(row=7, column=2, value=0)
    # Xe 11111: 1 dòng chính (Vỉ Legend=10) + 1 dòng tiếp (bỏ trống SỐ XE) có KM rời=3.
    ws.cell(row=8, column=1, value="11111")
    ws.cell(row=8, column=2, value="Tài xế A")
    ws.cell(row=8, column=5, value="NPP1")
    ws.cell(row=8, column=10, value=10)  # Vỉ Legend
    ws.cell(row=9, column=5, value="NPP1")
    ws.cell(row=9, column=7, value="100")  # SỐ QĐ KM
    ws.cell(row=9, column=11, value=3)  # LON Legend (Lon tết) KM
    # Xe 22222: 1 dòng, Bia hơi 30L=5.
    ws.cell(row=10, column=1, value="22222")
    ws.cell(row=10, column=2, value="Tài xế B")
    ws.cell(row=10, column=5, value="NPP2")
    ws.cell(row=10, column=8, value=5)  # Bia hơi 30L
    # Mốc dừng + rác phía sau — không được lấy vào danh sách xe.
    ws.cell(row=11, column=1, value="TỔNG KEG")
    ws.cell(row=11, column=8, value=15)
    ws.cell(row=12, column=1, value="99999")  # nếu parser không dừng đúng sẽ lẫn xe giả này
    ws.cell(row=12, column=2, value="Không nên xuất hiện")
    ws.cell(row=12, column=10, value=999)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


def _import(client, admin_h, content, filename="lenh-dong-hang.xlsx"):
    r = client.post("/api/wms/load-slips/import", headers=admin_h,
                    files={"file": (filename, content,
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 201, r.text
    return r.json()


def test_import_groups_by_vehicle_and_splits_promo_line(client, admin_h):
    content = _build_workbook()
    result = _import(client, admin_h, content)
    assert len(result["HL"]) == 2  # đúng 2 xe, không lẫn xe "99999" sau mốc TỔNG KEG
    assert result.get("ĐM", []) == []

    by_plate = {v["vehicle_plate"]: v for v in result["HL"]}
    assert by_plate["11111"]["lines"] == 2
    assert by_plate["22222"]["lines"] == 1

    slip = client.get(f"/api/wms/load-slips/{by_plate['11111']['load_slip_id']}", headers=admin_h).json()
    assert slip["driver_name"] == "Tài xế A"
    assert slip["routes"] == "NPP1"  # NPP lặp lại ở dòng tiếp theo không bị nhân đôi
    lines = {l["product_name"].strip(): l for l in slip["lines"]}
    assert lines["Vỉ Legend"]["quantity"] == 10
    assert lines["Vỉ Legend"]["uom"] == "Vỉ"
    assert lines["Vỉ Legend"]["is_promo"] is False
    promo = lines["LON Legend (Lon tết) KM"]
    assert promo["quantity"] == 3
    assert promo["uom"] == "Lon"
    assert promo["is_promo"] is True
    assert "100" in (promo["note"] or "")

    slip2 = client.get(f"/api/wms/load-slips/{by_plate['22222']['load_slip_id']}", headers=admin_h).json()
    assert slip2["lines"][0]["product_name"].strip() == "Bia hơi 30L"
    assert slip2["lines"][0]["uom"] == "Lít"


def test_slip_code_format_and_year(client, admin_h):
    content = _build_workbook(date_text="Ngày 5 tháng 3 năm 2026")
    result = _import(client, admin_h, content)
    for v in result["HL"]:
        assert v["slip_code"].endswith("/2026/BBBG-BHL")


def test_list_update_header_and_delete(client, admin_h):
    content = _build_workbook()
    result = _import(client, admin_h, content)
    load_slip_id = result["HL"][0]["load_slip_id"]

    listed = client.get("/api/wms/load-slips?sheet_type=HL", headers=admin_h).json()
    assert any(s["load_slip_id"] == load_slip_id for s in listed)

    updated = client.put(f"/api/wms/load-slips/{load_slip_id}", headers=admin_h, json={
        "issuer_name": "Nguyễn Văn Tùng", "issuer_title": "Thủ kho",
        "recipient_title": "Lái xe",
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["issuer_name"] == "Nguyễn Văn Tùng"
    assert updated.json()["recipient_title"] == "Lái xe"
    assert updated.json()["recipient_name"]  # vẫn giữ giá trị mặc định (tên lái xe) đã có sẵn

    deleted = client.delete(f"/api/wms/load-slips/{load_slip_id}", headers=admin_h)
    assert deleted.status_code == 204, deleted.text
    missing = client.get(f"/api/wms/load-slips/{load_slip_id}", headers=admin_h)
    assert missing.status_code == 404


def test_import_requires_permission(client, admin_h):
    thukho_h = _login(client, "thukho", "123456")
    content = _build_workbook()
    r = client.post("/api/wms/load-slips/import", headers=thukho_h,
                    files={"file": ("x.xlsx", content,
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 201, r.text  # thukho có warehouse.issue
