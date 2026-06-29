"""Identity tối giản cho MVP (tài liệu §7.8, §10.2).

Production phải dùng Enterprise IdP/SSO + MFA. Ở MVP, danh tính được truyền
qua header X-User và X-Role để minh hoạ RBAC và segregation of duties.
"""

import hashlib
import secrets
from dataclasses import dataclass
from typing import Optional

from fastapi import Header, Request

from .common import Role, utcnow
from .errors import DomainError, PermissionError_


@dataclass
class User:
    username: str
    role: str
    full_name: Optional[str] = None
    job_title: Optional[str] = None
    permissions: object = "*"   # set[str] hoặc "*" (toàn quyền)
    # Phạm vi dữ liệu (data-scoping §10.2): "*" = toàn nhà máy, hoặc set[str] cụ thể.
    scope_lines: object = "*"   # line đóng gói / dây chuyền
    scope_areas: object = "*"   # khu vực: nau|len_men|loc|chiet|kho
    scope_qc: object = "*"      # loại test QC được phân (theo tên parameter)
    must_change_password: bool = False  # đang dùng mật khẩu mặc định → buộc đổi trước khi thao tác


# ---- Ma trận quyền chi tiết (catalog) ----
# key -> nhãn hiển thị. Áp ở tầng router cho các thao tác nhạy cảm.
PERMISSION_CATALOG = {
    "master.manage": "Quản lý danh mục sản phẩm/vật tư",
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


PASSWORD_MIN_LEN = 8


def validate_password_strength(pw: str, username: Optional[str] = None) -> None:
    """Chính sách mật khẩu mạnh (dùng chung: đổi mật khẩu + tạo tài khoản).

    Yêu cầu: ≥8 ký tự, có cả chữ và số, không chứa tên đăng nhập.
    Vi phạm → DomainError (HTTP 409) với thông báo rõ ràng (không phải 403).
    """
    pw = pw or ""
    if len(pw) < PASSWORD_MIN_LEN:
        raise DomainError(f"Mật khẩu phải có tối thiểu {PASSWORD_MIN_LEN} ký tự.")
    if not any(c.isalpha() for c in pw):
        raise DomainError("Mật khẩu phải có ít nhất một chữ cái.")
    if not any(c.isdigit() for c in pw):
        raise DomainError("Mật khẩu phải có ít nhất một chữ số.")
    if username and len(username) >= 3 and username.lower() in pw.lower():
        raise DomainError("Mật khẩu không được chứa tên đăng nhập.")


def new_token() -> str:
    return secrets.token_urlsafe(32)


# Đường dẫn được phép khi tài khoản đang buộc đổi mật khẩu (chưa đổi → chặn phần còn lại).
_MUST_CHANGE_ALLOW = {"/api/auth/change-password", "/api/auth/me", "/api/auth/logout"}


def get_current_user(
    request: Request = None,
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
            must_change = bool(getattr(u, "must_change_password", False))
            # Buộc đổi mật khẩu lần đầu: chặn mọi thao tác trừ đổi mật khẩu/hồ sơ/đăng xuất.
            if must_change and request is not None and request.url.path not in _MUST_CHANGE_ALLOW:
                raise PermissionError_(
                    "Cần đổi mật khẩu lần đầu trước khi sử dụng hệ thống "
                    "(POST /api/auth/change-password)."
                )
            perms = "*" if (u.permissions or "").strip() == "*" else {
                p.strip() for p in (u.permissions or "").split(",") if p.strip()}
            return User(username=u.username, role=u.role, full_name=u.full_name,
                        job_title=u.job_title, permissions=perms,
                        scope_lines=_parse_scope(getattr(u, "scope_lines", "*")),
                        scope_areas=_parse_scope(getattr(u, "scope_areas", "*")),
                        scope_qc=_parse_scope(getattr(u, "scope_qc", "*")),
                        must_change_password=must_change)
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


# ============================================================================
# RBAC data-scoping (§10.2): phân quyền theo phạm vi dữ liệu (line/khu vực/loại
# test) — bổ sung cho require_perm (phân quyền theo *hành động*). Một operator
# Line-1 chỉ thao tác/nhìn mẻ & lệnh thuộc Line-1; KCS chỉ ghi loại test mình phụ trách.
# ============================================================================

# Danh mục khu vực chuẩn (khớp 'stage' trong process/brewing và Equipment.system).
SCOPE_AREAS = {
    "nau": "Nấu",
    "len_men": "Lên men",
    "loc": "Lọc",
    "chiet": "Chiết",
    "kho": "Kho",
}


def _parse_scope(raw) -> object:
    """Chuẩn hóa giá trị scope từ DB (csv|'*') thành '*' hoặc set[str]."""
    if raw is None:
        return "*"
    if not isinstance(raw, str):
        return raw  # đã là set (vd test) → giữ nguyên
    raw = raw.strip()
    if raw == "" or raw == "*":
        return "*"
    return {s.strip() for s in raw.split(",") if s.strip()}


def has_scope(user: User, dimension: str, value) -> bool:
    """True nếu user được phép với 'value' ở chiều 'dimension' (lines|areas|qc).

    - admin hoặc scope '*' → luôn True.
    - value rỗng/None (bản ghi chưa gắn line/khu vực) → True (không khóa cứng dữ liệu cũ).
    """
    if user.role == Role.ADMIN.value:
        return True
    scope = getattr(user, {"lines": "scope_lines", "areas": "scope_areas",
                           "qc": "scope_qc"}.get(dimension, "scope_lines"), "*")
    if scope == "*":
        return True
    if value is None or value == "":
        return True
    return value in scope


def require_scope(user: User, dimension: str, value) -> None:
    """Chặn thao tác ngoài phạm vi (gọi SAU require_perm/require_role)."""
    if not has_scope(user, dimension, value):
        label = {"lines": "line", "areas": "khu vực", "qc": "loại test"}.get(dimension, dimension)
        raise PermissionError_(
            f"Ngoài phạm vi được phân ({label}='{value}'): tài khoản '{user.username}' "
            f"không có quyền thao tác/xem dữ liệu này."
        )


def filter_by_scope(user: User, rows: list, dimension: str, key) -> list:
    """Lọc list (dict hoặc ORM) theo scope. key: callable(row)->value hoặc tên thuộc tính."""
    if user.role == Role.ADMIN.value:
        return rows
    getval = key if callable(key) else (
        lambda r: r.get(key) if isinstance(r, dict) else getattr(r, key, None))
    return [r for r in rows if has_scope(user, dimension, getval(r))]
