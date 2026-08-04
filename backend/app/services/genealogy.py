"""Đồ thị phả hệ: thêm cạnh và truy ngược/truy xuôi (tài liệu §7.6).

Node = (type, id). Truy ngược (backward) trả về tất cả nguyên liệu/mẻ đã đi
vào một node; truy xuôi (forward) trả về tất cả lô/mẻ sinh ra từ một node.
Có chống chu trình để tránh vòng lặp vô hạn.

NODE_REGISTRY liệt kê mọi loại node được hỗ trợ: "lot"/"batch" là 2 loại gốc
(lô NVL, mẻ của module Mẻ sản xuất/BatchExecution cũ) — "brew_batch"/"brew"/
"ferment"/"filter"/"bottle"/"finished_goods_unit" là chuỗi công đoạn sản xuất
bia thật (Nấu→Lên men→Lọc→Chiết→Kho TP theo vỉ/keg, xem routers/brewing.py và
services/wms.py nơi add_edge() được gọi tại từng bước) — nhờ đó Truy xuất nhận
được cả mã chiết/mã vỉ-keg thật, không chỉ mã mẻ/lô của module BatchExecution cũ."""

from typing import Optional

from sqlalchemy import and_, case, delete, func, or_, select
from sqlalchemy.orm import Session

from ..common import new_id, utcnow
from ..models.batches import BatchExecution
from ..models.brewing import BottleRecord, BrewBatch, BrewRecord, FermentRecord, FilterRecord
from ..models.master import FinishedProduct, Material
from ..models.materials import GenealogyEdge, MaterialLot, Supplier
from ..models.wms import FinishedGoodsUnit, Shipment
from . import qc_catalog

# Trùng với services/wms.py::_pack_divisor_expr (không import trực tiếp — wms.py đã import
# genealogy, import ngược lại sẽ tạo vòng lặp). Quy đổi quantity (SL nhỏ lưu trên dòng) ra số
# vỉ/keg/lon vật lý: vi chia pack_size (Danh mục Sản phẩm); không có SKU khai báo -> mặc định
# 1 (KHÔNG đoán 24 — xem lý do ở wms.py::_pack_divisor), keg/lon giữ nguyên.
_PACK_DIVISOR_EXPR = case(
    (FinishedGoodsUnit.unit_type == "vi", func.coalesce(func.nullif(FinishedProduct.pack_size, 0), 1)), else_=1)

# node_type -> (Model, tên cột khóa chính, tên cột mã hiển thị) — dùng để LABEL 1 node đã biết
# type+id (an toàn, tra theo khóa chính, xem _label) VÀ để tra cứu theo mã ở find_node (CHỈ
# với các mã thật sự duy nhất — xem FIND_NODE_ORDER bên dưới, KHÔNG dùng nguyên thứ tự dict
# này cho việc tra cứu vì "brew_batch" (số mẻ) không duy nhất toàn hệ thống).
NODE_REGISTRY = {
    "lot": (MaterialLot, "lot_id", "lot_code"),
    "batch": (BatchExecution, "batch_id", "batch_code"),
    "brew_batch": (BrewBatch, "batch_id", "batch_code"),
    "brew": (BrewRecord, "brew_id", "brew_code"),
    "ferment": (FermentRecord, "ferment_id", "lm_code"),
    "filter": (FilterRecord, "filter_id", "filter_code"),
    "bottle": (BottleRecord, "bottle_id", "bottle_code"),
    "finished_goods_unit": (FinishedGoodsUnit, "unit_id", "unit_code"),
    "ship_to": (Supplier, "supplier_id", "code"),  # nơi xuất đến (dùng chung danh mục Nhà cung cấp) — điểm cuối truy xuôi/recall
}

