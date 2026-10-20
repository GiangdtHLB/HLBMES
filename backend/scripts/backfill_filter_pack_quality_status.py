"""Rà lại quality_status cho TOÀN BỘ BatchFilterLot (Lọc) + BatchPackLot (Chiết) đã có trong DB,
tính lại đúng theo chỉ tiêu thật đã khai (qc_catalog.sync_stage_quality_status) — sửa dữ liệu cũ
bị mắc bug 2026-09-23: quality_status mặc định "released" ngay lúc tạo, không bao giờ được cập
nhật lại theo tiến độ khai "Chỉ tiêu Lọc"/"Chỉ tiêu Chiết" thật.

Chạy: python scripts/backfill_filter_pack_quality_status.py [--apply]
  (không có --apply: chỉ liệt kê thay đổi SẼ áp dụng, không ghi DB — mặc định an toàn)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.models.batch_pipeline import BatchFilterLot, BatchPackLot
from app.security import User
from app.services import qc_catalog

_SCRIPT_USER = User(username="backfill_script", role="admin")


def main(apply: bool) -> None:
    db = SessionLocal()
    changes = []
    try:
        for fl in db.query(BatchFilterLot).all():
            before = fl.quality_status
            qc_catalog.sync_stage_quality_status(db, "loc", "batch_filter_lot", fl.filter_lot_id, _SCRIPT_USER)
            if fl.quality_status != before:
                changes.append(("batch_filter_lot", fl.filter_lot_code, before, fl.quality_status))
        for p in db.query(BatchPackLot).all():
            before = p.quality_status
            qc_catalog.sync_stage_quality_status(db, "thanh_pham", "batch_pack_lot", p.pack_lot_id, _SCRIPT_USER)
            if p.quality_status != before:
                changes.append(("batch_pack_lot", p.pack_lot_code, before, p.quality_status))

        print(f"{len(changes)} lô sẽ đổi quality_status:")
        for kind, code, before, after in changes:
            print(f"  [{kind}] {code}: {before} -> {after}")

        if apply:
            db.commit()
            print(f"Đã ghi {len(changes)} thay đổi vào DB.")
        else:
            db.rollback()
            print("Chưa ghi gì (chạy lại kèm --apply để áp dụng thật).")
    finally:
        db.close()


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
