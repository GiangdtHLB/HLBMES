"""Cấp phát nguyên liệu (dispense) + backflush (tài liệu §7.4, §7.6).

- dispense: cấp liệu cho mẻ theo lô cụ thể HOẶC tự chọn lô theo FEFO (hết hạn trước
  xuất trước), tái dùng batches.consume_lot (trừ tồn + genealogy + chặn vượt định mức),
  bổ sung: chặn lô hết hạn, tách nhu cầu qua nhiều lô.
- backflush: tự khấu trừ NVL theo định mức BOM × tỉ lệ sản lượng đã sản xuất, trừ phần
  đã tiêu thụ trước đó (tránh trừ trùng), tự chọn lô FEFO.
"""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import LotStatus, Role, new_id, utcnow
from ..errors import DomainError, NotFoundError
from ..models.batches import BatchExecution
from ..models.master import Material
from ..models.materials import GenealogyEdge, MaterialLot
from ..models.materials_ext import Dispense, DispenseLine
from ..security import User, require_role
from . import batches as batch_svc
from . import bom
from . import warehouse as warehouse_svc


def _is_expired(lot: MaterialLot) -> bool:
    if not lot.expiry:
        return False
    exp = lot.expiry
    now = utcnow()
    if exp.tzinfo is None:
        now = now.replace(tzinfo=None)
    return exp < now


def _fefo_lots(db: Session, material_code: str) -> list:
    """Các lô khả dụng (available/released — mirror warehouse.py::stock_on_hand, KHÔNG chỉ
    "available") của một material_code, sắp theo FEFO (hết hạn trước) rồi FIFO — nếu
    `material_code` thực ra là mã 1 Nhóm vật tư thay thế (dòng BOM khai theo nhóm, không có mã
    vật tư cụ thể — xem bom.py::codes_for_dispense), gộp lô của MỌI thành viên rồi mới sắp
    chung 1 hàng đợi FEFO (thủ kho xuất mã thành viên nào cũng hợp lệ)."""
    real_codes = bom.codes_for_dispense(db, material_code)
    mats = db.execute(select(Material).where(Material.code.in_(real_codes))).scalars().all()
    material_ids = [m.material_id for m in mats]
    if not material_ids:
        return []
    lots = db.execute(select(MaterialLot).where(
        MaterialLot.material_id.in_(material_ids),
        MaterialLot.status.in_([LotStatus.AVAILABLE.value, LotStatus.RELEASED.value]),
        MaterialLot.quantity > 0)).scalars().all()
    lots = [l for l in lots if not _is_expired(l)]
    # expiry None → cuối hàng đợi (giá trị lớn); cùng expiry → FIFO theo created_at
    far = utcnow().replace(tzinfo=None) + timedelta(days=36500)

    def key(l):
        e = l.expiry
        if e is None:
            e = far
        elif e.tzinfo is not None:
            e = e.replace(tzinfo=None)
        c = l.created_at
        if c is not None and c.tzinfo is not None:
            c = c.replace(tzinfo=None)
        return (e, c)
    return sorted(lots, key=key)


def _workshop_fefo_lots(db: Session, material_code: str) -> list:
    """Như _fefo_lots nhưng chỉ lấy lô ở Kho phân xưởng — nơi NVL thật sự cấp cho mẻ nấu
    (tài liệu §9.0: "nguyên liệu phân bổ vào mẻ nấu ... luôn lấy từ Kho phân xưởng")."""
    return [l for l in _fefo_lots(db, material_code) if warehouse_svc._is_workshop_location(l.location)]


def _effective_qty(lot: MaterialLot, reserved: dict) -> float:
    """Tồn CÒN LẠI của 1 lô sau khi trừ phần đã "giữ chỗ" bởi các dòng KHÁC trong CÙNG 1 lần
    gọi dispense()/backflush() (chưa commit vào DB — 2 pha lập kế hoạch rồi mới thực thi, xem
    _plan_consume) — tránh 2 dòng trong cùng 1 phiếu cùng tưởng còn nguyên 1 lô rồi tính trùng."""
    return round(lot.quantity - reserved.get(lot.lot_id, 0.0), 6)


