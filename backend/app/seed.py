"""Seed dữ liệu nhà máy bia + kịch bản end-to-end để demo.

Chạy:  python -m app.seed         (từ thư mục backend, trong venv)
Tạo: products, materials, recipe (effective), order, material lots,
rồi chạy 1 mẻ: create → consume → run → QC pass → produce → release →
close, để có sẵn dữ liệu genealogy cho phần truy xuất/recall.
"""

from datetime import timedelta

from sqlalchemy import select

from .common import LotStatus, Role, new_id, utcnow
from .database import SessionLocal, init_db
from .models.brewing import (
    BottleRecord,
    BrewRecord,
    FermentRecord,
    FilterRecord,
    MaterialReceipt,
    StageIndicator,
)
from .models.auth import User as AppUser
from .models.energy import EnergyArea, EnergyGroup, EnergyReading
from .models.integration import ApiKey
from .security import hash_password
from .models.maintenance import Calibration, Equipment, Incident, MaintenancePlan, SparePart
from .models.master import Material, Product
from .models.materials import MaterialLot
from .models.metrics import OEERecord, ProcessReading
from .models.orders import ProductionOrder
from .models.process import ChemicalUsage, YeastIssue, YeastLot
from .models.recipes import Recipe
from .models.warehouse import StockMovement
from .security import User
from .services import batches as batch_svc
from .services import quality as qual_svc
from .services import recipes as recipe_svc

ENG = User("engineer1", Role.ENGINEER.value)
QA = User("qa1", Role.QA.value)
SUP = User("supervisor1", Role.SUPERVISOR.value)
OP = User("operator1", Role.OPERATOR.value)


def _get_or_create_product(db, code, name, uom="L"):
    p = db.execute(select(Product).where(Product.code == code)).scalar_one_or_none()
    if not p:
        p = Product(product_id=new_id(), code=code, name=name, uom=uom)
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


