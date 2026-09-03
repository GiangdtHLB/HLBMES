"""Seed dữ liệu nhà máy bia + kịch bản end-to-end để demo.

Chạy:  python -m app.seed         (từ thư mục backend, trong venv)
Tạo: products, materials, recipe (effective), order, material lots,
rồi chạy 1 mẻ: create → consume → run → QC pass → produce → release →
close, để có sẵn dữ liệu genealogy cho phần truy xuất/recall.
"""

from datetime import timedelta

from sqlalchemy import select

from .common import LotStatus, Role, new_id, utcnow
from .config import SEED_DEMO
from .database import SessionLocal, init_db
from .models.brewing import (
    BottleRecord,
    BrewOrder,
    BrewRecord,
    FermentRecord,
    FilterRecord,
    MaterialReceipt,
    StageIndicator,
)
from .models.auth import RoleTemplate, User as AppUser
from .models.batches import BatchExecution
from .models.energy import EnergyArea, EnergyGroup, EnergyReading
from .models.integration import ApiKey
from .security import hash_password
from .models.maintenance import Calibration, Equipment, Incident, MaintenancePlan, SparePart
from .models.master import BeerType, Material, Product
from .models.materials import MaterialLot
from .models.metrics import OEERecord, ProcessReading
from .models.process import ChemicalUsage, YeastIssue, YeastLot
from .models.recipes import Recipe, RecipeVersion
from .models.formula import Formula
from .models.recipe_ext import BatchYieldActual, RecipeChange
from .models.quality_ext import CAPA, QCParameter, Sample
from .models.quality import QualityResult
from .models.oee_ext import DowntimeEvent
from .models.materials_ext import Dispense, DispenseLine
from .models.warehouse import StockMovement
from .security import User
from .services import batches as batch_svc
from .services import quality as qual_svc
from .services import recipes as recipe_svc
from .services import formula as formula_svc

ENG = User("engineer1", Role.ENGINEER.value)
QA = User("qa1", Role.QA.value)
SUP = User("supervisor1", Role.SUPERVISOR.value)
OP = User("operator1", Role.OPERATOR.value)


def _get_or_create_beer_type(db, code, name):
    bt = db.execute(select(BeerType).where(BeerType.code == code)).scalar_one_or_none()
    if not bt:
        bt = BeerType(beer_type_id=new_id(), code=code, name=name)
        db.add(bt)
        db.commit()
    return bt


def _get_or_create_product(db, code, name, uom="L", beer_type_id=None):
    p = db.execute(select(Product).where(Product.code == code)).scalar_one_or_none()
    if not p:
        p = Product(product_id=new_id(), code=code, name=name, uom=uom, beer_type_id=beer_type_id)
        db.add(p)
        db.commit()
    return p


def _get_or_create_material(db, code, name, uom, category):
    m = db.execute(select(Material).where(Material.code == code)).scalar_one_or_none()
    if not m:
        m = Material(material_id=new_id(), code=code, name=name, uom=uom, category=category)
        db.add(m)
        db.commit()
    return m


def ensure_admin(db) -> None:
    """Luôn đảm bảo có tài khoản admin. Mật khẩu lấy từ MES_ADMIN_PASSWORD;
    nếu không đặt → dùng 'admin123' nhưng BẮT BUỘC đổi mật khẩu lần đầu."""
    from .config import ADMIN_PASSWORD
    if db.execute(select(AppUser).where(AppUser.username == "admin")).scalar_one_or_none():
        return
    pw = ADMIN_PASSWORD or "admin123"
    must_change = not ADMIN_PASSWORD          # mật khẩu mặc định → buộc đổi
    db.add(AppUser(user_id=new_id(), username="admin", password_hash=hash_password(pw),
                   full_name="Quản trị viên", job_title="Quản trị hệ thống", role="admin",
                   allowed_views="*", permissions="*", scope_lines="*", scope_areas="*",
                   scope_qc="*", scope_warehouse="*", active=True, must_change_password=must_change))
    db.commit()
    if must_change:
        print("⚠️  Đã tạo admin với mật khẩu MẶC ĐỊNH 'admin123' — sẽ buộc đổi khi đăng nhập. "
              "Đặt MES_ADMIN_PASSWORD để dùng mật khẩu riêng (không buộc đổi).")


def ensure_unit_types(db) -> None:
    """Luôn đảm bảo có đủ 3 loại đơn vị tồn kho hệ thống (vi/keg/lon) trong Danh mục Loại đơn
    vị tồn kho — bắt buộc phải có ngay từ đầu để services/wms.py::_pack_divisor tính đúng
    (dữ liệu cấu trúc lõi, không phải dữ liệu demo, xem migration 1f8a7f187deb cho môi trường
    dùng alembic upgrade thay vì create_all() + seed()/init_db() như ở đây)."""
    from .models.master import UnitTypeCatalog
    existing = {ut.code for ut in db.execute(select(UnitTypeCatalog)).scalars().all()}
    defaults = [
        ("vi", "Vỉ", True, True),
        ("keg", "Keg", False, True),
        ("lon", "Lon (phân rã)", False, False),
    ]
    added = False
    for code, name, divide, selectable in defaults:
        if code in existing:
            continue
        db.add(UnitTypeCatalog(unit_type_id=new_id(), code=code, name=name,
                               divide_by_pack_size=divide, selectable=selectable, active=True))
        added = True
    if added:
        db.commit()


def seed():
    init_db()
    db = SessionLocal()
    ensure_admin(db)
    ensure_unit_types(db)
    if not SEED_DEMO:
        print("MES_SEED_DEMO=0 → chỉ tạo admin, KHÔNG seed tài khoản/API key/dữ liệu demo (an toàn cho production).")
        db.close()
        return
    if db.execute(select(BrewOrder).where(BrewOrder.order_code == "PO-2406-1001")).first():
        print("Đã có dữ liệu — bỏ qua seed. (Xóa backend/mes.db để seed lại.)")
        db.close()
        return

    # --- Master data ---
    lager_type = _get_or_create_beer_type(db, "LAGER", "Lager")
    lager = _get_or_create_product(db, "BIA-LAGER", "Bia Lager 4.8%", "L", beer_type_id=lager_type.beer_type_id)
    malt = _get_or_create_material(db, "MALT-PILS", "Malt Pilsner", "kg", "malt")
    hop = _get_or_create_material(db, "HOP-SAAZ", "Hoa bia Saaz", "kg", "hop")
    yeast = _get_or_create_material(db, "YEAST-L34", "Men Lager W-34/70", "L", "yeast")
    # Nguyên liệu thay thế (alternates) cho malt chính — demo #3.
    malt_alt = _get_or_create_material(db, "MALT-VIENNA", "Malt Vienna (thay thế)", "kg", "malt")

    # --- Material lots (nguyên liệu đầu vào) ---
    lots = [
        MaterialLot(lot_id=new_id(), lot_code="MALT-2406-01", lot_year=2024, material_id=malt.material_id,
                    lot_type="material", supplier_lot="SUP-M-991", quantity=5000, uom="kg",
                    status=LotStatus.AVAILABLE.value, location="Kho công ty"),
        MaterialLot(lot_id=new_id(), lot_code="HOP-2406-01", lot_year=2024, material_id=hop.material_id,
                    lot_type="material", supplier_lot="SUP-H-220", quantity=80, uom="kg",
                    status=LotStatus.AVAILABLE.value, location="Kho công ty"),
        MaterialLot(lot_id=new_id(), lot_code="YEAST-2406-01", lot_year=2024, material_id=yeast.material_id,
                    lot_type="material", supplier_lot="SUP-Y-007", quantity=200, uom="L",
                    status=LotStatus.AVAILABLE.value, location="Kho công ty"),
        MaterialLot(lot_id=new_id(), lot_code="MALT-V-2406-01", lot_year=2024, material_id=malt_alt.material_id,
                    lot_type="material", supplier_lot="SUP-MV-101", quantity=3000, uom="kg",
                    status=LotStatus.AVAILABLE.value, location="Kho công ty",
                    expiry=utcnow() + timedelta(days=180)),
    ]
    db.add_all(lots)
    db.commit()

    # --- Recipe + version (draft → review → approved → effective) ---
    recipe = db.execute(select(Recipe).where(Recipe.code == "REC-LAGER")).scalar_one_or_none()
    if not recipe:
        recipe = Recipe(recipe_id=new_id(), code="REC-LAGER", name="Công thức Bia Lager",
                        beer_type_id=lager_type.beer_type_id)
        db.add(recipe)
        db.commit()

    rv = recipe_svc.create_version(db, recipe.recipe_id, {
        "product_id": lager.product_id,
        "base_qty": 50000, "base_uom": "L",   # BOM định mức cho mẻ chuẩn 50.000 L
        "parameters": [
            {"name": "Nhiệt độ đường hóa", "target": 65, "lower": 63, "upper": 67, "unit": "°C", "phase": "mash"},
            {"name": "Thời gian sôi", "target": 60, "lower": 55, "upper": 70, "unit": "phút", "phase": "boil"},
            {"name": "Nhiệt độ lên men", "target": 12, "lower": 10, "upper": 14, "unit": "°C", "phase": "ferment"},
        ],
        "materials": [
            {"material_code": "MALT-PILS", "qty": 1200, "uom": "kg", "tol_pct": 3,
             "alternates": [{"material_code": "MALT-VIENNA", "factor": 1.05, "priority": 1}]},
            {"material_code": "HOP-SAAZ", "qty": 15, "uom": "kg", "tol_pct": 5},
            {"material_code": "YEAST-L34", "qty": 50, "uom": "L", "tol_pct": 10},
        ],
        "quality_checks": [
            {"parameter": "Độ đường (°P)", "method": "Refractometer", "lower": 11.0, "upper": 12.5, "unit": "°P", "mandatory": True},
            {"parameter": "pH", "method": "pH meter", "lower": 4.2, "upper": 4.6, "unit": "", "mandatory": True},
        ],
        # Hiệu suất kỳ vọng theo công đoạn (yield) — demo #3.
        "yield_steps": [
            {"step_key": "nau", "label": "Nấu (dịch nha)", "step_no": 1, "expected_pct": 98, "warn_pct": 95},
            {"step_key": "len_men", "label": "Lên men", "step_no": 2, "expected_pct": 95, "warn_pct": 90},
            {"step_key": "loc", "label": "Lọc", "step_no": 3, "expected_pct": 98, "warn_pct": 96},
            {"step_key": "chiet", "label": "Chiết", "step_no": 4, "expected_pct": 97, "warn_pct": 94},
        ],
        # Thủ tục ISA-88 (procedure → unit procedure → operation → phase) — demo #P3-1.
        "procedure": [
            {"name": "Nấu", "unit_class": "brewhouse", "operations": [
                {"name": "Đường hóa", "phases": [
                    {"name": "Vào liệu", "params": [{"name": "Nhiệt độ", "setpoint": 52, "unit": "°C"}]},
                    {"name": "Giữ 65°C", "params": [{"name": "Nhiệt độ", "setpoint": 65, "unit": "°C"}], "duration_min": 30},
                    {"name": "Nâng 76°C", "params": [{"name": "Nhiệt độ", "setpoint": 76, "unit": "°C"}], "duration_min": 10}]},
                {"name": "Lọc bã", "phases": [{"name": "Lọc bã", "duration_min": 60}]},
                {"name": "Sôi hoa", "phases": [
                    {"name": "Thêm hoa", "params": [{"name": "Hoa Saaz", "setpoint": 15, "unit": "kg"}]},
                    {"name": "Sôi", "duration_min": 60}]}]},
            {"name": "Lên men", "unit_class": "fv", "operations": [
                {"name": "Cấy men", "phases": [{"name": "Bơm men", "params": [{"name": "Men", "setpoint": 50, "unit": "L"}]}]},
                {"name": "Lên men chính", "phases": [{"name": "Giữ 12°C", "params": [{"name": "Nhiệt độ", "setpoint": 12, "unit": "°C"}], "duration_min": 10080}]},
                {"name": "Hạ nhiệt", "phases": [{"name": "Hạ 2°C", "params": [{"name": "Nhiệt độ", "setpoint": 2, "unit": "°C"}]}]}]},
            {"name": "Lọc", "unit_class": "filter", "operations": [
                {"name": "Lọc nến", "phases": [{"name": "Lọc", "duration_min": 120}]}]},
            {"name": "CIP Nồi nấu", "unit_class": "cip", "operations": [
                {"name": "CIP", "phases": [
                    {"name": "Tiền rửa", "duration_min": 10},
                    {"name": "Xút 2%", "params": [{"name": "NaOH", "setpoint": 2, "unit": "%"}], "duration_min": 20},
                    {"name": "Tráng nước", "duration_min": 10}]}]},
        ],
    }, ENG)
    recipe_svc.transition(db, rv.version_id, "review", ENG)
    recipe_svc.transition(db, rv.version_id, "approved", QA)   # QA duyệt (SoD: khác người soạn)
    recipe_svc.transition(db, rv.version_id, "effective", ENG)

    # --- Formula (mô hình mới thay Recipe/RecipeVersion — xem models/formula.py) ---
    # Recipe/RecipeVersion ở trên giữ nguyên cho Công thức+ (nav-unused) cũ; Lệnh nấu
    # (services/brew_order.py::_effective_bom) chỉ đọc Formula, nên seed cũng phải tạo +
    # kích hoạt 1 Formula cho BIA-LAGER — nếu không, DB seed mới (test/dev từ trống) sẽ
    # không có Formula nào cho product này dù Recipe cũ đã "effective" (2 mô hình độc lập,
    # migration chỉ tự chuyển đổi dữ liệu recipe_version ĐÃ CÓ SẴN lúc chạy alembic, không
    # áp dụng cho dữ liệu seed() tạo ra sau đó).
    lager_formula = db.execute(select(Formula).where(Formula.code == "REC-LAGER-V1")).scalar_one_or_none()
    if not lager_formula:
        lager_formula = formula_svc.create_formula(db, {
            "code": "REC-LAGER-V1", "product_id": lager.product_id,
            "note": "Seed demo — mirror của REC-LAGER (RecipeVersion cũ) cho Lệnh nấu tự nạp NVL.",
            "base_qty": 50000, "base_uom": "L",
            "materials": [
                {"material_code": "MALT-PILS", "qty": 1200, "uom": "kg"},
                {"material_code": "HOP-SAAZ", "qty": 15, "uom": "kg"},
                {"material_code": "YEAST-L34", "qty": 50, "uom": "L"},
            ],
        }, ENG)
        formula_svc.activate_formula(db, lager_formula.formula_id, ENG)

    # --- Lệnh nấu (BrewOrder) làm cha cho mẻ demo end-to-end ---
    order = BrewOrder(brew_order_id=new_id(), order_code="PO-2406-1001", order_year=utcnow().year,
                      product_id=lager.product_id, recipe_version_id=rv.version_id,
                      planned_volume_hl=50000, created_at=utcnow())
    db.add(order)
    db.commit()

    # --- Kịch bản end-to-end cho một mẻ ---
    # Mã mẻ Braumat BẮT BUỘC số nguyên (unique theo năm) từ 2026-09-02 — xem
    # services/batches.py::create_batch; seed dùng "9001"/"9002" (số cao, tránh trùng với mã nhỏ 1,2,3... mà các test file khác hay tự đặt trong cùng 1 DB tạm) thay vì mã mô tả cũ "B-2406-0001".
    batch = batch_svc.create_batch(db, order.brew_order_id, rv.version_id, SUP,
                                   batch_code="9001", planned_qty=50000)
    # consume nguyên liệu
    malt_lot = db.execute(select(MaterialLot).where(MaterialLot.lot_code == "MALT-2406-01")).scalar_one()
    hop_lot = db.execute(select(MaterialLot).where(MaterialLot.lot_code == "HOP-2406-01")).scalar_one()
    yeast_lot = db.execute(select(MaterialLot).where(MaterialLot.lot_code == "YEAST-2406-01")).scalar_one()
    batch_svc.transition(db, batch.batch_id, "ready", SUP)
    batch_svc.transition(db, batch.batch_id, "running", OP)
    batch_svc.consume_lot(db, batch.batch_id, malt_lot.lot_id, 1200, OP)
    batch_svc.consume_lot(db, batch.batch_id, hop_lot.lot_id, 15, OP)
    batch_svc.consume_lot(db, batch.batch_id, yeast_lot.lot_id, 50, OP)
    batch_svc.record_actual(db, batch.batch_id, {"name": "Nhiệt độ đường hóa", "target": 65,
                                                 "actual": 64.5, "unit": "°C", "phase": "mash"}, OP)
    # QC pass
    qual_svc.record_result(db, {"scope_type": "batch", "scope_id": batch.batch_id,
                                "parameter": "Độ đường (°P)", "method": "Refractometer",
                                "value": 11.8, "unit": "°P", "lower_limit": 11.0, "upper_limit": 12.5}, QA)
    qual_svc.record_result(db, {"scope_type": "batch", "scope_id": batch.batch_id,
                                "parameter": "pH", "method": "pH meter",
                                "value": 4.4, "unit": "", "lower_limit": 4.2, "upper_limit": 4.6}, QA)
    # tạo lô bright beer
    bright = batch_svc.produce_lot(db, batch.batch_id, "BRIGHT-2406-0001", 48500, "bright", OP)
    batch_svc.set_actual_qty(db, batch.batch_id, 48500, OP)
    batch_svc.set_end_at(db, batch.batch_id, utcnow(), OP)
    batch_svc.transition(db, batch.batch_id, "completed", OP)
    # release chất lượng cho mẻ và lô bright
    qual_svc.set_hold(db, "batch", batch.batch_id, on_hold=False, user=QA, reason="QC đạt")
    qual_svc.set_hold(db, "lot", bright.lot_id, on_hold=False, user=QA, reason="Release để đóng gói")
    # đóng gói: tạo package lot từ bright (consume bright -> produce package qua mẻ giả lập)
    # ở MVP minh hoạ genealogy bright->package bằng edge produce từ cùng batch:
    pkg = batch_svc.produce_lot(db, batch.batch_id, "PKG-2406-0001", 47000, "package", OP)
    qual_svc.set_hold(db, "lot", pkg.lot_id, on_hold=False, user=QA, reason="Thành phẩm đạt")
    batch_svc.transition(db, batch.batch_id, "closed", SUP)

    _seed_workorders(db, order, rv, batch)
    _seed_fermentation_curve(db, batch.batch_id)
    _seed_oee(db)
    _seed_warehouse(db, [malt, hop, yeast])
    _seed_energy(db)
    _seed_maintenance(db)
    _seed_process(db, batch.batch_id)
    _seed_brewing(db)
    _seed_recipe_ext(db, recipe.recipe_id, rv, batch.batch_id)
    _seed_isa88(db)
    _seed_quality_adv(db, batch.batch_id)
    _seed_downtime(db)
    _seed_oee_reason_catalog(db)
    _seed_oee_reason_catalog_keg30k(db)
    _seed_dispense(db, batch.batch_id, [malt, hop, yeast])
    _seed_lines(db)
    _seed_cip(db)
    _seed_packaging(db)
    _seed_schedule(db)
    _seed_wms(db)
    # API key: lấy từ env (MES_DEMO_READ_KEY/MES_EDGE_KEY) nếu có, KHÔNG hardcode bí mật.
    # Thiếu env → sinh ngẫu nhiên và IN RA MỘT LẦN (lưu lại để cấu hình edge/ERP).
    import os
    import secrets
    read_token = os.environ.get("MES_DEMO_READ_KEY") or ("read_" + secrets.token_urlsafe(18))
    edge_token = os.environ.get("MES_EDGE_KEY") or ("edge_" + secrets.token_urlsafe(18))
    db.add(ApiKey(key_id=new_id(), name="Demo ERP (read)", token=read_token,
                  scopes="read", created_by="admin"))
    db.add(ApiKey(key_id=new_id(), name="Edge Gateway (write)", token=edge_token,
                  scopes="read,write", created_by="admin"))
    from .services import historian as hist_svc
    hist_svc.backfill(db, hours=6, step_min=5)   # 6h dữ liệu sensor mô phỏng
    _seed_users(db)
    _seed_role_templates(db)
    db.commit()

    db.close()
    print("Seed xong. Order PO-2406-1001, mẻ 9001 đã chạy & close.")
    print("Thử truy xuất: GET /api/trace/backward?code=PKG-2406-0001")
    print(f"API key (read) : {read_token}")
    print(f"API key (write/edge): {edge_token}")
    print("→ Lưu lại 2 khóa trên (đặt MES_EDGE_KEY / MES_DEMO_READ_KEY để cố định).")


