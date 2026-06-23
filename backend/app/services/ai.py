"""Lớp AI vận hành + trợ lý chat.

- operational_insights(): engine tư vấn — quét dữ liệu, sinh cảnh báo/đề xuất có
  mức ưu tiên. KHÔNG tự hành động (tài liệu §1.1: human-in-the-loop).
- chat(): trợ lý hội thoại. Nếu cấu hình ANTHROPIC_API_KEY + cài 'anthropic' →
  dùng Claude (claude-opus-4-8, adaptive thinking, tool-use). Nếu không → engine luật.
"""

import re

from sqlalchemy.orm import Session

from ..config import LLM_API_KEY, LLM_ENABLED, LLM_MODEL
from ..logging_config import get_logger, log_ai_call
from . import ai_tools

log = get_logger("mes.ai")

SYSTEM_PROMPT = (
    "Bạn là trợ lý vận hành cho hệ thống MES nhà máy bia. Trả lời ngắn gọn, "
    "chính xác bằng tiếng Việt, dựa trên dữ liệu lấy từ các tool MES. "
    "Bạn CHỈ tư vấn: không bao giờ ra lệnh điều khiển thiết bị, đổi setpoint hay "
    "thay đổi dữ liệu — mọi hành động phải do con người phê duyệt (human-in-the-loop). "
    "Khi cần số liệu, hãy gọi tool phù hợp; nếu thiếu dữ liệu thì nói rõ."
)


# ===================== AI VẬN HÀNH (advisory) =====================

def operational_insights(db: Session) -> dict:
    """Sinh danh sách insight tư vấn có mức ưu tiên từ dữ liệu thật."""
    insights = []

    inv = ai_tools.get_inventory_status(db)
    for e in inv.get("expiring_soon", []):
        sev = "high" if e["status"] == "expired" else "medium"
        rec = ("Cách ly và xử lý theo quy trình" if e["status"] == "expired"
               else "Ưu tiên dùng trước (FEFO) hoặc lên kế hoạch dùng/đổi")
        insights.append(_mk("Tồn kho", sev, f"Lô {e['lot_code']} {('đã hết hạn' if e['status']=='expired' else 'sắp hết hạn')} "
                            f"({e['days_left']} ngày)", rec))

    for c in ai_tools.get_calibrations_due(db)["due_or_overdue"]:
        sev = "high" if c["status"] == "overdue" else "medium"
        insights.append(_mk("Kiểm định", sev, f"{c['name']} {('quá hạn' if c['status']=='overdue' else 'sắp đến hạn')} "
                            f"({c['days_left']} ngày)", "Lên lịch kiểm định/hiệu chuẩn, tránh dùng thiết bị nếu bắt buộc"))

    for i in ai_tools.get_open_incidents(db)["open_incidents"]:
        sev = "high" if i["severity"] in ("major", "critical") else "low"
        insights.append(_mk("Bảo trì", sev, f"Sự cố {i['code']}: {i['title']} ({i['severity']})",
                            "Phân công xử lý; theo dõi downtime ảnh hưởng OEE"))

    qa = ai_tools.get_quality_alerts(db)
    bcount = qa["brewing"].get("count", 0)
    if bcount:
        insights.append(_mk("Chất lượng", "medium", f"Có {bcount} cảnh báo chỉ tiêu nấu/lọc/chiết",
                            "Cập nhật đủ chỉ tiêu/sản lượng để báo cáo chính xác"))
    pcount = qa["process"].get("count", 0)
    if pcount:
        insights.append(_mk("Chất lượng", "high", f"Có {pcount} cảnh báo QC mẻ (FAIL/ngoài giới hạn)",
                            "Mở deviation, giữ hold và điều tra trước khi release"))

    for r in ai_tools.get_oee(db)["records"][:5]:
        if r["oee"] < 0.70:
            insights.append(_mk("Hiệu suất", "medium",
                                f"OEE {r['line']} ca {r['shift']} thấp: {r['oee']*100:.1f}%",
                                "Phân tích downtime/loss lớn nhất; ưu tiên cải tiến"))

    order = {"high": 0, "medium": 1, "low": 2}
    insights.sort(key=lambda x: order.get(x["severity"], 3))
    summary = {"high": sum(1 for i in insights if i["severity"] == "high"),
               "medium": sum(1 for i in insights if i["severity"] == "medium"),
               "low": sum(1 for i in insights if i["severity"] == "low")}
    return {"count": len(insights), "summary": summary, "insights": insights,
            "note": "AI tư vấn (advisory) — mọi hành động cần con người phê duyệt."}


def _mk(domain, severity, finding, recommendation):
    return {"domain": domain, "severity": severity, "finding": finding,
            "recommendation": recommendation}


# ===================== TRỢ LÝ CHAT =====================

