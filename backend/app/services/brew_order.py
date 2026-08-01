"""Lệnh nấu bia (Brew Production Order) — mẫu giấy "LỆNH NẤU BIA KIÊM PHIẾU XUẤT KHO",
chỉ giữ phần LỆNH (định mức NVL dự kiến), không lặp lại phần phiếu xuất kho thật (đã có
qua BrewMaterialUsage/warehouse_svc.issue() ở từng mẻ, xem routers/brewing.py::add_brew_material).

Định mức NVL tự nạp từ Công thức (BOM) hiệu lực của dịch bia. Công thức khai báo định mức
CHO ĐÚNG 1 MẺ (không phải theo 1 quy mô thể tích trừu tượng rồi scale ngược) — Nhu cầu 1 mẻ
= NGUYÊN VĂN số lượng khai báo trong công thức, Nhu cầu Tổng mẻ = Nhu cầu 1 mẻ x Số mẻ kế
hoạch (xem build_lines_from_bom; KHÔNG dùng planned_volume_hl để scale — trường đó chỉ mang
tính kế hoạch/báo cáo sản lượng, độc lập với định mức NVL). Snapshot tồn kho công ty/phân
xưởng được ghi lại NGAY LÚC LẬP PHIẾU (không phải tồn sống) — đúng tính chất văn bản đã
ký/in ra, để về sau xem lại vẫn đúng số liệu tại thời điểm đó."""

from sqlalchemy import select, true
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import new_id, resolve_years, utcnow
from ..errors import DomainError, NotFoundError
from ..models.brewing import (
    BrewBatch,
    BrewMasterOrder,
    BrewOrder,
    BrewOrderMaterialLine,
    BrewProcessLog,
    BrewRecord,
    FermentBrewLink,
    FermentRecord,
)
from ..models.formula import Formula
from ..models.master import Material, MaterialAltGroup, Product
from . import braumat_import as braumat_svc
from . import warehouse as warehouse_svc


def _effective_bom(db: Session, product_id: str):
    """Công thức đang hiệu lực của dịch bia — tối đa 1 dòng vì services/formula.py::
    activate_formula đảm bảo chỉ 1 formula/product được is_active=True tại 1 thời điểm
    (khác bug cũ ở RecipeVersion.state='effective' không có ràng buộc loại trừ)."""
    if not product_id:
        return None
    return db.execute(select(Formula).where(
        Formula.product_id == product_id, Formula.is_active == true())).scalars().first()


def _resolve_group_members(db: Session, group_code: str | None) -> list:
    """Tra danh sách material_id thành viên của 1 Nhóm vật tư thay thế (VD "Malt Úc" = rời +
    bao) — trả rỗng nếu nhóm không tồn tại/đã ngừng hoạt động. KHÔNG lưu cứng danh sách này
    vào BrewOrderMaterialLine vì nhóm có thể đổi thành viên sau khi lệnh đã lập — chỉ ảnh
    hưởng gợi ý hiển thị lúc ghi NVL thực tế (openBrewMaterialsModal), không ảnh hưởng số
    liệu định mức/tồn kho đã snapshot lúc lập lệnh."""
    if not group_code:
        return []
    g = db.execute(select(MaterialAltGroup).where(
        MaterialAltGroup.code == group_code, MaterialAltGroup.active == true())).scalars().first()
    return list(g.member_material_ids or []) if g else []


def _stock_snapshot(db: Session) -> tuple[dict, dict]:
    """Trả 2 dict {material_id: on_hand} — 1 lần gọi cho cả lệnh, tránh N+1 query."""
    company = {r["material_id"]: r["on_hand"] for r in warehouse_svc.stock_on_hand(db, "Kho công ty")}
    workshop = {r["material_id"]: r["on_hand"] for r in warehouse_svc.stock_on_hand(db, "Kho phân xưởng")}
    return company, workshop


