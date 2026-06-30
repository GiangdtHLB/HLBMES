"""Test Import Mapping Explorer (Phase 1 — master data) ở tầng service.

Chạy:  cd backend && pytest -q
"""
import io
import os
import tempfile

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ.setdefault("MES_DATABASE_URL", f"sqlite:///{_TMP.name}")
os.environ.setdefault("MES_RL_ENABLED", "0")
os.environ.setdefault("MES_ADMIN_PASSWORD", "AdminTest123")
os.environ["MES_IMPORT_DIR"] = tempfile.mkdtemp(prefix="mesimp_")

import pytest

from app import seed as seed_mod
from app.database import SessionLocal
from app.errors import DomainError
from app.services import import_parser, import_targets, import_mapping


@pytest.fixture(scope="module", autouse=True)
def _seeded():
    seed_mod.seed()
    yield


@pytest.fixture()
def db():
    s = SessionLocal()
    yield s
    s.close()


# ---------------- Parser ----------------

def test_parse_csv_unicode():
    data = "MaVT,TenVT,DonVi\nVT-001,Malt Đức,kg\nVT-002,Hoa bia Saaz,kg\n".encode("utf-8")
    cols, rows = import_parser.parse(data, "csv")
    assert cols == ["MaVT", "TenVT", "DonVi"]
    assert len(rows) == 2
    assert rows[0]["TenVT"] == "Malt Đức"      # giữ dấu tiếng Việt


def test_parse_excel():
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active
    ws.append(["MaVT", "TenVT", "DonVi"])
    ws.append(["VT-X", "Gạo tẻ", "kg"])
    buf = io.BytesIO(); wb.save(buf)
    cols, rows = import_parser.parse(buf.getvalue(), "excel")
    assert cols == ["MaVT", "TenVT", "DonVi"]
    assert rows[0]["TenVT"] == "Gạo tẻ"


def test_detect_source_type():
    assert import_parser.detect_source_type("a.csv") == "csv"
    assert import_parser.detect_source_type("a.xlsx") == "excel"
    with pytest.raises(ValueError):
        import_parser.detect_source_type("a.pdf")


# ---------------- Whitelist / Blacklist ----------------

def test_whitelist_targets():
    names = {t["table"] for t in import_targets.list_targets()}
    assert "material" in names and "product" in names
    assert "audit_log" not in names and "app_user" not in names


def test_target_schema_material():
    sch = import_targets.target_schema("material")
    cols = {c["name"]: c for c in sch["columns"]}
    assert cols["code"]["required"] and cols["code"]["unique"]
    assert cols["name"]["required"]
    assert not cols["uom"]["required"]          # có default


def test_blacklist_schema_rejected():
    for bad in ("audit_log", "app_user", "api_key", "ai_message"):
        with pytest.raises(ValueError):
            import_targets.target_schema(bad)


# ---------------- Validate ----------------

def _upload(db, content: str, name="f.csv"):
    return import_mapping.save_upload(db, name, content.encode("utf-8"), "tester")["file_id"]


def test_validate_required_missing(db):
    fid = _upload(db, "MaVT,DonVi\nVT-R1,kg\n")     # thiếu cột tên
    res = import_mapping.validate(db, fid, "material",
                                  {"code": "MaVT", "uom": "DonVi"}, {}, "code")
    assert res["summary"]["error"] == 1
    assert res["summary"]["conflict"] == 1
    assert any(e["column"] == "name" for e in res["conflicts"])


def test_validate_required_with_default(db):
    fid = _upload(db, "MaVT,DonVi\nVT-R2,kg\n")
    res = import_mapping.validate(db, fid, "material",
                                  {"code": "MaVT", "uom": "DonVi"}, {"name": "Chưa đặt tên"}, "code")
    assert res["summary"]["error"] == 0          # default lấp trường bắt buộc


def test_validate_duplicate_in_file(db):
    fid = _upload(db, "MaVT,Ten\nDUP-1,A\nDUP-1,B\n")
    res = import_mapping.validate(db, fid, "material",
                                  {"code": "MaVT", "name": "Ten"}, {}, "code")
    assert res["summary"]["skip"] >= 1           # dòng trùng khóa bị skip


