"""Nhập "Lệnh đóng hàng" (file Excel do bộ phận điều vận lập, 2 sheet HL/ĐM) và tách thành
các "Biên bản bàn giao hàng hóa" (LoadSlip) — mỗi xe (SỐ XE) trong sheet gộp thành 1 phiếu,
kèm danh mục hàng hóa (LoadSlipLine) lấy từ các cột SKU có số lượng > 0 trên các dòng của xe
đó. Đây là chứng từ giấy tờ nội bộ (Kho thành phẩm bàn giao cho xe/lái xe đi giao hàng),
KHÔNG trừ tồn kho WMS — khác với Shipment/Pallet vốn gắn với lô/pallet cụ thể.

Cột khuyến mại rời (LON/Lốc ... KM) đã được người lập lệnh tách riêng khỏi cột vỉ/thùng đủ
số ngay trong file gốc — ở đây chỉ cần giữ nguyên tách đó (is_promo=True, ĐVT Lon/Lốc), không
cần tính lại số lẻ khi 1 khuyến mại (VD 3 lon) không đủ đóng nguyên 1 vỉ 24 lon."""

import io
import re
from datetime import datetime, timezone
from typing import Optional

import openpyxl
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..common import new_id, utcnow
from ..errors import DomainError, NotFoundError
from ..models.wms import LoadSlip, LoadSlipLine

SHEET_TYPES = ["HL", "ĐM"]

# Các cột không phải hàng hóa (metadata điều vận/tài chính) — bỏ qua khi quét cột SKU.
_METADATA_HEADERS = {
    "pl", "cân tải trọng xe", "ghép tải ca 3", "ghép tải đm", "tổng trọng tải xe",
    "% trọng tải xe", "tiền hàng", "npp trả tm", "npp ck", "check hình ảnh",
    "số điện thoại lái xe", "thu vỏ keg", "thu vỏ chai", "thu pallet",
}
_STOP_MARKER = "tổng keg"


def _clean_header(v) -> str:
    if v is None:
        return ""
    return re.sub(r"\s+", " ", str(v)).strip()


def _classify_column(header: str) -> Optional[dict]:
    """Trả None nếu cột không phải hàng hóa; ngược lại {"uom", "is_promo"}."""
    h = _clean_header(header)
    if not h:
        return None
    hl = h.lower()
    if hl in _METADATA_HEADERS:
        return None
    is_promo = "km" in hl
    if hl.startswith("lon"):
        uom = "Lon"
    elif hl.startswith("lốc"):
        uom = "Lốc"
    elif hl.startswith("vỉ"):
        uom = "Vỉ"
    elif hl.startswith("gông"):
        uom = "Gông"
    elif hl.startswith("chai"):
        uom = "Chai" if hl.endswith("(chai)") else "Két"
    elif hl.startswith("bia hơi") or hl.startswith("bia tươi"):
        uom = "Lít"
    else:
        uom = "SL"
    return {"uom": uom, "is_promo": is_promo}


def _find_header_row(ws) -> int:
    for r in range(1, 16):
        for c in range(1, ws.max_column + 1):
            if _clean_header(ws.cell(row=r, column=c).value).upper() == "SỐ XE":
                return r
    raise DomainError("Không tìm thấy dòng tiêu đề (cột 'SỐ XE') trong sheet.")


def _parse_sheet_meta(ws) -> tuple[Optional[str], Optional[datetime]]:
    """Tìm 'Ca X' và 'Ngày D tháng M năm Y' trong vài dòng/ cột đầu sheet."""
    shift_label, order_date = None, None
    for r in range(1, 6):
        for c in range(1, 4):
            v = ws.cell(row=r, column=c).value
            if not isinstance(v, str):
                continue
            m_shift = re.search(r"Ca\s*\S+", v)
            if m_shift and not shift_label:
                shift_label = m_shift.group(0).strip()
            m_date = re.search(r"[Nn]gày\s*(\d+)\s*tháng\s*(\d+)\s*năm\s*(\d+)", v)
            if m_date and not order_date:
                d, mth, y = (int(x) for x in m_date.groups())
                try:
                    order_date = datetime(y, mth, d, tzinfo=timezone.utc)
                except ValueError:
                    pass
    return shift_label, order_date


