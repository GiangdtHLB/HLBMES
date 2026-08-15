"""Nghiệp vụ kho: nhập/xuất/hoàn/sang ngang + tồn/thẻ kho/hạn dùng/báo cáo."""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import GenealogyRelation, LotStatus, Role, new_id, utcnow
from ..errors import DomainError, NotFoundError, PermissionError_
from ..models.brewing import (BottleMaterialUsage, BottleRecord, BrewBatch, BrewMaterialUsage, BrewOrder,
                              BrewRecord, FilterMasterOrder, FilterMaterialUsage, FilterRecord)
from ..models.master import Material
from ..models.materials import GenealogyEdge, MaterialLocation, MaterialLot
from ..models.quality import Deviation, QualityResult
from ..models.warehouse import (FactoryLocation, MaterialRequest, MaterialRequestLine, SangNgangRequest,
                                StockCount, StockCountLine, StockMovement, TransferPxRequest)
from ..security import User, has_scope, require_perm, require_role, require_scope
from .opening_balance_import import parse_opening_balance_sheet
from .qc_catalog import required_params_for_material


def _require_any_perm(user: User, *perms: str) -> None:
    last_err = None
    for p in perms:
        try:
            require_perm(user, p)
            return
        except PermissionError_ as e:
            last_err = e
    if last_err:
        raise last_err


def _move(db, mtype, lot, quantity, user, ts=None, **kw):
    mv = StockMovement(movement_id=new_id(), movement_type=mtype,
                       material_id=lot.material_id, lot_id=lot.lot_id, lot_code=lot.lot_code,
                       quantity=quantity, uom=lot.uom, actor=user.username, ts=ts or utcnow(), **kw)
    db.add(mv)
    return mv


def _next_lot_code(db: Session, year: int) -> str:
    """Mã lô tự sinh tăng dần theo năm (VD 2026-00001) — năm sau đánh lại từ 1
    (mirror BrewBatch.batch_code per-year numbering)."""
    count = db.execute(select(func.count()).select_from(MaterialLot)
                       .where(MaterialLot.lot_year == year)).scalar_one()
    while True:
        count += 1
        code = f"{year}-{count:05d}"
        exists = db.execute(select(MaterialLot.lot_id).where(
            MaterialLot.lot_year == year, MaterialLot.lot_code == code)).scalar_one_or_none()
        if not exists:
            return code


def any_material_locations_declared(db: Session) -> bool:
    """Danh mục vị trí kho NVL đã có ít nhất 1 vị trí hay chưa — dùng để chỉ bắt buộc chọn vị
    trí lúc nhập SAU KHI admin đã bắt đầu khai báo danh mục (tránh vấn đề con-gà-quả-trứng: nếu
    bắt buộc ngay từ đầu khi danh mục còn trống thì không ai nhập kho được nữa)."""
    return db.execute(select(func.count()).select_from(MaterialLocation)).scalar() > 0


def list_material_locations(db: Session) -> list[dict]:
    locs = db.execute(select(MaterialLocation).order_by(MaterialLocation.code)).scalars().all()
    used = dict(db.execute(
        select(MaterialLot.location_id, func.count())
        .where(MaterialLot.location_id.isnot(None), MaterialLot.quantity != 0)
        .group_by(MaterialLot.location_id)).all())
    return [{"loc_id": l.loc_id, "code": l.code, "name": l.name, "zone": l.zone, "active": l.active,
             "lot_count": used.get(l.loc_id, 0)} for l in locs]


def create_material_location(db: Session, payload: dict, user: User) -> MaterialLocation:
    require_perm(user, "master.manage")
    if db.execute(select(MaterialLocation).where(MaterialLocation.code == payload["code"])).scalar_one_or_none():
        raise DomainError(f"Mã vị trí '{payload['code']}' đã tồn tại.")
    loc = MaterialLocation(loc_id=new_id(), **payload)
    db.add(loc)
    record_audit(db, entity_type="material_location", entity_id=loc.loc_id, action="create", actor=user,
                after={"code": loc.code, "name": loc.name})
    db.commit()
    db.refresh(loc)
    return loc


def update_material_location(db: Session, loc_id: str, payload: dict, user: User) -> MaterialLocation:
    require_perm(user, "master.manage")
    loc = db.get(MaterialLocation, loc_id)
    if not loc:
        raise NotFoundError("Vị trí không tồn tại.")
    for k, v in payload.items():
        if v is not None:
            setattr(loc, k, v)
    record_audit(db, entity_type="material_location", entity_id=loc.loc_id, action="update", actor=user,
                after={"code": loc.code, "name": loc.name})
    db.commit()
    db.refresh(loc)
    return loc


def delete_material_location(db: Session, loc_id: str, user: User) -> None:
    require_perm(user, "master.manage")
    loc = db.get(MaterialLocation, loc_id)
    if not loc:
        raise NotFoundError("Vị trí không tồn tại.")
    used = db.execute(select(func.count()).select_from(MaterialLot).where(
        MaterialLot.location_id == loc_id, MaterialLot.quantity != 0)).scalar() or 0
    if used:
        raise DomainError(f"Vị trí {loc.code} đang chứa {used} lô NVL — không thể xóa.")
    # Lô đã RỖNG (quantity==0) vẫn giữ location_id trỏ tới vị trí này → MSSQL enforce FK
    # fk_material_lot_location_id chặn DELETE (SQLite bỏ qua). Gỡ tham chiếu (an toàn vì lô hết
    # tồn) + flush TRƯỚC khi xóa vị trí — xem DEPLOY-CONTRACT lớp con-ẩn.
    db.execute(update(MaterialLot).where(MaterialLot.location_id == loc_id).values(location_id=None))
    db.flush()
    record_audit(db, entity_type="material_location", entity_id=loc.loc_id, action="delete", actor=user,
                before={"code": loc.code, "name": loc.name})
    db.delete(loc)
    db.commit()


def relocate_lot(db: Session, lot_id: str, location_id: str, user: User) -> dict:
    """Đổi vị trí cất của 1 lô NVL đang ở Kho công ty sang vị trí khác trong danh mục — dùng
    khi thủ kho sắp xếp lại kho trong quá trình làm việc (khác receive(), vốn chỉ gán vị trí
    LÚC nhập lô mới). Không đổi `location` (tầng kho Kho công ty/Kho phân xưởng) — chỉ đổi vị
    trí cụ thể trong cùng tầng, mirror WMS putaway()."""
    require_perm(user, "warehouse.receive")
    lot = _lot(db, lot_id)
    if _is_workshop_location(lot.location):
        raise DomainError(f"Lô {lot.lot_code} đang ở Kho phân xưởng — chưa có danh mục vị trí "
                          "cho kho phân xưởng.")
    _assert_location_scope(user, lot.location)
    loc = db.get(MaterialLocation, location_id)
    if not loc:
        raise NotFoundError("Vị trí không tồn tại.")
    before = lot.location_id
    lot.location_id = loc.loc_id
    record_audit(db, entity_type="lot", entity_id=lot.lot_id, action="relocate", actor=user,
                before={"location_id": before}, after={"location_id": loc.loc_id, "location_code": loc.code})
    db.commit()
    return {"lot_id": lot.lot_id, "lot_code": lot.lot_code, "location_id": loc.loc_id, "location_code": loc.code}


def receive(db: Session, payload: dict, user: User) -> dict:
    """Nhập kho: tạo lô mới hoặc cộng vào lô hiện có (cùng vật tư + cùng mã lô)."""
    require_perm(user, "warehouse.receive")
    if payload.get("is_opening_balance"):
        # Nhập tồn đầu (nạp số dư ban đầu khi triển khai hệ thống, không qua nhận hàng NCC
        # thật) — CHỈ ADMIN, khác nhập kho thường vốn mở cho thủ kho (Role.OPERATOR trở lên).
        require_role(user, Role.ADMIN)
    qty = float(payload["quantity"])
    if qty <= 0:
        raise DomainError("Số lượng nhập phải > 0.")
    now = utcnow()
    received_at = payload.get("received_at")
    if received_at:
        received_dt = datetime.fromisoformat(received_at) if isinstance(received_at, str) else received_at
        if received_dt.tzinfo is None:
            received_dt = received_dt.replace(tzinfo=now.tzinfo)
        if received_dt > now:
            raise DomainError("Ngày nhập không được sau thời điểm hiện tại.")
        # Tồn đầu (nạp số dư ban đầu khi triển khai hệ thống) hợp lệ với ngày rất xa trong quá
        # khứ — giới hạn 15 ngày chỉ áp dụng cho nhập kho thường (tránh gõ nhầm ngày).
        if not payload.get("is_opening_balance") and received_dt < now - timedelta(days=15):
            raise DomainError("Ngày nhập không được quá 15 ngày trước thời điểm hiện tại.")
    else:
        received_dt = now
    year = received_dt.year
    lot_code = payload.get("lot_code") or None
    material_id = payload.get("material_id")
    # (lot_year, lot_code) là duy nhất TOÀN HỆ THỐNG (không phải riêng từng vật tư — mã lô
    # tự sinh là 1 dãy đếm chung), nên phải tra theo đúng mã lô trước, rồi mới kiểm tra
    # có KHỚP vật tư không — trước đây chỉ khớp theo lot_code mà bỏ qua vật tư, nên nhập
    # trùng mã lô của vật tư khác sẽ âm thầm cộng nhầm vào lô của vật tư đó (bug thực tế).
    lot = None
    if lot_code:
        lot = db.execute(select(MaterialLot).where(
            MaterialLot.lot_year == year, MaterialLot.lot_code == lot_code)).scalar_one_or_none()
        if lot and lot.material_id != material_id:
            raise DomainError(f"Mã lô '{lot_code}' đã dùng cho vật tư khác trong năm {year} — "
                              "nhập mã lô khác hoặc để trống để hệ thống tự sinh.")
    if lot:
        _assert_location_scope(user, lot.location)
        lot.quantity += qty
        # Cộng dồn thêm 1 đợt hàng vào lô đã tồn tại (kể cả lô đã Released) — vật tư có chỉ
        # tiêu bắt buộc phải quay lại HOLD chờ KCS khai báo/duyệt lại cho đợt hàng mới này,
        # không được coi là "đã qua QC" chỉ vì đợt hàng trước của cùng mã lô đã được duyệt.
        if lot.material_id and required_params_for_material(db, lot.material_id):
            lot.status = LotStatus.ON_HOLD.value
        elif lot.status == LotStatus.CONSUMED.value:
            lot.status = LotStatus.AVAILABLE.value
    else:
        location = payload.get("location", "Kho công ty")
        _assert_location_scope(user, location)
        # Bắt buộc chọn vị trí cất (khi tạo lô MỚI tại Kho công ty) được kiểm tra ở tầng router
        # (routers/warehouse.py::receive), không phải ở đây — vì receive() còn được gọi trực
        # tiếp từ import_opening_balance_materials (nhập tồn đầu hàng loạt qua Excel, chưa có
        # cột vị trí trong mẫu import) và từ nhiều test fixture chỉ dùng receive() làm bước dựng
        # sẵn tồn kho, không phải để kiểm thử chính bản thân việc nhập kho.
        expiry = payload.get("expiry")
        lot = MaterialLot(lot_id=new_id(), lot_code=lot_code or _next_lot_code(db, year), lot_year=year,
                          material_id=material_id, lot_type=payload.get("lot_type", "material"),
                          supplier_lot=payload.get("supplier_lot"), supplier_id=payload.get("supplier_id"),
                          unit_price=payload.get("unit_price"), kcs_lot_no=payload.get("kcs_lot_no"),
                          quantity=qty, uom=payload.get("uom", "kg"), status=LotStatus.AVAILABLE.value,
                          expiry=datetime.fromisoformat(expiry) if isinstance(expiry, str) else expiry,
                          location=location, location_id=payload.get("location_id"), created_at=received_dt)
        db.add(lot)
        db.flush()
        # Nguyên liệu có gán nhóm chỉ tiêu bắt buộc → lô mới phải HOLD chờ khai báo + KCS duyệt
        # trước khi được coi là đã nhập kho nhà máy chính thức (không áp dụng khi cộng dồn lô cũ).
        if lot.material_id and required_params_for_material(db, lot.material_id):
            lot.status = LotStatus.ON_HOLD.value
    mv = _move(db, "receipt", lot, qty, user, ts=received_dt, location_to=lot.location,
              reason=payload.get("reason"), ref_doc=payload.get("ref_doc"))
    record_audit(db, entity_type="lot", entity_id=lot.lot_id, action="receipt", actor=user,
                 after={"lot_code": lot.lot_code, "quantity": qty})
    db.commit()
    db.refresh(mv)
    return {"lot_id": lot.lot_id, "lot_code": lot.lot_code, "on_hand": lot.quantity, "uom": lot.uom,
            "status": lot.status, "movement_id": mv.movement_id}


def _lot_used(db: Session, lot_id: str) -> bool:
    """Lô đã "dùng" nếu có bất kỳ StockMovement KHÔNG PHẢI receipt nào tham chiếu (issue/
    return/transfer/adjust) — mọi tiêu thụ thực tế (brew/filter material usage, xuất, điều
    chuyển...) đều đi qua issue()/transfer() nên luôn để lại 1 StockMovement non-receipt, dùng
    làm nguồn sự thật duy nhất thay vì dò khắp các bảng usage khác nhau."""
    n = db.execute(select(func.count()).select_from(StockMovement).where(
        StockMovement.lot_id == lot_id, StockMovement.movement_type != "receipt")).scalar_one()
    return n > 0


