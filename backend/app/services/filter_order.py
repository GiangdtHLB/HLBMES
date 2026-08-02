"""Lệnh lọc — lập trước 1 (không phối) hoặc nhiều (phối) tank lên men sẽ lọc chung, khai báo
thể tích dịch lọc KẾ HOẠCH (đã gồm nước bài khí) + sai số cho phép; chọn lệnh khi tạo bản ghi
lọc thật (mirror BrewOrder/Lệnh nấu, xem services/brew_order.py) — có thể tạo NHIỀU bản ghi
("mẻ lọc") cho cùng 1 lệnh, tank BBT chọn tự do, sản lượng cộng dồn tới khi đạt kế hoạch thì
lệnh hoàn thành (xem _is_complete). Có thể kèm thêm vật tư (VD bột trợ lọc/diatomite) — chọn
từ Danh mục vật tư, tồn kho (tổng Kho công ty + Kho phân xưởng) được kiểm tra NGAY LÚC LẬP
LỆNH và CHẶN tạo lệnh nếu thiếu (khác Lệnh nấu chỉ cảnh báo — xem material_fifo_detail)."""

from typing import Optional

from sqlalchemy import select, true
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import new_id, resolve_years, utcnow
from ..errors import DomainError, NotFoundError
from ..models.brewing import (
    BottleRecord, FermentRecord, FilterMasterOrder, FilterOrder, FilterOrderMaterialLine, FilterOrderTank,
    FilterRecord,
)
from ..models.master import BeerType, FinishedProduct, Material, MaterialAltGroup, Product
from . import warehouse as warehouse_svc


def _validate_tanks(db: Session, blend_mode: str, tanks_in: list, beer_type_id: str = None) -> tuple:
    """Trả về (sources, beer_type_id đã xác định). Mỗi phần tử của `sources` là 1 dict
    chuẩn hoá: {tank_type, ferment (FermentRecord|None), source_bbt_code, source_filter
    (FilterRecord đại diện|None), reason, product_id, display_code} — nguồn có thể là tank
    lên men (tank_type="cct", `tanks_in` item có "ferment_id") HOẶC 1 tank thành phẩm/BBT
    ĐÃ LỌC XONG đang được LỌC LẠI (tank_type="bbt", item có "source_bbt_code"+"reason").
    Lọc phối được phép gộp nhiều tank KHÁC dịch bia (VD Sapphire-13oP + Sapphire-14oP), và
    cả nguồn CCT lẫn nguồn BBT trong cùng 1 lệnh nhỏ, miễn là cùng 1 Loại bia — Loại bia tự
    suy ra nếu tất cả tank cùng 1 Loại bia; nếu các tank thuộc NHIỀU Loại bia khác nhau (VD
    phối Sapphire với Legend) thì người lập PHẢI tự chọn 1 trong số đó (`beer_type_id`).
    Tank nào ĐÃ khai báo dịch bia (product_id) nhưng dịch bia đó CHƯA được gán Loại bia
    trong danh mục thì chặn hẳn; tank KHÔNG khai báo dịch bia (product_id None — VD dữ liệu
    cũ/test) thì bỏ qua, không tính vào tập Loại bia (giữ hành vi cũ: không có dịch bia =
    không suy ra được Loại bia, không phải lỗi). Nguồn BBT bắt buộc: TẤT CẢ mẻ lọc cùng
    to_bbt đã KCS duyệt và đã lọc xong (ended_at != None) — nếu không sẽ không có 1 nội
    dung tank rõ ràng để lọc lại (yêu cầu #5 áp dụng luôn ở đây)."""
    if blend_mode == "khong_phoi" and len(tanks_in) != 1:
        raise DomainError("Lọc không phối phải chọn đúng 1 tank nguồn.")
    if blend_mode == "phoi" and len(tanks_in) < 2:
        raise DomainError("Lọc phối phải chọn từ 2 tank nguồn trở lên.")

    sources = []
    for t in tanks_in:
        tank_type = t.get("tank_type", "cct")
        if tank_type == "bbt":
            code = t.get("source_bbt_code")
            reason = (t.get("reason") or "").strip()
            if not code:
                raise DomainError("Chưa chọn tank BBT nguồn để lọc lại.")
            if not reason:
                raise DomainError(f"Tank BBT {code} (lọc lại) phải nhập lý do lọc lại.")
            recs = db.execute(select(FilterRecord).where(FilterRecord.to_bbt == code)).scalars().all()
            if not recs:
                raise NotFoundError(f"Tank BBT '{code}' không tồn tại hoặc chưa có mẻ lọc nào.")
            if not all(r.qc_approved for r in recs):
                raise DomainError(f"Tank BBT {code} còn mẻ lọc chưa được KCS duyệt — không thể chọn lọc lại.")
            if not all(r.ended_at is not None for r in recs):
                raise DomainError(f"Tank BBT {code} còn mẻ lọc chưa lọc xong — không thể chọn lọc lại.")
            rep = max(recs, key=lambda r: r.filter_date)
            sources.append({"tank_type": "bbt", "ferment": None, "source_bbt_code": code,
                            "source_filter": rep, "reason": reason, "product_id": rep.product_id,
                            "display_code": code})
        else:
            fid = t.get("ferment_id")
            ferment = db.get(FermentRecord, fid)
            if not ferment:
                raise NotFoundError(f"Tank lên men '{fid}' không tồn tại.")
            if not ferment.qc_approved:
                raise DomainError(f"Tank {ferment.tank_lm} (lô LM {ferment.lm_code}) chưa được KCS duyệt lên men đạt — không thể chọn vào lệnh lọc.")
            sources.append({"tank_type": "cct", "ferment": ferment, "source_bbt_code": None,
                            "source_filter": None, "reason": None, "product_id": ferment.product_id,
                            "display_code": ferment.tank_lm})

    products = {}
    for s in sources:
        pid = s["product_id"]
        if pid and pid not in products:
            products[pid] = db.get(Product, pid)

    candidates = set()
    for s in sources:
        pid = s["product_id"]
        if not pid:
            continue
        prod = products[pid]
        if not prod or not prod.beer_type_id:
            raise DomainError(
                f"Dịch bia {prod.code if prod else pid} của tank {s['display_code']} chưa được gán "
                "Loại bia — vào Danh mục Dịch bia để gán trước khi lập lệnh lọc.")
        candidates.add(prod.beer_type_id)

    if not candidates:
        resolved_beer_type_id = None
    elif len(candidates) == 1:
        resolved_beer_type_id = next(iter(candidates))
    else:
        if not beer_type_id or beer_type_id not in candidates:
            raise DomainError("Các tank chọn thuộc nhiều Loại bia khác nhau — chọn 1 Loại bia cho lệnh lọc nhỏ này.")
        resolved_beer_type_id = beer_type_id
    return sources, resolved_beer_type_id


def _resolve_group_members(db: Session, group_code: str | None) -> list:
    """Tra danh sách material_id thành viên của 1 Nhóm vật tư thay thế — trả rỗng nếu nhóm
    không tồn tại/đã ngừng hoạt động. KHÔNG lưu cứng vào FilterOrderMaterialLine vì nhóm có
    thể đổi thành viên sau khi lệnh đã lập (mirror services/brew_order.py cùng tên hàm)."""
    if not group_code:
        return []
    g = db.execute(select(MaterialAltGroup).where(
        MaterialAltGroup.code == group_code, MaterialAltGroup.active == true())).scalars().first()
    return list(g.member_material_ids or []) if g else []