def _parse_sheet(ws) -> list[dict]:
    header_row = _find_header_row(ws)
    col_by_name = {}
    for c in range(1, ws.max_column + 1):
        h = _clean_header(ws.cell(row=header_row, column=c).value).upper()
        if h and h not in col_by_name:
            col_by_name[h] = c
    required = ["SỐ XE", "TÊN LX", "NPP VÀ NVBH", "GHI CHÚ", "SỐ QĐ KM"]
    missing = [r for r in required if r not in col_by_name]
    if missing:
        raise DomainError(f"Sheet thiếu cột bắt buộc: {', '.join(missing)}.")
    c_plate, c_driver = col_by_name["SỐ XE"], col_by_name["TÊN LX"]
    c_npp, c_note, c_qdkm = col_by_name["NPP VÀ NVBH"], col_by_name["GHI CHÚ"], col_by_name["SỐ QĐ KM"]

    product_cols = []  # [(col_idx, product_name, uom, is_promo)]
    for c in range(1, ws.max_column + 1):
        if c in (c_plate, c_driver, c_npp, c_note, c_qdkm) or c in (
            col_by_name.get("TỔ LX"), col_by_name.get("TỔ NPP/NVBH")):
            continue
        header = _clean_header(ws.cell(row=header_row, column=c).value)
        cls = _classify_column(header)
        if cls:
            product_cols.append((c, header, cls["uom"], cls["is_promo"]))

    vehicles: list[dict] = []
    current = None
    for r in range(header_row + 1, ws.max_row + 1):
        a_val = _clean_header(ws.cell(row=r, column=c_plate).value)
        if a_val.lower() == _STOP_MARKER:
            break
        if a_val:
            if current is None or current["vehicle_plate"] != a_val:
                if current and current["lines"]:
                    vehicles.append(current)
                driver = _clean_header(ws.cell(row=r, column=c_driver).value) or None
                current = {"vehicle_plate": a_val, "driver_name": driver, "routes": [],
                          "notes": [], "lines": {}}
        if current is None:
            continue  # dòng lẻ trước khi có xe đầu tiên — bỏ qua

        npp = _clean_header(ws.cell(row=r, column=c_npp).value)
        if npp and npp not in current["routes"]:
            current["routes"].append(npp)
        note = _clean_header(ws.cell(row=r, column=c_note).value)
        if note and note not in current["notes"] and note != "#N/A":
            current["notes"].append(note)
        qdkm = ws.cell(row=r, column=c_qdkm).value
        qdkm = str(qdkm).strip() if qdkm not in (None, "") else None

        for c, name, uom, is_promo in product_cols:
            val = ws.cell(row=r, column=c).value
            try:
                qty = float(val)
            except (TypeError, ValueError):
                continue
            if not qty:
                continue
            line = current["lines"].setdefault(name, {"uom": uom, "is_promo": is_promo, "qty": 0.0, "qdkm": set()})
            line["qty"] += qty
            if qdkm:
                line["qdkm"].add(qdkm)

    if current and current["lines"]:
        vehicles.append(current)
    return vehicles


def _next_slip_code(db: Session, year: int, used: dict) -> str:
    """Số thứ tự dựa trên SỐ LỚN NHẤT đã dùng cho năm đó (không phải COUNT) — vì xóa 1 phiếu
    ở giữa vẫn phải tiếp tục tăng từ số cao nhất, không được cấp lại trùng số đã xóa."""
    suffix = f"/{year}/BBBG-BHL"
    if year not in used:
        existing = db.execute(select(LoadSlip.slip_code)
                              .where(LoadSlip.slip_code.like(f"%{suffix}"))).scalars().all()
        max_seq = 0
        for code in existing:
            try:
                max_seq = max(max_seq, int(code.split("/")[0]))
            except (ValueError, IndexError):
                pass
        used[year] = max_seq
    used[year] += 1
    return f"{used[year]:03d}{suffix}"


def import_casing_order(db: Session, filename: str, content: bytes, user) -> dict:
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    except Exception as e:
        raise DomainError(f"Không đọc được file Excel: {e}")

    seq_used: dict = {}
    created = {"HL": [], "ĐM": []}
    for sheet_type in SHEET_TYPES:
        if sheet_type not in wb.sheetnames:
            continue
        ws = wb[sheet_type]
        shift_label, order_date = _parse_sheet_meta(ws)
        vehicles = _parse_sheet(ws)
        for v in vehicles:
            year = order_date.year if order_date else utcnow().year
            slip = LoadSlip(
                load_slip_id=new_id(), slip_code=_next_slip_code(db, year, seq_used),
                sheet_type=sheet_type, shift_label=shift_label, order_date=order_date,
                vehicle_plate=v["vehicle_plate"], driver_name=v["driver_name"],
                routes=", ".join(v["routes"]) or None, note=", ".join(v["notes"]) or None,
                source_file_name=filename, recipient_name=v["driver_name"],
                recipient_unit=v["vehicle_plate"], created_by=user.username, created_at=utcnow(),
            )
            db.add(slip)
            db.flush()
            for i, (name, line) in enumerate(v["lines"].items()):
                note = f"Theo QĐ KM {', '.join(sorted(line['qdkm']))}" if line["qdkm"] else None
                db.add(LoadSlipLine(
                    line_id=new_id(), load_slip_id=slip.load_slip_id, seq=i,
                    product_name=name, uom=line["uom"], quantity=round(line["qty"], 3),
                    is_promo=line["is_promo"], note=note,
                ))
            created[sheet_type].append({"load_slip_id": slip.load_slip_id, "slip_code": slip.slip_code,
                                        "vehicle_plate": slip.vehicle_plate, "driver_name": slip.driver_name,
                                        "lines": len(v["lines"])})
    db.commit()
    return created