def update_receipt(db: Session, movement_id: str, payload: dict, user: User) -> dict:
    """Sửa 1 lượt nhập kho (StockMovement type=receipt) — CHỈ khi lô liên quan CHƯA bị dùng
    (chưa xuất/chuyển/tiêu thụ) — lúc đó lot.quantity vẫn đúng bằng tổng các lượt receipt nên
    sửa số lượng vẫn an toàn (không làm sai lệch số đã xuất trước đó)."""
    require_perm(user, "warehouse.receive")
    mv = db.get(StockMovement, movement_id)
    if not mv or mv.movement_type != "receipt":
        raise NotFoundError("Không tìm thấy lượt nhập kho này.")
    lot = db.get(MaterialLot, mv.lot_id)
    if not lot:
        raise NotFoundError("Lô không tồn tại.")
    if _lot_used(db, lot.lot_id):
        raise DomainError(f"Lô {lot.lot_code} đã được sử dụng (xuất/chuyển/tiêu thụ) — không thể sửa nhập kho.")
    new_qty = payload.get("quantity")
    if new_qty is not None:
        new_qty = float(new_qty)
        if new_qty <= 0:
            raise DomainError("Số lượng phải > 0.")
        lot.quantity += new_qty - mv.quantity
        mv.quantity = new_qty
    if "supplier_id" in payload:
        lot.supplier_id = payload["supplier_id"]
    if "unit_price" in payload:
        lot.unit_price = payload["unit_price"]
    if "kcs_lot_no" in payload:
        lot.kcs_lot_no = payload["kcs_lot_no"]
    if "expiry" in payload:
        expiry = payload["expiry"]
        lot.expiry = datetime.fromisoformat(expiry) if isinstance(expiry, str) else expiry
    if "reason" in payload:
        mv.reason = payload["reason"]
    record_audit(db, entity_type="stock_movement", entity_id=mv.movement_id, action="update_receipt",
                 actor=user, after={"quantity": mv.quantity, "lot_code": lot.lot_code})
    db.commit()
    return {"movement_id": mv.movement_id, "lot_id": lot.lot_id, "quantity": mv.quantity, "on_hand": lot.quantity}


def delete_receipt(db: Session, movement_id: str, user: User) -> dict:
    """Xóa 1 lượt nhập kho — CHỈ khi lô CHƯA bị dùng và CHƯA khai báo/duyệt chỉ tiêu chất lượng
    nào (còn QualityResult hoặc Deviation trỏ tới lô là chặn hẳn, không cascade xóa theo —
    dữ liệu QC đã ghi nhận thì lượt nhập tạo ra lô đó không còn được coi là "nhập nhầm" nữa).
    Nếu qua được cả 2 điều kiện, trừ đúng số lượng của lượt này khỏi tồn lô; nếu đây là lượt
    receipt DUY NHẤT của lô (không còn receipt nào khác), xóa luôn MaterialLot (chắc chắn
    không còn QC nào tham chiếu tới, vừa kiểm tra ở trên)."""
    require_perm(user, "warehouse.receive")
    mv = db.get(StockMovement, movement_id)
    if not mv or mv.movement_type != "receipt":
        raise NotFoundError("Không tìm thấy lượt nhập kho này.")
    lot = db.get(MaterialLot, mv.lot_id)
    if not lot:
        raise NotFoundError("Lô không tồn tại.")
    if _lot_used(db, lot.lot_id):
        raise DomainError(f"Lô {lot.lot_code} đã được sử dụng (xuất/chuyển/tiêu thụ) — không thể xóa nhập kho.")
    has_qc = db.execute(select(func.count()).select_from(QualityResult).where(
        QualityResult.scope_type == "lot", QualityResult.scope_id == lot.lot_id)).scalar_one() > 0
    has_dev = db.execute(select(func.count()).select_from(Deviation).where(
        Deviation.scope_type == "lot", Deviation.scope_id == lot.lot_id)).scalar_one() > 0
    if has_qc or has_dev:
        raise DomainError(f"Lô {lot.lot_code} đã được khai báo/duyệt chỉ tiêu chất lượng — không thể xóa nhập kho.")
    lot.quantity -= mv.quantity
    remaining_receipts = db.execute(select(func.count()).select_from(StockMovement).where(
        StockMovement.lot_id == lot.lot_id, StockMovement.movement_type == "receipt",
        StockMovement.movement_id != mv.movement_id)).scalar_one()
    record_audit(db, entity_type="stock_movement", entity_id=mv.movement_id, action="delete_receipt",
                 actor=user, before={"quantity": mv.quantity, "lot_code": lot.lot_code})
    db.delete(mv)
    db.flush()  # MSSQL enforce FK: xóa stock_movement (con) TRƯỚC material_lot (cha) — autoflush=False
    lot_deleted = False
    if remaining_receipts == 0:
        # Lô sắp bị xóa → dọn các đề nghị "Xuất sang ngang" con còn trỏ tới lô. Tới được đây thì
        # chúng CHỈ có thể là pending/rejected (chưa move stock): nếu đã duyệt thì transfer() để
        # lại StockMovement non-receipt và _lot_used đã chặn ở trên. MSSQL enforce FK
        # sang_ngang_request.lot_id → material_lot (SQLite bỏ qua) — phải xóa con + flush trước.
        for req in db.execute(select(SangNgangRequest).where(
                SangNgangRequest.lot_id == lot.lot_id)).scalars().all():
            record_audit(db, entity_type="sang_ngang_request", entity_id=req.request_id,
                         action="delete", actor=user,
                         before={"lot_id": req.lot_id, "status": req.status})
            db.delete(req)
        db.flush()
        db.delete(lot)
        lot_deleted = True
    db.commit()
    return {"deleted": True, "lot_deleted": lot_deleted}


def import_opening_balance_materials(db: Session, content: bytes, location: str, user: User) -> dict:
    """Import Excel hàng loạt tồn đầu kho NVL (Kho công ty/Kho phân xưởng) — CHỈ ADMIN. Mẫu 4
    cột bắt buộc: NGÀY NHẬP, MÃ VẬT TƯ, LÔ, SỐ LƯỢNG + 1 cột tuỳ chọn SỐ LÔ KCS (có thể bỏ
    trống). Mỗi dòng hợp lệ gọi lại receive() với is_opening_balance=True để tái dùng toàn bộ
    nghiệp vụ (sinh mã lô nếu để trống, hold chờ KCS nếu vật tư có chỉ tiêu bắt buộc, ghi
    StockMovement/audit) — receive() tự commit từng dòng nên 1 dòng lỗi không làm mất các dòng
    đã nhập thành công trước đó."""
    require_role(user, Role.ADMIN)
    rows = parse_opening_balance_sheet(content, "MÃ VẬT TƯ", optional_headers={"kcs_lot_no": "SỐ LÔ KCS"})
    created, failed = [], []
    for r in rows:
        if r["error"]:
            failed.append({"row": r["row"], "reason": r["error"]})
            continue
        material = db.execute(select(Material).where(Material.code == r["ma"])).scalar_one_or_none()
        if not material:
            failed.append({"row": r["row"], "reason": f"Không tìm thấy vật tư mã '{r['ma']}'."})
            continue
        try:
            result = receive(db, {
                "material_id": material.material_id, "quantity": r["so_luong"], "uom": material.uom,
                "location": location, "lot_code": r["lo"] or None, "kcs_lot_no": r["kcs_lot_no"],
                "received_at": r["ngay_nhap"].isoformat() if r["ngay_nhap"] else None,
                "reason": "Nhập tồn đầu (import Excel)", "is_opening_balance": True,
            }, user)
        except DomainError as e:
            failed.append({"row": r["row"], "reason": str(e)})
            continue
        created.append({"row": r["row"], "material_code": material.code, **result})
    return {"created": created, "failed": failed, "total": len(rows)}


def return_stock(db: Session, lot_id: str, quantity: float, user: User, reason: str = None,
                  skip_perm_check: bool = False) -> dict:
    """Nhập hoàn kho: trả vật tư chưa dùng về lô. skip_perm_check=True khi gọi nội bộ từ
    undo_issue() với skip_perm_check=True (xem đó)."""
    if not skip_perm_check:
        require_perm(user, "warehouse.issue")
    lot = _lot(db, lot_id)
    _assert_location_scope(user, lot.location)
    if quantity <= 0:
        raise DomainError("Số lượng hoàn phải > 0.")
    lot.quantity += quantity
    if lot.status == LotStatus.CONSUMED.value:
        lot.status = LotStatus.AVAILABLE.value
    mv = _move(db, "return", lot, quantity, user, location_to=lot.location, reason=reason)
    record_audit(db, entity_type="lot", entity_id=lot.lot_id, action="return", actor=user,
                 after={"quantity": quantity})
    db.commit()
    db.refresh(mv)
    return {"lot_id": lot.lot_id, "on_hand": lot.quantity, "movement_id": mv.movement_id}


def issue(db: Session, lot_id: str, quantity: float, user: User, mode: str = "tu_do",
          reason: str = None, ref_doc: str = None, destination_factory_id: str = None,
          skip_perm_check: bool = False) -> dict:
    """Xuất kho tự do (không qua phiếu đề nghị), trả nhà cung cấp (mode="tra_ncc"), hoặc điều
    chuyển sang nhà máy khác (mode="dieu_chuyen_nha_may", destination_factory_id bắt buộc).
    skip_perm_check=True dành cho lệnh gọi NỘI BỘ từ tiêu thụ NVL cho mẻ nấu/mẻ lọc (xem
    routers/brewing.py::add_brew_material/add_filter_material) — router đó đã tự gate bằng
    "batch.execute" (vận hành nhà máy tiêu thụ NVL phân xưởng cho SẢN XUẤT, không phải nghiệp
    vụ Xuất kho), không nên đòi thêm quyền "warehouse.issue" vốn dành cho thủ kho."""
    if not skip_perm_check:
        require_perm(user, "warehouse.issue")
    lot = _lot(db, lot_id)
    _assert_location_scope(user, lot.location)
    if lot.status == LotStatus.ON_HOLD.value:
        raise DomainError(f"Lô {lot.lot_code} đang HOLD, không được xuất.")
    if quantity <= 0 or quantity > lot.quantity:
        raise DomainError(f"Số lượng xuất không hợp lệ (tồn {lot.quantity} {lot.uom}).")
    factory = None
    if mode == "dieu_chuyen_nha_may":
        if not destination_factory_id:
            raise DomainError("Phải chọn nhà máy đích khi điều chuyển sang nhà máy khác.")
        factory = db.get(FactoryLocation, destination_factory_id)
        if not factory or not factory.active:
            raise DomainError("Nhà máy đích không tồn tại hoặc đã ngừng hoạt động.")
    lot.quantity -= quantity
    # So sánh bằng epsilon thay vì `== 0` — trừ dần bằng số thực (float) qua nhiều lần xuất có
    # thể để lại số dư cực nhỏ khác 0 tuyệt đối (VD 1e-13), khiến lô "còn hiện" trong dropdown
    # dù thực tế đã hết; dưới ngưỡng này coi như đã hết và chốt về đúng 0.
    if lot.quantity <= 1e-6:
        lot.quantity = 0.0
        lot.status = LotStatus.CONSUMED.value
    mv = _move(db, "issue", lot, quantity, user, location_from=lot.location, mode=mode,
              reason=reason, ref_doc=ref_doc,
              destination_factory_id=factory.factory_id if factory else None)
    record_audit(db, entity_type="lot", entity_id=lot.lot_id, action="issue", actor=user,
                 after={"quantity": quantity, "mode": mode})
    db.commit()
    db.refresh(mv)
    return {"lot_id": lot.lot_id, "on_hand": lot.quantity, "movement_id": mv.movement_id}


def transfer_to_factory(db: Session, lot_id: str, quantity: float, factory_id: str, user: User,
                        reason: str = None) -> dict:
    """Điều chuyển 1 lô đang ở Kho công ty sang 1 nhà máy khác — xuất NGAY (giảm tồn Kho công
    ty), tự do hoàn tác cho tới khi Trưởng phòng Kế hoạch duyệt (approve_transfer_to_factory),
    sau đó chỉ ADMIN mới hoàn tác được (xem undo_issue)."""
    require_perm(user, "warehouse.issue")
    lot = _lot(db, lot_id)
    if _is_workshop_location(lot.location):
        raise DomainError(f"Lô {lot.lot_code} đang ở Kho phân xưởng — chỉ điều chuyển sang nhà "
                          "máy khác được lô đang ở Kho công ty.")
    return issue(db, lot_id, quantity, user, mode="dieu_chuyen_nha_may", reason=reason,
                destination_factory_id=factory_id)


def approve_transfer_to_factory(db: Session, movement_id: str, user: User) -> dict:
    """Trưởng phòng Kế hoạch duyệt giao dịch điều chuyển sang nhà máy khác — chỉ khoá lại (đánh
    dấu đã duyệt), KHÔNG đổi số liệu tồn kho (đã trừ ngay lúc xuất). Sau khi duyệt, chỉ ADMIN
    mới "Hoàn tác" được (xem undo_issue)."""
    require_perm(user, "warehouse.transfer_approve_factory")
    mv = db.get(StockMovement, movement_id)
    if not mv:
        raise NotFoundError("Giao dịch không tồn tại.")
    if mv.mode != "dieu_chuyen_nha_may":
        raise DomainError("Chỉ duyệt được giao dịch điều chuyển sang nhà máy khác.")
    if mv.approved_by:
        raise DomainError("Giao dịch này đã được duyệt trước đó.")
    mv.approved_by = user.username
    mv.approved_at = utcnow()
    record_audit(db, entity_type="stock_movement", entity_id=mv.movement_id,
                action="approve_transfer_factory", actor=user)
    db.commit()
    db.refresh(mv)
    return {"movement_id": mv.movement_id, "approved_by": mv.approved_by, "approved_at": mv.approved_at}


