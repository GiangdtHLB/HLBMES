"""Whitelist bảng đích cho Import Mapping Explorer (Phase 1: chỉ MASTER DATA).

Mô tả cột (kiểu/nullable/required/unique/length) được INTROSPECT từ SQLAlchemy
metadata — không hardcode danh sách cột, nên khi model đổi thì registry tự cập nhật.
Bảng ngoài whitelist (audit/auth/AI/giao dịch...) bị từ chối tuyệt đối.
"""

from sqlalchemy import Boolean, DateTime, Float, Integer
from sqlalchemy.types import JSON

from ..database import Base

# Phase 1 — chỉ master data.
WHITELIST = {
    "product", "material", "equipment", "production_line", "packaging_type",
    "energy_group", "energy_area", "qc_parameter", "spare_part", "wms_location",
}

# Cấm tuyệt đối (kể cả khi có người cố truyền tên bảng).
BLACKLIST = {
    "audit_log", "app_user", "api_key", "ai_message", "ai_conversation",
    "user_session", "alembic_version", "ebr_snapshot", "esignature", "webhook", "job",
}

TABLE_DESC = {
    "product": "Sản phẩm / bia thành phẩm",
    "material": "Nguyên vật liệu",
    "equipment": "Thiết bị",
    "production_line": "Dây chuyền sản xuất",
    "packaging_type": "Loại bao bì tuần hoàn",
    "energy_group": "Nhóm năng lượng (Điện/Nước/Hơi)",
    "energy_area": "Khu vực tiêu thụ năng lượng",
    "qc_parameter": "Danh mục chỉ tiêu QC (LIMS)",
    "spare_part": "Vật tư phụ tùng bảo trì",
    "wms_location": "Vị trí kho thành phẩm (WMS)",
}

# Cột hệ thống không cho map (tự sinh / nội bộ).
_SYSTEM_COLS = {"created_at", "updated_at", "ts"}


def is_allowed(table: str) -> bool:
    return table in WHITELIST and table not in BLACKLIST


def _py_type(coltype) -> str:
    if isinstance(coltype, Boolean):
        return "bool"
    if isinstance(coltype, Integer):
        return "int"
    if isinstance(coltype, Float):
        return "float"
    if isinstance(coltype, DateTime):
        return "datetime"
    if isinstance(coltype, JSON):
        return "json"
    return "string"


def list_targets() -> list:
    """Danh sách bảng đích cho phép import + mô tả ngắn."""
    return [{"table": t, "description": TABLE_DESC.get(t, t)} for t in sorted(WHITELIST)]


def target_schema(table: str, db=None) -> dict:
    """Mô tả cột của bảng đích (introspect core + custom field active). Raise nếu ngoài whitelist.

    db != None → ghép thêm các Custom Field đang active (is_custom=True)."""
    if not is_allowed(table):
        raise ValueError(f"Bảng '{table}' không nằm trong whitelist import (Phase 1: chỉ master data).")
    tbl = Base.metadata.tables[table]
    cols = []
    key_candidates = []
    pk_col = None
    for c in tbl.columns:
        if c.name in _SYSTEM_COLS:
            continue
        has_default = c.default is not None or c.server_default is not None
        required = (not c.nullable) and (not has_default) and (not c.primary_key)
        maxlen = getattr(c.type, "length", None)
        unique = bool(c.unique) or any(c.name in idx.columns and idx.unique for idx in tbl.indexes)
        if c.primary_key:
            pk_col = c.name
        if unique and not c.primary_key:
            key_candidates.append(c.name)
        cols.append({
            "name": c.name, "type": _py_type(c.type), "nullable": bool(c.nullable),
            "required": required, "unique": unique, "max_length": maxlen,
            "primary_key": bool(c.primary_key), "has_default": has_default, "is_custom": False,
        })
    custom = []
    if db is not None:
        from . import custom_fields  # lazy — tránh vòng import
        custom = custom_fields.active_columns(db, table)
    return {
        "table": table,
        "description": TABLE_DESC.get(table, table),
        "columns": cols + custom,
        "core_columns": [c["name"] for c in cols],
        "custom_columns": [c["name"] for c in custom],
        "pk_col": pk_col,
        "key_candidates": key_candidates or ["code"],
    }