def _is_fifo_choice(db: Session, material_code: str, lot_id: str, reserved: dict) -> bool:
    """1 lô được coi là "đúng FIFO/FEFO" nếu KHÔNG có lô nào xếp TRƯỚC nó (theo FEFO, Kho phân
    xưởng) mà còn tồn > 0 (SAU khi trừ phần đã giữ chỗ bởi dòng khác cùng phiếu) bị bỏ qua. Lô
    không nằm trong danh sách FEFO hợp lệ (khác Kho phân xưởng / đã hết hạn / khác vật tư) luôn
    coi là lệch."""
    order = _workshop_fefo_lots(db, material_code)
    idx = next((i for i, l in enumerate(order) if l.lot_id == lot_id), None)
    if idx is None:
        return False
    return not any(_effective_qty(l, reserved) > 1e-9 for l in order[:idx])


def _plan_consume(db: Session, material_code: str, qty: float, picked_lot_id: str = None,
                  reason: str = None, reserved: dict = None) -> tuple:
    """Lập kế hoạch cấp liệu cho `qty` của material_code — CHỈ TÍNH, KHÔNG trừ tồn (all-or-
    nothing: raise NGAY nếu không đủ 100%, tránh trừ 1 phần rồi mới báo thiếu). Nếu chỉ định lot
    mà lot đó KHÔNG phải lô FIFO/FEFO gợi ý (còn lô xếp trước còn tồn) thì bắt buộc có `reason`.
    `reserved` (dict lot_id -> đã giữ chỗ) dùng CHUNG cho mọi dòng trong 1 lần gọi dispense()/
    backflush() — CẬP NHẬT TRỰC TIẾP (mutate) để dòng sau thấy đúng phần lô mà dòng trước đã
    dùng, dù chưa commit DB thật. Trả về (plan, fifo_ok) — plan: list[(lot, take)] để
    _execute_plan thực thi thật khi đã chắc chắn đủ."""
    reserved = reserved if reserved is not None else {}
    remaining = round(qty, 6)
    plan = []
    fifo_ok = True
    if picked_lot_id:
        lot = db.get(MaterialLot, picked_lot_id)
        if not lot:
            raise NotFoundError("Lô vật tư không tồn tại.")
        if _is_expired(lot):
            raise DomainError(f"Lô {lot.lot_code} đã HẾT HẠN — không được cấp.")
        fifo_ok = _is_fifo_choice(db, material_code, lot.lot_id, reserved)
        if not fifo_ok and not (reason or "").strip():
            raise DomainError(
                f"Lô {lot.lot_code} không phải lô FIFO/FEFO gợi ý cho {material_code} — "
                "bắt buộc nhập lý do chọn lô khác.")
        take = min(remaining, max(_effective_qty(lot, reserved), 0.0))
        if take > 0:
            plan.append((lot, take))
            reserved[lot.lot_id] = reserved.get(lot.lot_id, 0.0) + take
        remaining = round(remaining - take, 6)
    else:
        for lot in _fefo_lots(db, material_code):
            if remaining <= 1e-9:
                break
            take = min(remaining, max(_effective_qty(lot, reserved), 0.0))
            if take <= 0:
                continue
            plan.append((lot, take))
            reserved[lot.lot_id] = reserved.get(lot.lot_id, 0.0) + take
            remaining = round(remaining - take, 6)
    if remaining > 1e-6:
        raise DomainError(
            f"Không đủ lô khả dụng (còn hạn) cho {material_code}: thiếu {round(remaining,3)} — "
            "không cấp liệu (all-or-nothing).")
    return plan, fifo_ok