def transfer(db: Session, lot_id: str, quantity: float, location_to: str, user: User,
             reason: str = None, mode: str = "sang_ngang", request_id: str = None,
             request_line_id: str = None) -> dict:
    """Chuyển vị trí (không đổi tổng tồn) — entrypoint công khai, đòi `warehouse.issue`. `mode`
    phân biệt nguồn gốc giao dịch trong lịch sử: "xuat_theo_de_nghi" (công ty→phân xưởng qua đề
    nghị) | "dieu_chuyen" (phân xưởng→công ty thủ công).

    Nếu `quantity` bằng đúng tồn của lô thì đổi vị trí NGUYÊN lô đó; nếu nhỏ hơn, TÁCH một lô
    mới tại `location_to` mang đúng `quantity` (giữ nguyên lô gốc ở vị trí cũ với phần còn lại,
    nối genealogy "split" để vẫn truy xuất được về lô gốc) — trước đây hàm này luôn di chuyển
    NGUYÊN LÔ bất kể `quantity` truyền vào, khiến sổ sách ghi sai số lượng đã chuyển khi người
    dùng chỉ định chuyển một phần lô."""
    require_perm(user, "warehouse.issue")
    return _transfer_lot(db, lot_id, quantity, location_to, user, reason, mode, request_id, request_line_id)


def _transfer_lot(db: Session, lot_id: str, quantity: float, location_to: str, user: User,
                  reason: str = None, mode: str = "sang_ngang", request_id: str = None,
                  request_line_id: str = None) -> dict:
    """Logic chuyển vị trí thực sự, KHÔNG kiểm tra `warehouse.issue` — dùng cho các nơi đã tự
    xác thực quyền theo cách khác (vd approve_sang_ngang/undo_sang_ngang: thủ kho phân xưởng
    duyệt qua `warehouse.request` + phạm vi kho, không phải người cầm quyền "xuất kho" chung)."""
    lot = _lot(db, lot_id)
    _assert_transfer_scope(user, lot.location, location_to)
    if lot.status == LotStatus.ON_HOLD.value:
        raise DomainError(f"Lô {lot.lot_code} đang HOLD (chờ khai báo/duyệt chỉ tiêu chất lượng), "
                          "không được chuyển kho.")
    if quantity <= 0 or quantity > lot.quantity + 1e-6:
        raise DomainError(f"Số lượng chuyển không hợp lệ (tồn {lot.quantity} {lot.uom}).")
    loc_from = lot.location
    if quantity >= lot.quantity - 1e-6:
        lot.location = location_to
        moved_lot = lot
    else:
        lot.quantity -= quantity
        moved_lot = MaterialLot(lot_id=new_id(), lot_code=_next_lot_code(db, lot.lot_year), lot_year=lot.lot_year,
                                material_id=lot.material_id, product_id=lot.product_id, lot_type=lot.lot_type,
                                supplier_lot=lot.supplier_lot, supplier_id=lot.supplier_id,
                                kcs_lot_no=lot.kcs_lot_no, unit_price=lot.unit_price,
                                quantity=quantity, uom=lot.uom, status=lot.status, expiry=lot.expiry,
                                location=location_to, created_at=lot.created_at)
        db.add(moved_lot)
        db.flush()
        db.add(GenealogyEdge(edge_id=new_id(), from_type="lot", from_id=lot.lot_id, to_type="lot",
                             to_id=moved_lot.lot_id, relation=GenealogyRelation.SPLIT.value,
                             quantity=quantity, uom=lot.uom, source_event="transfer"))
    mv = _move(db, "transfer", moved_lot, quantity, user, location_from=loc_from, location_to=location_to,
              mode=mode, reason=reason, request_id=request_id, request_line_id=request_line_id)
    record_audit(db, entity_type="lot", entity_id=moved_lot.lot_id, action="transfer", actor=user,
                 after={"from": loc_from, "to": location_to, "quantity": quantity,
                       "split_from": lot.lot_id if moved_lot is not lot else None})
    db.commit()
    db.refresh(mv)
    return {"lot_id": moved_lot.lot_id, "location": moved_lot.location, "movement_id": mv.movement_id}


def _is_workshop_location(location: str) -> bool:
    return bool(location) and "phân xưởng" in location.lower()


def _warehouse_token(location: str) -> str:
    return "phan_xuong" if _is_workshop_location(location) else "cong_ty"


def _assert_location_scope(user: User, location: str) -> None:
    """Chặn thao tác 1-địa-điểm (nhập/xuất/hoàn/kiểm kê) ngoài phạm vi kho được phân
    (`User.scope_warehouse`: cong_ty|phan_xuong|"*") — vd Thủ kho công ty không được
    nhập/xuất trực tiếp tại Kho phân xưởng và ngược lại. `location` rỗng/None (kiểm kê
    không lọc theo kho cụ thể) không bị chặn, theo đúng quy ước các chiều scope khác
    (bản ghi chưa gắn phạm vi cụ thể thì không khoá cứng)."""
    if not location:
        return
    require_scope(user, "warehouse", _warehouse_token(location))


def _assert_transfer_scope(user: User, loc_from: str, loc_to: str) -> None:
    """Chuyển kho (transfer) luôn đụng tới 2 địa điểm — cho phép nếu user có phạm vi ở
    ÍT NHẤT 1 trong 2 đầu (nguồn hoặc đích): Thủ kho công ty duyệt đề nghị nhận kho di
    chuyển Kho công ty (đầu họ có quyền) → Kho phân xưởng vẫn hợp lệ; người phân xưởng
    điều chuyển ngược lại Kho phân xưởng (đầu họ có quyền) → Kho công ty cũng hợp lệ.
    Chỉ chặn khi user không có quyền ở CẢ HAI đầu (vd dùng tài khoản kho công ty để
    chuyển thẳng giữa 2 lô đều đang ở Kho phân xưởng)."""
    if has_scope(user, "warehouse", _warehouse_token(loc_from)) or \
       has_scope(user, "warehouse", _warehouse_token(loc_to)):
        return
    raise PermissionError_(
        f"Ngoài phạm vi kho được phân: tài khoản '{user.username}' không có quyền "
        f"chuyển kho giữa '{loc_from}' và '{loc_to}'."
    )


def _location_filter_clause(location_filter: str):
    """`location_filter`: None (không lọc) | 'Kho công ty' | 'Kho phân xưởng' (khớp theo quy ước
    "chứa 'phân xưởng'" — nhất quán với frontend)."""
    if not location_filter:
        return None
    if _is_workshop_location(location_filter):
        return func.lower(MaterialLot.location).contains("phân xưởng")
    return ~func.coalesce(func.lower(MaterialLot.location), "").contains("phân xưởng")


def stock_on_hand(db: Session, location: str = None) -> list[dict]:
    """Xem tồn kho theo vật tư (lọc theo kho nếu truyền `location`).

    `on_hand` (dùng để so `stock_min`/cảnh báo thiếu hụt) chỉ tính lô KHẢ DỤNG (available/
    released) — loại trừ lô đang HOLD (chờ khai báo/duyệt chỉ tiêu chất lượng) hoặc SCRAPPED
    (đã hỏng/trả NCC), vì 2 loại này không thể xuất/chuyển được (issue()/transfer() đều chặn)
    nên không nên tính là tồn "khả dụng" — trước đây gộp chung khiến số tồn hiển thị cao hơn
    thực tế dùng được.

    `pending_qc` = tổng SL đang ở lô HOLD (đã nhập kho vật lý nhưng chưa qua QC) và
    `actual_total` = on_hand + pending_qc — tổng SL thực tế đang nằm trong kho (kể cả lô chưa
    qua QC), phục vụ đối chiếu kiểm kê thực tế, tách biệt với con số "khả dụng để xuất/chuyển"."""
    stmt = (
        select(MaterialLot.material_id, MaterialLot.status, func.sum(MaterialLot.quantity), MaterialLot.uom)
        .where(MaterialLot.material_id.isnot(None),
              MaterialLot.status.in_([LotStatus.AVAILABLE.value, LotStatus.RELEASED.value,
                                       LotStatus.ON_HOLD.value]))
    )
    clause = _location_filter_clause(location)
    if clause is not None:
        stmt = stmt.where(clause)
    rows = db.execute(stmt.group_by(MaterialLot.material_id, MaterialLot.status, MaterialLot.uom)).all()
    if not rows:
        return []
    agg = {}
    for material_id, status, total, uom in rows:
        a = agg.setdefault(material_id, {"uom": uom, "available": 0.0, "pending_qc": 0.0})
        if status == LotStatus.ON_HOLD.value:
            a["pending_qc"] += total or 0
        else:
            a["available"] += total or 0
    mats = {m.material_id: m for m in db.execute(
        select(Material).where(Material.material_id.in_(agg.keys()))).scalars().all()}
    out = []
    for material_id, a in agg.items():
        mat = mats.get(material_id)
        on_hand = round(a["available"], 3)
        pending_qc = round(a["pending_qc"], 3)
        stock_min = mat.stock_min if mat else None
        out.append({"material_id": material_id, "material_code": mat.code if mat else material_id,
                    "material_name": mat.name if mat else "", "on_hand": on_hand,
                    "actual_total": round(on_hand + pending_qc, 3), "pending_qc": pending_qc,
                    "uom": a["uom"], "category": mat.category if mat else None,
                    "stock_min": stock_min, "low_stock": stock_min is not None and on_hand < stock_min})
    return sorted(out, key=lambda x: x["material_code"])


def low_stock_report(db: Session) -> list[dict]:
    """Chỉ các vật tư đang dưới ngưỡng tồn tối thiểu (Material.stock_min) — dùng cho biểu đồ
    "Tồn tối thiểu" ở Kho NVL, sắp theo mức thiếu hụt (deficit = stock_min - on_hand) giảm dần
    để vật tư cần xử lý gấp nhất hiện lên đầu."""
    rows = [r for r in stock_on_hand(db) if r["low_stock"]]
    for r in rows:
        r["deficit"] = round(r["stock_min"] - r["on_hand"], 3)
    return sorted(rows, key=lambda r: r["deficit"], reverse=True)


def material_fifo_detail(db: Session, material_id: str) -> dict:
    """Chi tiết tồn theo lô của 1 vật tư, sắp FIFO (created_at tăng dần), tách theo kho —
    dùng để hiển thị cho người lập Lệnh lọc biết có đủ tồn theo đúng thứ tự lô cũ nhất
    hay không (khác stock_on_hand chỉ trả tổng, không có chi tiết từng lô)."""
    lots = db.execute(select(MaterialLot).where(
        MaterialLot.material_id == material_id, MaterialLot.quantity > 0,
        MaterialLot.status.in_([LotStatus.AVAILABLE.value, LotStatus.RELEASED.value]),
    )).scalars().all()
    lots_sorted = sorted(lots, key=lambda l: l.created_at)
    company = sum(l.quantity for l in lots_sorted if not _is_workshop_location(l.location or ""))
    workshop = sum(l.quantity for l in lots_sorted if _is_workshop_location(l.location or ""))
    return {
        "material_id": material_id,
        "stock_company": round(company, 3), "stock_workshop": round(workshop, 3),
        "stock_total": round(company + workshop, 3),
        "lots": [{"lot_id": l.lot_id, "lot_code": l.lot_code, "location": l.location,
                 "quantity": round(l.quantity, 3), "uom": l.uom, "received_at": l.created_at}
                for l in lots_sorted],
    }


def stock_card(db: Session, material_id: str = None, lot_id: str = None) -> list[dict]:
    """Thẻ kho: ledger có số dư luỹ kế."""
    stmt = select(StockMovement)
    if lot_id:
        stmt = stmt.where(StockMovement.lot_id == lot_id)
    elif material_id:
        stmt = stmt.where(StockMovement.material_id == material_id)
    movements = db.execute(stmt.order_by(StockMovement.ts)).scalars().all()
    bal = 0.0
    out = []
    for m in movements:
        sign = 1 if m.movement_type in ("receipt", "return") else (-1 if m.movement_type == "issue" else 0)
        bal += sign * m.quantity
        out.append({"ts": m.ts, "type": m.movement_type, "lot_code": m.lot_code,
                    "in": m.quantity if sign > 0 else 0, "out": m.quantity if sign < 0 else 0,
                    "balance": round(bal, 3), "uom": m.uom, "mode": m.mode,
                    "reason": m.reason, "actor": m.actor})
    return out


def expiry_report(db: Session, warn_days: int = 30) -> list[dict]:
    """Xem hạn sử dụng nguyên vật liệu còn tồn kho: phân loại ok / sắp hết hạn / hết hạn.
    Chỉ xét lô NVL (material_id) — lô thành phẩm/bán thành phẩm dùng bảng này chung nhưng
    không có ý nghĩa "hạn dùng NVL" ở đây."""
    now = utcnow()
    lots = db.execute(
        select(MaterialLot).where(MaterialLot.expiry.isnot(None), MaterialLot.quantity > 0,
                                  MaterialLot.material_id.isnot(None))
        .order_by(MaterialLot.expiry)
    ).scalars().all()
    mat_by_id = {m.material_id: m for m in db.execute(select(Material)).scalars().all()}
    out = []
    for lot in lots:
        exp = lot.expiry
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=now.tzinfo)
        days = (exp - now).days
        status = "expired" if days < 0 else ("near" if days <= warn_days else "ok")
        mat = mat_by_id.get(lot.material_id)
        out.append({"lot_code": lot.lot_code, "material_code": mat.code if mat else None,
                    "material_name": mat.name if mat else None, "quantity": lot.quantity, "uom": lot.uom,
                    "expiry": lot.expiry, "days_left": days, "status": status, "location": lot.location})
    return out