def _seed_workorders(db, order, rv, batch) -> None:
    """Vài lệnh sản xuất cho bảng điều độ; gắn mẻ đã chạy vào 1 WO completed."""
    from .models.workorder import WorkOrder
    from .common import WorkOrderState
    today = utcnow().date()
    wo1 = WorkOrder(wo_id=new_id(), wo_code="WO-2406-001", brew_order_id=order.brew_order_id,
                    product_id=order.product_id, recipe_version_id=rv.version_id, planned_qty=50000,
                    uom="L", line="Nấu A", shift="A", scheduled_date=today - timedelta(days=1),
                    priority=3, status=WorkOrderState.COMPLETED.value, created_by="quandoc")
    wo2 = WorkOrder(wo_id=new_id(), wo_code="WO-2406-002", brew_order_id=order.brew_order_id,
                    product_id=order.product_id, recipe_version_id=rv.version_id, planned_qty=50000,
                    uom="L", line="Nấu A", shift="B", scheduled_date=today,
                    priority=2, status=WorkOrderState.RELEASED.value, created_by="quandoc")
    wo3 = WorkOrder(wo_id=new_id(), wo_code="WO-2406-003", brew_order_id=order.brew_order_id,
                    product_id=order.product_id, recipe_version_id=rv.version_id, planned_qty=25000,
                    uom="L", line="Nấu B", shift="A", scheduled_date=today + timedelta(days=1),
                    priority=5, status=WorkOrderState.PLANNED.value, created_by="quandoc")
    # Thêm nhu cầu cho bộ lập lịch (P3-2): vài WO released rải trong tuần; WO-006 SL lớn → thiếu NVL.
    extra = []
    demand = [("004", 40000, 0, 2), ("005", 50000, 1, 3), ("006", 500000, 1, 1),
              ("007", 30000, 2, 4), ("008", 45000, 3, 2)]
    for code, qty, day_off, prio in demand:
        extra.append(WorkOrder(wo_id=new_id(), wo_code=f"WO-2406-{code}", brew_order_id=order.brew_order_id,
                               product_id=order.product_id, recipe_version_id=rv.version_id, planned_qty=qty,
                               uom="L", line="Nấu A", shift="A", scheduled_date=today + timedelta(days=day_off),
                               priority=prio, status=WorkOrderState.RELEASED.value, created_by="quandoc"))
    db.add_all([wo1, wo2, wo3] + extra)
    db.commit()
    batch.work_order_id = wo1.wo_id   # mẻ đã chạy thuộc WO-001 (completed)
    db.commit()

    # Mẻ thứ 2 (đang chạy, CHƯA cấp liệu) thuộc WO-002 (Nấu A) — để demo Cấp liệu/Backflush.
    rv_eff = db.execute(select(RecipeVersion).where(
        RecipeVersion.recipe_id == rv.recipe_id, RecipeVersion.state == "effective")).scalars().first()
    b2 = batch_svc.create_batch(db, order.brew_order_id, rv_eff.version_id, SUP,
                                batch_code="9002", planned_qty=50000,
                                work_order_id=wo2.wo_id)
    batch_svc.transition(db, b2.batch_id, "ready", SUP)
    batch_svc.transition(db, b2.batch_id, "running", OP)


def _seed_fermentation_curve(db, batch_id: str) -> None:
    """Sinh đường cong lên men lager ~7 ngày, điểm mỗi 6 giờ:
    - gravity (°P): giảm từ 12 → ~2.6 (lên men đường)
    - temperature (°C): giữ ~12, diacetyl rest lên 14 (ngày 5-6), rồi crash về 2
    - pH: giảm từ 5.2 → ~4.4
    """
    start = utcnow() - timedelta(days=9)  # mẻ đã lên men trong quá khứ
    points = 7 * 4  # 28 điểm
    rows = []
    for i in range(points + 1):
        day = i / 4.0
        ts = start + timedelta(hours=6 * i)
        # gravity giảm theo dạng mũ về attenuation
        gravity = 2.6 + (12.0 - 2.6) * (2.71828 ** (-0.55 * day))
        # nhiệt độ
        if day < 5:
            temp = 12.0 + (0.3 if (i % 3 == 0) else -0.2)  # dao động nhẹ quanh 12
        elif day < 6:
            temp = 12.0 + (14.0 - 12.0) * (day - 5)         # diacetyl rest ramp 12->14
        else:
            temp = 14.0 - (14.0 - 2.0) * (day - 6)          # crash 14->2
        ph = 5.2 - (5.2 - 4.4) * min(day / 6.0, 1.0)
        rows.append(ProcessReading(reading_id=new_id(), batch_id=batch_id, parameter="gravity",
                                   value=round(gravity, 2), unit="°P", ts=ts))
        rows.append(ProcessReading(reading_id=new_id(), batch_id=batch_id, parameter="temperature",
                                   value=round(temp, 2), unit="°C", ts=ts))
        rows.append(ProcessReading(reading_id=new_id(), batch_id=batch_id, parameter="pH",
                                   value=round(ph, 2), unit="", ts=ts))
    db.add_all(rows)
    db.commit()


def _seed_oee(db) -> None:
    """Dữ liệu OEE đóng gói cho vài ca/line."""
    base = utcnow().replace(hour=6, minute=0, second=0, microsecond=0)
    recs = [
        OEERecord(oee_id=new_id(), line="Line-1 (chai)", shift="A", shift_date=base,
                  planned_time_min=480, downtime_min=65, ideal_rate_per_min=500,
                  total_count=195000, good_count=191000,
                  downtime_reasons=[{"reason": "Đổi nhãn/SKU", "minutes": 28},
                                    {"reason": "Kẹt băng tải", "minutes": 22},
                                    {"reason": "Hết keo dán", "minutes": 15}]),
        OEERecord(oee_id=new_id(), line="Line-1 (chai)", shift="B", shift_date=base - timedelta(days=1),
                  planned_time_min=480, downtime_min=48, ideal_rate_per_min=500,
                  total_count=205000, good_count=202500,
                  downtime_reasons=[{"reason": "Vệ sinh giữa ca", "minutes": 30},
                                    {"reason": "Lỗi coder", "minutes": 18}]),
        OEERecord(oee_id=new_id(), line="Line-2 (lon)", shift="A", shift_date=base,
                  planned_time_min=480, downtime_min=92, ideal_rate_per_min=720,
                  total_count=268000, good_count=258000,
                  downtime_reasons=[{"reason": "Sự cố seamer", "minutes": 55},
                                    {"reason": "Chờ vật tư", "minutes": 37}]),
    ]
    db.add_all(recs)
    db.commit()


def _seed_warehouse(db, materials) -> None:
    """Vài giao dịch kho để có thẻ kho/báo cáo."""
    now = utcnow()
    for mat in materials:
        lot = db.execute(select(MaterialLot).where(MaterialLot.material_id == mat.material_id)).scalars().first()
        if not lot:
            continue
        db.add_all([
            StockMovement(movement_id=new_id(), movement_type="receipt", material_id=mat.material_id,
                          lot_id=lot.lot_id, lot_code=lot.lot_code, quantity=lot.quantity + 200, uom=lot.uom,
                          location_to=lot.location, reason="Nhập đầu kỳ", actor="operator1",
                          ts=now - timedelta(days=10)),
            StockMovement(movement_id=new_id(), movement_type="issue", material_id=mat.material_id,
                          lot_id=lot.lot_id, lot_code=lot.lot_code, quantity=200, uom=lot.uom,
                          location_from=lot.location, mode="de_nghi", reason="Cấp cho mẻ 9001",
                          actor="operator1", ts=now - timedelta(days=2)),
        ])
    db.commit()