def _execute_plan(db: Session, batch: BatchExecution, material_code: str, plan: list, user: User,
                  allow_over: bool, fifo_ok: bool, reason: str = None) -> list:
    """Thực thi thật 1 kế hoạch đã lập (_plan_consume) — trừ tồn + genealogy qua consume_lot.

    Ghi `material_code` THẬT theo từng lô (bom.material_code_for_lot), KHÔNG dùng thẳng
    `material_code` truyền vào — khi dòng BOM khai theo Nhóm vật tư thay thế, `material_code`
    truyền vào là mã NHÓM (không xuất kho trực tiếp được), còn lô thực tế tiêu thụ luôn thuộc
    1 mã vật tư CỤ THỂ (xem _fefo_lots) — ghi đúng mã đó để sổ sách/lịch sử cấp liệu chính xác."""
    lines = []
    for lot, take in plan:
        batch_svc.consume_lot(db, batch.batch_id, lot.lot_id, take, user, allow_over)
        lines.append({"material_code": bom.material_code_for_lot(db, lot), "lot_id": lot.lot_id,
                      "lot_code": lot.lot_code, "quantity": take, "uom": lot.uom,
                      "fifo_ok": fifo_ok, "reason": reason})
    return lines


def suggest_dispense(db: Session, batch_id: str) -> dict:
    """Xem trước gợi ý cấp liệu cho 1 mẻ: với mỗi vật tư còn THIẾU theo Định mức (BOM, đã scale
    theo SL kế hoạch của mẻ — cùng phép tính hiển thị ở bảng Định mức↔Thực tế), tự chọn lô theo
    FEFO ở Kho phân xưởng — CHỈ TÍNH, không trừ tồn. `alternatives` liệt kê MỌI lô khả dụng
    (Kho phân xưởng, còn hạn) của vật tư đó để người dùng có thể chọn lô KHÁC lô FIFO gợi ý
    (kèm lý do, xem _plan_consume). Người dùng xem bảng này rồi bấm "Áp dụng" sẽ gọi lại
    dispense() với đúng lô/số lượng (có thể đã sửa) lấy từ đây."""
    batch = db.get(BatchExecution, batch_id)
    if not batch:
        raise NotFoundError("Batch không tồn tại.")
    cmp = bom.compare_batch(db, batch)
    # Tồn hiện tại theo material_code THẬT ở mỗi kho — dùng để hiển thị tham khảo "Tồn kho công
    # ty"/"Tồn kho phân xưởng" cạnh gợi ý (khác `alternatives`/`picks` vốn CHỈ xét Kho phân
    # xưởng — nơi duy nhất được cấp liệu thật, xem _workshop_fefo_lots). Vật tư khai theo Nhóm
    # thay thế (bom.codes_for_dispense) cộng dồn tồn của MỌI mã thành viên.
    company_stock = {r["material_code"]: r["on_hand"] for r in warehouse_svc.stock_on_hand(db, "Kho công ty")}
    workshop_stock = {r["material_code"]: r["on_hand"] for r in warehouse_svc.stock_on_hand(db, "Kho phân xưởng")}
    name_by_code = {m.code: m.name for m in db.execute(select(Material)).scalars().all()}
    lines = []
    for l in cmp["lines"]:
        need = round(-l["diff"], 3) if l["diff"] < 0 else 0.0
        if need <= 1e-6:
            continue
        member_codes = l.get("match_codes") or [l["material_code"]]
        if l.get("is_group") and len(member_codes) > 1:
            # Nhóm "dùng nhiều mã cùng lúc" khai CHUNG 1 định mức, không tách sẵn theo từng
            # thành viên (khác dòng member_qty, đã tách sẵn ở compare_batch) — hiện THÀNH TỪNG
            # DÒNG theo mã thành viên để người dùng tự do phân bổ số lượng/lô qua từng mã, vẫn
            # gợi ý trước theo FIFO chung (gộp tồn mọi thành viên rồi chia theo thứ tự FEFO) —
            # tổng số lượng qua các dòng này không được vượt định mức chung (chặn thật ở
            # consume_lot/ceiling_for_material, không phải ở đây)."""
            combined_lots = _workshop_fefo_lots(db, l["material_code"])
            picks_by_member = {c: [] for c in member_codes}
            remaining = need
            for lot in combined_lots:
                if remaining <= 1e-9:
                    break
                take = min(remaining, lot.quantity)
                if take <= 0:
                    continue
                mcode = bom.material_code_for_lot(db, lot)
                picks_by_member.setdefault(mcode, []).append(
                    {"lot_id": lot.lot_id, "lot_code": lot.lot_code, "quantity": round(take, 6),
                     "uom": lot.uom, "expiry": lot.expiry.isoformat() if lot.expiry else None})
                remaining = round(remaining - take, 6)
            group_shortfall = round(remaining, 3) if remaining > 1e-6 else 0.0
            for mcode in member_codes:
                member_lots = _fefo_lots(db, mcode)
                alternatives = [{"lot_id": lot.lot_id, "lot_code": lot.lot_code, "quantity": round(lot.quantity, 6),
                                "uom": lot.uom, "expiry": lot.expiry.isoformat() if lot.expiry else None}
                               for lot in member_lots]
                lines.append({"material_code": mcode, "material_name": name_by_code.get(mcode),
                             "uom": l["uom"], "planned": l["planned"],
                             "stock_company": round(company_stock.get(mcode, 0.0), 3),
                             "stock_workshop": round(workshop_stock.get(mcode, 0.0), 3),
                             "need": need, "picks": picks_by_member.get(mcode, []), "alternatives": alternatives,
                             "group_code": l["material_code"], "shortfall": group_shortfall})
            continue
        real_codes = bom.codes_for_dispense(db, l["material_code"])
        stock_company = round(sum(company_stock.get(c, 0.0) for c in real_codes), 3)
        stock_workshop = round(sum(workshop_stock.get(c, 0.0) for c in real_codes), 3)
        fefo_lots = _workshop_fefo_lots(db, l["material_code"])
        alternatives = [{"lot_id": lot.lot_id, "lot_code": lot.lot_code, "quantity": round(lot.quantity, 6),
                        "uom": lot.uom, "expiry": lot.expiry.isoformat() if lot.expiry else None}
                       for lot in fefo_lots]
        picks = []
        remaining = need
        for lot in fefo_lots:
            if remaining <= 1e-9:
                break
            take = min(remaining, lot.quantity)
            if take <= 0:
                continue
            picks.append({"lot_id": lot.lot_id, "lot_code": lot.lot_code,
                         "quantity": round(take, 6), "uom": lot.uom,
                         "expiry": lot.expiry.isoformat() if lot.expiry else None})
            remaining = round(remaining - take, 6)
        lines.append({"material_code": l["material_code"], "material_name": l.get("material_name"),
                     "uom": l["uom"], "planned": l["planned"],
                     "stock_company": stock_company, "stock_workshop": stock_workshop,
                     "need": need, "picks": picks, "alternatives": alternatives,
                     "shortfall": round(remaining, 3) if remaining > 1e-6 else 0.0})
    return {"batch_id": batch_id, "batch_code": batch.batch_code, "lines": lines}