def _member_breakdown(db: Session, member_ids: list) -> list:
    """Tồn kho TỪNG mã thành viên của 1 dòng Nhóm vật tư thay thế (tính LIVE, không snapshot)
    — để người lập lệnh thấy đúng nhóm gồm mã nào và mã nào đang thực sự còn hàng."""
    out = []
    for mid in member_ids:
        mat = db.get(Material, mid)
        d = warehouse_svc.material_fifo_detail(db, mid)
        out.append({"material_id": mid, "material_code": mat.code if mat else None,
                    "material_name": mat.name if mat else mid,
                    "stock_company": d["stock_company"], "stock_workshop": d["stock_workshop"]})
    return out


def _validate_material_lines(db: Session, lines_in: list) -> list:
    """Kiểm tra đủ vật tư TRƯỚC khi tạo/sửa bất kỳ bản ghi nào — thiếu tồn (tổng 2 kho) thì
    chặn hẳn, không cho lập/sửa lệnh (khác Lệnh nấu chỉ cảnh báo rồi vẫn cho lưu). 1 dòng có
    thể khai theo `alt_group_code` (Nhóm vật tư thay thế) thay vì `material_id` cụ thể — tồn
    kiểm tra CỘNG DỒN qua mọi mã thành viên (xem _resolve_group_members)."""
    material_lines = []
    for line in lines_in:
        quantity = line["quantity"]
        group_code = line.get("alt_group_code")
        if group_code:
            group = db.execute(select(MaterialAltGroup).where(
                MaterialAltGroup.code == group_code, MaterialAltGroup.active == true())).scalars().first()
            if not group:
                raise NotFoundError(f"Nhóm vật tư thay thế '{group_code}' không tồn tại hoặc đã ngừng hoạt động.")
            member_ids = list(group.member_material_ids or [])
            if not member_ids:
                raise DomainError(f"Nhóm vật tư thay thế '{group.name}' chưa có vật tư thành viên.")
            company = sum(warehouse_svc.material_fifo_detail(db, mid)["stock_company"] for mid in member_ids)
            workshop = sum(warehouse_svc.material_fifo_detail(db, mid)["stock_workshop"] for mid in member_ids)
            if quantity > company + workshop:
                raise DomainError(
                    f"Nhóm vật tư '{group.name}' không đủ tồn kho: cần {quantity}, hiện có {round(company + workshop, 3)} "
                    f"(Kho công ty {round(company, 3)} + Kho phân xưởng {round(workshop, 3)}).")
            material_lines.append({"material": None, "group": group, "quantity": quantity,
                                   "unit_price": line.get("unit_price"),
                                   "stock_company": round(company, 3), "stock_workshop": round(workshop, 3)})
            continue
        material_id = line["material_id"]
        mat = db.get(Material, material_id)
        if not mat:
            raise NotFoundError(f"Vật tư '{material_id}' không tồn tại.")
        detail = warehouse_svc.material_fifo_detail(db, material_id)
        if quantity > detail["stock_total"]:
            raise DomainError(
                f"Vật tư '{mat.name}' không đủ tồn kho: cần {quantity}, hiện có {detail['stock_total']} "
                f"(Kho công ty {detail['stock_company']} + Kho phân xưởng {detail['stock_workshop']}).")
        material_lines.append({"material": mat, "group": None, "quantity": quantity, "unit_price": line.get("unit_price"),
                               "stock_company": detail["stock_company"], "stock_workshop": detail["stock_workshop"]})
    return material_lines


def _material_line_row(filter_order_id: str, seq: int, ml: dict) -> FilterOrderMaterialLine:
    """Dựng 1 FilterOrderMaterialLine từ dict đã validate (_validate_material_lines) — dùng
    chung cho create_order/update_order, tách riêng vì dòng Nhóm vật tư thay thế không có
    `material` (material_id=None, lưu material_group_code thay vào)."""
    if ml.get("group"):
        return FilterOrderMaterialLine(
            line_id=new_id(), filter_order_id=filter_order_id, seq=seq,
            material_id=None, material_name=ml["group"].name, material_group_code=ml["group"].code,
            uom=None, quantity=ml["quantity"], unit_price=ml["unit_price"],
            stock_company_snapshot=ml["stock_company"], stock_workshop_snapshot=ml["stock_workshop"])
    return FilterOrderMaterialLine(
        line_id=new_id(), filter_order_id=filter_order_id, seq=seq,
        material_id=ml["material"].material_id, material_name=ml["material"].name,
        uom=ml["material"].uom, quantity=ml["quantity"], unit_price=ml["unit_price"],
        stock_company_snapshot=ml["stock_company"], stock_workshop_snapshot=ml["stock_workshop"])


def _validate_finished_product(db: Session, finished_product_id: str = None) -> Optional[str]:
    """Sản phẩm đích (SKU, tuỳ chọn) khai báo lúc lập Lệnh lọc — không tự suy ra như
    beer_type_id, người lập tự chọn khi cần phân biệt chỉ tiêu Lọc theo hình thức đóng gói
    đích (VD Legend chai lọc khác Legend tươi, xem qc_catalog.SKU_SCOPED_STAGES)."""
    if not finished_product_id:
        return None
    if not db.get(FinishedProduct, finished_product_id):
        raise NotFoundError("Sản phẩm không tồn tại.")
    return finished_product_id


def _validate_volume_plan(planned_volume_hl, tolerance_hl) -> None:
    """Thể tích dịch lọc kế hoạch bắt buộc phải > 0 — nếu để 0/None, logic hoàn thành
    (abs(thực tế - kế hoạch) <= sai số) sẽ coi lệnh "hoàn thành ngay từ đầu" khi thực tế cũng
    đang là 0 (chưa lọc gì), sai hoàn toàn (xem _is_complete)."""
    if planned_volume_hl is None or planned_volume_hl <= 0:
        raise DomainError("Nhập thể tích dịch lọc kế hoạch (phải lớn hơn 0).")
    if tolerance_hl is None or tolerance_hl < 0:
        raise DomainError("Sai số cho phép không được âm.")


def _validate_tank_plans(tanks_in: list) -> None:
    """Mỗi tank lên men trong 1 lệnh nhỏ phải tự khai báo thể tích dịch lọc kế hoạch > 0 —
    tổng của lệnh nhỏ = cộng dồn các tank (xem _validate_children)."""
    if not tanks_in:
        raise DomainError("Chọn ít nhất 1 tank lên men.")
    for t in tanks_in:
        if t.get("planned_v_dich_hl") is None or t["planned_v_dich_hl"] <= 0:
            raise DomainError("Mỗi tank lên men phải khai báo thể tích dịch lọc kế hoạch (phải lớn hơn 0).")


