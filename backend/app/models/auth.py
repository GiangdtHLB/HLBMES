"""Tài khoản người dùng + phiên đăng nhập (token).

User gắn với một vai trò nghiệp vụ (Role: quyết định quyền/SoD ở backend) và một
chức danh nhà máy + danh sách menu được phép (allowed_views) để cá nhân hoá UI.
Production nên thay bằng IdP/SSO + MFA (tài liệu §10.2); đây là MVP nội bộ.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import UnicodeText, Boolean, Unicode
from sqlalchemy.orm import Mapped, mapped_column

from ..common import UTCDateTime, new_id, utcnow
from ..database import Base


class User(Base):
    __tablename__ = "app_user"

    user_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(Unicode(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Unicode(128))
    full_name: Mapped[str] = mapped_column(Unicode(255))
    job_title: Mapped[str] = mapped_column(Unicode(255))          # chức danh nhà máy
    role: Mapped[str] = mapped_column(Unicode(255))               # vai trò nghiệp vụ (Role enum)
    allowed_views: Mapped[str] = mapped_column(UnicodeText, default="dashboard")  # csv hoặc "*"
    permissions: Mapped[str] = mapped_column(UnicodeText, default="")  # csv quyền chi tiết hoặc "*"
    # Phạm vi dữ liệu (data-scoping §10.2): csv hoặc "*" (toàn nhà máy).
    scope_lines: Mapped[str] = mapped_column(Unicode(255), default="*")
    scope_areas: Mapped[str] = mapped_column(Unicode(255), default="*")
    scope_qc: Mapped[str] = mapped_column(Unicode(255), default="*")
    # "cong_ty" | "phan_xuong" | "*" — chặn thao tác kho NVL ngoài địa điểm được phân.
    scope_warehouse: Mapped[str] = mapped_column(Unicode(255), default="*")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Buộc đổi mật khẩu lần đăng nhập đầu (admin tạo bằng mật khẩu mặc định).
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)


class RoleTemplate(Base):
    """Mẫu chức danh — admin tự khai báo (tên chức danh + vai trò hệ thống + menu/quyền/phạm
    vi mặc định) để chọn nhanh khi tạo tài khoản mới, không cần soạn tay từng trường. Vai trò
    hệ thống (role) vẫn phải là 1 trong 5 giá trị Role enum vì đó là thứ backend dùng để chặn
    quyền (require_role) — mẫu chức danh chỉ là lớp đặt tên/đóng gói bên trên, không thay thế
    cơ chế phân quyền theo Role."""
    __tablename__ = "role_template"

    role_template_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(Unicode(255))                # tên chức danh, vd "Trưởng ca trực"
    role: Mapped[str] = mapped_column(Unicode(255))                # vai trò hệ thống (Role enum)
    allowed_views: Mapped[str] = mapped_column(UnicodeText, default="dashboard")
    permissions: Mapped[str] = mapped_column(UnicodeText, default="")
    scope_lines: Mapped[str] = mapped_column(Unicode(255), default="*")
    scope_areas: Mapped[str] = mapped_column(Unicode(255), default="*")
    scope_qc: Mapped[str] = mapped_column(Unicode(255), default="*")
    scope_warehouse: Mapped[str] = mapped_column(Unicode(255), default="*")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class UserSession(Base):
    __tablename__ = "user_session"

    token: Mapped[str] = mapped_column(Unicode(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(Unicode(64), index=True)
    username: Mapped[str] = mapped_column(Unicode(255))
    role: Mapped[str] = mapped_column(Unicode(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
