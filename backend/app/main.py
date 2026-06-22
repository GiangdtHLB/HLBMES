"""Điểm vào ứng dụng FastAPI (modular monolith)."""

import os

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import APP_NAME, FRONTEND_DIR
from .database import init_db
from .errors import DomainError, NotFoundError, PermissionError_
from .security import get_current_user
from .routers import (
    ai,
    audit,
    auth,
    batches,
    brewing,
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
    recipes,
    reports,
    scan,
    traceability,
    warehouse,
    workorders,
)

# Tài liệu API (/docs, /redoc, /openapi.json) chỉ bật khi MES_DEBUG — production tắt
# để tránh lộ bề mặt API & hướng dẫn xác thực. Đặt MES_DEBUG=1 ở môi trường dev.
_DEBUG = os.environ.get("MES_DEBUG", "").lower() in ("1", "true", "on")

app = FastAPI(
    title=APP_NAME,
    version="0.1.0-mvp",
    description=(
        "MES Nhà máy Bia — MVP P0 (Order → Batch → Recipe/version → "
        "QC hold/release → Genealogy → Audit). Theo blueprint MES-ARCH-002.\n\n"
        "Xác thực: đăng nhập qua `POST /api/auth/login` rồi gửi "
        "`Authorization: Bearer <token>`."
    ),
    docs_url="/docs" if _DEBUG else None,
    redoc_url="/redoc" if _DEBUG else None,
    openapi_url="/openapi.json" if _DEBUG else None,
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
# auth: chứa /login, /logout — không gắn phụ thuộc xác thực toàn router (login phải mở).
app.include_router(auth.router)
# gateway: cổng ngoài /api/v1 dùng X-API-Key + phần /api/integration tự kiểm tra vai trò.
app.include_router(gateway.router)
# Mọi router còn lại: BẮT BUỘC đăng nhập (đóng các endpoint đọc/ghi từng bị mở).
# require_perm/require_role ở từng endpoint vẫn áp dụng chồng lên (defense in depth).
for r in (master, orders, workorders, recipes, batches, materials, quality, traceability,
          performance, warehouse, energy, maintenance, process, brewing, reports, historian,
          scan, ai, audit):
    app.include_router(r.router, dependencies=[Depends(get_current_user)])


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