def _insert_sub_order(db: Session, master_order_id, seq: int, order_code: str, order_year: int, blend_mode: str,
                       note, kcs_lot_no, planned_volume_hl: float, volume_tolerance_hl: float,
                       sources: list, material_lines: list, user,
                       beer_type_id: str = None, finished_product_id: str = None) -> FilterOrder:
    """Tạo 1 dòng FilterOrder ("lệnh lọc nhỏ") + tank/vật tư — KHÔNG validate (caller đã
    validate), KHÔNG commit (caller tự quyết định điểm commit). `sources` là danh sách dict
    đã chuẩn hoá từ `_validate_tanks` (mỗi phần tử thêm key "planned_v_dich_hl" trước khi
    gọi hàm này). Dùng chung bởi create_order (lệnh lọc phẳng cũ, master_order_id=None) và
    create_master_order/update_master_order (nhiều lệnh nhỏ trong 1 lệnh lớn)."""
    order = FilterOrder(filter_order_id=new_id(), order_code=order_code, order_year=order_year,
                        master_order_id=master_order_id,
                        seq=seq, blend_mode=blend_mode, note=note, kcs_lot_no=kcs_lot_no,
                        planned_volume_hl=planned_volume_hl, volume_tolerance_hl=volume_tolerance_hl,
                        beer_type_id=beer_type_id, finished_product_id=finished_product_id,
                        created_by=user.username, created_at=utcnow())
    db.add(order)
    db.flush()

    for i, s in enumerate(sources):
        if s["tank_type"] == "bbt":
            db.add(FilterOrderTank(line_id=new_id(), filter_order_id=order.filter_order_id,
                                   tank_type="bbt", source_bbt_code=s["source_bbt_code"], reason=s["reason"],
                                   seq=i + 1, planned_v_dich_hl=s.get("planned_v_dich_hl", 0.0)))
        else:
            db.add(FilterOrderTank(line_id=new_id(), filter_order_id=order.filter_order_id,
                                   tank_type="cct", ferment_id=s["ferment"].ferment_id, seq=i + 1,
                                   planned_v_dich_hl=s.get("planned_v_dich_hl", 0.0)))

    for i, ml in enumerate(material_lines):
        db.add(_material_line_row(order.filter_order_id, i, ml))
    return order


def create_order(db: Session, payload: dict, user) -> FilterOrder:
    """Lệnh lọc phẳng (cũ, không thuộc lệnh lớn) — CHỈ hỗ trợ nguồn tank lên men, không hỗ
    trợ lọc lại tank BBT (schema FilterOrderIn.tank_ferment_ids là danh sách phẳng, không
    phân biệt loại nguồn) — frontend hiện không dùng path này nữa (đã chuyển hẳn sang
    filter-master-orders, xem create_master_order), giữ lại cho tương thích ngược API/test."""
    tank_ferment_ids = payload.pop("tank_ferment_ids")
    lines_in = payload.pop("lines", None) or []
    blend_mode = payload.get("blend_mode", "khong_phoi")

    tanks_in = [{"tank_type": "cct", "ferment_id": fid} for fid in tank_ferment_ids]
    sources, beer_type_id = _validate_tanks(db, blend_mode, tanks_in, payload.get("beer_type_id"))
    finished_product_id = _validate_finished_product(db, payload.get("finished_product_id"))
    for s in sources:
        s["planned_v_dich_hl"] = 0.0
    material_lines = _validate_material_lines(db, lines_in)
    _validate_volume_plan(payload.get("planned_volume_hl"), payload.get("volume_tolerance_hl"))

    order_code = payload["order_code"]
    order_year = utcnow().year
    if db.execute(select(FilterOrder).where(FilterOrder.order_code == order_code,
                  FilterOrder.order_year == order_year)).first():
        raise DomainError(f"Số lệnh '{order_code}' đã tồn tại trong năm {order_year}.")

    order = _insert_sub_order(db, None, 1, order_code, order_year, blend_mode,
                              payload.get("note"), payload.get("kcs_lot_no"),
                              payload.get("planned_volume_hl", 0.0), payload.get("volume_tolerance_hl", 0.0),
                              sources, material_lines, user, beer_type_id=beer_type_id,
                              finished_product_id=finished_product_id)

    record_audit(db, entity_type="filter_order", entity_id=order.filter_order_id, action="create",
                 actor=user, after={"order_code": order.order_code, "tanks": len(sources), "materials": len(material_lines)})
    db.commit()
    db.refresh(order)
    return order


def update_order(db: Session, filter_order_id: str, payload: dict, user) -> FilterOrder:
    """Sửa lại lệnh lọc CHƯA thực hiện (chưa có FilterRecord) — cho phép sửa toàn bộ (số
    lệnh, loại lọc, tank, ghi chú, danh sách vật tư); tồn kho vật tư được kiểm tra lại đúng
    như lúc tạo mới (xem create_order/_validate_material_lines)."""
    order = db.get(FilterOrder, filter_order_id)
    if not order:
        raise NotFoundError("Lệnh lọc không tồn tại.")
    if db.execute(select(FilterRecord).where(FilterRecord.filter_order_id == filter_order_id)).first():
        raise DomainError("Lệnh lọc đã được thực hiện — không thể sửa.")

    tank_ferment_ids = payload.pop("tank_ferment_ids")
    lines_in = payload.pop("lines", None) or []
    blend_mode = payload.get("blend_mode", "khong_phoi")
    new_code = payload.get("order_code")

    if new_code != order.order_code and db.execute(
            select(FilterOrder).where(FilterOrder.order_code == new_code,
                    FilterOrder.order_year == order.order_year)).first():
        raise DomainError(f"Số lệnh '{new_code}' đã tồn tại trong năm {order.order_year}.")

    tanks_in = [{"tank_type": "cct", "ferment_id": fid} for fid in tank_ferment_ids]
    sources, beer_type_id = _validate_tanks(db, blend_mode, tanks_in, payload.get("beer_type_id"))
    finished_product_id = _validate_finished_product(db, payload.get("finished_product_id"))
    for s in sources:
        s["planned_v_dich_hl"] = 0.0
    material_lines = _validate_material_lines(db, lines_in)
    _validate_volume_plan(payload.get("planned_volume_hl"), payload.get("volume_tolerance_hl"))

    for l in db.execute(select(FilterOrderTank).where(
            FilterOrderTank.filter_order_id == filter_order_id)).scalars().all():
        db.delete(l)
    for l in db.execute(select(FilterOrderMaterialLine).where(
            FilterOrderMaterialLine.filter_order_id == filter_order_id)).scalars().all():
        db.delete(l)
    db.flush()

    order.order_code = new_code
    order.blend_mode = blend_mode
    order.note = payload.get("note")
    order.kcs_lot_no = payload.get("kcs_lot_no")
    order.planned_volume_hl = payload.get("planned_volume_hl")
    order.volume_tolerance_hl = payload.get("volume_tolerance_hl")
    order.beer_type_id = beer_type_id
    order.finished_product_id = finished_product_id

    for i, s in enumerate(sources):
        db.add(FilterOrderTank(line_id=new_id(), filter_order_id=order.filter_order_id,
                               tank_type="cct", ferment_id=s["ferment"].ferment_id, seq=i + 1))

    for i, ml in enumerate(material_lines):
        db.add(_material_line_row(order.filter_order_id, i, ml))

    record_audit(db, entity_type="filter_order", entity_id=order.filter_order_id, action="update",
                 actor=user, after={"order_code": order.order_code, "tanks": len(sources), "materials": len(material_lines)})
    db.commit()
    db.refresh(order)
    return order


