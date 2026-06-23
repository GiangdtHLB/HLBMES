"""Logic BOM dùng chung: scale theo mẻ, tồn khả dụng, đối chiếu định mức↔thực tế.

Dùng cho: kiểm tra tồn trước khi tạo mẻ (§7.1), chặn consume vượt định mức,
bảng đối chiếu trong chi tiết mẻ, và báo cáo định mức NVL nhiều mẻ.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..common import LotStatus
from ..errors import DomainError
from ..models.master import Material
from ..models.materials import GenealogyEdge, MaterialLot


def material_code_for_lot(db: Session, lot) -> str:
    if lot and lot.material_id:
        m = db.get(Material, lot.material_id)
        return m.code if m else lot.material_id
    return lot.lot_code if lot else "?"


def factor_for(snapshot: dict, planned_qty: float) -> float:
    if planned_qty is None or planned_qty <= 0:
        raise DomainError("SL kế hoạch (planned_qty) phải > 0 để scale định mức BOM.")
    base = (snapshot or {}).get("base_qty") or 0
    return (planned_qty / base) if base else 1.0


def actual_consumed(db: Session, batch_id: str) -> dict:
    """Tổng đã tiêu thụ theo material_code (từ cạnh genealogy consume)."""
    edges = db.execute(select(GenealogyEdge).where(
        GenealogyEdge.to_type == "batch", GenealogyEdge.to_id == batch_id,
        GenealogyEdge.relation == "consume")).scalars().all()
    out = {}
    for e in edges:
        lot = db.get(MaterialLot, e.from_id)
        code = material_code_for_lot(db, lot)
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
    """Đối chiếu định mức (scale) ↔ thực tế cho một mẻ."""
    snap = batch.recipe_snapshot or {}
    factor = factor_for(snap, batch.planned_qty)
    actual = actual_consumed(db, batch.batch_id)
    lines, seen = [], set()
    for m in (snap.get("materials") or []):
        code = m.get("material_code")
        seen.add(code)
        planned = round((m.get("qty", 0) or 0) * factor, 3)
        act = round(actual.get(code, 0.0), 3)
        tol = m.get("tol_pct", 0) or 0
        diff, pct, status = _classify(planned, act, tol)
        lines.append({"material_code": code, "uom": m.get("uom"), "tol_pct": tol,
                      "planned": planned, "actual": act, "diff": diff, "pct": pct, "status": status})
    extras = [{"material_code": c, "actual": round(q, 3), "status": "ngoai_bom"}
              for c, q in actual.items() if c not in seen]
    return {"batch_code": batch.batch_code, "base_qty": snap.get("base_qty"),
            "base_uom": snap.get("base_uom"), "planned_qty": batch.planned_qty,
            "factor": round(factor, 4), "lines": lines, "extras": extras}


def stock_available(db: Session) -> dict:
    """Tồn khả dụng (status=available) theo material_code."""
    lots = db.execute(select(MaterialLot).where(
        MaterialLot.status == LotStatus.AVAILABLE.value,
        MaterialLot.material_id.isnot(None))).scalars().all()
    out = {}
    for l in lots:
        m = db.get(Material, l.material_id)
        code = m.code if m else l.material_id
        out[code] = out.get(code, 0.0) + l.quantity
    return out


def availability(db: Session, snapshot: dict, planned_qty: float) -> dict:
    """Kiểm tra tồn khả dụng so với nhu cầu BOM (đã scale) cho một mẻ dự kiến."""
    factor = factor_for(snapshot, planned_qty)
    avail = stock_available(db)
    # Gộp định mức theo material_code (BOM có thể trùng dòng) trước khi so tồn.
    req_by, uom_by = {}, {}
    for m in (snapshot.get("materials") or []):
        code = m.get("material_code")
        req_by[code] = req_by.get(code, 0.0) + (m.get("qty", 0) or 0) * factor
        uom_by.setdefault(code, m.get("uom"))
    rows, shortage = [], False
    for code, req in req_by.items():
        req = round(req, 3)
        have = round(avail.get(code, 0.0), 3)
        ok = have >= req
        if not ok:
            shortage = True
        rows.append({"material_code": code, "uom": uom_by.get(code), "required": req,
                     "available": have, "ok": ok, "short": round(max(req - have, 0), 3)})
    return {"factor": round(factor, 4), "shortage": shortage, "rows": rows}


def availability_with_alternates(db: Session, snapshot: dict, planned_qty: float) -> dict:
    """Như availability(), nhưng khi NVL chính thiếu thì gợi ý nguyên liệu thay thế.

    Mỗi dòng BOM có thể khai key 'alternates': list[{material_code, factor, priority}].
    factor = hệ số quy đổi (cần qty_chính × factor của NVL thay thế). priority nhỏ = ưu tiên.
    """
    factor = factor_for(snapshot, planned_qty)
    avail = stock_available(db)
    # Gộp định mức + giữ alternates theo material_code.
    req_by, uom_by, alt_by = {}, {}, {}
    for m in (snapshot.get("materials") or []):
        code = m.get("material_code")
        req_by[code] = req_by.get(code, 0.0) + (m.get("qty", 0) or 0) * factor
        uom_by.setdefault(code, m.get("uom"))
        if m.get("alternates"):
            alt_by.setdefault(code, m.get("alternates"))
    rows, shortage = [], False
    for code, req in req_by.items():
        req = round(req, 3)
        have = round(avail.get(code, 0.0), 3)
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
        rows.append({"material_code": code, "uom": uom_by.get(code), "required": req,
                     "available": have, "ok": ok, "short": short, "alternates": suggestions})
    return {"factor": round(factor, 4), "shortage": shortage, "rows": rows}


def ceiling_for_material(db: Session, batch, material_code: str):
    """Ngưỡng tối đa cho phép tiêu thụ một vật tư (định mức scale × (1+dung sai)).

    Trả về None nếu vật tư không có trong BOM (không giới hạn)."""
    snap = batch.recipe_snapshot or {}
    factor = factor_for(snap, batch.planned_qty)
    qty_sum, tol = 0.0, 0.0
    found = False
    for m in (snap.get("materials") or []):
        if m.get("material_code") == material_code:
            found = True
            qty_sum += (m.get("qty", 0) or 0)
            tol = max(tol, (m.get("tol_pct", 0) or 0))  # dùng dung sai lớn nhất nếu trùng dòng
    if not found:
        return None
    planned = qty_sum * factor
    return round(planned * (1 + tol / 100.0), 3), round(planned, 3)
