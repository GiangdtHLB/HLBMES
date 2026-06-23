"""Điểm vào ứng dụng FastAPI (modular monolith)."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import APP_NAME, FRONTEND_DIR
from .database import init_db
from .errors import DomainError, NotFoundError, PermissionError_
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
    maintenance,
    master,
    materials,
    orders,
    performance,
    process,
    quality,
    quality_adv,
    recipes,
    reports,
    scan,
    traceability,
    warehouse,
    workorders,
)

app = FastAPI(
    title=APP_NAME,
    version="0.1.0-mvp",
    description=(
        "MES Nhà máy Bia — MVP P0 (Order → Batch → Recipe/version → "
        "QC hold/release → Genealogy → Audit). Theo blueprint MES-ARCH-002.\n\n"
        "Xác thực MVP: truyền header **X-User** và **X-Role** "
        "(operator|supervisor|qa|engineer|admin)."
    ),
)


@app.on_event("startup")
def _startup() -> None:
    init_db()


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
          process, brewing, reports, historian, scan, ai, gateway, audit):
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
    except Exception:  # noqa: BLE001
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "app": APP_NAME, "version": "0.1.0-mvp",
            "db": {"ok": db_ok, "dialect": dialect}, "time": utcnow().isoformat()}


# ---- Frontend tĩnh (đặt cuối để không che /api) ----
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