def inventory_report(db: Session, days: int = 30, location: str = None,
                     date_from: datetime = None, date_to: datetime = None) -> list[dict]:
    """BC nhập-xuất-tồn trong kỳ: tổng nhập, tổng xuất, tồn hiện tại theo vật tư (lọc theo kho
    nếu truyền `location`: nhập tính theo location_to, xuất theo location_from). Khoảng thời
    gian ưu tiên `date_from`/`date_to` nếu truyền, ngược lại dùng `days` gần nhất tính tới hiện tại.

    Vật tư được liệt kê là HỢP của (1) vật tư còn tồn tại kho được lọc và (2) vật tư có giao
    dịch trong kỳ — trước đây chỉ lấy theo (1) nên vật tư nhập rồi chuyển hết đi trong kỳ (VD
    "Xuất sang ngang": nhập vào Kho công ty rồi chuyển thẳng sang Kho phân xưởng luôn) không còn
    tồn tại Kho công ty nên biến mất khỏi báo cáo dù có phát sinh nhập/xuất thật trong kỳ."""
    since = date_from or (utcnow() - timedelta(days=days))
    until = date_to
    on_hand = {r["material_id"]: r for r in stock_on_hand(db, location)}
    stmt = select(StockMovement).where(StockMovement.ts >= since)
    if until:
        stmt = stmt.where(StockMovement.ts <= until)
    moves = db.execute(stmt).scalars().all()
    workshop = _is_workshop_location(location) if location else None
    agg = {}
    for m in moves:
        if m.material_id is None:
            continue
        # Chỉ chạm vào `agg` (kể cả setdefault) SAU KHI đã xác định giao dịch thực sự thuộc kho
        # đang lọc — nếu setdefault chạy trước rồi mới `continue` khi không khớp kho, vật tư vẫn
        # để lại 1 dòng agg toàn số 0, khiến `mat_ids` (hợp với on_hand) lẫn cả vật tư không hề
        # có giao dịch nào ở kho này (bug thực tế: vật tư chỉ nhập ở Kho công ty vẫn xuất hiện
        # trong báo cáo lọc theo Kho phân xưởng với các cột đều = 0).
        if m.movement_type == "transfer":
            # Chuyển kho không đổi tổng tồn toàn nhà máy nên chỉ có ý nghĩa khi báo cáo đã lọc
            # theo 1 kho cụ thể — khi đó "chuyển ra khỏi kho này" tính như xuất, "chuyển vào kho
            # này" tính như nhập (VD "Xuất sang ngang"/"Điều chuyển": tăng tồn kho đích, giảm tồn
            # kho nguồn), y hệt cách receipt/issue thường đã lọc theo location_to/location_from.
            if not location:
                continue
            if _is_workshop_location(m.location_to) == workshop:
                agg.setdefault(m.material_id, {"receipt": 0.0, "issue": 0.0, "return": 0.0})["receipt"] += m.quantity
            elif _is_workshop_location(m.location_from) == workshop:
                agg.setdefault(m.material_id, {"receipt": 0.0, "issue": 0.0, "return": 0.0})["issue"] += m.quantity
            continue
        if location:
            loc = m.location_to if m.movement_type in ("receipt", "return") else m.location_from
            if _is_workshop_location(loc) != workshop:
                continue
        if m.movement_type in ("receipt", "issue", "return"):
            agg.setdefault(m.material_id, {"receipt": 0.0, "issue": 0.0, "return": 0.0})[m.movement_type] += m.quantity
    mat_ids = set(on_hand) | set(agg)
    mats = {mt.material_id: mt for mt in db.execute(
        select(Material).where(Material.material_id.in_(mat_ids))).scalars().all()} if mat_ids else {}
    out = []
    for mid in mat_ids:
        oh = on_hand.get(mid)
        if oh is None:
            mat = mats.get(mid)
            oh = {"material_id": mid, "material_code": mat.code if mat else mid,
                  "material_name": mat.name if mat else "", "on_hand": 0.0, "actual_total": 0.0,
                  "pending_qc": 0.0, "uom": mat.uom if mat else "", "category": mat.category if mat else None,
                  "stock_min": None, "low_stock": False}
        a = agg.get(mid, {"receipt": 0.0, "issue": 0.0, "return": 0.0})
        out.append({**oh, "received": round(a["receipt"] + a["return"], 3),
                    "issued": round(a["issue"], 3)})
    return sorted(out, key=lambda x: x["material_code"])


def _lot(db, lot_id):
    lot = db.get(MaterialLot, lot_id)
    if not lot:
        raise NotFoundError("Lô không tồn tại.")
    return lot


# ---- Đề nghị nhận kho (phân xưởng → kho công ty) ----
# 1 phiếu (MaterialRequest) có thể gồm nhiều dòng vật tư khác nhau (MaterialRequestLine);
# mỗi dòng xử lý duyệt/từ chối độc lập vì mỗi vật tư cần chọn lô riêng.

def _line_dict(line: MaterialRequestLine) -> dict:
    return {"line_id": line.line_id, "request_id": line.request_id, "seq": line.seq,
            "material_id": line.material_id, "quantity": line.quantity, "uom": line.uom,
            "preferred_lot_id": line.preferred_lot_id, "status": line.status,
            "fulfilled_lot_id": line.fulfilled_lot_id, "fulfilled_qty": line.fulfilled_qty,
            "fulfilled_by": line.fulfilled_by, "fulfilled_at": line.fulfilled_at, "reason": line.reason,
            "fifo_ok": line.fifo_ok}


def _source_label(db: Session, source_type: str, source_id: str) -> Optional[str]:
    """Nhãn hiển thị cho nguồn gắn kèm phiếu (Lệnh nấu/Lệnh lọc lớn) — chỉ để hiển thị,
    không raise nếu nguồn đã bị xoá (phiếu cũ vẫn xem được bình thường)."""
    if not source_type or not source_id:
        return None
    if source_type == "brew_order":
        order = db.get(BrewOrder, source_id)
        return f"Lệnh nấu {order.order_code}" if order else None
    if source_type == "filter_master_order":
        master = db.get(FilterMasterOrder, source_id)
        return f"Lệnh lọc {master.order_code}" if master else None
    return None


def _request_dict(db: Session, req: MaterialRequest, lines: list[MaterialRequestLine]) -> dict:
    return {"request_id": req.request_id, "request_code": req.request_code, "note": req.note,
            "requested_by": req.requested_by, "requested_at": req.requested_at,
            "source_type": req.source_type, "source_id": req.source_id,
            "source_label": _source_label(db, req.source_type, req.source_id),
            "lines": [_line_dict(l) for l in sorted(lines, key=lambda l: l.seq)]}


def _stock_at_company(db: Session, material_id: str) -> float:
    """Tổng tồn KHẢ DỤNG của 1 vật tư tại Kho công ty (dùng để chặn đề nghị vượt tồn) — loại
    trừ lô đang HOLD/SCRAPPED, nếu không phiếu đề nghị vẫn tạo được nhưng không bao giờ xuất
    nổi vì issue()/transfer() chặn lô hold (mirror material_fifo_detail đã lọc đúng)."""
    clause = _location_filter_clause("Kho công ty")
    total = db.execute(
        select(func.sum(MaterialLot.quantity)).where(
            MaterialLot.material_id == material_id, clause,
            MaterialLot.status.in_([LotStatus.AVAILABLE.value, LotStatus.RELEASED.value]))
    ).scalar()
    return total or 0.0


def _aggregate_source_material_lines(db: Session, source_type: str, source_id: str) -> list[dict]:
    """Nhu cầu NVL của 1 Lệnh nấu/Lệnh lọc lớn, gộp theo vật tư (cộng dồn nếu 1 vật tư xuất
    hiện nhiều dòng/nhiều lệnh nhỏ) — dùng để tự động điền sẵn phiếu đề nghị nhận kho, mirror
    dữ liệu định mức đã có sẵn ở BrewOrderMaterialLine/FilterOrderMaterialLine (không tính lại
    từ công thức, dùng đúng con số đã "chốt" lúc lập lệnh). Với Lệnh nấu, số lượng lấy đúng
    bằng qty_from_company (phần đã tính phải lấy tại Kho công ty) chứ không phải toàn bộ nhu
    cầu — phần còn lại đã có sẵn tại Kho phân xưởng nên không cần đề nghị nhận thêm.

    Dòng khai theo Nhóm vật tư thay thế (material_id=None, xem models/master.py::MaterialAltGroup)
    KHÔNG được tự chọn hộ 1 mã cụ thể — trả về riêng (is_group=True kèm member_material_ids) để
    router/frontend cảnh báo thủ kho tự chọn mã và số lượng, thay vì âm thầm bỏ qua dòng này."""
    agg: dict[str, dict] = {}
    group_agg: dict[str, dict] = {}

    def _add(material_id: str, material_name: str, uom: str, qty: float) -> None:
        if not material_id or not qty:
            return
        a = agg.setdefault(material_id, {"material_id": material_id, "material_name": material_name,
                                         "uom": uom, "quantity": 0.0})
        a["quantity"] += qty

    def _add_group(group_code: str, group_name: str, member_ids: list, uom: str, qty: float) -> None:
        if not group_code or not qty:
            return
        a = group_agg.setdefault(group_code, {"group_code": group_code, "material_name": group_name,
                                              "member_material_ids": set(), "uom": uom, "quantity": 0.0})
        a["member_material_ids"].update(member_ids or [])
        a["quantity"] += qty

    if source_type == "brew_order":
        from . import brew_order as brew_order_svc
        order = brew_order_svc.get_order(db, source_id)
        for l in order["lines"]:
            if l["is_header"]:
                continue
            # Chỉ cần đề nghị đúng phần đã tính phải lấy ở Kho công ty (phần còn lại lấy tại
            # Kho phân xưởng, không cần đề nghị) — xem BrewOrderMaterialLine.qty_from_company.
            # Lệnh cũ (lập trước khi có tính năng tách SL) chưa có giá trị này -> dùng tạm
            # Nhu cầu Tổng mẻ như hành vi cũ.
            qty = l["qty_from_company"] if l.get("qty_from_company") is not None else l["qty_total"]
            if l["material_id"]:
                _add(l["material_id"], l["material_name"], l["uom"], qty or 0.0)
            elif l.get("material_group_code"):
                _add_group(l["material_group_code"], l["material_name"], l.get("member_material_ids"),
                           l["uom"], qty or 0.0)
    elif source_type == "filter_master_order":
        from . import filter_order as filter_order_svc
        master = filter_order_svc.get_master_order(db, source_id)
        for child in master["children"]:
            for l in child["lines"]:
                if l["material_id"]:
                    _add(l["material_id"], l["material_name"], l["uom"], l["quantity"] or 0.0)
                elif l.get("material_group_code"):
                    member_ids = [m["material_id"] for m in l.get("member_breakdown") or []]
                    _add_group(l["material_group_code"], l["material_name"], member_ids,
                               l["uom"], l["quantity"] or 0.0)
    else:
        raise DomainError(f"Loại nguồn '{source_type}' không hợp lệ (chỉ nhận brew_order|filter_master_order).")

    out = []
    for a in agg.values():
        mat = db.get(Material, a["material_id"])
        out.append({"material_id": a["material_id"],
                    "material_code": mat.code if mat else None,
                    "material_name": (mat.name if mat else None) or a["material_name"],
                    "uom": a["uom"] or (mat.uom if mat else "kg"),
                    "quantity": round(a["quantity"], 3), "is_group": False, "group_code": None,
                    "member_material_ids": []})
    for a in group_agg.values():
        out.append({"material_id": None, "material_code": None, "material_name": a["material_name"],
                    "uom": a["uom"] or "kg", "quantity": round(a["quantity"], 3), "is_group": True,
                    "group_code": a["group_code"], "member_material_ids": sorted(a["member_material_ids"])})
    return sorted(out, key=lambda x: x["material_code"] or x["material_name"] or "")


def preview_source_materials(db: Session, source_type: str, source_id: str) -> list[dict]:
    """Xem trước nhu cầu NVL của 1 Lệnh nấu/Lệnh lọc lớn để tự động điền sẵn phiếu đề nghị
    nhận kho — trả về danh sách vật tư gộp, KHÔNG tạo phiếu (người dùng vẫn chỉnh SL/lô trước
    khi gửi thật, giống Xem NVL của Lệnh nấu — routers/orders.py::preview_bom_lines)."""
    if source_type == "brew_order":
        if not db.get(BrewOrder, source_id):
            raise NotFoundError("Lệnh nấu không tồn tại.")
    elif source_type == "filter_master_order":
        if not db.get(FilterMasterOrder, source_id):
            raise NotFoundError("Lệnh lọc không tồn tại.")
    else:
        raise DomainError(f"Loại nguồn '{source_type}' không hợp lệ (chỉ nhận brew_order|filter_master_order).")
    return _aggregate_source_material_lines(db, source_type, source_id)


def create_request(db: Session, payload: dict, user: User) -> dict:
    """Phân xưởng tạo 1 phiếu đề nghị nhận kho gồm 1 hoặc nhiều dòng vật tư — tuỳ chọn gắn
    với 1 Lệnh nấu/Lệnh lọc lớn (`source_type`/`source_id`, chỉ để tham chiếu/báo cáo).

    Mỗi dòng không được đề nghị vượt quá tồn kho công ty hiện có của vật tư đó."""
    require_perm(user, "warehouse.request")
    source_type = payload.get("source_type")
    source_id = payload.get("source_id")
    if source_type and not source_id:
        raise DomainError("Đã chọn loại nguồn thì phải chọn cả lệnh cụ thể.")
    if source_type == "brew_order" and not db.get(BrewOrder, source_id):
        raise NotFoundError("Lệnh nấu không tồn tại.")
    if source_type == "filter_master_order" and not db.get(FilterMasterOrder, source_id):
        raise NotFoundError("Lệnh lọc không tồn tại.")
    if source_type and source_type not in ("brew_order", "filter_master_order"):
        raise DomainError(f"Loại nguồn '{source_type}' không hợp lệ.")
    lines_payload = payload.get("lines") or []
    if not lines_payload:
        raise DomainError("Đề nghị phải có ít nhất 1 dòng vật tư.")
    for line in lines_payload:
        mat = db.get(Material, line["material_id"])
        if not mat:
            raise NotFoundError(f"Vật tư '{line['material_id']}' không tồn tại.")
        qty = float(line["quantity"])
        if qty <= 0:
            raise DomainError("Số lượng đề nghị phải > 0.")
        on_hand = _stock_at_company(db, line["material_id"])
        if qty > on_hand:
            raise DomainError(
                f"Số lượng đề nghị của '{mat.code}' ({qty} {line.get('uom', 'kg')}) vượt quá "
                f"tồn kho công ty hiện có ({on_hand} {line.get('uom', 'kg')})."
            )
        if line.get("preferred_lot_id"):
            _lot(db, line["preferred_lot_id"])

    req = MaterialRequest(request_id=new_id(), request_code=f"DN-{utcnow():%Y%m%d}-{new_id()[:5].upper()}",
                          note=payload.get("note"), requested_by=user.username, requested_at=utcnow(),
                          source_type=source_type, source_id=source_id)
    db.add(req)
    db.flush()
    lines = []
    for i, line in enumerate(lines_payload):
        ln = MaterialRequestLine(line_id=new_id(), request_id=req.request_id, seq=i,
                                 material_id=line["material_id"], quantity=float(line["quantity"]),
                                 uom=line.get("uom", "kg"), preferred_lot_id=line.get("preferred_lot_id"),
                                 status="pending")
        db.add(ln)
        lines.append(ln)
    record_audit(db, entity_type="material_request", entity_id=req.request_id, action="create",
                 actor=user, after={"lines": len(lines)})
    db.commit()
    for ln in lines:
        db.refresh(ln)
    return _request_dict(db, req, lines)


