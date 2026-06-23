"""Điểm vào ứng dụng FastAPI (modular monolith)."""

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import APP_NAME, FRONTEND_DIR
from .database import init_db
from .errors import DomainError, NotFoundError, PermissionError_
from . import metrics_prom
from .logging_config import configure_logging, get_logger, request_id_var
from .ratelimit import check_rate_limit
from .routers import (
    ai,
    audit,
    auth,
    batches,
    brewing,
    dispense,
    downtime,
    energy,
    gateway,
    historian,
    isa88,
    jobs,
    label,
    lines,
    maintenance,
    master,
    materials,
    orders,
    packaging,
    performance,
    process,
    quality,
    quality_adv,
    recipes,
    reports,
    scan,
    schedule,
    traceability,
    warehouse,
    wms,
    workorders,
)

configure_logging()
log = get_logger("mes.http")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    get_logger("mes").info("MES khởi động — %s", APP_NAME)
    yield


app = FastAPI(
    title=APP_NAME,
    version="0.1.0-mvp",
    lifespan=lifespan,
    description=(
        "MES Nhà máy Bia — MVP P0 (Order → Batch → Recipe/version → "
        "QC hold/release → Genealogy → Audit). Theo blueprint MES-ARCH-002."
    ),
)


@app.middleware("http")
async def _observability(request: Request, call_next):
    """Gắn request-id, áp rate-limit, đo độ trễ + log mỗi request."""
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    token = request_id_var.set(rid)
    start = time.monotonic()
    try:
        blocked = check_rate_limit(request)   # 429 nếu vượt giới hạn
        if blocked is not None:
            log.warning("rate_limited %s %s", request.method, request.url.path)
            blocked.headers["X-Request-ID"] = rid
            return blocked
        resp = await call_next(request)
        dur = (time.monotonic() - start) * 1000
        resp.headers["X-Request-ID"] = rid
        # Metrics: dùng route template (vd /api/batches/{batch_id}) để giới hạn cardinality.
        r = request.scope.get("route")
        route = getattr(r, "path", request.url.path)
        if route != "/metrics":
            metrics_prom.inc("mes_http_requests_total", method=request.method,
                             route=route, status=resp.status_code)
            metrics_prom.observe_duration(route, dur / 1000.0)
        if request.url.path.startswith("/api"):
            log.info("%s %s -> %s %.0fms", request.method, request.url.path,
                     resp.status_code, dur)
        return resp
    finally:
        request_id_var.reset(token)


# ---- Ánh xạ lỗi nghiệp vụ sang HTTP ----
@app.exception_handler(NotFoundError)
async def _not_found(_: Request, exc: NotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(DomainError)
async def _domain(_: Request, exc: DomainError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(PermissionError_)
async def _perm(_: Request, exc: PermissionError_):
    return JSONResponse(status_code=403, content={"detail": str(exc)})


# ---- Routers ----
for r in (auth, master, orders, workorders, recipes, batches, materials, dispense, quality,
          quality_adv, traceability, performance, downtime, warehouse, energy, maintenance,
          process, brewing, reports, historian, scan, schedule, ai, jobs, isa88, wms,
          label, lines, packaging, gateway, audit):
    app.include_router(r.router)


@app.get("/api/health", tags=["system"])
def health():
    """Health/readiness: kiểm tra kết nối DB + thông tin phiên bản (cho monitoring)."""
    from sqlalchemy import text
    from .common import utcnow
    from .database import engine
    db_ok, dialect = True, engine.dialect.name
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:  # noqa: BLE001 — health không được ném; nhưng PHẢI log
        db_ok = False
        log.error("health DB check failed: %s", e, exc_info=True)
    return {"status": "ok" if db_ok else "degraded", "app": APP_NAME, "version": "0.1.0-mvp",
            "db": {"ok": db_ok, "dialect": dialect}, "time": utcnow().isoformat()}


@app.get("/metrics", tags=["system"])
def metrics():
    """Số liệu Prometheus (text exposition). Cập nhật gauge audit-chain khi scrape."""
    from fastapi.responses import PlainTextResponse
    from .audit import verify_chain
    from .database import SessionLocal
    db = SessionLocal()
    try:
        vc = verify_chain(db)
        metrics_prom.set_gauge("mes_audit_chain_intact", 1 if vc.get("intact") else 0)
        metrics_prom.set_gauge("mes_audit_entries", vc.get("count", 0))
    except Exception as e:  # noqa: BLE001
        log.error("metrics audit gauge failed: %s", e)
    finally:
        db.close()
    return PlainTextResponse(metrics_prom.render(), media_type="text/plain; version=0.0.4")


# ---- Frontend tĩnh (đặt cuối để không che /api) ----
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
