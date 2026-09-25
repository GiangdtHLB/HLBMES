"""Sổ chi tiết vật tư (material_transaction_detail) không được hiện lại cặp "điều chuyển đi rồi
hoàn tác ngay sau đó" (net = 0, tồn kho chưa hề thật sự tăng lên/mất đi lâu dài) — chỉ hiện giao
dịch làm tồn kho THẬT SỰ thay đổi (yêu cầu người dùng 2026-09-15: "Sổ chi tiết vật tư không cần
hiện lại hoàn kho, chỉ cần hiện khi kho tăng lên, hoặc mất đi thôi, các thao tác liên quan đến
hoàn tác không cần hiển thị"). Cũng phát hiện lúc kiểm tra dữ liệu thật: vật tư 2NC14 có "Xuất
theo đề nghị" rồi "Hoàn tác" 13 lần liên tiếp làm Sổ chi tiết dài dằng dặc, gây hiểu lầm là có
nhiều giao dịch thật."""

import os
import tempfile
from datetime import timedelta

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["MES_DATABASE_URL"] = f"sqlite:///{_TMP.name}"
os.environ["MES_DEV_HEADER_AUTH"] = "0"
os.environ["MES_RL_ENABLED"] = "0"
os.environ["MES_ADMIN_PASSWORD"] = "AdminTest123"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import seed as seed_mod
from app.common import utcnow


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


def test_transfer_then_undo_disappears_from_material_detail(client, admin_h):
    mat = client.post("/api/materials", headers=admin_h,
                      json={"code": "MTD-REV01", "name": "Vật tư MTD reversed", "uom": "kg"})
    assert mat.status_code == 201, mat.text
    material_id = mat.json()["material_id"]

    date_from = (utcnow() - timedelta(days=1)).isoformat()

    recv = client.post("/api/warehouse/receive", headers=admin_h, json={
        "material_id": material_id, "quantity": 100, "uom": "kg", "location": "Kho công ty"})
    assert recv.status_code == 200, recv.text
    lot_id = recv.json()["lot_id"]

    out = client.post("/api/warehouse/transfer", headers=admin_h, json={
        "lot_id": lot_id, "quantity": 20, "location_to": "Kho phân xưởng",
        "reason": "Xuất theo đề nghị DN-TEST (dòng 1, duyệt cả phiếu)"})
    assert out.status_code == 200, out.text
    moved_lot_id = out.json()["lot_id"]

    back = client.post("/api/warehouse/transfer", headers=admin_h, json={
        "lot_id": moved_lot_id, "quantity": 20, "location_to": "Kho công ty",
        "reason": "Hoàn tác xuất theo đề nghị DN-TEST (dòng 1)"})
    assert back.status_code == 200, back.text

    date_to = utcnow().isoformat()

    # Lọc theo Kho phân xưởng: cặp chuyển-đi-rồi-hoàn-tác phải BIẾN MẤT hoàn toàn (không hiện cả
    # "Xuất theo đề nghị" lẫn "Hoàn tác") — tồn kho phân xưởng thực chất chưa hề tăng lên.
    detail = client.get("/api/warehouse/report/material-detail", headers=admin_h, params={
        "material_id": material_id, "date_from": date_from, "date_to": date_to,
        "location": "Kho phân xưởng"})
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["rows"] == []
    assert body["opening_balance"] == 0.0
    assert body["closing_balance"] == 0.0

    # Lọc theo Kho công ty: vẫn chỉ thấy "Nhập kho" gốc (100kg) — cặp chuyển đi/hoàn tác cũng ẩn
    # nốt ở phía kho công ty (lô rời đi rồi quay lại đúng chỗ, không đổi gì lâu dài).
    detail_ct = client.get("/api/warehouse/report/material-detail", headers=admin_h, params={
        "material_id": material_id, "date_from": date_from, "date_to": date_to,
        "location": "Kho công ty"})
    assert detail_ct.status_code == 200, detail_ct.text
    body_ct = detail_ct.json()
    types = [r["type"] for r in body_ct["rows"]]
    assert types == ["receipt"]
    assert body_ct["closing_balance"] == 100.0


