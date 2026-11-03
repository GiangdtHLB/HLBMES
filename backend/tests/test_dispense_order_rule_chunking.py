"""services/dispense.py::_assert_dispense_order — luật nghiệp vụ "mẻ bắt đầu nấu trước phải
được cấp liệu trước" vừa được chia mẻ `.in_()` (2026-11-03, memory item 18: trần 2100 tham số
bind của SQL Server) ở 2 chỗ: `Dispense.batch_id.in_(earlier_ids)` và
`GenealogyEdge.to_id.in_(earlier_ids)`. Đây là LUẬT NGHIỆP VỤ (chặn/cho phép cấp liệu thật), khác
hẳn các báo cáo chỉ đọc — sai 1 phần tử bị rớt khỏi 1 mẻ chia là cho phép/chặn NHẦM, không ai
biết, nên cần test riêng xác nhận đúng ở QUY MÔ VƯỢT NGƯỠNG CHIA MẺ (IN_CHUNK=900), không chỉ
đúng ở quy mô nhỏ (nơi SQLite/test thường không bao giờ lộ lỗi loại này — xem DEPLOY-CONTRACT
§2(H)).

Tạo trực tiếp qua ORM (không qua HTTP) để đủ nhanh dựng >900 "mẻ trước" — mục tiêu là kiểm tra
đúng hành vi dữ liệu, không phải luồng API đầy đủ (đã có test khác cho luồng API)."""

import os
import tempfile

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["MES_DATABASE_URL"] = f"sqlite:///{_TMP.name}"
os.environ["MES_DEV_HEADER_AUTH"] = "0"
os.environ["MES_RL_ENABLED"] = "0"
os.environ.setdefault("MES_LLM_ENABLED", "off")

import pytest
from datetime import timedelta
from sqlalchemy import select

from app.main import app  # noqa: F401 — đăng ký đủ model trước khi import service/model khác
from app import seed as seed_mod
from app.common import BatchState, GenealogyRelation, IN_CHUNK, new_id, utcnow
from app.database import SessionLocal
from app.errors import DomainError
from app.models.batches import BatchExecution
from app.models.brewing import BrewOrder
from app.models.materials import GenealogyEdge
from app.models.master import BeerType, Product
from app.models.recipes import Recipe, RecipeVersion
from app.services import dispense


@pytest.fixture(scope="module", autouse=True)
def _seeded():
    seed_mod.seed()
    yield


@pytest.fixture(scope="module")
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture(scope="module")
def shared_order_recipe_product(db):
    """1 Lệnh nấu/công thức/dịch bia dùng chung cho mọi mẻ "mồi" — tránh dựng lại hàng nghìn bộ
    danh mục chỉ để test thuần logic xếp hàng theo start_at/state."""
    order = db.execute(select(BrewOrder)).scalars().first()
    if order is None:
        order = BrewOrder(brew_order_id=new_id(), order_code="ORD-CHUNK-TEST", order_year=2026,
                          planned_batch_count=1, planned_volume_hl=100.0, volume_tolerance_hl=5.0)
        db.add(order)
    beer_type = BeerType(beer_type_id=new_id(), code="BT-CHUNK-TEST", name="Loai chunk test")
    db.add(beer_type)
    db.flush()
    product = Product(product_id=new_id(), code="PRD-CHUNK-TEST", name="Dich chunk test", uom="L",
                      beer_type_id=beer_type.beer_type_id)
    recipe = Recipe(recipe_id=new_id(), code="CT-CHUNK-TEST", name="Recipe chunk test",
                    beer_type_id=beer_type.beer_type_id)
    db.add_all([product, recipe])
    db.flush()
    rv = RecipeVersion(version_id=new_id(), recipe_id=recipe.recipe_id, product_id=product.product_id,
                       version_no=1, base_qty=100.0, base_uom="L", state="effective", materials=[])
    db.add(rv)
    db.commit()
    return order.brew_order_id, rv.version_id, product.product_id


def _bulk_insert_batches(db, order_id, version_id, product_id, count, start_base, state):
    """Chèn thẳng `count` dòng BatchExecution qua ORM (nhanh, không qua HTTP) — start_at tăng dần
    từng giây kể từ `start_base`, đều ở trạng thái `state` (mặc định "running", nằm trong
    always_states nên luôn tính là "mẻ trước" đủ điều kiện xếp hàng bất kể _ORDER_RULE_EXTENDED_
    STATES_SINCE)."""
    rows = []
    for i in range(count):
        rows.append(BatchExecution(
            batch_id=new_id(), batch_code=f"CHUNK-{start_base.isoformat()}-{i}", batch_year=2026,
            order_id=order_id, recipe_version_id=version_id, product_id=product_id,
            state=state, planned_qty=100.0, uom="L", recipe_snapshot={},
            start_at=start_base + timedelta(seconds=i),
        ))
    db.add_all(rows)
    db.commit()
    return rows