def list_requests(db: Session, status: str = None, limit: int = 500, offset: int = 0) -> list[dict]:
    """Phiếu kèm dòng, mới nhất trước. `status`: chỉ trả phiếu có ít nhất 1 dòng ở trạng thái
    đó (lọc SAU khi phân trang theo phiếu — số phiếu càng ngày càng nhiều nên có limit/offset,
    tối đa 2000, mặc định 500)."""
    limit = max(1, min(limit or 500, 2000))
    offset = max(0, offset or 0)
    headers = db.execute(select(MaterialRequest).order_by(MaterialRequest.requested_at.desc())
                         .limit(limit).offset(offset)).scalars().all()
    request_ids = [h.request_id for h in headers]
    all_lines = db.execute(select(MaterialRequestLine)
                           .where(MaterialRequestLine.request_id.in_(request_ids))).scalars().all() if request_ids else []
    lines_by_request: dict[str, list] = {}
    for l in all_lines:
        lines_by_request.setdefault(l.request_id, []).append(l)
    out = []
    for h in headers:
        lines = lines_by_request.get(h.request_id, [])
        if status and not any(l.status == status for l in lines):
            continue
        out.append(_request_dict(db, h, lines))
    return out


def _get_request(db, request_id) -> MaterialRequest:
    req = db.get(MaterialRequest, request_id)
    if not req:
        raise NotFoundError("Đề nghị không tồn tại.")
    return req


def _get_request_line(db, request_id: str, line_id: str) -> MaterialRequestLine:
    line = db.get(MaterialRequestLine, line_id)
    if not line or line.request_id != request_id:
        raise NotFoundError("Dòng đề nghị không tồn tại.")
    return line


def cancel_request(db: Session, request_id: str, user: User) -> dict:
    """Hủy phiếu (soft-cancel, vẫn còn trong lịch sử) — chỉ khi CHƯA có dòng nào được duyệt."""
    _require_any_perm(user, "warehouse.request", "warehouse.issue")
    req = _get_request(db, request_id)
    lines = db.execute(
        select(MaterialRequestLine).where(MaterialRequestLine.request_id == request_id)
    ).scalars().all()
    if any(l.status == "fulfilled" for l in lines):
        raise DomainError(f"Phiếu {req.request_code} đã có dòng được duyệt, không thể hủy.")
    for l in lines:
        if l.status == "pending":
            l.status = "cancelled"
    record_audit(db, entity_type="material_request", entity_id=req.request_id, action="cancel", actor=user)
    db.commit()
    return _request_dict(db, req, lines)


def _is_oldest_company_lot(db: Session, material_id: str, lot_id: str) -> bool:
    """Lô đang chọn có phải lô cũ nhất (FIFO) hiện có tại Kho công ty của vật tư đó hay
    không — gọi NGAY TRƯỚC LÚC transfer() để chụp lại (snapshot) vào
    MaterialRequestLine.fifo_ok; so sánh live SAU KHI đã xuất sẽ sai lệch vì lô cũ hơn có
    thể đã hết hoặc lô mới đã nhập thêm.

    Chỉ so sánh trong số lô KHẢ DỤNG (không tính lô đang HOLD/SCRAPPED) — lô cũ nhất tuyệt đối
    có thể đang chờ duyệt QC nên không thể chọn được; nếu vẫn tính lô đó vào danh sách so sánh,
    thủ kho chọn đúng lô khả dụng cũ nhất vẫn bị báo oan "vi phạm FIFO" dù không có lựa chọn nào
    khác."""
    clause = _location_filter_clause("Kho công ty")
    candidates = db.execute(
        select(MaterialLot).where(MaterialLot.material_id == material_id, MaterialLot.quantity > 0, clause,
                                  MaterialLot.status.in_([LotStatus.AVAILABLE.value, LotStatus.RELEASED.value]))
        .order_by(MaterialLot.created_at)
    ).scalars().all()
    return bool(candidates) and candidates[0].lot_id == lot_id


def is_oldest_workshop_lot(db: Session, material_id: str, lot_id: str) -> bool:
    """Lô đang chọn có phải lô cũ nhất (FIFO) hiện có tại Kho phân xưởng của vật tư đó hay
    không — mirror _is_oldest_company_lot (cùng loại trừ lô đang HOLD/SCRAPPED khỏi so sánh),
    dùng cho NVL dùng thật ở mẻ nấu/mẻ lọc/mẻ chiết (xem BrewMaterialUsage/FilterMaterialUsage/
    BottleMaterialUsage.fifo_ok). Gọi NGAY TRƯỚC LÚC issue() trừ kho — so sánh live sau khi đã
    xuất sẽ sai lệch vì lô có thể đã hết."""
    clause = _location_filter_clause("Kho phân xưởng")
    candidates = db.execute(
        select(MaterialLot).where(MaterialLot.material_id == material_id, MaterialLot.quantity > 0, clause,
                                  MaterialLot.status.in_([LotStatus.AVAILABLE.value, LotStatus.RELEASED.value]))
        .order_by(MaterialLot.created_at)
    ).scalars().all()
    return bool(candidates) and candidates[0].lot_id == lot_id


def fulfill_request_line(db: Session, request_id: str, line_id: str, lot_id: str, quantity: float,
                         user: User, location_to: str = "Kho phân xưởng") -> dict:
    """Thủ kho công ty duyệt 1 dòng của phiếu: chuyển lô sang kho đích đã chọn (transfer,
    không phải issue — nguyên liệu vẫn được theo dõi trong hệ thống, chỉ đổi kho)."""
    require_perm(user, "warehouse.issue")
    req = _get_request(db, request_id)
    line = _get_request_line(db, request_id, line_id)
    if line.status != "pending":
        raise DomainError(f"Dòng vật tư này đã ở trạng thái '{line.status}', không thể xử lý lại.")
    fifo_ok = _is_oldest_company_lot(db, line.material_id, lot_id)
    result = transfer(db, lot_id, quantity, location_to, user, mode="xuat_theo_de_nghi",
                      reason=f"Xuất theo đề nghị {req.request_code} (dòng {line.seq + 1})",
                      request_id=req.request_id, request_line_id=line.line_id)
    line.status = "fulfilled"
    # Dùng lot_id TRẢ VỀ từ transfer(), không phải lot_id truyền vào — nếu quantity < tồn của
    # lô gốc, transfer() tách 1 lô mới mang đúng quantity đã xuất; lot_id gốc lúc này vẫn còn
    # nằm ở kho cũ với phần dư, không phải lô thực sự đã sang Kho phân xưởng.
    line.fulfilled_lot_id = result["lot_id"]
    line.fulfilled_qty = quantity
    line.fulfilled_by = user.username
    line.fulfilled_at = utcnow()
    line.fifo_ok = fifo_ok
    record_audit(db, entity_type="material_request_line", entity_id=line.line_id, action="fulfill",
                 actor=user, after={"lot_id": lot_id, "quantity": quantity, "location_to": location_to})
    db.commit()
    return {"request_id": request_id, "line_id": line.line_id, "status": line.status, "lot_id": lot_id,
            "quantity": quantity, "location": result["location"]}


def undo_fulfill_line(db: Session, request_id: str, line_id: str, user: User) -> dict:
    """Hoàn tác 1 dòng đã fulfilled: chuyển lô về lại Kho công ty + đưa dòng về `pending`.
    Chỉ cho phép khi lô CHƯA từng được tiêu thụ (consume) cho mẻ nào — tái dùng bảng
    genealogy có sẵn để tự kiểm tra, không cần thủ kho tự xác nhận."""
    require_perm(user, "warehouse.issue")
    req = _get_request(db, request_id)
    line = _get_request_line(db, request_id, line_id)
    if line.status != "fulfilled":
        raise DomainError(f"Dòng này đang ở trạng thái '{line.status}', không phải 'fulfilled' để hoàn tác.")
    consumed = db.execute(
        select(GenealogyEdge).where(GenealogyEdge.from_id == line.fulfilled_lot_id,
                                    GenealogyEdge.relation == GenealogyRelation.CONSUME.value)
    ).scalars().first()
    if consumed:
        raise DomainError("Lô này đã được dùng cho mẻ sản xuất, không thể hoàn tác.")
    transfer(db, line.fulfilled_lot_id, line.fulfilled_qty, "Kho công ty", user, mode="dieu_chuyen",
            reason=f"Hoàn tác xuất theo đề nghị {req.request_code} (dòng {line.seq + 1})")
    line.status = "pending"
    line.fulfilled_lot_id = None
    line.fulfilled_qty = None
    line.fulfilled_by = None
    line.fulfilled_at = None
    line.fifo_ok = None
    record_audit(db, entity_type="material_request_line", entity_id=line.line_id, action="undo_fulfill", actor=user)
    db.commit()
    return _line_dict(line)


def fulfill_all_lines(db: Session, request_id: str, user: User,
                      location_to: str = "Kho phân xưởng") -> dict:
    """Duyệt cả phiếu 1 lần: với mỗi dòng đang pending, tự chọn lô (ưu tiên lô đã chọn khi đề
    nghị nếu đủ số lượng và không đang HOLD, ngược lại chọn lô FIFO đủ số lượng) rồi transfer.
    Dòng nào không có lô đơn lẻ nào đủ số lượng (hoặc lô đang chờ QC) sẽ bị bỏ qua để xử lý
    thủ công riêng — vì việc tách 1 dòng ra nhiều lô nằm ngoài phạm vi MVP này."""
    require_perm(user, "warehouse.issue")
    req = _get_request(db, request_id)
    lines = db.execute(
        select(MaterialRequestLine).where(MaterialRequestLine.request_id == request_id,
                                          MaterialRequestLine.status == "pending")
        .order_by(MaterialRequestLine.seq)
    ).scalars().all()
    fulfilled, skipped = [], []
    for line in lines:
        candidates = db.execute(
            select(MaterialLot).where(MaterialLot.material_id == line.material_id,
                                      MaterialLot.quantity >= line.quantity,
                                      MaterialLot.status != LotStatus.ON_HOLD.value)
        ).scalars().all()
        candidates = [c for c in candidates if not _is_workshop_location(c.location)]
        lot = None
        if line.preferred_lot_id:
            lot = next((c for c in candidates if c.lot_id == line.preferred_lot_id), None)
        if not lot and candidates:
            lot = sorted(candidates, key=lambda c: c.created_at)[0]   # FIFO
        if not lot:
            skipped.append({"line_id": line.line_id, "material_id": line.material_id,
                            "reason": "Không có lô nào đủ số lượng (hoặc đang chờ duyệt QC) — cần xử lý thủ công."})
            continue
        fifo_ok = _is_oldest_company_lot(db, line.material_id, lot.lot_id)
        result = transfer(db, lot.lot_id, line.quantity, location_to, user, mode="xuat_theo_de_nghi",
                          reason=f"Xuất theo đề nghị {req.request_code} (dòng {line.seq + 1}, duyệt cả phiếu)",
                          request_id=req.request_id, request_line_id=line.line_id)
        line.status = "fulfilled"
        # Dùng lot_id TRẢ VỀ từ transfer() (có thể là lô tách), không phải lot.lot_id gốc —
        # mirror fulfill_request_line (xem đó), tránh cùng lỗi cho đường "duyệt cả phiếu".
        line.fulfilled_lot_id = result["lot_id"]
        line.fulfilled_qty = line.quantity
        line.fulfilled_by = user.username
        line.fulfilled_at = utcnow()
        line.fifo_ok = fifo_ok
        record_audit(db, entity_type="material_request_line", entity_id=line.line_id, action="fulfill",
                     actor=user, after={"lot_id": lot.lot_id, "quantity": line.quantity, "location_to": location_to})
        db.commit()
        fulfilled.append({"line_id": line.line_id, "material_id": line.material_id,
                          "lot_id": result["lot_id"], "quantity": line.quantity, "location": result["location"]})
    return {"request_id": request_id, "fulfilled": fulfilled, "skipped": skipped}


def reject_request_line(db: Session, request_id: str, line_id: str, reason: str, user: User) -> dict:
    require_perm(user, "warehouse.issue")
    line = _get_request_line(db, request_id, line_id)
    if line.status != "pending":
        raise DomainError(f"Dòng vật tư này đã ở trạng thái '{line.status}', không thể xử lý lại.")
    line.status = "rejected"
    line.reason = reason
    record_audit(db, entity_type="material_request_line", entity_id=line.line_id, action="reject",
                 actor=user, reason=reason)
    db.commit()
    db.refresh(line)
    return _line_dict(line)


# ---- Điều chuyển phân xưởng → công ty / trả nhà cung cấp / hoàn xuất tự do / lịch sử ----

# ---- Điều chuyển kho công ty, chiều 1: Kho phân xưởng → Kho công ty (duyệt trước khi chuyển) ----
# Thủ kho phân xưởng tạo đề nghị (CHƯA động tồn kho) → Thủ kho công ty duyệt thì lệnh MỚI THỰC
# SỰ gọi transfer() dịch chuyển lô. Sau khi đã duyệt, chỉ ADMIN mới "Hoàn tác" được.

