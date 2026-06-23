"""Tài khoản người dùng + phiên đăng nhập (token).

User gắn với một vai trò nghiệp vụ (Role: quyết định quyền/SoD ở backend) và một
chức danh nhà máy + danh sách menu được phép (allowed_views) để cá nhân hoá UI.
Production nên thay bằng IdP/SSO + MFA (tài liệu §10.2); đây là MVP nội bộ.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from ..common import new_id, utcnow
from ..database import Base


class User(Base):
    __tablename__ = "app_user"

    user_id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String)
    full_name: Mapped[str] = mapped_column(String)
    job_title: Mapped[str] = mapped_column(String)          # chức danh nhà máy
    role: Mapped[str] = mapped_column(String)               # vai trò nghiệp vụ (Role enum)
    allowed_views: Mapped[str] = mapped_column(String, default="dashboard")  # csv hoặc "*"
    permissions: Mapped[str] = mapped_column(String, default="")  # csv quyền chi tiết hoặc "*"
    # Phạm vi dữ liệu (data-scoping §10.2): csv hoặc "*" (toàn nhà máy).
    scope_lines: Mapped[str] = mapped_column(String, default="*")
    scope_areas: Mapped[str] = mapped_column(String, default="*")
    scope_qc: Mapped[str] = mapped_column(String, default="*")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class UserSession(Base):
    __tablename__ = "user_session"

    token: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    username: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