def llm_available() -> bool:
    if LLM_ENABLED == "off":
        return False
    if LLM_ENABLED == "on":
        return True
    if not LLM_API_KEY:
        return False
    try:
        import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


def chat(db: Session, message: str, history: list = None) -> dict:
    if llm_available():
        try:
            return _chat_llm(db, message, history or [])
        except Exception as e:  # noqa: BLE001 — fallback an toàn sang engine luật
            log.warning("LLM chat lỗi, fallback engine luật: %s", e, exc_info=True)
            res = _chat_local(db, message)
            res["note"] = f"(LLM lỗi, đã dùng engine luật: {e})"
            return res
    return _chat_local(db, message)


# ===================== CHAT STREAMING (SSE) =====================

def stream_chat(db: Session, message: str, history: list = None):
    """Generator phát sự kiện token-by-token cho SSE.

    Yield dict: {"type":"delta","text"} | {"type":"tool","name"} | {"type":"final","mode","tools_used"}.
    Dùng Claude streaming nếu khả dụng; ngược lại stream câu trả lời engine luật từng từ.
    """
    history = history or []
    if llm_available():
        try:
            yield from _stream_llm(db, message, history)
            return
        except Exception as e:  # noqa: BLE001 — fallback an toàn sang engine luật
            log.warning("LLM stream lỗi, fallback engine luật: %s", e, exc_info=True)
            res = _chat_local(db, message)
            yield from _stream_text(res["answer"], res.get("tools_used"), "local (LLM lỗi)")
            return
    res = _chat_local(db, message)
    yield from _stream_text(res["answer"], res.get("tools_used"), "local")


def _stream_text(text: str, tools: list, mode: str):
    """Mô phỏng stream cho engine luật: phát tool trước rồi nhả từng từ."""
    for t in (tools or []):
        yield {"type": "tool", "name": t}
    for chunk in re.findall(r"\S+\s*", text or ""):
        yield {"type": "delta", "text": chunk}
    yield {"type": "final", "mode": mode, "tools_used": tools or []}


def _stream_llm(db: Session, message: str, history: list):
    """Claude streaming + vòng lặp tool-use (nhả text delta giữa các lần gọi tool)."""
    import time

    import anthropic
    client = anthropic.Anthropic(api_key=LLM_API_KEY)
    tools = ai_tools.anthropic_tool_specs()
    messages = [{"role": h["role"], "content": h["content"]} for h in history[-8:]]
    messages.append({"role": "user", "content": message})
    used, in_tok, out_tok, t0 = [], 0, 0, time.monotonic()
    for _ in range(6):
        with client.messages.stream(model=LLM_MODEL, max_tokens=2048, system=SYSTEM_PROMPT,
                                    tools=tools, messages=messages) as stream:
            for text in stream.text_stream:
                yield {"type": "delta", "text": text}
            final = stream.get_final_message()
        u = getattr(final, "usage", None)
        if u:
            in_tok += getattr(u, "input_tokens", 0) or 0
            out_tok += getattr(u, "output_tokens", 0) or 0
        if final.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": final.content})
            results = []
            for block in final.content:
                if block.type == "tool_use":
                    used.append(block.name)
                    yield {"type": "tool", "name": block.name}
                    out = ai_tools.call_tool(db, block.name, block.input)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": _json(out)})
            messages.append({"role": "user", "content": results})
            continue
        break
    log_ai_call(log, model=LLM_MODEL, input_tokens=in_tok, output_tokens=out_tok,
                latency_ms=(time.monotonic() - t0) * 1000, tools=used)
    yield {"type": "final", "mode": "claude:" + LLM_MODEL, "tools_used": used}


def _chat_llm(db: Session, message: str, history: list) -> dict:
    """Dùng Claude (claude-opus-4-8) với tool-use loop trên các tool MES."""
    import anthropic

    import time
    client = anthropic.Anthropic(api_key=LLM_API_KEY)
    tools = ai_tools.anthropic_tool_specs()
    messages = [{"role": h["role"], "content": h["content"]} for h in history[-8:]]
    messages.append({"role": "user", "content": message})

    used = []
    in_tok = out_tok = 0
    t0 = time.monotonic()
    for _ in range(6):  # giới hạn vòng lặp tool-use
        resp = client.messages.create(
            model=LLM_MODEL,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            thinking={"type": "adaptive"},
            tools=tools,
            messages=messages,
        )
        u = getattr(resp, "usage", None)
        if u:
            in_tok += getattr(u, "input_tokens", 0) or 0
            out_tok += getattr(u, "output_tokens", 0) or 0
        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for block in resp.content:
                if block.type == "tool_use":
                    used.append(block.name)
                    out = ai_tools.call_tool(db, block.name, block.input)
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": _json(out)})
            messages.append({"role": "user", "content": results})
            continue
        answer = "".join(b.text for b in resp.content if b.type == "text")
        log_ai_call(log, model=LLM_MODEL, input_tokens=in_tok, output_tokens=out_tok,
                    latency_ms=(time.monotonic() - t0) * 1000, tools=used)
        return {"answer": answer, "tools_used": used, "mode": "claude:" + LLM_MODEL}
    log_ai_call(log, model=LLM_MODEL, input_tokens=in_tok, output_tokens=out_tok,
                latency_ms=(time.monotonic() - t0) * 1000, tools=used, ok=False)
    return {"answer": "Xin lỗi, truy vấn quá phức tạp.", "tools_used": used, "mode": "claude:" + LLM_MODEL}


