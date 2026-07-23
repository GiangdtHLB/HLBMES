"""Nghiệp vụ kho: nhập/xuất/hoàn/sang ngang + tồn/thẻ kho/hạn dùng/báo cáo."""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import GenealogyRelation, LotStatus, Role, new_id, utcnow
from ..errors import DomainError, NotFoundError, PermissionError_
from ..models.brewing import (BottleMaterialUsage, BottleRecord, BrewBatch, BrewMaterialUsage, BrewOrder,
                              BrewRecord, FilterMasterOrder, FilterMaterialUsage, FilterRecord)
from ..models.master import Material
from ..models.materials import GenealogyEdge, MaterialLot
from ..models.warehouse import MaterialRequest, MaterialRequestLine, StockCount, StockCountLine, StockMovement
from ..security import User, has_scope, require_perm, require_role, require_scope
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


def receive(db: Session, payload: dict, user: User) -> dict:
    """Nhập kho: tạo lô mới hoặc cộng vào lô hiện có (cùng vật tư + cùng mã lô)."""
    require_role(user, Role.OPERATOR, Role.SUPERVISOR)
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
        if received_dt < now - timedelta(days=15):
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
        if lot.status == LotStatus.CONSUMED.value:
            lot.status = LotStatus.AVAILABLE.value
    else:
        _assert_location_scope(user, payload.get("location", "Kho công ty"))
        expiry = payload.get("expiry")
        lot = MaterialLot(lot_id=new_id(), lot_code=lot_code or _next_lot_code(db, year), lot_year=year,
                          material_id=material_id, lot_type=payload.get("lot_type", "material"),
                          supplier_lot=payload.get("supplier_lot"), supplier_id=payload.get("supplier_id"),
                          unit_price=payload.get("unit_price"),
                          quantity=qty, uom=payload.get("uom", "kg"), status=LotStatus.AVAILABLE.value,
                          expiry=datetime.fromisoformat(expiry) if isinstance(expiry, str) else expiry,
                          location=payload.get("location", "Kho công ty"), created_at=received_dt)
        db.add(lot)
        db.flush()
        # Nguyên liệu có gán nhóm chỉ tiêu bắt buộc → lô mới phải HOLD chờ khai báo + KCS duyệt
        # trước khi được coi là đã nhập kho nhà máy chính thức (không áp dụng khi cộng dồn lô cũ).
        if lot.material_id and required_params_for_material(db, lot.material_id):
            lot.status = LotStatus.ON_HOLD.value
    _move(db, "receipt", lot, qty, user, ts=received_dt, location_to=lot.location,
          reason=payload.get("reason"), ref_doc=payload.get("ref_doc"))
    record_audit(db, entity_type="lot", entity_id=lot.lot_id, action="receipt", actor=user,
                 after={"lot_code": lot.lot_code, "quantity": qty})
    db.commit()
    return {"lot_id": lot.lot_id, "lot_code": lot.lot_code, "on_hand": lot.quantity, "uom": lot.uom,
            "status": lot.status}


def return_stock(db: Session, lot_id: str, quantity: float, user: User, reason: str = None) -> dict:
    """Nhập hoàn kho: trả vật tư chưa dùng về lô."""
    require_role(user, Role.OPERATOR, Role.SUPERVISOR)
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
          reason: str = None, ref_doc: str = None) -> dict:
    """Xuất kho tự do (không qua phiếu đề nghị) hoặc trả nhà cung cấp (mode="tra_ncc")."""
    require_role(user, Role.OPERATOR, Role.SUPERVISOR)
    lot = _lot(db, lot_id)
    _assert_location_scope(user, lot.location)
    if lot.status == LotStatus.ON_HOLD.value:
        raise DomainError(f"Lô {lot.lot_code} đang HOLD, không được xuất.")
    if quantity <= 0 or quantity > lot.quantity:
        raise DomainError(f"Số lượng xuất không hợp lệ (tồn {lot.quantity} {lot.uom}).")
    lot.quantity -= quantity
    if lot.quantity == 0:
        lot.status = LotStatus.CONSUMED.value
    mv = _move(db, "issue", lot, quantity, user, location_from=lot.location, mode=mode,
              reason=reason, ref_doc=ref_doc)
    record_audit(db, entity_type="lot", entity_id=lot.lot_id, action="issue", actor=user,
                 after={"quantity": quantity, "mode": mode})
    db.commit()
    db.refresh(mv)
    return {"lot_id": lot.lot_id, "on_hand": lot.quantity, "movement_id": mv.movement_id}


