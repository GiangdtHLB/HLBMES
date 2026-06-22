"""Identity tối giản cho MVP (tài liệu §7.8, §10.2).

Production phải dùng Enterprise IdP/SSO + MFA. Ở MVP, danh tính được truyền
qua header X-User và X-Role để minh hoạ RBAC và segregation of duties.
"""

import hashlib
import secrets
from dataclasses import dataclass
from typing import Optional

from fastapi import Header

from .common import Role, utcnow
from .errors import PermissionError_


@dataclass
class User:
    username: str
    role: str
    full_name: Optional[str] = None
    job_title: Optional[str] = None
    permissions: object = "*"   # set[str] hoặc "*" (toàn quyền)


# ---- Ma trận quyền chi tiết (catalog) ----
# key -> nhãn hiển thị. Áp ở tầng router cho các thao tác nhạy cảm.
PERMISSION_CATALOG = {
    "order.create": "Tạo/điều phối lệnh sản xuất",
    "wo.manage": "Lập/sửa lệnh sản xuất (work order)",
    "wo.dispatch": "Điều độ — phát mẻ từ lệnh",
    "batch.create": "Tạo mẻ sản xuất",
    "batch.execute": "Thực thi mẻ (chạy/consume/produce/actual)",
    "recipe.author": "Soạn/sửa công thức (version)",
    "recipe.approve": "Duyệt/ban hành công thức",
    "quality.release": "Release chất lượng (QC)",
    "quality.deviation": "Mở/xử lý deviation",
    "ebr.sign": "Ký điện tử hồ sơ mẻ (EBR)",
    "ebr.approve": "Phê duyệt & khóa hồ sơ mẻ (EBR)",
    "warehouse.receive": "Nhập kho",
    "warehouse.issue": "Xuất/hoàn/chuyển kho",
    "maintenance.manage": "Quản lý bảo trì/sự cố",
    "calibration.manage": "Quản lý kiểm định",
    "energy.update": "Cập nhật số liệu năng lượng",
    "user.manage": "Quản trị tài khoản",
    "integration.manage": "Quản trị API key/webhook",
}


def require_perm(user: User, perm: str) -> None:
    if user.role == Role.ADMIN.value:
        return
    perms = user.permissions
    if perms == "*":
        return
    if not perms or perm not in perms:
        label = PERMISSION_CATALOG.get(perm, perm)
        raise PermissionError_(
            f"Chức danh của '{user.username}' không có quyền: {label} ({perm})."
        )


# ---- Mật khẩu (pbkdf2 — stdlib, không cần thư viện ngoài) ----
def hash_password(pw: str, salt: Optional[str] = None) -> str:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100_000)
    return f"{salt}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        salt, h = stored.split("$", 1)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100_000)
    return secrets.compare_digest(dk.hex(), h)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def get_current_user(
    authorization: str = Header(default=""),
    x_user: str = Header(default="", alias="X-User"),
    x_role: str = Header(default="", alias="X-Role"),
) -> User:
    """Ưu tiên token (Authorization: Bearer …); fallback X-User/X-Role cho /docs & test."""
    if authorization.startswith("Bearer "):
        from sqlalchemy import select
        from .database import SessionLocal
        from .models.auth import User as UserModel, UserSession
        token = authorization[7:]
        db = SessionLocal()
        try:
            sess = db.get(UserSession, token)
            if not sess:
                raise PermissionError_("Phiên đăng nhập không hợp lệ.")
            exp = sess.expires_at
            now = utcnow()
            if exp.tzinfo is None:          # SQLite trả naive → coi như UTC
                now = now.replace(tzinfo=None)
            if exp < now:
                raise PermissionError_("Phiên đăng nhập đã hết hạn.")
            u = db.execute(select(UserModel).where(UserModel.username == sess.username)).scalar_one_or_none()
            if not u or not u.active:
                raise PermissionError_("Tài khoản không tồn tại hoặc đã bị khoá.")
            perms = "*" if (u.permissions or "").strip() == "*" else {
                p.strip() for p in (u.permissions or "").split(",") if p.strip()}
            return User(username=u.username, role=u.role, full_name=u.full_name,
                        job_title=u.job_title, permissions=perms)
        finally:
            db.close()
    # Fallback X-User/X-Role: CHỈ khi bật cờ dev (mặc định tắt) — tránh bypass quyền.
    from .config import DEV_HEADER_AUTH
    if DEV_HEADER_AUTH and x_role:
        role = x_role if x_role in {r.value for r in Role} else Role.OPERATOR.value
        return User(username=x_user or "dev", role=role, permissions="*")
    raise PermissionError_("Cần đăng nhập (thiếu hoặc sai token).")


def require_role(user: User, *allowed: Role) -> None:
    allowed_values = {r.value for r in allowed}
    if user.role == Role.ADMIN.value:
        return  # admin bỏ qua kiểm tra vai trò (vẫn bị ràng buộc SoD bên dưới)
    if user.role not in allowed_values:
        raise PermissionError_(
            f"Vai trò '{user.role}' không được phép; yêu cầu một trong {sorted(allowed_values)}."
        )


def require_api_key(write: bool = False):
    """Dependency factory: xác thực X-API-Key cho cổng /api/v1 (phần mềm ngoài).

    Tách biệt hoàn toàn với xác thực người dùng nội bộ (X-User/X-Role)."""
    from fastapi import Header
    from sqlalchemy import select
    from .database import SessionLocal
    from .models.integration import ApiKey

    def _dep(x_api_key: str = Header(default="", alias="X-API-Key")):
        if not x_api_key:
            raise PermissionError_("Thiếu X-API-Key.")
        db = SessionLocal()
        try:
            key = db.execute(select(ApiKey).where(ApiKey.token == x_api_key)).scalar_one_or_none()
            if not key or not key.active:
                raise PermissionError_("API key không hợp lệ hoặc đã khoá.")
            if write and "write" not in key.scopes:
                raise PermissionError_("API key không có quyền ghi (scope 'write').")
            key.call_count += 1
            from .common import utcnow as _now
            key.last_used_at = _now()
            db.commit()
            return {"name": key.name, "scopes": key.scopes}
        finally:
            db.close()

    return _dep


def enforce_sod(actor_username: Optional[str], current: User, action: str) -> None:
    """Segregation of duties: người thực hiện bước sau không được trùng người
    thực hiện bước trước (vd: soạn recipe vs duyệt recipe, ghi QC vs release)."""
    if actor_username and actor_username == current.username:
        raise PermissionError_(
            f"Vi phạm phân tách nhiệm vụ (SoD): '{current.username}' không thể tự "
            f"{action} thứ do chính mình tạo/ghi."
        )
