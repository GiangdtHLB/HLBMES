"""Công thức NVL mới (Formula/FormulaActivationLog) — thay Recipe/RecipeVersion versioning

Revision ID: a3b4c5d6e7f9
Revises: e4f5a6b7c8d9
Create Date: 2026-08-01

- formula: 1 dòng = 1 công thức độc lập theo dịch bia (KHÔNG version hóa) — nhiều công thức/1
  dịch bia, nhưng chỉ đúng 1 công thức is_active=True tại 1 thời điểm (đảm bảo ở tầng ứng dụng,
  xem services/formula.py::activate_formula). Lệnh nấu tự nạp NVL theo công thức đang active
  (xem services/brew_order.py::_effective_bom — đổi nguồn từ RecipeVersion.state='effective'
  sang Formula.is_active).
- formula_activation_log: lịch sử bật/tắt hiệu lực (ai, lúc nào, đổi gì), hiển thị ngay dưới
  danh sách công thức của mỗi dịch bia.
- Data migration 1 CHIỀU (không đảo ngược lại khi downgrade): chuyển mỗi recipe_version cũ
  thành 1 dòng formula (code = "{recipe.code}-V{version_no}"), giữ nguyên base_qty/base_uom/
  materials/created_by/created_at. Version đang state='effective' -> is_active=True; NẾU CÓ
  NHIỀU HƠN 1 version 'effective' cho cùng product (bug thực tế phát hiện được ở hệ thống cũ —
  _effective_bom() cũ dùng .first() không ORDER BY nên có thể có 2 bản effective cùng lúc mà
  không ai biết), chỉ version_no CAO NHẤT trong số đó được chọn active, còn lại chuyển thành
  is_active=False. KHÔNG xóa/sửa bảng recipe/recipe_version cũ — vẫn cần cho Công thức+
  (nav-unused)/RecipeChange/Signature lịch sử.
"""
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = 'a3b4c5d6e7f9'
down_revision = 'e4f5a6b7c8d9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'formula',
        sa.Column('formula_id', sa.Unicode(64), primary_key=True),
        sa.Column('code', sa.Unicode(64), nullable=False),
        sa.Column('product_id', sa.Unicode(64), sa.ForeignKey('product.product_id'), nullable=False),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.Column('base_qty', sa.Float(), nullable=False, server_default='0'),
        sa.Column('base_uom', sa.Unicode(255), nullable=False, server_default='L'),
        sa.Column('materials', sa.JSON(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('locked', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('locked_by', sa.Unicode(255), nullable=True),
        sa.Column('locked_at', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.Unicode(255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_formula_code', 'formula', ['code'], unique=True)
    op.create_index('ix_formula_product_id', 'formula', ['product_id'])
    op.create_index('ix_formula_is_active', 'formula', ['is_active'])

    op.create_table(
        'formula_activation_log',
        sa.Column('log_id', sa.Unicode(64), primary_key=True),
        sa.Column('formula_id', sa.Unicode(64), sa.ForeignKey('formula.formula_id'), nullable=False),
        sa.Column('product_id', sa.Unicode(64), nullable=False),
        sa.Column('action', sa.Unicode(32), nullable=False),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.Column('changed_by', sa.Unicode(255), nullable=False),
        sa.Column('changed_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_formula_activation_log_formula_id', 'formula_activation_log', ['formula_id'])
    op.create_index('ix_formula_activation_log_product_id', 'formula_activation_log', ['product_id'])

    _migrate_old_recipe_versions()


def _migrate_old_recipe_versions() -> None:
    bind = op.get_bind()

    recipe_t = sa.table(
        'recipe', sa.column('recipe_id', sa.Unicode(64)), sa.column('code', sa.Unicode(64)),
        sa.column('product_id', sa.Unicode(64)))
    version_t = sa.table(
        'recipe_version', sa.column('version_id', sa.Unicode(64)), sa.column('recipe_id', sa.Unicode(64)),
        sa.column('version_no', sa.Integer()), sa.column('state', sa.Unicode(255)),
        sa.column('base_qty', sa.Float()), sa.column('base_uom', sa.Unicode(255)),
        sa.column('materials', sa.JSON()), sa.column('created_by', sa.Unicode(255)),
        sa.column('created_at', sa.DateTime()))

    recipes = {r.recipe_id: (r.code, r.product_id) for r in bind.execute(sa.select(recipe_t)).fetchall()}
    versions = bind.execute(sa.select(version_t)).fetchall()
    if not versions:
        return

    # Xác định version_no cao nhất trong số các bản 'effective' của CÙNG product — trường hợp
    # có nhiều hơn 1 (bug cũ) thì chỉ bản này được active, còn lại tắt (is_active=False).
    winner_by_product: dict[str, int] = {}
    for v in versions:
        recipe = recipes.get(v.recipe_id)
        if not recipe or v.state != 'effective':
            continue
        _, product_id = recipe
        winner_by_product[product_id] = max(winner_by_product.get(product_id, -1), v.version_no)

    formula_t = sa.table(
        'formula', sa.column('formula_id', sa.Unicode(64)), sa.column('code', sa.Unicode(64)),
        sa.column('product_id', sa.Unicode(64)), sa.column('note', sa.UnicodeText()),
        sa.column('base_qty', sa.Float()), sa.column('base_uom', sa.Unicode(255)),
        sa.column('materials', sa.JSON()), sa.column('is_active', sa.Boolean()),
        sa.column('locked', sa.Boolean()), sa.column('created_by', sa.Unicode(255)),
        sa.column('created_at', sa.DateTime()))
    log_t = sa.table(
        'formula_activation_log', sa.column('log_id', sa.Unicode(64)),
        sa.column('formula_id', sa.Unicode(64)), sa.column('product_id', sa.Unicode(64)),
        sa.column('action', sa.Unicode(32)), sa.column('note', sa.UnicodeText()),
        sa.column('changed_by', sa.Unicode(255)), sa.column('changed_at', sa.DateTime()))

    formula_rows, log_rows = [], []
    for v in versions:
        recipe = recipes.get(v.recipe_id)
        if not recipe:
            continue
        recipe_code, product_id = recipe
        is_winner = v.state == 'effective' and v.version_no == winner_by_product.get(product_id)
        formula_id = str(uuid.uuid4())
        created_at = v.created_at or datetime.now(timezone.utc)
        formula_rows.append({
            'formula_id': formula_id, 'code': f"{recipe_code}-V{v.version_no}", 'product_id': product_id,
            'note': f"Chuyển đổi tự động từ recipe_version v{v.version_no} (trạng thái cũ: {v.state}).",
            'base_qty': v.base_qty or 0.0, 'base_uom': v.base_uom or 'L', 'materials': v.materials or [],
            'is_active': is_winner, 'locked': False, 'created_by': v.created_by, 'created_at': created_at,
        })
        if is_winner:
            multi_effective = sum(1 for x in versions if recipes.get(x.recipe_id, (None, None))[1] == product_id
                                  and x.state == 'effective') > 1
            note = ("Chuyển đổi tự động, đang hiệu lực từ hệ thống cũ."
                   if not multi_effective else
                   "Chuyển đổi tự động — hệ thống cũ có NHIỀU HƠN 1 bản 'effective' cho dịch bia này "
                   "(lỗi dữ liệu cũ), đã tự động chọn bản version cao nhất làm hiệu lực.")
            log_rows.append({
                'log_id': str(uuid.uuid4()), 'formula_id': formula_id, 'product_id': product_id,
                'action': 'activate', 'note': note, 'changed_by': v.created_by or 'system',
                'changed_at': created_at,
            })

    if formula_rows:
        op.bulk_insert(formula_t, formula_rows)
    if log_rows:
        op.bulk_insert(log_t, log_rows)


def downgrade() -> None:
    op.drop_index('ix_formula_activation_log_product_id', table_name='formula_activation_log')
    op.drop_index('ix_formula_activation_log_formula_id', table_name='formula_activation_log')
    op.drop_table('formula_activation_log')
    op.drop_index('ix_formula_is_active', table_name='formula')
    op.drop_index('ix_formula_product_id', table_name='formula')
    op.drop_index('ix_formula_code', table_name='formula')
    op.drop_table('formula')