# ---------------- Import (insert/update/upsert + raw_payload) ----------------

def test_import_material_insert_then_update(db):
    fid = _upload(db, "MaVT,Ten,DonVi,GhiChuNoiBo\nIMP-001,Malt Đức nhập,kg,note-thừa\n")
    mp = {"code": "MaVT", "name": "Ten", "uom": "DonVi"}
    r1 = import_mapping.run_import(db, fid, "material", mp, {}, "code", "tester")
    assert r1["inserted"] == 1 and r1["errored"] == 0
    # đọc DB
    from app.models.master import Material
    import sqlalchemy as sa
    row = db.execute(sa.select(Material).where(Material.code == "IMP-001")).scalar_one()
    assert row.name == "Malt Đức nhập"           # Unicode giữ nguyên
    # cột dư 'GhiChuNoiBo' KHÔNG vào core → vào raw_payload của import_error/log
    # import lại = update
    fid2 = _upload(db, "MaVT,Ten,DonVi\nIMP-001,Malt Đức (cập nhật),kg\n")
    r2 = import_mapping.run_import(db, fid2, "material", mp, {}, "code", "tester")
    assert r2["updated"] == 1 and r2["inserted"] == 0
    db.expire_all()
    row2 = db.execute(sa.select(Material).where(Material.code == "IMP-001")).scalar_one()
    assert row2.name == "Malt Đức (cập nhật)"


def test_import_product_unicode(db):
    fid = _upload(db, "Code,Name,Uom\nIMP-P1,Bia Hạ Long Đông Mai,L\n")
    r = import_mapping.run_import(db, fid, "product",
                                  {"code": "Code", "name": "Name", "uom": "Uom"}, {}, "code", "tester")
    assert r["inserted"] == 1
    import sqlalchemy as sa
    from app.models.master import Product
    p = db.execute(sa.select(Product).where(Product.code == "IMP-P1")).scalar_one()
    assert p.name == "Bia Hạ Long Đông Mai"


def test_import_blacklist_rejected(db):
    fid = _upload(db, "x\n1\n")
    with pytest.raises(DomainError):
        import_mapping.run_import(db, fid, "audit_log", {"x": "x"}, {}, "x", "tester")


def test_import_log_and_errors(db):
    fid = _upload(db, "MaVT,Ten\nLOG-1,Tên A\nLOG-1,Tên B\n")  # 1 insert + 1 skip(dup)
    r = import_mapping.run_import(db, fid, "material", {"code": "MaVT", "name": "Ten"}, {}, "code", "tester")
    assert r["inserted"] == 1 and r["skipped"] >= 1
    hist = import_mapping.history(db)
    assert any(h["run_id"] == r["run_id"] for h in hist)
    errs = import_mapping.errors(db, r["run_id"])
    assert any("Trùng khóa" in e["message"] for e in errs)


# ---------------- Mapping Profile ----------------

def test_profile_roundtrip(db):
    p = import_mapping.save_profile(db, "Brawmart material", "material", "csv", "code",
                                    {"code": "MaVT", "name": "TenVT"}, {"uom": "kg"}, "tester")
    got = import_mapping.get_profile(db, p["profile_id"])
    assert got["target_table"] == "material"
    assert got["mappings"]["code"] == "MaVT"
    assert got["defaults"]["uom"] == "kg"
    assert any(x["profile_id"] == p["profile_id"] for x in import_mapping.list_profiles(db, "material"))


# ================= PHASE 1.1 — RULE ENGINE =================
from app.services import import_rules


def test_rule_trim_case():
    assert import_rules.apply("  abc ", {"type": "trim"})["value"] == "abc"
    assert import_rules.apply("abc", {"type": "uppercase"})["value"] == "ABC"
    assert import_rules.apply("ABC", {"type": "lowercase"})["value"] == "abc"


def test_rule_normalize_uom():
    r = import_rules.apply("Kilogram", {"type": "normalize_uom"})
    assert r["value"] == "KG" and r["warning"]
    assert import_rules.apply("lít", {"type": "normalize_uom"})["value"] == "L"


