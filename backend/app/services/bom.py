"""Logic BOM dùng chung: scale theo mẻ, tồn khả dụng, đối chiếu định mức↔thực tế.

Dùng cho: kiểm tra tồn trước khi tạo mẻ (§7.1), chặn consume vượt định mức,
bảng đối chiếu trong chi tiết mẻ, và báo cáo định mức NVL nhiều mẻ.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..common import LotStatus
from ..errors import DomainError
from ..models.brewing import BrewOrderMaterialLine
from ..models.master import Material, MaterialAltGroup
from ..models.materials import GenealogyEdge, MaterialLot


def material_code_for_lot(db: Session, lot) -> str:
    if lot and lot.material_id:
        m = db.get(Material, lot.material_id)
        return m.code if m else lot.material_id
    return lot.lot_code if lot else "?"


def _material_codes_for_lots(db: Session, lots: list) -> dict:
    """Tra mã vật tư cho nhiều lô cùng lúc bằng 1 câu IN(...) thay vì 1 `db.get(Material, ...)`
    riêng cho từng lô (N+1) — dùng khi gộp nhiều mẻ/nhiều lô như báo cáo định mức NVL."""
    material_ids = list({l.material_id for l in lots if l.material_id})
    code_by_material_id = {m.material_id: m.code for m in (db.execute(
        select(Material).where(Material.material_id.in_(material_ids))).scalars().all()
        if material_ids else [])}
    return {l.lot_id: (code_by_material_id.get(l.material_id, l.material_id) if l.material_id
                       else l.lot_code) for l in lots}


def _group_member_codes(db: Session, group_code: str) -> set[str]:
    """Mã vật tư CỤ THỂ thuộc 1 Nhóm vật tư thay thế (models/master.py::MaterialAltGroup) —
    dùng để gộp thực tế tiêu thụ (thủ kho có thể xuất BẤT KỲ thành viên nào) khi so với dòng
    BOM chỉ khai theo nhóm, không khai member_qty riêng từng thành viên."""
    g = db.execute(select(MaterialAltGroup).where(MaterialAltGroup.code == group_code)).scalar_one_or_none()
    if not g or not g.member_material_ids:
        return set()
    mats = db.execute(select(Material).where(Material.material_id.in_(g.member_material_ids))).scalars().all()
    return {m.code for m in mats}


def _selected_codes_for_group(db: Session, brew_order_id: str, group_code: str):
    """Mã thành viên NÀO thực sự được chọn cho 1 dòng "Nhóm vật tư thay thế" khai kiểu
    member_qty (mỗi thành viên 1 định mức riêng) của MỘT Lệnh nấu cụ thể — mirror
    services/brew_order.py::_build_group_line's `selected_codes` param, nhưng đọc NGƯỢC từ
    BrewOrderMaterialLine.member_qty_snapshot đã lưu lúc lập Lệnh nấu (chỉ còn các thành viên
    ĐÃ CHỌN, xem services/brew_order.py::_persist_material_lines) thay vì nhận trực tiếp từ
    payload lúc đó. Trả None nếu không tìm thấy dòng nào khớp (VD dòng khai kiểu "dùng chung 1
    số" không qua member_qty, hoặc mẻ không gắn Lệnh nấu nào) — nghĩa là KHÔNG lọc gì (giữ
    nguyên toàn bộ thành viên trong công thức), khác {} (rỗng) nghĩa là có dòng nhưng chưa chọn
    gì cả."""
    if not brew_order_id or not group_code:
        return None
    line = db.execute(select(BrewOrderMaterialLine).where(
        BrewOrderMaterialLine.brew_order_id == brew_order_id,
        BrewOrderMaterialLine.material_group_code == group_code)).scalars().first()
    if not line or line.member_qty_snapshot is None:
        return None
    return {mq["material_code"] for mq in line.member_qty_snapshot if mq.get("material_code")}


def codes_for_dispense(db: Session, code: str) -> list[str]:
    """Mã vật tư THẬT có thể xuất kho cho 1 `code` chọn ở màn Cấp liệu — nếu `code` là mã vật
    tư cụ thể (Material.code) thì giữ nguyên; nếu là mã Nhóm vật tư thay thế (không xuất kho
    trực tiếp được, chỉ dùng để khai định mức, xem models/master.py::MaterialAltGroup) thì trả
    về mọi mã thành viên (xuất lô của BẤT KỲ thành viên nào cũng hợp lệ)."""
    if db.execute(select(Material.material_id).where(Material.code == code)).first():
        return [code]
    members = _group_member_codes(db, code)
    return sorted(members) if members else [code]


def _expand_materials(db: Session, materials: list, brew_order_id: str = None) -> list[dict]:
    """Chuẩn hoá từng dòng BOM (snapshot.materials) thành 1 dòng CỤ THỂ có material_code —
    dòng khai qua Nhóm vật tư thay thế (alt_group_code) không có material_code trực tiếp
    (mirror _build_group_line ở services/brew_order.py, module Lệnh nấu cũ, giản lược bỏ phần
    tách kho công ty/phân xưởng vì không áp dụng ở tầng Mẻ sản xuất):
    - material_code thường: giữ nguyên, chỉ bổ sung material_name (tra Danh mục vật tư).
    - member_qty = [{material_code, qty}, ...]: mỗi thành viên có định mức RIÊNG. Công thức có
      thể khai NHIỀU thành viên khả dụng (VD "Malt Pilsner HOẶC Malt Vienna, chọn 1"), nhưng 1
      Lệnh nấu CỤ THỂ chỉ thực sự dùng phần đã CHỌN lúc lập lệnh (selection_mode "single"/
      "multi", xem BrewOrderMaterialLine.member_qty_snapshot) — nếu `brew_order_id` cho biết
      lựa chọn đó, CHỈ tách dòng cho các thành viên ĐÃ CHỌN (mirror _build_group_line's
      `selected_codes` filter); nếu không xác định được lựa chọn (mẻ không gắn Lệnh nấu, hoặc
      dòng không khớp Lệnh nấu nào), giữ nguyên TOÀN BỘ thành viên khai trong công thức (an
      toàn hơn — không bỏ sót định mức). Mỗi dòng con material_code THẬT nên so với thực tế
      tiêu thụ (actual_consumed) như dòng thường, không cần gộp gì thêm (match_codes = chính nó).
    - CHỈ có alt_group_code (không member_qty): 1 định mức DÙNG CHUNG cho cả nhóm, không quan
      tâm xuất mã thành viên nào — match_codes = TOÀN BỘ mã thành viên của nhóm, để cộng dồn
      thực tế tiêu thụ dù ghi nhận qua bất kỳ mã nào trong nhóm. Tên hiển thị = tên nhóm."""
    name_by_code = {m.code: m.name for m in db.execute(select(Material)).scalars().all()}
    out = []
    for m in materials or []:
        code = m.get("material_code")
        if code:
            out.append({**m, "material_name": name_by_code.get(code), "match_codes": {code}})
            continue
        group_code = m.get("alt_group_code")
        member_qty = m.get("member_qty")
        if member_qty:
            selected = _selected_codes_for_group(db, brew_order_id, group_code)
            entries = ([mq for mq in member_qty if mq.get("material_code") in selected]
                      if selected is not None else member_qty)
            for mq in entries:
                mcode = mq.get("material_code")
                out.append({"material_code": mcode, "material_name": name_by_code.get(mcode),
                           "qty": mq.get("qty", 0), "uom": m.get("uom"), "tol_pct": m.get("tol_pct", 0),
                           "group_code": group_code, "match_codes": {mcode}})
            continue
        if group_code:
            g = db.execute(select(MaterialAltGroup).where(MaterialAltGroup.code == group_code)).scalar_one_or_none()
            out.append({"material_code": group_code, "material_name": g.name if g else group_code,
                       "qty": m.get("qty", 0), "uom": m.get("uom"), "tol_pct": m.get("tol_pct", 0),
                       "is_group": True, "match_codes": _group_member_codes(db, group_code) or {group_code}})
    return out


def factor_for(snapshot: dict, planned_qty: float, scale: bool = False) -> float:
    """Mặc định (`scale=False`) LUÔN trả 1.0 — định mức NVL của 1 Mẻ sản xuất KHÔNG scale theo
    SL kế hoạch (hl) của riêng mẻ đó so với quy mô chuẩn công thức (base_qty): "1 mẻ" luôn cần
    ĐÚNG số lượng công thức đã khai (m.get("qty")), giống hệt cách "Lệnh nấu" tính "Nhu cầu 1
    mẻ" (services/brew_order.py::_build_group_line — không nhân thêm hệ số nào, "Nhu cầu Tổng
    mẻ" nhân theo SỐ MẺ chứ không theo tỉ lệ thể tích). Xem compare_batch/ceiling_for_material/
    actual_consumed_for_match (luôn scale=False, không nhận tham số này).

    `scale=True` (CHỈ dùng cho services/scheduler.py::auto_schedule — ước lượng SƠ BỘ nhu cầu
    NVL của 1 Lệnh sản xuất TRƯỚC khi "Phát mẻ"/biết sẽ chia thành bao nhiêu mẻ, xấp xỉ "số mẻ"
    bằng tỉ lệ planned_qty/base_qty) mới thực sự nhân hệ số — quy đổi base_qty về CÙNG đơn vị
    "hl" với planned_qty trước khi chia nếu công thức khai base_uom bằng "L" (1 hl = 100 L),
    tránh lệch hệ số do khác đơn vị đo (bug thực tế đã gặp: hệ số ra 0.004 thay vì đúng tỉ lệ,
    xem lịch sử sửa 2026-08-31)."""
    if planned_qty is None or planned_qty <= 0:
        raise DomainError("SL kế hoạch (planned_qty) phải > 0.")
    if not scale:
        return 1.0
    base = (snapshot or {}).get("base_qty") or 0
    if not base:
        return 1.0
    base_uom = ((snapshot or {}).get("base_uom") or "").strip().lower()
    base_hl = base / 100.0 if base_uom == "l" else base
    return (planned_qty / base_hl) if base_hl else 1.0


def actual_consumed(db: Session, batch_id: str) -> dict:
    """Tổng đã tiêu thụ theo material_code (từ cạnh genealogy consume)."""
    edges = db.execute(select(GenealogyEdge).where(
        GenealogyEdge.to_type == "batch", GenealogyEdge.to_id == batch_id,
        GenealogyEdge.relation == "consume")).scalars().all()
    if not edges:
        return {}
    lot_ids = list({e.from_id for e in edges})
    lots = db.execute(select(MaterialLot).where(MaterialLot.lot_id.in_(lot_ids))).scalars().all()
    code_by_lot_id = _material_codes_for_lots(db, lots)
    out = {}
    for e in edges:
        code = code_by_lot_id.get(e.from_id, "?")
        out[code] = out.get(code, 0.0) + (e.quantity or 0.0)
    return out


def _classify(planned, act, tol):
    diff = round(act - planned, 3)
    pct = round((diff / planned * 100), 1) if planned else 0.0
    if planned <= 0:
        # BOM không khai định mức (qty=0): có tiêu thụ là vượt, không thì bỏ qua.
        status = "vuot" if act > 0 else "chua_dung"
    elif act == 0:
        status = "chua_dung"
    elif abs(pct) <= tol:
        status = "dat"
    elif diff > 0:
        status = "vuot"
    else:
        status = "thieu"
    return diff, pct, status


def compare_batch(db: Session, batch) -> dict:
    """Đối chiếu định mức ↔ thực tế cho một mẻ — định mức LUÔN là số công thức đã khai cho
    "1 mẻ" (m.get("qty")), KHÔNG scale theo SL kế hoạch (hl) của riêng mẻ này (xem factor_for)."""
    snap = batch.recipe_snapshot or {}
    factor = factor_for(snap, batch.planned_qty)
    actual = actual_consumed(db, batch.batch_id)
    lines, seen = [], set()
    for m in _expand_materials(db, snap.get("materials"), brew_order_id=batch.order_id):
        code = m.get("material_code")
        match_codes = m.get("match_codes") or {code}
        seen |= match_codes
        planned = round(m.get("qty", 0) or 0, 3)
        act = round(sum(actual.get(c, 0.0) for c in match_codes), 3)
        tol = m.get("tol_pct", 0) or 0
        diff, pct, status = _classify(planned, act, tol)
        lines.append({"material_code": code, "material_name": m.get("material_name"), "uom": m.get("uom"),
                      "tol_pct": tol, "planned": planned, "actual": act, "diff": diff, "pct": pct,
                      "status": status, "is_group": bool(m.get("is_group")), "match_codes": sorted(match_codes)})
    extras = [{"material_code": c, "actual": round(q, 3), "status": "ngoai_bom"}
              for c, q in actual.items() if c not in seen]
    return {"batch_code": batch.batch_code, "base_qty": snap.get("base_qty"),
            "base_uom": snap.get("base_uom"), "planned_qty": batch.planned_qty,
            "factor": round(factor, 4), "lines": lines, "extras": extras}


def stock_available(db: Session) -> dict:
    """Tồn khả dụng (available/released — mirror warehouse.py::stock_on_hand) theo material_code."""
    lots = db.execute(select(MaterialLot).where(
        MaterialLot.status.in_([LotStatus.AVAILABLE.value, LotStatus.RELEASED.value]),
        MaterialLot.material_id.isnot(None))).scalars().all()
    if not lots:
        return {}
    code_by_lot_id = _material_codes_for_lots(db, lots)
    out = {}
    for l in lots:
        code = code_by_lot_id[l.lot_id]
        out[code] = out.get(code, 0.0) + l.quantity
    return out


def availability(db: Session, snapshot: dict, planned_qty: float, brew_order_id: str = None,
                 scale: bool = False) -> dict:
    """Kiểm tra tồn khả dụng so với nhu cầu BOM cho một mẻ dự kiến — mặc định (`scale=False`)
    nhu cầu LUÔN là số công thức đã khai cho "1 mẻ", KHÔNG scale theo planned_qty (xem
    factor_for) — dùng cho "Tạo mẻ"/"Kiểm tra tồn". `scale=True` CHỈ dùng cho
    services/scheduler.py::auto_schedule (ước lượng sơ bộ Ở CẤP LỆNH SX, trước khi biết chia
    thành bao nhiêu mẻ). Truyền `brew_order_id` (nếu đã chọn Lệnh nấu) để chỉ tính đúng thành
    viên ĐÃ CHỌN của dòng khai theo Nhóm vật tư thay thế kiểu member_qty (xem _expand_materials)."""
    factor = factor_for(snapshot, planned_qty, scale=scale)
    avail = stock_available(db)
    # Gộp định mức theo material_code (BOM có thể trùng dòng) trước khi so tồn.
    req_by, uom_by, match_by, name_by = {}, {}, {}, {}
    for m in _expand_materials(db, snapshot.get("materials"), brew_order_id=brew_order_id):
        code = m.get("material_code")
        req_by[code] = req_by.get(code, 0.0) + (m.get("qty", 0) or 0) * factor
        uom_by.setdefault(code, m.get("uom"))
        match_by.setdefault(code, m.get("match_codes") or {code})
        if m.get("material_name"):
            name_by[code] = m["material_name"]
    rows, shortage = [], False
    for code, req in req_by.items():
        req = round(req, 3)
        have = round(sum(avail.get(c, 0.0) for c in match_by[code]), 3)
        ok = have >= req
        if not ok:
            shortage = True
        rows.append({"material_code": code, "material_name": name_by.get(code), "uom": uom_by.get(code),
                     "required": req, "available": have, "ok": ok, "short": round(max(req - have, 0), 3)})
    return {"factor": round(factor, 4), "shortage": shortage, "rows": rows}


def availability_with_alternates(db: Session, snapshot: dict, planned_qty: float,
                                 brew_order_id: str = None) -> dict:
    """Như availability(), nhưng khi NVL chính thiếu thì gợi ý nguyên liệu thay thế.

    Mỗi dòng BOM có thể khai key 'alternates': list[{material_code, factor, priority}].
    factor = hệ số quy đổi (cần qty_chính × factor của NVL thay thế). priority nhỏ = ưu tiên.
    `brew_order_id`: xem availability()."""
    factor = factor_for(snapshot, planned_qty)
    avail = stock_available(db)
    # Gộp định mức + giữ alternates theo material_code (KHÔNG scale theo planned_qty, xem
    # availability()/factor_for).
    req_by, uom_by, alt_by, match_by, name_by = {}, {}, {}, {}, {}
    for m in _expand_materials(db, snapshot.get("materials"), brew_order_id=brew_order_id):
        code = m.get("material_code")
        req_by[code] = req_by.get(code, 0.0) + (m.get("qty", 0) or 0)
        uom_by.setdefault(code, m.get("uom"))
        match_by.setdefault(code, m.get("match_codes") or {code})
        if m.get("material_name"):
            name_by[code] = m["material_name"]
        if m.get("alternates"):
            alt_by.setdefault(code, m.get("alternates"))
    rows, shortage = [], False
    for code, req in req_by.items():
        req = round(req, 3)
        have = round(sum(avail.get(c, 0.0) for c in match_by[code]), 3)
        ok = have >= req
        short = round(max(req - have, 0), 3)
        suggestions = []
        if not ok:
            shortage = True
            need_more = short  # phần thiếu của NVL chính (theo đơn vị NVL chính)
            for alt in sorted(alt_by.get(code, []), key=lambda a: a.get("priority", 99)):
                acode = alt.get("material_code")
                af = alt.get("factor")            # 0 là giá trị hợp lệ (không quy đổi)
                af = 1 if af is None else af
                alt_need = round(need_more * af, 3)         # quy đổi sang NVL thay thế
                alt_have = round(avail.get(acode, 0.0), 3)
                suggestions.append({"material_code": acode, "factor": af,
                                    "need": alt_need, "available": alt_have,
                                    "covers": alt_have >= alt_need})
        rows.append({"material_code": code, "material_name": name_by.get(code), "uom": uom_by.get(code),
                     "required": req, "available": have, "ok": ok, "short": short, "alternates": suggestions})
    return {"factor": round(factor, 4), "shortage": shortage, "rows": rows}


def ceiling_for_material(db: Session, batch, material_code: str):
    """Ngưỡng tối đa cho phép tiêu thụ một vật tư (định mức công thức × (1+dung sai), KHÔNG
    scale theo planned_qty — xem factor_for) — vật tư thuộc 1 Nhóm vật tư thay thế khai KHÔNG
    có member_qty riêng thì ngưỡng là CỦA CẢ NHÓM (dùng chung, xem _expand_materials), không
    phải riêng mã này.

    Trả về None nếu vật tư không có trong BOM (không giới hạn)."""
    snap = batch.recipe_snapshot or {}
    qty_sum, tol = 0.0, 0.0
    found = False
    for m in _expand_materials(db, snap.get("materials"), brew_order_id=batch.order_id):
        match_codes = m.get("match_codes") or {m.get("material_code")}
        # material_code có thể là 1 mã thành viên THẬT (gọi từ consume_lot, xem
        # bom.material_code_for_lot) hoặc chính mã dòng BOM này (gọi từ dispense.py::
        # adjust_actual, người dùng chọn thẳng mã nhóm ở màn Cấp liệu) — khớp cả 2 trường hợp.
        if material_code in match_codes or material_code == m.get("material_code"):
            found = True
            qty_sum += (m.get("qty", 0) or 0)
            tol = max(tol, (m.get("tol_pct", 0) or 0))  # dùng dung sai lớn nhất nếu trùng dòng
    if not found:
        return None
    return round(qty_sum * (1 + tol / 100.0), 3), round(qty_sum, 3)


def actual_consumed_for_match(db: Session, batch, material_code: str) -> float:
    """Thực tế ĐÃ tiêu thụ tính cho phần "ngưỡng" của material_code (xem ceiling_for_material)
    — nếu material_code thuộc 1 dòng BOM khai theo Nhóm vật tư thay thế (không member_qty
    riêng), cộng dồn thực tế của MỌI mã thành viên trong nhóm (không chỉ riêng mã này), vì
    ngưỡng đó vốn dùng CHUNG cho cả nhóm. Khớp cả khi gọi bằng 1 mã thành viên THẬT lẫn khi
    gọi thẳng bằng mã nhóm (xem ceiling_for_material)."""
    snap = batch.recipe_snapshot or {}
    actual = actual_consumed(db, batch.batch_id)
    for m in _expand_materials(db, snap.get("materials"), brew_order_id=batch.order_id):
        match_codes = m.get("match_codes") or {m.get("material_code")}
        if material_code in match_codes or material_code == m.get("material_code"):
            return sum(actual.get(c, 0.0) for c in match_codes)
    return actual.get(material_code, 0.0)