# Thứ tự tra mã DUY NHẤT trong find_node (tier 1) — TOÀN BỘ NODE_REGISTRY trừ "brew_batch":
# BrewBatch.batch_code ("số mẻ", VD "1") chỉ duy nhất TRONG 1 NĂM (unique constraint thật sự
# là (batch_year, batch_code), xem models/brewing.py::BrewBatch), KHÔNG duy nhất toàn hệ
# thống — nếu xếp ngang hàng các mã thật-sự-duy-nhất khác (brew_code, lm_code, filter_code,
# bottle_code... đều unique=True) thì 1 mã ngắn kiểu "1" sẽ ưu tiên khớp nhầm vào 1 mẻ nấu
# "1" của 1 mã nấu KHÁC hoàn toàn không liên quan, thay vì "số lô bia" (BottleRecord.lot_no)
# mà người dùng thật sự định tra (bug thực tế: Truy ngược/Hồ sơ điện tử lô "1" ra rỗng vì
# resolve nhầm sang mẻ nấu "1" mồ côi, trong khi Truy xuôi theo nấu (chọn thẳng brew_id, không
# qua find_node) vẫn đúng) — nên brew_batch bị đẩy xuống ALIAS_LOOKUP (tra SAU CÙNG, sau cả
# bottle/finished_goods_unit) bên dưới.
FIND_NODE_ORDER = [nt for nt in NODE_REGISTRY if nt != "brew_batch"]

# Số cạnh "bottle -> finished_goods_unit" từ đó Truy xuôi/Recall chuyển sang gộp nhóm qua SQL
# thay vì đệ quy từng đơn vị — xem _bottle_forward_groups. Dưới ngưỡng vẫn đệ quy đầy đủ (giữ
# nguyên mã từng vỉ/keg trong cây, cần cho thao tác thủ công/test trên vài đơn vị).
BOTTLE_UNIT_AGGREGATE_THRESHOLD = 200

# Bí danh tra cứu THÊM khi không khớp mã duy nhất ở FIND_NODE_ORDER — theo thứ tự ưu tiên:
# "số lô bia" (BottleRecord.lot_no) và "số lô" trên vỉ/keg (FinishedGoodsUnit.lot_code, kế
# thừa từ lot_no lúc duyệt chiết, xem approve_bottle) là con số NGƯỜI DÙNG THẬT SỰ CẦM TRONG
# TAY (in trên bao bì/phiếu), khác với bottle_code/unit_code (mã nội bộ hệ thống tự sinh) —
# nên phải cho tra được cả 2 chiều; "brew_batch" (số mẻ) xếp SAU CÙNG vì ít đặc hiệu nhất (xem
# lý do ở FIND_NODE_ORDER). Các cột này KHÔNG unique (có thể trùng qua nhiều lần/nhiều năm),
# nên lấy bản ghi MỚI NHẤT khi có nhiều khớp.
ALIAS_LOOKUP = [
    ("bottle", BottleRecord, "bottle_id", "lot_no", "bottle_date"),
    ("finished_goods_unit", FinishedGoodsUnit, "unit_id", "lot_code", "created_at"),
    ("brew_batch", BrewBatch, "batch_id", "batch_code", "created_at"),
]


def add_edge(
    db: Session,
    *,
    from_type: str,
    from_id: str,
    to_type: str,
    to_id: str,
    relation: str,
    quantity: Optional[float] = None,
    uom: Optional[str] = None,
    source_event: Optional[str] = None,
) -> GenealogyEdge:
    edge = GenealogyEdge(
        edge_id=new_id(),
        from_type=from_type,
        from_id=from_id,
        to_type=to_type,
        to_id=to_id,
        relation=relation,
        quantity=quantity,
        uom=uom,
        source_event=source_event,
        event_time=utcnow(),
    )
    db.add(edge)
    return edge


def _trim_qc(stage: str, label: str, status: dict) -> dict:
    return {"stage": stage, "label": label, "can_release": status["can_release"],
            "pending": status["pending"], "recorded_count": len(status["recorded"]),
            "required_count": len(status["required"])}