def test_real_unreversed_transfer_still_shows(client, admin_h):
    """Điều chuyển KHÔNG bị hoàn tác vẫn phải hiện bình thường — chỉ ẩn đúng cặp đã hoàn tác,
    không ẩn nhầm điều chuyển thật."""
    mat = client.post("/api/materials", headers=admin_h,
                      json={"code": "MTD-REAL01", "name": "Vật tư MTD real transfer", "uom": "kg"})
    assert mat.status_code == 201, mat.text
    material_id = mat.json()["material_id"]

    date_from = (utcnow() - timedelta(days=1)).isoformat()

    recv = client.post("/api/warehouse/receive", headers=admin_h, json={
        "material_id": material_id, "quantity": 50, "uom": "kg", "location": "Kho công ty"})
    assert recv.status_code == 200, recv.text
    lot_id = recv.json()["lot_id"]

    out = client.post("/api/warehouse/transfer", headers=admin_h, json={
        "lot_id": lot_id, "quantity": 15, "location_to": "Kho phân xưởng",
        "reason": "Xuất theo đề nghị DN-TEST-REAL (dòng 1)"})
    assert out.status_code == 200, out.text

    date_to = utcnow().isoformat()

    detail = client.get("/api/warehouse/report/material-detail", headers=admin_h, params={
        "material_id": material_id, "date_from": date_from, "date_to": date_to,
        "location": "Kho phân xưởng"})
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert len(body["rows"]) == 1
    assert body["rows"][0]["type"] == "transfer"
    assert body["rows"][0]["quantity"] == 15.0
    assert body["closing_balance"] == 15.0


def test_reversed_pair_matched_by_request_code_not_just_quantity(client, admin_h):
    """Bug thực tế 2026-09-24: 2 phiếu KHÁC NHAU cùng rút CÙNG SỐ LƯỢNG từ CÙNG 1 lô (VD "duyệt
    cả phiếu" rút cùng lúc 45kg cho nhiều phiếu) — chỉ 1 phiếu được hoàn tác, phiếu còn lại vẫn
    còn thật (chưa hoàn tác). Ghép cặp CHỈ theo lot_code + số lượng ngược dấu (không xét đúng mã
    phiếu trong `reason`) dễ ghép nhầm "Hoàn tác của phiếu A" với "Xuất của phiếu B" — ẩn nhầm
    đúng phiếu còn thật (B), để lộ đúng phiếu đã hoàn tác (A), khiến người xem hiểu lầm ngược lại
    hoàn toàn (thấy phiếu ĐÃ hoàn tác báo như CHƯA hoàn tác, phiếu CHƯA hoàn tác lại biến mất)."""
    mat = client.post("/api/materials", headers=admin_h,
                      json={"code": "MTD-DUAL01", "name": "Vật tư MTD 2 phiếu cùng SL", "uom": "kg"})
    assert mat.status_code == 201, mat.text
    material_id = mat.json()["material_id"]

    date_from = (utcnow() - timedelta(days=1)).isoformat()

    recv = client.post("/api/warehouse/receive", headers=admin_h, json={
        "material_id": material_id, "quantity": 100, "uom": "kg", "location": "Kho công ty"})
    assert recv.status_code == 200, recv.text
    lot_id = recv.json()["lot_id"]

    # Phiếu A (AAAA1) xuất 45kg — SAU NÀY sẽ hoàn tác.
    outA = client.post("/api/warehouse/transfer", headers=admin_h, json={
        "lot_id": lot_id, "quantity": 45, "location_to": "Kho phân xưởng",
        "reason": "Xuất theo đề nghị DN-20260917-AAAA1"})
    assert outA.status_code == 200, outA.text
    lot_at_px = outA.json()["lot_id"]

    # Phiếu B (BBBB1) xuất CÙNG 45kg từ CÙNG lô nguồn — KHÔNG BAO GIỜ hoàn tác (vẫn còn thật).
    outB = client.post("/api/warehouse/transfer", headers=admin_h, json={
        "lot_id": lot_id, "quantity": 45, "location_to": "Kho phân xưởng",
        "reason": "Xuất theo đề nghị DN-20260917-BBBB1"})
    assert outB.status_code == 200, outB.text

    # Chỉ hoàn tác phiếu A.
    backA = client.post("/api/warehouse/transfer", headers=admin_h, json={
        "lot_id": lot_at_px, "quantity": 45, "location_to": "Kho công ty",
        "reason": "Hoàn tác xuất theo đề nghị DN-20260917-AAAA1 (dòng 1)"})
    assert backA.status_code == 200, backA.text

    date_to = utcnow().isoformat()

    detail = client.get("/api/warehouse/report/material-detail", headers=admin_h, params={
        "material_id": material_id, "date_from": date_from, "date_to": date_to,
        "location": "Kho công ty"})
    assert detail.status_code == 200, detail.text
    reasons = [r["reason"] for r in detail.json()["rows"]]
    # Phiếu B (chưa hoàn tác) PHẢI còn hiện — đây chính là điều bug làm sai (ẩn nhầm B).
    assert any("BBBB1" in (r or "") for r in reasons), reasons
    # Phiếu A (đã hoàn tác) và dòng "Hoàn tác" của nó PHẢI biến mất hoàn toàn.
    assert not any("AAAA1" in (r or "") for r in reasons), reasons
