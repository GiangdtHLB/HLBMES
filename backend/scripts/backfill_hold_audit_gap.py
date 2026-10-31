"""Ghi bổ sung 1 dòng audit "hold" cho các BatchTank/BatchFilterLot ĐANG on_hold nhưng CHƯA TỪNG
có dòng audit action="hold"/"release" nào (phát hiện 2026-10-23: trước khi fix 25d7a157 thực sự
chạy đúng trên production, sync_tank_quality_status/sync_stage_quality_status đổi quality_status
âm thầm, không ghi audit — các bản ghi đã on_hold từ giai đoạn đó mãi mãi không có dòng "hold"
trong "Lịch sử Hold/Release", dù "create" vẫn có).

Dùng record_audit() THẬT (không tự tính hash/seq tay) nên tự động có khoá chống race
(_acquire_db_lock) + seq/hash đúng 100% như ghi audit bình thường — an toàn hơn hẳn chạy SQL tay.

Chỉ bổ sung cho bản ghi: (a) đang on_hold THẬT SỰ ngay lúc chạy script, VÀ (b) chưa từng có dòng
hold/release nào trong audit_log — tính lại danh sách này TƯƠI mỗi lần chạy, không dùng danh
sách cũ chốt sẵn, nên không bị trôi dữ liệu.

Chạy: python scripts/backfill_hold_audit_gap.py [--apply]
  (không có --apply: chỉ liệt kê bản ghi SẼ được bổ sung audit, không ghi DB — mặc định an toàn)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.audit import record_audit
from app.database import SessionLocal
from app.models.audit import AuditLog
from app.models.batch_pipeline import BatchFilterLot, BatchTank
from app.security import User

_SCRIPT_USER = User(username="backfill_script", role="admin")
_REASON = ("Backfill — bản ghi đã on_hold từ trước khi cơ chế ghi audit tự động hold/release "
          "chạy đúng trên production (fix 25d7a157, xác nhận hoạt động từ 2026-10-23); không "
          "xác định được thời điểm/lý do gốc chuyển on_hold.")


def _entity_ids_with_hold_release(db, entity_type: str) -> set:
    rows = db.execute(
        select(AuditLog.entity_id).where(AuditLog.entity_type == entity_type,
                                         AuditLog.action.in_(("hold", "release")))
    ).scalars().all()
    return set(rows)


def main(apply: bool) -> None:
    db = SessionLocal()
    changes = []
    try:
        tank_has_hr = _entity_ids_with_hold_release(db, "batch_tank")
        for t in db.query(BatchTank).filter(BatchTank.quality_status == "on_hold").all():
            if t.tank_id not in tank_has_hr:
                changes.append(("batch_tank", t.tank_id, t.tank_code))

        lot_has_hr = _entity_ids_with_hold_release(db, "batch_filter_lot")
        for fl in db.query(BatchFilterLot).filter(BatchFilterLot.quality_status == "on_hold").all():
            if fl.filter_lot_id not in lot_has_hr:
                changes.append(("batch_filter_lot", fl.filter_lot_id, fl.filter_lot_code))

        print(f"{len(changes)} bản ghi sẽ được bổ sung audit \"hold\":")
        for kind, entity_id, code in changes:
            print(f"  [{kind}] {code} ({entity_id})")

        if apply:
            for kind, entity_id, code in changes:
                record_audit(db, entity_type=kind, entity_id=entity_id, action="hold",
                            actor=_SCRIPT_USER, before={"quality_status": "released"},
                            after={"quality_status": "on_hold"}, reason=_REASON)
            db.commit()
            print(f"Đã ghi {len(changes)} dòng audit \"hold\" vào DB.")
        else:
            db.rollback()
            print("Chưa ghi gì (chạy lại kèm --apply để áp dụng thật).")
    finally:
        db.close()


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