def build_lines_from_bom(db: Session, product_id: str, planned_batch_count: int, planned_volume_hl: float) -> list:
    """Nạp Định mức từ Công thức hiệu lực của dịch bia — công thức khai báo định mức CHO
    ĐÚNG 1 MẺ, nên Nhu cầu 1 mẻ = nguyên văn số lượng trong công thức (KHÔNG scale theo
    planned_volume_hl — tham số này chỉ giữ lại cho tương thích chữ ký hàm/router, không
    dùng trong phép tính), Nhu cầu Tổng mẻ = Nhu cầu 1 mẻ x Số mẻ kế hoạch.

    Dòng khai theo Nhóm vật tư thay thế (alt_group_code, VD "Malt Úc") không có material_id
    cụ thể — material_name = tên nhóm, kèm member_material_ids để _annotate_stock cộng dồn
    tồn kho qua mọi mã thành viên và để thủ kho được gợi ý đúng mọi mã lúc ghi NVL thực tế
    (xem _resolve_group_members, frontend openBrewMaterialsModal)."""
    formula = _effective_bom(db, product_id)
    if not formula:
        return []
    materials_by_code = {m.code: m for m in db.execute(select(Material)).scalars().all()}
    groups_by_code = {g.code: g for g in db.execute(select(MaterialAltGroup)).scalars().all()}
    out = []
    for i, m in enumerate(formula.materials or []):
        qty_per_batch = round(m.get("qty", 0) or 0, 3)
        qty_total = round(qty_per_batch * planned_batch_count, 3)
        group_code = m.get("alt_group_code")
        if group_code:
            group = groups_by_code.get(group_code)
            out.append({
                "seq": i, "stt_label": str(i + 1), "is_header": False,
                "material_id": None,
                "material_name": group.name if group else group_code,
                "material_group_code": group_code,
                "member_material_ids": list(group.member_material_ids or []) if group else [],
                "uom": m.get("uom"),
                "qty_per_batch": qty_per_batch,
                "qty_total": qty_total,
            })
            continue
        code = m.get("material_code")
        mat = materials_by_code.get(code)
        out.append({
            "seq": i, "stt_label": str(i + 1), "is_header": False,
            "material_id": mat.material_id if mat else None,
            "material_name": mat.name if mat else code,
            "uom": m.get("uom"),
            "qty_per_batch": qty_per_batch,
            "qty_total": qty_total,
        })
    return out


def _line_stock(l: dict, company_stock: dict, workshop_stock: dict) -> tuple:
    """Tồn công ty/phân xưởng cho 1 dòng NVL — dòng nhóm vật tư thay thế (member_material_ids
    không rỗng) cộng dồn qua MỌI mã thành viên; dòng thường tra theo material_id đơn lẻ."""
    member_ids = l.get("member_material_ids") or []
    if member_ids:
        company = sum(company_stock.get(mid, 0) or 0 for mid in member_ids)
        workshop = sum(workshop_stock.get(mid, 0) or 0 for mid in member_ids)
        return company, workshop
    material_id = l.get("material_id")
    return company_stock.get(material_id, 0) or 0, workshop_stock.get(material_id, 0) or 0


def _materials_by_id(db: Session) -> dict:
    return {m.material_id: m for m in db.execute(select(Material)).scalars().all()}


def _member_breakdown(member_ids: list, company_stock: dict, workshop_stock: dict, materials_by_id: dict) -> list:
    """Tồn kho TỪNG mã thành viên của 1 dòng Nhóm vật tư thay thế — để người lập lệnh thấy
    ngay nhóm gồm đúng những mã nào và mã nào đang thực sự có tồn (VD "Malt Úc" gồm Malt Úc
    rời + Malt Úc bao, chỉ 1 trong 2 đang còn hàng), không chỉ số tổng cộng dồn."""
    out = []
    for mid in member_ids or []:
        mat = materials_by_id.get(mid)
        out.append({
            "material_id": mid, "material_code": mat.code if mat else None,
            "material_name": mat.name if mat else mid,
            "stock_company": company_stock.get(mid, 0) or 0,
            "stock_workshop": workshop_stock.get(mid, 0) or 0,
        })
    return out


def _annotate_stock(lines: list, company_stock: dict, workshop_stock: dict, materials_by_id: dict | None = None) -> list:
    """Gắn tồn kho công ty/phân xưởng + cờ "shortage" (thiếu tồn) vào từng dòng NVL — dùng
    chung cho preview (trước khi tạo lệnh) và get_order (đã tạo, đọc lại snapshot đã lưu).
    Dòng Nhóm vật tư thay thế còn kèm member_breakdown (tồn riêng từng mã thành viên) khi có
    materials_by_id — bắt buộc để hiện đúng tên vật tư, không chỉ material_id."""
    out = []
    for l in lines:
        has_target = bool(l.get("material_id") or l.get("member_material_ids"))
        company, workshop = _line_stock(l, company_stock, workshop_stock)
        qty_total = l.get("qty_total")
        shortage = (not l.get("is_header")) and qty_total is not None and qty_total > (company + workshop)
        member_ids = l.get("member_material_ids") or []
        member_breakdown = (_member_breakdown(member_ids, company_stock, workshop_stock, materials_by_id)
                             if member_ids and materials_by_id is not None else [])
        out.append({**l, "stock_company_snapshot": company if has_target else None,
                    "stock_workshop_snapshot": workshop if has_target else None,
                    "unit_price": l.get("unit_price"), "shortage": shortage,
                    "member_breakdown": member_breakdown})
    return out


def preview_bom_lines(db: Session, product_id: str, planned_batch_count: int, planned_volume_hl: float) -> list:
    """Xem trước bảng định mức NVL tự nạp từ Công thức (BOM) + tồn kho hiện tại, TRƯỚC khi
    tạo lệnh nấu thật — để người lập biết ngay có đủ NVL hay không mà không cần tạo lệnh
    xong rồi mới xem (xem routers/brewing.py::preview_brew_order_bom)."""
    lines = build_lines_from_bom(db, product_id, planned_batch_count, planned_volume_hl)
    company_stock, workshop_stock = _stock_snapshot(db)
    return _annotate_stock(lines, company_stock, workshop_stock, _materials_by_id(db))