def _qc_summary(db: Session, node_type: str, node_id: str) -> list:
    """Tóm tắt tình trạng khai báo chỉ tiêu chất lượng tại 1 node — để Truy xuất hiện được
    NGAY chỉ tiêu NVL/từng công đoạn thay vì chỉ có mã, người dùng khỏi phải mở riêng từng
    màn hình Kho NVL/Nấu-Lọc-Chiết để xem. Rỗng nếu node không có bước khai báo chỉ tiêu nào
    (VD "brew"/"pallet" — chỉ tiêu gắn ở "brew_batch"/"bottle" tương ứng, xem quy ước stage
    ở routers/brewing.py::data-stageqc)."""
    if node_type == "lot":
        lot = db.get(MaterialLot, node_id)
        if not lot:
            return []
        st = qc_catalog.lot_qc_status(db, lot)
        return [{"stage": "lot", "label": "NVL", "can_release": st["can_release"],
                 "pending": st["pending"], "recorded_count": len(st["recorded"]),
                 "required_count": len(st["required"])}]
    if node_type == "brew_batch":
        batch = db.get(BrewBatch, node_id)
        if not batch:
            return []
        brew = db.get(BrewRecord, batch.brew_id)
        st = qc_catalog.stage_qc_status(db, "nau", "brew_batch", batch.batch_id,
                                        brew.product_id if brew else None)
        return [_trim_qc("nau", "Nấu", st)]
    if node_type == "ferment":
        f = db.get(FermentRecord, node_id)
        if not f:
            return []
        out = []
        for stage, label in (("len_men_chinh", "Lên men chính"), ("len_men_phu", "Lên men phụ")):
            st = qc_catalog.stage_qc_status(db, stage, "ferment",
                                            qc_catalog.ferment_scope_id(f.lm_code, f.ferment_year, stage),
                                            f.product_id)
            out.append(_trim_qc(stage, label, st))
        return out
    if node_type == "filter":
        f = db.get(FilterRecord, node_id)
        if not f:
            return []
        st = qc_catalog.stage_qc_status(db, "loc", "filter",
                                        qc_catalog.filter_scope_id(f.filter_code, f.filter_year), f.product_id,
                                        finished_product_id=f.finished_product_id, beer_type_id=f.beer_type_id)
        return [_trim_qc("loc", "Lọc", st)]
    if node_type == "bottle":
        b = db.get(BottleRecord, node_id)
        if not b:
            return []
        st = qc_catalog.stage_qc_status(db, "thanh_pham", "bottle",
                                        qc_catalog.bottle_scope_id(b.bottle_code, b.bottle_year),
                                        b.product_id, finished_product_id=b.finished_product_id,
                                        beer_type_id=b.beer_type_id)
        return [_trim_qc("thanh_pham", "Thành phẩm", st)]
    return []


def _period(db: Session, node_type: str, node_id: str) -> Optional[dict]:
    """Mốc bắt đầu/kết thúc hiển thị trên cây truy xuất (dùng lại started_at/ended_at,
    brew_date/kt_date đã có sẵn từ tính năng "Trạng thái lô" — xem routers/brewing.py).
    "brew" (mã nấu) không có started_at/ended_at riêng vì 1 mã nấu có thể gồm nhiều mẻ —
    tính từ các BrewBatch con: bắt đầu = mẻ sớm nhất, kết thúc = mẻ trễ nhất (None nếu còn
    mẻ nào chưa bấm Kết thúc, nghĩa là mã nấu chưa xong hẳn)."""
    if node_type == "brew":
        batches = db.execute(select(BrewBatch).where(BrewBatch.brew_id == node_id)).scalars().all()
        if not batches:
            return None
        starts = [b.started_at for b in batches if b.started_at]
        ends = [b.ended_at for b in batches]
        return {"start": min(starts) if starts else None,
                "end": max(ends) if ends and all(ends) else None}
    if node_type == "ferment":
        f = db.get(FermentRecord, node_id)
        return {"start": f.brew_date, "end": f.kt_date} if f else None
    if node_type == "filter":
        f = db.get(FilterRecord, node_id)
        return {"start": f.filter_date, "end": f.ended_at} if f else None
    if node_type == "bottle":
        b = db.get(BottleRecord, node_id)
        return {"start": b.bottle_date, "end": b.ended_at} if b else None
    if node_type == "finished_goods_unit":
        u = db.get(FinishedGoodsUnit, node_id)
        return {"start": u.created_at, "end": u.shipped_at} if u else None
    return None