def test_rule_boolean_map():
    assert import_rules.apply("Đang dùng", {"type": "boolean_map"})["value"] is True
    assert import_rules.apply("Ngừng dùng", {"type": "boolean_map"})["value"] is False
    assert import_rules.apply("xyz", {"type": "boolean_map"})["error"]


def test_rule_enum_map():
    rule = {"type": "enum_map", "params": {"map": {"malt": "MALT", "hoa": "HOP"}}}
    assert import_rules.apply("Malt", rule)["value"] == "MALT"
    assert import_rules.apply("khac", rule)["error"]


def test_rule_date_number_parse():
    assert import_rules.apply("25/12/2026", {"type": "date_parse", "params": {"format": "dd/MM/yyyy"}})["value"] == "2026-12-25"
    assert import_rules.apply("31/31/2026", {"type": "date_parse"})["error"]
    assert import_rules.apply("1.234,5", {"type": "number_parse"})["value"] == 1234.5
    assert import_rules.apply("abc", {"type": "number_parse"})["error"]


def test_rule_regex_default():
    assert import_rules.apply("AB-12", {"type": "regex_validate", "params": {"pattern": "[A-Z]+-[0-9]+"}})["error"] is None
    assert import_rules.apply("bad", {"type": "regex_validate", "params": {"pattern": "[A-Z]+-[0-9]+"}})["error"]
    assert import_rules.apply("", {"type": "default_if_empty", "params": {"value": "X"}})["value"] == "X"


def test_validate_warning_normalize(db):
    fid = _upload(db, "MaVT,Ten,DV\nRULE-1,Malt,Kilogram\n")
    res = import_mapping.validate(db, fid, "material",
                                  {"code": "MaVT", "name": "Ten", "uom": "DV"}, {},
                                  "code", {"uom": {"type": "normalize_uom"}})
    assert res["summary"]["warning"] >= 1
    assert any("UOM" in w["message"] for w in res["warnings"])


def test_validate_conflict_regex(db):
    fid = _upload(db, "MaVT,Ten\nbad code,X\n")   # code có khoảng trắng
    res = import_mapping.validate(db, fid, "material", {"code": "MaVT", "name": "Ten"}, {},
                                  "code", {"code": {"type": "regex_validate", "params": {"pattern": "[A-Z0-9-]+"}}})
    assert res["summary"]["error"] == 1


def test_import_material_with_rule(db):
    fid = _upload(db, "MaVT,Ten,DV\nRULE-IMP-1,Malt Đức,kilogram\n")
    r = import_mapping.run_import(db, fid, "material",
                                  {"code": "MaVT", "name": "Ten", "uom": "DV"}, {}, "code", "tester",
                                  rules={"uom": {"type": "normalize_uom"}, "code": {"type": "uppercase"}},
                                  source_system="brawmart")
    assert r["inserted"] == 1
    import sqlalchemy as sa
    from app.models.master import Material
    m = db.execute(sa.select(Material).where(Material.code == "RULE-IMP-1")).scalar_one()
    assert m.uom == "KG" and m.name == "Malt Đức"      # rule + Unicode


def test_profile_with_rules_roundtrip(db):
    p = import_mapping.save_profile(db, "BrawmartRules", "material", "csv", "code",
                                    {"code": "MaVT", "uom": "DV"}, {}, "tester",
                                    rules={"uom": {"type": "normalize_uom"}}, source_system="brawmart")
    got = import_mapping.get_profile(db, p["profile_id"])
    assert got["source_system"] == "brawmart"
    assert got["rules"]["uom"]["type"] == "normalize_uom"


def test_export_report_csv_xlsx(db):
    fid = _upload(db, "MaVT,Ten\nEXP-1,A\nEXP-1,B\n")
    r = import_mapping.run_import(db, fid, "material", {"code": "MaVT", "name": "Ten"}, {}, "code", "tester")
    name_csv, content_csv, media_csv = import_mapping.export_report(db, r["run_id"], "csv")
    assert name_csv.endswith(".csv") and b"SUMMARY" in content_csv and b"row_number" in content_csv
    name_x, content_x, media_x = import_mapping.export_report(db, r["run_id"], "xlsx")
    assert name_x.endswith(".xlsx") and content_x[:2] == b"PK"   # xlsx = zip