def _transfer_px_request_dict(req: TransferPxRequest) -> dict:
    return {"request_id": req.request_id, "request_code": req.request_code, "lot_id": req.lot_id,
            "quantity": req.quantity, "uom": req.uom, "reason": req.reason, "status": req.status,
            "movement_id": req.movement_id, "reversed": req.reversed,
            "created_by": req.created_by, "created_at": req.created_at,
            "approved_by": req.approved_by, "approved_at": req.approved_at,
            "rejected_by": req.rejected_by, "rejected_at": req.rejected_at,
            "reject_reason": req.reject_reason}


def _get_transfer_px_request(db, request_id) -> TransferPxRequest:
    req = db.get(TransferPxRequest, request_id)
    if not req:
        raise NotFoundError("Đề nghị điều chuyển không tồn tại.")
    return req


def create_transfer_px_request(db: Session, lot_id: str, quantity: float, user: User,
                               reason: str = None) -> dict:
    """Thủ kho phân xưởng tạo đề nghị điều chuyển 1 lô về Kho công ty — chưa động tồn kho."""
    require_perm(user, "warehouse.request")
    lot = _lot(db, lot_id)
    if not _is_workshop_location(lot.location):
        raise DomainError(f"Lô {lot.lot_code} không ở Kho phân xưởng — chỉ đề nghị điều chuyển "
                          "được lô đang ở kho phân xưởng.")
    if lot.status == LotStatus.ON_HOLD.value:
        raise DomainError(f"Lô {lot.lot_code} đang HOLD, không được đề nghị điều chuyển.")
    if quantity <= 0 or quantity > lot.quantity:
        raise DomainError(f"Số lượng đề nghị không hợp lệ (tồn {lot.quantity} {lot.uom}).")
    req = TransferPxRequest(request_id=new_id(), request_code=f"DCPX-{utcnow():%Y%m%d}-{new_id()[:5].upper()}",
                            lot_id=lot_id, quantity=quantity, uom=lot.uom, reason=reason,
                            status="pending", created_by=user.username, created_at=utcnow())
    db.add(req)
    record_audit(db, entity_type="transfer_px_request", entity_id=req.request_id, action="create",
                actor=user, after={"lot_id": lot_id, "quantity": quantity})
    db.commit()
    db.refresh(req)
    return _transfer_px_request_dict(req)


def list_transfer_px_requests(db: Session, status: str = None, limit: int = 500,
                              offset: int = 0) -> list[dict]:
    limit = max(1, min(limit or 500, 2000))
    offset = max(0, offset or 0)
    stmt = select(TransferPxRequest).order_by(TransferPxRequest.created_at.desc()).limit(limit).offset(offset)
    if status:
        stmt = stmt.where(TransferPxRequest.status == status)
    rows = db.execute(stmt).scalars().all()
    return [_transfer_px_request_dict(r) for r in rows]


def approve_transfer_px_request(db: Session, request_id: str, user: User) -> dict:
    """Thủ kho công ty duyệt — lúc này MỚI thật sự chuyển lô (tăng tồn Kho công ty, giảm tồn
    Kho phân xưởng) qua transfer(). Chốt bằng _assert_location_scope("Kho công ty") — không chỉ
    require_perm — để người tạo đề nghị (Kho phân xưởng, cũng có warehouse.receive cho việc kiểm
    kê riêng của họ) KHÔNG tự duyệt được đề nghị của chính mình (maker-checker)."""
    require_perm(user, "warehouse.receive")
    _assert_location_scope(user, "Kho công ty")
    req = _get_transfer_px_request(db, request_id)
    if req.status != "pending":
        raise DomainError(f"Đề nghị {req.request_code} đã được xử lý (trạng thái: {req.status}).")
    lot = _lot(db, req.lot_id)
    if not _is_workshop_location(lot.location):
        raise DomainError(f"Lô {lot.lot_code} hiện không còn ở Kho phân xưởng — có thể đã được "
                          "xử lý bởi thao tác khác.")
    result = transfer(db, req.lot_id, req.quantity, "Kho công ty", user, reason=req.reason,
                      mode="dieu_chuyen")
    req.movement_id = result["movement_id"]
    req.status = "approved"
    req.approved_by = user.username
    req.approved_at = utcnow()
    req.reversed = False
    record_audit(db, entity_type="transfer_px_request", entity_id=req.request_id, action="approve", actor=user)
    db.commit()
    db.refresh(req)
    return _transfer_px_request_dict(req)


def reject_transfer_px_request(db: Session, request_id: str, user: User, reason: str = None) -> dict:
    require_perm(user, "warehouse.receive")
    _assert_location_scope(user, "Kho công ty")
    req = _get_transfer_px_request(db, request_id)
    if req.status != "pending":
        raise DomainError(f"Đề nghị {req.request_code} đã được xử lý (trạng thái: {req.status}).")
    req.status = "rejected"
    req.rejected_by = user.username
    req.rejected_at = utcnow()
    req.reject_reason = reason
    record_audit(db, entity_type="transfer_px_request", entity_id=req.request_id, action="reject",
                actor=user, after={"reason": reason})
    db.commit()
    db.refresh(req)
    return _transfer_px_request_dict(req)


def undo_transfer_px_request(db: Session, request_id: str, user: User) -> dict:
    """Hoàn tác đề nghị ĐÃ duyệt — trả lô về lại Kho phân xưởng VÀ đưa phiếu về lại trạng thái
    "pending" (chưa duyệt) để thủ kho công ty xử lý lại (duyệt lại hoặc từ chối) — không giữ
    nguyên trạng thái "approved" như StockMovement.reversed (đây là phiếu đề nghị, không phải
    sổ giao dịch, nên hoàn tác nghĩa là coi như CHƯA từng duyệt). "Chia rõ 2 quyền khác nhau"
    (yêu cầu ban đầu) áp dụng cho tạo (warehouse.request, phía phân xưởng) và duyệt/từ chối
    (warehouse.receive, phía công ty) — SAU KHI đã duyệt, đề nghị coi như khóa lại, chỉ ADMIN
    mới hoàn tác được (mirror đúng khóa của chiều 2 — xem undo_issue mode=dieu_chuyen_nha_may)."""
    req = _get_transfer_px_request(db, request_id)
    if req.status != "approved":
        raise DomainError(f"Chỉ hoàn tác được đề nghị đã duyệt (trạng thái hiện tại: {req.status}).")
    require_role(user, Role.ADMIN)
    # Dùng lot_id THẬT của giao dịch đã duyệt (StockMovement.lot_id), không phải req.lot_id gốc —
    # nếu lúc duyệt chỉ chuyển 1 phần lô, transfer() đã tách ra 1 lô mới mang đúng số lượng đó;
    # req.lot_id vẫn là lô gốc còn ở Kho phân xưởng với phần dư, không phải lô đã sang Kho công ty.
    mv = db.get(StockMovement, req.movement_id) if req.movement_id else None
    lot_id_to_revert = mv.lot_id if mv else req.lot_id
    transfer(db, lot_id_to_revert, req.quantity, "Kho phân xưởng", user,
            reason=f"Hoàn tác điều chuyển {req.request_code}", mode="dieu_chuyen")
    req.status = "pending"
    req.approved_by = None
    req.approved_at = None
    req.movement_id = None
    req.reversed = True
    record_audit(db, entity_type="transfer_px_request", entity_id=req.request_id, action="undo", actor=user)
    db.commit()
    db.refresh(req)
    return _transfer_px_request_dict(req)


def _sang_ngang_dict(req: SangNgangRequest) -> dict:
    return {"request_id": req.request_id, "request_code": req.request_code, "lot_id": req.lot_id,
            "quantity": req.quantity, "uom": req.uom, "reason": req.reason, "status": req.status,
            "movement_id": req.movement_id, "reversed": req.reversed,
            "created_by": req.created_by, "created_at": req.created_at,
            "approved_by": req.approved_by, "approved_at": req.approved_at,
            "rejected_by": req.rejected_by, "rejected_at": req.rejected_at,
            "reject_reason": req.reject_reason,
            "can_edit": req.status != "approved"}


def _get_sang_ngang(db, request_id) -> SangNgangRequest:
    req = db.get(SangNgangRequest, request_id)
    if not req:
        raise NotFoundError("Đề nghị xuất sang ngang không tồn tại.")
    return req


def create_sang_ngang(db: Session, payload: dict, user: User) -> dict:
    """Thủ kho công ty khai báo "Xuất sang ngang": hàng về CẬP KHO CÔNG TY (gọi receive() y hệt
    Nhập kho thường — tăng tồn công ty, ghi StockMovement type=receipt, HOLD nếu vật tư có chỉ
    tiêu bắt buộc) rồi tạo đề nghị này — CHƯA chuyển vị trí lô, chỉ khi Thủ kho phân xưởng duyệt
    mới thật sự sang Kho phân xưởng (xem approve_sang_ngang)."""
    payload = dict(payload)
    payload["location"] = "Kho công ty"
    receipt = receive(db, payload, user)
    req = SangNgangRequest(request_id=new_id(), request_code=f"SNG-{utcnow():%Y%m%d}-{new_id()[:5].upper()}",
                          lot_id=receipt["lot_id"], quantity=float(payload["quantity"]),
                          uom=payload.get("uom", "kg"), reason=payload.get("reason"),
                          status="pending", created_by=user.username, created_at=utcnow(),
                          receipt_movement_id=receipt["movement_id"])
    db.add(req)
    record_audit(db, entity_type="sang_ngang_request", entity_id=req.request_id, action="create",
                actor=user, after={"lot_id": receipt["lot_id"], "quantity": payload["quantity"]})
    db.commit()
    db.refresh(req)
    return _sang_ngang_dict(req)


def list_sang_ngang_requests(db: Session, status: str = None, limit: int = 500,
                             offset: int = 0) -> list[dict]:
    limit = max(1, min(limit or 500, 2000))
    offset = max(0, offset or 0)
    stmt = select(SangNgangRequest).order_by(SangNgangRequest.created_at.desc()).limit(limit).offset(offset)
    if status:
        stmt = stmt.where(SangNgangRequest.status == status)
    rows = db.execute(stmt).scalars().all()
    return [_sang_ngang_dict(r) for r in rows]


def approve_sang_ngang(db: Session, request_id: str, user: User) -> dict:
    """Thủ kho phân xưởng duyệt — lúc này MỚI thật sự chuyển lô (giảm tồn Kho công ty, tăng tồn
    Kho phân xưởng) qua transfer(). Chốt bằng _assert_location_scope("Kho phân xưởng") để người
    tạo đề nghị (Kho công ty) KHÔNG tự duyệt được đề nghị của chính mình (maker-checker). Nếu vật
    tư có chỉ tiêu chất lượng bắt buộc và lô vẫn đang HOLD (chưa qua KCS), chặn duyệt."""
    require_perm(user, "warehouse.request")
    _assert_location_scope(user, "Kho phân xưởng")
    req = _get_sang_ngang(db, request_id)
    if req.status != "pending":
        raise DomainError(f"Đề nghị {req.request_code} đã được xử lý (trạng thái: {req.status}).")
    lot = _lot(db, req.lot_id)
    if _is_workshop_location(lot.location):
        raise DomainError(f"Lô {lot.lot_code} hiện không còn ở Kho công ty — có thể đã được "
                          "xử lý bởi thao tác khác.")
    if lot.status == LotStatus.ON_HOLD.value:
        raise DomainError(f"Lô {lot.lot_code} đang chờ KCS khai báo/duyệt chỉ tiêu chất lượng — "
                          "chưa thể nhận vào Kho phân xưởng.")
    result = _transfer_lot(db, req.lot_id, req.quantity, "Kho phân xưởng", user, reason=req.reason,
                           mode="sang_ngang")
    req.movement_id = result["movement_id"]
    req.status = "approved"
    req.approved_by = user.username
    req.approved_at = utcnow()
    req.reversed = False
    record_audit(db, entity_type="sang_ngang_request", entity_id=req.request_id, action="approve", actor=user)
    db.commit()
    db.refresh(req)
    return _sang_ngang_dict(req)


def reject_sang_ngang(db: Session, request_id: str, user: User, reason: str = None) -> dict:
    require_perm(user, "warehouse.request")
    _assert_location_scope(user, "Kho phân xưởng")
    req = _get_sang_ngang(db, request_id)
    if req.status != "pending":
        raise DomainError(f"Đề nghị {req.request_code} đã được xử lý (trạng thái: {req.status}).")
    req.status = "rejected"
    req.rejected_by = user.username
    req.rejected_at = utcnow()
    req.reject_reason = reason
    record_audit(db, entity_type="sang_ngang_request", entity_id=req.request_id, action="reject",
                actor=user, after={"reason": reason})
    db.commit()
    db.refresh(req)
    return _sang_ngang_dict(req)


def update_sang_ngang(db: Session, request_id: str, payload: dict, user: User) -> dict:
    """Sửa 1 đề nghị "Xuất sang ngang" — cho phép khi CHƯA được Kho phân xưởng duyệt (status
    pending hoặc rejected; đã duyệt thì lô đã thật sự chuyển kho, không còn "sửa nhập" an toàn
    nữa). Tái dùng đúng update_receipt() cho lượt nhập kho gốc (đã tự chặn nếu lô liên quan đã bị
    dùng/xuất/chuyển — dù request này chưa duyệt, lô vẫn có thể đã bị thao tác khác động vào)."""
    req = _get_sang_ngang(db, request_id)
    if req.status == "approved":
        raise DomainError(f"Đề nghị {req.request_code} đã được Kho phân xưởng duyệt — không thể sửa.")
    if not req.receipt_movement_id:
        raise DomainError("Đề nghị này không có lượt nhập kho liên kết (dữ liệu cũ) — không thể sửa.")
    update_receipt(db, req.receipt_movement_id, payload, user)
    if payload.get("quantity") is not None:
        req.quantity = float(payload["quantity"])
    if "uom" in payload and payload["uom"] is not None:
        req.uom = payload["uom"]
    if "reason" in payload:
        req.reason = payload["reason"]
    record_audit(db, entity_type="sang_ngang_request", entity_id=req.request_id, action="update",
                actor=user, after={"quantity": req.quantity, "reason": req.reason})
    db.commit()
    db.refresh(req)
    return _sang_ngang_dict(req)


