"""Danh mục dây chuyền sản xuất/đóng gói (master) — để theo dõi OEE theo line.

Trước đây `line` chỉ là chuỗi tự do trong OEERecord/WorkOrder. ProductionLine cho phép
thêm/ngừng dây chuyền có quản lý; OEE & lập lịch tham chiếu danh mục này.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from ..common import new_id, utcnow
from ..database import Base


class ProductionLine(Base):
    __tablename__ = "production_line"

    line_id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String, unique=True, index=True)   # tên line (khớp OEERecord.line)
    name: Mapped[str] = mapped_column(String)
    area: Mapped[Optional[str]] = mapped_column(String, nullable=True)   # khu vực (chiet/...)
    ideal_rate_per_min: Mapped[float] = mapped_column(Float, default=0.0)  # tốc độ lý tưởng (chai-lon/phút)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
