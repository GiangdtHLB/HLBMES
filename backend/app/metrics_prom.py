"""Metrics dạng Prometheus, in-process, không cần thư viện ngoài (P2 monitoring).

Đăng ký counter/gauge đơn giản + xuất text exposition tại /metrics. Đủ để Prometheus
scrape (http requests, AI calls/tokens/errors, rate-limit blocks, audit-chain intact).
Nhiều worker/replica: mỗi tiến trình tự đếm — gộp ở Prometheus (dùng nhãn instance).
"""

import threading
from typing import Dict, Tuple

_lock = threading.Lock()
_counters: Dict[Tuple[str, Tuple], float] = {}
_gauges: Dict[Tuple[str, Tuple], float] = {}

# Mô tả + kiểu cho phần # HELP/# TYPE.
_META = {
    "mes_http_requests_total": ("counter", "Tổng số request HTTP theo route/status"),
    "mes_http_request_duration_seconds_sum": ("counter", "Tổng thời gian xử lý request (giây)"),
    "mes_http_request_duration_seconds_count": ("counter", "Số request đã đo thời gian"),
    "mes_ai_calls_total": ("counter", "Số lượt gọi LLM"),
    "mes_ai_errors_total": ("counter", "Số lượt lỗi LLM (fallback engine luật)"),
    "mes_ai_tokens_total": ("counter", "Tổng token LLM theo chiều in/out"),
    "mes_ratelimit_blocks_total": ("counter", "Số request bị rate-limit chặn (429)"),
    "mes_audit_chain_intact": ("gauge", "Chuỗi hash audit toàn vẹn (1) hay đã gãy (0)"),
    "mes_audit_entries": ("gauge", "Số bản ghi audit hiện có"),
}


def _key(name: str, labels: dict) -> Tuple[str, Tuple]:
    return (name, tuple(sorted((labels or {}).items())))


def inc(name: str, value: float = 1.0, **labels) -> None:
    with _lock:
        k = _key(name, labels)
        _counters[k] = _counters.get(k, 0.0) + value


def set_gauge(name: str, value: float, **labels) -> None:
    with _lock:
        _gauges[_key(name, labels)] = value


def observe_duration(route: str, seconds: float) -> None:
    inc("mes_http_request_duration_seconds_sum", seconds, route=route)
    inc("mes_http_request_duration_seconds_count", 1.0, route=route)


def _fmt_labels(labels: Tuple) -> str:
    if not labels:
        return ""
    inner = ",".join(f'{k}="{str(v).replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"'
                     for k, v in labels)
    return "{" + inner + "}"


def render() -> str:
    lines, seen_help = [], set()
    with _lock:
        snap_c = dict(_counters)
        snap_g = dict(_gauges)
    for store in (snap_c, snap_g):
        for (name, labels), val in sorted(store.items()):
            if name not in seen_help:
                kind, desc = _META.get(name, ("untyped", name))
                lines.append(f"# HELP {name} {desc}")
                lines.append(f"# TYPE {name} {kind}")
                seen_help.add(name)
            v = int(val) if float(val).is_integer() else val
            lines.append(f"{name}{_fmt_labels(labels)} {v}")
    return "\n".join(lines) + "\n"