def delete_sang_ngang(db: Session, request_id: str, user: User) -> dict:
    """Xóa 1 đề nghị "Xuất sang ngang" chưa được Kho phân xưởng duyệt (status pending hoặc
    rejected) — xóa qua delete_receipt() trên đúng lượt nhập kho gốc (tự chặn nếu lô đã dùng/đã
    khai báo QC; tự cascade xóa CHÍNH dòng đề nghị này nếu đây là lô vừa bị xóa hẳn — xem
    delete_receipt), rồi dọn nốt nếu đề nghị vẫn còn (lô còn receipt khác nên chưa bị xóa)."""
    req = _get_sang_ngang(db, request_id)
    if req.status == "approved":
        raise DomainError(f"Đề nghị {req.request_code} đã được Kho phân xưởng duyệt — không thể xóa.")
    if not req.receipt_movement_id:
        raise DomainError("Đề nghị này không có lượt nhập kho liên kết (dữ liệu cũ) — không thể xóa.")
    request_code, lot_id, status = req.request_code, req.lot_id, req.status
    result = delete_receipt(db, req.receipt_movement_id, user)
    still_there = db.get(SangNgangRequest, request_id)
    if still_there:
        record_audit(db, entity_type="sang_ngang_request", entity_id=request_id, action="delete",
                    actor=user, before={"lot_id": lot_id, "status": status})
        db.delete(still_there)
        db.commit()
    return {"deleted": True, "request_code": request_code, **result}


def undo_sang_ngang(db: Session, request_id: str, user: User) -> dict:
    """Hoàn tác đề nghị ĐÃ duyệt — trả lô về lại Kho công ty VÀ đưa phiếu về lại "pending" để
    thủ kho phân xưởng xử lý lại — CHỈ ADMIN (mirror undo_transfer_px_request)."""
    req = _get_sang_ngang(db, request_id)
    if req.status != "approved":
        raise DomainError(f"Chỉ hoàn tác được đề nghị đã duyệt (trạng thái hiện tại: {req.status}).")
    require_role(user, Role.ADMIN)
    mv = db.get(StockMovement, req.movement_id) if req.movement_id else None
    lot_id_to_revert = mv.lot_id if mv else req.lot_id
    _transfer_lot(db, lot_id_to_revert, req.quantity, "Kho công ty", user,
                 reason=f"Hoàn tác xuất sang ngang {req.request_code}", mode="sang_ngang")
    req.status = "pending"
    req.approved_by = None
    req.approved_at = None
    req.movement_id = None
    req.reversed = True
    record_audit(db, entity_type="sang_ngang_request", entity_id=req.request_id, action="undo", actor=user)
    db.commit()
    db.refresh(req)
    return _sang_ngang_dict(req)


def return_to_supplier(db: Session, lot_id: str, quantity: float, user: User, reason: str) -> dict:
    """Xuất trả nhà cung cấp: lô hỏng/không đạt rời khỏi hệ thống hẳn — bắt buộc có lý do."""
    if not reason or not reason.strip():
        raise DomainError("Phải nhập lý do trả nhà cung cấp (vd: hàng hỏng, không đạt chỉ tiêu).")
    return issue(db, lot_id, quantity, user, mode="tra_ncc", reason=reason)


def undo_issue(db: Session, movement_id: str, user: User, strict: bool = True,
                skip_perm_check: bool = False) -> dict:
    """Hoàn lại 1 giao dịch xuất tự do (mode="tu_do") hoặc điều chuyển sang nhà máy khác
    (mode="dieu_chuyen_nha_may") — không áp dụng cho trả NCC (hàng đã rời kho thật sự) hay
    xuất theo đề nghị. Chặn hoàn 2 lần bằng cờ `reversed`.

    Điều chuyển sang nhà máy khác: tự do hoàn tác cho tới khi Trưởng phòng Kế hoạch duyệt
    (approve_transfer_to_factory đặt `approved_by`) — sau đó CHỈ ADMIN mới hoàn tác được.

    `strict=False` (dùng khi xóa theo tầng — xóa mẻ nấu/lọc/chiết kéo theo xóa từng dòng NVL
    đã dùng): nếu giao dịch ĐÃ được hoàn trước đó rồi thì coi là xong việc, trả về luôn thay vì
    báo lỗi — tránh chặn cứng không xóa được nếu 1 lần xóa trước đó bị lỗi dở dang giữa chừng
    (VD lỗi ở dòng NVL thứ 2 nhưng dòng thứ 1 đã hoàn kho + commit xong — services/warehouse.py::
    undo_issue tự commit riêng nên khi retry sẽ gặp lại dòng đã hoàn). Giữ `strict=True` (mặc
    định) cho nút "Hoàn tác" thao tác tay của người dùng (routers/warehouse.py::undo_issue) và
    luồng SỬA số lượng NVL (update_brew_material và tương đương Lọc/Chiết) — ở 2 chỗ đó gặp lại
    giao dịch đã hoàn thật sự là bất thường, cần báo cho người dùng biết.

    skip_perm_check=True: mọi lệnh gọi từ routers/brewing.py (thêm/sửa/xóa NVL dùng cho mẻ
    nấu/lọc/chiết, xóa mẻ theo tầng) — router đó đã tự gate bằng "batch.execute", không cần
    đòi thêm "warehouse.issue" (xem issue() ở trên, cùng lý do)."""
    if not skip_perm_check:
        require_perm(user, "warehouse.issue")
    mv = db.get(StockMovement, movement_id)
    if not mv:
        raise NotFoundError("Giao dịch không tồn tại.")
    if mv.movement_type != "issue" or mv.mode not in ("tu_do", "dieu_chuyen_nha_may"):
        raise DomainError("Chỉ hoàn lại được giao dịch xuất tự do hoặc điều chuyển sang nhà máy "
                          "khác (không áp dụng cho trả NCC/xuất theo đề nghị).")
    if mv.reversed:
        if not strict:
            return {"movement_id": mv.movement_id, "already_reversed": True}
        raise DomainError("Giao dịch này đã được hoàn lại trước đó.")
    if mv.mode == "dieu_chuyen_nha_may" and mv.approved_by:
        require_role(user, Role.ADMIN)
    result = return_stock(db, mv.lot_id, mv.quantity, user, reason=f"Hoàn lại xuất kho (giao dịch {mv.movement_id})",
                          skip_perm_check=skip_perm_check)
    mv.reversed = True
    new_mv = db.get(StockMovement, result["movement_id"])
    new_mv.reversal_of = mv.movement_id
    record_audit(db, entity_type="stock_movement", entity_id=mv.movement_id, action="undo_issue", actor=user)
    db.commit()
    return result


def delete_free_issue_history(db: Session, workshop: bool, user: User) -> dict:
    """Xóa lịch sử Xuất tự do (Kho phân xưởng nếu workshop=True, Kho công ty nếu False) —
    CHỈ ADMIN. Chỉ xóa các giao dịch xuất tự do THẬT SỰ tự do (không gắn với NVL đã dùng cho
    mẻ nấu/lọc/chiết) — những dòng đó cũng dùng chung mode="tu_do" (xem add_brew_material/
    add_filter_material/add_bottle_material) nhưng đang bị brew_material_usage/
    filter_material_usage/bottle_material_usage.movement_id tham chiếu, PHẢI giữ nguyên để
    không làm mất dấu vết NVL đã dùng thật cho sản xuất."""
    require_role(user, Role.ADMIN)
    used_ids = set()
    for cls in (BrewMaterialUsage, FilterMaterialUsage, BottleMaterialUsage):
        used_ids.update(row[0] for row in db.execute(
            select(cls.movement_id).where(cls.movement_id.isnot(None))).all())
    rows = db.execute(select(StockMovement).where(
        StockMovement.movement_type == "issue", StockMovement.mode == "tu_do")).scalars().all()
    target = [m for m in rows if m.movement_id not in used_ids
              and _is_workshop_location(m.location_from) == workshop]
    ids = {m.movement_id for m in target}
    if ids:
        # Xóa giao dịch "Hoàn lại" trỏ ngược (reversal_of) tới các dòng này trước — tự tham
        # chiếu nên phải xóa con trước cha.
        for r in db.execute(select(StockMovement).where(StockMovement.reversal_of.in_(ids))).scalars().all():
            db.delete(r)
        db.flush()
        for m in target:
            db.delete(m)
    record_audit(db, entity_type="stock_movement", entity_id="bulk", action="delete_free_issue_history",
                 actor=user, after={"scope": "phan_xuong" if workshop else "cong_ty", "count": len(target)})
    db.commit()
    return {"deleted": len(target)}


def delete_receipt_history(db: Session, user: User) -> dict:
    """Xóa lịch sử Nhập kho (Kho công ty) — CHỈ ADMIN. Chỉ xóa bản ghi sổ nhập
    (StockMovement movement_type="receipt"), KHÔNG đụng lô/tồn kho hiện tại — các lô đã tạo
    từ những lần nhập đó vẫn còn nguyên trong material_lot, chỉ mất dòng lịch sử ghi lại
    giao dịch nhập đó."""
    require_role(user, Role.ADMIN)
    rows = db.execute(select(StockMovement).where(StockMovement.movement_type == "receipt")).scalars().all()
    count = len(rows)
    for m in rows:
        db.delete(m)
    record_audit(db, entity_type="stock_movement", entity_id="bulk", action="delete_receipt_history",
                 actor=user, after={"count": count})
    db.commit()
    return {"deleted": count}


def delete_request_history(db: Session, user: User) -> dict:
    """Xóa "Sổ xuất theo đề nghị" (các phiếu đề nghị nhận kho ĐÃ xử lý xong hết — không còn
    dòng nào ở trạng thái pending) — CHỈ ADMIN. Xóa phiếu + dòng + giao dịch StockMovement
    (mode="xuat_theo_de_nghi") gắn với phiếu đó. KHÔNG đụng phiếu còn dòng đang chờ xử lý
    (những phiếu đó vẫn hiện ở khối "đang chờ", không phải lịch sử)."""
    require_role(user, Role.ADMIN)
    all_requests = db.execute(select(MaterialRequest)).scalars().all()
    done = []
    for req in all_requests:
        lines = db.execute(select(MaterialRequestLine).where(
            MaterialRequestLine.request_id == req.request_id)).scalars().all()
        if lines and not any(l.status == "pending" for l in lines):
            done.append((req, lines))
    request_ids = [req.request_id for req, _ in done]
    if request_ids:
        # Liên kết trực tiếp qua StockMovement.request_id (khóa ngoại) thay vì so khớp chuỗi
        # `reason` — bền hơn nếu định dạng lý do từng bị sửa tay ở nơi khác. Phiếu cũ hơn (tạo
        # trước khi có cột này) không có request_id nên vẫn dự phòng khớp theo `reason` như trước.
        codes = [req.request_code for req, _ in done]
        xtdn = db.execute(select(StockMovement).where(StockMovement.mode == "xuat_theo_de_nghi")).scalars().all()
        for m in xtdn:
            if m.request_id in request_ids or (
                m.request_id is None and m.reason and
                any(m.reason.startswith(f"Xuất theo đề nghị {code}") for code in codes)):
                db.delete(m)
        db.flush()
        for req, lines in done:
            for l in lines:
                db.delete(l)
            db.flush()
            db.delete(req)
    record_audit(db, entity_type="material_request", entity_id="bulk", action="delete_request_history",
                 actor=user, after={"count": len(done)})
    db.commit()
    return {"deleted": len(done)}


def list_movements(db: Session, movement_type: str = None, mode: str = None, limit: int = 200,
                   offset: int = 0) -> list[StockMovement]:
    """Sổ giao dịch kho — dùng chung cho lịch sử xuất tự do / điều chuyển / trả NCC / xuất theo đề
    nghị. Có phân trang (limit tối đa 2000, offset) — sổ càng ngày càng dài nên không cho tải hết
    không giới hạn."""
    limit = max(1, min(limit or 200, 2000))
    offset = max(0, offset or 0)
    stmt = select(StockMovement).order_by(StockMovement.ts.desc()).limit(limit).offset(offset)
    if movement_type:
        stmt = stmt.where(StockMovement.movement_type == movement_type)
    if mode:
        stmt = stmt.where(StockMovement.mode == mode)
    return db.execute(stmt).scalars().all()


