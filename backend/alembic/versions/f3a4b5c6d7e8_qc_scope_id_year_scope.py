"""QC: rewrite quality_result/deviation scope_id cho ferment/filter/bottle để kèm năm

Revision ID: f3a4b5c6d7e8
Revises: 2b3c4d5e6f7a
Create Date: 2026-08-02

Data migration đi kèm task "scope_id for ferment/filter/bottle results must include year":
lm_code/filter_code/bottle_code chỉ duy nhất TRONG 1 năm (xem UniqueConstraint trên
ferment_record/filter_record/bottle_record), nhưng scope_id ghi ở quality_result/deviation cho
3 loại này trước đây ghép thẳng mã (VD "LM-01__len_men_chinh", "FL-01", "CH-01__thanh_pham")
KHÔNG kèm năm — 2 lô khác năm trùng mã sẽ lẫn lộn kết quả QC của nhau (xem
services/qc_catalog.py::ferment_scope_id/filter_scope_id/bottle_scope_id, nơi định dạng mới
đã áp dụng: "{year}-{mã}[__stage]"). Migration này viết lại các dòng ĐÃ CÓ SẴN trên DB (dev/
prod) sang định dạng mới để khớp đúng code mới, tránh "mất" lịch sử QC đã ghi trước đó.

Với mỗi bản ghi ferment/filter/bottle thật, tính old_scope_id (định dạng cũ) và new_scope_id
(định dạng mới), rồi UPDATE quality_result/deviation nơi scope_type khớp và scope_id = old.
Nếu 2 bản ghi khác năm tình cờ trùng mã (chính là kịch bản lỗi đang sửa), old_scope_id của cả
2 giống hệt nhau — không thể phân biệt ngược lại dòng QC nào thuộc bản ghi nào từ dữ liệu cũ
(dữ liệu đã bị lẫn ngay từ lúc ghi); trường hợp này dòng QC được gán theo bản ghi xử lý SAU
trong vòng lặp (ghi đè key trùng), chấp nhận vì không có cách khôi phục chính xác hơn.

KHÔNG thể downgrade an toàn (một khi đã áp dụng thêm bản ghi mới sau migration, không còn cách
phân biệt dòng nào cần trả ngược lại dạng cũ) — xem downgrade().
"""
from alembic import op
import sqlalchemy as sa

revision = 'f3a4b5c6d7e8'
down_revision = '2b3c4d5e6f7a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    ferments = conn.execute(sa.text(
        "SELECT lm_code, ferment_year FROM ferment_record"
    )).mappings().all()
    for f in ferments:
        for stage in ("len_men_chinh", "len_men_phu"):
            old_id = f"{f['lm_code']}__{stage}"
            new_id = f"{f['ferment_year']}-{f['lm_code']}__{stage}"
            if old_id == new_id:
                continue
            conn.execute(sa.text(
                "UPDATE quality_result SET scope_id = :new_id "
                "WHERE scope_type = 'ferment' AND scope_id = :old_id"
            ), {"new_id": new_id, "old_id": old_id})
            conn.execute(sa.text(
                "UPDATE deviation SET scope_id = :new_id "
                "WHERE scope_type = 'ferment' AND scope_id = :old_id"
            ), {"new_id": new_id, "old_id": old_id})

    filters = conn.execute(sa.text(
        "SELECT filter_code, filter_year FROM filter_record"
    )).mappings().all()
    for r in filters:
        old_id = r["filter_code"]
        new_id = f"{r['filter_year']}-{r['filter_code']}"
        if old_id == new_id:
            continue
        conn.execute(sa.text(
            "UPDATE quality_result SET scope_id = :new_id "
            "WHERE scope_type = 'filter' AND scope_id = :old_id"
        ), {"new_id": new_id, "old_id": old_id})
        conn.execute(sa.text(
            "UPDATE deviation SET scope_id = :new_id "
            "WHERE scope_type = 'filter' AND scope_id = :old_id"
        ), {"new_id": new_id, "old_id": old_id})

    bottles = conn.execute(sa.text(
        "SELECT bottle_code, bottle_year FROM bottle_record"
    )).mappings().all()
    for b in bottles:
        old_id = f"{b['bottle_code']}__thanh_pham"
        new_id = f"{b['bottle_year']}-{b['bottle_code']}__thanh_pham"
        if old_id == new_id:
            continue
        conn.execute(sa.text(
            "UPDATE quality_result SET scope_id = :new_id "
            "WHERE scope_type = 'bottle' AND scope_id = :old_id"
        ), {"new_id": new_id, "old_id": old_id})
        conn.execute(sa.text(
            "UPDATE deviation SET scope_id = :new_id "
            "WHERE scope_type = 'bottle' AND scope_id = :old_id"
        ), {"new_id": new_id, "old_id": old_id})


def downgrade() -> None:
    """Không thể hoàn tác an toàn — sau upgrade, các dòng quality_result/deviation ghi mới sẽ
    dùng ngay định dạng {year}-{mã}[__stage]; không còn cách phân biệt dòng nào tồn tại TRƯỚC
    migration (cần trả ngược) với dòng ghi SAU (không được đổi). Đây là data migration một
    chiều đi kèm thay đổi quy ước scope_id ở tầng code (không phải thay đổi schema)."""