def _validate_volume_plan(planned_volume_hl, tolerance_hl) -> None:
    """Sản lượng nấu kế hoạch (hl) bắt buộc phải > 0 — nếu để 0/None, logic hoàn thành
    (thực tế >= kế hoạch - sai số) sẽ coi lệnh "hoàn thành ngay từ đầu" khi thực tế
    cũng đang là 0 (chưa nấu gì), sai hoàn toàn (xem _is_complete)."""
    if planned_volume_hl is None or planned_volume_hl <= 0:
        raise DomainError("Nhập sản lượng nấu kế hoạch (hl) (phải lớn hơn 0).")
    if tolerance_hl is None or tolerance_hl < 0:
        raise DomainError("Sai số cho phép không được âm.")


def _insert_sub_order(db: Session, master_order_id, seq: int, order_code: str, order_year: int, payload: dict, user) -> BrewOrder:
    """Tạo 1 dòng BrewOrder ("lệnh nấu nhỏ") + định mức NVL — KHÔNG validate (caller đã
    validate), KHÔNG commit (caller tự quyết định điểm commit). Dùng chung bởi create_order
    (lệnh nấu phẳng cũ, master_order_id=None) và create_master_order/update_master_order
    (nhiều lệnh nhỏ trong 1 lệnh lớn), mirror filter_order.py::_insert_sub_order."""
    payload = dict(payload)
    lines_in = payload.pop("lines", None) or []
    auto_from_bom = payload.pop("auto_from_bom", True)

    order = BrewOrder(brew_order_id=new_id(), order_code=order_code, order_year=order_year,
                      master_order_id=master_order_id,
                      seq=seq, created_by=user.username, created_at=utcnow(), **payload)
    db.add(order)
    db.flush()

    lines = lines_in if lines_in else (
        build_lines_from_bom(db, order.product_id, order.planned_batch_count, order.planned_volume_hl)
        if auto_from_bom and order.product_id else []
    )

    company_stock, workshop_stock = _stock_snapshot(db)
    for i, line in enumerate(lines):
        material_id = line.get("material_id")
        has_target = bool(material_id or line.get("member_material_ids"))
        company, workshop = _line_stock(line, company_stock, workshop_stock)
        db.add(BrewOrderMaterialLine(
            line_id=new_id(), brew_order_id=order.brew_order_id, seq=line.get("seq", i),
            stt_label=line.get("stt_label"), is_header=line.get("is_header", False),
            material_id=material_id, material_name=line.get("material_name"), uom=line.get("uom"),
            material_group_code=line.get("material_group_code"),
            qty_per_batch=line.get("qty_per_batch"), qty_total=line.get("qty_total"),
            unit_price=line.get("unit_price"),
            stock_company_snapshot=company if has_target else None,
            stock_workshop_snapshot=workshop if has_target else None,
        ))
    return order


def create_order(db: Session, payload: dict, user) -> BrewOrder:
    payload = dict(payload)
    order_code = payload.pop("order_code")
    order_year = utcnow().year
    if db.execute(select(BrewOrder).where(BrewOrder.order_code == order_code,
                  BrewOrder.order_year == order_year)).first():
        raise DomainError(f"Số lệnh '{order_code}' đã tồn tại trong năm {order_year}.")
    _validate_volume_plan(payload.get("planned_volume_hl"), payload.get("volume_tolerance_hl"))

    order = _insert_sub_order(db, None, 1, order_code, order_year, payload, user)

    record_audit(db, entity_type="brew_order", entity_id=order.brew_order_id, action="create",
                 actor=user, after={"order_code": order.order_code})
    db.commit()
    db.refresh(order)
    return order


