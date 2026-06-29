"""Rate-limit + quota với backend cắm được (in-process mặc định, Redis tùy chọn).

- /api/auth/login: chống brute-force theo IP.
- /api/ai/*: chống lạm dụng + hạn mức ngày cho chat (Claude thật = chi phí).

Một tiến trình → InProcessBackend (sliding-window/deque). Nhiều worker/replica →
đặt MES_REDIS_URL để dùng RedisBackend (fixed-window + daily INCR); nếu Redis lỗi/thiếu
thư viện sẽ tự fallback in-process. Interface check_rate_limit() giữ nguyên.
"""

import threading
import time
from collections import defaultdict, deque
from datetime import date
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from . import metrics_prom
from .config import (
    REDIS_URL,
    RL_AI_DAILY_QUOTA,
    RL_AI_PER_MIN,
    RL_ENABLED,
    RL_LOGIN_PER_MIN,
    TRUSTED_PROXY,
)
from .logging_config import get_logger

log = get_logger("mes.ratelimit")
_WINDOW = 60.0


class InProcessBackend:
    """Sliding-window/phút + đếm ngày, lưu trong bộ nhớ tiến trình."""

    name = "in-process"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict = defaultdict(deque)
        self._daily: dict = {}

    def hit_window(self, key: str, limit: int) -> tuple:
        now = time.monotonic()
        with self._lock:
            dq = self._hits[key]
            cutoff = now - _WINDOW
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= limit:
                return False, int(_WINDOW - (now - dq[0])) + 1
            dq.append(now)
            return True, 0

    def hit_daily(self, key: str, quota: int) -> bool:
        today = date.today().isoformat()
        with self._lock:
            rec = self._daily.get(key)
            if not rec or rec[0] != today:
                rec = [today, 0]
                self._daily[key] = rec
            if rec[1] >= quota:
                return False
            rec[1] += 1
            return True

    # tiện cho test
    def clear(self) -> None:
        with self._lock:
            self._hits.clear()
            self._daily.clear()


class RedisBackend:
    """Fixed-window/phút (INCR+EXPIRE) + daily INCR — đúng khi nhiều worker chung Redis."""

    name = "redis"

    def __init__(self, client) -> None:
        self.r = client

    def hit_window(self, key: str, limit: int) -> tuple:
        bucket = int(time.time() // _WINDOW)
        rkey = f"rl:w:{key}:{bucket}"
        n = self.r.incr(rkey)
        if n == 1:
            self.r.expire(rkey, int(_WINDOW) + 1)
        if n > limit:
            return False, int(_WINDOW - (time.time() % _WINDOW)) + 1
        return True, 0

    def hit_daily(self, key: str, quota: int) -> bool:
        rkey = f"rl:d:{key}:{date.today().isoformat()}"
        n = self.r.incr(rkey)
        if n == 1:
            self.r.expire(rkey, 86400 + 60)
        return n <= quota

    def clear(self) -> None:  # pragma: no cover
        pass


def _make_backend():
    if REDIS_URL:
        try:
            import redis  # type: ignore
            client = redis.Redis.from_url(REDIS_URL, decode_responses=True,
                                          socket_connect_timeout=2)
            client.ping()
            log.info("Rate-limit backend: Redis (%s)", REDIS_URL)
            return RedisBackend(client)
        except Exception as e:  # noqa: BLE001 — fallback an toàn
            log.warning("Không dùng được Redis (%s) → fallback in-process: %s", REDIS_URL, e)
    return InProcessBackend()


_backend = _make_backend()
# Tương thích test cũ (test monkeypatch ratelimit._hits): trỏ về store của backend in-proc.
_hits = getattr(_backend, "_hits", {})


def _client_key(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return "t:" + auth[7:][:16]
    # CHỈ tin X-Forwarded-For khi chạy sau reverse proxy tin cậy (MES_TRUSTED_PROXY=1);
    # nếu không, kẻ tấn công có thể giả header để né rate-limit → dùng IP kết nối thực.
    client_ip = request.client.host if request.client else "?"
    if TRUSTED_PROXY:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            client_ip = xff.split(",")[0].strip()
    return "ip:" + client_ip


def _deny(detail: str, retry: int, kind: str) -> JSONResponse:
    metrics_prom.inc("mes_ratelimit_blocks_total", kind=kind)
    log.warning("rate-limit chặn (%s): %s", kind, detail)
    headers = {"Retry-After": str(retry)} if retry else {}
    return JSONResponse(status_code=429, content={"detail": detail}, headers=headers)


def check_rate_limit(request: Request) -> Optional[JSONResponse]:
    """Trả JSONResponse 429 nếu vượt giới hạn; None nếu cho qua."""
    if not RL_ENABLED:
        return None
    path = request.url.path
    method = request.method

    if path == "/api/auth/login" and method == "POST":
        ok, retry = _backend.hit_window("login:" + _client_key(request), RL_LOGIN_PER_MIN)
        if not ok:
            return _deny(f"Quá nhiều lần đăng nhập, thử lại sau {retry}s.", retry, "login")
        return None

    if path.startswith("/api/ai/") and path != "/api/ai/status" and method in ("POST", "GET"):
        key = _client_key(request)
        ok, retry = _backend.hit_window("ai:" + key, RL_AI_PER_MIN)
        if not ok:
            return _deny(f"Quá nhiều yêu cầu AI, thử lại sau {retry}s.", retry, "ai")
        if method == "POST" and path in ("/api/ai/chat", "/api/ai/chat/stream"):
            if not _backend.hit_daily("aichat:" + key, RL_AI_DAILY_QUOTA):
                return _deny(f"Đã đạt hạn mức AI trong ngày ({RL_AI_DAILY_QUOTA} lượt chat). "
                             "Liên hệ quản trị nếu cần nâng hạn mức.", 0, "ai_quota")
        return None

    return None