# ================= PHASE 1.2 — CUSTOM FIELDS =================
from app.services import custom_fields


def test_custom_field_create_and_schema(db):
    cf = custom_fields.create_definition(db, "material", "Ghi chú nội bộ", "string")
    assert cf["field_key"] == "ghi_chu_noi_bo" and cf["is_active"]
    sch = import_targets.target_schema("material", db)
    col = next((c for c in sch["columns"] if c["name"] == "ghi_chu_noi_bo"), None)
    assert col and col["is_custom"] is True
    assert "ghi_chu_noi_bo" in sch["custom_columns"]
    assert sch["pk_col"] == "material_id"


def test_custom_field_collision_core(db):
    with pytest.raises(DomainError):
        custom_fields.create_definition(db, "material", "code", "string")   # trùng cột core


def test_custom_field_blacklist_table(db):
    with pytest.raises(DomainError):
        custom_fields.create_definition(db, "audit_log", "x", "string")


def test_import_with_custom_field(db):
    custom_fields.create_definition(db, "material", "Nhà cung cấp", "string", field_key="ncc")
    fid = _upload(db, "MaVT,Ten,DonVi,NCC\nCF-IMP-1,Malt CF,kg,Brenntag Việt Nam\n")
    r = import_mapping.run_import(db, fid, "material",
                                  {"code": "MaVT", "name": "Ten", "uom": "DonVi", "ncc": "NCC"}, {}, "code", "tester")
    assert r["inserted"] == 1 and r["errored"] == 0
    import sqlalchemy as sa
    from app.models.master import Material
    m = db.execute(sa.select(Material).where(Material.code == "CF-IMP-1")).scalar_one()
    # custom value lưu ở custom_field_value, KHÔNG ở core
    vals = custom_fields.get_values(db, "material", m.material_id)
    assert vals["ncc"]["value"] == "Brenntag Việt Nam"     # Unicode + EAV
    assert vals["ncc"]["display_name"] == "Nhà cung cấp"
    # validate phân biệt custom trong preview
    fid2 = _upload(db, "MaVT,Ten,NCC\nCF-IMP-2,X,Cty Y\n")
    vr = import_mapping.validate(db, fid2, "material", {"code": "MaVT", "name": "Ten", "ncc": "NCC"}, {}, "code")
    item = vr["preview"][0]
    assert "ncc" in (item.get("custom") or {}) and "ncc" not in item["data"]


def test_custom_field_required_conflict(db):
    custom_fields.create_definition(db, "product", "Mã ERP", "string", field_key="ma_erp", is_required=True)
    fid = _upload(db, "Code,Name\nCF-P-1,SP A\n")        # thiếu cột cho ma_erp
    vr = import_mapping.validate(db, fid, "product", {"code": "Code", "name": "Name"}, {}, "code")
    assert vr["summary"]["conflict"] >= 1
    assert any(c["column"] == "ma_erp" for c in vr["conflicts"])


def test_custom_field_delete_soft_and_hard(db):
    custom_fields.create_definition(db, "equipment", "Vị trí GPS", "string", field_key="gps")
    custom_fields.delete_definition(db, "equipment", "gps", hard=False)      # soft → ẩn
    sch = import_targets.target_schema("equipment", db)
    assert "gps" not in sch["custom_columns"]
    custom_fields.create_definition(db, "equipment", "Mã tài sản", "string", field_key="ma_ts")
    custom_fields.upsert_value(db, "equipment", "rec-1", "ma_ts", "TS-001"); db.commit()
    res = custom_fields.delete_definition(db, "equipment", "ma_ts", hard=True)  # hard → xoá cả value
    assert res["hard"] is True and res["values_removed"] == 1
    assert custom_fields.get_values(db, "equipment", "rec-1") == {}
    with pytest.raises(DomainError):
        custom_fields.delete_definition(db, "equipment", "khong_co", hard=False)