def update_order(db: Session, brew_order_id: str, payload: dict, user) -> BrewOrder:
    """Sửa lại lệnh nấu CHƯA thực hiện (chưa có BrewRecord nào) — cho phép sửa toàn bộ (số
    lệnh, dịch bia, sản lượng kế hoạch...); định mức NVL được nạp lại từ đầu giống hệt lúc
    tạo mới (lines truyền tay hoặc tự nạp lại từ BOM theo product_id/planned_batch_count/
    planned_volume_hl mới — xem create_order)."""
    order = db.get(BrewOrder, brew_order_id)
    if not order:
        raise NotFoundError("Lệnh nấu không tồn tại.")
    if db.execute(select(BrewRecord).where(BrewRecord.brew_order_id == brew_order_id)).first():
        raise DomainError("Lệnh nấu đã được thực hiện — không thể sửa.")

    lines_in = payload.pop("lines", None) or []
    auto_from_bom = payload.pop("auto_from_bom", True)
    new_code = payload.get("order_code")
    if new_code != order.order_code and db.execute(
            select(BrewOrder).where(BrewOrder.order_code == new_code,
                    BrewOrder.order_year == order.order_year)).first():
        raise DomainError(f"Số lệnh '{new_code}' đã tồn tại trong năm {order.order_year}.")
    _validate_volume_plan(payload.get("planned_volume_hl"), payload.get("volume_tolerance_hl"))

    for l in db.execute(select(BrewOrderMaterialLine).where(
            BrewOrderMaterialLine.brew_order_id == brew_order_id)).scalars().all():
        db.delete(l)
    db.flush()

    for field, value in payload.items():
        setattr(order, field, value)

    lines = lines_in if lines_in else (
        build_lines_from_bom(db, order.product_id, order.planned_batch_count, order.planned_volume_hl)
        if auto_from_bom and order.product_id else []
    )

    company_stock, workshop_stock = _stock_snapshot(db)
    for i, line in enumerate(lines):
        material_id = line.get("material_id")
        has_target = bool(material_id or line.get("member_material_ids"))
        company, workshop = _line_stock(line, company_stock, workshop_stock)
        db.add(BrewOrderMaterialLine(
            line_id=new_id(), brew_order_id=order.brew_order_id, seq=line.get("seq", i),
            stt_label=line.get("stt_label"), is_header=line.get("is_header", False),
            material_id=material_id, material_name=line.get("material_name"), uom=line.get("uom"),
            material_group_code=line.get("material_group_code"),
            qty_per_batch=line.get("qty_per_batch"), qty_total=line.get("qty_total"),
            unit_price=line.get("unit_price"),
            stock_company_snapshot=company if has_target else None,
            stock_workshop_snapshot=workshop if has_target else None,
        ))

    record_audit(db, entity_type="brew_order", entity_id=order.brew_order_id, action="update",
                 actor=user, after={"order_code": order.order_code, "lines": len(lines)})
    db.commit()
    db.refresh(order)
    return order


def _real_actual_by_brew(db: Session, brew_ids: list) -> dict:
    """Sản lượng nấu THỰC TẾ đo được = tổng "Tổng lượng dịch (hl)" (Ghi chép nấu, mục Lắng
    xoáy + hạ T°) cộng dồn qua mọi mẻ của từng mã nấu — volume_hl trên BrewRecord chỉ là số
    nhập tay lúc TẠO mã nấu (kế hoạch/ước tính ban đầu), không phải số đo thật."""
    if not brew_ids:
        return {}
    batch_to_brew = {row[0]: row[1] for row in db.execute(
        select(BrewBatch.batch_id, BrewBatch.brew_id).where(BrewBatch.brew_id.in_(brew_ids))).all()}
    out: dict = {}
    if not batch_to_brew:
        return out
    logs = db.execute(select(BrewProcessLog).where(
        BrewProcessLog.batch_id.in_(list(batch_to_brew.keys())))).scalars().all()
    for log in logs:
        brew_id = batch_to_brew.get(log.batch_id)
        v = braumat_svc.get_manual_values(log).get("whp_tong_luong_dich_hl")
        if brew_id and v is not None:
            out[brew_id] = out.get(brew_id, 0.0) + float(v)
    return out


def _record_summaries(db: Session, brew_order_id: str) -> list:
    """TẤT CẢ BrewRecord của lệnh (1 lệnh có thể có nhiều mã nấu/tank lên men cộng dồn tới
    sản lượng kế hoạch — xem routers/brewing.py::add_brew)."""
    records = db.execute(select(BrewRecord).where(
        BrewRecord.brew_order_id == brew_order_id).order_by(BrewRecord.brew_date)).scalars().all()
    real_actual = _real_actual_by_brew(db, [r.brew_id for r in records])
    return [{"brew_id": r.brew_id, "brew_code": r.brew_code, "volume_hl": r.volume_hl,
            "actual_volume_hl": real_actual.get(r.brew_id), "brew_date": r.brew_date} for r in records]


def _actual_volume_hl(records: list) -> float:
    return round(sum(r.get("actual_volume_hl") or 0.0 for r in records), 3)


def _all_batches_finished(db: Session, brew_ids: list) -> bool:
    """TẤT CẢ mẻ của TẤT CẢ mã nấu thuộc lệnh đã được bấm "Kết thúc" chưa — mirror
    routers/brewing.py::_sync_ferment_kt_date (tank chỉ coi là "đầy" khi đủ mẻ kết thúc).
    Chưa có mẻ nào, hoặc còn mẻ nào dở dang (ended_at rỗng), đều coi là chưa xong."""
    if not brew_ids:
        return False
    ended_ats = [row[0] for row in db.execute(
        select(BrewBatch.ended_at).where(BrewBatch.brew_id.in_(brew_ids))).all()]
    return bool(ended_ats) and all(e is not None for e in ended_ats)


