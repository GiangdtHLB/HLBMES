"""Bao bì tuần hoàn (returnable assets): vỏ chai, két/gông, keg inox.

PackagingType = danh mục loại bao bì + tồn kho (on_hand) và đang lưu hành ngoài thị
trường (in_circulation). PackagingMove = nhật ký biến động (nhập/xuất/thu hồi/loại bỏ/kiểm kê).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ..common import new_id, utcnow
from ..database import Base


class PackagingType(Base):
    __tablename__ = "packaging_type"

    pkg_id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String, index=True)   # vo_chai | ket_gong | keg
    material: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # glass/plastic/steel...
    volume_l: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # dung tích (L)
    deposit: Mapped[float] = mapped_column(Float, default=0.0)   # tiền cược / đơn vị
    on_hand: Mapped[float] = mapped_column(Float, default=0.0)   # tồn trong kho
    in_circulation: Mapped[float] = mapped_column(Float, default=0.0)  # đang lưu hành (ngoài thị trường)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PackagingMove(Base):
    __tablename__ = "packaging_move"

    move_id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    pkg_id: Mapped[str] = mapped_column(ForeignKey("packaging_type.pkg_id"), index=True)
    kind: Mapped[str] = mapped_column(String)   # nhap | xuat | thu_hoi | loai_bo | kiem_ke
    qty: Mapped[float] = mapped_column(Float, default=0.0)
    ref: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
