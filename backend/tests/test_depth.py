"""Test 5 phân hệ chiều sâu + hardening (pytest + TestClient trên SQLite tạm).

Phủ: SPC, downtime/Pareto/MTBF, dispense FEFO + chặn vượt định mức, yield,
RBAC data-scoping (line + loại test QC), master-data perm, change-control diff,
chuỗi audit qua external event, auth bắt buộc cho AI, và rate-limit.
"""

import os
import tempfile

# Đặt DB tạm + tắt rate-limit TRƯỚC khi import app.
_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["MES_DATABASE_URL"] = f"sqlite:///{_TMP.name}"
os.environ["MES_DEV_HEADER_AUTH"] = "0"
os.environ["MES_RL_ENABLED"] = "0"

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


def _batch_id(client, h, code):
    bs = client.get("/api/batches", headers=h).json()
    return next(b["batch_id"] for b in bs if b["batch_code"] == code)


# ---------------- #7 Quality: SPC ----------------
def test_spc_control_chart(client):
    h = _login(client, "quandoc", "123456")
    spc = client.get("/api/qc/spc", params={"parameter": "Độ đường (°P)"}, headers=h).json()
    assert spc["n"] >= 20
    assert spc["ucl"] > spc["mean"] > spc["lcl"]
    assert spc["cp"] is not None and spc["cpk"] is not None
    # seed cố tình tạo chuỗi lệch lên cuối → phải có điểm vi phạm Western Electric
    assert spc["out_of_control"] >= 1


def test_capa_and_coa(client):
    h = _login(client, "quandoc", "123456")
    capas = client.get("/api/qc/capa", headers=h).json()
    assert len(capas) >= 1
    b1 = _batch_id(client, h, "B-2406-0001")
    coa = client.get(f"/api/qc/coa/{b1}", headers=h).json()
    assert coa["overall_verdict"] == "PASS"   # mẻ đạt + released


# ---------------- #8 OEE: downtime ----------------
def test_downtime_pareto_cumulative(client):
    h = _login(client, "quandoc", "123456")
    p = client.get("/api/downtime/pareto", headers=h).json()
    assert p["total_minutes"] > 0
    assert p["items"][-1]["cum_pct"] == 100.0   # tích lũy về đúng 100%


def test_mtbf_window_filter(client):
    h = _login(client, "quandoc", "123456")
    wide = client.get("/api/downtime/mtbf", params={"days": 3650}, headers=h).json()
    narrow = client.get("/api/downtime/mtbf", params={"days": 1}, headers=h).json()
    wide_f = sum(e["failures"] for e in wide["equipment"])
    narrow_f = sum(e["failures"] for e in narrow["equipment"])
    assert wide_f >= narrow_f   # cửa sổ hẹp ⊆ cửa sổ rộng


def test_downtime_negative_rejected(client):
    h = _login(client, "quandoc", "123456")
    r = client.post("/api/downtime", headers=h, json={
        "line": "L", "reason_group": "thiet_bi", "reason_code": "hong_co_khi", "minutes": -5})
    assert r.status_code == 409


# ---------------- #6 Material: dispense ----------------
def test_dispense_fefo_and_ceiling(client):
    h = _login(client, "vanhanh", "123456")          # operator scope Nấu A (B2 thuộc Nấu A)
    b2 = _batch_id(client, h, "B-2406-0002")
    ok = client.post(f"/api/dispense/{b2}", headers=h,
                     json={"lines": [{"material_code": "MALT-PILS", "quantity": 1000}]})
    assert ok.status_code == 200, ok.text
    assert ok.json()["lines"][0]["lot_code"]          # đã tự chọn lô FEFO
    # vượt trần định mức (1200*1.03=1236; đã cấp 1000, thêm 1000 → vượt) → 409
    over = client.post(f"/api/dispense/{b2}", headers=h,
                       json={"lines": [{"material_code": "MALT-PILS", "quantity": 1000}]})
    assert over.status_code == 409


# ---------------- #3 Recipe/BOM: yield + change-control ----------------
def test_yield_report(client):
    h = _login(client, "quandoc", "123456")
    b1 = _batch_id(client, h, "B-2406-0001")
    y = client.get(f"/api/batches/{b1}/yield", headers=h).json()
    assert y["overall_yield_pct"] and y["overall_yield_pct"] < 100
    assert any(s["expected_pct"] for s in y["steps"])   # snapshot có yield_steps


def test_recipe_change_diff(client):
    h = _login(client, "quandoc", "123456")
    changes = client.get("/api/recipes/changes", headers=h).json()
    assert len(changes) >= 1 and changes[0]["diff"].get("materials")


# ---------------- #10 RBAC data-scoping ----------------
def test_scope_line_filters_workorders(client):
    h = _login(client, "vanhanh", "123456")           # scope line = "Nấu A"
    board = client.get("/api/workorders", headers=h).json()
    assert board and all(w["line"] != "Nấu B" for w in board)


def test_scope_qc_blocks_unassigned_test(client):
    h = _login(client, "kcs", "123456")               # scope_qc = "Độ đường (°P),pH"
    b1 = _batch_id(client, _login(client, "admin", "admin123"), "B-2406-0001")
    bad = client.post("/api/quality/results", headers=h,
                      json={"scope_id": b1, "parameter": "CO2 (g/L)", "value": 5.2})
    assert bad.status_code == 403
    good = client.post("/api/quality/results", headers=h,
                       json={"scope_id": b1, "parameter": "pH", "value": 4.4,
                             "lower_limit": 4.2, "upper_limit": 4.6})
    assert good.status_code == 201