def seed():
    init_db()
    db = SessionLocal()
    if db.execute(select(ProductionOrder)).first():
        print("Đã có dữ liệu — bỏ qua seed. (Xóa backend/mes.db để seed lại.)")
        db.close()
        return

    # --- Master data ---
    lager = _get_or_create_product(db, "BIA-LAGER", "Bia Lager 4.8%", "L")
    malt = _get_or_create_material(db, "MALT-PILS", "Malt Pilsner", "kg", "malt")
    hop = _get_or_create_material(db, "HOP-SAAZ", "Hoa bia Saaz", "kg", "hop")
    yeast = _get_or_create_material(db, "YEAST-L34", "Men Lager W-34/70", "L", "yeast")

    # --- Material lots (nguyên liệu đầu vào) ---
    lots = [
        MaterialLot(lot_id=new_id(), lot_code="MALT-2406-01", material_id=malt.material_id,
                    lot_type="material", supplier_lot="SUP-M-991", quantity=5000, uom="kg",
                    status=LotStatus.AVAILABLE.value, location="Kho A"),
        MaterialLot(lot_id=new_id(), lot_code="HOP-2406-01", material_id=hop.material_id,
                    lot_type="material", supplier_lot="SUP-H-220", quantity=80, uom="kg",
                    status=LotStatus.AVAILABLE.value, location="Kho lạnh"),
        MaterialLot(lot_id=new_id(), lot_code="YEAST-2406-01", material_id=yeast.material_id,
                    lot_type="material", supplier_lot="SUP-Y-007", quantity=200, uom="L",
                    status=LotStatus.AVAILABLE.value, location="Lab men"),
    ]
    db.add_all(lots)
    db.commit()

    # --- Recipe + version (draft → review → approved → effective) ---
    recipe = db.execute(select(Recipe).where(Recipe.code == "REC-LAGER")).scalar_one_or_none()
    if not recipe:
        recipe = Recipe(recipe_id=new_id(), code="REC-LAGER", name="Công thức Bia Lager",
                        product_id=lager.product_id)
        db.add(recipe)
        db.commit()

    rv = recipe_svc.create_version(db, recipe.recipe_id, {
        "base_qty": 50000, "base_uom": "L",   # BOM định mức cho mẻ chuẩn 50.000 L
        "parameters": [
            {"name": "Nhiệt độ đường hóa", "target": 65, "lower": 63, "upper": 67, "unit": "°C", "phase": "mash"},
            {"name": "Thời gian sôi", "target": 60, "lower": 55, "upper": 70, "unit": "phút", "phase": "boil"},
            {"name": "Nhiệt độ lên men", "target": 12, "lower": 10, "upper": 14, "unit": "°C", "phase": "ferment"},
        ],
        "materials": [
            {"material_code": "MALT-PILS", "qty": 1200, "uom": "kg", "tol_pct": 3},
            {"material_code": "HOP-SAAZ", "qty": 15, "uom": "kg", "tol_pct": 5},
            {"material_code": "YEAST-L34", "qty": 50, "uom": "L", "tol_pct": 10},
        ],
        "quality_checks": [
            {"parameter": "Độ đường (°P)", "method": "Refractometer", "lower": 11.0, "upper": 12.5, "unit": "°P", "mandatory": True},
            {"parameter": "pH", "method": "pH meter", "lower": 4.2, "upper": 4.6, "unit": "", "mandatory": True},
        ],
    }, ENG)
    recipe_svc.transition(db, rv.version_id, "review", ENG)
    recipe_svc.transition(db, rv.version_id, "approved", QA)   # QA duyệt (SoD: khác người soạn)
    recipe_svc.transition(db, rv.version_id, "effective", ENG)

    # --- Production order ---
    order = ProductionOrder(order_id=new_id(), order_code="PO-2406-1001",
                            product_id=lager.product_id, planned_qty=50000, uom="L",
                            priority=3, status="released", source_version="ERP-v1",
                            created_at=utcnow())
    db.add(order)
    db.commit()

    # --- Kịch bản end-to-end cho một mẻ ---
    batch = batch_svc.create_batch(db, order.order_id, rv.version_id, SUP,
                                   batch_code="B-2406-0001", planned_qty=50000)
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
    db.add(ApiKey(key_id=new_id(), name="Demo ERP", token="mes_demo_readonly_key_0001",
                  scopes="read", created_by="admin"))
    db.add(ApiKey(key_id=new_id(), name="Edge Gateway", token="mes_edge_writer_key_0001",
                  scopes="read,write", created_by="admin"))
    from .services import historian as hist_svc
    hist_svc.backfill(db, hours=6, step_min=5)   # 6h dữ liệu sensor mô phỏng
    _seed_users(db)
    db.commit()

    db.close()
    print("Seed xong. Order PO-2406-1001, mẻ B-2406-0001 đã chạy & close.")
    print("Thử truy xuất: GET /api/trace/backward?code=PKG-2406-0001")
    print("API key demo (read): mes_demo_readonly_key_0001 → thử: GET /api/v1/inventory")