def workshop_usage_history(db: Session, limit: int = 200) -> list[dict]:
    """Lịch sử NVL xuất từ Kho phân xưởng đã dùng thật cho sản xuất — cho biết đúng công
    đoạn (Nấu/Lọc/Chiết), mẻ, lô NVL của từng dòng đã gán (xem routers/brewing.py::
    add_brew_material/add_filter_material/add_bottle_material). Khác "Xuất tự do" (StockMovement
    mode="tu_do") chỉ ghi lý do dạng text tự do dùng chung cho cả xuất tay lẫn xuất dùng sản
    xuất — ở đây tra thẳng 3 bảng usage (đã liên kết sẵn tới batch/filter/bottle) nên có cấu
    trúc rõ ràng theo công đoạn/mẻ, không phải suy từ chuỗi lý do.

    Mỗi truy vấn con đã ORDER BY created_at DESC LIMIT limit trước khi gộp — vì kết quả cuối
    cùng chỉ lấy top `limit` bản ghi mới nhất trên cả 3 nguồn, top-limit của mỗi nguồn riêng
    lẻ chắc chắn phủ hết top-limit gộp, nên không cần tải hết cả 3 bảng vào bộ nhớ."""
    limit = max(1, min(limit or 200, 5000))
    rows = []
    for u, batch_code, brew_code in db.execute(
            select(BrewMaterialUsage, BrewBatch.batch_code, BrewRecord.brew_code)
            .join(BrewBatch, BrewMaterialUsage.batch_id == BrewBatch.batch_id)
            .join(BrewRecord, BrewBatch.brew_id == BrewRecord.brew_id)
            .order_by(BrewMaterialUsage.created_at.desc()).limit(limit)).all():
        rows.append({"usage_id": u.usage_id, "ts": u.created_at, "stage": "Nấu",
                    "batch_label": f"Mẻ {batch_code} (mã nấu {brew_code})",
                    "material_name": u.material_name, "lot_code": u.lot_pm,
                    "quantity": u.quantity, "uom": u.uom, "movement_id": u.movement_id})
    for u, filter_code in db.execute(
            select(FilterMaterialUsage, FilterRecord.filter_code)
            .join(FilterRecord, FilterMaterialUsage.filter_id == FilterRecord.filter_id)
            .order_by(FilterMaterialUsage.created_at.desc()).limit(limit)).all():
        rows.append({"usage_id": u.usage_id, "ts": u.created_at, "stage": "Lọc",
                    "batch_label": f"Mẻ lọc {filter_code}",
                    "material_name": u.material_name, "lot_code": u.lot_pm,
                    "quantity": u.quantity, "uom": u.uom, "movement_id": u.movement_id})
    for u, bottle_code in db.execute(
            select(BottleMaterialUsage, BottleRecord.bottle_code)
            .join(BottleRecord, BottleMaterialUsage.bottle_id == BottleRecord.bottle_id)
            .order_by(BottleMaterialUsage.created_at.desc()).limit(limit)).all():
        rows.append({"usage_id": u.usage_id, "ts": u.created_at, "stage": "Chiết",
                    "batch_label": f"Mẻ chiết {bottle_code}",
                    "material_name": u.material_name, "lot_code": u.lot_pm,
                    "quantity": u.quantity, "uom": u.uom, "movement_id": u.movement_id})

    movement_ids = [r["movement_id"] for r in rows if r["movement_id"]]
    actor_by_id = dict(db.execute(select(StockMovement.movement_id, StockMovement.actor)
                                  .where(StockMovement.movement_id.in_(movement_ids))).all()) if movement_ids else {}
    for r in rows:
        r["actor"] = actor_by_id.get(r.pop("movement_id"))

    rows.sort(key=lambda r: r["ts"], reverse=True)
    return rows[:limit]


# ---- Kiểm kê định kỳ (cycle count): đối chiếu tồn hệ thống vs tồn thực tế ----

def _count_line_dict(line: StockCountLine, mat_by_id: dict, lot_by_id: dict) -> dict:
    mat = mat_by_id.get(line.material_id)
    lot = lot_by_id.get(line.lot_id)
    variance = None if line.counted_qty is None else round(line.counted_qty - line.system_qty, 3)
    return {"line_id": line.line_id, "material_id": line.material_id,
            "material_code": mat.code if mat else None, "material_name": mat.name if mat else None,
            "lot_id": line.lot_id, "lot_code": lot.lot_code if lot else None,
            "location": lot.location if lot else None,
            "system_qty": round(line.system_qty, 3),
            "counted_qty": round(line.counted_qty, 3) if line.counted_qty is not None else None,
            "variance": variance, "uom": line.uom, "note": line.note}


def _count_dict(db: Session, count: StockCount) -> dict:
    lines = db.execute(select(StockCountLine).where(StockCountLine.count_id == count.count_id)).scalars().all()
    mat_by_id = {m.material_id: m for m in db.execute(select(Material)).scalars().all()}
    lot_by_id = {l.lot_id: l for l in db.execute(select(MaterialLot)).scalars().all()}
    line_dicts = [_count_line_dict(l, mat_by_id, lot_by_id) for l in lines]
    return {"count_id": count.count_id, "count_code": count.count_code, "location": count.location,
            "start_date": count.start_date, "end_date": count.end_date,
            "note": count.note, "status": count.status, "created_by": count.created_by,
            "created_at": count.created_at, "posted_by": count.posted_by, "posted_at": count.posted_at,
            "approved_by": count.approved_by, "approved_at": count.approved_at,
            "can_undo": count.status == "posted" and not count.approved_by,
            "can_approve": count.status == "posted" and not count.approved_by,
            "lines": line_dicts,
            "variance_count": sum(1 for l in line_dicts if l["variance"])}


def create_count(db: Session, location: Optional[str], user: User, note: str = None,
                 start_date=None, end_date=None) -> dict:
    """Tạo phiếu kiểm kê: chụp (snapshot) tồn hệ thống hiện tại của mọi lô còn tồn tại 1 kho
    (hoặc toàn bộ nếu không lọc theo kho) thành các dòng StockCountLine — nhân viên điền
    counted_qty sau, không sửa được system_qty (đây là mốc đối chiếu tại thời điểm tạo phiếu).
    start_date/end_date là kỳ kiểm kê thực tế khai báo tay (khác created_at/posted_at)."""
    require_perm(user, "warehouse.receive")
    _assert_location_scope(user, location)
    stmt = select(MaterialLot).where(MaterialLot.material_id.isnot(None), MaterialLot.quantity != 0)
    clause = _location_filter_clause(location)
    if clause is not None:
        stmt = stmt.where(clause)
    lots = db.execute(stmt).scalars().all()
    if not lots:
        raise DomainError("Không có lô nào đang tồn tại kho này để kiểm kê.")
    stamp = f"{utcnow():%y%m%d}-{new_id()[:4].upper()}"
    count = StockCount(count_id=new_id(), count_code=f"KK-{stamp}", location=location, note=note,
                       start_date=start_date, end_date=end_date,
                       status="draft", created_by=user.username, created_at=utcnow())
    db.add(count)
    db.flush()
    for lot in lots:
        db.add(StockCountLine(line_id=new_id(), count_id=count.count_id, material_id=lot.material_id,
                              lot_id=lot.lot_id, system_qty=lot.quantity, uom=lot.uom))
    record_audit(db, entity_type="stock_count", entity_id=count.count_id, action="create", actor=user,
                after={"count_code": count.count_code, "location": location, "line_count": len(lots)})
    db.commit()
    return _count_dict(db, count)


def list_counts(db: Session, status: str = None, limit: int = 1000, offset: int = 0) -> list[dict]:
    """Có phân trang (mặc định 1000, tối đa 5000). Đếm số dòng theo 1 truy vấn GROUP BY duy
    nhất thay vì 1 truy vấn COUNT riêng cho mỗi phiếu kiểm kê (N+1) như trước."""
    limit = max(1, min(limit or 1000, 5000))
    offset = max(0, offset or 0)
    stmt = select(StockCount).order_by(StockCount.created_at.desc()).limit(limit).offset(offset)
    if status:
        stmt = stmt.where(StockCount.status == status)
    counts = db.execute(stmt).scalars().all()
    count_ids = [c.count_id for c in counts]
    line_counts = dict(db.execute(
        select(StockCountLine.count_id, func.count())
        .where(StockCountLine.count_id.in_(count_ids))
        .group_by(StockCountLine.count_id)).all()) if count_ids else {}
    out = []
    for c in counts:
        n_lines = line_counts.get(c.count_id, 0)
        out.append({"count_id": c.count_id, "count_code": c.count_code, "location": c.location,
                    "start_date": c.start_date, "end_date": c.end_date,
                    "status": c.status, "created_by": c.created_by, "created_at": c.created_at,
                    "posted_by": c.posted_by, "posted_at": c.posted_at, "line_count": n_lines,
                    "approved_by": c.approved_by, "approved_at": c.approved_at,
                    "can_undo": c.status == "posted" and not c.approved_by,
                    "can_approve": c.status == "posted" and not c.approved_by})
    return out


def _get_count(db: Session, count_id: str) -> StockCount:
    count = db.get(StockCount, count_id)
    if not count:
        raise NotFoundError("Phiếu kiểm kê không tồn tại.")
    return count


def get_count(db: Session, count_id: str) -> dict:
    return _count_dict(db, _get_count(db, count_id))


def update_count_lines(db: Session, count_id: str, lines: list[dict], user: User) -> dict:
    """Điền/sửa số lượng đếm thực tế cho từng dòng — chỉ áp dụng khi phiếu còn ở trạng thái
    draft (đã post thì số liệu chốt, không sửa được nữa)."""
    require_perm(user, "warehouse.receive")
    count = _get_count(db, count_id)
    _assert_location_scope(user, count.location)
    if count.status != "draft":
        raise DomainError("Phiếu kiểm kê đã chốt (posted) — không thể sửa số liệu.")
    by_id = {l.line_id: l for l in db.execute(select(StockCountLine)
                                              .where(StockCountLine.count_id == count_id)).scalars().all()}
    for payload in lines:
        line = by_id.get(payload.get("line_id"))
        if not line:
            continue
        if "counted_qty" in payload:
            line.counted_qty = None if payload["counted_qty"] is None else float(payload["counted_qty"])
        if "note" in payload:
            line.note = payload["note"]
    db.commit()
    return _count_dict(db, count)


def post_count(db: Session, count_id: str, user: User) -> dict:
    """Chốt phiếu kiểm kê: với mỗi dòng đã điền counted_qty và có lệch so với system_qty, ghi
    1 StockMovement(movement_type="adjust") làm sổ cái rồi cập nhật thẳng MaterialLot.quantity
    = counted_qty (MaterialLot.quantity là nguồn sự thật duy nhất về tồn — xem stock_on_hand).
    "adjust" có sign=0 trong received/issued aggregation (services/warehouse.py::inventory_report)
    nên không làm lệch báo cáo nhập/xuất trong kỳ."""
    require_perm(user, "warehouse.receive")
    count = _get_count(db, count_id)
    _assert_location_scope(user, count.location)
    if count.status != "draft":
        raise DomainError("Phiếu kiểm kê này đã được chốt trước đó.")
    lines = db.execute(select(StockCountLine).where(StockCountLine.count_id == count_id)).scalars().all()
    entered = [l for l in lines if l.counted_qty is not None]
    if not entered:
        raise DomainError("Chưa nhập số liệu đếm thực tế cho dòng nào — không thể chốt phiếu.")
    adjustments = []
    for line in entered:
        diff = round(line.counted_qty - line.system_qty, 3)
        if diff == 0:
            continue
        lot = db.get(MaterialLot, line.lot_id)
        if not lot:
            continue
        _move(db, "adjust", lot, abs(diff), user,
              reason=f"Kiểm kê {count.count_code}: hệ thống {line.system_qty}{lot.uom} → thực tế {line.counted_qty}{lot.uom}",
              location_from=lot.location, location_to=lot.location)
        lot.quantity = line.counted_qty
        adjustments.append({"lot_code": lot.lot_code, "system_qty": line.system_qty,
                            "counted_qty": line.counted_qty, "variance": diff})
    count.status = "posted"
    count.posted_by = user.username
    count.posted_at = utcnow()
    record_audit(db, entity_type="stock_count", entity_id=count.count_id, action="post", actor=user,
                after={"count_code": count.count_code, "adjustments": adjustments})
    db.commit()
    return _count_dict(db, count)


def approve_count(db: Session, count_id: str, user: User) -> dict:
    """Duyệt phiếu kiểm kê đã chốt (Quản đốc phân xưởng sản xuất, hoặc bất kỳ chức danh nào
    được admin cấp quyền warehouse.count_approve qua Tài khoản — trước đây gate cứng theo
    role supervisor/qa/engineer/admin, không cấu hình được). Chỉ là xác nhận đã xem/đồng ý,
    KHÔNG đổi lại số liệu tồn kho (đã điều chỉnh xong lúc post_count). Một khi đã duyệt thì
    khóa hẳn, không cho hoàn tác nữa (xem undo_count)."""
    require_perm(user, "warehouse.count_approve")
    count = _get_count(db, count_id)
    _assert_location_scope(user, count.location)
    if count.status != "posted":
        raise DomainError("Chỉ có thể duyệt phiếu đã chốt (posted).")
    if count.approved_by:
        raise DomainError("Phiếu kiểm kê này đã được duyệt trước đó.")
    count.approved_by = user.username
    count.approved_at = utcnow()
    record_audit(db, entity_type="stock_count", entity_id=count.count_id, action="approve", actor=user,
                after={"count_code": count.count_code})
    db.commit()
    return _count_dict(db, count)


def undo_count(db: Session, count_id: str, user: User) -> dict:
    """Hoàn tác phiếu kiểm kê đã chốt (posted) nhưng CHƯA được duyệt — trả tồn kho (MaterialLot
    .quantity) về đúng system_qty đã chụp lúc tạo phiếu cho từng dòng đã điều chỉnh, ghi thêm
    1 StockMovement("adjust") đối ứng làm sổ cái, rồi đưa phiếu về draft để sửa/chốt lại. Bị
    chặn nếu đã duyệt (approved_by) — duyệt là mốc khóa chặn cuối cùng, không hoàn tác được nữa."""
    require_perm(user, "warehouse.receive")
    count = _get_count(db, count_id)
    _assert_location_scope(user, count.location)
    if count.status != "posted":
        raise DomainError("Chỉ có thể hoàn tác phiếu đã chốt (posted).")
    if count.approved_by:
        raise DomainError("Phiếu kiểm kê này đã được duyệt — không thể hoàn tác.")
    lines = db.execute(select(StockCountLine).where(StockCountLine.count_id == count_id)).scalars().all()
    reverted = []
    for line in lines:
        if line.counted_qty is None:
            continue
        diff = round(line.counted_qty - line.system_qty, 3)
        if diff == 0:
            continue
        lot = db.get(MaterialLot, line.lot_id)
        if not lot:
            continue
        _move(db, "adjust", lot, abs(diff), user,
              reason=f"Hoàn tác kiểm kê {count.count_code}: thực tế {line.counted_qty}{lot.uom} → hệ thống {line.system_qty}{lot.uom}",
              location_from=lot.location, location_to=lot.location)
        lot.quantity = line.system_qty
        reverted.append({"lot_code": lot.lot_code, "restored_qty": line.system_qty})
    count.status = "draft"
    count.posted_by = None
    count.posted_at = None
    record_audit(db, entity_type="stock_count", entity_id=count.count_id, action="undo", actor=user,
                before={"count_code": count.count_code}, after={"reverted": reverted})
    db.commit()
    return _count_dict(db, count)
