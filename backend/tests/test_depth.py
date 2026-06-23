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


# ---------------- P3-1: ISA-88 procedural ----------------
def test_isa88_procedure_execution(client):
    h = _login(client, "quandoc", "123456")
    b2 = _batch_id(client, h, "B-2406-0002")
    st = client.get(f"/api/isa88/batch/{b2}", headers=h).json()
    assert st["phases_total"] > 0 and st["phases_done"] >= 2   # seed đã chạy 2 phase complete
    # tìm 1 phase idle → start → complete
    idle = None
    for u in st["unit_procedures"]:
        for o in u["operations"]:
            for p in o["phases"]:
                if p["state"] == "idle":
                    idle = (u["unit_procedure"], o["operation"], p["phase"])
                    break
            if idle:
                break
        if idle:
            break
    assert idle, "không có phase idle để test"
    r = client.post(f"/api/isa88/batch/{b2}/start", headers=h,
                    json={"up": idle[0], "op": idle[1], "phase": idle[2]})
    assert r.status_code == 200
    rid = r.json()["run_id"]
    done = client.post(f"/api/isa88/phase/{rid}/transition", headers=h, json={"target": "complete"})
    assert done.json()["state"] == "complete"
    # transition không hợp lệ: complete → running phải bị chặn
    bad = client.post(f"/api/isa88/phase/{rid}/transition", headers=h, json={"target": "running"})
    assert bad.status_code == 409


# ---------------- P3-2: Scheduling ----------------
def test_scheduler_auto_no_overlap(client):
    h = _login(client, "quandoc", "123456")
    r = client.post("/api/schedule/auto", headers=h, json={"days": 12})
    assert r.status_code == 200 and r.json()["placed"] >= 1
    board = client.get("/api/schedule", headers=h).json()
    assert any(board["lanes"][res] for res in board["resources"])
    conf = client.get("/api/schedule/conflicts", headers=h).json()
    assert conf["overlaps"] == []          # bộ lập lịch KHÔNG được tạo chồng lấn tài nguyên
    # WO-2406-006 sản lượng rất lớn → thiếu NVL theo BOM
    assert any(s["wo_code"] == "WO-2406-006" for s in conf["material_short"])


# ---------------- P3-4: WMS pallet/case + barcode ----------------
def test_wms_pallet_lifecycle(client):
    h = _login(client, "thukho", "123456")            # warehouse.receive + warehouse.issue
    locs = client.get("/api/wms/locations", headers=h).json()
    assert len(locs) >= 3
    r = client.post("/api/wms/pallets", headers=h,
                    json={"product": "BIA-LAGER", "lot_code": "PKG-2406-0001",
                          "case_count": 10, "units_per_case": 24})
    assert r.status_code == 201
    pid, pcode = r.json()["pallet_id"], r.json()["pallet_code"]
    pa = client.post(f"/api/wms/pallets/{pid}/putaway", headers=h, json={"loc_id": locs[0]["loc_id"]})
    assert pa.json()["status"] == "stored"
    # barcode pallet phân giải qua kiosk /api/scan
    sc = client.get("/api/scan", params={"code": pcode}, headers=h).json()
    assert sc["type"] == "pallet"
    # barcode case phân giải qua /api/wms/resolve
    pals = client.get("/api/wms/pallets", headers=h).json()
    case_code = next(p for p in pals if p["pallet_code"] == pcode)["cases"][0]["case_code"]
    rc = client.get("/api/wms/resolve", params={"code": case_code}, headers=h).json()
    assert rc["type"] == "case" and rc["pallet_code"] == pcode


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


# ---------------- Q1: recipe suspend/resume ----------------
def test_recipe_suspend_resume(client):
    h = _login(client, "kysu", "123456")              # recipe.approve
    rid = client.get("/api/recipes", headers=h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=h).json()
    vid = next(v["version_id"] for v in vers if v["state"] == "effective")
    # A: tạm ngưng KHÔNG nêu lý do → bị chặn
    assert client.post(f"/api/recipes/versions/{vid}/transition", headers=h,
                       json={"target": "suspended"}).status_code == 409
    # tạm ngưng kèm lý do → OK
    assert client.post(f"/api/recipes/versions/{vid}/transition", headers=h,
                       json={"target": "suspended", "reason": "Tạm ngưng để hiệu chỉnh men"}).json()["state"] == "suspended"
    # đang tạm ngưng → KHÔNG tạo được mẻ
    hq = _login(client, "quandoc", "123456")
    oid = client.get("/api/orders", headers=hq).json()[0]["order_id"]
    bad = client.post("/api/batches", headers=hq,
                      json={"order_id": oid, "recipe_version_id": vid, "planned_qty": 1000, "allow_shortage": True})
    assert bad.status_code == 409
    # kích hoạt lại (không cần lý do)
    assert client.post(f"/api/recipes/versions/{vid}/transition", headers=h,
                       json={"target": "effective"}).json()["state"] == "effective"


