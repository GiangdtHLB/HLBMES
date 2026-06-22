"""Historian / time-series + ingest từ edge connector."""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..security import User, get_current_user, require_api_key
from ..services import historian as svc

router = APIRouter(prefix="/api/historian", tags=["historian"])


class HistPoint(BaseModel):
    tag: str
    value: float
    unit: str = None
    quality: str = "good"
    ts: datetime = None
    source: str = None


class IngestIn(BaseModel):
    points: list[HistPoint]


# ---- Edge → MES: ingest telemetry (xác thực bằng X-API-Key, scope write) ----
@router.post("/ingest")
def ingest(payload: IngestIn, db: Session = Depends(get_db), client=Depends(require_api_key(write=True))):
    n = svc.ingest(db, [p.model_dump() for p in payload.points], source=client["name"])
    return {"ingested": n}


# ---- Query (người dùng đăng nhập) ----
@router.get("/tags")
def list_tags(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.tags(db)


@router.get("/latest")
def latest_all(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [svc.latest(db, t) for t in svc.tags(db)]


@router.get("/series")
def series(tag: str, hours: float = 6, buckets: int = 60, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    return svc.series(db, tag, hours, buckets)


# ---- Mô phỏng nhanh trong app (1 tick) — tiện demo không cần chạy edge_sim ----
@router.post("/simulate")
def simulate(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    n = svc.tick(db, source="in-app")
    return {"ingested": n, "tags": len(svc.TAGS)}
