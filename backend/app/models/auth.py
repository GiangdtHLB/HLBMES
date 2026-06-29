"""Tài khoản người dùng + phiên đăng nhập (token).

User gắn với một vai trò nghiệp vụ (Role: quyết định quyền/SoD ở backend) và một
chức danh nhà máy + danh sách menu được phép (allowed_views) để cá nhân hoá UI.
Production nên thay bằng IdP/SSO + MFA (tài liệu §10.2); đây là MVP nội bộ.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Text, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from ..common import new_id, utcnow
from ..database import Base


class User(Base):
    __tablename__ = "app_user"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    full_name: Mapped[str] = mapped_column(String(255))
    job_title: Mapped[str] = mapped_column(String(255))          # chức danh nhà máy
    role: Mapped[str] = mapped_column(String(255))               # vai trò nghiệp vụ (Role enum)
    allowed_views: Mapped[str] = mapped_column(Text, default="dashboard")  # csv hoặc "*"
    permissions: Mapped[str] = mapped_column(Text, default="")  # csv quyền chi tiết hoặc "*"
    # Phạm vi dữ liệu (data-scoping §10.2): csv hoặc "*" (toàn nhà máy).
    scope_lines: Mapped[str] = mapped_column(String(255), default="*")
    scope_areas: Mapped[str] = mapped_column(String(255), default="*")
    scope_qc: Mapped[str] = mapped_column(String(255), default="*")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Buộc đổi mật khẩu lần đăng nhập đầu (admin tạo bằng mật khẩu mặc định).
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class UserSession(Base):
    __tablename__ = "user_session"

    token: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    username: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
