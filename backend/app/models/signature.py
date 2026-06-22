"""Chữ ký điện tử + snapshot EBR (tài liệu §7.6, §10.3 — tư duy 21 CFR Part 11).

E-signature yêu cầu re-authentication; mỗi chữ ký lưu ý nghĩa, người ký, lý do,
và hash nội dung hồ sơ tại thời điểm ký. EBRSnapshot là bản đóng băng bất biến
của hồ sơ mẻ khi khóa (có content_hash để kiểm tra toàn vẹn)."""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..common import new_id, utcnow
from ..database import Base


class Signature(Base):
    __tablename__ = "esignature"

    sig_id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    scope_type: Mapped[str] = mapped_column(String, index=True)   # ebr | release | deviation
    scope_id: Mapped[str] = mapped_column(String, index=True)
    meaning: Mapped[str] = mapped_column(String)                  # ý nghĩa chữ ký
    signed_by: Mapped[str] = mapped_column(String)
    role: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    content_hash: Mapped[str] = mapped_column(String)            # hash hồ sơ tại thời điểm ký
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EBRSnapshot(Base):
    __tablename__ = "ebr_snapshot"

    snap_id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(String, index=True)
    snapshot_version: Mapped[int] = mapped_column(Integer, default=1)
    content_hash: Mapped[str] = mapped_column(String)
    content: Mapped[dict] = mapped_column(JSON)                  # hồ sơ đóng băng
    locked_by: Mapped[str] = mapped_column(String)
    locked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
