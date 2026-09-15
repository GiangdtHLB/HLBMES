"""material_lot: unique(lot_year, lot_code, location) thay vì unique(lot_year, lot_code)

Revision ID: 492bb7ee99aa
Revises: a1b2c3d4e5fa
Create Date: 2026-09-14 22:04:59.361946

Cho phép 1 mã lô (`lot_code`) có NHIỀU dòng `material_lot`, mỗi dòng ở 1 kho (`location`) khác
nhau — điều chuyển MỘT PHẦN 1 lô NVL giữa Kho công ty ↔ Kho phân xưởng không còn sinh mã lô mới
(`_transfer_lot`, services/warehouse.py) mà tách/gộp vào đúng dòng của kho đích, dùng LẠI cùng
`lot_code`. Yêu cầu người dùng: "1 lô tồn ở 2 kho số lượng khác nhau hoàn toàn bình thường", không
nên bị coi là 2 lô khác nhau.

KHÔNG cần di trú dữ liệu: ràng buộc CŨ (lot_year, lot_code) đã đảm bảo mỗi cặp (lot_year, lot_code)
chỉ có ĐÚNG 1 dòng trong toàn hệ thống, nên ràng buộc MỚI (thêm location vào khoá — lỏng hơn, không
chặt hơn) tự động đúng với mọi dòng hiện có, không cần backfill/sửa dữ liệu.

Ghi chú MSSQL (DEPLOY-CONTRACT §3.1 — UNIQUE index trên cột nullable): `location` cho phép NULL
(lô brew/bright/package tạo qua `produce_lot()`, không đi qua `_transfer_lot`, không có `location`).
Về lý thuyết KHÔNG vỡ: vì `lot_code` (không phải `location`) đã là thành phần phân biệt sẵn mỗi
dòng — 2 dòng không thể cùng (lot_year, lot_code) dưới ràng buộc CŨ, nên bộ ba mới luôn duy nhất dù
`location` là NULL ở cả 2. Vẫn seed ≥2 dòng NULL-location khi chạy gate MSSQL để xác nhận thực
nghiệm, không chỉ suy luận (theo đúng cách gate DEPLOY-CONTRACT §3.1 yêu cầu).
"""
from alembic import op
import sqlalchemy as sa


revision = '492bb7ee99aa'
down_revision = 'a1b2c3d4e5fa'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('material_lot', recreate='auto') as batch_op:
        batch_op.drop_constraint('uq_material_lot_year_code', type_='unique')
        batch_op.create_unique_constraint(
            'uq_material_lot_year_code_location', ['lot_year', 'lot_code', 'location'])


def downgrade() -> None:
    conn = op.get_bind()
    dupes = conn.execute(sa.text(
        "SELECT lot_year, lot_code, COUNT(DISTINCT location) AS n_loc "
        "FROM material_lot GROUP BY lot_year, lot_code HAVING COUNT(DISTINCT location) > 1"
    )).mappings().all()
    if dupes:
        sample = ", ".join(f"{d['lot_year']}-{d['lot_code']}" for d in dupes[:10])
        raise RuntimeError(
            f"Không thể downgrade: {len(dupes)} mã lô đang có nhiều dòng ở nhiều kho khác nhau "
            f"(VD: {sample}) — ràng buộc cũ (lot_year, lot_code) sẽ vỡ. Phải gộp/xoá bớt dòng "
            "trùng mã trước khi hạ cấp migration này.")
    with op.batch_alter_table('material_lot', recreate='auto') as batch_op:
        batch_op.drop_constraint('uq_material_lot_year_code_location', type_='unique')
        batch_op.create_unique_constraint('uq_material_lot_year_code', ['lot_year', 'lot_code'])