# ---------------- A: lý do bắt buộc khi tạm ngưng + ghi audit ----------------
def test_recipe_suspend_requires_reason_and_audits(client):
    h = _login(client, "kysu", "123456")
    rid = client.get("/api/recipes", headers=h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=h).json()
    vid = next(v["version_id"] for v in vers if v["state"] == "effective")
    # reason rỗng / chỉ khoảng trắng → chặn
    assert client.post(f"/api/recipes/versions/{vid}/transition", headers=h,
                       json={"target": "suspended", "reason": "   "}).status_code == 409
    # có lý do → OK + audit ghi lý do
    reason = "Phát hiện lệch độ đắng — review lại định mức hoa"
    assert client.post(f"/api/recipes/versions/{vid}/transition", headers=h,
                       json={"target": "suspended", "reason": reason}).status_code == 200
    ha = _login(client, "quandoc", "123456")
    audits = client.get("/api/audit", params={"entity_type": "recipe_version"}, headers=ha).json()
    rows = audits.get("entries", audits) if isinstance(audits, dict) else audits
    assert any(reason in (str(a.get("reason") or "") + str(a.get("after") or "")) for a in rows)
    # khôi phục để không ảnh hưởng test khác
    client.post(f"/api/recipes/versions/{vid}/transition", headers=h, json={"target": "effective"})


# ---------------- B: scheduler dùng danh mục tank master ----------------
def test_scheduler_uses_master_tanks(client):
    h = _login(client, "kysu", "123456")              # master.manage
    # danh mục có tank FV (kind=tank) từ seed
    lines = client.get("/api/lines", headers=h).json()
    tanks = [l for l in lines if l.get("kind") == "tank"]
    assert len(tanks) >= 4
    # thêm 1 tank mới rồi auto-schedule → board phải dùng được tài nguyên tank master
    r = client.post("/api/lines", headers=h,
                    json={"code": "FV-99", "name": "Tank test 99", "kind": "tank", "area": "len_men"})
    assert r.status_code == 201
    hq = _login(client, "quandoc", "123456")          # wo.dispatch
    auto = client.post("/api/schedule/auto", headers=hq, json={"days": 12})
    assert auto.status_code == 200
    # số tank trả về khớp danh mục (>= số tank active), và FV-99 nằm trong tài nguyên board
    board = client.get("/api/schedule", headers=hq).json()
    assert "FV-99" in board["resources"]


# ---------------- C: WMS summary tổng hợp ----------------
def test_wms_summary(client):
    h = _login(client, "thukho", "123456")
    sm = client.get("/api/wms/summary", headers=h).json()
    assert sm["locations"] >= 4
    assert sm["capacity_pallets"] >= sm["pallets_stored"]
    assert sm["pallets_total"] >= 3
    assert sm["cases"] >= 80            # 2 pallet stored × 40 case (pallet building cũng tính)
    assert sm["units"] >= sm["cases"]   # mỗi case ≥ 1 lon
    assert 0 <= sm["fill_pct"] <= 100
    # cần đăng nhập
    assert client.get("/api/wms/summary").status_code == 403


# ---------------- D: bao bì tuần hoàn (vỏ chai/két-gông/keg) ----------------
def test_packaging_declare_and_summary(client):
    h = _login(client, "thukho", "123456")
    data = client.get("/api/packaging", headers=h).json()
    assert set(["vo_chai", "ket_gong", "keg"]).issubset(set(data["categories"].keys()))
    assert len(data["types"]) >= 6
    # tổng hợp theo nhóm
    cats = {c["category"] for c in data["summary"]["by_category"]}
    assert {"vo_chai", "ket_gong", "keg"}.issubset(cats)


def test_packaging_create_requires_master_manage(client):
    # thủ kho KHÔNG có master.manage → không khai báo loại mới được
    h = _login(client, "thukho", "123456")
    bad = client.post("/api/packaging", headers=h,
                      json={"code": "VOCHAI-X", "name": "x", "category": "vo_chai"})
    assert bad.status_code == 403
    # kysu có master.manage → tạo được
    hk = _login(client, "kysu", "123456")
    ok = client.post("/api/packaging", headers=hk,
                     json={"code": "KEG-20", "name": "Keg inox 20L", "category": "keg",
                           "material": "steel", "volume_l": 20, "on_hand": 100, "in_circulation": 10})
    assert ok.status_code == 201
    # mã trùng → chặn
    dup = client.post("/api/packaging", headers=hk,
                      json={"code": "KEG-20", "name": "trùng", "category": "keg"})
    assert dup.status_code == 409
    # category sai → chặn
    badcat = client.post("/api/packaging", headers=hk,
                         json={"code": "ZZ-1", "name": "z", "category": "khong_hop_le"})
    assert badcat.status_code == 409