def dispense(db: Session, batch_id: str, lines_in: list, user: User, note: str = None) -> dict:
    """Cấp liệu cho mẻ. lines_in = [{material_code, quantity, lot_id?, reason?}]. All-or-nothing:
    LẬP KẾ HOẠCH cho MỌI dòng trước (không trừ tồn) — nếu BẤT KỲ dòng nào không đủ tồn (hoặc
    chọn lô lệch FIFO mà thiếu lý do) thì KHÔNG cấp liệu dòng nào cả, báo lỗi gộp ngay."""
    require_role(user, Role.OPERATOR, Role.SUPERVISOR, Role.ENGINEER)
    batch = db.get(BatchExecution, batch_id)
    if not batch:
        raise NotFoundError("Batch không tồn tại.")
    if not lines_in:
        raise DomainError("Phiếu cấp liệu rỗng.")
    planned, errors, reserved = [], [], {}
    for ln in lines_in:
        code = ln.get("material_code")
        qty = float(ln.get("quantity") or 0)
        if not code or qty <= 0:
            continue
        try:
            plan, fifo_ok = _plan_consume(db, code, qty, picked_lot_id=ln.get("lot_id"),
                                          reason=ln.get("reason"), reserved=reserved)
            planned.append((code, plan, bool(ln.get("allow_over")), fifo_ok, ln.get("reason")))
        except DomainError as e:
            errors.append(str(e))
    if errors:
        raise DomainError("Không cấp liệu — " + "; ".join(errors))
    disp = Dispense(dispense_id=new_id(),
                    dispense_code=f"DISP-{utcnow():%Y%m%d}-{new_id()[:5].upper()}",
                    batch_id=batch_id, mode="dispense", status="issued",
                    note=note, created_by=user.username, created_at=utcnow())
    db.add(disp)
    db.flush()
    all_lines = []
    for code, plan, allow_over, fifo_ok, reason in planned:
        rows = _execute_plan(db, batch, code, plan, user, allow_over, fifo_ok, reason)
        for r in rows:
            db.add(DispenseLine(line_id=new_id(), dispense_id=disp.dispense_id, **r))
            all_lines.append(r)
    record_audit(db, entity_type="batch", entity_id=batch_id, action="dispense", actor=user,
                 after={"dispense_code": disp.dispense_code, "lines": len(all_lines)})
    db.commit()
    return {"dispense_code": disp.dispense_code, "lines": all_lines,
            "bom": bom.compare_batch(db, batch)}


