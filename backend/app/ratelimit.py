"""Rate-limit + quota tối giản (in-process, không cần thư viện ngoài).

Mục tiêu cấp bách: bảo vệ /api/auth/login (chống brute-force) và /api/ai/*
(chống lạm dụng — AI gọi Claude thật = chi phí). Dùng sliding-window theo
IP/phiên + hạn mức ngày cho chat AI.

Giới hạn: in-memory nên chỉ đúng trong 1 tiến trình. Khi chạy nhiều worker/replica,
thay bằng Redis (token bucket) — interface check_rate_limit() giữ nguyên.
"""

import threading
import time
from collections import defaultdict, deque
from datetime import date
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from .config import (
    RL_AI_DAILY_QUOTA,
    RL_AI_PER_MIN,
    RL_ENABLED,
    RL_LOGIN_PER_MIN,
)

_WINDOW = 60.0  # giây cho sliding-window /phút
_lock = threading.Lock()
_hits: dict = defaultdict(deque)      # key -> deque[timestamp]
_ai_daily: dict = {}                  # key -> [date_iso, count]


def _client_key(request: Request) -> str:
    """Định danh client: ưu tiên token (theo phiên/người dùng), fallback IP."""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return "t:" + auth[7:][:16]
    xff = request.headers.get("x-forwarded-for")
    ip = xff.split(",")[0].strip() if xff else (request.client.host if request.client else "?")
    return "ip:" + ip


def _allow_window(key: str, limit: int, now: float) -> tuple[bool, int]:
    dq = _hits[key]
    cutoff = now - _WINDOW
    while dq and dq[0] < cutoff:
        dq.popleft()
    if len(dq) >= limit:
        return False, int(_WINDOW - (now - dq[0])) + 1
    dq.append(now)
    return True, 0


def _deny(detail: str, retry: int) -> JSONResponse:
    headers = {"Retry-After": str(retry)} if retry else {}
    return JSONResponse(status_code=429, content={"detail": detail}, headers=headers)


def check_rate_limit(request: Request) -> Optional[JSONResponse]:
    """Trả JSONResponse 429 nếu vượt giới hạn; None nếu cho qua."""
    if not RL_ENABLED:
        return None
    path = request.url.path
    method = request.method

    # 1) Đăng nhập: chống brute-force theo IP.
    if path == "/api/auth/login" and method == "POST":
        key = "login:" + _client_key(request)
        with _lock:
            ok, retry = _allow_window(key, RL_LOGIN_PER_MIN, time.monotonic())
        if not ok:
            return _deny(f"Quá nhiều lần đăng nhập, thử lại sau {retry}s.", retry)
        return None

    # 2) AI: chống lạm dụng + hạn mức ngày cho chat (Claude thật = chi phí).
    if path.startswith("/api/ai/") and path not in ("/api/ai/status",) and method in ("POST", "GET"):
        key = _client_key(request)
        with _lock:
            ok, retry = _allow_window("ai:" + key, RL_AI_PER_MIN, time.monotonic())
            if ok and path == "/api/ai/chat" and method == "POST":
                today = date.today().isoformat()
                rec = _ai_daily.get(key)
                if not rec or rec[0] != today:
                    rec = [today, 0]
                    _ai_daily[key] = rec
                if rec[1] >= RL_AI_DAILY_QUOTA:
                    return _deny(
                        f"Đã đạt hạn mức AI trong ngày ({RL_AI_DAILY_QUOTA} lượt chat). "
                        "Liên hệ quản trị nếu cần nâng hạn mức.", 0)
                rec[1] += 1
        if not ok:
            return _deny(f"Quá nhiều yêu cầu AI, thử lại sau {retry}s.", retry)
        return None

    return None