def _actual_tank_and_batch_range(db: Session, brew_ids: list) -> tuple:
    """Tank lên men + khoảng số mẻ THỰC TẾ đã nấu — suy ra từ lô lên men liên kết
    (FermentBrewLink) và các mẻ (BrewBatch) đã tạo cho các mã nấu của lệnh, KHÁC với
    tank_lm/batch_range_from/to nhập tay lúc lập lệnh (chỉ là dự kiến, thường bỏ trống).
    Trả None nếu chưa có dữ liệu (chưa tạo mã nấu/mẻ nào)."""
    if not brew_ids:
        return None, None
    ferment_ids = [row[0] for row in db.execute(
        select(FermentBrewLink.ferment_id).where(FermentBrewLink.brew_id.in_(brew_ids))).all()]
    tanks = []
    if ferment_ids:
        tanks = [row[0] for row in db.execute(
            select(FermentRecord.tank_lm).where(FermentRecord.ferment_id.in_(ferment_ids))).all() if row[0]]
    tank_str = ", ".join(sorted(set(tanks))) if tanks else None
    batches = db.execute(select(BrewBatch.batch_code).where(BrewBatch.brew_id.in_(brew_ids))
                         .order_by(BrewBatch.created_at)).scalars().all()
    batch_range = None
    if batches:
        batch_range = batches[0] if len(batches) == 1 else f"{batches[0]}-{batches[-1]}"
    return tank_str, batch_range


def _is_complete(db: Session, records: list, planned_volume_hl: float, tolerance_hl: float) -> bool:
    """Hoàn thành khi ĐÃ có ít nhất 1 mã nấu, tổng sản lượng thực tế (cộng dồn qua tất cả
    mã nấu của lệnh) đạt kế hoạch trong sai số cho phép (thực tế >= kế hoạch - sai số) HOẶC
    đã vượt kế hoạch (thực tế >= kế hoạch) — chỉ chặn hoàn thành khi còn HỤT quá sai số,
    KHÔNG chặn khi vượt kế hoạch (một chiều, không còn kiểu ±sai số 2 chiều như trước) — VÀ
    tất cả mẻ của tất cả mã nấu đó đã bấm "Kết thúc" — sản lượng khớp nhưng còn mẻ đang dở
    dang thì lệnh vẫn coi như đang thực hiện, chưa hoàn thành. Xem routers/brewing.py::
    add_brew (chặn tạo mã nấu mới khi đã hoàn thành)."""
    if not records:
        return False
    if _actual_volume_hl(records) < planned_volume_hl - tolerance_hl:
        return False
    return _all_batches_finished(db, [r["brew_id"] for r in records])


def list_orders(db: Session) -> list:
    orders = db.execute(select(BrewOrder).order_by(BrewOrder.created_at.desc())).scalars().all()
    products = {p.product_id: p for p in db.execute(select(Product)).scalars().all()}
    masters = {m.brew_master_order_id: m for m in db.execute(select(BrewMasterOrder)).scalars().all()}
    out = []
    for o in orders:
        records = _record_summaries(db, o.brew_order_id)
        prod = products.get(o.product_id)
        master = masters.get(o.master_order_id)
        actual_tank, actual_batch_range = _actual_tank_and_batch_range(db, [r["brew_id"] for r in records])
        out.append({
            "brew_order_id": o.brew_order_id, "order_code": o.order_code,
            "master_order_id": o.master_order_id, "master_order_code": master.order_code if master else None,
            "seq": o.seq,
            "product_id": o.product_id, "product_code": prod.code if prod else None,
            "product_desc": o.product_desc,
            "planned_batch_count": o.planned_batch_count,
            "tank_lm": o.tank_lm, "batch_range_from": o.batch_range_from, "batch_range_to": o.batch_range_to,
            "actual_tank_lm": actual_tank, "actual_batch_range": actual_batch_range,
            "created_at": o.created_at, "records": records,
            "planned_volume_hl": o.planned_volume_hl, "volume_tolerance_hl": o.volume_tolerance_hl,
            "actual_volume_hl": _actual_volume_hl(records),
            "is_executed": len(records) > 0,
            "is_complete": _is_complete(db, records, o.planned_volume_hl, o.volume_tolerance_hl),
            "locked": o.locked, "locked_by": o.locked_by,
        })
    return out