def _material_line_summaries(db: Session, filter_order_id: str) -> list:
    """`stock_company_snapshot`/`stock_workshop_snapshot` là tồn LÚC LẬP PHIẾU (đúng tính
    chất văn bản đã ký/in); `member_breakdown` (chỉ có ở dòng Nhóm vật tư thay thế) là tồn
    TỪNG mã thành viên tính LIVE — nhóm có thể đổi thành viên/tồn sau khi lệnh đã lập, xem
    _resolve_group_members/_member_breakdown."""
    lines = db.execute(select(FilterOrderMaterialLine).where(
        FilterOrderMaterialLine.filter_order_id == filter_order_id).order_by(FilterOrderMaterialLine.seq)).scalars().all()
    out = []
    for l in lines:
        member_ids = _resolve_group_members(db, l.material_group_code)
        out.append({"line_id": l.line_id, "material_id": l.material_id, "material_name": l.material_name,
                    "material_group_code": l.material_group_code,
                    "member_breakdown": _member_breakdown(db, member_ids) if member_ids else [],
                    "uom": l.uom, "quantity": l.quantity, "unit_price": l.unit_price,
                    "stock_company_snapshot": l.stock_company_snapshot,
                    "stock_workshop_snapshot": l.stock_workshop_snapshot})
    return out


def _tank_summaries(db: Session, filter_order_id: str) -> list:
    """Tank NGUỒN của lệnh — chỉ lấy dòng "template" (filter_id NULL, tạo lúc lập lệnh),
    KHÔNG lấy các dòng nhân bản riêng cho từng FilterRecord (xem FilterOrderTank). Nguồn có
    thể là tank lên men (tank_type="cct") hoặc tank BBT đang lọc lại (tank_type="bbt") —
    giữ key `tank_lm`/`lm_code` = None cho dòng BBT để code cũ chưa cập nhật không vỡ."""
    lines = db.execute(select(FilterOrderTank).where(
        FilterOrderTank.filter_order_id == filter_order_id,
        FilterOrderTank.filter_id.is_(None)).order_by(FilterOrderTank.seq)).scalars().all()
    out = []
    for l in lines:
        if l.tank_type == "bbt":
            source_on_hand_bbt = round(sum(
                r.on_hand_bbt for r in db.execute(select(FilterRecord).where(
                    FilterRecord.to_bbt == l.source_bbt_code)).scalars().all()), 3)
            out.append({"line_id": l.line_id, "tank_type": "bbt", "ferment_id": None,
                        "tank_lm": None, "lm_code": None, "seq": l.seq,
                        "source_bbt_code": l.source_bbt_code, "reason": l.reason,
                        "source_on_hand_bbt": source_on_hand_bbt,
                        "planned_v_dich_hl": l.planned_v_dich_hl,
                        "ended_at": l.ended_at, "v_dich_hl": l.v_dich_hl, "nuoc_bai_khi_hl": l.nuoc_bai_khi_hl})
        else:
            ferment = db.get(FermentRecord, l.ferment_id)
            out.append({"line_id": l.line_id, "tank_type": "cct", "ferment_id": l.ferment_id,
                        "tank_lm": ferment.tank_lm if ferment else None, "lm_code": ferment.lm_code if ferment else None,
                        "seq": l.seq, "source_bbt_code": None, "reason": None, "source_on_hand_bbt": None,
                        "planned_v_dich_hl": l.planned_v_dich_hl,
                        "ended_at": l.ended_at, "v_dich_hl": l.v_dich_hl, "nuoc_bai_khi_hl": l.nuoc_bai_khi_hl})
    return out


def _representative_product(db: Session, tanks: list, products: dict = None) -> Optional[Product]:
    """Dịch bia đại diện để hiển thị product_code — tank đầu tiên còn dữ liệu (CCT: qua
    FermentRecord.product_id; BBT: qua FilterRecord đại diện mới nhất của source_bbt_code)."""
    for t in tanks:
        if t.get("tank_type", "cct") == "cct" and t.get("ferment_id"):
            f = db.get(FermentRecord, t["ferment_id"])
            if f and f.product_id:
                return (products or {}).get(f.product_id) or db.get(Product, f.product_id)
        elif t.get("tank_type") == "bbt" and t.get("source_bbt_code"):
            rep = db.execute(select(FilterRecord).where(FilterRecord.to_bbt == t["source_bbt_code"])
                             .order_by(FilterRecord.filter_date.desc())).scalars().first()
            if rep and rep.product_id:
                return (products or {}).get(rep.product_id) or db.get(Product, rep.product_id)
    return None


def _record_summaries(db: Session, filter_order_id: str) -> list:
    """TẤT CẢ FilterRecord của lệnh (1 lệnh có thể có nhiều bản ghi/"mẻ lọc" cộng dồn tới
    thể tích kế hoạch — xem routers/brewing.py::add_filter)."""
    records = db.execute(select(FilterRecord).where(
        FilterRecord.filter_order_id == filter_order_id).order_by(FilterRecord.filter_date)).scalars().all()
    return [{"filter_id": r.filter_id, "filter_code": r.filter_code, "to_bbt": r.to_bbt,
            "v_beer_hl": r.v_beer_hl, "ended_at": r.ended_at,
            "batch_number": r.batch_number, "order_number": r.order_number} for r in records]


def _actual_volume_hl(records: list) -> float:
    return round(sum(r["v_beer_hl"] or 0.0 for r in records), 3)


def _is_complete(records: list, planned_volume_hl: float, tolerance_hl: float) -> bool:
    """Hoàn thành khi ĐÃ có ít nhất 1 mẻ lọc, tổng sản lượng thực tế (v_beer_hl, đã gồm nước
    bài khí, cộng dồn qua tất cả mẻ lọc của lệnh) đạt kế hoạch trong sai số cho phép (thực tế
    >= kế hoạch - sai số) HOẶC đã vượt kế hoạch (thực tế >= kế hoạch) — chỉ chặn hoàn thành
    khi còn HỤT quá sai số, KHÔNG chặn khi vượt kế hoạch (một chiều, không còn kiểu ±sai số 2
    chiều như trước, dễ hiểu nhầm "vượt kế hoạch" thành "chưa xong") — VÀ tất cả mẻ lọc đó đã
    bấm "Kết thúc" (ended_at) — sản lượng đã khớp/vượt nhưng còn mẻ đang lọc dở dang thì lệnh
    vẫn coi như đang thực hiện, chưa hoàn thành. Mirror services/brew_order.py::_is_complete.
    Xem routers/brewing.py::add_filter (chặn tạo mẻ mới khi đã hoàn thành)."""
    if not records:
        return False
    if _actual_volume_hl(records) < planned_volume_hl - tolerance_hl:
        return False
    return all(r["ended_at"] is not None for r in records)


