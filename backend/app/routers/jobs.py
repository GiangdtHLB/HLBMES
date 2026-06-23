"""Tác vụ nền (jobs): submit + poll trạng thái/kết quả (P2 worker)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import JobIn
from ..security import User, get_current_user
from ..services import jobs as svc

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
def list_jobs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.list_jobs(db, user)


@router.post("", status_code=201)
def submit_job(payload: JobIn, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    job = svc.submit(db, payload.kind, payload.params, user)
    return {"job_id": job.job_id, "kind": job.kind, "status": job.status}


@router.get("/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.get_job(db, job_id, user)
