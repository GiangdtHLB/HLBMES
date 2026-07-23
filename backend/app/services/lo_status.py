"""Báo cáo trạng thái lô tổng hợp — cho biết 1 mã nấu đang ở trạng thái nào tại cả 4 công
đoạn Nấu/Lên men/Lọc/Chiết trong 1 màn hình, thay vì phải mở từng tab riêng để tự ghép.

Nấu/Lọc/Chiết dùng trạng thái THỰC THI của vận hành (đã bấm "Kết thúc" hay chưa — xem
BrewBatch/FilterRecord/BottleRecord.ended_at, routers/brewing.py::_exec_status), khác với
Lên men vẫn giữ nguyên trạng thái tự động suy ra từ tồn CCT thật (derived.ferment_status)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.brewing import BottleRecord, BrewBatch, BrewRecord, FermentBrewLink, FermentRecord, FilterOrderTank, FilterRecord
from . import derived

NAU_LABEL = {"chua_co_me": "Chưa có mẻ", "dang_thuc_hien": "Đang thực hiện", "hoan_thanh": "Hoàn thành"}
LEN_MEN_LABEL = {"len_men": "Đang lên men", "loc_mot_phan": "Lọc 1 phần", "da_loc_het": "Lọc hết"}
LOC_LABEL = {"chua_loc": "Chưa lọc", "dang_loc": "Đang lọc", "da_ket_thuc": "Đã kết thúc"}
CHIET_LABEL = {"chua_chiet": "Chưa chiết", "dang_chiet": "Đang chiết", "da_ket_thuc": "Đã kết thúc"}


def lo_status_report(db: Session) -> list[dict]:
    brews = db.execute(select(BrewRecord).order_by(BrewRecord.brew_date.desc())).scalars().all()
    out = []
    for brew in brews:
        batches = db.execute(select(BrewBatch).where(BrewBatch.brew_id == brew.brew_id)).scalars().all()
        nau = ("chua_co_me" if not batches else
               "dang_thuc_hien" if any(b.ended_at is None for b in batches) else "hoan_thanh")

        ferment_ids = [r[0] for r in db.execute(select(FermentBrewLink.ferment_id)
                       .where(FermentBrewLink.brew_id == brew.brew_id)).all()]
        ferments = db.execute(select(FermentRecord).where(FermentRecord.ferment_id.in_(ferment_ids))
                              ).scalars().all() if ferment_ids else []
        # 1 mã nấu thường vào đúng 1 tank lên men — lấy đại diện bản ghi đầu tiên nếu có.
        len_men = derived.ferment_status(ferments[0]) if ferments else None

        # Tra qua FilterOrderTank (không phải FilterRecord.ferment_id trực tiếp) vì lọc PHỐI
        # có nhiều tank/dòng — FilterRecord.ferment_id khi đó là None.
        filter_order_ids = [r[0] for r in db.execute(select(FilterOrderTank.filter_order_id)
                            .where(FilterOrderTank.ferment_id.in_(ferment_ids))).all()] if ferment_ids else []
        filters = db.execute(select(FilterRecord).where(FilterRecord.filter_order_id.in_(filter_order_ids))
                             ).scalars().all() if filter_order_ids else []
        loc = ("chua_loc" if not filters else
               "dang_loc" if any(f.ended_at is None for f in filters) else "da_ket_thuc")

        filter_ids = [f.filter_id for f in filters]
        bottles = db.execute(select(BottleRecord).where(BottleRecord.filter_id.in_(filter_ids))
                             ).scalars().all() if filter_ids else []
        chiet = ("chua_chiet" if not bottles else
                 "dang_chiet" if any(bo.ended_at is None for bo in bottles) else "da_ket_thuc")

        out.append({
            "brew_id": brew.brew_id, "brew_code": brew.brew_code, "brew_date": brew.brew_date,
            "wort_type": brew.wort_type,
            "nau": nau, "nau_label": NAU_LABEL[nau],
            "len_men": len_men, "len_men_label": LEN_MEN_LABEL.get(len_men, "Chưa lên men"),
            "loc": loc, "loc_label": LOC_LABEL[loc],
            "chiet": chiet, "chiet_label": CHIET_LABEL[chiet],
        })
    return out