def _chiet_started(db: Session, filter_order_id: str) -> bool:
    """Lệnh đã bắt đầu chiết khi có ít nhất 1 BottleRecord tham chiếu filter_id của MỘT trong
    các mẻ lọc (FilterRecord) thuộc lệnh này (xem BottleRecord.filter_id, gán trong
    routers/brewing.py::add_bottle khi chiết chọn tank BBT nguồn) — mirror khái niệm
    "dang_chiet"/"da_ket_thuc" của lo_status.py nhưng scope theo 1 FilterOrder thay vì cả mã
    nấu. Dùng để chặn tạo thêm mẻ lọc mới ở routers/brewing.py::add_filter — theo yêu cầu
    nghiệp vụ: lô ĐANG CHIẾT rồi thì không cho thêm mẻ lọc nữa, chỉ được thêm khi còn ĐANG LỌC
    (chưa có mẻ nào bị lấy đi chiết)."""
    filter_ids = db.execute(select(FilterRecord.filter_id).where(
        FilterRecord.filter_order_id == filter_order_id)).scalars().all()
    if not filter_ids:
        return False
    return db.execute(select(BottleRecord.bottle_id).where(
        BottleRecord.filter_id.in_(filter_ids))).first() is not None


def list_orders(db: Session) -> list:
    orders = db.execute(select(FilterOrder).order_by(FilterOrder.created_at.desc())).scalars().all()
    products = {p.product_id: p for p in db.execute(select(Product)).scalars().all()}
    masters = {m.filter_master_order_id: m for m in db.execute(select(FilterMasterOrder)).scalars().all()}
    out = []
    for o in orders:
        records = _record_summaries(db, o.filter_order_id)
        tanks = _tank_summaries(db, o.filter_order_id)
        prod = _representative_product(db, tanks, products)
        master = masters.get(o.master_order_id)
        beer_type = db.get(BeerType, o.beer_type_id) if o.beer_type_id else None
        finished_product = db.get(FinishedProduct, o.finished_product_id) if o.finished_product_id else None
        out.append({
            "filter_order_id": o.filter_order_id, "order_code": o.order_code, "blend_mode": o.blend_mode,
            "master_order_id": o.master_order_id, "master_order_code": master.order_code if master else None,
            "seq": o.seq,
            "note": o.note, "created_at": o.created_at, "tanks": tanks,
            "product_code": prod.code if prod else None,
            "beer_type_id": o.beer_type_id,
            "beer_type_code": beer_type.code if beer_type else None,
            "beer_type_name": beer_type.name if beer_type else None,
            "finished_product_id": o.finished_product_id,
            "finished_product_code": finished_product.code if finished_product else None,
            "finished_product_name": finished_product.name if finished_product else None,
            "kcs_lot_no": o.kcs_lot_no, "records": records,
            "planned_volume_hl": o.planned_volume_hl, "volume_tolerance_hl": o.volume_tolerance_hl,
            "actual_volume_hl": _actual_volume_hl(records),
            "is_executed": len(records) > 0,
            "is_complete": _is_complete(records, o.planned_volume_hl, o.volume_tolerance_hl),
            "chiet_started": _chiet_started(db, o.filter_order_id),
            "locked": o.locked, "locked_by": o.locked_by,
        })
    return out


def get_order(db: Session, filter_order_id: str) -> dict:
    order = db.get(FilterOrder, filter_order_id)
    if not order:
        raise NotFoundError("Lệnh lọc không tồn tại.")
    records = _record_summaries(db, filter_order_id)
    tanks = _tank_summaries(db, filter_order_id)
    product = _representative_product(db, tanks)
    master = db.get(FilterMasterOrder, order.master_order_id) if order.master_order_id else None
    beer_type = db.get(BeerType, order.beer_type_id) if order.beer_type_id else None
    finished_product = db.get(FinishedProduct, order.finished_product_id) if order.finished_product_id else None
    return {
        "filter_order_id": order.filter_order_id, "order_code": order.order_code,
        "blend_mode": order.blend_mode, "note": order.note,
        "master_order_id": order.master_order_id, "master_order_code": master.order_code if master else None,
        "seq": order.seq,
        "kcs_lot_no": order.kcs_lot_no,
        "product_code": product.code if product else None,
        "beer_type_id": order.beer_type_id,
        "beer_type_code": beer_type.code if beer_type else None,
        "beer_type_name": beer_type.name if beer_type else None,
        "finished_product_id": order.finished_product_id,
        "finished_product_code": finished_product.code if finished_product else None,
        "created_by": order.created_by, "created_at": order.created_at,
        "tanks": tanks,
        "lines": _material_line_summaries(db, filter_order_id),
        "records": records,
        "planned_volume_hl": order.planned_volume_hl, "volume_tolerance_hl": order.volume_tolerance_hl,
        "actual_volume_hl": _actual_volume_hl(records),
        "is_executed": len(records) > 0,
        "is_complete": _is_complete(records, order.planned_volume_hl, order.volume_tolerance_hl),
        "chiet_started": _chiet_started(db, filter_order_id),
        "locked": order.locked, "locked_by": order.locked_by,
    }


def delete_order(db: Session, filter_order_id: str, user) -> None:
    order = db.get(FilterOrder, filter_order_id)
    if not order:
        raise NotFoundError("Lệnh lọc không tồn tại.")
    if db.execute(select(FilterRecord).where(FilterRecord.filter_order_id == filter_order_id)).first():
        raise DomainError("Lệnh lọc đã được thực hiện — không thể xóa.")
    for l in db.execute(select(FilterOrderTank).where(
            FilterOrderTank.filter_order_id == filter_order_id)).scalars().all():
        db.delete(l)
    for l in db.execute(select(FilterOrderMaterialLine).where(
            FilterOrderMaterialLine.filter_order_id == filter_order_id)).scalars().all():
        db.delete(l)
    db.flush()  # MSSQL enforce FK: xóa tank/material line (con) trước filter_order (cha).
    record_audit(db, entity_type="filter_order", entity_id=filter_order_id, action="delete",
                 actor=user, before={"order_code": order.order_code})
    db.delete(order)
    db.commit()


# ===== Lệnh lọc LỚN (FilterMasterOrder — chứa nhiều "lệnh lọc nhỏ" FilterOrder) =====

def _child_summary(db: Session, order: FilterOrder, products: dict) -> dict:
    records = _record_summaries(db, order.filter_order_id)
    tanks = _tank_summaries(db, order.filter_order_id)
    prod = _representative_product(db, tanks, products)
    beer_type = db.get(BeerType, order.beer_type_id) if order.beer_type_id else None
    finished_product = db.get(FinishedProduct, order.finished_product_id) if order.finished_product_id else None
    return {
        "filter_order_id": order.filter_order_id, "seq": order.seq, "blend_mode": order.blend_mode,
        "kcs_lot_no": order.kcs_lot_no, "tanks": tanks,
        "product_code": prod.code if prod else None,
        "beer_type_id": order.beer_type_id,
        "beer_type_code": beer_type.code if beer_type else None,
        "beer_type_name": beer_type.name if beer_type else None,
        "finished_product_id": order.finished_product_id,
        "finished_product_code": finished_product.code if finished_product else None,
        "records": records,
        "planned_volume_hl": order.planned_volume_hl, "volume_tolerance_hl": order.volume_tolerance_hl,
        "actual_volume_hl": _actual_volume_hl(records),
        "is_executed": len(records) > 0,
        "is_complete": _is_complete(records, order.planned_volume_hl, order.volume_tolerance_hl),
        "chiet_started": _chiet_started(db, order.filter_order_id),
        "locked": order.locked, "locked_by": order.locked_by,
    }