def backflush(db: Session, batch_id: str, produced_qty: float, user: User) -> dict:
    """Tự khấu trừ NVL theo định mức BOM cho `produced_qty` đã sản xuất.

    standard(material) = qty_BOM × (produced_qty / base_qty). Trừ phần đã consume trước đó."""
    require_role(user, Role.OPERATOR, Role.SUPERVISOR, Role.ENGINEER)
    batch = db.get(BatchExecution, batch_id)
    if not batch:
        raise NotFoundError("Batch không tồn tại.")
    snap = batch.recipe_snapshot or {}
    base = snap.get("base_qty") or 0
    if not base:
        raise DomainError("Recipe snapshot thiếu base_qty — không backflush được.")
    factor = produced_qty / base
    already = bom.actual_consumed(db, batch_id)
    disp = Dispense(dispense_id=new_id(),
                    dispense_code=f"BKF-{utcnow():%Y%m%d}-{new_id()[:5].upper()}",
                    batch_id=batch_id, mode="backflush", status="issued",
                    note=f"Backflush cho {produced_qty} {batch.uom}",
                    created_by=user.username, created_at=utcnow())
    db.add(disp)
    db.flush()
    all_lines, skipped, reserved = [], [], {}
    # Gộp định mức theo material_code (dòng khai theo Nhóm vật tư thay thế được chuẩn hoá về
    # material_code cụ thể/mã nhóm qua bom._expand_materials, xem compare_batch cùng module).
    req_by, uom_by, match_by = {}, {}, {}
    for m in bom._expand_materials(db, snap.get("materials"), brew_order_id=batch.order_id):
        code = m.get("material_code")
        req_by[code] = req_by.get(code, 0.0) + (m.get("qty", 0) or 0) * factor
        uom_by.setdefault(code, m.get("uom"))
        match_by.setdefault(code, m.get("match_codes") or {code})
    for code, std in req_by.items():
        already_code = sum(already.get(c, 0.0) for c in match_by[code])
        need = round(std - already_code, 3)
        if need <= 1e-6:
            continue
        try:
            # Backflush vẫn TÔN TRỌNG trần định mức BOM (không tự ý vượt); nếu vượt hoặc
            # thiếu tồn sẽ rơi vào DomainError → ghi vào 'skipped' để người dùng xử lý thủ công
            # (KHÔNG chặn toàn bộ backflush như dispense() — mỗi vật tư độc lập).
            plan, fifo_ok = _plan_consume(db, code, need, reserved=reserved)
            rows = _execute_plan(db, batch, code, plan, user, allow_over=False, fifo_ok=fifo_ok)
            for r in rows:
                db.add(DispenseLine(line_id=new_id(), dispense_id=disp.dispense_id, **r))
                all_lines.append(r)
        except DomainError as e:
            skipped.append({"material_code": code, "need": need, "error": str(e)})
    record_audit(db, entity_type="batch", entity_id=batch_id, action="backflush", actor=user,
                 after={"dispense_code": disp.dispense_code, "produced_qty": produced_qty,
                        "lines": len(all_lines)})
    db.commit()
    return {"dispense_code": disp.dispense_code, "factor": round(factor, 4),
            "lines": all_lines, "skipped": skipped, "bom": bom.compare_batch(db, batch)}


