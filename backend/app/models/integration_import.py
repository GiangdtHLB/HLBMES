"""Import Mapping Explorer — mô hình dữ liệu cho luồng import file ngoài
(CSV/Excel từ phần mềm Quản lý sản xuất / Brawmart) vào MES.

Tách hoàn toàn khỏi bảng nghiệp vụ lõi: KHÔNG ALTER core. Cột dư không map được
giữ trong raw_payload (JSON) ở tầng integration để sau thiết kế field chuẩn.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Unicode, UnicodeText
from sqlalchemy.orm import Mapped, mapped_column

from ..common import new_id, utcnow
from ..database import Base


class IntegrationMappingProfile(Base):
    """Hồ sơ mapping tái sử dụng: file nguồn → bảng MES, cấu hình cột (không hardcode)."""
    __tablename__ = "integration_mapping_profile"

    profile_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(Unicode(255), index=True)
    target_table: Mapped[str] = mapped_column(Unicode(64), index=True)
    source_system: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)  # vd brawmart/qlsx
    source_type: Mapped[str] = mapped_column(Unicode(32), default="csv")  # csv | excel
    key_field: Mapped[str] = mapped_column(Unicode(64), default="code")   # cột upsert (code/external_code)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IntegrationColumnMapping(Base):
    """Một dòng map: cột file (source_column) → cột bảng MES (target_column),
    kèm default_value khi file thiếu trường bắt buộc."""
    __tablename__ = "integration_column_mapping"

    mapping_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    profile_id: Mapped[str] = mapped_column(Unicode(64), ForeignKey("integration_mapping_profile.profile_id"), index=True)
    target_column: Mapped[str] = mapped_column(Unicode(64))
    source_column: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    default_value: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    transform_rule: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)   # {"type":...,"params":...}
    validation_rule: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class IntegrationImportFile(Base):
    """File đã upload (chỉ đọc, chưa import). Lưu metadata + mẫu 50 dòng + đường dẫn."""
    __tablename__ = "integration_import_file"

    file_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    filename: Mapped[str] = mapped_column(Unicode(255))
    source_type: Mapped[str] = mapped_column(Unicode(32), default="csv")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    columns: Mapped[list] = mapped_column(JSON, default=list)   # danh sách cột nguồn
    sample: Mapped[list] = mapped_column(JSON, default=list)    # preview tối đa 50 dòng
    stored_path: Mapped[Optional[str]] = mapped_column(Unicode(512), nullable=True)
    uploaded_by: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IntegrationImportRun(Base):
    """Một lần import: liên kết file + (tùy chọn) profile + bảng đích + summary."""
    __tablename__ = "integration_import_run"

    run_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    file_id: Mapped[Optional[str]] = mapped_column(Unicode(64), ForeignKey("integration_import_file.file_id"), nullable=True, index=True)
    profile_id: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    source_system: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    target_table: Mapped[str] = mapped_column(Unicode(64), index=True)
    key_field: Mapped[str] = mapped_column(Unicode(64), default="code")
    status: Mapped[str] = mapped_column(Unicode(32), default="pending")  # pending|validated|done|failed
    total: Mapped[int] = mapped_column(Integer, default=0)
    inserted: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    errored: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    run_by: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class IntegrationImportError(Base):
    """Lỗi theo từng dòng/cột trong một lần import (để soi & sửa file nguồn)."""
    __tablename__ = "integration_import_error"

    error_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(Unicode(64), ForeignKey("integration_import_run.run_id"), index=True)
    row_index: Mapped[int] = mapped_column(Integer, default=0)
    column: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    value: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    message: Mapped[str] = mapped_column(UnicodeText)
    severity: Mapped[str] = mapped_column(Unicode(16), default="error")  # error | warning
    raw_payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # dòng gốc (gồm cột dư)