def _bbt_tank_on_hand(db: Session, source_bbt_code: str) -> float:
    """Tổng on_hand_bbt của MỌI FilterRecord cùng to_bbt — "tồn thật" của 1 tank BBT vật lý
    (không phải giá trị của 1 mẻ lọc cụ thể, vì 1 tank có thể được lọc phối nhiều mẻ)."""
    return sum(r.on_hand_bbt for r in db.execute(
        select(FilterRecord).where(FilterRecord.to_bbt == source_bbt_code)).scalars().all())


def _bbt_target_blocked_by(db: Session, code: str) -> Optional[str]:
    """Lý do chặn (string) nếu tank BBT `code` KHÔNG THỂ nhận thêm mẻ lọc mới đổ vào — dùng khi
    chọn tank ĐÍCH lúc tạo MẺ LỌC ĐẦU TIÊN của 1 lệnh, HOẶC khi 1 lệnh đã có mẻ trước nhưng mẻ
    gần nhất của lệnh đó đã "kết thúc" (ended_at) và vận hành muốn đổi sang tank khác (tank cũ
    bé, lọc tràn sang tank mới — xem routers/brewing.py::add_filter).

    Nhiều Lệnh lọc KHÁC NHAU được phép cùng đổ vào 1 tank vật lý (thể tích cộng dồn — xem
    available_bbt_tanks) MIỄN LÀ chưa có mẻ lọc nào trong tank được KCS duyệt: vận hành nhà
    máy chủ động dùng chung 1 tank BBT cho nhiều mẻ lọc/nhiều lệnh trước khi khoá lại bằng
    duyệt KCS. Bị chặn khi: (1) tank ĐANG có mẻ lọc chưa "kết thúc" (ended_at rỗng) — về mặt
    vật lý không thể vừa rót mẻ này vừa cho mẻ khác (của bất kỳ lệnh nào) vào cùng lúc, phải
    đợi mẻ đang dở kết thúc trước; HOẶC (2) tank còn dịch (tổng on_hand_bbt của mọi mẻ cùng
    to_bbt > 0) VÀ có ít nhất 1 mẻ lọc trong tank đã được KCS duyệt (qc_approved) — từ lúc đó
    tank coi như đã khoá, chỉ còn chờ chiết ra, không nhận thêm mẻ lọc mới. Tank đã chiết hết
    (tổng on_hand_bbt = 0) luôn tự do trở lại, bất kể lịch sử duyệt trước đó."""
    recs = db.execute(select(FilterRecord).where(FilterRecord.to_bbt == code)).scalars().all()
    if not recs:
        return None
    if any(r.ended_at is None for r in recs):
        return f"Tank BBT {code} đang có mẻ lọc chưa kết thúc — chờ kết thúc mẻ đó trước khi thêm mẻ mới vào tank này."
    on_hand = sum(r.on_hand_bbt for r in recs)
    if on_hand <= 1e-6:
        return None
    if any(r.qc_approved for r in recs):
        return f"Tank BBT {code} đã được KCS duyệt — không thể lọc thêm vào, chỉ có thể chiết ra."
    return None


def _bbt_mix_warning(db: Session, code: str, beer_type_id: Optional[str]) -> Optional[str]:
    """Cảnh báo (KHÔNG chặn — khác _bbt_target_blocked_by) nếu tank BBT `code` đang còn dịch
    (on_hand_bbt > 0) của 1 Loại bia KHÁC với Loại bia sắp lọc vào — vận hành vẫn được phép đổ
    chung (thể tích cộng dồn, xem available_bbt_tanks) nhưng cần biết để tránh trộn lẫn nhầm
    loại bia thật sự khác nhau khi chưa có chỉ tiêu bắt buộc nào chặn việc này lại."""
    if not beer_type_id:
        return None
    recs = db.execute(select(FilterRecord).where(FilterRecord.to_bbt == code)).scalars().all()
    other_types = {r.beer_type_id for r in recs if r.beer_type_id and r.beer_type_id != beer_type_id and r.on_hand_bbt > 1e-6}
    if not other_types:
        return None
    names = [bt.name for bt in (db.get(BeerType, bid) for bid in other_types) if bt]
    return (f"⚠ Tank BBT {code} đang còn dịch của Loại bia khác ({', '.join(names) or 'không rõ'}) — "
            "kiểm tra kỹ để tránh trộn lẫn nhầm loại bia.")


def _bbt_reserved_volume(db: Session, source_bbt_code: str, exclude_order_ids: set = None) -> float:
    """Tổng thể tích đang bị các Lệnh lọc lọc-lại CHƯA HOÀN THÀNH 'giữ chỗ' trên 1 tank BBT
    vật lý — chỉ tính dòng TEMPLATE (filter_id IS NULL, đại diện kế hoạch của cả lệnh) của
    các FilterOrder CHƯA is_complete (đã complete thì phần tiêu thụ đã phản ánh qua
    on_hand_bbt rồi, không cần giữ chỗ nữa). Đây là cơ chế CHẶN CHIẾT ngay từ lúc LẬP LỆNH
    (không đợi tới lúc thực hiện mẻ lọc thật) — xem routers/brewing.py::add_bottle và
    available_bbt_tanks. Xấp xỉ BẢO THỦ: 1 lệnh đã lọc được MỘT PHẦN cho tank này (chưa
    complete) vẫn tính đủ planned_v_dich_hl — thiên về CHẶN quá mức còn hơn thiếu, an toàn
    hơn cho vận hành."""
    rows = db.execute(select(FilterOrderTank).where(
        FilterOrderTank.tank_type == "bbt", FilterOrderTank.source_bbt_code == source_bbt_code,
        FilterOrderTank.filter_id.is_(None))).scalars().all()
    total = 0.0
    for l in rows:
        if exclude_order_ids and l.filter_order_id in exclude_order_ids:
            continue
        order = db.get(FilterOrder, l.filter_order_id)
        if not order:
            continue
        records = _record_summaries(db, order.filter_order_id)
        if _is_complete(records, order.planned_volume_hl, order.volume_tolerance_hl):
            continue
        total += l.planned_v_dich_hl
    return total


def available_bbt_tanks(db: Session) -> list:
    """Tổng hợp THEO TỪNG TANK BBT VẬT LÝ (mã to_bbt) — dùng chung bởi (1) picker chọn tank
    BBT nguồn khi "lọc lại" (Tạo Lệnh lọc) và (2) điều kiện chiết: tank phải đã lọc xong
    (all_finished, mọi FilterRecord cùng to_bbt có ended_at) + đã KCS duyệt hết
    (all_qc_approved) + KHÔNG đang bị giữ chỗ lọc lại (reserved_hl<=0) mới được chiết."""
    records = db.execute(select(FilterRecord).where(FilterRecord.to_bbt.isnot(None))).scalars().all()
    by_code: dict = {}
    for r in records:
        by_code.setdefault(r.to_bbt, []).append(r)
    out = []
    for code, recs in by_code.items():
        on_hand = round(sum(r.on_hand_bbt for r in recs), 3)
        all_qc = all(r.qc_approved for r in recs)
        any_qc = any(r.qc_approved for r in recs)
        all_fin = all(r.ended_at is not None for r in recs)
        rep = max(recs, key=lambda r: r.filter_date)
        reserved = round(_bbt_reserved_volume(db, code), 3)
        finished_product = db.get(FinishedProduct, rep.finished_product_id) if rep.finished_product_id else None
        out.append({
            "to_bbt": code, "on_hand_bbt": on_hand, "all_qc_approved": all_qc, "any_qc_approved": any_qc,
            "all_finished": all_fin,
            "beer_type_id": rep.beer_type_id, "beer_type": rep.beer_type, "product_id": rep.product_id,
            "finished_product_id": rep.finished_product_id,
            "finished_product_code": finished_product.code if finished_product else None,
            "finished_product_name": finished_product.name if finished_product else None,
            "reserved_hl": reserved, "remaining_hl": round(max(0.0, on_hand - reserved), 3),
            "eligible_for_chiet": on_hand > 1e-6 and all_qc and all_fin and reserved <= 1e-6,
            "eligible_for_refilter_source": on_hand > 1e-6 and all_qc and all_fin,
        })
    return out


