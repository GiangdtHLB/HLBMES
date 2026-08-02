"""Báo cáo trạng thái lô tổng hợp — cho biết 1 mã nấu đang ở trạng thái nào tại cả 4 công
đoạn Nấu/Lên men/Lọc/Chiết trong 1 màn hình, thay vì phải mở từng tab riêng để tự ghép.

Nấu/Lọc/Chiết dùng trạng thái THỰC THI của vận hành (đã bấm "Kết thúc" hay chưa — xem
BrewBatch/FilterRecord/BottleRecord.ended_at, routers/brewing.py::_exec_status), khác với
Lên men vẫn giữ nguyên trạng thái tự động suy ra từ tồn CCT thật (derived.ferment_status).

Mặc định chỉ lấy `days` ngày gần nhất (theo brew_date) — mã nấu càng cũ càng ít giá trị theo
dõi thực thi (đã xong cả 4 công đoạn từ lâu), trong khi số BrewRecord tích lũy vô hạn theo thời
gian vận hành nhà máy; không giới hạn sẽ làm báo cáo chậm dần vô thời hạn. Mọi tra cứu phụ
(mẻ/lô lên men/lọc/chiết) đều gộp thành 1 câu IN (...) cho toàn bộ tập brew đã lọc, thay vì lặp
1 câu truy vấn riêng cho từng brew (N+1)."""

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..common import utcnow
from ..models.brewing import BottleRecord, BrewBatch, BrewRecord, FermentBrewLink, FermentRecord, FilterOrderTank, FilterRecord
from . import derived

NAU_LABEL = {"chua_co_me": "Chưa có mẻ", "dang_thuc_hien": "Đang thực hiện", "hoan_thanh": "Hoàn thành"}
LEN_MEN_LABEL = {"dang_nau": "Đang nấu", "len_men": "Đang lên men", "loc_mot_phan": "Lọc 1 phần", "da_loc_het": "Lọc hết"}
LOC_LABEL = {"chua_loc": "Chưa lọc", "dang_loc": "Đang lọc", "da_ket_thuc": "Đã kết thúc"}
CHIET_LABEL = {"chua_chiet": "Chưa chiết", "dang_chiet": "Đang chiết", "da_ket_thuc": "Đã kết thúc"}


def lo_status_report(db: Session, days: int = 180) -> list[dict]:
    since = utcnow() - timedelta(days=days)
    brews = db.execute(select(BrewRecord).where(BrewRecord.brew_date >= since)
                        .order_by(BrewRecord.brew_date.desc())).scalars().all()
    if not brews:
        return []
    brew_ids = [b.brew_id for b in brews]

    batches_by_brew = defaultdict(list)
    for b in db.execute(select(BrewBatch).where(BrewBatch.brew_id.in_(brew_ids))).scalars().all():
        batches_by_brew[b.brew_id].append(b)

    ferment_ids_by_brew = defaultdict(list)
    for brew_id, ferment_id in db.execute(select(FermentBrewLink.brew_id, FermentBrewLink.ferment_id)
                                           .where(FermentBrewLink.brew_id.in_(brew_ids))).all():
        ferment_ids_by_brew[brew_id].append(ferment_id)
    all_ferment_ids = [fid for ids in ferment_ids_by_brew.values() for fid in ids]
    ferment_by_id = {f.ferment_id: f for f in (db.execute(
        select(FermentRecord).where(FermentRecord.ferment_id.in_(all_ferment_ids))).scalars().all()
        if all_ferment_ids else [])}

    # Tra qua FilterOrderTank (không phải FilterRecord.ferment_id trực tiếp) vì lọc PHỐI
    # có nhiều tank/dòng — FilterRecord.ferment_id khi đó là None.
    filter_order_ids_by_ferment = defaultdict(list)
    if all_ferment_ids:
        for ferment_id, filter_order_id in db.execute(
                select(FilterOrderTank.ferment_id, FilterOrderTank.filter_order_id)
                .where(FilterOrderTank.ferment_id.in_(all_ferment_ids))).all():
            filter_order_ids_by_ferment[ferment_id].append(filter_order_id)
    all_filter_order_ids = list({fo_id for ids in filter_order_ids_by_ferment.values() for fo_id in ids})
    filters_by_order = defaultdict(list)
    for f in (db.execute(select(FilterRecord).where(FilterRecord.filter_order_id.in_(all_filter_order_ids))
                          ).scalars().all() if all_filter_order_ids else []):
        filters_by_order[f.filter_order_id].append(f)

    all_filter_ids = [f.filter_id for fs in filters_by_order.values() for f in fs]
    bottles_by_filter = defaultdict(list)
    for bo in (db.execute(select(BottleRecord).where(BottleRecord.filter_id.in_(all_filter_ids))
                          ).scalars().all() if all_filter_ids else []):
        bottles_by_filter[bo.filter_id].append(bo)

    out = []
    for brew in brews:
        batches = batches_by_brew.get(brew.brew_id, [])
        nau = ("chua_co_me" if not batches else
               "dang_thuc_hien" if any(b.ended_at is None for b in batches) else "hoan_thanh")

        ferment_ids = ferment_ids_by_brew.get(brew.brew_id, [])
        ferments = [ferment_by_id[fid] for fid in ferment_ids if fid in ferment_by_id]
        # 1 mã nấu thường vào đúng 1 tank lên men — lấy đại diện bản ghi đầu tiên nếu có.
        len_men = derived.ferment_status(ferments[0]) if ferments else None

        filter_order_ids = [fo_id for fid in ferment_ids for fo_id in filter_order_ids_by_ferment.get(fid, [])]
        filters = [f for fo_id in filter_order_ids for f in filters_by_order.get(fo_id, [])]
        loc = ("chua_loc" if not filters else
               "dang_loc" if any(f.ended_at is None for f in filters) else "da_ket_thuc")

        bottles = [bo for f in filters for bo in bottles_by_filter.get(f.filter_id, [])]
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
