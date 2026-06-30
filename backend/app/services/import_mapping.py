"""Điều phối Import Mapping Explorer: lưu file, preview, validate, run, history,
mapping profile. KHÔNG viết logic trong router — router chỉ gọi service này.
"""

import os
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..common import new_id, utcnow
from ..config import BASE_DIR
from ..errors import DomainError, NotFoundError
from ..models.integration_import import (
    IntegrationColumnMapping,
    IntegrationImportError,
    IntegrationImportFile,
    IntegrationImportRun,
    IntegrationMappingProfile,
)
from . import import_parser, import_runner, import_targets
from .import_validator import build_plan

UPLOAD_DIR = Path(os.environ.get("MES_IMPORT_DIR", str(BASE_DIR / ".import_uploads")))
MAX_BYTES = 10 * 1024 * 1024  # 10MB


def _ensure_table(table: str):
    if not import_targets.is_allowed(table):
        raise DomainError(f"Bảng '{table}' không được phép import (Phase 1: chỉ master data trong whitelist).")


# ---------------- Upload / Preview ----------------

def save_upload(db: Session, filename: str, data: bytes, user: str) -> dict:
    if len(data) > MAX_BYTES:
        raise DomainError(f"File vượt giới hạn 10MB (hiện {len(data) // 1024} KB).")
    source_type = import_parser.detect_source_type(filename)
    columns, rows = import_parser.parse(data, source_type)
    if not columns:
        raise DomainError("File rỗng hoặc không đọc được header.")
    file_id = new_id()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    ext = ".xlsx" if source_type == "excel" else ".csv"
    path = UPLOAD_DIR / f"{file_id}{ext}"
    path.write_bytes(data)
    rec = IntegrationImportFile(
        file_id=file_id, filename=filename, source_type=source_type,
        size_bytes=len(data), row_count=len(rows), columns=columns,
        sample=rows[:50], stored_path=str(path), uploaded_by=user, uploaded_at=utcnow())
    db.add(rec)
    db.commit()
    return {"file_id": file_id, "filename": filename, "source_type": source_type,
            "row_count": len(rows), "columns": columns, "preview": rows[:50]}


def _read_rows(db: Session, file_id: str) -> list:
    rec = db.get(IntegrationImportFile, file_id)
    if not rec or not rec.stored_path or not Path(rec.stored_path).exists():
        raise NotFoundError("Không tìm thấy file đã upload (hoặc đã bị dọn).")
    data = Path(rec.stored_path).read_bytes()
    _, rows = import_parser.parse(data, rec.source_type)
    return rows


def preview(db: Session, file_id: str) -> dict:
    rec = db.get(IntegrationImportFile, file_id)
    if not rec:
        raise NotFoundError("File không tồn tại.")
    return {"file_id": rec.file_id, "filename": rec.filename, "source_type": rec.source_type,
            "row_count": rec.row_count, "columns": rec.columns, "preview": rec.sample}


# ---------------- Validate (preview plan, không ghi) ----------------

def validate(db: Session, file_id: str, table: str, mapping: dict, defaults: dict,
             key_field: str, rules: dict = None) -> dict:
    _ensure_table(table)
    rows = _read_rows(db, file_id)
    plan = build_plan(db, table, mapping, defaults, key_field or "code", rows, rules)
    iss = plan["issues"]
    return {"table": plan["table"], "key_field": plan["key_field"], "summary": plan["summary"],
            "conflicts": [i for i in iss if i["kind"] == "conflict"][:200],
            "warnings": [i for i in iss if i["kind"] == "warning"][:200],
            "errors": [i for i in iss if i["kind"] == "error"][:200],
            "issues": iss[:400], "preview": plan["items"][:50]}


# ---------------- Run (transaction upsert) ----------------

def run_import(db: Session, file_id: str, table: str, mapping: dict, defaults: dict,
               key_field: str, user: str, profile_id: str = None, rules: dict = None,
               source_system: str = None) -> dict:
    _ensure_table(table)
    t0 = time.monotonic()
    rows = _read_rows(db, file_id)
    plan = build_plan(db, table, mapping, defaults, key_field or "code", rows, rules)
    kf = plan["key_field"]

    run = IntegrationImportRun(
        run_id=new_id(), file_id=file_id, profile_id=profile_id, source_system=source_system,
        target_table=table, key_field=kf, status="running", total=plan["summary"]["total"],
        run_by=user, started_at=utcnow())
    db.add(run)
    db.flush()

    result = import_runner.run_upsert(db, table, kf, plan["items"])

    # lưu MỌI issue (conflict/error/warning) + lỗi DB → để soi & export report
    for e in (plan["issues"] + result["db_errors"])[:2000]:
        db.add(IntegrationImportError(
            error_id=new_id(), run_id=run.run_id, row_index=e.get("row_index", 0),
            column=e.get("column"), value=(str(e.get("value"))[:1000] if e.get("value") is not None else None),
            message=e.get("message", ""), severity=e.get("kind", e.get("severity", "error")),
            raw_payload=e.get("raw_payload")))

    run.inserted = result["inserted"]
    run.updated = result["updated"]
    run.skipped = plan["summary"]["skip"]
    run.errored = plan["summary"]["error"] + result["errored"]
    run.duration_ms = int((time.monotonic() - t0) * 1000)
    run.status = "done" if run.errored == 0 else "done_with_errors"
    run.finished_at = utcnow()
    run.summary = {"validate": plan["summary"], "applied": {"inserted": result["inserted"],
                   "updated": result["updated"], "db_errors": result["errored"]}}
    db.commit()
    return {"run_id": run.run_id, "status": run.status, "table": table, "key_field": kf,
            "total": run.total, "inserted": run.inserted, "updated": run.updated,
            "skipped": run.skipped, "errored": run.errored,
            "warning": plan["summary"]["warning"], "conflict": plan["summary"]["conflict"],
            "duration_ms": run.duration_ms}