def get_order(db: Session, brew_order_id: str) -> dict:
    order = db.get(BrewOrder, brew_order_id)
    if not order:
        raise NotFoundError("Lệnh nấu không tồn tại.")
    lines = db.execute(select(BrewOrderMaterialLine).where(
        BrewOrderMaterialLine.brew_order_id == brew_order_id).order_by(BrewOrderMaterialLine.seq)).scalars().all()
    records = _record_summaries(db, brew_order_id)
    prod = db.get(Product, order.product_id) if order.product_id else None
    master = db.get(BrewMasterOrder, order.master_order_id) if order.master_order_id else None

    # Tồn kho TỪNG mã thành viên hiện tại (KHÔNG snapshot — nhóm có thể đổi tồn/thành viên
    # sau khi lệnh đã lập, nên hiện số sống để thủ kho biết thực tế đang còn mã nào).
    live_company_stock, live_workshop_stock = _stock_snapshot(db)
    materials_by_id = _materials_by_id(db)

    line_out = []
    for l in lines:
        company = l.stock_company_snapshot or 0
        workshop = l.stock_workshop_snapshot or 0
        shortage = (not l.is_header) and l.qty_total is not None and l.qty_total > (company + workshop)
        member_ids = _resolve_group_members(db, l.material_group_code)
        line_out.append({
            "line_id": l.line_id, "seq": l.seq, "stt_label": l.stt_label, "is_header": l.is_header,
            "material_id": l.material_id, "material_name": l.material_name, "uom": l.uom,
            "material_group_code": l.material_group_code,
            "member_material_ids": member_ids,
            "member_breakdown": _member_breakdown(member_ids, live_company_stock, live_workshop_stock, materials_by_id),
            "qty_per_batch": l.qty_per_batch, "qty_total": l.qty_total, "unit_price": l.unit_price,
            "stock_company_snapshot": l.stock_company_snapshot,
            "stock_workshop_snapshot": l.stock_workshop_snapshot, "shortage": shortage,
        })

    actual_tank, actual_batch_range = _actual_tank_and_batch_range(db, [r["brew_id"] for r in records])
    return {
        "brew_order_id": order.brew_order_id, "order_code": order.order_code,
        "master_order_id": order.master_order_id, "master_order_code": master.order_code if master else None,
        "seq": order.seq,
        "product_id": order.product_id, "product_code": prod.code if prod else None,
        "product_name": prod.name if prod else None, "product_desc": order.product_desc,
        "planned_batch_count": order.planned_batch_count,
        "bx_min": order.bx_min, "bx_max": order.bx_max,
        "tank_lm": order.tank_lm, "batch_range_from": order.batch_range_from,
        "batch_range_to": order.batch_range_to,
        "actual_tank_lm": actual_tank, "actual_batch_range": actual_batch_range,
        "created_by": order.created_by, "created_at": order.created_at,
        "records": records,
        "planned_volume_hl": order.planned_volume_hl, "volume_tolerance_hl": order.volume_tolerance_hl,
        "actual_volume_hl": _actual_volume_hl(records),
        "is_executed": len(records) > 0,
        "is_complete": _is_complete(db, records, order.planned_volume_hl, order.volume_tolerance_hl),
        "lines": line_out,
        "locked": order.locked, "locked_by": order.locked_by,
    }


# ===== Lệnh nấu LỚN (BrewMasterOrder — chứa nhiều "lệnh nấu nhỏ" BrewOrder) =====

def _child_summary(db: Session, order: BrewOrder, products: dict) -> dict:
    records = _record_summaries(db, order.brew_order_id)
    prod = products.get(order.product_id)
    actual_tank, actual_batch_range = _actual_tank_and_batch_range(db, [r["brew_id"] for r in records])
    return {
        "brew_order_id": order.brew_order_id, "seq": order.seq,
        "product_id": order.product_id, "product_code": prod.code if prod else None,
        "product_desc": order.product_desc,
        "planned_batch_count": order.planned_batch_count,
        "bx_min": order.bx_min, "bx_max": order.bx_max,
        "tank_lm": order.tank_lm, "batch_range_from": order.batch_range_from, "batch_range_to": order.batch_range_to,
        "actual_tank_lm": actual_tank, "actual_batch_range": actual_batch_range,
        "created_at": order.created_at, "records": records,
        "planned_volume_hl": order.planned_volume_hl, "volume_tolerance_hl": order.volume_tolerance_hl,
        "actual_volume_hl": _actual_volume_hl(records),
        "is_executed": len(records) > 0,
        "is_complete": _is_complete(db, records, order.planned_volume_hl, order.volume_tolerance_hl),
        "locked": order.locked, "locked_by": order.locked_by,
    }


def _validate_children(db: Session, children_in: list) -> list:
    """Validate TOÀN BỘ lệnh nhỏ TRƯỚC khi ghi bất kỳ dòng nào (tránh tạo dở dang nếu 1 lệnh
    nhỏ ở giữa danh sách bị lỗi). Không có kiểm tra chéo giữa các lệnh nhỏ (khác Lệnh lọc) —
    tank_lm/batch_range_from/to ở đây chỉ là thông tin dự kiến (free text, không FK tới tài
    nguyên sống nào), không có gì để tính over-commit."""
    if not children_in:
        raise DomainError("Lệnh nấu lớn phải có ít nhất 1 lệnh nấu nhỏ.")
    validated = []
    for child in children_in:
        child = dict(child)
        _validate_volume_plan(child.get("planned_volume_hl"), child.get("volume_tolerance_hl"))
        validated.append(child)
    return validated


