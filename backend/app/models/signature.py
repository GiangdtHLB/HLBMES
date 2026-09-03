"""Chữ ký điện tử + snapshot EBR (tài liệu §7.6, §10.3 — tư duy 21 CFR Part 11).

E-signature yêu cầu re-authentication; mỗi chữ ký lưu ý nghĩa, người ký, lý do,
và hash nội dung hồ sơ tại thời điểm ký. EBRSnapshot là bản đóng băng bất biến
của hồ sơ mẻ khi khóa (có content_hash để kiểm tra toàn vẹn)."""

from datetime import datetime
from typing import Optional

from sqlalchemy import UnicodeText, JSON, Integer, Unicode, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..common import UTCDateTime, new_id, utcnow
from ..database import Base


class Signature(Base):
    __tablename__ = "esignature"

    sig_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    scope_type: Mapped[str] = mapped_column(Unicode(255), index=True)   # ebr | release | deviation
    scope_id: Mapped[str] = mapped_column(Unicode(64), index=True)
    meaning: Mapped[str] = mapped_column(Unicode(255))                  # ý nghĩa chữ ký
    signed_by: Mapped[str] = mapped_column(Unicode(255))
    role: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    content_hash: Mapped[str] = mapped_column(Unicode(128))            # hash hồ sơ tại thời điểm ký
    signed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class EBRSnapshot(Base):
    """batch_id: cột "liên kết mềm" tái dùng cho batch_id/tank_id/filter_lot_id/pack_lot_id tùy
    scope (xem services/ebr.py) — không có FK constraint thật.

    UniqueConstraint(batch_id, snapshot_version): backstop DB thật cho race condition giữa khóa
    thủ công (lock_tank/lock_filter_lot/lock()) và cascade khóa từ lô thành phẩm
    (_cascade_lock -> _lock_*_snapshot) — trước đây CHỈ có check-rồi-ghi kiểu Python thường
    (`if obj.locked: return`), 2 giao dịch gần như đồng thời đều đọc locked=False trước khi cái
    nào commit xong đều tạo được snapshot riêng, tạo ra 2 bản snapshot cho cùng 1 đối tượng dù
    docstring khẳng định "chỉ tạo ĐÚNG 1 LẦN" (2026-09-02, audit module "Mẻ sản xuất"). Ràng buộc
    này bắt lỗi ở tầng DB (IntegrityError) — services/ebr.py bắt lỗi đó và coi như "đã khóa rồi",
    kết hợp với with_for_update() khi đọc đối tượng ĐANG khóa để tuần tự hoá 2 giao dịch race
    trên các DB có row-lock thật (SQL Server/Postgres)."""
    __tablename__ = "ebr_snapshot"
    __table_args__ = (UniqueConstraint("batch_id", "snapshot_version", name="uq_ebr_snapshot_scope_version"),)

    snap_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(Unicode(64), index=True)
    snapshot_version: Mapped[int] = mapped_column(Integer, default=1)
    content_hash: Mapped[str] = mapped_column(Unicode(128))
    content: Mapped[dict] = mapped_column(JSON)                  # hồ sơ đóng băng
    locked_by: Mapped[str] = mapped_column(Unicode(255))
    locked_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