def list_load_slips(db: Session, sheet_type: Optional[str] = None,
                    limit: int = 1000, offset: int = 0) -> list[dict]:
    """Có phân trang (mặc định 1000, tối đa 5000) — số biên bản tích lũy tăng dần theo mỗi
    lần nhập lệnh đóng hàng. Đếm số dòng theo 1 truy vấn GROUP BY duy nhất thay vì 1 truy vấn
    COUNT riêng cho mỗi biên bản (N+1) như trước."""
    limit = max(1, min(limit or 1000, 5000))
    offset = max(0, offset or 0)
    q = select(LoadSlip).order_by(LoadSlip.created_at.desc()).limit(limit).offset(offset)
    if sheet_type:
        q = q.where(LoadSlip.sheet_type == sheet_type)
    slips = db.execute(q).scalars().all()
    slip_ids = [s.load_slip_id for s in slips]
    line_counts = dict(db.execute(
        select(LoadSlipLine.load_slip_id, func.count())
        .where(LoadSlipLine.load_slip_id.in_(slip_ids))
        .group_by(LoadSlipLine.load_slip_id)).all()) if slip_ids else {}
    out = []
    for s in slips:
        n_lines = line_counts.get(s.load_slip_id, 0)
        out.append({
            "load_slip_id": s.load_slip_id, "slip_code": s.slip_code, "sheet_type": s.sheet_type,
            "shift_label": s.shift_label, "order_date": s.order_date, "vehicle_plate": s.vehicle_plate,
            "driver_name": s.driver_name, "routes": s.routes, "note": s.note,
            "recipient_name": s.recipient_name, "recipient_unit": s.recipient_unit,
            "created_at": s.created_at, "line_count": n_lines,
        })
    return out


def get_load_slip(db: Session, load_slip_id: str) -> dict:
    slip = db.get(LoadSlip, load_slip_id)
    if not slip:
        raise NotFoundError("Biên bản bàn giao hàng hóa không tồn tại.")
    lines = db.execute(select(LoadSlipLine).where(LoadSlipLine.load_slip_id == load_slip_id)
                       .order_by(LoadSlipLine.seq)).scalars().all()
    return {
        "load_slip_id": slip.load_slip_id, "slip_code": slip.slip_code, "sheet_type": slip.sheet_type,
        "shift_label": slip.shift_label, "order_date": slip.order_date, "vehicle_plate": slip.vehicle_plate,
        "driver_name": slip.driver_name, "routes": slip.routes, "note": slip.note,
        "source_file_name": slip.source_file_name,
        "issuer_name": slip.issuer_name, "issuer_title": slip.issuer_title, "issuer_dept": slip.issuer_dept,
        "recipient_name": slip.recipient_name, "recipient_title": slip.recipient_title,
        "recipient_unit": slip.recipient_unit, "created_by": slip.created_by, "created_at": slip.created_at,
        "lines": [{"line_id": l.line_id, "seq": l.seq, "product_name": l.product_name, "uom": l.uom,
                   "quantity": l.quantity, "is_promo": l.is_promo, "note": l.note} for l in lines],
    }


def update_load_slip_header(db: Session, load_slip_id: str, payload: dict) -> dict:
    slip = db.get(LoadSlip, load_slip_id)
    if not slip:
        raise NotFoundError("Biên bản bàn giao hàng hóa không tồn tại.")
    for key in ("issuer_name", "issuer_title", "issuer_dept",
                "recipient_name", "recipient_title", "recipient_unit"):
        if key in payload:
            setattr(slip, key, payload[key])
    db.commit()
    return get_load_slip(db, load_slip_id)


def delete_load_slip(db: Session, load_slip_id: str) -> None:
    slip = db.get(LoadSlip, load_slip_id)
    if not slip:
        raise NotFoundError("Biên bản bàn giao hàng hóa không tồn tại.")
    for l in db.execute(select(LoadSlipLine).where(LoadSlipLine.load_slip_id == load_slip_id)).scalars().all():
        db.delete(l)
    db.delete(slip)
    db.commit()