def _seed_energy(db) -> None:
    groups = [
        EnergyGroup(group_id=new_id(), code="DIEN", name="Điện", unit="kWh"),
        EnergyGroup(group_id=new_id(), code="NUOC", name="Nước", unit="m³"),
        EnergyGroup(group_id=new_id(), code="HOI", name="Hơi", unit="tấn"),
    ]
    areas = [
        EnergyArea(area_id=new_id(), code="NAU", name="Khu nấu"),
        EnergyArea(area_id=new_id(), code="LENMEN", name="Khu lên men"),
        EnergyArea(area_id=new_id(), code="CHIET", name="Khu chiết"),
    ]
    db.add_all(groups + areas)
    db.commit()
    base = {"DIEN": 4200, "NUOC": 380, "HOI": 18}
    today = utcnow().date()
    rows = []
    for d in range(30):
        day = today - timedelta(days=29 - d)
        wobble = ((d * 37) % 11 - 5) / 100.0  # ±5% tất định theo ngày
        weekend = 0.6 if day.weekday() >= 5 else 1.0
        for g in groups:
            val = base[g.code] * weekend * (1 + wobble)
            rows.append(EnergyReading(reading_id=new_id(), day=day, group_id=g.group_id,
                                      area_id=areas[0].area_id, value=round(val, 1)))
    db.add_all(rows)
    db.commit()


def _seed_maintenance(db) -> None:
    eqs = [
        Equipment(equipment_id=new_id(), code="NK-01", name="Nồi nấu malt 1", eq_type="Nồi nấu",
                  system="Nấu", location="Khu nấu", status="running"),
        Equipment(equipment_id=new_id(), code="FV-07", name="Tank lên men 07", eq_type="Fermenter",
                  system="Lên men", location="Khu lên men", status="running"),
        Equipment(equipment_id=new_id(), code="FIL-02", name="Máy lọc nến 2", eq_type="Lọc",
                  system="Lọc", location="Khu lọc", status="maintenance"),
        Equipment(equipment_id=new_id(), code="CHT-01", name="Dây chuyền chiết chai 1", eq_type="Chiết",
                  system="Chiết", location="Khu chiết", status="running"),
    ]
    db.add_all(eqs)
    parts = [
        SparePart(part_id=new_id(), code="PT-GASKET", name="Gioăng inox DN50", uom="cái", stock=12, stock_min=20),
        SparePart(part_id=new_id(), code="PT-PUMP-SEAL", name="Phớt bơm ly tâm", uom="bộ", stock=5, stock_min=3),
        SparePart(part_id=new_id(), code="PT-FILTER", name="Nến lọc", uom="cái", stock=40, stock_min=10),
    ]
    db.add_all(parts)
    db.commit()
    today = utcnow().date()
    db.add(Incident(incident_id=new_id(), incident_code="SC-OPEN-001", equipment_id=eqs[2].equipment_id,
                    title="Rò rỉ áp lực máy lọc", description="Phát hiện rò tại mặt bích", severity="major",
                    status="open", reported_by="operator1", reported_at=utcnow() - timedelta(hours=5)))
    db.add(Incident(incident_id=new_id(), incident_code="SC-DONE-001", equipment_id=eqs[1].equipment_id,
                    title="Cảm biến nhiệt sai số", severity="minor", status="resolved", downtime_min=45,
                    reported_by="operator1", resolution="Hiệu chuẩn lại cảm biến",
                    reported_at=utcnow() - timedelta(days=3), resolved_at=utcnow() - timedelta(days=3)))
    plans = [
        MaintenancePlan(plan_id=new_id(), equipment_id=eqs[0].equipment_id, plan_type="bao_tri",
                        scheduled_date=today + timedelta(days=7), status="planned", note="Bảo trì định kỳ quý"),
        MaintenancePlan(plan_id=new_id(), equipment_id=eqs[1].equipment_id, plan_type="kiem_tra",
                        scheduled_date=today - timedelta(days=2), status="planned", note="Kiểm tra van"),
        MaintenancePlan(plan_id=new_id(), equipment_id=eqs[3].equipment_id, plan_type="tu_bo",
                        scheduled_date=today + timedelta(days=20), status="planned", note="Tu bổ băng tải"),
    ]
    db.add_all(plans)
    calibs = [
        Calibration(calib_id=new_id(), equipment_id=eqs[0].equipment_id, name="Cảm biến nhiệt nồi nấu",
                    calib_type="hieu_chuan_tbd", last_date=today - timedelta(days=350),
                    due_date=today + timedelta(days=15), interval_months=12, result="pass", status="valid"),
        Calibration(calib_id=new_id(), name="Van an toàn nồi hơi", calib_type="van_an_toan",
                    last_date=today - timedelta(days=380), due_date=today - timedelta(days=15),
                    interval_months=12, result="pass", status="overdue"),
        Calibration(calib_id=new_id(), name="Nguồn phóng xạ đo mức", calib_type="phong_xa",
                    last_date=today - timedelta(days=200), due_date=today + timedelta(days=165),
                    interval_months=12, status="valid"),
    ]
    db.add_all(calibs)
    db.commit()


def _seed_process(db, batch_id: str) -> None:
    db.add_all([
        ChemicalUsage(usage_id=new_id(), batch_id=batch_id, stage="nau", chemical="CaCl₂",
                      quantity=2.5, uom="kg", note="Điều chỉnh nước nấu"),
        ChemicalUsage(usage_id=new_id(), batch_id=batch_id, stage="len_men", chemical="O₂",
                      quantity=8, uom="ppm", note="Sục khí trước cấy men"),
        ChemicalUsage(usage_id=new_id(), batch_id=batch_id, stage="loc", chemical="Diatomite (bột trợ lọc)",
                      quantity=35, uom="kg"),
        ChemicalUsage(usage_id=new_id(), batch_id=batch_id, stage="cip", chemical="NaOH 2%",
                      quantity=120, uom="L", note="CIP tank lên men"),
    ])
    y1 = YeastLot(yeast_lot_id=new_id(), code="MEN-G2-001", strain="W-34/70", generation=2,
                  source_tank="FV-07", source_batch_id=batch_id, quantity=80, uom="L",
                  viability=96.5, vitality=92.0, status="available")
    y2 = YeastLot(yeast_lot_id=new_id(), code="MEN-G3-002", strain="W-34/70", generation=3,
                  source_tank="FV-05", quantity=60, uom="L", viability=89.0, vitality=85.0,
                  status="available")
    db.add_all([y1, y2])
    db.commit()
    db.add(YeastIssue(issue_id=new_id(), yeast_lot_id=y1.yeast_lot_id, batch_id=batch_id,
                      quantity=20, uom="L", actor="operator1", ts=utcnow() - timedelta(days=1)))
    y1.quantity -= 20
    db.commit()


