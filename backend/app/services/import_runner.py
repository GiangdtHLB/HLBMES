"""Thực thi import (upsert) trong transaction. Lỗi từng dòng → savepoint rollback
riêng dòng đó + ghi lỗi, tiếp tục. KHÔNG xóa/truncate. KHÔNG ALTER core.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import Base


def run_upsert(db: Session, table: str, key_field: str, items: list, pk_col: str = None) -> dict:
    """items: list từ validator (chỉ xử lý action insert/update). Ghi core + custom field.
    Trả thống kê + lỗi DB."""
    from sqlalchemy import select as _select
    from . import custom_fields
    tbl = Base.metadata.tables[table]
    inserted = updated = errored = 0
    db_errors = []
    for it in items:
        action = it.get("action")
        if action not in ("insert", "update"):
            continue
        data = {k: v for k, v in it["data"].items() if v is not None}
        keyval = it["data"].get(key_field)
        custom = it.get("custom") or {}
        try:
            with db.begin_nested():   # SAVEPOINT — lỗi dòng không phá cả mẻ
                if action == "insert":
                    db.execute(tbl.insert().values(**data))   # PK/created_at dùng default model
                    inserted += 1
                else:
                    setvals = {k: v for k, v in data.items() if k != key_field}
                    if setvals:
                        db.execute(tbl.update().where(tbl.c[key_field] == keyval).values(**setvals))
                    updated += 1
                # ghi custom field (EAV) — KHÔNG đụng schema core
                if custom and pk_col:
                    rid = db.execute(_select(tbl.c[pk_col]).where(tbl.c[key_field] == keyval)).scalar()
                    if rid is not None:
                        for fk, fv in custom.items():
                            custom_fields.upsert_value(db, table, str(rid), fk, fv)
        except Exception as e:  # noqa: BLE001 — lỗi DB từng dòng: ghi lại, tiếp tục
            errored += 1
            db_errors.append({"row_index": it["row_index"], "column": None,
                              "value": str(keyval), "message": f"Lỗi ghi DB: {str(e)[:300]}",
                              "severity": "error", "raw_payload": it.get("raw_payload")})
    db.commit()
    return {"inserted": inserted, "updated": updated, "errored": errored, "db_errors": db_errors}


def count_existing(db: Session, table: str, key_field: str) -> int:
    tbl = Base.metadata.tables[table]
    if key_field not in tbl.columns:
        return 0
    return len(list(db.execute(select(tbl.c[key_field]))))