def adjust_actual(db: Session, batch_id: str, material_code: str, new_actual: float,
                  user: User, reason: str) -> dict:
    """"Sửa" Thực tế của 1 vật tư ở bảng Định mức↔Thực tế (Cấp liệu cho mẻ) — tự tính CHÊNH LỆCH
    với thực tế hiện tại rồi TỰ ĐỘNG cấp thêm (tăng: qua FEFO ở Kho phân xưởng, all-or-nothing,
    mirror dispense()) hoặc hoàn lại (giảm: hoàn về lô đã dùng GẦN NHẤT của vật tư này trên mẻ,
    theo thứ tự LIFO — giảm dần quantity trên chính cạnh genealogy consume đã tạo trước đó, xoá
    cạnh nếu hoàn hết). Mọi thay đổi vẫn đi qua consume_lot thật/genealogy edge thật — không có
    số nào tồn tại ngoài sổ sách. Bắt buộc `reason` để truy vết. Chỉ sửa được khi mẻ CHƯA khóa
    hồ sơ (EBR)."""
    require_role(user, Role.OPERATOR, Role.SUPERVISOR, Role.ENGINEER)
    batch = db.get(BatchExecution, batch_id)
    if not batch:
        raise NotFoundError("Batch không tồn tại.")
    if batch.ebr_locked:
        raise DomainError("Hồ sơ mẻ (EBR) đã khóa — không thể sửa Thực tế; chỉ tạo amendment.")
    if not (reason or "").strip():
        raise DomainError("Bắt buộc nhập lý do khi sửa Thực tế.")
    current = round(bom.actual_consumed_for_match(db, batch, material_code), 6)
    new_actual = round(new_actual, 6)
    delta = round(new_actual - current, 6)
    if abs(delta) <= 1e-6:
        raise DomainError("Số Thực tế mới giống hệt hiện tại — không có gì để sửa.")

    disp = Dispense(dispense_id=new_id(),
                    dispense_code=f"ADJ-{utcnow():%Y%m%d}-{new_id()[:5].upper()}",
                    batch_id=batch_id, mode="adjust", status="issued",
                    note=f"Sửa Thực tế {material_code}: {current} → {new_actual} ({reason})",
                    created_by=user.username, created_at=utcnow())
    db.add(disp)
    db.flush()
    all_lines = []
    if delta > 0:
        plan, fifo_ok = _plan_consume(db, material_code, delta)
        rows = _execute_plan(db, batch, material_code, plan, user, allow_over=True,
                             fifo_ok=fifo_ok, reason=reason)
        for r in rows:
            db.add(DispenseLine(line_id=new_id(), dispense_id=disp.dispense_id, **r))
            all_lines.append(r)
    else:
        need_refund = round(-delta, 6)
        # material_code có thể là mã Nhóm vật tư thay thế (dòng BOM khai theo nhóm) — hoàn lại
        # phải khớp BẤT KỲ mã thành viên nào đã thực sự tiêu thụ, không chỉ đúng mã nhóm.
        refund_codes = set(bom.codes_for_dispense(db, material_code))
        edges = db.execute(select(GenealogyEdge).where(
            GenealogyEdge.to_type == "batch", GenealogyEdge.to_id == batch_id,
            GenealogyEdge.from_type == "lot", GenealogyEdge.relation == "consume")
            .order_by(GenealogyEdge.event_time.desc())).scalars().all()
        candidates = []
        for edge in edges:
            if not edge.quantity:
                continue
            # with_for_update(): khóa hàng trước khi đọc lot.quantity — 2 request hoàn lại/cấp
            # liệu gần như đồng thời trên CÙNG lô có thể cùng đọc quantity cũ (2026-09-03, audit
            # Kho công ty/phân xưởng).
            lot = db.execute(select(MaterialLot).where(
                MaterialLot.lot_id == edge.from_id).with_for_update()).scalar_one_or_none()
            if not lot or bom.material_code_for_lot(db, lot) not in refund_codes:
                continue
            candidates.append((edge, lot))
        plan_refund, remaining = [], need_refund
        for edge, lot in candidates:
            if remaining <= 1e-9:
                break
            take = min(remaining, edge.quantity)
            if take <= 0:
                continue
            plan_refund.append((edge, lot, take))
            remaining = round(remaining - take, 6)
        if remaining > 1e-6:
            raise DomainError(
                f"Không đủ lịch sử tiêu thụ (qua Cấp liệu/Consume) để hoàn lại — thiếu "
                f"{remaining} {material_code}.")
        for edge, lot, take in plan_refund:
            lot.quantity = round(lot.quantity + take, 6)
            if lot.status == LotStatus.CONSUMED.value:
                lot.status = LotStatus.AVAILABLE.value
            edge.quantity = round(edge.quantity - take, 6)
            if edge.quantity <= 1e-9:
                db.delete(edge)
            row = {"material_code": bom.material_code_for_lot(db, lot), "lot_id": lot.lot_id,
                  "lot_code": lot.lot_code, "quantity": -take, "uom": lot.uom,
                  "fifo_ok": True, "reason": reason}
            db.add(DispenseLine(line_id=new_id(), dispense_id=disp.dispense_id, **row))
            all_lines.append(row)
    record_audit(db, entity_type="batch", entity_id=batch_id, action="adjust_actual", actor=user,
                after={"material_code": material_code, "from": current, "to": new_actual, "reason": reason})
    db.commit()
    return {"dispense_code": disp.dispense_code, "lines": all_lines, "bom": bom.compare_batch(db, batch)}