def _json(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False, default=str)[:6000]


# ---- Engine luật nội bộ (offline) ----

INTENTS = [
    (("tồn", "kho", "vật tư", "nguyên liệu", "inventory"), "get_inventory_status"),
    (("oee", "hiệu suất", "đóng gói"), "get_oee"),
    (("cảnh báo", "chỉ tiêu", "alert", "chất lượng"), "get_quality_alerts"),
    (("mẻ", "batch", "lên men", "trạng thái sản xuất"), "get_batch_status"),
    (("kiểm định", "hiệu chuẩn", "calib"), "get_calibrations_due"),
    (("sự cố", "bảo trì", "incident", "hỏng"), "get_open_incidents"),
    (("năng lượng", "điện", "nước", "hơi", "energy"), "get_energy_summary"),
    (("truy xuất", "recall", "nguồn gốc", "trace"), "trace_lot"),
]


def _chat_local(db: Session, message: str) -> dict:
    m = (message or "").lower()
    if any(k in m for k in ("giúp", "help", "làm được gì", "chức năng")):
        caps = "; ".join(t["description"] for t in ai_tools.TOOLS.values())
        return {"answer": "Tôi có thể trả lời về: " + caps, "tools_used": [], "mode": "local"}

    for keys, tool in INTENTS:
        if any(k in m for k in keys):
            payload = {}
            if tool == "trace_lot":
                # lấy token in hoa/có gạch làm mã
                for w in message.split():
                    if "-" in w or w.isupper():
                        payload["code"] = w.strip(".,?")
                        break
                if "code" not in payload:
                    return {"answer": "Bạn cho tôi mã lô/mẻ cần truy xuất (vd PKG-2406-0001).",
                            "tools_used": [], "mode": "local"}
            data = ai_tools.call_tool(db, tool, payload)
            return {"answer": _summarize(tool, data), "tools_used": [tool], "data": data, "mode": "local"}

    return {"answer": "Tôi chưa hiểu rõ. Hãy hỏi về tồn kho, OEE, cảnh báo chất lượng, "
            "trạng thái mẻ, kiểm định, sự cố, năng lượng, hoặc truy xuất lô.",
            "tools_used": [], "mode": "local"}


def _summarize(tool: str, data: dict) -> str:
    if tool == "get_inventory_status":
        n = len(data.get("items", []))
        exp = len(data.get("expiring_soon", []))
        return f"Có {n} mã vật tư trong kho; {exp} lô sắp/đã hết hạn cần lưu ý."
    if tool == "get_oee":
        recs = data.get("records", [])
        if not recs:
            return "Chưa có dữ liệu OEE."
        parts = [f"{r['line']} ca {r['shift']}: OEE {r['oee']*100:.1f}%" for r in recs[:3]]
        return "OEE gần nhất — " + "; ".join(parts) + "."
    if tool == "get_quality_alerts":
        return (f"Cảnh báo: {data['brewing'].get('count',0)} ở nấu/lọc/chiết, "
                f"{data['process'].get('count',0)} ở QC mẻ.")
    if tool == "get_batch_status":
        bs = data.get("batches", [])
        run = sum(1 for b in bs if b["state"] == "running")
        return f"Có {len(bs)} mẻ; {run} đang chạy. Mẻ mới nhất: " + (bs[0]["batch_code"] if bs else "—") + "."
    if tool == "get_calibrations_due":
        return f"{len(data.get('due_or_overdue', []))} hạng mục kiểm định sắp/đã quá hạn (tổng {data.get('total',0)})."
    if tool == "get_open_incidents":
        return f"{len(data.get('open_incidents', []))} sự cố đang mở."
    if tool == "get_energy_summary":
        return f"Đã tổng hợp {len(data.get('monthly', []))} dòng năng lượng theo tháng."
    if tool == "trace_lot":
        if data.get("error"):
            return data["error"]
        return f"Mã {data['code']}: ảnh hưởng {len(data.get('affected_forward', []))} lô/mẻ (truy xuôi)."
    return "Đã lấy dữ liệu."
