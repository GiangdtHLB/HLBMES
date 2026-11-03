"""execute_in_chunks() — bất biến BẮT BUỘC: không bao giờ đưa quá IN_CHUNK phần tử vào 1 lệnh
`.in_()` dù input bao lớn (SQL Server giới hạn 2100 tham số bind/câu lệnh — xem common.py và
memory item 18). SQLite không có giới hạn này nên không tự lộ lỗi; test này thay cho việc tái
hiện lỗi 07002 thật trên SQL Server (không có sẵn ở môi trường dev) bằng cách khẳng định cơ chế
chia mẻ luôn đúng, bất kể input."""

import os
import tempfile

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["MES_DATABASE_URL"] = f"sqlite:///{_TMP.name}"
os.environ["MES_DEV_HEADER_AUTH"] = "0"
os.environ["MES_RL_ENABLED"] = "0"
os.environ.setdefault("MES_LLM_ENABLED", "off")

from app.main import app  # noqa: F401 — import side effect: registers all ORM models exactly once
from app.common import IN_CHUNK, execute_in_chunks
from app.database import SessionLocal, init_db

init_db()


def _db():
    return SessionLocal()


def test_never_exceeds_in_chunk_elements_per_call():
    """Bất biến chính: ghi lại độ dài mỗi lần stmt_for(chunk) được gọi, assert không lần nào > IN_CHUNK."""
    db = _db()
    values = list(range(2500))   # > 2×IN_CHUNK, mirror quy mô seed test MSSQL thật (2500 mẻ)
    seen_chunk_sizes = []

    def stmt_for(chunk):
        seen_chunk_sizes.append(len(chunk))
        from sqlalchemy import select, literal
        return select(literal(1))

    execute_in_chunks(db, stmt_for, values)
    assert seen_chunk_sizes, "stmt_for phải được gọi ít nhất 1 lần"
    assert all(n <= IN_CHUNK for n in seen_chunk_sizes), \
        f"Có lần gọi vượt IN_CHUNK={IN_CHUNK}: {seen_chunk_sizes}"
    assert sum(seen_chunk_sizes) == len(values), "Tổng phần tử qua các mẻ phải đúng bằng input"


def test_merges_results_from_all_chunks_completely():
    """Kết quả gộp phải ĐỦ, không rơi/trùng phần tử nào ở ranh giới mẻ 900 — dùng dữ liệu thật
    trong bảng (Material) thay vì UNION ALL nhiều literal, vì SQLite tự giới hạn số nhánh
    compound-select (~500) — không liên quan tới bất biến đang kiểm ở đây."""
    from app.models.master import Material
    db = _db()
    codes = [f"EIC-ORDER-{i:05d}" for i in range(2500)]
    db.add_all([Material(code=c, name=c, uom="kg") for c in codes])
    db.commit()

    def stmt_for(chunk):
        from sqlalchemy import select
        return select(Material.code).where(Material.code.in_(chunk))

    out = execute_in_chunks(db, stmt_for, codes)
    flat = {row[0] for row in out}
    assert flat == set(codes), "Phải gộp đủ, không rơi/trùng ở ranh giới mẻ 900"
    assert len(out) == len(codes), "Không được trùng lặp dòng nào giữa các mẻ"


def test_empty_values_returns_empty_without_calling_stmt_for():
    db = _db()
    calls = []

    def stmt_for(chunk):
        calls.append(chunk)
        from sqlalchemy import select, literal
        return select(literal(1))

    out = execute_in_chunks(db, stmt_for, [])
    assert out == []
    assert calls == [], "Không nên gọi stmt_for khi values rỗng"


def test_scalars_true_returns_orm_entities():
    """scalars=True phải trả về entity ORM thật (không phải tuple Row) — mirror cách
    bom.py/dashboard.py dùng cho SELECT nguyên entity (MaterialLot/BatchTank...)."""
    from app.models.master import Material
    db = _db()
    db.add(Material(code="EIC-TEST-1", name="Test 1", uom="kg"))
    db.add(Material(code="EIC-TEST-2", name="Test 2", uom="kg"))
    db.commit()
    codes = ["EIC-TEST-1", "EIC-TEST-2", "EIC-TEST-NONEXISTENT"]

    def stmt_for(chunk):
        from sqlalchemy import select
        return select(Material).where(Material.code.in_(chunk))

    out = execute_in_chunks(db, stmt_for, codes, scalars=True)
    assert {m.code for m in out} == {"EIC-TEST-1", "EIC-TEST-2"}
    assert all(isinstance(m, Material) for m in out)