def _seed_brewing(db) -> None:
    """Luồng sản xuất bia: nguyên liệu → nấu → lên men → lọc → chiết."""
    now = utcnow()
    H = lambda days, hours=0: now - timedelta(days=days, hours=hours)

    # --- Nguyên liệu (Thông tin nguyên liệu) ---
    mats = [
        ("Malt Đức", "51672", None, 25000, "kg", "Nguyễn Thị Tuyết", "nhập mới", False),
        ("Malt Đức", "51671", "NC-MDB", 25024, "kg", "Nguyễn Thị Tuyết", "nhập Silo", False),
        ("Gạo tẻ (504)", "51670", "NC-G", 21000, "kg", "Hưng Cúc", "nhập Silo", True),
        ("Food Flavor NSF-02", "51668", "NC-DV", 50, "kg", "Cty TNHH BRENNTAG Việt Nam", "nhập mới", True),
        ("Dinh dưỡng nấm men", "51667", "VP-SPRINGER", 25, "kg", "Cty TNHH BRENNTAG Việt Nam", "nhập mới", True),
        ("Enzyme Termamyl SCDS (Đan Mạch)", "51665", "NP-Ez-Termamyl", 25, "kg", "Cty TNHH BRENNTAG Việt Nam", "nhập mới", True),
        ("Malt Úc rời", "51664", "NC-MUR", 25050, "kg", "Công ty CP Bắc Mỹ", "nhập mới", True),
        ("Gạo tẻ (504)", "51663", "G-LH-TB", 25000, "kg", "Công ty TNHH Liên Hạnh", "nhập mới", True),
        ("Hoa bia Saaz", "51662", None, 800, "kg", "Cty TNHH BRENNTAG Việt Nam", "nhập mới", False),
    ]
    for i, (name, mskt, lot_kcs, qty, uom, sup, note, ind) in enumerate(mats):
        db.add(MaterialReceipt(receipt_id=new_id(), mskt=mskt, receipt_date=H(i),
                               material_name=name, lot_pm=mskt, lot_kcs=lot_kcs, quantity=qty,
                               uom=uom, location=note, supplier=sup, has_indicators=ind))

    worts = ["Dịch bia Sapphire 14oP", "Dịch bia Legend 13oP", "Dịch bia lowCarb 13oP"]
    beers = {"Dịch bia Sapphire 14oP": "Bia lon Sapphire", "Dịch bia Legend 13oP": "Bia lon Legend",
             "Dịch bia lowCarb 13oP": "Bia lon Golden"}

    # --- Nấu (10 mẻ; 2 mẻ thiếu chỉ tiêu để sinh cảnh báo) ---
    for i in range(10):
        wort = worts[i % 3]
        full = i not in (2, 5)  # mẻ 2 và 5 thiếu OE/Plato
        brew_date = H(10 - i, 6)
        db.add(BrewRecord(brew_id=new_id(), brew_code=f"412{40 + i}", brew_date=brew_date,
                          brew_year=brew_date.year,
                          wort_type=wort, volume_hl=round(890 + (i % 3) * 450 + i * 5, 1),
                          original_extract=(14.0 if full else None) if i % 3 == 0 else (13.0 if full else None),
                          plato=(14.2 if full else None)))

    # --- Lên men (8 lô đang lên men, tank B01-B31) ---
    tanks_lm = ["B18", "B03", "B14", "B16", "B15", "B05", "B26", "B01"]
    for i in range(8):
        wort = worts[i % 3]
        vol = round(896 + (i % 3) * 450 + i * 3, 1)
        ferment_brew_date = H(2 + i, 4)
        db.add(FermentRecord(ferment_id=new_id(), lm_code=f"{145 - i}", brew_code=f"412{50 - i}",
                             brew_date=ferment_brew_date, ferment_year=ferment_brew_date.year, kt_date=H(1 + i),
                             batch_numbers=",".join(str(1423 - i * 6 - j) for j in range(3)) + ",...",
                             wort_type=wort, yeast_gen="Men Khác", tank_lm=tanks_lm[i],
                             volume_hl=vol, on_hand_cct=vol, status="len_men",
                             ferment_days=f"{i + 1}.{(i*7) % 24}.35"))

    # --- Lọc (10 bản ghi, đủ trạng thái) ---
    statuses = ["cho_chiet", "chiet_1_phan", "chiet_1_phan", "cho_chiet", "da_chiet_het",
                "da_chiet_het", "da_chiet_het", "cho_chiet", "da_chiet_het", "da_chiet_het"]
    bbt = ["T1", "T2", "T9", "T11", "T6", "T1", "T12", "T3", "T2", "T11"]
    cct = ["B28", "B28", "B28", "B08", "B11,B04", "B06,B11", "B06,B11", "B08", "B08", "B23"]
    for i in range(10):
        wort = worts[i % 3]
        v_dich = round(148 + i * 17, 1)
        v_beer = round(228 + i * 12, 1)
        on_hand = 0 if statuses[i] == "da_chiet_het" else (v_beer if statuses[i] == "cho_chiet" else round(v_beer * 0.5, 1))
        has_ind = i not in (0, 3)
        filter_date = H(i, 3)
        db.add(FilterRecord(filter_id=new_id(), filter_code=f"839{42 - i}", brew_code=f"412{27 - (i % 5)}",
                            lot_loc=f"{700 - i}", filter_date=filter_date, filter_year=filter_date.year, filter_type="thuong",
                            wort_type=wort, from_cct=cct[i], v_dich_hl=v_dich,
                            beer_type=beers[wort], v_beer_hl=v_beer, to_bbt=bbt[i],
                            status=statuses[i], on_hand_bbt=on_hand, has_indicators=has_ind, has_nvl=has_ind))

    # --- Chiết (10 bản ghi theo ca; 1 bản ghi sản lượng = 0 để cảnh báo) ---
    blines = ["Lon Sapphire", "Lon Sapphire", "Tươi Ha Long", "Lon Sapphire", "Lon Legend",
              "Chai Legend", "Lon Golden", "Lon Sapphire", "Lon Sapphire", "Lon Sapphire"]
    bbeers = ["Bia lon Sapphire(sleek can)", "Bia lon Sapphire(sleek can)", "Bia tươi Ha Long 20L",
              "Bia lon Sapphire(sleek can)", "Bia lon Legend(sleek can)", "Bia chai Legend",
              "Bia lon Golden", "Bia lon Sapphire(sleek can)", "Bia lon Sapphire(sleek can)", "Bia lon Sapphire(sleek can)"]
    ca_data = [(0, 0, 0), (0, 0, 0), (973, 0, 0), (0, 0, 2370), (0, 0, 3180), (2490, 0, 0),
               (0, 0, 5537), (0, 4375, 0), (5050, 0, 0), (5166, 0, 0)]
    for i in range(10):
        c1, c2, c3 = ca_data[i]
        stocked = i >= 4
        bottle_date = H(i // 2, (i % 2) * 5)
        db.add(BottleRecord(bottle_id=new_id(), bottle_code=f"935{35 - i}", filter_code=f"839{42 - i}",
                            bottle_date=bottle_date, bottle_year=bottle_date.year, beer_type=bbeers[i], lot_no=f"{697 - (i % 6)}",
                            v_cap_chiet_hl=round(21 + i * 35, 1), from_bbt=bbt[i], line=blines[i],
                            ca1=c1, ca2=c2, ca3=c3, stocked=stocked, approved=stocked,
                            has_indicators=stocked, has_nvl=stocked))

    db.commit()

    # vài chỉ tiêu cho lô lên men đầu
    fr = db.execute(select(FermentRecord).order_by(FermentRecord.brew_date.desc())).scalars().first()
    if fr:
        db.add_all([
            StageIndicator(indicator_id=new_id(), stage="len_men", scope_code=fr.lm_code,
                           name="Độ đường biểu kiến", unit="°P", value=3.2, analyst="qa1"),
            StageIndicator(indicator_id=new_id(), stage="len_men", scope_code=fr.lm_code,
                           name="pH", unit="", value=4.35, analyst="qa1"),
            StageIndicator(indicator_id=new_id(), stage="len_men", scope_code=fr.lm_code,
                           name="Diacetyl", unit="ppm", value=0.08, warning="OK", analyst="qa1"),
        ])
        db.commit()


def _seed_recipe_ext(db, recipe_id, rv_effective, batch_id) -> None:
    """#3: yield thực tế theo công đoạn + 1 phiếu change-control (version 2 + diff)."""
    # Yield thực tế cho mẻ đã chạy (sát expected, riêng lọc thấp hơn → cảnh báo nhẹ).
    steps = [("nau", 1, 52000, 51000), ("len_men", 2, 51000, 48500),
             ("loc", 3, 48500, 47100), ("chiet", 4, 47100, 47000)]
    snap_steps = {s["step_key"]: s for s in (rv_effective.yield_steps or [])}
    for key, no, inp, outp in steps:
        meta = snap_steps.get(key, {})
        db.add(BatchYieldActual(yield_id=new_id(), batch_id=batch_id, step_key=key, step_no=no,
                                input_qty=inp, output_qty=outp, uom="L",
                                expected_pct=meta.get("expected_pct"),
                                recorded_by="operator1", recorded_at=utcnow()))
    db.commit()

    # Change-control: tạo version 2 (draft) đổi định mức malt + lý do, lưu RecipeChange + diff.
    rv2 = recipe_svc.create_version(db, recipe_id, {
        "product_id": rv_effective.product_id,
        "base_qty": rv_effective.base_qty, "base_uom": rv_effective.base_uom,
        "parameters": rv_effective.parameters,
        "materials": [
            {"material_code": "MALT-PILS", "qty": 1250, "uom": "kg", "tol_pct": 3,
             "alternates": [{"material_code": "MALT-VIENNA", "factor": 1.05, "priority": 1}]},
            {"material_code": "HOP-SAAZ", "qty": 16, "uom": "kg", "tol_pct": 5},
            {"material_code": "YEAST-L34", "qty": 50, "uom": "L", "tol_pct": 10},
        ],
        "quality_checks": rv_effective.quality_checks,
        "yield_steps": rv_effective.yield_steps,
        "change_reason": "Tăng định mức malt +50kg/hoa bia +1kg để nâng độ đắng theo phản hồi cảm quan.",
    }, ENG)
    recipe_svc.transition(db, rv2.version_id, "review", ENG)
    diff = recipe_svc.diff_versions(db, rv_effective.version_id, rv2.version_id)
    db.add(RecipeChange(change_id=new_id(), change_code="CHG-2406-0001", recipe_id=recipe_id,
                        version_id=rv2.version_id, from_version_id=rv_effective.version_id,
                        reason=rv2.change_reason, diff=diff, state="approved",
                        requested_by="engineer1", approved_by="qa1", approved_at=utcnow()))
    rv2.state = "approved"
    rv2.approved_by = "qa1"
    rv2.approved_at = utcnow()
    db.commit()


def _seed_lines(db) -> None:
    """#Q2/B: danh mục dây chuyền (đóng gói) + tank lên men (cho scheduler dùng chung)."""
    from .models.lines import ProductionLine
    db.add_all([
        ProductionLine(line_id=new_id(), code="Line-1 (chai)", name="Dây chuyền chai #1",
                       kind="line", area="chiet", ideal_rate_per_min=300, active=True),
        ProductionLine(line_id=new_id(), code="Line-2 (lon)", name="Dây chuyền lon #2",
                       kind="line", area="chiet", ideal_rate_per_min=500, active=True),
        # Dây chuyền chiết lon 30K thật (CAN L3, KHS 30K) — Đông Mai, tách riêng khỏi
        # "Line-2 (lon)" demo cũ vì OeeReasonCatalog/OPI dashboard khai đúng theo file Excel
        # vận hành thật "OPI - CAN L3 (KHS 30K).xlsx" (xem _seed_oee_reason_catalog).
        ProductionLine(line_id=new_id(), code="CAN30K", name="Dây chuyền chiết lon 30K (CAN L3, KHS 30K)",
                       kind="line", area="chiet", ideal_rate_per_min=500, active=True),
        # Dây chuyền chiết keg 30L thật (KEG Hạ Long, KHS 30L) — 400 keg/giờ (xem cột H công
        # thức "Hiệu suất d.chuyền" của sheet KEG30K: mẫu số 3200/8h = 400/h), OeeReasonCatalog
        # khai đúng theo file "OPI - KEG HẠ LONG (KHS 30L)_20260718.xlsx" (xem
        # _seed_oee_reason_catalog_keg30k).
        ProductionLine(line_id=new_id(), code="KEG30K", name="Dây chuyền chiết keg 30L (Hạ Long, KHS 30L)",
                       kind="line", area="chiet", ideal_rate_per_min=400 / 60, active=True),
    ] + [
        ProductionLine(line_id=new_id(), code=f"FV-0{i}", name=f"Tank lên men {i}",
                       kind="tank", area="len_men", ideal_rate_per_min=0, active=True)
        for i in range(1, 5)
    ])
    db.commit()


def _st(no, content, time=None, temp=None, conc=None, check=None, note=None):
    """1 dòng trong bảng bước MẪU — trích đúng cột "Quy định" (thông số chuẩn) từ biểu mẫu
    giấy gốc, KHÔNG lấy cột "Thực hiện/Bắt đầu/Kết thúc" (để trống cho người vận hành điền
    lúc thực hiện thật)."""
    return {"step_no": str(no), "content": content, "time_spec": time, "temp": temp,
            "concentration": conc, "check_result": check, "performed_by": None, "note": note}


def _seed_cip(db) -> None:
    """CIP (vệ sinh thiết bị) — 21 loại biểu mẫu giấy THẬT đang dùng tại nhà máy (mã/tên/bảng
    bước mẫu trích nguyên văn từ 17 file Word QT-KCS-QT-BM gốc — không phải mã tự đặt).
    area khớp vocabulary scope_type CIP (nau|len_men|loc|chiet) để suggest_for_scope() lọc
    đúng theo công đoạn thực tế — không nhất thiết khớp cách phân thư mục giấy gốc (VD: CIP
    dây chuyền chiết keg vốn nằm chung thư mục với hệ lọc trên giấy, nhưng ở đây xếp area=chiet
    vì đó là thiết bị của công đoạn Chiết)."""
    from .models.cip import CipEquipment, CipFormType
    from .models.lines import ProductionLine

    form_types = [
        ("2.1.2/2025/QT-KCS-QT-BM-01", "THEO DÕI VỆ SINH TANK LÊN MEN - ĐÔNG MAI (CIP FULL)", "len_men", [
            _st(1, "Thu hồi CO2"),
            _st(2, "Kết nối với hệ CIP theo sơ đồ — mở van xả men khoảng 20%, kiểm tra áp suất cấp đỉnh tank khi chạy bước 3"),
            _st(3, "Phun/ngưng xút lần 1 (xả bỏ)", time="150s – nghỉ 480s", temp="Môi trường", conc="2,0-2,2%"),
            _st(4, "Phun/ngưng xút lần 2 (xả bỏ)", time="120s – nghỉ 480s", temp="Môi trường", conc="2,0-2,2%"),
            _st(5, "Phun/ngưng xút/nước lần 3 (xả bỏ)", time="90s (xút) – 30s (nước) – nghỉ 480s", temp="Môi trường", conc="2,0-2,2%"),
            _st(6, "Rửa xút bằng nước", time="120s – nghỉ 60s (4-5 lần)", temp="Môi trường", check="Test Phenol (Đ/KĐ)"),
            _st(7, "Làm đầy axit", note="Độ dẫn điện cuối đường ống = 4mS"),
            _st(8, "Phun Axit – thu hồi", time="180s – nghỉ 120s (10 lần)", temp="Môi trường", conc="1,9-2,0%"),
            _st(9, "Nước đẩy axit", note="Đẩy hết axit trong ống CIP cấp và hồi về bồn chứa — độ dẫn = 3mS"),
            _st(10, "Rửa axit", time="120s – nghỉ 60s (3-4 lần)", temp="Môi trường", check="Test Metyl da cam (Đ/KĐ)"),
            _st(11, "Khử trùng", time="1800s", temp="Môi trường"),
        ]),
        ("2.1.5/2025/QT-KCS-QT-BM-01", "THEO DÕI VỆ SINH HỆ LỌC VI SINH (ĐÔNG MAI)", "loc", [
            _st(2, "VS thô, KT độ kín bằng nước vô trùng", time="5÷10 phút", temp="Môi trường", check="Test Phenol (Đ/KĐ)"),
            _st(3, "VS bằng nước nóng", time="5÷10 phút", temp="75÷80°C"),
            _st(4, "VS bằng dd hóa chất", time="30 phút", temp="65÷70°C", conc="1,0÷1,5%"),
            _st(5, "VS bằng nước nóng", time="Sạch", temp="75÷80°C"),
            _st(6, "Thanh trùng bằng nước nóng", time="30 phút", temp="85÷90°C"),
            _st(7, "Rửa bằng nước vô trùng", time="5÷10 phút", temp="Môi trường", note="Xả"),
            _st(8, "Kiểm tra độ nguyên vẹn của màng lọc", time="15 phút", check="∆P ≤ 90mbar (theo tc ncc)"),
            _st(9, "CO2 nén tạo áp", note="0,8 bar"),
        ]),
        ("2.1.5/2025/QT-KCS-QT-BM-02", "THEO DÕI VỆ SINH DÂY CHUYỀN CHIẾT KEG (20 LÍT) (ĐÔNG MAI)", "chiet", [
            _st(2, "VS thô, KT độ kín bằng nước vô trùng", time="5÷10 phút", temp="Môi trường"),
            _st(3, "VS bằng nước nóng", time="5÷10 phút", temp="70÷75°C"),
            _st(4, "VS bằng dd hóa chất", time="30 phút", temp="65÷70°C", conc="1,0÷1,5%"),
            _st(5, "VS bằng nước nóng", time="Sạch", temp="75÷80°C"),
            _st(6, "Thanh trùng bằng nước nóng", time="30 phút", temp="85÷90°C"),
            _st(7, "Khí đuổi nước", note="Sạch"),
        ]),
        ("2.1.5/2025/QT-KCS-QT-BM-03", "THEO DÕI VỆ SINH DÂY CHUYỀN CHIẾT KEG (20 LÍT) (ĐÔNG MAI) — CIP SÂU", "chiet", [
            _st(2, "VS thô, KT độ kín bằng nước vô trùng", time="5÷10 phút", temp="Môi trường"),
            _st(3, "VS bằng nước nóng", time="5÷10 phút", temp="65÷70°C"),
            _st(4, "VS bằng dd hóa chất (xút + SU560)", time="60 phút", temp="77±1°C", conc="2,5÷3% + SU560 0,2kg/1kg xút", note="Lưu lượng 165÷170 hl/h"),
            _st(5, "VS bằng nước nóng", time="Sạch", temp="65÷70°C"),
            _st(6, "VS bằng dd hóa chất (axit)", time="30 phút", temp="43÷47°C", conc="2,0÷2,5%", note="Lưu lượng 165÷170 hl/h"),
            _st(7, "VS bằng nước thường", time="Sạch", temp="Môi trường"),
            _st(8, "Tiệt trùng bằng hóa chất PAA", time="30 phút", temp="Môi trường", conc="0,4%", note="Lưu lượng 165÷170 hl/h"),
            _st(9, "Nước nóng đuổi", time="10 phút", temp="65÷70°C"),
            _st(10, "Thanh trùng bằng nước nóng", time="30 phút", temp="88÷90°C", note="Lưu lượng 165÷170 hl/h"),
        ]),
        ("2.2.2/2025-QT-KCS-QT-BM-02", "THEO DÕI VỆ SINH TANK THÀNH PHẨM ĐÔNG MAI (VỆ SINH BẰNG XÚT)", "chiet", [
            _st(1, "Xả khí", note="2 lần"),
            _st(3, "VS thô, KT độ kín bằng nước vô trùng", time="1÷2 phút", temp="Môi trường"),
            _st(4, "VS bằng nước nóng", time="5 phút", temp="70÷75°C"),
            _st(5, "VS bằng dd hóa chất", time="90 phút", temp="65÷70°C", conc="2,5÷3%"),
            _st(6, "VS bằng nước nóng", time="Sạch", temp="70÷75°C"),
            _st(7, "VS bằng nước vô trùng", temp="Môi trường", note="Kết quả theo nhiệt độ nước"),
            _st(8, "Khử trùng", time="30 phút", temp="Môi trường", conc="0,3-0,4%"),
        ]),
        ("2.2.2/2025-QT-KCS-QT-BM-01", "THEO DÕI VỆ SINH TANK THÀNH PHẨM ĐÔNG MAI (VỆ SINH BẰNG AXIT)", "chiet", [
            _st(1, "Xả khí", note="2 lần"),
            _st(3, "VS thô, KT độ kín bằng nước vô trùng", time="10÷15 phút", temp="Môi trường"),
            _st(5, "VS bằng dd hóa chất", time="90 phút", temp="Môi trường", conc="1,9÷2,0%"),
            _st(7, "VS bằng nước vô trùng", time="Sạch", temp="Môi trường"),
            _st(8, "Khử trùng", time="30 phút", temp="Môi trường", conc="0,3-0,4%"),
        ]),
        ("2.3.2/2025-QT-KCS-QT-BM-01", "THEO DÕI VỆ SINH TANK CHỨA MEN SỮA ĐÔNG MAI (VỆ SINH BẰNG XÚT)", "len_men", [
            _st(2, "VS thô, KT độ kín bằng nước vô trùng", time="5÷10 phút", temp="Môi trường"),
            _st(4, "VS bằng dd hóa chất xút", time="20-5-20 phút", temp="65÷70°C", conc="2,0÷3,0%"),
            _st(5, "VS bằng nước vô trùng", time="Sạch", temp="Môi trường"),
            _st(6, "Khử trùng", time="30 phút", temp="Môi trường", conc="0,3÷0,4%"),
        ]),
        ("2.3.2/2025-QT-KCS-QT-BM-02", "THEO DÕI VỆ SINH TANK CHỨA MEN SỮA ĐÔNG MAI (VỆ SINH BẰNG AXIT)", "len_men", [
            _st(1, "Xả khí"),
            _st(3, "VS thô, KT độ kín bằng nước vô trùng", time="5÷10 phút", temp="Môi trường"),
            _st(4, "VS bằng dd hóa chất Axít", time="60 phút", temp="Môi trường", conc="1,9÷2,0%"),
            _st(5, "VS bằng nước vô trùng", time="Sạch", temp="Môi trường"),
            _st(6, "Khử trùng", time="30 phút", temp="Môi trường", conc="0,3÷0,4%"),
        ]),
        ("2.3.2/2025-QT-BM-KCS-BM-03", "THEO DÕI VỆ SINH ĐƯỜNG ỐNG CẤP MEN ĐÔNG MAI (VỆ SINH BẰNG XÚT)", "len_men", [
            _st(2, "VS thô, KT độ kín bằng nước vô trùng", time="1÷2 phút", temp="Môi trường"),
            _st(3, "VS bằng nước nóng", time="1÷2 phút", temp="70÷75°C"),
            _st(4, "VS bằng dd hóa chất xút", time="20-5-20 phút", temp="65÷70°C", conc="2,5÷3%"),
            _st(5, "VS bằng nước nóng", time="Sạch", temp="70÷75°C"),
            _st(6, "VS bằng nước vô trùng", temp="Môi trường", note="Kết quả theo nhiệt độ nước"),
            _st(7, "Khử trùng", time="30 phút", temp="Môi trường", conc="0,3÷0,4%"),
        ]),
        ("2.3.2/2025-QT-KCS-QT-BM-04", "THEO DÕI VỆ SINH ĐƯỜNG ỐNG THU MEN ĐÔNG MAI (VỆ SINH BẰNG XÚT)", "len_men", [
            _st(2, "VS thô, KT độ kín bằng nước vô trùng", time="1÷2 phút", temp="Môi trường"),
            _st(3, "VS bằng nước nóng", time="1÷2 phút", temp="70÷75°C"),
            _st(4, "VS bằng dd hóa chất xút", time="20-5-20 phút", temp="65÷70°C", conc="2,5÷3%"),
            _st(5, "VS bằng nước nóng", time="Sạch", temp="70÷75°C"),
            _st(6, "VS bằng nước vô trùng", temp="Môi trường", note="Kết quả theo nhiệt độ nước"),
            _st(7, "Khử trùng", time="30 phút", temp="Môi trường", conc="0,3÷0,4%"),
        ]),
        ("2.4.2/2025-QT-KCS-QT-BM-01(01)", "THEO DÕI VỆ SINH HỆ THỐNG NẤU ĐÔNG MAI: NỒI GẠO, NỒI MALT, NỒI TRUNG GIAN", "nau", [
            _st(2, "VS thô, KT độ kín bằng nước nóng", time="1÷2 phút", temp="70÷75°C"),
            _st(3, "VS bằng dd hóa chất", time="30/60 phút", temp="65÷70°C", conc="2,5÷3%", note="Bổ sung hóa chất tẩy cặn vào khi CIP nồi gạo và nồi malt"),
            _st(4, "VS bằng nước nóng", time="Sạch", temp="70÷75°C"),
        ]),
        ("2.4.2/2025-QT-KCS-QT-BM-01(02)", "THEO DÕI VỆ SINH HỆ THỐNG NẤU ĐÔNG MAI: NỒI LỌC, NỒI SÔI HOA, NỒI LẮNG XOÁY", "nau", [
            _st(2, "VS thô, KT độ kín bằng nước nóng", time="1÷2 phút", temp="70÷75°C"),
            _st(3, "VS bằng dd hóa chất tại nồi", time="30/45 phút", temp="65÷70°C", conc="2,5÷3%"),
            _st("3b", "VS bằng dd hóa chất tại hệ thống", time="60/120 phút", temp="65÷70°C", conc="2,5÷3%", note="Hóa chất tẩy cặn được bổ sung vào khi CIP nồi sôi hoa"),
            _st(4, "VS bằng nước nóng", time="Sạch", temp="70÷75°C"),
        ]),
        ("2.4.2/2025-QT-KCS-QT-BM-02", "THEO DÕI VỆ SINH MÁY HẠ NHIỆT ĐỘ, ĐƯỜNG ỐNG CHUYỂN DỊCH ĐÔNG MAI", "nau", [
            _st(2, "VS bằng nước nóng, KT độ kín", time="1÷2 phút", temp="70÷75°C"),
            _st(3, "VS bằng dd hóa chất", time="20-5-20 phút", temp="65÷70°C", conc="2,5÷3%"),
            _st(4, "VS bằng nước nóng", time="Sạch", temp="70÷75°C",
               note="Trước khi sản xuất hệ thống được VS CIP; cứ sau 6-7 mẻ thiết bị được VS CIP 01 lần"),
        ]),
        ("2.4.2/2025-QT-KCS-QT-BM-03", "THEO DÕI VỆ SINH MÁY NGHIỀN MALT ĐÔNG MAI", "nau", [
            _st(2, "VS bằng nước nóng, KT độ kín", time="1÷2 phút", temp="70÷75°C"),
            _st(3, "VS bằng dd hóa chất", time="30 phút", temp="65÷70°C", conc="2,5÷3%"),
            _st(4, "VS bằng nước nóng", time="Sạch", temp="70÷75°C"),
        ]),
        ("2.4.2/2025-QT-KCS-QT-BM-04", "THEO DÕI VỆ SINH TANK CHỨA NƯỚC NÓNG/NƯỚC THƯỜNG/NƯỚC LẠNH ĐÔNG MAI", "nau", [
            _st(2, "VS thô, KT độ kín bằng nước nóng", time="1÷2 phút", temp="70÷75°C"),
            _st(3, "VS bằng dd hóa chất", time="30 phút", temp="65÷70°C", conc="2,5÷3%"),
            _st(4, "VS bằng nước nóng", time="Sạch", temp="70÷75°C"),
            _st(5, "VS bằng nước vô trùng", temp="Môi trường", note="Kết quả theo nhiệt độ nước — định kỳ thực hiện VS CIP 01 năm/01 lần"),
        ]),
        ("2.6.2/2025-QT-KCS-QT-BM-01", "VỆ SINH MÁY CHIẾT CHAI, ĐƯỜNG ỐNG DẪN BIA ĐI CHIẾT", "chiet", [
            _st(1, "VS thô, KT độ kín bằng nước vô trùng", time="1÷2 phút", temp="Môi trường"),
            _st(2, "VS bằng nước nóng", time="1÷2 phút", temp="70÷75°C"),
            _st(3, "VS bằng dd hóa chất (NaOH)", time="30 phút", temp="65÷70°C", conc="2,5÷3%", note="Bổ sung trợ xút: 1,0kg xút tương ứng 0,2kg SU560/Stabilon WT/reencon cp"),
            _st(4, "VS bằng nước nóng", time="Sạch", temp="70÷75°C"),
            _st(5, "VS bằng nước vô trùng", temp="Môi trường", note="Kết quả theo nhiệt độ nước"),
            _st(6, "VS bằng nước DA (2-5°C)", note="Kết quả theo nhiệt độ nước"),
            _st(7, "Đuổi nước bằng khí/CO2", note="Hết nước"),
        ]),
        ("2.6.6/2025/QT-KCS-QT-BM-01", "THEO DÕI VỆ SINH MÁY CHIẾT LON, ĐƯỜNG ỐNG DẪN BIA ĐI CHIẾT DÂY CHUYỀN KHS", "chiet", [
            _st(2, "VS thô bằng nước vô trùng", time="5÷10 phút", temp="Môi trường"),
            _st(3, "VS bằng nước nóng", time="5÷10 phút", temp="75÷80°C"),
            _st(4, "Đuổi nước bằng khí", note="Hết nước"),
            _st(5, "VS bằng dung dịch hóa chất (NaOH)", time="45 phút", temp="75÷80°C", conc="2,5÷3,0%", note="Lưu lượng 200÷240 hl/h"),
            _st(6, "VS bằng nước nóng", time="Sạch", temp="75÷80°C"),
            _st(7, "Lắp túi lọc bia", check="Kín, không xì hở"),
            _st(8, "VS bằng nước nóng", time="5÷10 phút", temp="75÷80°C"),
            _st(9, "VS bằng nước vô trùng", note="Kết quả theo nhiệt độ nước"),
            _st(10, "VS bằng nước DA (20÷10°C)", conc="2÷10", note="Kết quả theo nhiệt độ nước"),
            _st(11, "Đuổi nước bằng khí", note="Hết nước"),
        ]),
        ("2.5.3.1/2025/QT-KCS-QT-BM-01", "THEO DÕI VỆ SINH HỆ KHỬ KHÍ", "loc", [
            _st(1, "VS thô, KT độ kín bằng nước vô trùng", time="5÷10 phút", temp="Môi trường", note="Xả"),
            _st(2, "VS bằng nước nóng", time="5÷10 phút", temp="75÷80°C", note="Xả"),
            _st(3, "VS bằng dd hóa chất (NaOH)", time="30 phút", temp="80÷85°C", conc="2,5÷3,0%", note="Tuần hoàn"),
            _st(4, "VS bằng nước nóng", time="5÷10 phút", temp="75÷80°C"),
            _st(5, "VS bằng dd hóa chất (H3PO4)", time="15 phút", temp="Môi trường", conc="1,0÷2,0%", note="Tuần hoàn"),
            _st(6, "VS bằng nước nóng", time="Sạch", note="Xả"),
            _st(7, "VS bằng nước vô trùng", time="5÷10 phút", temp="Môi trường", check="Test Phenol/Metyl (Đ/KĐ)",
               note="Xả — lưu lượng vệ sinh chung 200÷240 hl/h"),
        ]),
        ("2.5.3.1/2025/QT-KCS-QT-BM-02", "THEO DÕI VỆ SINH TANK CHỨA NƯỚC DA ĐÔNG MAI", "loc", [
            _st(1, "VS thô, KT độ kín bằng nước vô trùng", time="5÷10 phút", temp="Môi trường", note="Xả"),
            _st(2, "VS bằng nước nóng", time="5÷10 phút", temp="75÷80°C", note="Xả"),
            _st(3, "VS bằng dd hóa chất (NaOH)", time="30 phút", temp="80÷85°C", conc="2,5÷3,0%", note="Tuần hoàn"),
            _st(4, "VS bằng nước nóng", time="5÷10 phút", temp="75÷80°C"),
            _st(5, "VS bằng dd hóa chất (H3PO4)", time="15 phút", temp="Môi trường", conc="1,0÷2,0%", note="Tuần hoàn"),
            _st(6, "VS bằng nước nóng", time="Sạch", note="Xả"),
            _st(7, "VS bằng nước vô trùng", time="5÷10 phút", temp="Môi trường", check="Test Phenol (Đ/KĐ)",
               note="Xả — lưu lượng vệ sinh chung 200÷240 hl/h"),
        ]),
        ("2.1.6/2025/QT-KCS-QT-BM-01", "THEO DÕI VỆ SINH LỌC KG, LỌC TRAP FILLER, TANK ĐỆM BIA SAU LỌC, CARBAMIX", "loc", [
            _st(1, "VS thô, KT độ kín bằng nước vô trùng", time="5÷10 phút", temp="Môi trường", note="Xả"),
            _st(2, "VS bằng nước nóng", time="5÷10 phút", temp="75÷80°C", note="Xả"),
            _st(3, "VS bằng dd hóa chất (NaOH + SU560/Purexol 2VN)", time="30 phút", temp="80÷85°C", conc="NaOH 2,5÷3,0% + SU560/Purexol 0,5÷1,5%", note="Tuần hoàn"),
            _st(4, "VS bằng nước nóng", time="Sạch", temp="75÷80°C"),
            _st(5, "Rửa bằng nước vô trùng", time="5÷10 phút", temp="Môi trường", check="Test Phenol (Đ/KĐ)",
               note="Xả — lưu lượng vệ sinh chung 200÷240 hl/h"),
        ]),
        ("2.1.6/2025/QT-KCS-QT-BM-02", "THEO DÕI VỆ SINH ĐƯỜNG ỐNG LỌC (ĐÔNG MAI)", "loc", [
            _st(1, "VS thô, KT độ kín bằng nước vô trùng", time="5÷10 phút", temp="Môi trường", note="Xả"),
            _st(2, "VS bằng nước nóng", time="5÷10 phút", temp="75÷80°C", note="Xả"),
            _st(3, "VS bằng dd hóa chất (NaOH)", time="30 phút", temp="80÷85°C", conc="2,5÷3,0%", note="Tuần hoàn"),
            _st(4, "VS bằng nước nóng", time="Sạch", temp="75÷80°C"),
            _st(5, "Rửa bằng nước vô trùng", time="5÷10 phút", temp="Môi trường", check="Test Phenol (Đ/KĐ)",
               note="Xả — lưu lượng vệ sinh chung 200÷240 hl/h"),
        ]),
    ]
    # Đơn vị thời gian thực tế trên giấy khác nhau theo biểu mẫu — mặc định "phút", riêng tank
    # lên men (CIP full) ghi bằng giây trên biểu mẫu gốc.
    time_unit_overrides = {"2.1.2/2025/QT-KCS-QT-BM-01": "giây"}
    for entry in form_types:
        code, name, area, steps = entry[:4]
        db.add(CipFormType(form_type_id=new_id(), code=code, name=name, area=area, kind="full",
                           time_unit=time_unit_overrides.get(code, "phút"), temp_unit="°C", conc_unit="%",
                           default_steps=steps, active=True))

    fv_lines = {l.code: l.line_id for l in
                db.execute(select(ProductionLine).where(ProductionLine.code.like("FV-0%"))).scalars().all()}

    equipment = [
        ("EQ-NAU-01", "Nồi gạo/nồi malt/nồi trung gian", "nau", None),
        ("EQ-NAU-02", "Nồi lọc/nồi sôi hoa/thùng lắng xoáy", "nau", None),
        ("EQ-NAU-03", "Máy hạ nhiệt nhanh + đường ống chuyển dịch", "nau", None),
        ("EQ-NAU-04", "Máy nghiền malt", "nau", None),
        ("EQ-NAU-05", "Tank nước nóng/thường/lạnh", "nau", None),
        ("EQ-LM-05", "Tank men sữa (giống men)", "len_men", None),
        ("EQ-LM-06", "Đường ống cấp men", "len_men", None),
        ("EQ-LM-07", "Đường ống thu men", "len_men", None),
        ("EQ-LOC-01", "Hệ lọc vi sinh", "loc", None),
        ("EQ-LOC-02", "Lọc KG/trap filler/tank đệm/carbamix", "loc", None),
        ("EQ-LOC-03", "Đường ống lọc", "loc", None),
        ("EQ-LOC-04", "Hệ khử khí", "loc", None),
        ("EQ-LOC-05", "Tank chứa nước DA", "loc", None),
        ("EQ-CHIET-01", "Máy chiết chai + đường ống", "chiet", None),
        ("EQ-CHIET-02", "Máy chiết lon KHS + đường ống", "chiet", None),
        ("EQ-CHIET-03", "Dây chuyền chiết keg 20L", "chiet", None),
        ("EQ-CHIET-04", "Tank thành phẩm (BBT)", "chiet", None),
    ] + [
        (f"EQ-LM-TANK-{code}", f"Tank lên men {code}", "len_men", line_id)
        for code, line_id in fv_lines.items()
    ]
    for code, name, area, line_id in equipment:
        db.add(CipEquipment(equipment_id=new_id(), code=code, name=name, area=area,
                            production_line_id=line_id, active=True))
    db.commit()


def _seed_packaging(db) -> None:
    """#D: bao bì tuần hoàn — vỏ chai / két-gông / keg inox."""
    from .models.packaging import PackagingType
    rows = [
        ("VOCHAI-450", "Vỏ chai thủy tinh 450ml", "vo_chai", "glass", 0.45, 1200, 80000, 220000),
        ("VOCHAI-330", "Vỏ chai thủy tinh 330ml", "vo_chai", "glass", 0.33, 1000, 45000, 130000),
        ("KET-24", "Két nhựa 24 chai", "ket_gong", "plastic", None, 30000, 6500, 9800),
        ("GONG-20", "Gông sắt 20 chai", "ket_gong", "steel", None, 25000, 1200, 800),
        ("KEG-30", "Keg inox 30L", "keg", "steel", 30, 1500000, 320, 540),
        ("KEG-50", "Keg inox 50L", "keg", "steel", 50, 2200000, 180, 260),
    ]
    for code, name, cat, mat, vol, dep, on_hand, circ in rows:
        db.add(PackagingType(pkg_id=new_id(), code=code, name=name, category=cat, material=mat,
                             volume_l=vol, deposit=dep, on_hand=on_hand, in_circulation=circ, active=True))
    db.commit()


def _seed_wms(db) -> None:
    """#P3-4: vị trí kho TP + vài vỉ tồn kho (đơn vị độc lập, không pallet) cho lô đóng
    gói PKG-2406-0001."""
    from .models.wms import FinishedGoodsUnit, WmsLocation
    from .models.master import FinishedProduct
    locs = [
        WmsLocation(loc_id=new_id(), code="TP-A1", name="Kho TP - Kệ A1", zone="A", kind="bin", capacity=50),
        WmsLocation(loc_id=new_id(), code="TP-A2", name="Kho TP - Kệ A2", zone="A", kind="bin", capacity=50),
        WmsLocation(loc_id=new_id(), code="TP-COLD", name="Kho lạnh TP", zone="COLD", kind="cold", capacity=80),
        WmsLocation(loc_id=new_id(), code="DOCK-1", name="Bãi xuất hàng", zone="DOCK", kind="dock", capacity=20),
    ]
    db.add_all(locs)
    # Đăng ký danh mục SKU cho BIA-LAGER (pack_size=24 lon/vỉ) — cần thiết để
    # services/wms.py::_pack_divisor tra đúng pack_size khi quy đổi quantity ra số vỉ; không
    # có SKU sẽ mặc định 1 (không đoán 24), khiến số vỉ hiển thị/kiểm sức chứa sai 24 lần.
    fp = FinishedProduct(finished_product_id=new_id(), code="BIA-LAGER", name="Bia Lager 4.8% (vỉ)",
                         uom="lon", unit_type="vi", pack_size=24)
    db.add(fp)
    db.commit()
    # 8 vỉ (24 lon/vỉ) — 5 đã cất kệ A1/A2, 3 chưa cất (chờ vị trí) tại dock.
    plan = ["TP-A1", "TP-A1", "TP-A2", "TP-A2", "TP-A2", None, None, None]
    stamp = "260624"
    for i, loc_code in enumerate(plan, start=1):
        loc = next((l for l in locs if l.code == loc_code), None)
        db.add(FinishedGoodsUnit(unit_id=new_id(), unit_code=f"VI-{stamp}-{i:04d}", unit_type="vi",
                                 finished_product_id=fp.finished_product_id,
                                 product_name="BIA-LAGER", lot_code="PKG-2406-0001", quantity=24,
                                 status="stored", location_id=loc.loc_id if loc else None, created_by="thukho"))
    db.commit()


def _seed_schedule(db) -> None:
    """#P3-2: 1 cửa sổ bảo trì FV-02 + chạy bộ lập lịch tự động cho các WO released."""
    from .models.scheduling import ScheduleSlot
    from .services import scheduler
    start = (utcnow() + timedelta(days=2)).replace(microsecond=0)
    db.add(ScheduleSlot(slot_id=new_id(), resource="FV-02", kind="maintenance",
                        status="planned", start_at=start, end_at=start + timedelta(hours=12),
                        note="Bảo trì van đáy FV-02"))
    db.commit()
    scheduler.auto_schedule(db, SUP, days=12)


def _seed_isa88(db) -> None:
    """#P3-1: chạy vài phase ISA-88 trên mẻ B-2406-0002 (đang chạy)."""
    from .models.isa88 import BatchPhaseRun
    b = db.execute(select(BatchExecution).where(BatchExecution.batch_code == "9002")).scalar_one_or_none()
    if not b:
        return
    plan = [("Nấu", "Đường hóa", "Vào liệu", "complete"),
            ("Nấu", "Đường hóa", "Giữ 65°C", "complete"),
            ("Nấu", "Đường hóa", "Nâng 76°C", "running")]
    for i, (up, op, ph, state) in enumerate(plan, start=1):
        start = utcnow() - timedelta(hours=4 - i)
        db.add(BatchPhaseRun(run_id=new_id(), batch_id=b.batch_id, seq=i, unit_class="brewhouse",
                             up_name=up, op_name=op, phase_name=ph, state=state,
                             params={"params": [{"name": "Nhiệt độ", "setpoint": 65, "unit": "°C"}]},
                             values={"Nhiệt độ": 64.6} if state == "complete" else {},
                             operator="vanhanh", started_at=start,
                             ended_at=(start + timedelta(minutes=28)) if state == "complete" else None))
    db.commit()


def _seed_quality_adv(db, batch_id) -> None:
    """#7: định nghĩa chỉ tiêu SPC + chuỗi kết quả (control chart) + CAPA + LIMS sample."""
    db.add_all([
        QCParameter(param_id=new_id(), code="OG", name="Độ đường (°P)", unit="°P",
                    target=11.8, lsl=11.0, usl=12.5, stage="len_men"),
        QCParameter(param_id=new_id(), code="PH", name="pH", unit="",
                    target=4.4, lsl=4.2, usl=4.6, stage="len_men"),
        QCParameter(param_id=new_id(), code="CO2", name="CO2 (g/L)", unit="g/L",
                    target=5.2, lsl=4.8, usl=5.6, stage="chiet"),
        QCParameter(param_id=new_id(), code="IBU", name="Độ đắng (IBU)", unit="IBU",
                    target=22, lsl=18, usl=26, stage="nau"),
    ])
    # 24 kết quả "Độ đường (°P)" — biến thiên nhỏ + 8 điểm cuối lệch lên (Western Electric R4).
    og_vals = [11.8, 11.7, 11.9, 11.6, 11.8, 11.75, 11.85, 11.7, 11.9, 11.65,
               11.8, 11.7, 11.55, 11.85, 11.9, 11.95, 11.98, 12.0, 12.02, 12.05,
               12.08, 12.0, 12.05, 12.1]
    base_t = utcnow() - timedelta(hours=len(og_vals))
    for i, v in enumerate(og_vals):
        db.add(QualityResult(result_id=new_id(), sample_id=f"SPC-OG-{i+1:02d}",
                             scope_type="batch", scope_id=batch_id, parameter="Độ đường (°P)",
                             method="Refractometer", value=v, unit="°P",
                             lower_limit=11.0, upper_limit=12.5,
                             status=("pass" if 11.0 <= v <= 12.5 else "fail"),
                             recorded_by="qa1", recorded_at=base_t + timedelta(hours=i)))
    # CAPA: 1 đang xử lý (action) + 1 mới mở.
    db.add(CAPA(capa_id=new_id(), capa_code="CAPA-2406-0001", title="Độ đường có xu hướng tăng (drift)",
                capa_type="corrective", severity="major", state="action",
                root_cause="Hiệu chuẩn refractometer lệch + nhiệt độ đường hóa cao",
                action_plan="Hiệu chuẩn lại thiết bị; siết kiểm soát nhiệt độ mash; theo dõi 5 mẻ.",
                owner="kcs", opened_by="qa1", opened_at=utcnow() - timedelta(days=2)))
    db.add(CAPA(capa_id=new_id(), capa_code="CAPA-2406-0002", title="Phòng ngừa kẹt chai Line-1",
                capa_type="preventive", severity="minor", state="open",
                owner="baotri", opened_by="quandoc", opened_at=utcnow()))
    # LIMS-lite: 2 phiếu mẫu cho mẻ.
    db.add(Sample(sample_id=new_id(), sample_code="SMP-2406-0001", scope_type="batch",
                  scope_id=batch_id, stage="len_men", status="completed",
                  test_set="Độ đường (°P),pH", registered_by="qa1",
                  registered_at=utcnow() - timedelta(hours=6), completed_at=utcnow() - timedelta(hours=3)))
    db.add(Sample(sample_id=new_id(), sample_code="SMP-2406-0002", scope_type="batch",
                  scope_id=batch_id, stage="chiet", status="in_test",
                  test_set="CO2 (g/L)", registered_by="kcs", registered_at=utcnow()))
    db.commit()


def _seed_downtime(db) -> None:
    """#8: sự kiện dừng máy demo cho Pareto/big-losses (2 line đóng gói cũ, KHÔNG phải
    CAN30K — xem _seed_oee_reason_catalog cho danh mục lý do CAN30K thật). Nhãn/loss tra tay
    (REASON_TREE hardcode cũ đã bị thay bằng OeeReasonCatalog theo dây chuyền)."""
    _LABELS = {
        ("thiet_bi", "kep_chai"): ("Kẹt chai/lon", "availability"),
        ("thiet_bi", "hong_co_khi"): ("Hỏng cơ khí", "availability"),
        ("thiet_bi", "hong_dien"): ("Sự cố điện", "availability"),
        ("chuyen_doi", "cip"): ("Vệ sinh CIP", "performance"),
        ("chuyen_doi", "doi_san_pham"): ("Đổi sản phẩm", "performance"),
        ("thieu_vat_tu", "het_nhan"): ("Hết nhãn", "availability"),
        ("thieu_vat_tu", "het_co2"): ("Hết CO2", "availability"),
        ("van_hanh", "cho_lenh"): ("Chờ lệnh sản xuất", "availability"),
        ("van_hanh", "thieu_nhan_luc"): ("Thiếu nhân lực", "availability"),
        ("chat_luong", "loi_nhan"): ("Lỗi dán nhãn", "quality"),
        ("chat_luong", "do_day_sai"): ("Độ đầy sai", "quality"),
        ("toc_do", "dung_nho"): ("Dừng vặt (micro-stop)", "performance"),
        ("toc_do", "chay_cham"): ("Chạy dưới tốc độ", "performance"),
    }
    eqs = db.execute(select(Equipment)).scalars().all()
    eq_by = {e.code: e for e in eqs}
    # (line, group, code, minutes, shift)
    events = [
        ("Line-1 (chai)", "thiet_bi", "kep_chai", 38, "A"),
        ("Line-1 (chai)", "thiet_bi", "hong_co_khi", 25, "A"),
        ("Line-1 (chai)", "chuyen_doi", "cip", 45, "A"),
        ("Line-1 (chai)", "thieu_vat_tu", "het_nhan", 18, "B"),
        ("Line-1 (chai)", "van_hanh", "cho_lenh", 12, "B"),
        ("Line-1 (chai)", "chat_luong", "loi_nhan", 9, "B"),
        ("Line-1 (chai)", "toc_do", "dung_nho", 14, "A"),
        ("Line-2 (lon)", "thiet_bi", "kep_chai", 30, "A"),
        ("Line-2 (lon)", "chuyen_doi", "doi_san_pham", 40, "A"),
        ("Line-2 (lon)", "thieu_vat_tu", "het_co2", 22, "A"),
        ("Line-2 (lon)", "van_hanh", "thieu_nhan_luc", 16, "B"),
        ("Line-2 (lon)", "chat_luong", "do_day_sai", 11, "B"),
        ("Line-2 (lon)", "toc_do", "chay_cham", 20, "B"),
        ("Line-2 (lon)", "thiet_bi", "hong_dien", 28, "A"),
    ]
    for i, (line, grp, code, mins, shift) in enumerate(events):
        label, loss = _LABELS[(grp, code)]
        eq = eq_by.get("FILL-01") or (eqs[i % len(eqs)] if eqs else None)
        db.add(DowntimeEvent(event_id=new_id(), line=line,
                             equipment_id=(eq.equipment_id if (eq and i % 3 == 0) else None),
                             shift=shift, shift_date=utcnow() - timedelta(days=i % 5),
                             reason_group=grp, reason_code=code,
                             reason_label=label, loss_category=loss,
                             minutes=mins, recorded_by="truongca",
                             recorded_at=utcnow() - timedelta(hours=i)))
    db.commit()


def _seed_oee_reason_catalog(db) -> None:
    """Danh mục lý do dừng máy 2 cấp + target % cho CAN30K — trích đúng sheet Target/List của
    file vận hành thật "OPI - CAN L3 (KHS 30K).xlsx" (8 nhóm tổn thất OPI). target_pct cộng dồn
    theo category phải khớp đúng % tổng nhóm trong sheet Target (kiểm bằng test_oee_waterfall).
    """
    from .models.oee_ext import OeeReasonCatalog

    LINE = "CAN30K"

    def _row(category, sub_code, sub_label, target_pct=0.0, machine_position=None, sort_order=0):
        return OeeReasonCatalog(reason_id=new_id(), line_code=LINE, category=category,
                                sub_code=sub_code, sub_label=sub_label, target_pct=target_pct,
                                machine_position=machine_position, active=True, sort_order=sort_order)

    rows = []
    # Bảo trì ngoài (target nhóm 0.003)
    rows += [
        _row("bao_tri_ngoai", "bao_tri_ngoai", "Bảo trì ngoài", 0.0, sort_order=1),
        _row("bao_tri_ngoai", "bao_tri_khong_cbnv", "Bảo trì không CBNV", 0.003, sort_order=2),
    ]
    # NONA (target nhóm 0.063) — "Không có order" tính tự động ở services/oee_waterfall.py
    # (thời gian không có bản ghi ca nào), không phải lý do thao tác viên tự khai như đào tạo.
    rows += [
        _row("nona", "khong_co_order", "Không có order", 0.0, sort_order=1),
        _row("nona", "dao_tao_hop", "Đào tạo-họp", 0.063, sort_order=2),
    ]
    # Dừng có kế hoạch (target nhóm 0.078) — sub_code khớp đúng tên cột trong CAN30K để nhập
    # liệu, target dồn từ các mục con chi tiết hơn trong sheet Target (CIP hàng tuần+Vệ sinh
    # hàng ngày/tuần -> CIP-vệ sinh; Bảo dưỡng hàng ngày/tuần -> Bảo dưỡng...).
    rows += [
        _row("ke_hoach", "cip_ve_sinh", "CIP-vệ sinh", 0.044, sort_order=1),
        _row("ke_hoach", "bao_duong", "Bảo dưỡng", 0.0303, sort_order=2),
        _row("ke_hoach", "chay_thu", "Chạy thử", 0.0, sort_order=3),
        _row("ke_hoach", "start_up_line", "Start-up line", 0.001, sort_order=4),
        _row("ke_hoach", "run_out_line", "Run out line", 0.0015, sort_order=5),
        _row("ke_hoach", "lay_mau", "Lấy mẫu", 0.001, sort_order=6),
        _row("ke_hoach", "chay_kiem_tra", "Chạy kiểm tra", 0.0001, sort_order=7),
        _row("ke_hoach", "dung_khac", "Dừng khác", 0.0001, sort_order=8),
    ]
    # Chuyển máy (target nhóm 0.0025) — CAN30K tách theo loại lon đổi sang
    rows += [
        _row("chuyen_may", "normal_can", "Normal can", 0.0025, sort_order=1),
        _row("chuyen_may", "sleek_can", "Sleek can", 0.0, sort_order=2),
        _row("chuyen_may", "can_250ml", "Can 250ml", 0.0, sort_order=3),
    ]
    # Dừng nguyên vật liệu (target nhóm 0.001)
    rows += [
        _row("thieu_vat_tu", "mat_dien", "Mất điện", 0.0002, sort_order=1),
        _row("thieu_vat_tu", "mat_nuoc", "Mất nước", 0.0003, sort_order=2),
        _row("thieu_vat_tu", "mat_hoi", "Mất hơi", 0.0, sort_order=3),
        _row("thieu_vat_tu", "mat_khi_nen", "Mất khí nén", 0.0001, sort_order=4),
        _row("thieu_vat_tu", "cho_bia", "Chờ bia", 0.0002, sort_order=5),
        _row("thieu_vat_tu", "cho_co2", "Chờ CO2", 0.0002, sort_order=6),
        _row("thieu_vat_tu", "cho_vat_lieu", "Chờ vật liệu", 0.0, sort_order=7),
    ]
    # Breakdown (target nhóm 0.025) — 10 vị trí máy thật của CAN30K (sheet List cột B); target
    # gộp vào 1 dòng "chung" vì file gốc chỉ theo dõi % Breakdown tổng, không tách theo vị trí.
    positions = ["Dỡ lon", "Băng tải", "Chiết", "Hầm TT", "Thổi khô", "KT mức",
                 "Đóng thùng", "Xếp thùng", "In code", "Cân thùng"]
    rows.append(_row("breakdown", "chung", "Breakdown (chung)", 0.025, sort_order=0))
    for i, pos in enumerate(positions, start=1):
        rows.append(_row("breakdown", f"vt_{i}", pos, 0.0, machine_position=pos, sort_order=i))
    # Dừng lắt nhắt (target nhóm 0.0265, gán vào dòng "Tổng dừng" — residual ở waterfall) +
    # 14 lý do lắt nhắt cụ thể (đếm số lần theo tuần qua OeeMinorStopTally, sheet MS&SL).
    rows.append(_row("dung_lat_nhat", "tong_dung", "Tổng dừng", 0.0265, sort_order=0))
    minor_causes = [
        "Xe nâng không vào kệ vỏ lon kịp thời ở máy dỡ lon",
        "Mắc lon, đổ lon trên băng tải máy dỡ lon",
        "Lon méo vào máy chiết",
        "Phun nước vệ sinh băng tải làm sensor báo đầy băng tải máy chiết",
        "Mắc lon, đổ lon trên băng tải máy thổi khô",
        "Lon sleek đổ mắc vào vị trí đổ lon sau in phun",
        "Nhiều lon vơi, đạp lon không kịp, làm mắc lon trên băng tải",
        "Đổ lon trên băng tải đầu vào máy đóng hộp",
        "Kẹt kệ máy đóng hộp do kệ gãy, rác che sensor",
        "Kênh kệ do rác trên kệ máy đống hộp",
        "Hộp lỗi dán đi lên máy xếp hộp",
        "Dồn hộp, đầy kệ lao vỉ vào cần gạt tiến lùi",
        "Xe nâng không lấy kệ kịp thời",
        "Dừng khác",
    ]
    for i, cause in enumerate(minor_causes, start=1):
        rows.append(_row("dung_lat_nhat", f"ms_{i}", cause, 0.0, sort_order=i))
    # Sản phẩm lỗi (target nhóm 0.001)
    rows.append(_row("sp_loi", "sp_loi", "Sản phẩm lỗi", 0.001, sort_order=1))

    db.add_all(rows)
    db.commit()


def _seed_oee_reason_catalog_keg30k(db) -> None:
    """Danh mục lý do dừng máy 2 cấp + target % cho KEG30K — trích đúng sheet Target/List của
    file vận hành thật "OPI - KEG HẠ LONG (KHS 30L)_20260718.xlsx". Cùng khuôn 8 nhóm tổn thất
    OPI như CAN30K (_seed_oee_reason_catalog) — hầu hết target % nhóm con giống hệt CAN30K
    (cùng công ty áp cùng chuẩn), chỉ khác các mục CHUYỂN MÁY/NGUYÊN VẬT LIỆU/BREAKDOWN vì đặc
    thù dây chuyền chiết keg (không phải lon).

    Lưu ý: sheet nhập liệu thô "KEG30K" của file gốc vẫn còn 2 cột "Normal can"/"Sleek can" ở
    nhóm CHUYỂN — đây là tiêu đề copy sót lại từ mẫu CAN30K, KHÔNG khớp sheet "List" (cột
    K: "Keg 30L"/"Keg 20L", đúng nghĩa với dây chuyền keg) — danh mục dưới đây dùng đúng tên
    theo sheet List, không lặp lại lỗi đặt tên sai của sheet nhập liệu thô.
    Tương tự, nhóm "Dừng nguyên vật liệu": sheet List ghi "Chờ xe" (sai — đó là lý do Breakdown,
    xem cột E "Chờ xe" cuối) còn sheet Target ghi đúng "Chờ CO2" kèm % — dùng theo Target."""
    from .models.oee_ext import OeeReasonCatalog

    LINE = "KEG30K"

    def _row(category, sub_code, sub_label, target_pct=0.0, machine_position=None, sort_order=0):
        return OeeReasonCatalog(reason_id=new_id(), line_code=LINE, category=category,
                                sub_code=sub_code, sub_label=sub_label, target_pct=target_pct,
                                machine_position=machine_position, active=True, sort_order=sort_order)

    rows = []
    # Bảo trì ngoài (target nhóm 0.003) — giống CAN30K
    rows += [
        _row("bao_tri_ngoai", "bao_tri_ngoai", "Bảo trì ngoài", 0.0, sort_order=1),
        _row("bao_tri_ngoai", "bao_tri_khong_cbnv", "Bảo trì không CBNV", 0.003, sort_order=2),
    ]
    # NONA (target nhóm 0.063) — giống CAN30K
    rows += [
        _row("nona", "khong_co_order", "Không có order", 0.0, sort_order=1),
        _row("nona", "dao_tao_hop", "Đào tạo-họp", 0.063, sort_order=2),
    ]
    # Dừng có kế hoạch (target nhóm 0.078) — giống hệt breakdown target của CAN30K
    rows += [
        _row("ke_hoach", "cip_ve_sinh", "CIP-vệ sinh", 0.044, sort_order=1),
        _row("ke_hoach", "bao_duong", "Bảo dưỡng", 0.0303, sort_order=2),
        _row("ke_hoach", "chay_thu", "Chạy thử", 0.0, sort_order=3),
        _row("ke_hoach", "start_up_line", "Start-up line", 0.001, sort_order=4),
        _row("ke_hoach", "run_out_line", "Run out line", 0.0015, sort_order=5),
        _row("ke_hoach", "lay_mau", "Lấy mẫu", 0.001, sort_order=6),
        _row("ke_hoach", "chay_kiem_tra", "Chạy kiểm tra", 0.0001, sort_order=7),
        _row("ke_hoach", "dung_khac", "Dừng khác", 0.0001, sort_order=8),
    ]
    # Chuyển máy (target nhóm 0.0025) — 2 cỡ keg thật (sheet List cột K), KHÔNG dùng "Normal
    # can/Sleek can" của sheet nhập liệu thô (lỗi copy từ mẫu CAN30K).
    rows += [
        _row("chuyen_may", "keg_30l", "Keg 30L", 0.0025, sort_order=1),
        _row("chuyen_may", "keg_20l", "Keg 20L", 0.0, sort_order=2),
    ]
    # Dừng nguyên vật liệu (target nhóm 0.001) — theo đúng % sheet Target; "Mất khí nén" có mặt
    # ở sheet nhập liệu thô (cột AC) nhưng Target không chia % riêng — giữ lại với target=0 để
    # không mất lựa chọn khi khai tay.
    rows += [
        _row("thieu_vat_tu", "mat_dien", "Mất điện", 0.0002, sort_order=1),
        _row("thieu_vat_tu", "mat_nuoc", "Mất nước", 0.0003, sort_order=2),
        _row("thieu_vat_tu", "mat_hoi", "Mất hơi", 0.0001, sort_order=3),
        _row("thieu_vat_tu", "mat_khi_nen", "Mất khí nén", 0.0, sort_order=4),
        _row("thieu_vat_tu", "cho_bia", "Chờ bia", 0.0002, sort_order=5),
        _row("thieu_vat_tu", "cho_co2", "Chờ CO2", 0.0002, sort_order=6),
        _row("thieu_vat_tu", "cho_vat_lieu", "Chờ vật liệu", 0.0, sort_order=7),
    ]
    # Breakdown (target nhóm 0.025) — 14 vị trí máy thật của KEG30K (sheet nhập liệu thô cột
    # AG-AT — đầy đủ hơn sheet List cột E vì List thiếu "Hệ Robot"/"Quấn màng pallet"); target
    # gộp vào 1 dòng "chung" như CAN30K vì file gốc chỉ theo dõi % Breakdown tổng.
    positions = ["Vào vỏ", "Rửa vỏ", "CIP hóa chất", "Chiết keg", "In phun", "Cân", "Lật keg",
                 "Phóng màng co", "Đặt tem", "Khò màng co", "Băng tải", "Hệ Robot",
                 "Quấn màng pallet", "Chờ xe"]
    rows.append(_row("breakdown", "chung", "Breakdown (chung)", 0.025, sort_order=0))
    for i, pos in enumerate(positions, start=1):
        rows.append(_row("breakdown", f"vt_{i}", pos, 0.0, machine_position=pos, sort_order=i))
    # Dừng lắt nhắt (target nhóm 0.0265, gán vào dòng "Tổng dừng" — residual ở waterfall). File
    # KEG không có sheet MS&SL riêng (khác CAN30K) nên KHÔNG bịa lý do lắt nhắt cụ thể — chỉ giữ
    # đúng % tổng, khai tay lý do cụ thể khi có dữ liệu thật.
    rows.append(_row("dung_lat_nhat", "tong_dung", "Tổng dừng", 0.0265, sort_order=0))
    # Sản phẩm lỗi (target nhóm 0.001)
    rows.append(_row("sp_loi", "sp_loi", "Sản phẩm lỗi", 0.001, sort_order=1))

    db.add_all(rows)
    db.commit()


def _seed_dispense(db, batch_id, materials) -> None:
    """#6: 1 phiếu cấp liệu (informational) khớp lượng đã tiêu thụ của mẻ demo."""
    disp = Dispense(dispense_id=new_id(), dispense_code="DISP-2406-0001", batch_id=batch_id,
                    mode="dispense", status="issued", note="Cấp liệu mẻ 9001 (FEFO)",
                    created_by="vanhanh", created_at=utcnow())
    db.add(disp)
    db.flush()
    lines = [("MALT-PILS", "MALT-2406-01", 1200, "kg"),
             ("HOP-SAAZ", "HOP-2406-01", 15, "kg"),
             ("YEAST-L34", "YEAST-2406-01", 50, "L")]
    for code, lot_code, qty, uom in lines:
        db.add(DispenseLine(line_id=new_id(), dispense_id=disp.dispense_id, material_code=code,
                            lot_code=lot_code, quantity=qty, uom=uom))
    db.commit()


def _seed_users(db) -> None:
    """Tài khoản theo chức danh nhà máy. Mật khẩu demo: 123456 (admin: admin123).

    role = vai trò nghiệp vụ (quyết định quyền/SoD); views = menu được phép.
    """
    accounts = [
        # username, password, full_name, job_title, role, views, permissions,
        #   scope_lines, scope_areas, scope_qc, scope_warehouse  (admin do ensure_admin tạo riêng)
        #
        # Danh sách tài khoản đã được rút gọn để khớp đúng sơ đồ tổ chức thật
        # (01/2026/SĐTC-BHL) — bỏ các chức danh không có trong sơ đồ (giamdoc "chỉ xem" chung,
        # truongca, thukho_px, baotri, nangluong: không phải chức danh riêng trong sơ đồ, hoặc
        # trùng vai trò với tài khoản khác). Giữ lại "kysu" dù không nằm trong bảng đề xuất ban
        # đầu — nó ứng với "Phòng Kỹ thuật, Công nghệ và Cải tiến Sản xuất" có thật trong sơ đồ
        # (dưới Giám đốc SX-KT), và là tài khoản demo duy nhất giữ recipe.author — xóa hẳn sẽ
        # không còn ai soạn được công thức trong dữ liệu mẫu.
        # warehouse.count_approve: Quản đốc phân xưởng sản xuất duyệt phiếu kiểm kê định kỳ
        # (Kho công ty lẫn Kho phân xưởng) — trước đây gate cứng theo role supervisor/qa/
        # engineer/admin, không cấu hình được qua Tài khoản (xem services/warehouse.py
        # ::approve_count).
        ("quandoc", "123456", "Trần Quang Đốc", "Quản đốc phân xưởng", "supervisor",
         "dashboard,master,orders,dispatch,schedule,batches,isa88,dispense,recipeadv,process,realtime,quality,qclab,oee,trace,wms,warehouse_kc,warehouse_px,packaging,reports,ai,audit,cip",
         "master.manage,order.create,wo.manage,wo.dispatch,batch.create,batch.execute,quality.deviation,ebr.sign,ebr.approve,cip.manage,warehouse.count_approve",
         "*", "*", "*", "*"),
        # Phó Quản đốc kiêm trực ca — người ký khóa số liệu hàng ngày ở phân xưởng (thay cho
        # "truongca" cũ, không có trong sơ đồ thật; đúng chức danh sơ đồ là "Phó Quản đốc kiêm
        # trực ca" dưới Quản đốc, xem Phân xưởng Sản xuất Đông Mai).
        ("phoquandoc", "123456", "Lê Thị Trực", "Phó Quản đốc phân xưởng (trực ca)", "supervisor",
         "dashboard,batches,isa88,dispense,process,realtime,quality,oee,trace,wms,packaging,reports,ai,cip",
         "batch.execute,ebr.sign,ebr.approve,quality.deviation,cip.manage",
         "*", "*", "*", "*"),
        # warehouse.receive: cho phép tự tạo/duyệt/hoàn tác phiếu Kiểm kê định kỳ TẠI Kho phân
        # xưởng — _assert_location_scope (services/warehouse.py) vẫn chặn không cho đụng tới Kho
        # công ty vì scope_warehouse="phan_xuong" (không phải "*"), nên không mở rộng quyền nhận
        # hàng ở Kho công ty.
        ("vanhanh", "123456", "Phạm Văn Hành", "Nhân viên vận hành", "operator",
         "dashboard,batches,isa88,dispense,process,realtime,warehouse_px,cip", "batch.execute,ebr.sign,warehouse.request,warehouse.receive,cip.manage",
         "Nấu A", "nau,len_men", "*", "phan_xuong"),
        ("kcs", "123456", "Hoàng Thị Kiểm", "Nhân viên KCS / QA", "qa",
         "dashboard,quality,qclab,process,trace,ai,cip", "quality.release,quality.deviation,recipe.approve,ebr.sign,ebr.approve",
         "*", "*", "Độ đường (°P),pH", "*"),
        ("kysu", "123456", "Khuất Bích Phượng", "Kỹ sư - Phòng Kỹ thuật, Công nghệ và Cải tiến Sản xuất", "engineer",
         "dashboard,master,recipes,recipeadv,batches,isa88,qclab,process,realtime,oee,trace,reports,schedule,cip",
         "master.manage,recipe.author,recipe.approve,batch.create,batch.execute,ebr.sign,cip.manage",
         "*", "*", "*", "*"),
        ("thukho", "123456", "Vũ Thị Kho", "Thủ kho NVL", "operator",
         "dashboard,warehouse_kc,wms,packaging,dispense", "warehouse.receive,warehouse.issue",
         "*", "kho", "*", "cong_ty"),
        # Theo sơ đồ tổ chức thật (01/2026/SĐTC-BHL): Trưởng phòng KCS khóa chỉ tiêu + tạo
        # Lệnh lọc (khác với NV KCS chỉ nhập/duyệt kết quả theo chỉ tiêu được gán).
        ("kcs_truongphong", "123456", "Trịnh Thị Trưởng", "Trưởng phòng KCS", "qa",
         "dashboard,orders,quality,qclab,process,trace,ai,cip",
         "quality.release,quality.deviation,recipe.approve,ebr.sign,ebr.approve,order.create,quality.capa_approve_kcs",
         "*", "*", "*", "*"),
        # Giám đốc/Phó GĐ Sản xuất - Kỹ thuật: duyệt lô chiết cho nhập kho thành phẩm — tách
        # khỏi quyền quality.release của KCS (KCS nhập/khóa chỉ tiêu, GĐ SX quyết định nhập kho).
        ("giamdoc_sx", "123456", "Đoàn Sản Xuất", "Giám đốc Sản xuất - Kỹ thuật", "supervisor",
         "dashboard,process,quality,trace,reports,ai",
         "production.release_to_wms,quality.capa_approve_director",
         "*", "*", "*", "*"),
        # Trung tâm Điều hành: quản lý kho thành phẩm (xuất kho, điều chuyển, nhập bia cận date...).
        ("ttdh_thukhotp", "123456", "Mai Thị Vận", "NV Trung tâm Điều hành - Thủ kho TP", "operator",
         "dashboard,wms,packaging", "warehouse.receive,warehouse.issue",
         "*", "kho", "*", "*"),
        # Trưởng phòng Kế hoạch: duyệt điều chuyển Kho công ty → Nhà máy khác — sau khi duyệt
        # chỉ ADMIN mới hoàn tác được (xem services/warehouse.py::approve_transfer_to_factory).
        ("truongphong_kh", "123456", "Ngô Thị Kế Hoạch", "Trưởng phòng Kế hoạch", "supervisor",
         "dashboard,warehouse_kc,reports", "warehouse.transfer_approve_factory",
         "*", "*", "*", "cong_ty"),
        # Trưởng bộ phận Kho thành phẩm: xác nhận phiếu xuất kho thành phẩm + duyệt nhập kho từ
        # chiết — sau khi xác nhận/duyệt, chỉ ADMIN mới hoàn tác/xóa được (xem
        # services/wms.py::confirm_shipment/undo_shipment, confirm_receipt_by_lot).
        ("truongkho_tp", "123456", "Bùi Thị Trưởng Kho", "Trưởng bộ phận Kho thành phẩm", "supervisor",
         "dashboard,wms,reports", "wms.confirm_shipment,wms.confirm_receipt",
         "*", "*", "*", "*"),
    ]
    for username, pw, full, title, role, views, perms, sl, sa, sq, sw in accounts:
        db.add(AppUser(user_id=new_id(), username=username, password_hash=hash_password(pw),
                       full_name=full, job_title=title, role=role, allowed_views=views,
                       permissions=perms, scope_lines=sl, scope_areas=sa, scope_qc=sq,
                       scope_warehouse=sw, active=True))
    db.commit()
    print("Tài khoản: admin/admin123 · quandoc,phoquandoc,vanhanh,kcs,kysu,thukho,"
          "kcs_truongphong,giamdoc_sx,ttdh_thukhotp,truongphong_kh,truongkho_tp /123456")


def _seed_role_templates(db) -> None:
    """Mẫu chức danh khớp đúng các tài khoản theo sơ đồ tổ chức thật (xem _seed_users) —
    admin có thể chọn nhanh khi tạo tài khoản mới thay vì soạn tay từng trường."""
    templates = [
        # name, role, allowed_views, permissions, scope_lines, scope_areas, scope_qc, scope_warehouse
        ("Quản đốc phân xưởng", "supervisor",
         "dashboard,master,orders,dispatch,schedule,batches,isa88,dispense,recipeadv,process,realtime,quality,qclab,oee,trace,wms,packaging,reports,ai,audit,cip",
         "master.manage,order.create,wo.manage,wo.dispatch,batch.create,batch.execute,quality.deviation,ebr.sign,ebr.approve,cip.manage",
         "*", "*", "*", "*"),
        ("Phó Quản đốc phân xưởng (trực ca)", "supervisor",
         "dashboard,batches,isa88,dispense,process,realtime,quality,oee,trace,wms,packaging,reports,ai,cip",
         "batch.execute,ebr.sign,ebr.approve,quality.deviation,cip.manage",
         "*", "*", "*", "*"),
        ("Nhân viên vận hành", "operator",
         "dashboard,batches,isa88,dispense,process,realtime,warehouse_px,cip", "batch.execute,ebr.sign,warehouse.request,warehouse.receive,cip.manage",
         "Nấu A", "nau,len_men", "*", "phan_xuong"),
        ("Nhân viên KCS / QA", "qa",
         "dashboard,quality,qclab,process,trace,ai,cip", "quality.release,quality.deviation,recipe.approve,ebr.sign,ebr.approve",
         "*", "*", "Độ đường (°P),pH", "*"),
        ("Kỹ sư - Phòng Kỹ thuật, Công nghệ và Cải tiến Sản xuất", "engineer",
         "dashboard,master,recipes,recipeadv,batches,isa88,qclab,process,realtime,oee,trace,reports,schedule,cip",
         "master.manage,recipe.author,recipe.approve,batch.create,batch.execute,ebr.sign,cip.manage",
         "*", "*", "*", "*"),
        ("Thủ kho NVL", "operator",
         "dashboard,warehouse_kc,wms,packaging,dispense", "warehouse.receive,warehouse.issue",
         "*", "kho", "*", "cong_ty"),
        ("Trưởng phòng KCS", "qa",
         "dashboard,orders,quality,qclab,process,trace,ai,cip",
         "quality.release,quality.deviation,recipe.approve,ebr.sign,ebr.approve,order.create,quality.capa_approve_kcs",
         "*", "*", "*", "*"),
        ("Giám đốc Sản xuất - Kỹ thuật", "supervisor",
         "dashboard,process,quality,trace,reports,ai",
         "production.release_to_wms,quality.capa_approve_director",
         "*", "*", "*", "*"),
        ("NV Trung tâm Điều hành - Thủ kho TP", "operator",
         "dashboard,wms,packaging", "warehouse.receive,warehouse.issue",
         "*", "kho", "*", "*"),
        ("Trưởng phòng Kế hoạch", "supervisor",
         "dashboard,warehouse_kc,reports", "warehouse.transfer_approve_factory",
         "*", "*", "*", "cong_ty"),
        ("Trưởng bộ phận Kho thành phẩm", "supervisor",
         "dashboard,wms,reports", "wms.confirm_shipment,wms.confirm_receipt",
         "*", "*", "*", "*"),
    ]
    for name, role, views, perms, sl, sa, sq, sw in templates:
        db.add(RoleTemplate(role_template_id=new_id(), name=name, role=role, allowed_views=views,
                             permissions=perms, scope_lines=sl, scope_areas=sa, scope_qc=sq,
                             scope_warehouse=sw, active=True))
    db.commit()


if __name__ == "__main__":
    seed()
