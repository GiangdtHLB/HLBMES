"""Lệnh nấu bia (Brew Production Order) — mẫu giấy "LỆNH NẤU BIA KIÊM PHIẾU XUẤT KHO",
chỉ giữ phần LỆNH (định mức NVL dự kiến), không lặp lại phần phiếu xuất kho thật (nay đã đi
qua Dispense/DispenseLine — services/dispense.py — cho pipeline "Mẻ sản xuất").

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
from ..common import WorkOrderState, new_id, utcnow
from ..errors import DomainError, NotFoundError
from ..models.batches import BatchExecution
from ..models.brewing import BrewOrder, BrewOrderMaterialLine
from ..models.formula import Formula
from ..models.recipes import Recipe, RecipeVersion
from ..models.master import BeerType, Material, MaterialAltGroup, Product
from ..models.workorder import WorkOrder
from . import warehouse as warehouse_svc


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


def _build_group_line(i: int, m: dict, group_code: str, group, materials_by_code: dict,
                      planned_batch_count: int, selected_codes: list | None = None) -> dict:
    """Dựng 1 dòng BOM theo Nhóm vật tư thay thế — hỗ trợ 2 kiểu khai:
    - Kiểu cũ (m["qty"]): 1 định mức DÙNG CHUNG cho mọi thành viên (hành vi gốc, VD "cần 825kg
      Malt Úc", không quan tâm rời hay bao) — qty_per_batch/qty_total ở dòng = đúng số đó. Việc
      chọn mã cụ thể nào vẫn hoàn toàn tự do lúc ghi NVL thực tế (không có bước "chọn" ở Lệnh
      nấu cho kiểu này).
    - Kiểu mới (m["member_qty"] = [{material_code, qty}, ...]): mỗi thành viên 1 định mức
      RIÊNG (VD nhóm CO2 tương đương nhưng khác nồng độ). Người lập Lệnh nấu PHẢI chọn đúng
      những thành viên áp dụng cho lệnh này ngay lúc lập (`selected_codes`, theo
      MaterialAltGroup.selection_mode: "single" chọn đúng 1, "multi" chọn từ 1 trở lên) —
      qty_per_batch/qty_total của dòng = TỔNG định mức CHỈ của các thành viên đã chọn (không
      phải toàn bộ thành viên khai trong Công thức). `selected_codes=None` (VD preview lúc
      chưa chọn gì) giữ nguyên TOÀN BỘ để người dùng thấy hết lựa chọn trước khi chọn."""
    member_qty = m.get("member_qty")
    if member_qty:
        if selected_codes is not None:
            member_qty = [mq for mq in member_qty if mq.get("material_code") in selected_codes]
        member_declared = []
        for mq in member_qty:
            mat = materials_by_code.get(mq.get("material_code"))
            mqty_per_batch = round(mq.get("qty", 0) or 0, 3)
            member_declared.append({
                "material_id": mat.material_id if mat else None,
                "material_code": mat.code if mat else mq.get("material_code"),
                "material_name": mat.name if mat else mq.get("material_code"),
                "qty_per_batch": mqty_per_batch,
                "qty_total": round(mqty_per_batch * planned_batch_count, 3),
            })
        qty_per_batch = round(sum(d["qty_per_batch"] for d in member_declared), 3)
        qty_total = round(sum(d["qty_total"] for d in member_declared), 3)
        return {
            "seq": i, "stt_label": str(i + 1), "is_header": False,
            "material_id": None,
            "material_name": group.name if group else group_code,
            "material_group_code": group_code,
            "member_material_ids": list(group.member_material_ids or []) if group else [],
            "member_declared": member_declared,
            "selection_mode": group.selection_mode if group else "single",
            "uom": m.get("uom"),
            "qty_per_batch": qty_per_batch,
            "qty_total": qty_total,
        }
    qty_per_batch = round(m.get("qty", 0) or 0, 3)
    qty_total = round(qty_per_batch * planned_batch_count, 3)
    return {
        "seq": i, "stt_label": str(i + 1), "is_header": False,
        "material_id": None,
        "material_name": group.name if group else group_code,
        "material_group_code": group_code,
        "member_material_ids": list(group.member_material_ids or []) if group else [],
        "uom": m.get("uom"),
        "qty_per_batch": qty_per_batch,
        "qty_total": qty_total,
    }


def build_lines_from_bom(db: Session, formula_id: str, planned_batch_count: int, planned_volume_hl: float,
                         member_selection: dict | None = None) -> list:
    """Nạp Định mức từ 1 Công thức CỤ THỂ (formula_id do người lập Lệnh nấu tự chọn — nhiều
    công thức/dịch bia có thể cùng hiệu lực, xem services/formula.py) — công thức khai báo
    định mức CHO ĐÚNG 1 MẺ, nên Nhu cầu 1 mẻ = nguyên văn số lượng trong công thức (KHÔNG scale
    theo planned_volume_hl — tham số này chỉ giữ lại cho tương thích chữ ký hàm/router, không
    dùng trong phép tính), Nhu cầu Tổng mẻ = Nhu cầu 1 mẻ x Số mẻ kế hoạch.

    Dòng khai theo Nhóm vật tư thay thế (alt_group_code, VD "Malt Úc") không có material_id
    cụ thể — material_name = tên nhóm, kèm member_material_ids để _annotate_stock cộng dồn
    tồn kho qua mọi mã thành viên và để thủ kho được gợi ý đúng mọi mã lúc ghi NVL thực tế
    (xem _resolve_group_members, frontend openBrewMaterialsModal). Xem _build_group_line cho
    2 kiểu khai định mức nhóm (dùng chung 1 số / mỗi thành viên 1 số riêng) — `member_selection`
    ({str(seq): [material_code,...]}) chỉ áp dụng cho dòng khai kiểu mỗi thành viên 1 định mức
    riêng, chọn những mã nào áp dụng cho lệnh nấu này (None = chưa chọn, giữ nguyên toàn bộ)."""
    formula = db.get(Formula, formula_id) if formula_id else None
    if not formula:
        return []
    materials_by_code = {m.code: m for m in db.execute(select(Material)).scalars().all()}
    groups_by_code = {g.code: g for g in db.execute(select(MaterialAltGroup)).scalars().all()}
    out = []
    for i, m in enumerate(formula.materials or []):
        group_code = m.get("alt_group_code")
        if group_code:
            out.append(_build_group_line(i, m, group_code, groups_by_code.get(group_code),
                                         materials_by_code, planned_batch_count,
                                         (member_selection or {}).get(str(i))))
            continue
        qty_per_batch = round(m.get("qty", 0) or 0, 3)
        qty_total = round(qty_per_batch * planned_batch_count, 3)
        code = m.get("material_code")
        mat = materials_by_code.get(code)
        out.append({
            "seq": i, "stt_label": str(i + 1), "is_header": False,
            "material_id": mat.material_id if mat else None,
            "material_code": mat.code if mat else code,
            "material_name": mat.name if mat else code,
            "uom": m.get("uom"),
            "qty_per_batch": qty_per_batch,
            "qty_total": qty_total,
        })
    return out


def build_lines_from_recipe_version(db: Session, recipe_version_id: str, planned_batch_count: int,
                                    planned_volume_hl: float, member_selection: dict | None = None) -> list:
    """Nạp Định mức từ 1 RecipeVersion đang `effective` (do người lập Lệnh nấu tự chọn) — mirror
    build_lines_from_bom (cùng ngữ nghĩa Nhu cầu 1 mẻ/Tổng mẻ, cùng hỗ trợ khai theo Nhóm vật tư
    thay thế qua `alt_group_code` trong từng phần tử JSON `RecipeVersion.materials`, cùng tham
    số `member_selection` chọn thành viên áp dụng cho dòng khai định mức riêng từng thành viên)."""
    rv = db.get(RecipeVersion, recipe_version_id) if recipe_version_id else None
    if not rv:
        return []
    materials_by_code = {m.code: m for m in db.execute(select(Material)).scalars().all()}
    groups_by_code = {g.code: g for g in db.execute(select(MaterialAltGroup)).scalars().all()}
    out = []
    for i, m in enumerate(rv.materials or []):
        group_code = m.get("alt_group_code")
        if group_code:
            out.append(_build_group_line(i, m, group_code, groups_by_code.get(group_code),
                                         materials_by_code, planned_batch_count,
                                         (member_selection or {}).get(str(i))))
            continue
        qty_per_batch = round(m.get("qty", 0) or 0, 3)
        qty_total = round(qty_per_batch * planned_batch_count, 3)
        code = m.get("material_code")
        mat = materials_by_code.get(code)
        out.append({
            "seq": i, "stt_label": str(i + 1), "is_header": False,
            "material_id": mat.material_id if mat else None,
            "material_code": mat.code if mat else code,
            "material_name": mat.name if mat else code,
            "uom": m.get("uom"),
            "qty_per_batch": qty_per_batch,
            "qty_total": qty_total,
        })
    return out


def _convert_member_qty(mat, target_unit: str | None, qty: float) -> float:
    """Quy đổi tồn kho (lưu theo uom chính của vật tư) về đơn vị của nhóm vật tư thay thế
    (MaterialAltGroup.unit) trước khi cộng dồn với các thành viên khác — nếu không, cộng thô
    số lượng khác đơn vị (VD kg + Lon) sẽ ra kết quả vô nghĩa. validate_alt_group_unit đã bắt
    buộc mọi thành viên khai được target_unit (bằng uom chính hoặc alt_uom) lúc tạo/sửa nhóm."""
    if not mat or not target_unit or mat.uom == target_unit:
        return qty
    if mat.alt_uom == target_unit and mat.alt_uom_ratio:
        # round: nhân 2 float (VD 201.58 * 5.0) hay ra dư số nhị phân li ti (1007.9000000000001)
        # dù kết quả thập phân đúng là số tròn — làm tròn lại để hiển thị/so sánh sạch, khớp
        # cách stock_on_hand() đã làm tròn 3 chữ số trước khi trả ra.
        return round(qty * mat.alt_uom_ratio, 3)
    return qty


def _line_stock(l: dict, company_stock: dict, workshop_stock: dict, materials_by_id: dict | None = None) -> tuple:
    """Tồn công ty/phân xưởng cho 1 dòng NVL — dòng nhóm vật tư thay thế (member_material_ids
    không rỗng) cộng dồn qua MỌI mã thành viên, quy đổi về đơn vị của nhóm (l["uom"]) trước khi
    cộng nếu có materials_by_id; dòng thường tra theo material_id đơn lẻ."""
    member_ids = l.get("member_material_ids") or []
    if member_ids:
        target_unit = l.get("uom")
        if materials_by_id:
            company = sum(_convert_member_qty(materials_by_id.get(mid), target_unit, company_stock.get(mid, 0) or 0)
                          for mid in member_ids)
            workshop = sum(_convert_member_qty(materials_by_id.get(mid), target_unit, workshop_stock.get(mid, 0) or 0)
                          for mid in member_ids)
        else:
            company = sum(company_stock.get(mid, 0) or 0 for mid in member_ids)
            workshop = sum(workshop_stock.get(mid, 0) or 0 for mid in member_ids)
        return round(company, 3), round(workshop, 3)
    material_id = l.get("material_id")
    return company_stock.get(material_id, 0) or 0, workshop_stock.get(material_id, 0) or 0


def _materials_by_id(db: Session) -> dict:
    return {m.material_id: m for m in db.execute(select(Material)).scalars().all()}


def _actual_usage_by_material(db: Session, brew_ids: list) -> dict:
    """Tổng NVL thực tế đã dùng theo material_id — trước đây tính từ BrewMaterialUsage (module
    Nấu-Lọc-Chiết cũ, đối chiếu với Nhu cầu Tổng mẻ của dòng Nhóm vật tư thay thế), nay module
    đó đã xóa. Pipeline "Mẻ sản xuất" cấp phát NVL qua Dispense/DispenseLine (services/
    dispense.py) — cơ chế khác hẳn (không gắn material_id+lot_id theo kiểu BrewMaterialUsage),
    nên chưa có cách đối chiếu tương đương; trả rỗng để get_order() vẫn chạy được (actual_used
    hiện luôn 0), không raise lỗi."""
    return {}


def _member_breakdown(member_ids: list, company_stock: dict, workshop_stock: dict, materials_by_id: dict,
                      actual_usage: dict | None = None) -> list:
    """Tồn kho TỪNG mã thành viên của 1 dòng Nhóm vật tư thay thế — để người lập lệnh thấy
    ngay nhóm gồm đúng những mã nào và mã nào đang thực sự có tồn (VD "Malt Úc" gồm Malt Úc
    rời + Malt Úc bao, chỉ 1 trong 2 đang còn hàng), không chỉ số tổng cộng dồn. `actual_used`
    (khi truyền `actual_usage`) là tổng đã dùng THẬT của đúng mã đó qua mọi mẻ của lệnh — để
    đối chiếu với Nhu cầu Tổng mẻ của dòng gộp."""
    out = []
    for mid in member_ids or []:
        mat = materials_by_id.get(mid)
        out.append({
            "material_id": mid, "material_code": mat.code if mat else None,
            "material_name": mat.name if mat else mid,
            "stock_company": company_stock.get(mid, 0) or 0,
            "stock_workshop": workshop_stock.get(mid, 0) or 0,
            **({"actual_used": actual_usage.get(mid, 0) or 0} if actual_usage is not None else {}),
        })
    return out


def _member_declared_breakdown(member_declared: list, group_unit: str | None, company_stock: dict,
                               workshop_stock: dict, materials_by_id: dict | None,
                               actual_usage: dict | None = None, member_qty_splits: dict | None = None) -> tuple[list, bool]:
    """Gắn tồn kho + cờ thiếu tồn RIÊNG cho từng thành viên đã khai định mức riêng
    (member_declared, xem _build_group_line) — khác _member_breakdown (chỉ tồn, không định
    mức, dùng cho dòng nhóm khai kiểu cũ). Trả (breakdown, all_short) — `all_short` = True khi
    KHÔNG thành viên nào đủ tồn riêng của chính nó, dùng để chặn tạo lệnh (_assert_no_shortage)
    hay tính cờ shortage hiển thị (_annotate_stock); vẫn cho tạo lệnh nếu có ÍT NHẤT 1 lựa chọn
    khả thi — lựa chọn cụ thể do người thao tác quyết định lúc ghi NVL thực tế.

    Mỗi thành viên có định mức RIÊNG nên cũng gợi ý tách 2 nguồn kho RIÊNG cho chính mã đó
    (mirror _suggest_qty_split ở dòng thường) — `member_qty_splits` ({material_code: {qty_from_
    company, qty_from_workshop}}) là override người lập lệnh tự sửa, khớp theo material_code."""
    out = []
    all_short = True
    for d in member_declared or []:
        mid = d.get("material_id")
        mat = materials_by_id.get(mid) if materials_by_id and mid else None
        company = _convert_member_qty(mat, group_unit, company_stock.get(mid, 0) or 0) if mid else 0
        workshop = _convert_member_qty(mat, group_unit, workshop_stock.get(mid, 0) or 0) if mid else 0
        qty_total = d.get("qty_total")
        member_short = qty_total is not None and qty_total > (company + workshop)
        if not member_short:
            all_short = False
        qty_from_company, qty_from_workshop = _suggest_qty_split(qty_total, workshop)
        ov = (member_qty_splits or {}).get(d.get("material_code"))
        if ov:
            if ov.get("qty_from_company") is not None:
                qty_from_company = ov["qty_from_company"]
            if ov.get("qty_from_workshop") is not None:
                qty_from_workshop = ov["qty_from_workshop"]
        out.append({
            "material_id": mid, "material_code": d.get("material_code"), "material_name": d.get("material_name"),
            "stock_company": company, "stock_workshop": workshop,
            "qty_per_batch": d.get("qty_per_batch"), "qty_total": qty_total, "shortage": member_short,
            "qty_from_company": qty_from_company, "qty_from_workshop": qty_from_workshop,
            **({"actual_used": actual_usage.get(mid, 0) or 0} if actual_usage is not None and mid else {}),
        })
    return out, (all_short if member_declared else False)


def _suggest_qty_split(qty_total: float | None, workshop_stock: float) -> tuple:
    """Gợi ý tách Nhu cầu Tổng mẻ thành 2 nguồn thực xuất: ưu tiên dùng hết tồn đang có tại
    Kho phân xưởng (tối đa bằng đúng nhu cầu — không gợi ý lấy dư), phần còn thiếu lấy tại
    Kho công ty. Chỉ là GỢI Ý ban đầu — người lập lệnh nấu có thể sửa lại 2 số này trước khi
    lưu (xem frontend "Xem NVL" preview + _insert_sub_order/update_order phía dưới, nơi
    override do người dùng nhập được áp lên trên gợi ý này)."""
    if qty_total is None:
        return None, None
    qty_total = qty_total or 0
    from_workshop = min(max(workshop_stock or 0, 0), qty_total)
    return round(qty_total - from_workshop, 3), round(from_workshop, 3)


def _apply_qty_split_override(line: dict, workshop_stock: float, overrides: dict) -> tuple:
    """Tính SL thực xuất theo 2 nguồn cho 1 dòng NVL: bắt đầu từ gợi ý (_suggest_qty_split),
    rồi áp đè giá trị người lập lệnh nấu đã tự sửa trong preview (nếu có, khớp theo `seq` —
    key trong `overrides` là str(seq) vì JSON object key luôn là string). Chỉ áp đè từng
    trường có giá trị — nếu người dùng chỉ sửa 1 trong 2 ô thì ô còn lại vẫn giữ gợi ý."""
    if line.get("is_header") or not (line.get("material_id") or line.get("member_material_ids")):
        return None, None
    qty_from_company, qty_from_workshop = _suggest_qty_split(line.get("qty_total"), workshop_stock)
    ov = overrides.get(str(line.get("seq"))) if overrides else None
    if ov:
        if ov.get("qty_from_company") is not None:
            qty_from_company = ov["qty_from_company"]
        if ov.get("qty_from_workshop") is not None:
            qty_from_workshop = ov["qty_from_workshop"]
    return qty_from_company, qty_from_workshop


def _annotate_stock(lines: list, company_stock: dict, workshop_stock: dict, materials_by_id: dict | None = None) -> list:
    """Gắn tồn kho công ty/phân xưởng + cờ "shortage" (thiếu tồn) vào từng dòng NVL — dùng
    chung cho preview (trước khi tạo lệnh) và get_order (đã tạo, đọc lại snapshot đã lưu).
    Dòng Nhóm vật tư thay thế còn kèm member_breakdown (tồn riêng từng mã thành viên) khi có
    materials_by_id — bắt buộc để hiện đúng tên vật tư, không chỉ material_id.

    Dòng nhóm khai định mức RIÊNG từng thành viên (member_declared, xem _build_group_line) đi
    theo nhánh riêng: member_breakdown gồm cả định mức + shortage + gợi ý tách 2 nguồn kho
    (qty_from_company/workshop) CỦA TỪNG MÃ (không cộng dồn tồn qua mọi mã như kiểu cũ, vì mỗi
    mã có định mức độc lập của chính nó) — dòng cha chỉ shortage khi KHÔNG mã nào đủ tồn riêng,
    và không có 1 con số "SL lấy" chung ở cấp dòng (mỗi thành viên tự tách nguồn riêng)."""
    out = []
    for l in lines:
        member_declared = l.get("member_declared")
        if member_declared:
            breakdown, shortage = _member_declared_breakdown(
                member_declared, l.get("uom"), company_stock, workshop_stock, materials_by_id)
            company = round(sum(d["stock_company"] for d in breakdown), 3)
            workshop = round(sum(d["stock_workshop"] for d in breakdown), 3)
            out.append({**l, "stock_company_snapshot": company, "stock_workshop_snapshot": workshop,
                        "unit_price": l.get("unit_price"), "shortage": shortage,
                        "member_breakdown": breakdown,
                        "qty_from_company": None, "qty_from_workshop": None})
            continue
        has_target = bool(l.get("material_id") or l.get("member_material_ids"))
        company, workshop = _line_stock(l, company_stock, workshop_stock, materials_by_id)
        qty_total = l.get("qty_total")
        shortage = (not l.get("is_header")) and qty_total is not None and qty_total > (company + workshop)
        member_ids = l.get("member_material_ids") or []
        member_breakdown = (_member_breakdown(member_ids, company_stock, workshop_stock, materials_by_id)
                             if member_ids and materials_by_id is not None else [])
        qty_from_company, qty_from_workshop = (
            _suggest_qty_split(qty_total, workshop) if has_target and not l.get("is_header") else (None, None))
        out.append({**l, "stock_company_snapshot": company if has_target else None,
                    "stock_workshop_snapshot": workshop if has_target else None,
                    "unit_price": l.get("unit_price"), "shortage": shortage,
                    "member_breakdown": member_breakdown,
                    "qty_from_company": qty_from_company, "qty_from_workshop": qty_from_workshop})
    return out


def preview_bom_lines(db: Session, formula_id: str, planned_batch_count: int, planned_volume_hl: float) -> list:
    """Xem trước bảng định mức NVL tự nạp từ 1 Công thức (BOM) cụ thể + tồn kho hiện tại,
    TRƯỚC khi tạo lệnh nấu thật — để người lập biết ngay có đủ NVL hay không mà không cần tạo
    lệnh xong rồi mới xem (xem routers/brewing.py::preview_brew_order_bom)."""
    lines = build_lines_from_bom(db, formula_id, planned_batch_count, planned_volume_hl)
    company_stock, workshop_stock = _stock_snapshot(db)
    return _annotate_stock(lines, company_stock, workshop_stock, _materials_by_id(db))


def preview_bom_lines_from_recipe_version(db: Session, recipe_version_id: str, planned_batch_count: int,
                                          planned_volume_hl: float) -> list:
    """Mirror preview_bom_lines, nạp từ RecipeVersion thay Formula."""
    lines = build_lines_from_recipe_version(db, recipe_version_id, planned_batch_count, planned_volume_hl)
    company_stock, workshop_stock = _stock_snapshot(db)
    return _annotate_stock(lines, company_stock, workshop_stock, _materials_by_id(db))


def _assert_no_shortage(lines: list, company_stock: dict, workshop_stock: dict, materials_by_id: dict) -> None:
    """Chặn hẳn việc lập/sửa Lệnh nấu nếu có dòng NVL thiếu tồn (tổng 2 kho) — mirror
    filter_order.py::_validate_material_lines. Trước đây Lệnh nấu chỉ CẢNH BÁO (cờ shortage
    của _annotate_stock, hiển thị ở preview) rồi vẫn cho lưu; theo yêu cầu, giờ thiếu tồn thì
    không cho tạo/sửa lệnh, giống Lệnh lọc."""
    shortages = []
    for l in lines:
        if l.get("is_header"):
            continue
        member_declared = l.get("member_declared")
        if member_declared:
            breakdown, all_short = _member_declared_breakdown(
                member_declared, l.get("uom"), company_stock, workshop_stock, materials_by_id)
            if all_short:
                detail = "; ".join(f"{d['material_name']}: cần {d['qty_total']}, hiện có "
                                   f"{round(d['stock_company'] + d['stock_workshop'], 3)}" for d in breakdown)
                shortages.append(f"{l.get('material_name')} (không mã nào đủ tồn — {detail})")
            continue
        qty_total = l.get("qty_total")
        if qty_total is None:
            continue
        company, workshop = _line_stock(l, company_stock, workshop_stock, materials_by_id)
        if qty_total > company + workshop:
            shortages.append(
                f"{l.get('material_name')}: cần {qty_total}, hiện có {round(company + workshop, 3)} "
                f"(Kho công ty {round(company, 3)} + Kho phân xưởng {round(workshop, 3)})")
    if shortages:
        raise DomainError("Không đủ tồn kho để lập lệnh nấu — " + "; ".join(shortages) + ".")


def _validate_member_selection(lines: list) -> None:
    """Dòng khai định mức riêng từng thành viên (member_declared) BẮT BUỘC người lập Lệnh nấu
    đã chọn đúng số lượng thành viên theo selection_mode của Nhóm vật tư — "single" phải chọn
    ĐÚNG 1, "multi" phải chọn ÍT NHẤT 1. `_build_group_line` đã lọc `member_declared` theo lựa
    chọn (`selected_codes`) trước khi tới đây; nếu người lập Lệnh nấu chưa hề chọn gì (frontend
    không gửi lựa chọn), `member_declared` giữ nguyên TOÀN BỘ thành viên — với nhóm "single" sẽ
    tự động fail ở đây (đúng ý: bắt buộc phải chọn), tránh lọt lệnh không rõ dùng mã nào."""
    for l in lines:
        member_declared = l.get("member_declared")
        if not member_declared:
            continue
        mode = l.get("selection_mode", "single")
        if mode == "single" and len(member_declared) != 1:
            raise DomainError(f"{l.get('material_name')}: nhóm chỉ cho chọn ĐÚNG 1 vật tư khi lập lệnh nấu "
                              f"(hiện chọn {len(member_declared)}).")
        if mode == "multi" and len(member_declared) < 1:
            raise DomainError(f"{l.get('material_name')}: chọn ít nhất 1 vật tư trong nhóm.")


def _validate_volume_plan(planned_volume_hl, tolerance_hl) -> None:
    """Sản lượng nấu kế hoạch (hl) bắt buộc phải > 0 — nếu để 0/None, logic hoàn thành
    (thực tế >= kế hoạch - sai số) sẽ coi lệnh "hoàn thành ngay từ đầu" khi thực tế
    cũng đang là 0 (chưa nấu gì), sai hoàn toàn (xem _is_complete)."""
    if planned_volume_hl is None or planned_volume_hl <= 0:
        raise DomainError("Nhập sản lượng nấu kế hoạch (hl) (phải lớn hơn 0).")
    if tolerance_hl is None or tolerance_hl < 0:
        raise DomainError("Sai số cho phép không được âm.")


def _validate_formula_selection(db: Session, product_id: str | None, formula_id: str | None) -> None:
    """Nhiều công thức/dịch bia có thể cùng hiệu lực (xem services/formula.py) — người lập
    Lệnh nấu BẮT BUỘC tự chọn đúng 1 formula_id cho mỗi lệnh nhỏ có product_id, không còn tự
    suy ra "công thức hiệu lực duy nhất" như trước."""
    if not product_id:
        return
    if not formula_id:
        raise DomainError("Chọn công thức đang dùng cho lệnh nấu nhỏ này.")
    formula = db.get(Formula, formula_id)
    if not formula:
        raise DomainError("Công thức đã chọn không tồn tại.")
    if formula.product_id != product_id:
        raise DomainError(f"Công thức '{formula.code}' không thuộc Dịch bia đã chọn.")
    if not formula.is_active:
        raise DomainError(f"Công thức '{formula.code}' không còn hiệu lực.")


def _validate_recipe_version_selection(db: Session, product_id: str | None, recipe_version_id: str | None) -> None:
    """Mirror _validate_formula_selection cho hệ Recipe/RecipeVersion: Recipe giờ đại diện 1
    Loại bia (nhiều RecipeVersion bên trong, mỗi version tự gắn 1 Dịch bia riêng qua
    RecipeVersion.product_id) — người lập Lệnh nấu chọn 1 version đang hiệu lực (state=effective)
    ĐÚNG dịch bia đã chọn (so trực tiếp trên version, không cần qua Recipe)."""
    if not product_id:
        return
    if not recipe_version_id:
        raise DomainError("Chọn công thức đang dùng cho lệnh nấu nhỏ này.")
    rv = db.get(RecipeVersion, recipe_version_id)
    if not rv:
        raise DomainError("Công thức đã chọn không tồn tại.")
    if rv.product_id != product_id:
        raise DomainError(f"Công thức (version {rv.version_no}) không thuộc Dịch bia đã chọn.")
    if rv.state != "effective":
        recipe = db.get(Recipe, rv.recipe_id)
        raise DomainError(f"Công thức '{recipe.code if recipe else '?'}' version {rv.version_no} không còn hiệu lực.")


def _persist_material_lines(db: Session, order: BrewOrder, lines: list, qty_overrides: dict,
                            company_stock: dict, workshop_stock: dict, materials_by_id: dict) -> None:
    """Ghi các dòng BrewOrderMaterialLine cho 1 lệnh (order đã add/flush) — dùng chung bởi
    _create_order_row (tạo mới) và update_order (xóa dòng cũ rồi gọi lại hàm này)."""
    for i, line in enumerate(lines):
        material_id = line.get("material_id")
        member_declared = line.get("member_declared")
        member_qty_snapshot = None
        if member_declared:
            member_splits_ov = (qty_overrides.get(str(line.get("seq", i))) or {}).get("member_qty_splits")
            member_qty_snapshot, _ = _member_declared_breakdown(
                member_declared, line.get("uom"), company_stock, workshop_stock, materials_by_id,
                member_qty_splits=member_splits_ov)
            company = sum(d["stock_company"] for d in member_qty_snapshot)
            workshop = sum(d["stock_workshop"] for d in member_qty_snapshot)
            has_target = True
            qty_from_company = qty_from_workshop = None
        else:
            has_target = bool(material_id or line.get("member_material_ids"))
            company, workshop = _line_stock(line, company_stock, workshop_stock, materials_by_id)
            qty_from_company, qty_from_workshop = _apply_qty_split_override(
                line, workshop, qty_overrides)
        db.add(BrewOrderMaterialLine(
            line_id=new_id(), brew_order_id=order.brew_order_id, seq=line.get("seq", i),
            stt_label=line.get("stt_label"), is_header=line.get("is_header", False),
            material_id=material_id, material_name=line.get("material_name"), uom=line.get("uom"),
            material_group_code=line.get("material_group_code"),
            member_qty_snapshot=member_qty_snapshot,
            qty_per_batch=line.get("qty_per_batch"), qty_total=line.get("qty_total"),
            unit_price=line.get("unit_price"),
            stock_company_snapshot=company if has_target else None,
            stock_workshop_snapshot=workshop if has_target else None,
            qty_from_company=qty_from_company, qty_from_workshop=qty_from_workshop,
        ))


def _create_order_row(db: Session, order_code: str, order_year: int, payload: dict, user) -> BrewOrder:
    """Tạo 1 dòng BrewOrder (Lệnh sản xuất) + định mức NVL — KHÔNG validate (caller đã
    validate), KHÔNG commit (caller tự quyết định điểm commit)."""
    payload = dict(payload)
    lines_in = payload.pop("lines", None) or []
    auto_from_bom = payload.pop("auto_from_bom", True)
    qty_overrides = payload.pop("material_qty_overrides", None) or {}
    member_selection = {k: v["selected_material_codes"] for k, v in qty_overrides.items()
                        if v.get("selected_material_codes") is not None}

    if auto_from_bom and not lines_in:
        _validate_recipe_version_selection(db, payload.get("product_id"), payload.get("recipe_version_id"))

    lines = lines_in if lines_in else (
        build_lines_from_recipe_version(db, payload.get("recipe_version_id"), payload.get("planned_batch_count"),
                                        payload.get("planned_volume_hl"), member_selection)
        if auto_from_bom and payload.get("product_id") else []
    )
    _validate_member_selection(lines)
    company_stock, workshop_stock = _stock_snapshot(db)
    materials_by_id = _materials_by_id(db)
    _assert_no_shortage(lines, company_stock, workshop_stock, materials_by_id)

    order = BrewOrder(brew_order_id=new_id(), order_code=order_code, order_year=order_year,
                      created_by=user.username, created_at=utcnow(), **payload)
    db.add(order)
    db.flush()
    _persist_material_lines(db, order, lines, qty_overrides, company_stock, workshop_stock, materials_by_id)
    return order


def create_order(db: Session, payload: dict, user) -> BrewOrder:
    payload = dict(payload)
    order_code = payload.pop("order_code")
    order_year = utcnow().year
    if db.execute(select(BrewOrder).where(BrewOrder.order_code == order_code,
                  BrewOrder.order_year == order_year)).first():
        raise DomainError(f"Số lệnh '{order_code}' đã tồn tại trong năm {order_year}.")
    _validate_volume_plan(payload.get("planned_volume_hl"), payload.get("volume_tolerance_hl"))

    order = _create_order_row(db, order_code, order_year, payload, user)

    record_audit(db, entity_type="brew_order", entity_id=order.brew_order_id, action="create",
                 actor=user, after={"order_code": order.order_code})
    db.commit()
    db.refresh(order)
    return order


def update_order(db: Session, brew_order_id: str, payload: dict, user) -> BrewOrder:
    """Sửa lại lệnh nấu CHƯA thực hiện (chưa có mẻ sản xuất/Lệnh SX nào) — cho phép sửa toàn bộ (số
    lệnh, dịch bia, sản lượng kế hoạch...); định mức NVL được nạp lại từ đầu giống hệt lúc
    tạo mới (lines truyền tay hoặc tự nạp lại từ BOM theo product_id/planned_batch_count/
    planned_volume_hl mới — xem create_order)."""
    order = db.get(BrewOrder, brew_order_id)
    if not order:
        raise NotFoundError("Lệnh nấu không tồn tại.")
    if _has_any_execution(db, brew_order_id):
        raise DomainError("Lệnh nấu đã được thực hiện — không thể sửa.")

    lines_in = payload.pop("lines", None) or []
    auto_from_bom = payload.pop("auto_from_bom", True)
    qty_overrides = payload.pop("material_qty_overrides", None) or {}
    member_selection = {k: v["selected_material_codes"] for k, v in qty_overrides.items()
                        if v.get("selected_material_codes") is not None}
    new_code = payload.get("order_code")
    if new_code != order.order_code and db.execute(
            select(BrewOrder).where(BrewOrder.order_code == new_code,
                    BrewOrder.order_year == order.order_year)).first():
        raise DomainError(f"Số lệnh '{new_code}' đã tồn tại trong năm {order.order_year}.")
    _validate_volume_plan(payload.get("planned_volume_hl"), payload.get("volume_tolerance_hl"))
    if auto_from_bom and not lines_in:
        _validate_recipe_version_selection(db, payload.get("product_id"), payload.get("recipe_version_id"))

    lines = lines_in if lines_in else (
        build_lines_from_recipe_version(db, payload.get("recipe_version_id"), payload.get("planned_batch_count"),
                                        payload.get("planned_volume_hl"), member_selection)
        if auto_from_bom and payload.get("product_id") else []
    )
    _validate_member_selection(lines)
    company_stock, workshop_stock = _stock_snapshot(db)
    materials_by_id = _materials_by_id(db)
    _assert_no_shortage(lines, company_stock, workshop_stock, materials_by_id)

    for l in db.execute(select(BrewOrderMaterialLine).where(
            BrewOrderMaterialLine.brew_order_id == brew_order_id)).scalars().all():
        db.delete(l)
    db.flush()

    for field, value in payload.items():
        setattr(order, field, value)

    _persist_material_lines(db, order, lines, qty_overrides, company_stock, workshop_stock, materials_by_id)

    record_audit(db, entity_type="brew_order", entity_id=order.brew_order_id, action="update",
                 actor=user, after={"order_code": order.order_code, "lines": len(lines)})
    db.commit()
    db.refresh(order)
    return order


def _is_complete(batches: list, planned_volume_hl: float, tolerance_hl: float) -> bool:
    """Hoàn thành khi ĐÃ có ít nhất 1 mẻ sản xuất (BatchExecution), tổng sản lượng thực tế
    (actual_qty, cộng dồn qua tất cả mẻ của lệnh) đạt kế hoạch trong sai số cho phép (thực tế
    >= kế hoạch - sai số) HOẶC đã vượt kế hoạch — chỉ chặn hoàn thành khi còn HỤT quá sai số,
    KHÔNG chặn khi vượt kế hoạch (một chiều) — VÀ tất cả mẻ đó đã kết thúc (end_at có giá trị)
    — sản lượng khớp nhưng còn mẻ đang dở dang thì lệnh vẫn coi như đang thực hiện, chưa hoàn
    thành. Dùng làm fallback khi lệnh chưa có Lệnh SX (điều độ) nào (xem _wo_derived_status)."""
    if not batches:
        return False
    actual = round(sum(b.actual_qty or 0.0 for b in batches), 3)
    if actual < planned_volume_hl - tolerance_hl:
        return False
    return all(b.end_at is not None for b in batches)


def _batch_summaries(db: Session, brew_order_id: str) -> list:
    """Mẻ sản xuất (BatchExecution) của lệnh — liên kết TRỰC TIẾP qua order_id (dù tạo qua
    "Phát mẻ"/Điều độ hay tạo tay ở tab "Mẻ sản xuất", xem services/batches.py::create_batch).
    Đây là lớp thực thi DUY NHẤT còn lại (module Nấu-Lọc-Chiết cũ/BrewRecord/BrewBatch đã xóa)
    — Thực tế/Trạng thái của lệnh tính theo đây + trạng thái Điều độ (WorkOrder)."""
    return db.execute(select(BatchExecution).where(BatchExecution.order_id == brew_order_id)).scalars().all()


def _has_any_execution(db: Session, brew_order_id: str) -> bool:
    """Lệnh đã "động tay" vào chưa (chặn Sửa/Xóa) — kiểm cả 2 lớp thực thi: BatchExecution
    (mẻ sản xuất) VÀ Điều độ (WorkOrder, mirror is_executed ở list_orders/get_order)."""
    if db.execute(select(BatchExecution.batch_id).where(BatchExecution.order_id == brew_order_id)).first():
        return True
    wo_status = _wo_derived_status(db, brew_order_id)
    return bool(wo_status and wo_status[0])


def is_order_complete(db: Session, brew_order_id: str) -> bool:
    """Lệnh nấu đã "Hoàn thành" chưa — dùng để chặn lập Lệnh SX (Điều độ) MỚI cho lệnh đã xong
    (yêu cầu người dùng 2026-09-01: lệnh đã hoàn thành không được chọn lại). Cùng logic
    is_complete ở list_orders/get_order: ưu tiên trạng thái Điều độ (WorkOrder) nếu lệnh đã có
    ít nhất 1 Lệnh SX, không thì rơi về sản lượng thực tế qua BatchExecution so với kế
    hoạch/sai số."""
    wo_status = _wo_derived_status(db, brew_order_id)
    if wo_status is not None:
        return wo_status[1]
    order = db.get(BrewOrder, brew_order_id)
    if not order:
        return False
    batches = _batch_summaries(db, brew_order_id)
    return _is_complete(batches, order.planned_volume_hl, order.volume_tolerance_hl)


def _wo_aggregate_status(wos: list) -> str:
    """1 nhãn trạng thái đại diện cho TẤT CẢ Lệnh SX (điều độ) con của 1 lệnh nấu (WorkOrder.
    brew_order_id không unique — 1 lệnh nấu có thể có nhiều Lệnh SX) — ưu tiên trạng thái "tiến xa
    nhất": đang chạy (in_progress) > đã phát hành (released) > hoàn thành/đã chốt > lập kế hoạch."""
    statuses = {w.status for w in wos}
    if WorkOrderState.IN_PROGRESS.value in statuses:
        return WorkOrderState.IN_PROGRESS.value
    if WorkOrderState.RELEASED.value in statuses:
        return WorkOrderState.RELEASED.value
    if statuses and statuses <= {WorkOrderState.COMPLETED.value, WorkOrderState.CLOSED.value}:
        return WorkOrderState.CLOSED.value if statuses == {WorkOrderState.CLOSED.value} else WorkOrderState.COMPLETED.value
    if WorkOrderState.PLANNED.value in statuses:
        return WorkOrderState.PLANNED.value
    return WorkOrderState.CANCELLED.value


def _wo_derived_status(db: Session, brew_order_id: str) -> tuple:
    """Suy (is_executed, is_complete, wo_status) theo trạng thái Điều độ (WorkOrder.status) —
    is_executed CHỈ true khi đã thật sự "Phát mẻ" (dispatch, tạo mẻ nấu — state in_progress trở
    lên), KHÔNG tính "released" (đã phát hành, CHƯA phát mẻ) là "đang thực hiện" (yêu cầu người
    dùng 2026-09-01: lệnh released chưa dispatch phải hiện đúng "Đã phát hành", không phải "Đang
    nấu"). Trả None nếu lệnh này chưa có Lệnh SX (điều độ) nào (VD lệnh chỉ tạo mẻ tay ở tab
    "Mẻ sản xuất" không qua Điều độ) — caller tự rơi về cách tính qua BatchExecution trực tiếp
    (sản lượng/dung sai, xem _is_complete) cho trường hợp đó."""
    wos = db.execute(select(WorkOrder).where(WorkOrder.brew_order_id == brew_order_id)).scalars().all()
    if not wos:
        return None
    wo_status = _wo_aggregate_status(wos)
    is_executed = wo_status in (WorkOrderState.IN_PROGRESS.value, WorkOrderState.COMPLETED.value,
                                WorkOrderState.CLOSED.value)
    is_complete = wo_status in (WorkOrderState.COMPLETED.value, WorkOrderState.CLOSED.value)
    return is_executed, is_complete, wo_status


def list_orders(db: Session) -> list:
    orders = db.execute(select(BrewOrder).order_by(BrewOrder.created_at.desc())).scalars().all()
    products = {p.product_id: p for p in db.execute(select(Product)).scalars().all()}
    recipe_versions = {rv.version_id: rv for rv in db.execute(select(RecipeVersion)).scalars().all()}
    recipes = {r.recipe_id: r for r in db.execute(select(Recipe)).scalars().all()}
    beer_types = {bt.beer_type_id: bt for bt in db.execute(select(BeerType)).scalars().all()}
    out = []
    for o in orders:
        batches = _batch_summaries(db, o.brew_order_id)
        prod = products.get(o.product_id)
        rv = recipe_versions.get(o.recipe_version_id)
        recipe = recipes.get(rv.recipe_id) if rv else None
        beer_type = beer_types.get(recipe.beer_type_id) if recipe else None
        tolerance = o.volume_tolerance_hl
        wo_derived = _wo_derived_status(db, o.brew_order_id)
        if wo_derived is not None:
            is_executed, is_complete, wo_status = wo_derived
        else:
            is_executed = len(batches) > 0
            is_complete = _is_complete(batches, o.planned_volume_hl, tolerance)
            wo_status = None
        out.append({
            "brew_order_id": o.brew_order_id, "order_code": o.order_code,
            "product_id": o.product_id, "product_code": prod.code if prod else None,
            "product_desc": o.product_desc, "recipe_version_id": o.recipe_version_id,
            "recipe_code": recipe.code if recipe else None,
            "recipe_name": recipe.name if recipe else None,
            "beer_type_id": beer_type.beer_type_id if beer_type else None,
            "beer_type_code": beer_type.code if beer_type else None,
            "beer_type_name": beer_type.name if beer_type else None,
            "recipe_version_no": rv.version_no if rv else None,
            "recipe_note": rv.change_reason if rv else None,
            "planned_batch_count": o.planned_batch_count,
            "tank_lm": o.tank_lm, "batch_range_from": o.batch_range_from, "batch_range_to": o.batch_range_to,
            "actual_tank_lm": None, "actual_batch_range": None,
            "created_at": o.created_at, "records": [],
            "planned_volume_hl": o.planned_volume_hl, "volume_tolerance_hl": o.volume_tolerance_hl,
            "actual_volume_hl": round(sum(b.actual_qty or 0.0 for b in batches), 3),
            "is_executed": is_executed,
            "is_complete": is_complete,
            "wo_status": wo_status,
            "locked": o.locked, "locked_by": o.locked_by,
            "issued_by": o.issued_by, "executor_unit": o.executor_unit, "warehouse_keeper": o.warehouse_keeper,
            "reference_note": o.reference_note, "start_date": o.start_date, "end_date": o.end_date,
            "safety_note": o.safety_note,
        })
    return out


def get_order(db: Session, brew_order_id: str) -> dict:
    order = db.get(BrewOrder, brew_order_id)
    if not order:
        raise NotFoundError("Lệnh nấu không tồn tại.")
    lines = db.execute(select(BrewOrderMaterialLine).where(
        BrewOrderMaterialLine.brew_order_id == brew_order_id).order_by(BrewOrderMaterialLine.seq)).scalars().all()
    prod = db.get(Product, order.product_id) if order.product_id else None
    recipe_version = db.get(RecipeVersion, order.recipe_version_id) if order.recipe_version_id else None
    recipe = db.get(Recipe, recipe_version.recipe_id) if recipe_version else None

    # Tồn kho TỪNG mã thành viên hiện tại (KHÔNG snapshot — nhóm có thể đổi tồn/thành viên
    # sau khi lệnh đã lập, nên hiện số sống để thủ kho biết thực tế đang còn mã nào).
    live_company_stock, live_workshop_stock = _stock_snapshot(db)
    materials_by_id = _materials_by_id(db)
    actual_usage = _actual_usage_by_material(db, [])

    line_out = []
    for l in lines:
        company = l.stock_company_snapshot or 0
        workshop = l.stock_workshop_snapshot or 0
        if l.member_qty_snapshot:
            # Dòng nhóm khai định mức riêng từng thành viên — định mức + shortage TỪNG mã đã
            # snapshot lúc lập lệnh (đúng bản chất văn bản đã ký), chỉ merge thêm actual_used
            # (luôn tính LIVE vì phản ánh những gì đã thực sự dùng từ lúc đó tới giờ).
            member_breakdown = [{**mb, "actual_used": actual_usage.get(mb["material_id"], 0) or 0}
                               for mb in l.member_qty_snapshot]
            shortage = not l.is_header and all(mb["shortage"] for mb in member_breakdown)
            member_ids = [mb["material_id"] for mb in member_breakdown if mb["material_id"]]
        else:
            shortage = (not l.is_header) and l.qty_total is not None and l.qty_total > (company + workshop)
            member_ids = _resolve_group_members(db, l.material_group_code)
            member_breakdown = _member_breakdown(member_ids, live_company_stock, live_workshop_stock,
                                                 materials_by_id, actual_usage if l.material_group_code else None)
        line_out.append({
            "line_id": l.line_id, "seq": l.seq, "stt_label": l.stt_label, "is_header": l.is_header,
            "material_id": l.material_id, "material_name": l.material_name, "uom": l.uom,
            "material_group_code": l.material_group_code,
            "member_material_ids": member_ids,
            "member_breakdown": member_breakdown,
            "qty_per_batch": l.qty_per_batch, "qty_total": l.qty_total, "unit_price": l.unit_price,
            "stock_company_snapshot": l.stock_company_snapshot,
            "stock_workshop_snapshot": l.stock_workshop_snapshot, "shortage": shortage,
            "qty_from_company": l.qty_from_company, "qty_from_workshop": l.qty_from_workshop,
        })

    tolerance = order.volume_tolerance_hl
    batches = _batch_summaries(db, brew_order_id)
    wo_derived = _wo_derived_status(db, brew_order_id)
    if wo_derived is not None:
        is_executed, is_complete, wo_status = wo_derived
    else:
        is_executed = len(batches) > 0
        is_complete = _is_complete(batches, order.planned_volume_hl, tolerance)
        wo_status = None
    return {
        "brew_order_id": order.brew_order_id, "order_code": order.order_code,
        "product_id": order.product_id, "product_code": prod.code if prod else None,
        "product_name": prod.name if prod else None, "product_desc": order.product_desc,
        "recipe_version_id": order.recipe_version_id,
        "recipe_code": recipe.code if recipe else None,
        "recipe_name": recipe.name if recipe else None,
        "recipe_version_no": recipe_version.version_no if recipe_version else None,
        "recipe_note": recipe_version.change_reason if recipe_version else None,
        "planned_batch_count": order.planned_batch_count,
        "bx_min": order.bx_min, "bx_max": order.bx_max,
        "tank_lm": order.tank_lm, "batch_range_from": order.batch_range_from,
        "batch_range_to": order.batch_range_to,
        "actual_tank_lm": None, "actual_batch_range": None,
        "created_by": order.created_by, "created_at": order.created_at,
        "records": [],
        "planned_volume_hl": order.planned_volume_hl, "volume_tolerance_hl": order.volume_tolerance_hl,
        "actual_volume_hl": round(sum(b.actual_qty or 0.0 for b in batches), 3),
        "is_executed": is_executed,
        "is_complete": is_complete,
        "wo_status": wo_status,
        "lines": line_out,
        "locked": order.locked, "locked_by": order.locked_by,
        "issued_by": order.issued_by, "executor_unit": order.executor_unit,
        "warehouse_keeper": order.warehouse_keeper, "reference_note": order.reference_note,
        "start_date": order.start_date, "end_date": order.end_date, "safety_note": order.safety_note,
    }


def delete_order(db: Session, brew_order_id: str, user) -> None:
    order = db.get(BrewOrder, brew_order_id)
    if not order:
        raise NotFoundError("Lệnh nấu không tồn tại.")
    if _has_any_execution(db, brew_order_id):
        raise DomainError("Lệnh nấu đã được thực hiện — không thể xóa.")
    # WorkOrder.brew_order_id là FK NOT NULL không ondelete — 1 Lệnh SX (điều độ) dù CHƯA
    # dispatch (còn "planned"/"released", _has_any_execution() ở trên không chặn) vẫn tham
    # chiếu Lệnh nấu này, xóa thẳng sẽ vỡ FK 547 trên MSSQL (SQLite không enforce nên test
    # trước đây không lộ). Phải xóa/hủy Lệnh SX con trước.
    if db.execute(select(WorkOrder.wo_id).where(WorkOrder.brew_order_id == brew_order_id)).first():
        raise DomainError("Lệnh nấu đã có Lệnh SX (điều độ) — xóa Lệnh SX trước khi xóa Lệnh nấu.")
    for l in db.execute(select(BrewOrderMaterialLine).where(
            BrewOrderMaterialLine.brew_order_id == brew_order_id)).scalars().all():
        db.delete(l)
    db.flush()  # MSSQL enforce FK: xóa material line (con) trước brew_order (cha).
    record_audit(db, entity_type="brew_order", entity_id=brew_order_id, action="delete",
                 actor=user, before={"order_code": order.order_code})
    db.delete(order)
    db.commit()


# _assert_unlocked chuyển từ routers/brewing.py sang đây trước khi module Nấu-Lọc-Chiết cũ bị
# xóa — vẫn dùng bởi routers/brewing.py (Lệnh nấu) và qc_catalog.py hiện tại (giữ nguyên hành
# vi, chỉ dọn các hàm "Phát mẻ" (create_brew_record/create_brew_batch/create_brew_batches_bulk
# và các helper riêng của chúng) đã không còn caller nào sau khi module đó bị xóa).

def _assert_unlocked(*objs) -> None:
    """Chặn sửa/xóa/chuyển trạng thái nếu CHÍNH bản ghi HOẶC bất kỳ lệnh cha nào trong chuỗi
    đã bị "Khóa lô" (BrewOrder.locked — trước đây có endpoint riêng khóa/mở khóa theo chuỗi
    ngược dòng ở module Nấu-Lọc-Chiết cũ, nay đã xóa cùng module đó; cột vẫn giữ để guard này
    tiếp tục an toàn nếu có nơi khác set locked=True) HOẶC đang bị QA "HOLD" (xem
    services/quality.py::set_hold — tách biệt với khóa sổ). Truyền vào bản ghi + các cha của
    nó — Lệnh nấu không có quality_status riêng nên chỉ getattr rỗng."""
    for obj in objs:
        if obj is None:
            continue
        if getattr(obj, "locked", False):
            raise DomainError("Bản ghi đã bị khóa (lô đã chốt) — không thể sửa/xóa. Chỉ admin mới mở khóa được.")
        if getattr(obj, "quality_status", None) == "on_hold":
            raise DomainError("Bản ghi đang bị QA giữ (HOLD) — không thể sửa/xóa/chuyển bước. Phải RELEASE trước (tab Chất lượng).")

