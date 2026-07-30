"""Đăng nhập, phiên, và quản trị tài khoản."""

from datetime import timedelta

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import Role, new_id, utcnow
from ..database import get_db
from ..errors import DomainError, NotFoundError, PermissionError_
from ..models.auth import RoleTemplate, User as UserModel, UserSession
from ..security import (
    PERMISSION_CATALOG,
    User,
    get_current_user,
    hash_password,
    new_token,
    require_role,
    validate_password_strength,
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
    scope_lines: str = "*"
    scope_areas: str = "*"
    scope_qc: str = "*"
    scope_warehouse: str = "*"


class CopyPermissionsIn(BaseModel):
    source_username: str


class EditUserIn(BaseModel):
    full_name: str
    job_title: str
    role: str
    allowed_views: str
    permissions: str = ""


class ScopeIn(BaseModel):
    scope_lines: str = "*"   # csv hoặc "*"
    scope_areas: str = "*"
    scope_qc: str = "*"
    scope_warehouse: str = "*"   # cong_ty|phan_xuong|"*"


class RoleTemplateIn(BaseModel):
    name: str
    role: str
    allowed_views: str = "dashboard"
    permissions: str = ""
    scope_lines: str = "*"
    scope_areas: str = "*"
    scope_qc: str = "*"
    scope_warehouse: str = "*"


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
                           [p.strip() for p in (u.permissions or "").split(",") if p.strip()],
            "scope_lines": getattr(u, "scope_lines", "*") or "*",
            "scope_areas": getattr(u, "scope_areas", "*") or "*",
            "scope_qc": getattr(u, "scope_qc", "*") or "*",
            "scope_warehouse": getattr(u, "scope_warehouse", "*") or "*",
            "must_change_password": bool(getattr(u, "must_change_password", False))}


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
    if verify_password(payload.new_password, u.password_hash):
        raise DomainError("Mật khẩu mới phải khác mật khẩu hiện tại.")
    validate_password_strength(payload.new_password, u.username)
    u.password_hash = hash_password(payload.new_password)
    u.must_change_password = False          # đã đổi → bỏ cờ buộc đổi
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
             "scope_lines": getattr(u, "scope_lines", "*") or "*",
             "scope_areas": getattr(u, "scope_areas", "*") or "*",
             "scope_qc": getattr(u, "scope_qc", "*") or "*",
             "scope_warehouse": getattr(u, "scope_warehouse", "*") or "*",
             "active": u.active, "last_login_at": u.last_login_at} for u in rows]