def _insert_children(db: Session, master_order_id: str, order_year: int, validated: list, user) -> list:
    orders = []
    for seq, child in enumerate(validated, start=1):
        order = _insert_sub_order(db, master_order_id, seq, f"SUB-{new_id()[:12]}", order_year, child, user)
        orders.append(order)
    return orders


def _delete_children(db: Session, children: list) -> None:
    for o in children:
        for l in db.execute(select(BrewOrderMaterialLine).where(
                BrewOrderMaterialLine.brew_order_id == o.brew_order_id)).scalars().all():
            db.delete(l)
        db.flush()  # MSSQL enforce FK: material line (con) trước brew_order (cha).
        db.delete(o)
    db.flush()  # ... và brew_order (con) trước brew_master_order (cha).


def create_master_order(db: Session, payload: dict, user) -> BrewMasterOrder:
    order_code = payload["order_code"]
    order_year = utcnow().year
    if db.execute(select(BrewMasterOrder).where(BrewMasterOrder.order_code == order_code,
                  BrewMasterOrder.order_year == order_year)).first():
        raise DomainError(f"Số lệnh '{order_code}' đã tồn tại trong năm {order_year}.")
    validated = _validate_children(db, payload.get("children") or [])

    master = BrewMasterOrder(brew_master_order_id=new_id(), order_code=order_code, order_year=order_year,
                             issued_by=payload.get("issued_by"), executor_unit=payload.get("executor_unit"),
                             warehouse_keeper=payload.get("warehouse_keeper"),
                             reference_note=payload.get("reference_note"),
                             start_date=payload.get("start_date"), end_date=payload.get("end_date"),
                             safety_note=payload.get("safety_note"),
                             created_by=user.username, created_at=utcnow())
    db.add(master)
    db.flush()
    orders = _insert_children(db, master.brew_master_order_id, master.order_year, validated, user)

    record_audit(db, entity_type="brew_master_order", entity_id=master.brew_master_order_id, action="create",
                 actor=user, after={"order_code": master.order_code, "children": len(orders)})
    db.commit()
    db.refresh(master)
    return master


def list_master_orders(db: Session, years=None) -> list:
    years = resolve_years(years)
    stmt = select(BrewMasterOrder)
    if years:
        stmt = stmt.where(BrewMasterOrder.order_year.in_(years))
    masters = db.execute(stmt.order_by(BrewMasterOrder.created_at.desc())).scalars().all()
    products = {p.product_id: p for p in db.execute(select(Product)).scalars().all()}
    out = []
    for m in masters:
        children_rows = db.execute(select(BrewOrder).where(
            BrewOrder.master_order_id == m.brew_master_order_id).order_by(BrewOrder.seq)).scalars().all()
        children = [_child_summary(db, o, products) for o in children_rows]
        out.append({
            "brew_master_order_id": m.brew_master_order_id, "order_code": m.order_code,
            "issued_by": m.issued_by, "executor_unit": m.executor_unit, "warehouse_keeper": m.warehouse_keeper,
            "reference_note": m.reference_note, "start_date": m.start_date, "end_date": m.end_date,
            "safety_note": m.safety_note,
            "created_by": m.created_by, "created_at": m.created_at,
            "children": children,
            "planned_total_hl": round(sum(c["planned_volume_hl"] for c in children), 3),
            "actual_total_hl": round(sum(c["actual_volume_hl"] for c in children), 3),
            "is_executed_any": any(c["is_executed"] for c in children),
            "is_complete_all": bool(children) and all(c["is_complete"] for c in children),
            "locked": m.locked, "locked_by": m.locked_by,
        })
    return out


def get_master_order(db: Session, brew_master_order_id: str) -> dict:
    m = db.get(BrewMasterOrder, brew_master_order_id)
    if not m:
        raise NotFoundError("Lệnh nấu không tồn tại.")
    products = {p.product_id: p for p in db.execute(select(Product)).scalars().all()}
    children_rows = db.execute(select(BrewOrder).where(
        BrewOrder.master_order_id == brew_master_order_id).order_by(BrewOrder.seq)).scalars().all()
    # Tồn kho TỪNG mã thành viên hiện tại (KHÔNG snapshot — xem get_order cùng lý do).
    live_company_stock, live_workshop_stock = _stock_snapshot(db)
    materials_by_id = _materials_by_id(db)
    children = []
    for o in children_rows:
        summary = _child_summary(db, o, products)
        child_lines = []
        for l in db.execute(select(BrewOrderMaterialLine).where(
                BrewOrderMaterialLine.brew_order_id == o.brew_order_id).order_by(BrewOrderMaterialLine.seq)).scalars().all():
            member_ids = _resolve_group_members(db, l.material_group_code)
            child_lines.append({
                "line_id": l.line_id, "seq": l.seq, "stt_label": l.stt_label, "is_header": l.is_header,
                "material_id": l.material_id, "material_name": l.material_name, "uom": l.uom,
                "material_group_code": l.material_group_code,
                "member_material_ids": member_ids,
                "member_breakdown": _member_breakdown(member_ids, live_company_stock, live_workshop_stock, materials_by_id),
                "qty_per_batch": l.qty_per_batch, "qty_total": l.qty_total, "unit_price": l.unit_price,
                "stock_company_snapshot": l.stock_company_snapshot, "stock_workshop_snapshot": l.stock_workshop_snapshot,
            })
        summary["lines"] = child_lines
        children.append(summary)
    return {
        "brew_master_order_id": m.brew_master_order_id, "order_code": m.order_code,
        "issued_by": m.issued_by, "executor_unit": m.executor_unit, "warehouse_keeper": m.warehouse_keeper,
        "reference_note": m.reference_note, "start_date": m.start_date, "end_date": m.end_date,
        "safety_note": m.safety_note,
        "created_by": m.created_by, "created_at": m.created_at,
        "children": children,
        "planned_total_hl": round(sum(c["planned_volume_hl"] for c in children), 3),
        "actual_total_hl": round(sum(c["actual_volume_hl"] for c in children), 3),
        "is_executed_any": any(c["is_executed"] for c in children),
        "is_complete_all": bool(children) and all(c["is_complete"] for c in children),
        "locked": m.locked, "locked_by": m.locked_by,
    }


