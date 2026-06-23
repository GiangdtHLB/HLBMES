"""Structured logging + request-id (P1).

- request-id gắn vào mọi log dòng theo request (contextvar) để truy vết.
- Định dạng text (mặc định) hoặc JSON (MES_LOG_JSON=1) cho thu thập tập trung.
- Hàm log_ai_call() ghi chi phí AI (model/token/latency/cost) — theo dõi tiền.
"""

import contextvars
import json
import logging
import sys

from .config import LOG_JSON, LOG_LEVEL

request_id_var: contextvars.ContextVar = contextvars.ContextVar("request_id", default="-")

# Đơn giá ước tính (USD / 1M token) cho ước lượng chi phí AI — chỉnh khi đổi model.
_PRICE = {"input": 15.0, "output": 75.0}


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "msg": record.getMessage(),
        }
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_RequestIdFilter())
    if LOG_JSON:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
    # bớt ồn từ access log của uvicorn (đã có middleware tự log request)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return round(input_tokens / 1e6 * _PRICE["input"] + output_tokens / 1e6 * _PRICE["output"], 6)


def log_ai_call(logger: logging.Logger, *, model: str, input_tokens: int, output_tokens: int,
                latency_ms: float, tools: list, ok: bool = True) -> None:
    """Ghi 1 dòng chi phí cho mỗi lượt gọi LLM (để theo dõi token/tiền/độ trễ)."""
    cost = estimate_cost(input_tokens, output_tokens)
    logger.info(
        "ai_call model=%s in_tok=%d out_tok=%d est_usd=%.5f latency_ms=%.0f tools=%s ok=%s",
        model, input_tokens, output_tokens, cost, latency_ms, ",".join(tools) or "-", ok)
    from . import metrics_prom
    metrics_prom.inc("mes_ai_calls_total")
    metrics_prom.inc("mes_ai_tokens_total", input_tokens, direction="input")
    metrics_prom.inc("mes_ai_tokens_total", output_tokens, direction="output")
    if not ok:
        metrics_prom.inc("mes_ai_errors_total")