def _material_label(db: Session, lot: MaterialLot) -> Optional[str]:
    """Tên/mã vật tư của 1 lô NVL — dùng để hiển thị "mã nguyên vật liệu" thay vì chỉ mã lô
    trần trụi ở bảng gộp trong renderTree (frontend/app.js) — không phải mọi MaterialLot đều
    gắn material_id (lô thành phẩm/bán thành phẩm dùng product_id thay), nên có thể rỗng."""
    if not lot.material_id:
        return None
    mat = db.get(Material, lot.material_id)
    return f"{mat.code} — {mat.name}" if mat else None


def _label(db: Session, node_type: str, node_id: str) -> dict:
    """Nhãn người-đọc-được cho một node, kèm tóm tắt chỉ tiêu chất lượng (nếu có)."""
    entry = NODE_REGISTRY.get(node_type)
    if not entry:
        return {"type": node_type, "id": node_id, "code": node_id, "qc": [], "period": None}
    model, _pk_attr, code_attr = entry
    obj = db.get(model, node_id)
    code = getattr(obj, code_attr) if obj else node_id
    out = {"type": node_type, "id": node_id, "code": code, "qc": _qc_summary(db, node_type, node_id),
           "period": _period(db, node_type, node_id)}
    if node_type == "lot" and obj:
        out["material_label"] = _material_label(db, obj)
    return out


def delete_edges_for(db: Session, node_type: str, node_id: str) -> None:
    """Xóa mọi cạnh phả hệ (2 chiều) gắn với 1 node khi node đó bị xóa hẳn khỏi hệ thống —
    gọi từ các endpoint DELETE (xóa mã nấu/mẻ/lô LM/mã lọc/mã chiết ở routers/brewing.py).
    Không dọn thì cạnh còn trỏ tới id không còn tồn tại — hiện thành node mã ngẫu nhiên vô
    nghĩa mãi mãi ở Truy xuất (không tra được code thật vì bản ghi gốc đã bị xóa)."""
    db.execute(delete(GenealogyEdge).where(or_(
        and_(GenealogyEdge.from_type == node_type, GenealogyEdge.from_id == node_id),
        and_(GenealogyEdge.to_type == node_type, GenealogyEdge.to_id == node_id),
    )))


