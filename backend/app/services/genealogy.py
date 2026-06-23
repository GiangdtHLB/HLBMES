"""Đồ thị phả hệ: thêm cạnh và truy ngược/truy xuôi (tài liệu §7.6).

Node = (type, id) với type ∈ {lot, batch}. Truy ngược (backward) trả về tất cả
nguyên liệu/mẻ đã đi vào một node; truy xuôi (forward) trả về tất cả lô/mẻ
sinh ra từ một node. Có chống chu trình để tránh vòng lặp vô hạn.
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..common import new_id, utcnow
from ..models.batches import BatchExecution
from ..models.materials import GenealogyEdge, MaterialLot


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


def _label(db: Session, node_type: str, node_id: str) -> dict:
    """Nhãn người-đọc-được cho một node."""
    if node_type == "batch":
        b = db.get(BatchExecution, node_id)
        code = b.batch_code if b else node_id
    else:
        lot = db.get(MaterialLot, node_id)
        code = lot.lot_code if lot else node_id
    return {"type": node_type, "id": node_id, "code": code}


def _walk(db: Session, node_type: str, node_id: str, direction: str) -> dict:
    """direction='backward' đi theo cạnh tới->từ (cái gì tạo ra node này);
    direction='forward' đi theo cạnh từ->tới (node này sinh ra cái gì)."""
    visited: set[tuple] = set()

    def recurse(ntype: str, nid: str) -> dict:
        node = _label(db, ntype, nid)
        key = (ntype, nid)
        if key in visited:
            node["children"] = []
            node["cycle"] = True
            return node
        visited.add(key)

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


def trace_forward(db: Session, node_type: str, node_id: str) -> dict:
    """Truy xuôi: từ nguyên liệu/mẻ tới các lô thành phẩm — nền tảng recall."""
    return _walk(db, node_type, node_id, "forward")


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
    """Tìm node theo mã (batch_code hoặc lot_code) -> (type, id)."""
    b = db.execute(select(BatchExecution).where(BatchExecution.batch_code == code)).scalar_one_or_none()
    if b:
        return ("batch", b.batch_id)
    lot = db.execute(
        select(MaterialLot).where(MaterialLot.lot_code == code)
    ).scalar_one_or_none()
    if lot:
        return ("lot", lot.lot_id)
    return None
