"""Đăng nhập, phiên, và quản trị tài khoản."""

from datetime import timedelta

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import Role, new_id, utcnow
from ..database import get_db
from ..errors import NotFoundError, PermissionError_
from ..models.auth import User as UserModel, UserSession
from ..security import (
    PERMISSION_CATALOG,
    User,
    get_current_user,
    hash_password,
    new_token,
    require_role,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_HOURS = 12


class LoginIn(BaseModel):
    username: str
    password: str


class CreateUserIn(BaseModel):
    username: str
    password: str
    full_name: str
    job_title: str
    role: str
    allowed_views: str = "dashboard"
    permissions: str = ""


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str


class ProfileIn(BaseModel):
    full_name: str


def _profile(u: UserModel) -> dict:
    return {"username": u.username, "full_name": u.full_name, "job_title": u.job_title,
            "role": u.role,
            "views": [v.strip() for v in u.allowed_views.split(",")] if u.allowed_views != "*" else "*",
            "permissions": "*" if (u.permissions or "").strip() == "*" else
                           [p.strip() for p in (u.permissions or "").split(",") if p.strip()]}


def _audit_auth(db, username, role, action, reason=None):
    record_audit(db, entity_type="auth", entity_id=username, action=action,
                 actor=User(username=username, role=role or "?"), reason=reason)


@router.post("/login")
def login(payload: LoginIn, db: Session = Depends(get_db)):
    u = db.execute(select(UserModel).where(UserModel.username == payload.username)).scalar_one_or_none()
    if not u or not u.active or not verify_password(payload.password, u.password_hash):
        _audit_auth(db, payload.username, None, "login_failed", "Sai tài khoản/mật khẩu hoặc bị khoá")
        db.commit()
        raise PermissionError_("Sai tài khoản hoặc mật khẩu.")
    token = new_token()
    db.add(UserSession(token=token, user_id=u.user_id, username=u.username, role=u.role,
                       created_at=utcnow(), expires_at=utcnow() + timedelta(hours=SESSION_HOURS)))
    u.last_login_at = utcnow()
    _audit_auth(db, u.username, u.role, "login")
    db.commit()
    return {"token": token, "user": _profile(u)}


@router.post("/logout")
def logout(authorization: str = Header(default=""), db: Session = Depends(get_db)):
    if authorization.startswith("Bearer "):
        sess = db.get(UserSession, authorization[7:])
        if sess:
            _audit_auth(db, sess.username, sess.role, "logout")
            db.delete(sess)
            db.commit()
    return {"ok": True}


@router.get("/permissions")
def permission_catalog(user: User = Depends(get_current_user)):
    """Catalog quyền chi tiết (cho UI quản trị)."""
    return {"catalog": [{"key": k, "label": v} for k, v in PERMISSION_CATALOG.items()]}


@router.post("/change-password")
def change_password(payload: ChangePasswordIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    u = db.execute(select(UserModel).where(UserModel.username == user.username)).scalar_one_or_none()
    if not u or not verify_password(payload.old_password, u.password_hash):
        raise PermissionError_("Mật khẩu hiện tại không đúng.")
    if len(payload.new_password) < 6:
        raise PermissionError_("Mật khẩu mới tối thiểu 6 ký tự.")
    u.password_hash = hash_password(payload.new_password)
    _audit_auth(db, u.username, u.role, "change_password")
    db.commit()
    return {"ok": True}


@router.put("/me")
def update_profile(payload: ProfileIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    u = db.execute(select(UserModel).where(UserModel.username == user.username)).scalar_one_or_none()
    if not u:
        raise NotFoundError("Không tìm thấy tài khoản.")
    u.full_name = payload.full_name
    db.commit()
    return _profile(u)


@router.get("/me")
def me(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    u = db.execute(select(UserModel).where(UserModel.username == user.username)).scalar_one_or_none()
    if not u:
        raise NotFoundError("Không tìm thấy tài khoản.")
    return _profile(u)


# ---- Quản trị tài khoản (admin) ----
@router.get("/users")
def list_users(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_role(user, Role.ADMIN)
    rows = db.execute(select(UserModel).order_by(UserModel.username)).scalars().all()
    return [{"username": u.username, "full_name": u.full_name, "job_title": u.job_title,
             "role": u.role, "allowed_views": u.allowed_views, "permissions": u.permissions,
             "active": u.active, "last_login_at": u.last_login_at} for u in rows]


@router.post("/users", status_code=201)
def create_user(payload: CreateUserIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_role(user, Role.ADMIN)
    if payload.role not in {r.value for r in Role}:
        raise PermissionError_(f"Vai trò không hợp lệ: {payload.role}")
    if db.execute(select(UserModel).where(UserModel.username == payload.username)).scalar_one_or_none():
        raise PermissionError_("Tên đăng nhập đã tồn tại.")
    u = UserModel(user_id=new_id(), username=payload.username, password_hash=hash_password(payload.password),
                  full_name=payload.full_name, job_title=payload.job_title, role=payload.role,
                  allowed_views=payload.allowed_views, permissions=payload.permissions, active=True)
    db.add(u)
    db.commit()
    return {"username": u.username, "created": True}


@router.post("/users/{username}/toggle")
def toggle_user(username: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_role(user, Role.ADMIN)
    u = db.execute(select(UserModel).where(UserModel.username == username)).scalar_one_or_none()
    if not u:
        raise NotFoundError("Không tìm thấy tài khoản.")
    u.active = not u.active
    db.commit()
    return {"username": username, "active": u.active}