# ---------------- Export Report ----------------

def export_report(db: Session, run_id: str, fmt: str = "csv"):
    """Xuất report import: header tổng hợp + từng issue (row/cột/giá trị/kind/message).
    Trả (filename, bytes, media_type)."""
    run = db.get(IntegrationImportRun, run_id)
    if not run:
        raise NotFoundError("Run không tồn tại.")
    rows = db.execute(select(IntegrationImportError).where(IntegrationImportError.run_id == run_id)
                      .order_by(IntegrationImportError.row_index)).scalars().all()
    headers = ["run_id", "target_table", "row_number", "kind", "column", "value", "message"]
    data_rows = [[run.run_id, run.target_table, r.row_index + 1, r.severity, r.column or "",
                  (r.value or ""), r.message] for r in rows]
    summary = (f"SUMMARY total={run.total} inserted={run.inserted} updated={run.updated} "
               f"skipped={run.skipped} errored={run.errored} status={run.status}")
    if fmt == "xlsx":
        from openpyxl import Workbook
        import io
        wb = Workbook(); ws = wb.active; ws.title = "import_report"
        ws.append(["IMPORT REPORT", run.target_table, run.run_id])
        ws.append([summary]); ws.append([])
        ws.append(headers)
        for dr in data_rows:
            ws.append(dr)
        buf = io.BytesIO(); wb.save(buf)
        return f"import_report_{run_id[:8]}.xlsx", buf.getvalue(), \
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    # CSV
    import csv
    import io
    sio = io.StringIO()
    w = csv.writer(sio)
    w.writerow([summary])
    w.writerow(headers)
    for dr in data_rows:
        w.writerow(dr)
    return f"import_report_{run_id[:8]}.csv", ("﻿" + sio.getvalue()).encode("utf-8"), "text/csv; charset=utf-8"


# ---------------- History / Errors ----------------

def history(db: Session, limit: int = 50) -> list:
    rows = db.execute(select(IntegrationImportRun).order_by(IntegrationImportRun.started_at.desc()).limit(limit)).scalars().all()
    return [{"run_id": r.run_id, "target_table": r.target_table, "status": r.status,
             "total": r.total, "inserted": r.inserted, "updated": r.updated,
             "skipped": r.skipped, "errored": r.errored, "duration_ms": r.duration_ms,
             "run_by": r.run_by, "started_at": r.started_at} for r in rows]


def errors(db: Session, run_id: str, limit: int = 500) -> list:
    rows = db.execute(select(IntegrationImportError).where(IntegrationImportError.run_id == run_id)
                      .order_by(IntegrationImportError.row_index).limit(limit)).scalars().all()
    return [{"row_index": r.row_index, "column": r.column, "value": r.value,
             "message": r.message, "severity": r.severity} for r in rows]


# ---------------- Mapping Profiles ----------------

def save_profile(db: Session, name: str, target_table: str, source_type: str, key_field: str,
                 mappings: dict, defaults: dict, user: str, rules: dict = None,
                 validation_rules: dict = None, source_system: str = None) -> dict:
    _ensure_table(target_table)
    p = IntegrationMappingProfile(profile_id=new_id(), name=name, target_table=target_table,
                                  source_system=source_system, source_type=source_type or "csv",
                                  key_field=key_field or "code", created_by=user, created_at=utcnow())
    db.add(p)
    mappings = mappings or {}
    defaults = defaults or {}
    rules = rules or {}
    validation_rules = validation_rules or {}
    # lưu mọi cột đích có mapping / default / rule
    for tgt in set(mappings) | set(defaults) | set(rules) | set(validation_rules):
        db.add(IntegrationColumnMapping(mapping_id=new_id(), profile_id=p.profile_id,
                                        target_column=tgt, source_column=mappings.get(tgt),
                                        default_value=defaults.get(tgt),
                                        transform_rule=rules.get(tgt),
                                        validation_rule=validation_rules.get(tgt)))
    db.commit()
    return {"profile_id": p.profile_id, "name": p.name, "target_table": p.target_table}


def list_profiles(db: Session, table: str = None) -> list:
    stmt = select(IntegrationMappingProfile).where(IntegrationMappingProfile.active == True)  # noqa: E712
    if table:
        stmt = stmt.where(IntegrationMappingProfile.target_table == table)
    rows = db.execute(stmt.order_by(IntegrationMappingProfile.created_at.desc())).scalars().all()
    return [{"profile_id": p.profile_id, "name": p.name, "target_table": p.target_table,
             "source_type": p.source_type, "key_field": p.key_field} for p in rows]


def get_profile(db: Session, profile_id: str) -> dict:
    p = db.get(IntegrationMappingProfile, profile_id)
    if not p:
        raise NotFoundError("Profile không tồn tại.")
    maps = db.execute(select(IntegrationColumnMapping).where(IntegrationColumnMapping.profile_id == profile_id)).scalars().all()
    return {"profile_id": p.profile_id, "name": p.name, "target_table": p.target_table,
            "source_system": p.source_system, "source_type": p.source_type, "key_field": p.key_field,
            "mappings": {m.target_column: m.source_column for m in maps if m.source_column},
            "defaults": {m.target_column: m.default_value for m in maps if m.default_value is not None},
            "rules": {m.target_column: m.transform_rule for m in maps if m.transform_rule},
            "validation_rules": {m.target_column: m.validation_rule for m in maps if m.validation_rule}}
