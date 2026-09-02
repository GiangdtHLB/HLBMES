"""Cấp phát nguyên liệu cho mẻ: dispense (chọn lô/FEFO) + backflush (§7.4)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import AdjustActualIn, BackflushIn, DispenseIn
from ..security import User, get_current_user, require_perm
from ..services import dispense as svc

router = APIRouter(prefix="/api/dispense", tags=["dispense"])


@router.get("")
def list_dispenses(batch_id: str = None, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    return svc.list_dispenses(db, batch_id)


@router.get("/{batch_id}/summary")
def batch_dispense_summary(batch_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Bảng Định mức↔Thực tế cho màn Cấp liệu — tách theo mã vật tư THẬT đã cấp (mã lô + FIFO
    kèm theo), khác bom.py::compare_batch (gộp theo dòng BOM, có thể là mã Nhóm vật tư thay thế).
    Khai báo TRƯỚC /{batch_id}/suggest để không bị route động bắt nhầm."""
    return svc.batch_dispense_summary(db, batch_id)


@router.get("/{batch_id}/suggest")
def suggest_dispense(batch_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Gợi ý cấp liệu: vật tư nào còn thiếu theo Định mức (BOM), lô nào (FEFO, Kho phân xưởng)
    sẽ được chọn — chỉ tính, không trừ tồn. Xem trước rồi gọi POST /{batch_id} với đúng các dòng
    (material_code/lot_id/quantity) lấy từ đây để áp dụng thật."""
    return svc.suggest_dispense(db, batch_id)


@router.post("/{batch_id}")
def dispense(batch_id: str, payload: DispenseIn, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    """Cấp liệu cho mẻ (trừ tồn lô + genealogy + chặn vượt định mức / lô hết hạn)."""
    require_perm(user, "batch.execute")
    return svc.dispense(db, batch_id, [l.model_dump() for l in payload.lines], user, payload.note)


@router.post("/{batch_id}/backflush")
def backflush(batch_id: str, payload: BackflushIn, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    """Backflush: tự khấu trừ NVL theo định mức BOM × tỉ lệ sản lượng đã sản xuất."""
    require_perm(user, "batch.execute")
    return svc.backflush(db, batch_id, payload.produced_qty, user)


@router.post("/{batch_id}/adjust")
def adjust_actual(batch_id: str, payload: AdjustActualIn, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """Sửa Thực tế 1 vật tư — tự cấp thêm/hoàn lại cho khớp số mới, bắt buộc lý do."""
    require_perm(user, "batch.execute")
    return svc.adjust_actual(db, batch_id, payload.material_code, payload.new_actual, user, payload.reason)