@router.post("/users", status_code=201)
def create_user(payload: CreateUserIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_role(user, Role.ADMIN)
    if payload.role not in {r.value for r in Role}:
        raise PermissionError_(f"Vai trò không hợp lệ: {payload.role}")
    if db.execute(select(UserModel).where(UserModel.username == payload.username)).scalar_one_or_none():
        raise PermissionError_("Tên đăng nhập đã tồn tại.")
    validate_password_strength(payload.password, payload.username)
    u = UserModel(user_id=new_id(), username=payload.username, password_hash=hash_password(payload.password),
                  full_name=payload.full_name, job_title=payload.job_title, role=payload.role,
                  allowed_views=payload.allowed_views, permissions=payload.permissions,
                  scope_lines=payload.scope_lines or "*", scope_areas=payload.scope_areas or "*",
                  scope_qc=payload.scope_qc or "*", scope_warehouse=payload.scope_warehouse or "*",
                  active=True)
    db.add(u)
    record_audit(db, entity_type="auth", entity_id=u.username, action="create_user", actor=user,
                 after={"role": u.role, "scope_lines": u.scope_lines})
    db.commit()
    return {"username": u.username, "created": True}


@router.put("/users/{username}/scope")
def set_scope(username: str, payload: ScopeIn, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    """Gán/sửa phạm vi dữ liệu (line/khu vực/loại test) cho tài khoản — admin."""
    require_role(user, Role.ADMIN)
    u = db.execute(select(UserModel).where(UserModel.username == username)).scalar_one_or_none()
    if not u:
        raise NotFoundError("Không tìm thấy tài khoản.")
    before = {"scope_lines": u.scope_lines, "scope_areas": u.scope_areas, "scope_qc": u.scope_qc,
              "scope_warehouse": getattr(u, "scope_warehouse", "*")}
    u.scope_lines = (payload.scope_lines or "*").strip() or "*"
    u.scope_areas = (payload.scope_areas or "*").strip() or "*"
    u.scope_qc = (payload.scope_qc or "*").strip() or "*"
    u.scope_warehouse = (payload.scope_warehouse or "*").strip() or "*"
    after = {"scope_lines": u.scope_lines, "scope_areas": u.scope_areas, "scope_qc": u.scope_qc,
             "scope_warehouse": u.scope_warehouse}
    record_audit(db, entity_type="auth", entity_id=username, action="set_scope", actor=user,
                 before=before, after=after)
    db.commit()
    return {"username": username, **after}


@router.post("/users/{username}/copy-permissions")
def copy_permissions(username: str, payload: CopyPermissionsIn, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """Copy toàn bộ hồ sơ quyền (vai trò/menu/quyền thao tác/4 chiều phạm vi dữ liệu) từ 1
    tài khoản nguồn sang tài khoản đích — admin, dùng khi 2 người làm cùng chức danh/vị trí
    để khỏi phải gán tay lại từng mục. KHÔNG đụng tới danh tính (username/mật khẩu/họ tên/
    chức danh hiển thị) hay trạng thái active/must_change_password của tài khoản đích."""
    require_role(user, Role.ADMIN)
    if payload.source_username == username:
        raise DomainError("Tài khoản nguồn và đích phải khác nhau.")
    src = db.execute(select(UserModel).where(UserModel.username == payload.source_username)).scalar_one_or_none()
    if not src:
        raise NotFoundError(f"Không tìm thấy tài khoản nguồn '{payload.source_username}'.")
    dst = db.execute(select(UserModel).where(UserModel.username == username)).scalar_one_or_none()
    if not dst:
        raise NotFoundError(f"Không tìm thấy tài khoản đích '{username}'.")
    before = {"role": dst.role, "allowed_views": dst.allowed_views, "permissions": dst.permissions,
              "scope_lines": dst.scope_lines, "scope_areas": dst.scope_areas, "scope_qc": dst.scope_qc,
              "scope_warehouse": getattr(dst, "scope_warehouse", "*")}
    dst.role = src.role
    dst.allowed_views = src.allowed_views
    dst.permissions = src.permissions
    dst.scope_lines = src.scope_lines
    dst.scope_areas = src.scope_areas
    dst.scope_qc = src.scope_qc
    dst.scope_warehouse = getattr(src, "scope_warehouse", "*")
    after = {"role": dst.role, "allowed_views": dst.allowed_views, "permissions": dst.permissions,
             "scope_lines": dst.scope_lines, "scope_areas": dst.scope_areas, "scope_qc": dst.scope_qc,
             "scope_warehouse": dst.scope_warehouse, "copied_from": src.username}
    record_audit(db, entity_type="auth", entity_id=username, action="copy_permissions", actor=user,
                before=before, after=after)
    db.commit()
    return {"username": username, **after}


@router.put("/users/{username}")
def edit_user(username: str, payload: EditUserIn, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    """Sửa trực tiếp họ tên/chức danh/vai trò/menu/quyền thao tác của 1 tài khoản đã tồn tại —
    admin. Không đụng tới mật khẩu, trạng thái active hay 4 chiều phạm vi dữ liệu (đã có
    endpoint riêng /scope)."""
    require_role(user, Role.ADMIN)
    if payload.role not in {r.value for r in Role}:
        raise PermissionError_(f"Vai trò không hợp lệ: {payload.role}")
    u = db.execute(select(UserModel).where(UserModel.username == username)).scalar_one_or_none()
    if not u:
        raise NotFoundError("Không tìm thấy tài khoản.")
    before = {"full_name": u.full_name, "job_title": u.job_title, "role": u.role,
              "allowed_views": u.allowed_views, "permissions": u.permissions}
    u.full_name = payload.full_name
    u.job_title = payload.job_title
    u.role = payload.role
    u.allowed_views = payload.allowed_views
    u.permissions = payload.permissions
    after = {"full_name": u.full_name, "job_title": u.job_title, "role": u.role,
             "allowed_views": u.allowed_views, "permissions": u.permissions}
    record_audit(db, entity_type="auth", entity_id=username, action="edit_user", actor=user,
                 before=before, after=after)
    db.commit()
    return {"username": username, **after}


@router.get("/scope-catalog")
def scope_catalog(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Danh mục khu vực + line + loại test QC hiện hữu (cho dropdown UI gán scope)."""
    from ..security import SCOPE_AREAS, SCOPE_WAREHOUSE_LOCATIONS
    from ..models.workorder import WorkOrder
    from ..models.quality import QualityResult
    from ..models.quality_ext import QCParameter
    from ..models.lines import ProductionLine
    wo_lines = {l for (l,) in db.execute(select(WorkOrder.line).distinct()).all() if l}
    master_lines = {l for (l,) in db.execute(select(ProductionLine.code)).all() if l}
    line_codes = sorted(wo_lines | master_lines)   # gộp line từ WO + danh mục dây chuyền
    line_names = dict(db.execute(select(ProductionLine.code, ProductionLine.name)).all())
    lines = [{"key": c, "label": f"{c} — {line_names[c]}" if line_names.get(c) and line_names[c] != c else c}
              for c in line_codes]
    # Nguồn chính là Danh mục chỉ tiêu chất lượng (QCParameter) — trước đây chỉ lấy
    # QualityResult.parameter (chỉ tiêu ĐÃ TỪNG được ghi kết quả) nên phần lớn Danh mục (chỉ
    # ghi nhận demo/test 1 vài chỉ tiêu) không hiện ra được ở đây dù đã khai báo đầy đủ. Gộp
    # thêm parameter cũ trong QualityResult không còn trong Danh mục (đổi mã/xóa) để không làm
    # mất scope đã gán cho tài khoản từ trước.
    from sqlalchemy import true
    qc_names = dict(db.execute(select(QCParameter.code, QCParameter.name).where(QCParameter.active == true())).all())
    legacy_qc_codes = {p for (p,) in db.execute(select(QualityResult.parameter).distinct()).all() if p}
    qc_codes = sorted(set(qc_names) | legacy_qc_codes)
    qc_params = [{"key": c, "label": f"{c} — {qc_names[c]}" if qc_names.get(c) and qc_names[c] != c else c}
                  for c in qc_codes]
    return {"areas": [{"key": k, "label": v} for k, v in SCOPE_AREAS.items()],
            "lines": lines, "qc_params": qc_params,
            "warehouse_locations": [{"key": k, "label": v} for k, v in SCOPE_WAREHOUSE_LOCATIONS.items()]}


@router.post("/users/{username}/toggle")
def toggle_user(username: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_role(user, Role.ADMIN)
    u = db.execute(select(UserModel).where(UserModel.username == username)).scalar_one_or_none()
    if not u:
        raise NotFoundError("Không tìm thấy tài khoản.")
    u.active = not u.active
    db.commit()
    return {"username": username, "active": u.active}


# ---- Mẫu chức danh (Role Templates) ----
# Admin tự khai báo tên chức danh + vai trò hệ thống + menu/quyền/phạm vi mặc định để chọn
# nhanh khi tạo tài khoản mới, không cần soạn tay từng trường mỗi lần. KHÔNG thay thế Role
# enum (vẫn dùng để require_role() chặn quyền ở backend) — chỉ là lớp đóng gói/đặt tên.

def _role_template_out(t: RoleTemplate) -> dict:
    return {"role_template_id": t.role_template_id, "name": t.name, "role": t.role,
            "allowed_views": t.allowed_views, "permissions": t.permissions,
            "scope_lines": t.scope_lines, "scope_areas": t.scope_areas,
            "scope_qc": t.scope_qc, "scope_warehouse": t.scope_warehouse, "active": t.active}


@router.get("/role-templates")
def list_role_templates(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_role(user, Role.ADMIN)
    rows = db.execute(select(RoleTemplate).order_by(RoleTemplate.name)).scalars().all()
    return [_role_template_out(t) for t in rows]


@router.post("/role-templates", status_code=201)
def create_role_template(payload: RoleTemplateIn, db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    require_role(user, Role.ADMIN)
    if payload.role not in {r.value for r in Role}:
        raise PermissionError_(f"Vai trò không hợp lệ: {payload.role}")
    if not payload.name.strip():
        raise DomainError("Tên chức danh không được để trống.")
    t = RoleTemplate(role_template_id=new_id(), name=payload.name.strip(), role=payload.role,
                      allowed_views=payload.allowed_views or "dashboard", permissions=payload.permissions or "",
                      scope_lines=payload.scope_lines or "*", scope_areas=payload.scope_areas or "*",
                      scope_qc=payload.scope_qc or "*", scope_warehouse=payload.scope_warehouse or "*",
                      active=True)
    db.add(t)
    record_audit(db, entity_type="role_template", entity_id=t.role_template_id, action="create",
                 actor=user, after={"name": t.name, "role": t.role})
    db.commit()
    return _role_template_out(t)


@router.put("/role-templates/{role_template_id}")
def update_role_template(role_template_id: str, payload: RoleTemplateIn, db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    require_role(user, Role.ADMIN)
    if payload.role not in {r.value for r in Role}:
        raise PermissionError_(f"Vai trò không hợp lệ: {payload.role}")
    t = db.get(RoleTemplate, role_template_id)
    if not t:
        raise NotFoundError("Không tìm thấy mẫu chức danh.")
    before = _role_template_out(t)
    t.name = payload.name.strip() or t.name
    t.role = payload.role
    t.allowed_views = payload.allowed_views or "dashboard"
    t.permissions = payload.permissions or ""
    t.scope_lines = payload.scope_lines or "*"
    t.scope_areas = payload.scope_areas or "*"
    t.scope_qc = payload.scope_qc or "*"
    t.scope_warehouse = payload.scope_warehouse or "*"
    record_audit(db, entity_type="role_template", entity_id=t.role_template_id, action="update",
                 actor=user, before=before, after=_role_template_out(t))
    db.commit()
    return _role_template_out(t)


@router.delete("/role-templates/{role_template_id}", status_code=204)
def delete_role_template(role_template_id: str, db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    require_role(user, Role.ADMIN)
    t = db.get(RoleTemplate, role_template_id)
    if not t:
        raise NotFoundError("Không tìm thấy mẫu chức danh.")
    record_audit(db, entity_type="role_template", entity_id=t.role_template_id, action="delete",
                 actor=user, before={"name": t.name, "role": t.role})
    db.delete(t)
    db.commit()