def test_packaging_move_flow(client):
    h = _login(client, "thukho", "123456")            # warehouse.issue
    types = client.get("/api/packaging", headers=h).json()["types"]
    keg = next(t for t in types if t["code"] == "KEG-30")
    pid = keg["pkg_id"]
    on0, circ0 = keg["on_hand"], keg["in_circulation"]
    # xuất (ra lưu hành): tồn giảm, lưu hành tăng
    r = client.post("/api/packaging/move", headers=h,
                    json={"pkg_id": pid, "kind": "xuat", "qty": 50, "ref": "PX-001"}).json()
    assert r["on_hand"] == on0 - 50 and r["in_circulation"] == circ0 + 50
    # thu hồi: lưu hành giảm, tồn tăng
    r2 = client.post("/api/packaging/move", headers=h,
                     json={"pkg_id": pid, "kind": "thu_hoi", "qty": 30}).json()
    assert r2["on_hand"] == on0 - 20 and r2["in_circulation"] == circ0 + 20
    # xuất quá tồn → chặn
    over = client.post("/api/packaging/move", headers=h,
                       json={"pkg_id": pid, "kind": "xuat", "qty": 9_999_999})
    assert over.status_code == 409
    # kiểm kê: đặt lại tồn
    r3 = client.post("/api/packaging/move", headers=h,
                     json={"pkg_id": pid, "kind": "kiem_ke", "qty": 123, "note": "kiểm kê quý"}).json()
    assert r3["on_hand"] == 123
    # kiểm kê về 0 → hợp lệ
    assert client.post("/api/packaging/move", headers=h,
                       json={"pkg_id": pid, "kind": "kiem_ke", "qty": 0}).json()["on_hand"] == 0
    # kiểm kê âm → bị chặn (không cho tồn kho âm); schema ge=0 trả 422
    neg = client.post("/api/packaging/move", headers=h,
                      json={"pkg_id": pid, "kind": "kiem_ke", "qty": -100})
    assert neg.status_code in (409, 422)
    # tồn kho không bị kéo âm
    after = client.get("/api/packaging", headers=h).json()["types"]
    assert next(t for t in after if t["pkg_id"] == pid)["on_hand"] >= 0
    # lịch sử có bản ghi
    hist = client.get("/api/packaging/moves", params={"pkg_id": pid}, headers=h).json()
    assert len(hist) >= 3
    # operator không có warehouse.issue → không ghi được
    no = _login(client, "vanhanh", "123456")
    assert client.post("/api/packaging/move", headers=no,
                       json={"pkg_id": pid, "kind": "nhap", "qty": 1}).status_code == 403


# ---------------- Q2: production line master ----------------
def test_line_master_and_oee(client):
    h = _login(client, "kysu", "123456")              # master.manage
    assert len(client.get("/api/lines", headers=h).json()) >= 2
    r = client.post("/api/lines", headers=h,
                    json={"code": "Line-9 (test)", "name": "Line test", "ideal_rate_per_min": 150})
    assert r.status_code == 201
    lid = r.json()["line_id"]
    assert client.post(f"/api/lines/{lid}/toggle", headers=h).json()["active"] is False
    act = client.get("/api/lines", params={"active_only": True}, headers=h).json()
    assert all(l["code"] != "Line-9 (test)" for l in act)
    # không có master.manage → không thêm được dây chuyền
    no = _login(client, "vanhanh", "123456")
    assert client.post("/api/lines", headers=no, json={"code": "X", "name": "x"}).status_code == 403
    # nhập OEE theo dây chuyền
    hq = _login(client, "quandoc", "123456")
    oe = client.post("/api/oee", headers=hq, json={"line": "Line-1 (chai)", "shift": "C",
                     "planned_time_min": 480, "downtime_min": 30, "ideal_rate_per_min": 300,
                     "total_count": 100000, "good_count": 98000})
    assert oe.status_code == 201 and oe.json()["oee"] > 0


# ---------------- Q3: QR label ----------------
def test_qr_label(client):
    h = _login(client, "thukho", "123456")
    r = client.get("/api/label/qr", params={"data": "PLT-2406-01"}, headers=h)
    assert r.status_code == 200 and "image/svg" in r.headers.get("content-type", "")
    assert "<svg" in r.text and ("<path" in r.text or "<rect" in r.text)
    assert client.get("/api/label/qr", params={"data": "X"}).status_code == 403   # cần đăng nhập


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