def transfer(db: Session, lot_id: str, quantity: float, location_to: str, user: User,
             reason: str = None, mode: str = "sang_ngang") -> dict:
    """Chuyển vị trí (không đổi tổng tồn). `mode` phân biệt nguồn gốc giao dịch trong lịch sử:
    "xuat_theo_de_nghi" (công ty→phân xưởng qua đề nghị) | "dieu_chuyen" (phân xưởng→công ty thủ công)."""
    require_role(user, Role.OPERATOR, Role.SUPERVISOR)
    lot = _lot(db, lot_id)
    _assert_transfer_scope(user, lot.location, location_to)
    if lot.status == LotStatus.ON_HOLD.value:
        raise DomainError(f"Lô {lot.lot_code} đang HOLD (chờ khai báo/duyệt chỉ tiêu chất lượng), "
                          "không được chuyển kho.")
    loc_from = lot.location
    lot.location = location_to
    mv = _move(db, "transfer", lot, quantity, user, location_from=loc_from, location_to=location_to,
              mode=mode, reason=reason)
    record_audit(db, entity_type="lot", entity_id=lot.lot_id, action="transfer", actor=user,
                 after={"from": loc_from, "to": location_to})
    db.commit()
    db.refresh(mv)
    return {"lot_id": lot.lot_id, "location": lot.location, "movement_id": mv.movement_id}


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
    """Xem tồn kho: tổng tồn theo vật tư (lọc theo kho nếu truyền `location`)."""
    stmt = (
        select(MaterialLot.material_id, func.sum(MaterialLot.quantity), MaterialLot.uom)
        .where(MaterialLot.material_id.isnot(None))
    )
    clause = _location_filter_clause(location)
    if clause is not None:
        stmt = stmt.where(clause)
    rows = db.execute(stmt.group_by(MaterialLot.material_id, MaterialLot.uom)).all()
    out = []
    for material_id, total, uom in rows:
        mat = db.get(Material, material_id)
        on_hand = round(total or 0, 3)
        stock_min = mat.stock_min if mat else None
        out.append({"material_id": material_id, "material_code": mat.code if mat else material_id,
                    "material_name": mat.name if mat else "", "on_hand": on_hand,
                    "uom": uom, "category": mat.category if mat else None,
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


def inventory_report(db: Session, days: int = 30, location: str = None) -> list[dict]:
    """BC nhập-xuất-tồn trong kỳ: tổng nhập, tổng xuất, tồn hiện tại theo vật tư
    (lọc theo kho nếu truyền `location`: nhập tính theo location_to, xuất theo location_from)."""
    since = utcnow() - timedelta(days=days)
    on_hand = {r["material_id"]: r for r in stock_on_hand(db, location)}
    moves = db.execute(select(StockMovement).where(StockMovement.ts >= since)).scalars().all()
    workshop = _is_workshop_location(location) if location else None
    agg = {}
    for m in moves:
        if location:
            loc = m.location_to if m.movement_type in ("receipt", "return") else m.location_from
            if _is_workshop_location(loc) != workshop:
                continue
        a = agg.setdefault(m.material_id, {"receipt": 0.0, "issue": 0.0, "return": 0.0})
        if m.movement_type in a:
            a[m.movement_type] += m.quantity
    out = []
    for mid, oh in on_hand.items():
        a = agg.get(mid, {"receipt": 0.0, "issue": 0.0, "return": 0.0})
        out.append({**oh, "received": round(a["receipt"] + a["return"], 3),
                    "issued": round(a["issue"], 3)})
    return out


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
    """Tổng tồn của 1 vật tư tại Kho công ty (dùng để chặn đề nghị vượt tồn)."""
    clause = _location_filter_clause("Kho công ty")
    total = db.execute(
        select(func.sum(MaterialLot.quantity)).where(MaterialLot.material_id == material_id, clause)
    ).scalar()
    return total or 0.0


def _aggregate_source_material_lines(db: Session, source_type: str, source_id: str) -> list[dict]:
    """Nhu cầu NVL của 1 Lệnh nấu/Lệnh lọc lớn, gộp theo vật tư (cộng dồn nếu 1 vật tư xuất
    hiện nhiều dòng/nhiều lệnh nhỏ) — dùng để tự động điền sẵn phiếu đề nghị nhận kho, mirror
    dữ liệu định mức đã có sẵn ở BrewOrderMaterialLine/FilterOrderMaterialLine (không tính lại
    từ công thức, dùng đúng con số đã "chốt" lúc lập lệnh)."""
    agg: dict[str, dict] = {}

    def _add(material_id: str, material_name: str, uom: str, qty: float) -> None:
        if not material_id or not qty:
            return
        a = agg.setdefault(material_id, {"material_id": material_id, "material_name": material_name,
                                         "uom": uom, "quantity": 0.0})
        a["quantity"] += qty

    if source_type == "brew_order":
        from . import brew_order as brew_order_svc
        order = brew_order_svc.get_order(db, source_id)
        for l in order["lines"]:
            if l["is_header"] or not l["material_id"]:
                continue
            _add(l["material_id"], l["material_name"], l["uom"], l["qty_total"] or 0.0)
    elif source_type == "filter_master_order":
        from . import filter_order as filter_order_svc
        master = filter_order_svc.get_master_order(db, source_id)
        for child in master["children"]:
            for l in child["lines"]:
                _add(l["material_id"], l["material_name"], l["uom"], l["quantity"] or 0.0)
    else:
        raise DomainError(f"Loại nguồn '{source_type}' không hợp lệ (chỉ nhận brew_order|filter_master_order).")

    out = []
    for a in agg.values():
        mat = db.get(Material, a["material_id"])
        out.append({"material_id": a["material_id"],
                    "material_code": mat.code if mat else None,
                    "material_name": (mat.name if mat else None) or a["material_name"],
                    "uom": a["uom"] or (mat.uom if mat else "kg"),
                    "quantity": round(a["quantity"], 3)})
    return sorted(out, key=lambda x: x["material_code"] or "")


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


def list_requests(db: Session, status: str = None) -> list[dict]:
    """Toàn bộ phiếu kèm dòng. `status`: chỉ trả phiếu có ít nhất 1 dòng ở trạng thái đó."""
    headers = db.execute(select(MaterialRequest).order_by(MaterialRequest.requested_at.desc())).scalars().all()
    all_lines = db.execute(select(MaterialRequestLine)).scalars().all()
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
    thể đã hết hoặc lô mới đã nhập thêm."""
    clause = _location_filter_clause("Kho công ty")
    candidates = db.execute(
        select(MaterialLot).where(MaterialLot.material_id == material_id, MaterialLot.quantity > 0, clause)
        .order_by(MaterialLot.created_at)
    ).scalars().all()
    return bool(candidates) and candidates[0].lot_id == lot_id


def is_oldest_workshop_lot(db: Session, material_id: str, lot_id: str) -> bool:
    """Lô đang chọn có phải lô cũ nhất (FIFO) hiện có tại Kho phân xưởng của vật tư đó hay
    không — mirror _is_oldest_company_lot, dùng cho NVL dùng thật ở mẻ nấu/mẻ lọc/mẻ chiết
    (xem BrewMaterialUsage/FilterMaterialUsage/BottleMaterialUsage.fifo_ok). Gọi NGAY TRƯỚC
    LÚC issue() trừ kho — so sánh live sau khi đã xuất sẽ sai lệch vì lô có thể đã hết."""
    clause = _location_filter_clause("Kho phân xưởng")
    candidates = db.execute(
        select(MaterialLot).where(MaterialLot.material_id == material_id, MaterialLot.quantity > 0, clause)
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
                      reason=f"Xuất theo đề nghị {req.request_code} (dòng {line.seq + 1})")
    line.status = "fulfilled"
    line.fulfilled_lot_id = lot_id
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
                          reason=f"Xuất theo đề nghị {req.request_code} (dòng {line.seq + 1}, duyệt cả phiếu)")
        line.status = "fulfilled"
        line.fulfilled_lot_id = lot.lot_id
        line.fulfilled_qty = line.quantity
        line.fulfilled_by = user.username
        line.fulfilled_at = utcnow()
        line.fifo_ok = fifo_ok
        record_audit(db, entity_type="material_request_line", entity_id=line.line_id, action="fulfill",
                     actor=user, after={"lot_id": lot.lot_id, "quantity": line.quantity, "location_to": location_to})
        db.commit()
        fulfilled.append({"line_id": line.line_id, "material_id": line.material_id,
                          "lot_id": lot.lot_id, "quantity": line.quantity, "location": result["location"]})
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

def transfer_to_company(db: Session, lot_id: str, quantity: float, user: User, reason: str = None) -> dict:
    """Điều chuyển lô đang ở Kho phân xưởng về lại Kho công ty (chiều ngược của xuất theo đề nghị)."""
    lot = _lot(db, lot_id)
    if not _is_workshop_location(lot.location):
        raise DomainError(f"Lô {lot.lot_code} không ở Kho phân xưởng — chỉ điều chuyển được lô đang ở kho phân xưởng.")
    return transfer(db, lot_id, quantity, "Kho công ty", user, reason=reason, mode="dieu_chuyen")


def return_to_supplier(db: Session, lot_id: str, quantity: float, user: User, reason: str) -> dict:
    """Xuất trả nhà cung cấp: lô hỏng/không đạt rời khỏi hệ thống hẳn — bắt buộc có lý do."""
    if not reason or not reason.strip():
        raise DomainError("Phải nhập lý do trả nhà cung cấp (vd: hàng hỏng, không đạt chỉ tiêu).")
    return issue(db, lot_id, quantity, user, mode="tra_ncc", reason=reason)


def undo_issue(db: Session, movement_id: str, user: User) -> dict:
    """Hoàn lại 1 giao dịch xuất tự do (mode="tu_do") — không áp dụng cho trả NCC (hàng đã rời
    kho thật sự). Chặn hoàn 2 lần bằng cờ `reversed`."""
    require_role(user, Role.OPERATOR, Role.SUPERVISOR)
    mv = db.get(StockMovement, movement_id)
    if not mv:
        raise NotFoundError("Giao dịch không tồn tại.")
    if mv.movement_type != "issue" or mv.mode != "tu_do":
        raise DomainError("Chỉ hoàn lại được giao dịch xuất tự do (không áp dụng cho trả NCC/xuất theo đề nghị).")
    if mv.reversed:
        raise DomainError("Giao dịch này đã được hoàn lại trước đó.")
    result = return_stock(db, mv.lot_id, mv.quantity, user, reason=f"Hoàn lại xuất tự do (giao dịch {mv.movement_id})")
    mv.reversed = True
    new_mv = db.get(StockMovement, result["movement_id"])
    new_mv.reversal_of = mv.movement_id
    record_audit(db, entity_type="stock_movement", entity_id=mv.movement_id, action="undo_issue", actor=user)
    db.commit()
    return result


def list_movements(db: Session, movement_type: str = None, mode: str = None, limit: int = 200) -> list[StockMovement]:
    """Sổ giao dịch kho — dùng chung cho lịch sử xuất tự do / điều chuyển / trả NCC / xuất theo đề nghị."""
    stmt = select(StockMovement).order_by(StockMovement.ts.desc()).limit(limit)
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
    trúc rõ ràng theo công đoạn/mẻ, không phải suy từ chuỗi lý do."""
    rows = []
    for u, batch_code, brew_code in db.execute(
            select(BrewMaterialUsage, BrewBatch.batch_code, BrewRecord.brew_code)
            .join(BrewBatch, BrewMaterialUsage.batch_id == BrewBatch.batch_id)
            .join(BrewRecord, BrewBatch.brew_id == BrewRecord.brew_id)).all():
        rows.append({"usage_id": u.usage_id, "ts": u.created_at, "stage": "Nấu",
                    "batch_label": f"Mẻ {batch_code} (mã nấu {brew_code})",
                    "material_name": u.material_name, "lot_code": u.lot_pm,
                    "quantity": u.quantity, "uom": u.uom, "movement_id": u.movement_id})
    for u, filter_code in db.execute(
            select(FilterMaterialUsage, FilterRecord.filter_code)
            .join(FilterRecord, FilterMaterialUsage.filter_id == FilterRecord.filter_id)).all():
        rows.append({"usage_id": u.usage_id, "ts": u.created_at, "stage": "Lọc",
                    "batch_label": f"Mẻ lọc {filter_code}",
                    "material_name": u.material_name, "lot_code": u.lot_pm,
                    "quantity": u.quantity, "uom": u.uom, "movement_id": u.movement_id})
    for u, bottle_code in db.execute(
            select(BottleMaterialUsage, BottleRecord.bottle_code)
            .join(BottleRecord, BottleMaterialUsage.bottle_id == BottleRecord.bottle_id)).all():
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
            "note": count.note, "status": count.status, "created_by": count.created_by,
            "created_at": count.created_at, "posted_by": count.posted_by, "posted_at": count.posted_at,
            "approved_by": count.approved_by, "approved_at": count.approved_at,
            "can_undo": count.status == "posted" and not count.approved_by,
            "can_approve": count.status == "posted" and not count.approved_by,
            "lines": line_dicts,
            "variance_count": sum(1 for l in line_dicts if l["variance"])}


def create_count(db: Session, location: Optional[str], user: User, note: str = None) -> dict:
    """Tạo phiếu kiểm kê: chụp (snapshot) tồn hệ thống hiện tại của mọi lô còn tồn tại 1 kho
    (hoặc toàn bộ nếu không lọc theo kho) thành các dòng StockCountLine — nhân viên điền
    counted_qty sau, không sửa được system_qty (đây là mốc đối chiếu tại thời điểm tạo phiếu)."""
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


def list_counts(db: Session, status: str = None) -> list[dict]:
    stmt = select(StockCount).order_by(StockCount.created_at.desc())
    if status:
        stmt = stmt.where(StockCount.status == status)
    counts = db.execute(stmt).scalars().all()
    out = []
    for c in counts:
        n_lines = db.execute(select(func.count()).select_from(StockCountLine)
                             .where(StockCountLine.count_id == c.count_id)).scalar_one()
        out.append({"count_id": c.count_id, "count_code": c.count_code, "location": c.location,
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
    """Duyệt phiếu kiểm kê đã chốt (giám đốc nhà máy trở lên — role supervisor/qa/engineer/
    admin, không phải operator thường). Chỉ là xác nhận đã xem/đồng ý, KHÔNG đổi lại số liệu
    tồn kho (đã điều chỉnh xong lúc post_count). Một khi đã duyệt thì khóa hẳn, không cho
    hoàn tác nữa (xem undo_count)."""
    require_role(user, Role.SUPERVISOR, Role.QA, Role.ENGINEER, Role.ADMIN)
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