def _seed_workorders(db, order, rv, batch) -> None:
    """Vài lệnh sản xuất cho bảng điều độ; gắn mẻ đã chạy vào 1 WO completed."""
    from .models.workorder import WorkOrder
    from .common import WorkOrderState
    today = utcnow().date()
    wo1 = WorkOrder(wo_id=new_id(), wo_code="WO-2406-001", production_order_id=order.order_id,
                    product_id=order.product_id, recipe_version_id=rv.version_id, planned_qty=50000,
                    uom="L", line="Nấu A", shift="A", scheduled_date=today - timedelta(days=1),
                    priority=3, status=WorkOrderState.COMPLETED.value, created_by="quandoc")
    wo2 = WorkOrder(wo_id=new_id(), wo_code="WO-2406-002", production_order_id=order.order_id,
                    product_id=order.product_id, recipe_version_id=rv.version_id, planned_qty=50000,
                    uom="L", line="Nấu A", shift="B", scheduled_date=today,
                    priority=2, status=WorkOrderState.RELEASED.value, created_by="quandoc")
    wo3 = WorkOrder(wo_id=new_id(), wo_code="WO-2406-003", production_order_id=order.order_id,
                    product_id=order.product_id, recipe_version_id=rv.version_id, planned_qty=25000,
                    uom="L", line="Nấu B", shift="A", scheduled_date=today + timedelta(days=1),
                    priority=5, status=WorkOrderState.PLANNED.value, created_by="quandoc")
    db.add_all([wo1, wo2, wo3])
    db.commit()
    batch.work_order_id = wo1.wo_id   # mẻ đã chạy thuộc WO-001 (completed)
    db.commit()


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
                          location_from=lot.location, mode="de_nghi", reason="Cấp cho mẻ B-2406-0001",
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
        db.add(BrewRecord(brew_id=new_id(), brew_code=f"412{40 + i}", brew_date=H(10 - i, 6),
                          wort_type=wort, volume_hl=round(890 + (i % 3) * 450 + i * 5, 1),
                          original_extract=(14.0 if full else None) if i % 3 == 0 else (13.0 if full else None),
                          plato=(14.2 if full else None)))

    # --- Lên men (8 lô đang lên men, tank B01-B31) ---
    tanks_lm = ["B18", "B03", "B14", "B16", "B15", "B05", "B26", "B01"]
    for i in range(8):
        wort = worts[i % 3]
        vol = round(896 + (i % 3) * 450 + i * 3, 1)
        db.add(FermentRecord(ferment_id=new_id(), lm_code=f"{145 - i}", brew_code=f"412{50 - i}",
                             brew_date=H(2 + i, 4), kt_date=H(1 + i),
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
        db.add(FilterRecord(filter_id=new_id(), filter_code=f"839{42 - i}", brew_code=f"412{27 - (i % 5)}",
                            lot_loc=f"{700 - i}", filter_date=H(i, 3), filter_type="thuong",
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
        db.add(BottleRecord(bottle_id=new_id(), bottle_code=f"935{35 - i}", filter_code=f"839{42 - i}",
                            bottle_date=H(i // 2, (i % 2) * 5), beer_type=bbeers[i], lot_no=f"{697 - (i % 6)}",
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


def _seed_users(db) -> None:
    """Tài khoản theo chức danh nhà máy. Mật khẩu demo: 123456 (admin: admin123).

    role = vai trò nghiệp vụ (quyết định quyền/SoD); views = menu được phép.
    """
    accounts = [
        # username, password, full_name, job_title, role, views, permissions
        ("admin", "admin123", "Quản trị viên", "Quản trị hệ thống", "admin", "*", "*"),
        ("giamdoc", "123456", "Nguyễn Văn Giám", "Giám đốc nhà máy", "supervisor",
         "dashboard,dispatch,realtime,ai,trace,energy,reports,integration,audit", ""),  # chỉ xem
        ("quandoc", "123456", "Trần Quang Đốc", "Quản đốc phân xưởng", "supervisor",
         "dashboard,orders,dispatch,batches,process,realtime,quality,trace,reports,ai,audit",
         "order.create,wo.manage,wo.dispatch,batch.create,batch.execute,quality.deviation,ebr.sign,ebr.approve"),
        ("truongca", "123456", "Lê Thị Ca", "Trưởng ca sản xuất", "supervisor",
         "dashboard,orders,dispatch,batches,process,realtime,reports,ai",
         "order.create,wo.dispatch,batch.create,batch.execute,ebr.sign"),
        ("vanhanh", "123456", "Phạm Văn Hành", "Nhân viên vận hành", "operator",
         "dashboard,batches,process,realtime", "batch.execute,ebr.sign"),
        ("kcs", "123456", "Hoàng Thị Kiểm", "Nhân viên KCS / QA", "qa",
         "dashboard,quality,process,trace,ai", "quality.release,quality.deviation,recipe.approve,ebr.sign,ebr.approve"),
        ("kysu", "123456", "Đỗ Công Kỹ", "Kỹ sư công nghệ", "engineer",
         "dashboard,recipes,batches,process,realtime,trace,reports", "recipe.author,recipe.approve,batch.create,batch.execute,ebr.sign"),
        ("thukho", "123456", "Vũ Thị Kho", "Thủ kho NVL", "operator",
         "dashboard,warehouse", "warehouse.receive,warehouse.issue"),
        ("baotri", "123456", "Bùi Văn Trì", "Nhân viên bảo trì", "operator",
         "dashboard,maint,calib", "maintenance.manage,calibration.manage"),
        ("nangluong", "123456", "Ngô Văn Điện", "NV quản lý năng lượng", "operator",
         "dashboard,energy", "energy.update"),
    ]
    for username, pw, full, title, role, views, perms in accounts:
        db.add(AppUser(user_id=new_id(), username=username, password_hash=hash_password(pw),
                       full_name=full, job_title=title, role=role, allowed_views=views,
                       permissions=perms, active=True))
    db.commit()
    print("Tài khoản: admin/admin123 · giamdoc,quandoc,truongca,vanhanh,kcs,kysu,thukho,baotri,nangluong /123456")


if __name__ == "__main__":
    seed()