def _validate_children(db: Session, children_in: list, exclude_order_ids: set = None) -> list:
    """Validate TOÀN BỘ lệnh nhỏ TRƯỚC khi ghi bất kỳ dòng nào (tránh tạo dở dang nếu 1
    lệnh nhỏ ở giữa danh sách bị lỗi). Mỗi tank NGUỒN (lên men hoặc BBT lọc lại) trong 1
    lệnh nhỏ tự khai báo thể tích dịch lọc kế hoạch RIÊNG (child["tanks"]); planned_volume_hl
    của lệnh nhỏ = cộng dồn các tank đó. Sau khi validate từng lệnh nhỏ, kiểm tra CHÉO: (1)
    nếu 2+ lệnh nhỏ cùng dùng 1 tank CCT (trong cùng 1 lần tạo/sửa lệnh lớn này), tổng kế
    hoạch trên tank đó không được vượt quá tồn CCT thật; (2) nếu 1+ lệnh nhỏ dùng 1 tank BBT
    làm nguồn lọc lại, tổng kế hoạch + phần đã bị lệnh khác (CROSS-ORDER, không chỉ trong
    lần gọi này) giữ chỗ không được vượt quá tồn thật của tank BBT đó — mạnh hơn check CCT
    vì đây là cơ chế chặn chiết từ lúc lập lệnh (xem _bbt_reserved_volume).
    `exclude_order_ids`: dùng khi sửa 1 lệnh lớn đã có sẵn — bỏ qua phần lệnh nhỏ CŨ của
    chính lệnh lớn đang sửa khi tính "đã bị giữ chỗ", tránh tự chặn chính mình."""
    if not children_in:
        raise DomainError("Lệnh lọc lớn phải có ít nhất 1 lệnh lọc nhỏ.")
    validated = []
    ferment_by_id: dict = {}
    total_planned_by_ferment: dict = {}
    total_planned_by_bbt: dict = {}
    for child in children_in:
        blend_mode = child.get("blend_mode", "khong_phoi")
        tanks_in = child.get("tanks") or []
        _validate_tank_plans(tanks_in)
        sources, beer_type_id = _validate_tanks(db, blend_mode, tanks_in, child.get("beer_type_id"))
        finished_product_id = _validate_finished_product(db, child.get("finished_product_id"))
        material_lines = _validate_material_lines(db, child.get("lines") or [])
        for s, t in zip(sources, tanks_in):
            s["planned_v_dich_hl"] = t["planned_v_dich_hl"]
        planned_volume_hl = round(sum(s["planned_v_dich_hl"] for s in sources), 3)
        _validate_volume_plan(planned_volume_hl, child.get("volume_tolerance_hl"))
        for s in sources:
            if s["tank_type"] == "cct":
                fid = s["ferment"].ferment_id
                ferment_by_id[fid] = s["ferment"]
                total_planned_by_ferment[fid] = total_planned_by_ferment.get(fid, 0.0) + s["planned_v_dich_hl"]
            else:
                code = s["source_bbt_code"]
                total_planned_by_bbt[code] = total_planned_by_bbt.get(code, 0.0) + s["planned_v_dich_hl"]
        validated.append((child, sources, material_lines, planned_volume_hl, beer_type_id, finished_product_id))

    for fid, total in total_planned_by_ferment.items():
        f = ferment_by_id[fid]
        if total > f.on_hand_cct + 1e-6:
            raise DomainError(
                f"Tank {f.tank_lm} (lô LM {f.lm_code}) chỉ còn tồn {f.on_hand_cct} hl CCT nhưng tổng kế hoạch "
                f"các lệnh lọc nhỏ đang yêu cầu {round(total, 3)} hl — giảm bớt thể tích kế hoạch.")

    for code, total in total_planned_by_bbt.items():
        on_hand = _bbt_tank_on_hand(db, code)
        reserved_elsewhere = _bbt_reserved_volume(db, code, exclude_order_ids=exclude_order_ids)
        if total + reserved_elsewhere > on_hand + 1e-6:
            raise DomainError(
                f"Tank BBT {code} chỉ còn khả dụng {round(on_hand - reserved_elsewhere, 3)} hl để lọc lại "
                f"nhưng tổng kế hoạch đang yêu cầu {round(total, 3)} hl.")
    return validated


def _insert_children(db: Session, master_order_id: str, order_year: int, validated: list, user) -> list:
    orders = []
    for seq, (child, sources, material_lines, planned_volume_hl, beer_type_id, finished_product_id) in enumerate(validated, start=1):
        order = _insert_sub_order(db, master_order_id, seq, f"SUB-{new_id()[:12]}", order_year,
                                  child.get("blend_mode", "khong_phoi"), None, child.get("kcs_lot_no"),
                                  planned_volume_hl, child.get("volume_tolerance_hl", 0.0),
                                  sources, material_lines, user, beer_type_id=beer_type_id,
                                  finished_product_id=finished_product_id)
        orders.append(order)
    return orders


def _delete_children(db: Session, children: list) -> None:
    for o in children:
        for l in db.execute(select(FilterOrderTank).where(
                FilterOrderTank.filter_order_id == o.filter_order_id)).scalars().all():
            db.delete(l)
        for l in db.execute(select(FilterOrderMaterialLine).where(
                FilterOrderMaterialLine.filter_order_id == o.filter_order_id)).scalars().all():
            db.delete(l)
        db.flush()  # MSSQL enforce FK: tank/material line (con) trước filter_order (cha).
        db.delete(o)
    db.flush()  # ... và filter_order (con) trước filter_master_order (cha).


def create_master_order(db: Session, payload: dict, user) -> FilterMasterOrder:
    order_code = payload["order_code"]
    order_year = utcnow().year
    if db.execute(select(FilterMasterOrder).where(FilterMasterOrder.order_code == order_code,
                  FilterMasterOrder.order_year == order_year)).first():
        raise DomainError(f"Số lệnh '{order_code}' đã tồn tại trong năm {order_year}.")
    validated = _validate_children(db, payload.get("children") or [])

    master = FilterMasterOrder(filter_master_order_id=new_id(), order_code=order_code, order_year=order_year,
                               note=payload.get("note"), created_by=user.username, created_at=utcnow())
    db.add(master)
    db.flush()
    orders = _insert_children(db, master.filter_master_order_id, master.order_year, validated, user)

    record_audit(db, entity_type="filter_master_order", entity_id=master.filter_master_order_id, action="create",
                 actor=user, after={"order_code": master.order_code, "children": len(orders)})
    db.commit()
    db.refresh(master)
    return master


