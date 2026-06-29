"""Truy xuất nguồn gốc + recall simulation (tài liệu §7.6)."""

import time

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import NotFoundError
from ..security import get_current_user
from ..services import genealogy

# Truy xuất/recall lộ toàn bộ genealogy nhà máy → bắt buộc đăng nhập.
router = APIRouter(prefix="/api/trace", tags=["traceability"],
                   dependencies=[Depends(get_current_user)])


def _resolve(db: Session, code: str, node_type: str, node_id: str):
    if code:
        found = genealogy.find_node(db, code)
        if not found:
            raise NotFoundError(f"Không tìm thấy node với mã '{code}'.")
        return found
    if node_type and node_id:
        return (node_type, node_id)
    raise NotFoundError("Cần cung cấp 'code' hoặc cả 'node_type' và 'node_id'.")


@router.get("/backward")
def trace_backward(code: str = Query(default=None), node_type: str = Query(default=None),
                   node_id: str = Query(default=None), db: Session = Depends(get_db)):
    nt, nid = _resolve(db, code, node_type, node_id)
    return genealogy.trace_backward(db, nt, nid)


@router.get("/forward")
def trace_forward(code: str = Query(default=None), node_type: str = Query(default=None),
                  node_id: str = Query(default=None), db: Session = Depends(get_db)):
    nt, nid = _resolve(db, code, node_type, node_id)
    return genealogy.trace_forward(db, nt, nid)


@router.get("/recall")
def recall(code: str = Query(default=None), node_type: str = Query(default=None),
           node_id: str = Query(default=None), db: Session = Depends(get_db)):
    """Recall simulation: trả về danh sách lô bị ảnh hưởng + thời gian xử lý
    (SLO tài liệu §12: < 5 phút; thực tế MVP là mili-giây)."""
    nt, nid = _resolve(db, code, node_type, node_id)
    started = time.perf_counter()
    affected = genealogy.recall_affected(db, nt, nid)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    return {
        "source": {"type": nt, "id": nid},
        "affected_count": len(affected),
        "affected": affected,
        "elapsed_ms": elapsed_ms,
    }
