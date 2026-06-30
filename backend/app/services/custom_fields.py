"""Dynamic Custom Fields — CRUD định nghĩa + ghi/đọc giá trị (EAV).

Chỉ cho bảng trong whitelist import. KHÔNG ALTER core: giá trị lưu ở custom_field_value.
"""

import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..common import new_id, utcnow
from ..errors import DomainError
from ..models.custom_fields import CustomFieldDefinition, CustomFieldValue
from . import import_targets

DATA_TYPES = {"string", "int", "float", "bool", "date"}


def slugify(name: str) -> str:
    s = (name or "").strip()
    s = s.replace("đ", "d").replace("Đ", "D")
    s = "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))  # bỏ dấu tiếng Việt
    s = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    return s[:60] or "field"


def _ensure_table(table: str):
    if not import_targets.is_allowed(table):
        raise DomainError(f"Bảng '{table}' không được phép tạo custom field (chỉ whitelist master).")


def create_definition(db: Session, table: str, display_name: str, data_type: str,
                      field_key: str = None, is_required: bool = False) -> dict:
    _ensure_table(table)
    if data_type not in DATA_TYPES:
        raise DomainError(f"data_type không hợp lệ: {data_type} (cho phép: {sorted(DATA_TYPES)})")
    key = slugify(field_key or display_name)
    # không trùng cột core
    core = {c["name"] for c in import_targets.target_schema(table)["columns"]}
    if key in core:
        raise DomainError(f"'{key}' trùng cột core của bảng {table} — hãy map vào cột core đó.")
    existing = db.execute(select(CustomFieldDefinition).where(
        CustomFieldDefinition.table_name == table, CustomFieldDefinition.field_key == key)).scalar_one_or_none()
    if existing:
        if not existing.is_active:
            existing.is_active = True
            db.commit()
        return _def_dict(existing)
    d = CustomFieldDefinition(id=new_id(), table_name=table, field_key=key, display_name=display_name,
                              data_type=data_type, is_required=is_required, is_active=True, created_at=utcnow())
    db.add(d)
    db.commit()
    return _def_dict(d)


def _def_dict(d: CustomFieldDefinition) -> dict:
    return {"id": d.id, "table_name": d.table_name, "field_key": d.field_key,
            "display_name": d.display_name, "data_type": d.data_type,
            "is_required": d.is_required, "is_active": d.is_active}


def list_definitions(db: Session, table: str, active_only: bool = False) -> list:
    stmt = select(CustomFieldDefinition).where(CustomFieldDefinition.table_name == table)
    if active_only:
        stmt = stmt.where(CustomFieldDefinition.is_active == True)  # noqa: E712
    return [_def_dict(d) for d in db.execute(stmt.order_by(CustomFieldDefinition.created_at)).scalars().all()]


def active_columns(db: Session, table: str) -> list:
    """Trả custom field active dưới dạng 'column' để ghép vào target_schema."""
    out = []
    for d in list_definitions(db, table, active_only=True):
        out.append({"name": d["field_key"], "type": d["data_type"], "nullable": not d["is_required"],
                    "required": d["is_required"], "unique": False, "max_length": None,
                    "primary_key": False, "has_default": False, "is_custom": True,
                    "display_name": d["display_name"]})
    return out


def upsert_value(db: Session, table: str, record_id: str, field_key: str, value) -> None:
    sval = None if value is None else (value if isinstance(value, str) else str(value))
    row = db.execute(select(CustomFieldValue).where(
        CustomFieldValue.table_name == table, CustomFieldValue.record_id == record_id,
        CustomFieldValue.field_key == field_key)).scalar_one_or_none()
    if row:
        row.field_value = sval
    else:
        db.add(CustomFieldValue(id=new_id(), table_name=table, record_id=record_id,
                                field_key=field_key, field_value=sval, created_at=utcnow()))


def get_values(db: Session, table: str, record_id: str) -> dict:
    rows = db.execute(select(CustomFieldValue).where(
        CustomFieldValue.table_name == table, CustomFieldValue.record_id == record_id)).scalars().all()
    defs = {d["field_key"]: d for d in list_definitions(db, table)}
    return {r.field_key: {"value": r.field_value,
                          "display_name": defs.get(r.field_key, {}).get("display_name", r.field_key)}
            for r in rows}