def list_master_orders(db: Session, years=None) -> list:
    years = resolve_years(years)
    stmt = select(FilterMasterOrder)
    if years:
        stmt = stmt.where(FilterMasterOrder.order_year.in_(years))
    masters = db.execute(stmt.order_by(FilterMasterOrder.created_at.desc())).scalars().all()
    products = {p.product_id: p for p in db.execute(select(Product)).scalars().all()}
    out = []
    for m in masters:
        children_rows = db.execute(select(FilterOrder).where(
            FilterOrder.master_order_id == m.filter_master_order_id).order_by(FilterOrder.seq)).scalars().all()
        children = [_child_summary(db, o, products) for o in children_rows]
        out.append({
            "filter_master_order_id": m.filter_master_order_id, "order_code": m.order_code,
            "note": m.note, "created_by": m.created_by, "created_at": m.created_at,
            "children": children,
            "planned_total_hl": round(sum(c["planned_volume_hl"] for c in children), 3),
            "actual_total_hl": round(sum(c["actual_volume_hl"] for c in children), 3),
            "is_executed_any": any(c["is_executed"] for c in children),
            "is_complete_all": bool(children) and all(c["is_complete"] for c in children),
            "locked": m.locked, "locked_by": m.locked_by,
        })
    return out


def get_master_order(db: Session, filter_master_order_id: str) -> dict:
    m = db.get(FilterMasterOrder, filter_master_order_id)
    if not m:
        raise NotFoundError("Lệnh lọc không tồn tại.")
    products = {p.product_id: p for p in db.execute(select(Product)).scalars().all()}
    children_rows = db.execute(select(FilterOrder).where(
        FilterOrder.master_order_id == filter_master_order_id).order_by(FilterOrder.seq)).scalars().all()
    children = []
    for o in children_rows:
        summary = _child_summary(db, o, products)
        summary["lines"] = _material_line_summaries(db, o.filter_order_id)
        children.append(summary)
    return {
        "filter_master_order_id": m.filter_master_order_id, "order_code": m.order_code,
        "note": m.note, "created_by": m.created_by, "created_at": m.created_at,
        "children": children,
        "planned_total_hl": round(sum(c["planned_volume_hl"] for c in children), 3),
        "actual_total_hl": round(sum(c["actual_volume_hl"] for c in children), 3),
        "is_executed_any": any(c["is_executed"] for c in children),
        "is_complete_all": bool(children) and all(c["is_complete"] for c in children),
        "locked": m.locked, "locked_by": m.locked_by,
    }


def update_master_order(db: Session, filter_master_order_id: str, payload: dict, user) -> FilterMasterOrder:
    """Sửa lệnh lọc lớn — chỉ cho phép khi CHƯA có lệnh nhỏ nào được thực hiện (có
    FilterRecord); xoá hết lệnh nhỏ cũ (tank/vật tư) rồi tạo lại từ children mới, mirror
    cách update_order xoá-rồi-tạo-lại tank/vật tư của 1 lệnh nhỏ."""
    master = db.get(FilterMasterOrder, filter_master_order_id)
    if not master:
        raise NotFoundError("Lệnh lọc không tồn tại.")
    old_children = db.execute(select(FilterOrder).where(
        FilterOrder.master_order_id == filter_master_order_id)).scalars().all()
    for o in old_children:
        if db.execute(select(FilterRecord).where(FilterRecord.filter_order_id == o.filter_order_id)).first():
            raise DomainError("Lệnh lọc đã được thực hiện — không thể sửa.")

    order_code = payload["order_code"]
    if order_code != master.order_code and db.execute(
            select(FilterMasterOrder).where(FilterMasterOrder.order_code == order_code,
                    FilterMasterOrder.order_year == master.order_year)).first():
        raise DomainError(f"Số lệnh '{order_code}' đã tồn tại trong năm {master.order_year}.")

    validated = _validate_children(db, payload.get("children") or [],
                                   exclude_order_ids={o.filter_order_id for o in old_children})

    _delete_children(db, old_children)
    db.flush()

    master.order_code = order_code
    master.note = payload.get("note")
    orders = _insert_children(db, master.filter_master_order_id, master.order_year, validated, user)

    record_audit(db, entity_type="filter_master_order", entity_id=master.filter_master_order_id, action="update",
                 actor=user, after={"order_code": master.order_code, "children": len(orders)})
    db.commit()
    db.refresh(master)
    return master


def delete_master_order(db: Session, filter_master_order_id: str, user) -> None:
    master = db.get(FilterMasterOrder, filter_master_order_id)
    if not master:
        raise NotFoundError("Lệnh lọc không tồn tại.")
    children = db.execute(select(FilterOrder).where(
        FilterOrder.master_order_id == filter_master_order_id)).scalars().all()
    for o in children:
        if db.execute(select(FilterRecord).where(FilterRecord.filter_order_id == o.filter_order_id)).first():
            raise DomainError("Lệnh lọc đã được thực hiện — không thể xóa.")
    _delete_children(db, children)
    record_audit(db, entity_type="filter_master_order", entity_id=filter_master_order_id, action="delete",
                 actor=user, before={"order_code": master.order_code, "children": len(children)})
    db.delete(master)
    db.commit()


def next_batch_seq_no(db: Session, exclude_line_id: str = None) -> dict:
    """Gợi ý "Mẻ lọc số" kế tiếp + danh sách số đã dùng — quét TOÀN BỘ các lô lọc trong hệ
    thống (không giới hạn theo 1 lệnh lọc), lấy số lớn nhất đang có rồi +1, vì "Mẻ lọc số" vận
    hành thực tế đánh số chạy chung cho toàn nhà máy chứ không reset riêng theo từng lệnh lọc.
    batch_seq_no KHÔNG kiểm tra trùng ở tầng ứng dụng (xem FilterOrderTank.batch_seq_no, cho
    phép trùng cả trong cùng lệnh lẫn giữa các lệnh khác nhau, vì phiếu giấy thực tế có thể lặp
    số theo ca/ngày, và filter_yield_report còn CHỦ ĐỘNG gộp các dòng cùng batch_number/
    order_number/batch_seq_no thành 1 mẻ thật). Hàm này chỉ hỗ trợ UX (gợi ý số tiếp theo + hỏi
    lại nếu trùng), KHÔNG chặn lưu — exclude_line_id để không tự báo trùng với chính dòng đang
    sửa."""
    rows = db.execute(select(FilterOrderTank.line_id, FilterOrderTank.batch_seq_no).where(
        FilterOrderTank.filter_id.isnot(None),
        FilterOrderTank.batch_seq_no.isnot(None),
    )).all()
    used = sorted({no for line_id, no in rows if no and line_id != exclude_line_id})
    numeric = [int(no) for no in used if no.isdigit()]
    next_no = str(max(numeric) + 1) if numeric else "1"
    return {"next_batch_seq_no": next_no, "used_batch_seq_nos": used}
