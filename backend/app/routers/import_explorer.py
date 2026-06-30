"""Import Mapping Explorer API. Chỉ admin hoặc quyền 'integration.import'.
Router mỏng — toàn bộ logic ở services/import_*.
"""

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..security import User, get_current_user, require_perm
from ..services import custom_fields, import_mapping, import_targets

router = APIRouter(prefix="/api/integration/import", tags=["integration-import"])


def guard(user: User = Depends(get_current_user)) -> User:
    """Bắt buộc admin hoặc quyền integration.import."""
    require_perm(user, "integration.import")   # admin tự pass; user khác cần quyền
    return user


class ValidateIn(BaseModel):
    file_id: str
    target_table: str
    mappings: dict = {}
    defaults: dict = {}
    rules: dict = {}            # {target_col: {"type":..., "params":...}}
    key_field: str = "code"


class RunIn(ValidateIn):
    profile_id: str | None = None
    source_system: str | None = None


class ProfileIn(BaseModel):
    name: str
    target_table: str
    source_system: str | None = None
    source_type: str = "csv"
    key_field: str = "code"
    mappings: dict = {}
    defaults: dict = {}
    rules: dict = {}
    validation_rules: dict = {}


# ---- Bảng đích (whitelist) ----
@router.get("/targets")
def targets(user: User = Depends(guard)):
    return {"targets": import_targets.list_targets()}


@router.get("/targets/{table}")
def target_schema(table: str, db: Session = Depends(get_db), user: User = Depends(guard)):
    return import_targets.target_schema(table, db)   # gồm cả custom field active


# ---- Custom Fields (dynamic) ----
class CustomFieldIn(BaseModel):
    table_name: str
    display_name: str
    data_type: str = "string"      # string|int|float|bool|date
    field_key: str | None = None
    is_required: bool = False


@router.get("/custom-fields/{table}")
def list_custom_fields(table: str, db: Session = Depends(get_db), user: User = Depends(guard)):
    return {"fields": custom_fields.list_definitions(db, table)}


@router.post("/custom-fields", status_code=201)
def create_custom_field(payload: CustomFieldIn, db: Session = Depends(get_db), user: User = Depends(guard)):
    return custom_fields.create_definition(db, payload.table_name, payload.display_name,
                                           payload.data_type, payload.field_key, payload.is_required)


@router.delete("/custom-fields/{table}/{field_key}")
def delete_custom_field(table: str, field_key: str, hard: bool = False,
                        db: Session = Depends(get_db), user: User = Depends(guard)):
    return custom_fields.delete_definition(db, table, field_key, hard)


@router.get("/records/{table}/{record_id}/custom")
def record_custom_values(table: str, record_id: str, db: Session = Depends(get_db), user: User = Depends(guard)):
    return {"table": table, "record_id": record_id, "values": custom_fields.get_values(db, table, record_id)}


@router.get("/lookup/{table}/{code}")
def lookup_record(table: str, code: str, db: Session = Depends(get_db), user: User = Depends(guard)):
    return import_mapping.lookup_record(db, table, code)


# ---- Upload (chỉ đọc, chưa import) ----
@router.post("/upload")
async def upload(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(guard)):
    data = await file.read()
    return import_mapping.save_upload(db, file.filename, data, user.username)


@router.get("/preview/{file_id}")
def preview(file_id: str, db: Session = Depends(get_db), user: User = Depends(guard)):
    return import_mapping.preview(db, file_id)


# ---- Validate (preview plan) ----
@router.post("/validate")
def validate(payload: ValidateIn, db: Session = Depends(get_db), user: User = Depends(guard)):
    return import_mapping.validate(db, payload.file_id, payload.target_table,
                                   payload.mappings, payload.defaults, payload.key_field, payload.rules)


# ---- Run (CONFIRM IMPORT) ----
@router.post("/run")
def run(payload: RunIn, db: Session = Depends(get_db), user: User = Depends(guard)):
    return import_mapping.run_import(db, payload.file_id, payload.target_table, payload.mappings,
                                     payload.defaults, payload.key_field, user.username,
                                     payload.profile_id, payload.rules, payload.source_system)


# ---- Export report ----
@router.get("/export/{run_id}")
def export(run_id: str, fmt: str = "csv", db: Session = Depends(get_db), user: User = Depends(guard)):
    fname, content, media = import_mapping.export_report(db, run_id, fmt)
    return Response(content=content, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ---- History / Errors ----
@router.get("/history")
def history(db: Session = Depends(get_db), user: User = Depends(guard)):
    return {"runs": import_mapping.history(db)}


@router.get("/errors/{run_id}")
def errors(run_id: str, db: Session = Depends(get_db), user: User = Depends(guard)):
    return {"errors": import_mapping.errors(db, run_id)}


# ---- Mapping Profiles ----
@router.get("/profiles")
def list_profiles(table: str = None, db: Session = Depends(get_db), user: User = Depends(guard)):
    return {"profiles": import_mapping.list_profiles(db, table)}


@router.post("/profiles", status_code=201)
def create_profile(payload: ProfileIn, db: Session = Depends(get_db), user: User = Depends(guard)):
    return import_mapping.save_profile(db, payload.name, payload.target_table, payload.source_type,
                                       payload.key_field, payload.mappings, payload.defaults, user.username,
                                       payload.rules, payload.validation_rules, payload.source_system)


@router.get("/profiles/{profile_id}")
def get_profile(profile_id: str, db: Session = Depends(get_db), user: User = Depends(guard)):
    return import_mapping.get_profile(db, profile_id)