def test_order_rule_blocks_when_more_than_in_chunk_earlier_batches_undispensed(
        db, shared_order_recipe_product):
    """> IN_CHUNK (900) mẻ trước, CHƯA mẻ nào cấp liệu — mẻ sau phải bị chặn, và thông báo lỗi
    phải liệt kê đúng (ít nhất 1) mẻ vi phạm — chứng minh _assert_dispense_order không "bỏ sót"
    bất kỳ chunk nào khi gom earlier_ids thành dispensed_ids (nếu chunking sai, hàm có thể coi
    nhầm 1 chunk là "đã cấp đủ" rồi bỏ qua luôn các chunk còn lại)."""
    order_id, version_id, product_id = shared_order_recipe_product
    base = utcnow() - timedelta(days=1)
    count = IN_CHUNK + 600   # > 1 chunk, không chia hết IN_CHUNK để lộ lỗi chia dư nếu có
    earlier = _bulk_insert_batches(db, order_id, version_id, product_id, count, base, "running")

    later = BatchExecution(batch_id=new_id(), batch_code="CHUNK-LATER-1", batch_year=2026,
                           order_id=order_id, recipe_version_id=version_id, product_id=product_id,
                           state="running", planned_qty=100.0, uom="L", recipe_snapshot={},
                           start_at=base + timedelta(seconds=count + 10))
    db.add(later)
    db.commit()

    with pytest.raises(DomainError, match="bắt đầu nấu trước mẻ này và chưa cấp liệu"):
        dispense._assert_dispense_order(db, later)

    # Dọn để không ảnh hưởng test sau trong cùng DB module-scope.
    for b in earlier:
        db.delete(b)
    db.delete(later)
    db.commit()


def test_order_rule_allows_when_all_earlier_batches_dispensed_via_direct_consume_across_chunks(
        db, shared_order_recipe_product):
    """> IN_CHUNK mẻ trước, MỌI mẻ đã tiêu thụ qua GenealogyEdge(consume) trực tiếp (không qua
    DispenseLine — nhánh dispensed_via_consume) — mẻ sau phải được PHÉP cấp liệu. Đây là test
    quan trọng nhất: nếu execute_in_chunks lỡ chỉ kiểm tra 1 chunk của earlier_ids (bug chia mẻ
    kinh điển — vd range() sai bước, hoặc quên nối kết quả `extend` mà `=` đè mất chunk trước),
    test này sẽ FAIL vì các mẻ ở chunk bị bỏ sót vẫn bị coi là "chưa cấp liệu" và tiếp tục chặn."""
    order_id, version_id, product_id = shared_order_recipe_product
    base = utcnow() - timedelta(days=2)
    count = IN_CHUNK + 600
    earlier = _bulk_insert_batches(db, order_id, version_id, product_id, count, base, "running")

    # Mỗi mẻ trước tiêu thụ qua đúng 1 GenealogyEdge(relation=consume, to_type="batch") — không
    # cần lô NVL thật tồn tại, _assert_dispense_order chỉ tra to_id, không join sang MaterialLot.
    edges = [GenealogyEdge(edge_id=new_id(), from_type="lot", from_id=new_id(),
                           to_type="batch", to_id=b.batch_id,
                           relation=GenealogyRelation.CONSUME.value, quantity=1.0,
                           event_time=b.start_at) for b in earlier]
    db.add_all(edges)
    db.commit()

    later = BatchExecution(batch_id=new_id(), batch_code="CHUNK-LATER-2", batch_year=2026,
                           order_id=order_id, recipe_version_id=version_id, product_id=product_id,
                           state="running", planned_qty=100.0, uom="L", recipe_snapshot={},
                           start_at=base + timedelta(seconds=count + 10))
    db.add(later)
    db.commit()

    dispense._assert_dispense_order(db, later)   # không raise => đúng

    for e in edges:
        db.delete(e)
    for b in earlier:
        db.delete(b)
    db.delete(later)
    db.commit()


def test_order_rule_blocks_when_only_the_last_chunk_is_undispensed(db, shared_order_recipe_product):
    """Biên quan trọng nhất: mọi mẻ trước đã cấp liệu TRỪ đúng 1 mẻ nằm Ở CHUNK CUỐI CÙNG (sau vị
    trí IN_CHUNK) — phải vẫn bị chặn đúng mẻ đó. Nếu execute_in_chunks chỉ xử lý chunk ĐẦU rồi
    dừng sớm (bug "return" thay vì "continue"/"extend" trong vòng lặp), test earlier (toàn bộ đã
    cấp) sẽ pass giả do trùng hợp, nhưng test này sẽ lộ ra vì mẻ chưa cấp nằm ở chunk sau."""
    order_id, version_id, product_id = shared_order_recipe_product
    base = utcnow() - timedelta(days=3)
    count = IN_CHUNK + 50
    earlier = _bulk_insert_batches(db, order_id, version_id, product_id, count, base, "running")

    # Cấp (qua GenealogyEdge consume) cho MỌI mẻ TRỪ mẻ cuối cùng (chắc chắn nằm ở chunk thứ 2).
    undispensed = earlier[-1]
    to_dispense = earlier[:-1]
    edges = [GenealogyEdge(edge_id=new_id(), from_type="lot", from_id=new_id(),
                           to_type="batch", to_id=b.batch_id,
                           relation=GenealogyRelation.CONSUME.value, quantity=1.0,
                           event_time=b.start_at) for b in to_dispense]
    db.add_all(edges)
    db.commit()

    later = BatchExecution(batch_id=new_id(), batch_code="CHUNK-LATER-3", batch_year=2026,
                           order_id=order_id, recipe_version_id=version_id, product_id=product_id,
                           state="running", planned_qty=100.0, uom="L", recipe_snapshot={},
                           start_at=base + timedelta(seconds=count + 10))
    db.add(later)
    db.commit()

    with pytest.raises(DomainError) as exc_info:
        dispense._assert_dispense_order(db, later)
    assert undispensed.batch_code in str(exc_info.value)

    for e in edges:
        db.delete(e)
    for b in earlier:
        db.delete(b)
    db.delete(later)
    db.commit()
