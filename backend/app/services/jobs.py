"""Worker tác vụ nền in-process (ThreadPoolExecutor) + registry handler.

submit() tạo Job(queued) rồi đẩy vào executor; worker mở SessionLocal riêng, chạy
handler theo `kind`, cập nhật trạng thái/kết quả. Quy mô lớn: thay executor bằng
Celery/RQ + Redis — interface submit()/get() giữ nguyên.
"""

from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..common import new_id, utcnow
from ..database import SessionLocal
from ..errors import DomainError, NotFoundError, PermissionError_
from ..logging_config import get_logger
from ..models.jobs import Job
from ..security import User

log = get_logger("mes.jobs")
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mes-job")
HANDLERS = {}   # kind -> fn(db, params, set_progress) -> dict


def register(kind: str):
    def deco(fn):
        HANDLERS[kind] = fn
        return fn
    return deco


def submit(db: Session, kind: str, params: dict, user: User) -> Job:
    if kind not in HANDLERS:
        raise DomainError(f"Loại tác vụ không hỗ trợ: {kind}. Có: {', '.join(HANDLERS)}")
    job = Job(job_id=new_id(), kind=kind, status="queued", params=params or {},
              created_by=user.username, created_at=utcnow())
    db.add(job)
    db.commit()
    db.refresh(job)
    _executor.submit(_run, job.job_id)
    log.info("job submitted id=%s kind=%s by=%s", job.job_id, kind, user.username)
    return job


def _run(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if not job:
            return
        job.status = "running"
        job.started_at = utcnow()
        db.commit()

        def set_progress(p: int) -> None:
            job.progress = max(0, min(100, int(p)))
            db.commit()

        try:
            result = HANDLERS[job.kind](db, job.params or {}, set_progress)
            job.result = result
            job.status = "done"
            job.progress = 100
        except Exception as e:  # noqa: BLE001 — ghi lỗi vào job, không làm sập worker
            log.warning("job lỗi id=%s kind=%s: %s", job_id, job.kind, e, exc_info=True)
            job.status = "error"
            job.error = str(e)
        job.finished_at = utcnow()
        db.commit()
    finally:
        db.close()


def get_job(db: Session, job_id: str, user: User) -> dict:
    job = db.get(Job, job_id)
    if not job:
        raise NotFoundError("Tác vụ không tồn tại.")
    if user.role != "admin" and job.created_by != user.username:
        raise PermissionError_("Không có quyền xem tác vụ của người khác.")
    return _out(job)


def list_jobs(db: Session, user: User) -> list:
    stmt = select(Job).order_by(Job.created_at.desc()).limit(50)
    if user.role != "admin":
        stmt = stmt.where(Job.created_by == user.username)
    return [_out(j) for j in db.execute(stmt).scalars().all()]


def _out(j: Job) -> dict:
    return {"job_id": j.job_id, "kind": j.kind, "status": j.status, "progress": j.progress,
            "params": j.params, "result": j.result, "error": j.error,
            "created_by": j.created_by, "created_at": j.created_at,
            "started_at": j.started_at, "finished_at": j.finished_at}


# ---------------- Handlers ----------------

@register("ai_report")
def _ai_report(db: Session, params: dict, set_progress) -> dict:
    """Báo cáo vận hành AI: gom insight + tóm tắt (tác vụ có thể chậm nếu bật LLM)."""
    from . import ai
    set_progress(20)
    ins = ai.operational_insights(db)
    set_progress(70)
    s = ins["summary"]
    headline = (f"{ins['count']} khuyến nghị: {s['high']} cao, {s['medium']} trung bình, "
                f"{s['low']} thấp.")
    top = [f"[{i['severity']}] {i['domain']}: {i['finding']}" for i in ins["insights"][:5]]
    set_progress(95)
    return {"headline": headline, "top": top, "summary": s, "count": ins["count"]}


@register("recall")
def _recall(db: Session, params: dict, set_progress) -> dict:
    """Mô phỏng recall/truy xuất cho một mã lô/mẻ (có thể nặng với đồ thị lớn)."""
    from . import ai_tools
    code = (params or {}).get("code")
    if not code:
        raise DomainError("Thiếu 'code' (mã lô/mẻ) cho tác vụ recall.")
    set_progress(40)
    data = ai_tools.trace_lot(db, code)
    set_progress(95)
    if data.get("error"):
        raise DomainError(data["error"])
    return {"code": code, "affected": len(data.get("affected_forward", [])),
            "affected_forward": data.get("affected_forward", [])}
