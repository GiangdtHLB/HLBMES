"""Danh mục dây chuyền sản xuất/đóng gói (master) — để theo dõi OEE theo line.

Trước đây `line` chỉ là chuỗi tự do trong OEERecord/WorkOrder. ProductionLine cho phép
thêm/ngừng dây chuyền có quản lý; OEE & lập lịch tham chiếu danh mục này.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Float, Unicode
from sqlalchemy.orm import Mapped, mapped_column

from ..common import UTCDateTime, new_id, utcnow
from ..database import Base


class ProductionLine(Base):
    __tablename__ = "production_line"

    line_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)   # tên line (khớp OEERecord.line)
    name: Mapped[str] = mapped_column(Unicode(255))
    kind: Mapped[str] = mapped_column(Unicode(255), default="line", index=True)  # line | tank | brewhouse
    area: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)   # khu vực (chiet/len_men/...)
    ideal_rate_per_min: Mapped[float] = mapped_column(Float, default=0.0)  # tốc độ lý tưởng (chai-lon/phút)
    # Công suất (kind="line") — hiển thị/khai báo ở Danh mục "Dây chuyền sản xuất", tách
    # riêng khỏi ideal_rate_per_min (dùng cho tính OEE) để không ràng buộc đơn vị cố định.
    capacity_uom: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)  # VD "lon/phút"
    # Thể tích (kind="tank"/"tank_bbt") — hiển thị/khai báo ở Danh mục "Tank lên men"/"Tank thành phẩm".
    volume: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume_uom: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)  # VD "hl"
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