def _bottle_forward_groups(db: Session, bottle_id: str) -> list[dict]:
    """Con truy xuôi của 1 mã chiết — CHỈ gộp nhóm qua SQL GROUP BY, không đệ quy từng
    FinishedGoodsUnit: 1 mã chiết có thể sinh ra hàng trăm nghìn vỉ/keg riêng lẻ (mỗi vỉ 1
    cạnh GenealogyEdge, xem routers/brewing.py::approve_bottle), nên đệ quy từng cạnh như các
    loại node khác (fan-out vài chục) sẽ treo server nhiều phút/giờ (N+1 query + đệ quy hàng
    trăm nghìn lần). Gộp theo (unit_type, status, shipment_id) — mỗi phiếu xuất/mỗi trạng thái
    tồn ra ĐÚNG 1 dòng, kèm ngay thông tin nơi xuất đến/lái xe/ngày giờ/loại xuất qua JOIN
    Shipment + Supplier (không cần đệ quy thêm 1 tầng vào "ship_to")."""
    # "count" = tổng vỉ/keg/lon quy đổi (SUM(quantity)/pack_size qua _PACK_DIVISOR_EXPR),
    # KHÔNG đếm dòng — 1 dòng giờ có thể đại diện nhiều đơn vị đóng gói đã gộp lại (xem
    # docs/WMS-LOT-LEVEL-REDESIGN.md).
    rows = db.execute(
        select(FinishedGoodsUnit.unit_type, FinishedGoodsUnit.status, FinishedGoodsUnit.shipment_id,
               func.sum(FinishedGoodsUnit.quantity / _PACK_DIVISOR_EXPR), func.sum(FinishedGoodsUnit.quantity),
               FinishedProduct.name, FinishedProduct.code)
        .join(GenealogyEdge, and_(GenealogyEdge.to_type == "finished_goods_unit",
                                  GenealogyEdge.to_id == FinishedGoodsUnit.unit_id))
        .outerjoin(FinishedProduct, FinishedProduct.finished_product_id == FinishedGoodsUnit.finished_product_id)
        .where(GenealogyEdge.from_type == "bottle", GenealogyEdge.from_id == bottle_id)
        .group_by(FinishedGoodsUnit.unit_type, FinishedGoodsUnit.status, FinishedGoodsUnit.shipment_id,
                  FinishedProduct.name, FinishedProduct.code)
    ).all()
    shipment_ids = [r[2] for r in rows if r[2]]
    shipments = {s.shipment_id: s for s in db.execute(
        select(Shipment).where(Shipment.shipment_id.in_(shipment_ids))).scalars().all()} if shipment_ids else {}
    ship_to_by_id = {}
    if shipments:
        ship_to_ids = [s.ship_to_id for s in shipments.values()]
        ship_to_by_id = {s.supplier_id: s for s in db.execute(
            select(Supplier).where(Supplier.supplier_id.in_(ship_to_ids))).scalars().all()}

    def _small_unit_noun(product_text: str | None) -> str:
        # unit_type "lon" là mã hệ thống DÙNG CHUNG cho MỌI đơn vị nhỏ đã phân rã (lon HOẶC
        # chai HOẶC đơn vị lẻ khác), không phải luôn là lon vật lý — suy ra danh từ đúng từ
        # tên/mã sản phẩm, cùng cách views_ext.js::smallUnitNoun làm ở các bảng WMS khác.
        t = (product_text or "").lower()
        if "chai" in t:
            return "chai"
        if "keg" in t:
            return "keg"
        if "lon" in t:
            return "lon"
        return "sl nhỏ"

    status_label = {"stored": "còn tồn kho", "shipped": "đã xuất", "decomposed": "đã phân rã"}
    out = []
    for unit_type, status, shipment_id, count, qty, fp_name, fp_code in rows:
        product_text = f"{fp_code or ''} {fp_name or ''}"
        if unit_type == "lon":
            ut = _small_unit_noun(product_text)
        elif unit_type == "keg":
            ut = "keg"
        else:
            ut = "vỉ"
        shp = shipments.get(shipment_id) if shipment_id else None
        st = ship_to_by_id.get(shp.ship_to_id) if shp else None
        node = {
            "type": "shipment_group" if shp else "stock_group",
            "id": f"{bottle_id}:{unit_type}:{status}:{shipment_id or 'none'}",
            "count": count, "quantity": qty, "unit_type": unit_type, "unit_type_label": ut,
            "unit_status": status, "children": [], "qc": [], "period": None,
        }
        if shp:
            node.update({
                "code": f"{count:g} {ut} → {st.code if st else '?'} ({shp.shipment_code})",
                "shipment_code": shp.shipment_code, "shipment_type": shp.shipment_type,
                "shipped_at": shp.created_at.isoformat() if shp.created_at else None,
                "driver_name": shp.driver_name, "vehicle_plate": shp.vehicle_plate,
                "from_location": shp.from_location,
                "ship_to_code": st.code if st else None, "ship_to_name": st.name if st else None,
            })
        else:
            node["code"] = f"{count:g} {ut} {status_label.get(status, status)}"
        out.append(node)
    return out