def update_master_order(db: Session, brew_master_order_id: str, payload: dict, user) -> BrewMasterOrder:
    """Sửa lệnh nấu lớn — chỉ cho phép khi CHƯA có lệnh nhỏ nào được thực hiện (có
    BrewRecord); xoá hết lệnh nhỏ cũ (định mức NVL) rồi tạo lại từ children mới, mirror
    filter_order.py::update_master_order."""
    master = db.get(BrewMasterOrder, brew_master_order_id)
    if not master:
        raise NotFoundError("Lệnh nấu không tồn tại.")
    old_children = db.execute(select(BrewOrder).where(
        BrewOrder.master_order_id == brew_master_order_id)).scalars().all()
    for o in old_children:
        if db.execute(select(BrewRecord).where(BrewRecord.brew_order_id == o.brew_order_id)).first():
            raise DomainError("Lệnh nấu đã được thực hiện — không thể sửa.")

    order_code = payload["order_code"]
    if order_code != master.order_code and db.execute(
            select(BrewMasterOrder).where(BrewMasterOrder.order_code == order_code,
                    BrewMasterOrder.order_year == master.order_year)).first():
        raise DomainError(f"Số lệnh '{order_code}' đã tồn tại trong năm {master.order_year}.")

    validated = _validate_children(db, payload.get("children") or [])

    _delete_children(db, old_children)
    db.flush()

    master.order_code = order_code
    master.issued_by = payload.get("issued_by")
    master.executor_unit = payload.get("executor_unit")
    master.warehouse_keeper = payload.get("warehouse_keeper")
    master.reference_note = payload.get("reference_note")
    master.start_date = payload.get("start_date")
    master.end_date = payload.get("end_date")
    master.safety_note = payload.get("safety_note")
    orders = _insert_children(db, master.brew_master_order_id, master.order_year, validated, user)

    record_audit(db, entity_type="brew_master_order", entity_id=master.brew_master_order_id, action="update",
                 actor=user, after={"order_code": master.order_code, "children": len(orders)})
    db.commit()
    db.refresh(master)
    return master


def delete_master_order(db: Session, brew_master_order_id: str, user) -> None:
    master = db.get(BrewMasterOrder, brew_master_order_id)
    if not master:
        raise NotFoundError("Lệnh nấu không tồn tại.")
    children = db.execute(select(BrewOrder).where(
        BrewOrder.master_order_id == brew_master_order_id)).scalars().all()
    for o in children:
        if db.execute(select(BrewRecord).where(BrewRecord.brew_order_id == o.brew_order_id)).first():
            raise DomainError("Lệnh nấu đã được thực hiện — không thể xóa.")
    _delete_children(db, children)
    record_audit(db, entity_type="brew_master_order", entity_id=brew_master_order_id, action="delete",
                 actor=user, before={"order_code": master.order_code, "children": len(children)})
    db.delete(master)
    db.commit()


def delete_order(db: Session, brew_order_id: str, user) -> None:
    order = db.get(BrewOrder, brew_order_id)
    if not order:
        raise NotFoundError("Lệnh nấu không tồn tại.")
    if db.execute(select(BrewRecord).where(BrewRecord.brew_order_id == brew_order_id)).first():
        raise DomainError("Lệnh nấu đã được thực hiện — không thể xóa.")
    for l in db.execute(select(BrewOrderMaterialLine).where(
            BrewOrderMaterialLine.brew_order_id == brew_order_id)).scalars().all():
        db.delete(l)
    db.flush()  # MSSQL enforce FK: xóa material line (con) trước brew_order (cha).
    record_audit(db, entity_type="brew_order", entity_id=brew_order_id, action="delete",
                 actor=user, before={"order_code": order.order_code})
    db.delete(order)
    db.commit()