# ---------------- master-data + auth gaps ----------------
def test_master_create_requires_perm(client):
    no = _login(client, "vanhanh", "123456")          # không có master.manage
    assert client.post("/api/products", headers=no,
                       json={"code": "BIA-Z", "name": "z"}).status_code == 403
    yes = _login(client, "kysu", "123456")            # có master.manage
    assert client.post("/api/products", headers=yes,
                       json={"code": "BIA-IPA-T", "name": "IPA test"}).status_code == 201


def test_batch_read_requires_auth(client):
    assert client.get("/api/batches").status_code == 403           # list
    assert client.get("/api/quality/results").status_code == 403   # results
    assert client.post("/api/ai/chat", json={"message": "hi"}).status_code == 403


# ---------------- audit chain qua external event ----------------
def test_external_event_keeps_chain(client):
    h = _login(client, "admin", "admin123")
    before = client.get("/api/audit/verify-chain", headers=h).json()
    assert before["intact"] is True
    r = client.post("/api/v1/events", headers={"X-API-Key": "mes_edge_writer_key_0001"},
                    json={"entity_type": "erp", "entity_id": "PO-T", "action": "erp_confirm"})
    assert r.status_code == 200 and r.json()["accepted"]
    after = client.get("/api/audit/verify-chain", headers=h).json()
    assert after["intact"] is True and after["count"] == before["count"] + 1


# ---------------- P2: ConversationMemory ----------------
def test_ai_conversation_memory(client):
    h = _login(client, "quandoc", "123456")
    # lượt 1 → tạo hội thoại mới (engine luật offline, không tốn LLM)
    r1 = client.post("/api/ai/chat", headers=h, json={"message": "tồn kho thế nào?"}).json()
    cid = r1["conversation_id"]
    assert cid and r1.get("answer")
    # lượt 2 → nối vào cùng hội thoại
    r2 = client.post("/api/ai/chat", headers=h, json={"message": "còn OEE?", "conversation_id": cid}).json()
    assert r2["conversation_id"] == cid
    # lịch sử lưu server: 4 message (2 user + 2 assistant)
    msgs = client.get(f"/api/ai/conversations/{cid}", headers=h).json()["messages"]
    assert len(msgs) == 4 and msgs[0]["role"] == "user"
    # xuất hiện trong danh sách hội thoại của user
    convs = client.get("/api/ai/conversations", headers=h).json()
    assert any(c["conv_id"] == cid for c in convs)
    # cô lập theo người dùng: user khác không xem được
    h2 = _login(client, "kcs", "123456")
    assert client.get(f"/api/ai/conversations/{cid}", headers=h2).status_code == 403


# ---------------- P2: SSE streaming chat ----------------
def test_ai_chat_stream(client):
    import json as _j
    h = _login(client, "kysu", "123456")
    r = client.post("/api/ai/chat/stream", headers=h, json={"message": "tồn kho thế nào?"})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")
    events = [_j.loads(ln[5:].strip()) for ln in r.text.splitlines() if ln.startswith("data:")]
    types = {e["type"] for e in events}
    assert {"meta", "delta", "done"} <= types          # đủ chuỗi sự kiện SSE
    done = next(e for e in events if e["type"] == "done")
    full = "".join(e["text"] for e in events if e["type"] == "delta")
    assert full.strip() and done["answer"].strip()
    # đã lưu vào ConversationMemory (2 message)
    cid = done["conversation_id"]
    msgs = client.get(f"/api/ai/conversations/{cid}", headers=h).json()["messages"]
    assert len(msgs) == 2 and msgs[1]["role"] == "assistant"


# ---------------- P2: worker job queue ----------------
def test_job_queue_ai_report(client):
    import time as _t
    h = _login(client, "quandoc", "123456")
    sub = client.post("/api/jobs", headers=h, json={"kind": "ai_report"})
    assert sub.status_code == 201
    jid = sub.json()["job_id"]
    # poll tới khi worker (thread) hoàn thành
    status, result = None, None
    for _ in range(40):
        j = client.get(f"/api/jobs/{jid}", headers=h).json()
        status = j["status"]
        if status in ("done", "error"):
            result = j["result"]
            break
        _t.sleep(0.1)
    assert status == "done", f"job không hoàn thành: {status}"
    assert result and "headline" in result and "summary" in result
    # cô lập theo user
    h2 = _login(client, "kcs", "123456")
    assert client.get(f"/api/jobs/{jid}", headers=h2).status_code == 403


def test_job_queue_unknown_kind(client):
    h = _login(client, "quandoc", "123456")
    assert client.post("/api/jobs", headers=h, json={"kind": "khong_ton_tai"}).status_code == 409


# ---------------- rate-limit (bật riêng để test) ----------------
def test_rate_limit_login(client, monkeypatch):
    from app import ratelimit
    monkeypatch.setattr(ratelimit, "RL_ENABLED", True)
    monkeypatch.setattr(ratelimit, "RL_LOGIN_PER_MIN", 3)
    ratelimit._hits.clear()
    codes = [client.post("/api/auth/login", json={"username": "x", "password": "y"}).status_code
             for _ in range(5)]
    assert 429 in codes            # vượt ngưỡng → bị chặn
    ratelimit._hits.clear()