def list_dispenses(db: Session, batch_id: str = None) -> list:
    stmt = select(Dispense).order_by(Dispense.created_at.desc())
    if batch_id:
        stmt = stmt.where(Dispense.batch_id == batch_id)
    out = []
    for d in db.execute(stmt).scalars().all():
        lines = db.execute(select(DispenseLine).where(
            DispenseLine.dispense_id == d.dispense_id)).scalars().all()
        out.append({"dispense_code": d.dispense_code, "batch_id": d.batch_id, "mode": d.mode,
                    "status": d.status, "note": d.note, "created_by": d.created_by,
                    "created_at": d.created_at,
                    "lines": [{"material_code": l.material_code, "lot_code": l.lot_code,
                               "quantity": l.quantity, "uom": l.uom, "fifo_ok": l.fifo_ok,
                               "reason": l.reason} for l in lines]})
    return out


def batch_dispense_summary(db: Session, batch_id: str, only_dispensed: bool = True) -> list[dict]:
    """Bảng Định mức↔Thực tế tách THEO MÃ VẬT TƯ THẬT đã cấp (KHÔNG gộp theo mã Nhóm vật tư
    thay thế như bom.py::compare_batch), kèm mã lô đã dùng + có đúng FIFO hay không (từ lịch sử
    cấp liệu — DispenseLine, luôn ghi mã THẬT theo lô, xem _execute_plan/adjust_actual). Dòng
    BOM khai theo nhóm (member_qty hoặc bare group) mà ĐÃ cấp cho ít nhất 1 thành viên hiện
    thành N dòng con (1/mã thật đã cấp — bỏ qua mã chưa cấp gì trong CÙNG dòng đó), Định mức/
    Chênh/Trạng thái CHỈ hiện ở dòng ĐẦU (dùng CHUNG cho cả nhóm, xem bom.py::_expand_materials).

    `only_dispensed=True` (màn "Cấp liệu"): bỏ hẳn dòng BOM nào CHƯA cấp gì (theo yêu cầu người
    dùng — không tự liệt kê sẵn định mức công thức khi chưa cấp). `only_dispensed=False` (Mẻ
    sản xuất/EBR — cần thấy ĐỦ mọi dòng BOM kể cả chưa cấp): dòng chưa cấp gì giữ nguyên GỘP
    THEO NHÓM y hệt compare_batch (chưa biết sẽ cấp qua thành viên nào nên không tách được)."""
    batch = db.get(BatchExecution, batch_id)
    if not batch:
        raise NotFoundError("Batch không tồn tại.")
    cmp = bom.compare_batch(db, batch)
    # "Thực tế" LUÔN lấy từ actual_consumed (genealogy — đúng dù tiêu thụ qua /consume trực
    # tiếp hay qua dispense(), xem bom.py::actual_consumed) — TUYỆT ĐỐI KHÔNG tự cộng dồn
    # DispenseLine.quantity cho việc này (chỉ có nếu đi qua dispense(), thiếu/lệch nếu mẻ có
    # dòng tiêu thụ qua /consume trực tiếp — bug thực tế đã gặp: 1 mẻ consume 8kg qua /consume
    # rồi "Sửa" xuống 3kg qua adjust_actual (tạo dòng hoàn -5kg) ra "Thực tế" -5kg thay vì 3kg).
    actual_by_code = bom.actual_consumed(db, batch_id)
    name_by_code = {m.code: m.name for m in db.execute(select(Material)).scalars().all()}
    # DispenseLine CHỈ dùng để tra mã lô/FIFO — vốn chỉ có khi đi qua dispense() (suggest/Cấp 1
    # vật tư/backflush/adjust), KHÔNG có với tiêu thụ qua /consume trực tiếp (lot_codes rỗng/
    # fifo_ok=None khi đó — không suy đoán được là ĐÚNG hay SAI FIFO).
    dispense_ids = db.execute(select(Dispense.dispense_id).where(
        Dispense.batch_id == batch_id)).scalars().all()
    dlines = db.execute(select(DispenseLine).where(
        DispenseLine.dispense_id.in_(dispense_ids))).scalars().all() if dispense_ids else []
    lot_info: dict[str, dict] = {}
    for dl in dlines:
        info = lot_info.setdefault(dl.material_code, {"lot_codes": [], "fifo_ok": True})
        if dl.lot_code and dl.lot_code not in info["lot_codes"]:
            info["lot_codes"].append(dl.lot_code)
        if dl.fifo_ok is False:
            info["fifo_ok"] = False
    rows = []
    for l in cmp["lines"]:
        codes = l.get("match_codes") or [l["material_code"]]
        dispensed = [c for c in codes if abs(actual_by_code.get(c, 0.0)) > 1e-9]
        if not dispensed:
            if only_dispensed:
                continue
            rows.append({"material_code": l["material_code"], "material_name": l.get("material_name"),
                        "uom": l["uom"], "planned": l["planned"], "actual": l["actual"],
                        "diff": l["diff"], "pct": l["pct"], "status": l["status"],
                        "lot_codes": [], "fifo_ok": None})
            continue
        for i, code in enumerate(dispensed):
            info = lot_info.get(code)
            rows.append({
                "material_code": code,
                "material_name": l.get("material_name") if code == l["material_code"] else name_by_code.get(code),
                "uom": l["uom"],
                "planned": l["planned"] if i == 0 else None,
                "actual": round(actual_by_code.get(code, 0.0), 3),
                "diff": l["diff"] if i == 0 else None,
                "pct": l["pct"] if i == 0 else None,
                "status": l["status"] if i == 0 else None,
                "lot_codes": info["lot_codes"] if info else [],
                "fifo_ok": info["fifo_ok"] if info else None,
            })
    return rows
