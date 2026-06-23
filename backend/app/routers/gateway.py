"""Cổng API mở cho phần mềm ngoài (ERP/WMS/BI/AI agent).

- /api/v1/*  : endpoint versioned, xác thực bằng X-API-Key (đọc/ghi theo scope).
- Quản trị key & webhook: do người dùng nội bộ vai trò admin (X-Role: admin).
- /api/v1/events: feed sự kiện (từ audit log) cho tích hợp event-driven (§9.1).
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import Role, new_id
from ..database import get_db
from ..errors import NotFoundError
from ..models.audit import AuditLog
from ..models.integration import ApiKey, Webhook
from ..security import User, get_current_user, require_api_key, require_role
from ..services import ai_tools


class ExternalEventIn(BaseModel):
    entity_type: str = "external"
    entity_id: str = "-"
    action: str = "external_event"
    reason: Optional[str] = None
    data: Optional[dict] = None
    correlation_id: Optional[str] = None


class WebhookIn(BaseModel):
    target_url: str
    event_types: str = "*"
    secret: Optional[str] = None


class ApiKeyIn(BaseModel):
    name: str = "external"
    scopes: str = "read"

router = APIRouter(tags=["gateway"])

# ---------- /api/v1: dành cho phần mềm ngoài (X-API-Key) ----------
v1 = APIRouter(prefix="/api/v1")


@v1.get("/ping")
def ping(client=Depends(require_api_key())):
    return {"ok": True, "client": client["name"], "version": "v1"}


@v1.get("/production/batches")
def v1_batches(batch_code: str = None, db: Session = Depends(get_db), client=Depends(require_api_key())):
    return ai_tools.get_batch_status(db, batch_code)


@v1.get("/inventory")
def v1_inventory(db: Session = Depends(get_db), client=Depends(require_api_key())):
    return ai_tools.get_inventory_status(db)


@v1.get("/oee")
def v1_oee(line: str = None, db: Session = Depends(get_db), client=Depends(require_api_key())):
    return ai_tools.get_oee(db, line)


@v1.get("/energy")
def v1_energy(db: Session = Depends(get_db), client=Depends(require_api_key())):
    return ai_tools.get_energy_summary(db)


@v1.get("/quality/alerts")
def v1_quality(db: Session = Depends(get_db), client=Depends(require_api_key())):
    return ai_tools.get_quality_alerts(db)


@v1.get("/traceability")
def v1_trace(code: str, db: Session = Depends(get_db), client=Depends(require_api_key())):
    return ai_tools.trace_lot(db, code)


@v1.get("/events")
def v1_events(since_seq: int = 0, limit: int = 100, db: Session = Depends(get_db),
              client=Depends(require_api_key())):
    """Feed sự kiện nghiệp vụ (immutable) cho consumer; phân trang theo seq (§9.1)."""
    rows = db.execute(
        select(AuditLog).where(AuditLog.seq > since_seq)
        .order_by(AuditLog.seq).limit(min(limit, 500))
    ).scalars().all()
    return {"events": [{"seq": r.seq, "entity_type": r.entity_type, "entity_id": r.entity_id,
                        "action": r.action, "actor": r.actor, "occurred_at": r.ts.isoformat()}
                       for r in rows],
            "next_since_seq": rows[-1].seq if rows else since_seq}


@v1.post("/events")
def v1_ingest_event(payload: ExternalEventIn, db: Session = Depends(get_db),
                    client=Depends(require_api_key(write=True))):
    """Nhận event từ hệ ngoài (vd ERP xác nhận) — ghi vào audit log QUA record_audit
    để giữ nguyên chuỗi hash tamper-evident (trước đây insert thẳng làm hỏng chain)."""
    actor = User(username=f"api:{client['name']}", role="external", permissions=set())
    entry = record_audit(db, entity_type=payload.entity_type, entity_id=payload.entity_id,
                         action=payload.action, actor=actor, reason=payload.reason,
                         after=payload.data, correlation_id=payload.correlation_id)
    db.commit()
    return {"accepted": True, "seq": entry.seq}


router.include_router(v1)


# ---------- Quản trị key & webhook (nội bộ, admin) ----------
admin = APIRouter(prefix="/api/integration")


@admin.get("/keys")
def list_keys(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_role(user, Role.ADMIN)
    keys = db.execute(select(ApiKey).order_by(ApiKey.created_at.desc())).scalars().all()
    # che bớt token (chỉ hiện 8 ký tự cuối)
    return [{"key_id": k.key_id, "name": k.name, "scopes": k.scopes, "active": k.active,
             "token_preview": "…" + k.token[-8:], "call_count": k.call_count,
             "last_used_at": k.last_used_at, "created_at": k.created_at} for k in keys]


@admin.post("/keys", status_code=201)
def create_key(payload: ApiKeyIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_role(user, Role.ADMIN)
    token = "mes_" + new_id().replace("-", "") + new_id().replace("-", "")[:8]
    k = ApiKey(key_id=new_id(), name=payload.name, token=token,
               scopes=payload.scopes, created_by=user.username)
    db.add(k)
    db.commit()
    # token đầy đủ chỉ trả về lúc tạo
    return {"key_id": k.key_id, "name": k.name, "scopes": k.scopes, "token": token,
            "note": "Lưu token này — sẽ không hiển thị lại đầy đủ."}


@admin.post("/keys/{key_id}/revoke")
def revoke_key(key_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_role(user, Role.ADMIN)
    k = db.get(ApiKey, key_id)
    if not k:
        raise NotFoundError("Key không tồn tại.")
    k.active = False
    db.commit()
    return {"key_id": key_id, "active": False}


@admin.get("/webhooks")
def list_webhooks(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_role(user, Role.ADMIN)
    return db.execute(select(Webhook).order_by(Webhook.created_at.desc())).scalars().all()


@admin.post("/webhooks", status_code=201)
def create_webhook(payload: WebhookIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_role(user, Role.ADMIN)
    w = Webhook(webhook_id=new_id(), target_url=payload.target_url,
                event_types=payload.event_types, secret=payload.secret)
    db.add(w)
    db.commit()
    db.refresh(w)
    return w


@admin.post("/webhooks/{webhook_id}/disable")
def disable_webhook(webhook_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_role(user, Role.ADMIN)
    w = db.get(Webhook, webhook_id)
    if not w:
        raise NotFoundError("Webhook không tồn tại.")
    w.active = False
    db.commit()
    return {"webhook_id": webhook_id, "active": False}


router.include_router(admin)