def _walk(db: Session, node_type: str, node_id: str, direction: str,
          stop_types: Optional[set] = None) -> dict:
    """direction='backward' đi theo cạnh tới->từ (cái gì tạo ra node này);
    direction='forward' đi theo cạnh từ->tới (node này sinh ra cái gì). stop_types: các loại
    node vẫn hiện trong cây nhưng KHÔNG đi tiếp xuống con của nó — dùng cho "Truy xuôi theo
    nấu" (dừng ở "bottle"/chiết, không đi tiếp ra pallet/xuất kho, xem services/lot_record.py
    ::build_brew_forward_record)."""
    visited: set[tuple] = set()
    stop_types = stop_types or set()

    def recurse(ntype: str, nid: str) -> dict:
        node = _label(db, ntype, nid)
        key = (ntype, nid)
        if key in visited:
            node["children"] = []
            node["cycle"] = True
            return node
        visited.add(key)
        if ntype in stop_types:
            node["children"] = []
            return node

        if direction == "forward" and ntype == "bottle":
            # Dưới ngưỡng: đệ quy đầy đủ như mọi loại node khác (giữ nguyên mã từng vỉ/keg —
            # cần thiết khi thao tác thủ công trên vài đơn vị). Trên ngưỡng: 1 mã chiết có thể
            # sinh hàng trăm nghìn vỉ/keg (approve_bottle tạo 1 cạnh/đơn vị) — đệ quy từng cạnh
            # sẽ treo server hàng phút/giờ, nên gộp qua SQL GROUP BY (xem _bottle_forward_groups).
            edge_count = db.execute(select(func.count(GenealogyEdge.edge_id)).where(
                GenealogyEdge.from_type == "bottle", GenealogyEdge.from_id == nid)).scalar() or 0
            if edge_count > BOTTLE_UNIT_AGGREGATE_THRESHOLD:
                node["children"] = _bottle_forward_groups(db, nid)
                return node

        if direction == "backward":
            edges = db.execute(
                select(GenealogyEdge).where(
                    GenealogyEdge.to_type == ntype, GenealogyEdge.to_id == nid
                )
            ).scalars().all()
            nexts = [(e.from_type, e.from_id, e) for e in edges]
        else:
            edges = db.execute(
                select(GenealogyEdge).where(
                    GenealogyEdge.from_type == ntype, GenealogyEdge.from_id == nid
                )
            ).scalars().all()
            nexts = [(e.to_type, e.to_id, e) for e in edges]

        children = []
        for nt, ni, e in nexts:
            child = recurse(nt, ni)
            child["relation"] = e.relation
            child["quantity"] = e.quantity
            child["uom"] = e.uom
            children.append(child)
        node["children"] = children
        return node

    return recurse(node_type, node_id)


def trace_backward(db: Session, node_type: str, node_id: str) -> dict:
    """Truy ngược: từ thành phẩm về nguyên liệu gốc."""
    return _walk(db, node_type, node_id, "backward")


def trace_forward(db: Session, node_type: str, node_id: str, stop_types: Optional[set] = None) -> dict:
    """Truy xuôi: từ nguyên liệu/mẻ tới các lô thành phẩm — nền tảng recall."""
    return _walk(db, node_type, node_id, "forward", stop_types)


def recall_affected(db: Session, node_type: str, node_id: str) -> list[dict]:
    """Phẳng hoá cây truy xuôi thành danh sách lô bị ảnh hưởng (recall simulation)."""
    tree = trace_forward(db, node_type, node_id)
    out: list[dict] = []
    seen: set[tuple] = set()

    def collect(n: dict) -> None:
        key = (n["type"], n["id"])
        if key not in seen:
            seen.add(key)
            if key != (node_type, node_id):
                out.append({"type": n["type"], "id": n["id"], "code": n["code"]})
        for c in n.get("children", []):
            collect(c)

    collect(tree)
    return out


def find_node(db: Session, code: str) -> Optional[tuple]:
    """Tìm node theo mã — thử lần lượt từng loại trong FIND_NODE_ORDER (mã nội bộ, duy nhất
    toàn hệ thống) trước, rồi mới thử ALIAS_LOOKUP (số lô người dùng thật sự cầm trong tay/số
    mẻ, có thể trùng — lấy bản ghi mới nhất) -> (type, id)."""
    for node_type in FIND_NODE_ORDER:
        model, pk_attr, code_attr = NODE_REGISTRY[node_type]
        obj = db.execute(select(model).where(getattr(model, code_attr) == code)).scalar_one_or_none()
        if obj:
            return (node_type, getattr(obj, pk_attr))
    for node_type, model, pk_attr, code_attr, order_attr in ALIAS_LOOKUP:
        obj = db.execute(
            select(model).where(getattr(model, code_attr) == code)
            .order_by(getattr(model, order_attr).desc())
        ).scalars().first()
        if obj:
            return (node_type, getattr(obj, pk_attr))
    return None
