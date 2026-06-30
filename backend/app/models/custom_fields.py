"""Dynamic Custom Fields (EAV) — giữ cột ngoài schema core mà không ALTER core.

CustomFieldDefinition: khai báo field động cho một bảng đích whitelist.
CustomFieldValue: giá trị field động theo từng record (table_name + record_id + field_key).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Unicode, UnicodeText, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..common import new_id, utcnow
from ..database import Base


class CustomFieldDefinition(Base):
    __tablename__ = "custom_field_definition"
    __table_args__ = (UniqueConstraint("table_name", "field_key", name="uq_custom_field_def"),)

    id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    table_name: Mapped[str] = mapped_column(Unicode(64), index=True)
    field_key: Mapped[str] = mapped_column(Unicode(64))
    display_name: Mapped[str] = mapped_column(Unicode(255))
    data_type: Mapped[str] = mapped_column(Unicode(16), default="string")  # string|int|float|bool|date
    is_required: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CustomFieldValue(Base):
    __tablename__ = "custom_field_value"
    __table_args__ = (UniqueConstraint("table_name", "record_id", "field_key", name="uq_custom_field_value"),)

    id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    table_name: Mapped[str] = mapped_column(Unicode(64))
    record_id: Mapped[str] = mapped_column(Unicode(64))
    field_key: Mapped[str] = mapped_column(Unicode(64))
    field_value: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
