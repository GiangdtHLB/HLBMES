"""Pipeline thực thi MỚI cho "Mẻ sản xuất" (BatchExecution) theo blueprint 4 lớp: mẻ nấu →
tank lên men (BatchTank) → lô lọc (BatchFilterLot) → lô thành phẩm (BatchPackLot).

Mirror đúng pattern đã chứng minh hoạt động ở module Nấu-Lọc-Chiết cũ (on_hand giảm theo
DELTA — xem routers/brewing.py::finish_filter_tank/finish_bottle; genealogy edge tạo lúc gộp/
rút dịch — xem add_ferment/add_filter) nhưng độc lập hoàn toàn, KHÔNG đụng module cũ.

Chỉ tiêu chất lượng tái dùng đúng stage cũ ("len_men_chinh"/"loc"/"thanh_pham") qua scope_type
mới ("batch_tank"/"batch_filter_lot"/"batch_pack_lot") — xem services/qc_catalog.py::stage_qc_status.
"""

import re
from datetime import timedelta
from typing import Optional

from sqlalchemy import select, true
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import new_id, utcnow
from ..errors import DomainError, NotFoundError
from ..models.batch_pipeline import (
    BatchFilterLot,
    BatchFilterLotBatch,
    BatchFilterLotBatchDraw,
    BatchFilterLotMaterialUsage,
    BatchFilterLotSource,
    BatchFilterOrder,
    BatchFilterOrderSource,
    BatchPackLot,
    BatchPackLotMaterialUsage,
    BatchTank,
    BatchTankDailyReading,
    BatchTankLink,
    BatchTankProcessLog,
)
from ..models.batches import BatchExecution
from ..models.lines import ProductionLine
from ..models.master import BeerType, FinishedProduct, Material, Product
from ..models.materials import MaterialLot
from ..models.quality import Deviation, QualityResult
from ..models.signature import Signature
from ..models.workorder import WorkOrder
from ..security import User, require_perm
from . import genealogy, ops_setting, qc_catalog, quality
from . import warehouse as warehouse_svc
from . import wms as wms_svc

L_PER_HL = 100.0   # 1 hectolít = 100 lít — quy đổi Số lượng cấp chiết (lít) <-> on_hand lô lọc (hl)

# Trạng thái hiển thị (yêu cầu người dùng 2026-09-01) — mirror đúng mã/nhãn đã dùng ở module
# Nấu-Lọc-Chiết cũ (routers/brewing.py::FILTER_STATUS, services/derived.py::ferment_status) cho
# nhất quán, dù 2 hệ không liên kết. BatchTank suy hoàn toàn từ dữ liệu (không lưu cột status —
# xem _tank_status); BatchFilterLot lưu cột status thật vì "cho_chiet" cần 1 mốc XÁC NHẬN của
# vận hành ("Hoàn thành lọc") không suy được từ on_hand/ended_at; BatchFilterOrder suy hoàn toàn
# từ lot_count/is_complete (xem _filter_order_status).
TANK_STATUS_LABEL = {"dang_nau": "Đang điền dịch", "len_men": "Đang lên men", "cho_loc": "Chờ lọc",
                     "loc_1_phan": "Lọc 1 phần", "da_loc_het": "Lọc hết", "am": "⚠ Âm (lệch số liệu)"}
FILTER_LOT_STATUS_LABEL = {"dang_loc": "Đang lọc", "cho_chiet": "Chờ chiết", "chiet_1_phan": "Đang chiết",
                           "da_chiet_het": "Đã chiết hết", "am": "⚠ Âm (lệch số liệu)"}
FILTER_ORDER_STATUS_LABEL = {"planned": "Lập kế hoạch", "dang_loc": "Đang lọc", "hoan_thanh": "Hoàn thành"}


def _stamp_filter_lot_label(fl: BatchFilterLot) -> BatchFilterLot:
    """BatchFilterLot trả thẳng ORM object qua response_model=BatchFilterLotOut (không qua dict
    "_out" như BatchTank/BatchFilterOrder) — gắn status_label làm thuộc tính TẠM trên instance
    (không phải cột DB) để Pydantic (from_attributes) đọc được, mirror routers/brewing.py::FILTER_STATUS
    nhưng tính ngay ở đây cho gọn."""
    fl.status_label = FILTER_LOT_STATUS_LABEL.get(fl.status, fl.status)
    return fl


def _sync_filter_lot_chiet_status(fl: BatchFilterLot) -> None:
    """Gọi sau MỌI lần đổi fl.on_hand do lô thành phẩm (tạo/sửa SL/xóa) — chuyển
    cho_chiet<->chiet_1_phan<->da_chiet_het theo on_hand còn lại (yêu cầu người dùng
    2026-09-01). Nếu lô lọc chưa từng bấm "Hoàn thành lọc" (còn "dang_loc") mà đã có mẻ chiết
    rồi (VD do thao tác cũ/test không qua bước đó) thì coi như đã bỏ qua bước đó, tự chuyển
    thẳng sang chiet_1_phan/da_chiet_het luôn — KHÔNG chặn, chỉ "cho_chiet" (chưa chiết gì) mới
    cần đã rời khỏi dang_loc trước.

    "am" (tồn ÂM — đồng hồ đo lúc lọc/chiết ra số vượt tồn phần mềm đang có, yêu cầu người dùng
    2026-09-02: chọn cho phép ghi nhận thay vì chặn cứng, nhưng phải cảnh báo RÕ, khác hẳn
    "da_chiet_het" — 2 trạng thái ý nghĩa vật lý ngược nhau dù cùng "không còn gì để chiết tiếp")
    — chỉ zero được qua empty_filter_lot (trong ngưỡng dung sai); available_bbt_lines coi tank
    BBT còn "am" là VẪN CHIẾM DỤNG, không cho mẻ lọc mới nào khác dùng lại tank đó tới khi = 0."""
    if fl.on_hand < -1e-6:
        fl.status = "am"
    elif fl.volume_hl <= 1e-6:
        # Chưa từng có mẻ lọc nào "Kết thúc" (volume_hl vẫn = 0, chưa rút được hl nào) — LUÔN
        # "dang_loc" bất kể status cột DB đang lưu gì (kể cả đã lỡ bị lệch từ trước, VD do bug
        # cũ ở nhánh da_chiet_het thiếu điều kiện volume_hl > 0 — yêu cầu người dùng 2026-09-02:
        # "tôi vừa mới tạo lô lọc 03 mà tự nhiên lại hiện đã chiết hết"). Nhánh "cho_chiet" bên
        # dưới chỉ áp dụng cho lô ĐÃ có volume_hl thật.
        fl.status = "dang_loc"
    elif fl.on_hand <= 1e-6:
        fl.status = "da_chiet_het"
    elif fl.on_hand < fl.volume_hl - 1e-6:
        fl.status = "chiet_1_phan"
    elif fl.status != "dang_loc":
        fl.status = "cho_chiet"


def _assert_unlocked(*objs) -> None:
    for o in objs:
        if o is not None and getattr(o, "locked", False):
            raise DomainError("Bản ghi đã bị khóa — không thể sửa.")


# ==================== BatchTank (tank lên men) ====================

def list_tanks(db: Session) -> list[BatchTank]:
    return db.execute(select(BatchTank).order_by(BatchTank.created_at.desc())).scalars().all()


def get_tank(db: Session, tank_id: str) -> BatchTank:
    t = db.get(BatchTank, tank_id)
    if not t:
        raise NotFoundError("Tank lên men không tồn tại.")
    return t


def tank_batch_ids(db: Session, tank_id: str) -> list[str]:
    return [l.batch_id for l in db.execute(
        select(BatchTankLink).where(BatchTankLink.tank_id == tank_id)).scalars().all()]


def _tank_status(db: Session, tank: BatchTank) -> str:
    """Suy hoàn toàn từ dữ liệu (không lưu cột status riêng) — mirror derived.py::ferment_status
    (module cũ), thêm "cho_loc" (KHÔNG có ở module cũ) khi đã có Lệnh lọc khai báo tank này làm
    nguồn nhưng CHƯA rút dịch gì (yêu cầu người dùng 2026-09-01: tách rõ "còn đang lên men, chưa
    ai đụng tới" khỏi "đã lên kế hoạch lọc, sắp rút").

    "am" (tồn ÂM — đồng hồ đo lúc lọc ra số vượt tồn phần mềm đang có; yêu cầu người dùng
    2026-09-02: cho phép ghi nhận thay vì chặn cứng lúc nhập, nhưng phải cảnh báo RÕ RÀNG, khác
    hẳn "da_loc_het" — 2 trạng thái ý nghĩa vật lý ngược nhau dù cùng "không rút thêm được nữa")
    — chỉ zero được qua empty_tank (trong ngưỡng dung sai); available_tank_lines coi tank còn
    "am" là VẪN CHIẾM DỤNG, không cho mẻ nấu mới nào khác gộp vào tank đó tới khi = 0.

    "dang_nau" (yêu cầu người dùng 2026-09-02: "chưa kết thúc các mẻ nấu thì chưa được gọi là lên
    men... khi có dịch tồn ở tank lên men mà chưa kết thúc tất cả các mẻ sản xuất thì là đang
    nấu") — merge_batches_into_tank cho gộp mẻ ở BẤT KỲ trạng thái nào (kể cả "planned"/chưa nấu
    xong, xem docstring hàm đó), nên 1 tank có thể đã tồn tại (có thể đã có dịch tồn từ CÁC mẻ đã
    xong khác cùng gộp) trong khi VẪN còn ít nhất 1 mẻ chưa "Kết thúc" (chưa có end_at) — tank đó
    CHƯA thật sự "đang lên men", vẫn đang trong giai đoạn nấu. Chỉ khi TẤT CẢ mẻ đã gộp đều xong
    (có ngày bắt đầu/kết thúc — xem _tank_out::vao_dich_start/vao_dich_end) mới xét tiếp các
    nhánh lên men/lọc bên dưới."""
    if tank.on_hand < -1e-6:
        return "am"
    batch_ids = tank_batch_ids(db, tank.tank_id)
    if batch_ids and db.execute(select(BatchExecution.batch_id).where(
            BatchExecution.batch_id.in_(batch_ids), BatchExecution.end_at.is_(None))).first():
        return "dang_nau"
    if tank.volume_hl > 1e-6 and tank.on_hand <= 1e-6:
        return "da_loc_het"
    if tank.on_hand < tank.volume_hl - 1e-6:
        return "loc_1_phan"
    has_order = db.execute(select(BatchFilterOrderSource.link_id).where(
        BatchFilterOrderSource.source_type == "tank", BatchFilterOrderSource.source_tank_id == tank.tank_id
    )).first() is not None
    return "cho_loc" if has_order else "len_men"


def _tank_out(db: Session, tank: BatchTank) -> dict:
    """Bổ sung mốc "vào dịch"/thời gian lên men suy từ các mẻ nấu đã gộp — mirror công thức
    inline ở routers/brewing.py::list_ferments (module Nấu-Lọc-Chiết cũ):
    - vao_dich_start = mẻ nấu SỚM NHẤT bắt đầu (mirror brew_date).
    - vao_dich_end = mẻ nấu CUỐI CÙNG kết thúc (mirror kt_date) — CHỈ có giá trị khi TẤT CẢ mẻ
      đã gộp đều đã "Kết thúc" (end_at), vì tank chưa thật sự "vào dịch xong" khi còn mẻ đang nấu.
    - ferment_days_std đọc từ Product (không phải BeerType — xem models/master.py:59).
    - ferment_start = vao_dich_end hoặc vao_dich_start (ước tính khi tank chưa vào dịch xong)."""
    batches = db.execute(
        select(BatchExecution).join(BatchTankLink, BatchTankLink.batch_id == BatchExecution.batch_id)
        .where(BatchTankLink.tank_id == tank.tank_id)).scalars().all()
    starts = [b.start_at for b in batches if b.start_at]
    ends = [b.end_at for b in batches if b.end_at]
    vao_dich_start = min(starts) if starts else None
    vao_dich_end = max(ends) if (batches and len(ends) == len(batches)) else None
    product = db.get(Product, tank.product_id) if tank.product_id else None
    beer_type = db.get(BeerType, product.beer_type_id) if product and product.beer_type_id else None
    ferment_days_std = product.ferment_days_std if product else None
    ferment_start = vao_dich_end or vao_dich_start
    days_elapsed = (utcnow() - ferment_start).days if ferment_start else None
    ready_date = (ferment_start + timedelta(days=ferment_days_std)) if ferment_start and ferment_days_std else None
    status = _tank_status(db, tank)
    # Số chỉ tiêu CT chính + CT phụ đang FAIL (giá trị MỚI NHẤT/chỉ tiêu) — mirror
    # routers/brewing.py::list_ferments (module cũ), dùng cho badge cảnh báo ở biểu đồ Dashboard
    # "Tank đang lên men theo số ngày/theo giai đoạn" (yêu cầu người dùng 2026-09-02: đổi nguồn
    # 2 biểu đồ đó sang BatchTank).
    chinh_scope_id = qc_catalog.batch_tank_scope_id(tank.tank_id, "len_men_chinh")
    phu_scope_id = qc_catalog.batch_tank_scope_id(tank.tank_id, "len_men_phu")
    qc_fail_count = sum(
        1 for res in quality.latest_results_by_param(db, "batch_tank", chinh_scope_id).values() if res.status == "fail"
    ) + sum(
        1 for res in quality.latest_results_by_param(db, "batch_tank", phu_scope_id).values() if res.status == "fail"
    )
    return {
        "tank_id": tank.tank_id, "tank_code": tank.tank_code, "tank_year": tank.tank_year,
        "tank_lm": tank.tank_lm, "product_id": tank.product_id, "volume_hl": tank.volume_hl,
        "on_hand": tank.on_hand, "status": status, "status_label": TANK_STATUS_LABEL[status], "note": tank.note,
        "created_by": tank.created_by, "created_at": tank.created_at,
        "locked": tank.locked, "locked_by": tank.locked_by, "locked_at": tank.locked_at,
        "quality_status": tank.quality_status,
        "vao_dich_start": vao_dich_start, "vao_dich_end": vao_dich_end,
        "ferment_days_std": ferment_days_std, "days_elapsed": days_elapsed, "ready_date": ready_date,
        "product_code": product.code if product else None, "beer_type_name": beer_type.name if beer_type else None,
        "qc_fail_count": qc_fail_count,
    }


def list_tanks_out(db: Session) -> list[dict]:
    return [_tank_out(db, t) for t in list_tanks(db)]


def get_tank_out(db: Session, tank_id: str) -> dict:
    return _tank_out(db, get_tank(db, tank_id))


def _tank_lm_occupied(db: Session, tank_lm: str) -> bool:
    """1 tank vật lý (tank_lm) coi là đang chiếm dụng nếu có BẤT KỲ BatchTank nào đang dùng nó
    mà HOẶC còn tồn dịch thật (on_hand != 0, kể cả tồn ÂM) HOẶC còn mẻ nấu đã gộp CHƯA "Kết
    thúc" (chưa có end_at — tank đang "dang_nau"/"đang điền dịch", xem _tank_status). Trước đây
    CHỈ xét on_hand != 0 — bỏ sót đúng lúc "đang điền dịch": mẻ vừa gộp vào tank nhưng CHƯA mẻ
    nào ghi actual_qty (on_hand vẫn = 0, xem merge_batches_into_tank), nên tank vật lý đó vẫn bị
    coi là "trống" và cho chọn lại cho 1 lô lên men KHÁC trong khi lô cũ chưa xong (yêu cầu
    người dùng 2026-09-03: "Tank lên men đang điền dịch thì không cho tạo thêm nữa")."""
    tanks = db.execute(select(BatchTank).where(BatchTank.tank_lm == tank_lm)).scalars().all()
    if not tanks:
        return False
    if any(abs(t.on_hand) > 1e-6 for t in tanks):
        return True
    tank_ids = [t.tank_id for t in tanks]
    return db.execute(select(BatchTankLink.tank_id).join(
        BatchExecution, BatchExecution.batch_id == BatchTankLink.batch_id
    ).where(BatchTankLink.tank_id.in_(tank_ids), BatchExecution.end_at.is_(None))).first() is not None


def available_tank_lines(db: Session) -> list[dict]:
    """Từng tank lên men trong Danh mục (ProductionLine.kind == "tank") kèm cờ đang chiếm dụng
    hay không — mirror services/dashboard.py::available_ferment_tanks (module Nấu-Lọc-Chiết cũ).
    Chiếm dụng = _tank_lm_occupied (còn tồn dịch HOẶC còn mẻ nấu chưa kết thúc)."""
    lines = db.execute(select(ProductionLine).where(
        ProductionLine.kind == "tank", ProductionLine.active == true())).scalars().all()
    return [{"code": l.code, "name": l.name, "occupied": _tank_lm_occupied(db, l.code)}
            for l in sorted(lines, key=lambda x: x.code)]


def empty_tank(db: Session, tank_id: str, user: User) -> dict:
    """Buộc tồn tank về 0 khi tank vật lý đã cạn thật nhưng số liệu phần mềm còn lệch một
    khoảng nhỏ — mirror routers/brewing.py::empty_ferment_cct, dùng chung ngưỡng cấu hình
    empty_cct_tolerance_hl (cùng ý nghĩa vật lý — tank lên men). KHÔNG chặn dù hồ sơ EBR đã
    khóa (CỐ Ý không gọi _assert_unlocked — yêu cầu người dùng 2026-09-01: sai số đo lường lúc
    lọc/chiết là chuyện thường tình, tồn không bao giờ về đúng 0.0 tuyệt đối — phải sửa được
    trong ngưỡng dung sai kể cả sau khi đã khóa hồ sơ, khác mọi sửa đổi thực chất khác). Xử lý
    CẢ tồn ÂM (đồng hồ đo ra số vượt tồn phần mềm — yêu cầu người dùng 2026-09-02: cho phép ghi
    nhận tồn âm thay vì chặn cứng lúc nhập, nhưng bắt buộc đưa về đúng 0 qua đây trước khi tank
    dùng lại được cho mẻ nấu mới, xem available_tank_lines) — so |residual| với ngưỡng, không
    chỉ riêng residual dương."""
    require_perm(user, "batch.execute")
    tank = get_tank(db, tank_id)
    residual = tank.on_hand or 0.0
    if abs(residual) <= 1e-6:
        raise DomainError("Tank đã hết tồn — không cần làm rỗng.")
    settings = ops_setting.get_settings(db)
    if abs(residual) > settings.empty_cct_tolerance_hl:
        raise DomainError(
            f"Tồn còn {residual:g} hl, vượt ngưỡng cho phép làm rỗng ({settings.empty_cct_tolerance_hl:g} hl) "
            "— kiểm tra lại số liệu rút dịch trước khi làm rỗng, hoặc chỉnh ngưỡng ở Danh mục nếu chắc chắn đúng.")
    record_audit(db, entity_type="batch_tank", entity_id=tank.tank_id, action="empty", actor=user,
                before={"on_hand": residual}, after={"on_hand": 0.0})
    tank.on_hand = 0.0
    db.commit()
    db.refresh(tank)
    return _tank_out(db, tank)


def empty_filter_lot(db: Session, filter_lot_id: str, user: User) -> dict:
    """Buộc tồn lô lọc (= dịch còn lại trong tank BBT vật lý, chưa chiết hết) về 0 khi tank đã
    chiết cạn thật nhưng số liệu phần mềm còn lệch một khoảng nhỏ — mirror empty_tank (tank lên
    men), dùng ngưỡng riêng empty_bbt_tolerance_hl. Đặt nút ở màn "Lô thành phẩm" (thao tác lúc
    kết thúc chiết) nhưng sửa trên chính BatchFilterLot nguồn — pack lot không tự có tồn riêng.
    KHÔNG chặn dù hồ sơ EBR đã khóa (CỐ Ý không gọi _assert_unlocked, cùng lý do như empty_tank
    — yêu cầu người dùng 2026-09-01). Xử lý CẢ tồn ÂM giống empty_tank (yêu cầu người dùng
    2026-09-02) — so |residual| với ngưỡng, bắt buộc đưa về đúng 0 qua đây trước khi tank BBT
    dùng lại được cho lô lọc mới (xem available_bbt_lines)."""
    require_perm(user, "batch.execute")
    fl = get_filter_lot(db, filter_lot_id)
    residual = fl.on_hand or 0.0
    if abs(residual) <= 1e-6:
        raise DomainError("Tank BBT đã hết tồn — không cần làm rỗng.")
    settings = ops_setting.get_settings(db)
    if abs(residual) > settings.empty_bbt_tolerance_hl:
        raise DomainError(
            f"Tồn còn {residual:g} hl, vượt ngưỡng cho phép làm rỗng ({settings.empty_bbt_tolerance_hl:g} hl) "
            "— kiểm tra lại số liệu chiết trước khi làm rỗng, hoặc chỉnh ngưỡng ở Danh mục nếu chắc chắn đúng.")
    record_audit(db, entity_type="batch_filter_lot", entity_id=fl.filter_lot_id, action="empty", actor=user,
                before={"on_hand": residual}, after={"on_hand": 0.0})
    fl.on_hand = 0.0
    _sync_filter_lot_chiet_status(fl)
    db.commit()
    db.refresh(fl)
    return _stamp_filter_lot_label(fl)


def usable_capacity_for_code(db: Session, code: Optional[str], kind: str) -> Optional[float]:
    """Thể tích khả dụng (Danh mục "Tank lên men"/"Tank thành phẩm", ProductionLine.volume *
    usable_pct/100) của 1 tank vật lý theo mã — None nếu không gán tank vật lý, hoặc tank đó
    chưa khai đủ Thể tích/% khả dụng (không giới hạn dung tích trong trường hợp đó). Dùng để
    chặn tổng thể tích chứa ở tank lên men/tank thành phẩm vượt quá thể tích khả dụng trong lúc
    nấu/lọc (yêu cầu người dùng 2026-09-01)."""
    if not code:
        return None
    line = db.execute(select(ProductionLine).where(
        ProductionLine.code == code, ProductionLine.kind == kind)).scalar_one_or_none()
    if not line or line.volume is None or line.usable_pct is None:
        return None
    return line.volume * line.usable_pct / 100


def _assert_within_capacity(volume: float, cap: Optional[float], code: str, label: str) -> None:
    if cap is not None and volume > cap + 1e-6:
        raise DomainError(
            f"Tổng thể tích ở {label} '{code}' ({volume:g} hl) vượt quá thể tích khả dụng "
            f"({cap:g} hl) — kiểm tra lại % khả dụng ở Danh mục hoặc số liệu vừa nhập.")


def _auto_tank_code(db: Session, batches: list, tank_year: int) -> Optional[str]:
    """Mã lô lên men tự sinh khi không nhập tay — lấy theo số thứ tự của Lệnh SX (điều độ) mà
    các mẻ đang gộp cùng thuộc về (bỏ tiền tố "WO-"), KHÔNG cần mã riêng cho lô (yêu cầu người
    dùng 2026-09-01: lô lên men coi là 1 thể thống nhất với điều độ sinh ra nó). Trả None nếu các
    mẻ không cùng 1 Lệnh SX (hoặc không mẻ nào gắn Lệnh SX) — bắt người dùng tự nhập mã trong
    trường hợp mơ hồ đó."""
    wo_ids = {b.work_order_id for b in batches if b.work_order_id}
    if len(wo_ids) != 1:
        return None
    wo = db.get(WorkOrder, next(iter(wo_ids)))
    if not wo:
        return None
    m = re.fullmatch(r"WO-(\d+)", wo.wo_code or "")
    base = m.group(1) if m else wo.wo_code
    code, n = base, 1
    while db.execute(select(BatchTank).where(BatchTank.tank_code == code,
                     BatchTank.tank_year == tank_year)).scalar_one_or_none():
        n += 1
        code = f"{base}-{n}"
    return code


def merge_batches_into_tank(db: Session, batch_ids: list[str], payload: dict, user: User) -> dict:
    """Gộp N mẻ nấu (BatchExecution) vào 1 tank mới — mirror add_ferment (brew_ids).

    Cho gộp mẻ ở BẤT KỲ trạng thái nào (kể cả "planned" — vừa phát mẻ, chưa nấu xong) — mirror
    thực tế nấu bia: nhiều mẻ nấu liên tiếp cùng đổ vào 1 tank, mẻ nào xong bơm vào mẻ đó, không
    đợi hết cả đợt mới có tank. Vì vậy on_hand/volume_hl CHỈ cộng theo actual_qty đã ghi nhận —
    mẻ chưa xong (actual_qty=None) đóng góp 0, KHÔNG lấy tạm planned_qty (đó là gốc bug tồn tank
    bị cộng nhầm SL kế hoạch của mẻ chưa nấu như dịch thật, yêu cầu người dùng 2026-09-01). Khi
    1 mẻ đã gộp sau đó được ghi/sửa actual_qty (set_actual_qty), on_hand tank tự cộng thêm đúng
    phần chênh lệch — xem services/batches.py::set_actual_qty. "Ngày kết thúc vào dịch"
    (_tank_out::vao_dich_end) vẫn chỉ có giá trị khi TẤT CẢ mẻ đã gộp đều đã kết thúc (end_at),
    tức tank chỉ thật sự coi là "đang lên men" khi mọi mẻ trong đó đã hoàn thành."""
    require_perm(user, "batch.execute")
    if not batch_ids:
        raise DomainError("Chọn ít nhất 1 mẻ nấu để gộp vào tank.")
    existing_links = db.execute(
        select(BatchTankLink).where(BatchTankLink.batch_id.in_(batch_ids))).scalars().all()
    if existing_links:
        b = db.get(BatchExecution, existing_links[0].batch_id)
        raise DomainError(
            f"Mẻ nấu '{b.batch_code if b else existing_links[0].batch_id}' đã thuộc về 1 tank khác.")
    batches = db.execute(select(BatchExecution).where(BatchExecution.batch_id.in_(batch_ids))).scalars().all()
    if len(batches) != len(set(batch_ids)):
        raise NotFoundError("1 hoặc nhiều mẻ nấu không tồn tại.")
    tank_year = utcnow().year
    tank_code = (payload.get("tank_code") or "").strip()
    if not tank_code:
        tank_code = _auto_tank_code(db, batches, tank_year)
        if not tank_code:
            raise DomainError(
                "Nhập mã lô — không tự sinh được (các mẻ không cùng 1 Lệnh SX/điều độ).")
    elif db.execute(select(BatchTank).where(BatchTank.tank_code == tank_code,
                    BatchTank.tank_year == tank_year)).scalar_one_or_none():
        raise DomainError(f"Mã tank '{tank_code}' đã tồn tại trong năm {tank_year}.")
    product_ids = {b.product_id for b in batches if b.product_id}
    volume = sum(b.actual_qty or 0.0 for b in batches)
    tank_lm = payload.get("tank_lm")
    # Trước đây chỉ frontend tự lọc "tank đang trống" (available_tank_lines) khỏi dropdown —
    # không có chặn thật ở server, gọi API trực tiếp (hoặc dropdown đã stale) vẫn gộp được vào 1
    # tank vật lý đang bị tank khác chiếm dụng (2026-09-04, "Tank lên men đang điền dịch thì
    # không cho tạo thêm nữa").
    if tank_lm and _tank_lm_occupied(db, tank_lm):
        raise DomainError(f"Tank vật lý '{tank_lm}' đang bị chiếm dụng (còn tồn dịch hoặc còn mẻ nấu "
                          "chưa kết thúc) — chọn tank khác.")
    _assert_within_capacity(volume, usable_capacity_for_code(db, tank_lm, "tank"), tank_lm, "tank lên men")
    tank = BatchTank(
        tank_id=new_id(), tank_code=tank_code, tank_year=tank_year,
        tank_lm=tank_lm,
        product_id=next(iter(product_ids)) if len(product_ids) == 1 else None,
        volume_hl=volume, on_hand=volume, note=payload.get("note"),
        created_by=user.username, created_at=utcnow(),
    )
    db.add(tank)
    db.flush()
    for b in batches:
        db.add(BatchTankLink(link_id=new_id(), tank_id=tank.tank_id, batch_id=b.batch_id))
        genealogy.add_edge(db, from_type="batch", from_id=b.batch_id, to_type="batch_tank",
                           to_id=tank.tank_id, relation="lên men",
                           quantity=b.actual_qty or 0.0, uom=b.uom)
    record_audit(db, entity_type="batch_tank", entity_id=tank.tank_id, action="create",
                actor=user, after={"tank_code": tank_code, "batch_ids": batch_ids})
    db.commit()
    db.refresh(tank)
    return _tank_out(db, tank)


def update_tank(db: Session, tank_id: str, payload: dict, user: User) -> dict:
    """Sửa mã lô/tank vật lý/ghi chú của 1 BatchTank đã tồn tại (gõ nhầm lúc gộp) — trước đây
    KHÔNG có endpoint nào sửa được field riêng của Tank/Lô lọc (khác Lô thành phẩm có sẵn 3
    endpoint sửa qty/shifts/pack-date), gõ nhầm mã phải xóa tạo lại (2026-09-02, audit module
    "Mẻ sản xuất"). Chỉ nhận field THỰC SỰ có trong payload (`exclude_unset` ở router) — không
    truyền thì giữ nguyên. Đổi tank_code kiểm tra lại unique theo năm (mirror
    merge_batches_into_tank); đổi tank_lm kiểm tra lại thể tích khả dụng (mirror
    _assert_within_capacity, dùng đúng on_hand hiện tại của tank làm SL tham chiếu)."""
    require_perm(user, "batch.execute")
    tank = get_tank(db, tank_id)
    _assert_unlocked(tank)
    if "tank_code" in payload:
        new_code = (payload["tank_code"] or "").strip()
        if not new_code:
            raise DomainError("Mã lô không được để trống.")
        if new_code != tank.tank_code and db.execute(select(BatchTank).where(
                BatchTank.tank_code == new_code, BatchTank.tank_year == tank.tank_year)).scalar_one_or_none():
            raise DomainError(f"Mã tank '{new_code}' đã tồn tại trong năm {tank.tank_year}.")
        tank.tank_code = new_code
    if "tank_lm" in payload:
        new_tank_lm = payload["tank_lm"]
        if new_tank_lm != tank.tank_lm:
            if new_tank_lm and _tank_lm_occupied(db, new_tank_lm):
                raise DomainError(f"Tank vật lý '{new_tank_lm}' đang bị chiếm dụng (còn tồn dịch hoặc còn "
                                  "mẻ nấu chưa kết thúc) — chọn tank khác.")
            _assert_within_capacity(tank.volume_hl, usable_capacity_for_code(db, new_tank_lm, "tank"),
                                    new_tank_lm, "tank lên men")
            tank.tank_lm = new_tank_lm
    if "note" in payload:
        tank.note = payload["note"]
    record_audit(db, entity_type="batch_tank", entity_id=tank_id, action="edit", actor=user, after=payload)
    db.commit()
    db.refresh(tank)
    return _tank_out(db, tank)


def delete_tank(db: Session, tank_id: str, user: User) -> None:
    """Xóa 1 BatchTank — dọn ĐỦ mọi bảng con (mirror delete_ferment module Nấu-Lọc-Chiết cũ,
    routers/brewing.py:1054-1079: "MSSQL enforce FK: xóa link/reading/process_log/quality_result
    (con) trước ferment_record (cha)") — trước đây CHỈ xóa BatchTankLink + genealogy edge, bỏ
    sót BatchTankProcessLog/BatchTankDailyReading (FK thật tới batch_tank.tank_id) và
    QualityResult (len_men_chinh/phu) — trên SQL Server (FK enforce) sẽ crash IntegrityError lúc
    xóa; ở SQLite thì "xóa được" nhưng để lại rác mồ côi vĩnh viễn (2026-09-02, audit module "Mẻ
    sản xuất"). Cũng chặn xóa khi CÒN Lệnh lọc (BatchFilterOrder) đã khai báo tank này làm nguồn
    KẾ HOẠCH (chưa rút dịch thật) — trước đây chỉ chặn theo nguồn ĐÃ rút thật
    (BatchFilterLotSource), bỏ sót trường hợp lệnh lọc còn "treo" trỏ tới 1 tank không còn tồn
    tại nữa."""
    require_perm(user, "batch.execute")
    tank = get_tank(db, tank_id)
    _assert_unlocked(tank)
    _assert_no_ebr_signature(db, tank_id)
    if db.execute(select(BatchFilterLotSource).where(
            BatchFilterLotSource.source_tank_id == tank_id)).first():
        raise DomainError("Đã có lô lọc rút dịch từ tank này — xóa lô lọc trước khi xóa tank.")
    if db.execute(select(BatchFilterOrderSource).where(
            BatchFilterOrderSource.source_type == "tank",
            BatchFilterOrderSource.source_tank_id == tank_id)).first():
        raise DomainError("Đã có Lệnh lọc khai báo tank này làm nguồn — xóa/sửa lệnh lọc trước khi xóa tank.")
    for link in db.execute(select(BatchTankLink).where(BatchTankLink.tank_id == tank_id)).scalars().all():
        db.delete(link)
    for log in db.execute(select(BatchTankProcessLog).where(
            BatchTankProcessLog.tank_id == tank_id)).scalars().all():
        db.delete(log)
    for reading in db.execute(select(BatchTankDailyReading).where(
            BatchTankDailyReading.tank_id == tank_id)).scalars().all():
        db.delete(reading)
    for r in db.execute(select(QualityResult).where(
            QualityResult.scope_type == "batch_tank",
            QualityResult.scope_id.in_([qc_catalog.batch_tank_scope_id(tank_id, "len_men_chinh"),
                                        qc_catalog.batch_tank_scope_id(tank_id, "len_men_phu")]))).scalars().all():
        db.delete(r)
    # Deviation dùng scope_id = tank_id TRỰC TIẾP (khác QualityResult ở trên, dùng scope_id
    # ghép theo stage) — xem services/quality.py::open_deviation/_get_scope_obj. Trước đây không
    # dọn, để lại deviation mồ côi (có thể đang OPEN) khi xóa tank (2026-09-03, audit pipeline
    # "Mẻ SX" đợt 2).
    for dv in db.execute(select(Deviation).where(
            Deviation.scope_type == "batch_tank", Deviation.scope_id == tank_id)).scalars().all():
        db.delete(dv)
    db.flush()  # xóa con trước cha (đúng thứ tự cho DB có enforce FK thật, VD SQL Server).
    genealogy.delete_edges_for(db, "batch_tank", tank_id)
    db.delete(tank)
    record_audit(db, entity_type="batch_tank", entity_id=tank_id, action="delete", actor=user)
    db.commit()


# ==================== BatchFilterOrder (lệnh lọc) ====================
# Khai báo TRƯỚC nguồn (tank/lô lọc lại) + SL kế hoạch cho 1 đợt lọc — mirror FilterOrder/
# FilterOrderTank (module Nấu-Lọc-Chiết cũ, xem services/filter_order.py). Khi tạo Lô lọc thật
# (BatchFilterLot), người dùng CHỌN 1 lệnh lọc còn dùng được thay vì tự chọn lại nguồn (mirror
# routers/brewing.py::add_filter) — xem draw_from_filter_order bên dưới.

def list_filter_order_sources(db: Session, order_id: str) -> list[BatchFilterOrderSource]:
    return db.execute(select(BatchFilterOrderSource).where(BatchFilterOrderSource.order_id == order_id)
                      .order_by(BatchFilterOrderSource.seq)).scalars().all()


def _filter_order_status(db: Session, order: BatchFilterOrder) -> dict:
    """"Còn dùng được" (chưa complete) khi: chưa có Lô lọc nào, HOẶC còn nguồn chưa kết thúc,
    HOẶC tổng SL thực tế (volume_hl) các Lô lọc đã tạo từ lệnh này còn dưới kế hoạch - dung sai
    — mirror filter_order.py::_is_complete. "Đã tiêu thụ hạ lưu" (mirror _chiet_started) khi đã
    có Lô thành phẩm tách từ 1 trong các Lô lọc của lệnh này — chặn tạo thêm Lô lọc mới dù chưa
    đủ SL kế hoạch."""
    lots = db.execute(select(BatchFilterLot).where(BatchFilterLot.order_id == order.order_id)).scalars().all()
    actual = sum(l.volume_hl or 0.0 for l in lots)
    all_ended = bool(lots) and all(l.ended_at is not None for l in lots)
    is_complete = all_ended and actual >= (order.planned_volume_hl - order.volume_tolerance_hl)
    consumed_downstream = any(
        db.execute(select(BatchPackLot.pack_lot_id).where(
            BatchPackLot.filter_lot_id == l.filter_lot_id)).first()
        for l in lots
    )
    # Trạng thái hiển thị (yêu cầu người dùng 2026-09-01): planned (chưa tạo lô lọc nào) ->
    # dang_loc (đã có lô lọc, chưa đủ SL/chưa tiêu thụ hạ lưu) -> hoan_thanh (đủ SL kế hoạch,
    # HOẶC đã bị tiêu thụ hạ lưu — dù chưa đủ SL cũng coi như xong việc vì không thể lọc thêm).
    status = "planned" if not lots else ("hoan_thanh" if (is_complete or consumed_downstream) else "dang_loc")
    return {"lot_count": len(lots), "actual_volume_hl": round(actual, 3),
            "is_complete": is_complete, "consumed_downstream": consumed_downstream,
            "status": status, "status_label": FILTER_ORDER_STATUS_LABEL[status]}


def _filter_order_tank_lm_names(db: Session, order_id: str) -> list[str]:
    """Tên tank lên men vật lý (BatchTank.tank_lm) của các nguồn tank_type="tank" thuộc lệnh —
    hiển thị ở cột "Tank lên men" trong danh sách lệnh lọc, để phân biệt với Lô lên men (mã số,
    BatchTank.tank_code) — nguồn lọc lại (tank_type="filter_lot") không có tank lên men riêng nên
    bỏ qua, KHÔNG hiện gì cho loại đó."""
    names = []
    for s in list_filter_order_sources(db, order_id):
        if s.source_type == "tank":
            t = db.get(BatchTank, s.source_tank_id)
            if t and t.tank_lm:
                names.append(t.tank_lm)
    return names


def _filter_order_out(db: Session, order: BatchFilterOrder) -> dict:
    return {
        "order_id": order.order_id, "order_code": order.order_code, "order_year": order.order_year,
        "blend_mode": order.blend_mode, "planned_volume_hl": order.planned_volume_hl,
        "volume_tolerance_hl": order.volume_tolerance_hl, "beer_type_id": order.beer_type_id,
        "finished_product_id": order.finished_product_id, "kcs_lot_no": order.kcs_lot_no, "note": order.note,
        "created_by": order.created_by, "created_at": order.created_at, "locked": order.locked,
        "tank_lm_names": _filter_order_tank_lm_names(db, order.order_id),
        **_filter_order_status(db, order),
    }


def list_filter_orders(db: Session) -> list[dict]:
    orders = db.execute(select(BatchFilterOrder).order_by(BatchFilterOrder.created_at.desc())).scalars().all()
    return [_filter_order_out(db, o) for o in orders]


def get_filter_order(db: Session, order_id: str) -> dict:
    order = db.get(BatchFilterOrder, order_id)
    if not order:
        raise NotFoundError("Lệnh lọc không tồn tại.")
    return _filter_order_out(db, order)


def _source_label(db: Session, s: "BatchFilterOrderSource | BatchFilterLotSource") -> str:
    """Dùng chung cho CẢ BatchFilterOrderSource lẫn BatchFilterLotSource — 2 model có đúng 3
    field cần đọc (source_type/source_tank_id/source_filter_lot_id) trùng tên nhau."""
    if s.source_type == "tank":
        t = db.get(BatchTank, s.source_tank_id)
        if not t:
            return s.source_tank_id
        # Chỉ hiện tên tank vật lý (BatchTank.tank_lm) — mã lô (tank_code) không cần thiết ở
        # đây, chỉ gây rối (yêu cầu người dùng 2026-09-01: "không cần hiển thị số 01 này").
        return f"Tank {t.tank_lm}" if t.tank_lm else t.tank_code
    fl = db.get(BatchFilterLot, s.source_filter_lot_id)
    if not fl:
        return s.source_filter_lot_id
    return f"BBT {fl.to_bbt} (lọc lại — lô {fl.filter_lot_code})" if fl.to_bbt else fl.filter_lot_code


def list_filter_order_sources_out(db: Session, order_id: str) -> list[dict]:
    return [{"link_id": s.link_id, "order_id": s.order_id, "source_type": s.source_type,
             "source_tank_id": s.source_tank_id, "source_filter_lot_id": s.source_filter_lot_id,
             "source_label": _source_label(db, s), "reason": s.reason,
             "planned_v_dich_hl": s.planned_v_dich_hl, "seq": s.seq}
            for s in list_filter_order_sources(db, order_id)]


def create_filter_order(db: Session, sources: list[dict], payload: dict, user: User) -> dict:
    require_perm(user, "batch.execute")
    if not sources:
        raise DomainError("Chọn ít nhất 1 nguồn (tank hoặc lô lọc) cho lệnh lọc.")
    blend_mode = payload.get("blend_mode") or ("khong_phoi" if len(sources) == 1 else "phoi")
    if blend_mode == "khong_phoi" and len(sources) != 1:
        raise DomainError("Không phối chỉ được chọn đúng 1 nguồn.")
    if blend_mode == "phoi" and len(sources) < 2:
        raise DomainError("Phối phải chọn từ 2 nguồn trở lên.")
    order_code = (payload.get("order_code") or "").strip()
    if not order_code:
        raise DomainError("Nhập số lệnh lọc.")
    order_year = utcnow().year
    if db.execute(select(BatchFilterOrder).where(BatchFilterOrder.order_code == order_code,
                  BatchFilterOrder.order_year == order_year)).scalar_one_or_none():
        raise DomainError(f"Số lệnh lọc '{order_code}' đã tồn tại trong năm {order_year}.")

    tanks, filter_lots = [], []
    for src in sources:
        if src.get("source_type") == "filter_lot":
            if not (src.get("reason") or "").strip():
                raise DomainError("Nhập lý do lọc lại khi nguồn là 1 lô lọc khác.")
            filter_lots.append(get_filter_lot(db, src["source_filter_lot_id"]))
        else:
            tanks.append(get_tank(db, src["source_tank_id"]))

    # Tự suy Loại bia nếu tất cả tank/lô lọc nguồn cùng 1 Dịch bia (mirror _validate_tanks) —
    # nếu lẫn hoặc không rõ thì để trống, KHÔNG chặn tạo lệnh (giản lược so với module cũ).
    beer_type_id = payload.get("beer_type_id")
    if not beer_type_id:
        product_ids = {t.product_id for t in tanks if t.product_id} | {f.product_id for f in filter_lots if f.product_id}
        if len(product_ids) == 1:
            product = db.get(Product, next(iter(product_ids)))
            beer_type_id = product.beer_type_id if product else None

    planned_volume = sum(s.get("planned_v_dich_hl") or 0.0 for s in sources)
    order = BatchFilterOrder(
        order_id=new_id(), order_code=order_code, order_year=order_year, blend_mode=blend_mode,
        planned_volume_hl=planned_volume, volume_tolerance_hl=payload.get("volume_tolerance_hl") or 0.0,
        beer_type_id=beer_type_id, finished_product_id=payload.get("finished_product_id"),
        kcs_lot_no=payload.get("kcs_lot_no"), note=payload.get("note"),
        created_by=user.username, created_at=utcnow(),
    )
    db.add(order)
    db.flush()
    seq = 1
    for src, tank in zip((s for s in sources if s.get("source_type") != "filter_lot"), tanks):
        db.add(BatchFilterOrderSource(link_id=new_id(), order_id=order.order_id, source_type="tank",
                                      source_tank_id=tank.tank_id,
                                      planned_v_dich_hl=src.get("planned_v_dich_hl") or 0.0, seq=seq))
        seq += 1
    for src, fl in zip((s for s in sources if s.get("source_type") == "filter_lot"), filter_lots):
        db.add(BatchFilterOrderSource(link_id=new_id(), order_id=order.order_id, source_type="filter_lot",
                                      source_filter_lot_id=fl.filter_lot_id, reason=src["reason"],
                                      planned_v_dich_hl=src.get("planned_v_dich_hl") or 0.0, seq=seq))
        seq += 1
    record_audit(db, entity_type="batch_filter_order", entity_id=order.order_id, action="create",
                actor=user, after={"order_code": order_code, "blend_mode": blend_mode,
                                   "planned_volume_hl": planned_volume})
    db.commit()
    return _filter_order_out(db, order)


def delete_filter_order(db: Session, order_id: str, user: User) -> None:
    require_perm(user, "batch.execute")
    order = db.get(BatchFilterOrder, order_id)
    if not order:
        raise NotFoundError("Lệnh lọc không tồn tại.")
    if db.execute(select(BatchFilterLot).where(BatchFilterLot.order_id == order_id)).first():
        raise DomainError("Đã có lô lọc tạo từ lệnh này — không thể xóa.")
    for s in list_filter_order_sources(db, order_id):
        db.delete(s)
    db.delete(order)
    record_audit(db, entity_type="batch_filter_order", entity_id=order_id, action="delete", actor=user)
    db.commit()


def _bbt_aggregate(db: Session) -> dict:
    """Tổng hợp theo từng tank thành phẩm (BBT) VẬT LÝ (mã to_bbt) từ các BatchFilterLot đang
    tham chiếu — mirror filter_order.py::available_bbt_tanks (module Nấu-Lọc-Chiết cũ, giản
    lược bỏ phần "giữ chỗ lọc lại"/reserved_hl vì pipeline mới xử lý lọc lại qua
    BatchFilterLotSource.source_type="filter_lot", không cần giữ chỗ trước ở tank BBT)."""
    lots = db.execute(select(BatchFilterLot).where(BatchFilterLot.to_bbt.isnot(None))).scalars().all()
    by_code: dict[str, list[BatchFilterLot]] = {}
    for fl in lots:
        by_code.setdefault(fl.to_bbt, []).append(fl)
    out = {}
    for code, group in by_code.items():
        on_hand = round(sum(fl.on_hand or 0.0 for fl in group), 3)
        all_finished = all(fl.ended_at is not None for fl in group)
        any_qc_approved = any(fl.qc_approved for fl in group)
        all_qc_approved = all(fl.qc_approved for fl in group)
        out[code] = {"on_hand_bbt": on_hand, "all_finished": all_finished,
                    "any_qc_approved": any_qc_approved, "all_qc_approved": all_qc_approved}
    return out


def available_bbt_lines(db: Session) -> list[dict]:
    """Danh mục "Tank thành phẩm (BBT)" (ProductionLine kind=tank_bbt) kèm cờ đang chiếm dụng —
    mirror _bbt_target_blocked_by (module cũ): tank bị chặn (không chọn được làm đích mới) nếu
    CÒN mẻ chưa kết thúc (!all_finished, không thể vừa rót vừa cho mẻ khác vào cùng lúc) HOẶC
    còn dịch VÀ đã có mẻ được duyệt KCS (nhiều lô được phép cùng đổ vào 1 tank TRƯỚC khi duyệt,
    chỉ chặn SAU khi đã duyệt) HOẶC tồn ÂM (đồng hồ đo lúc lọc/chiết ra số vượt tồn phần mềm —
    LUÔN coi là chiếm dụng bất kể đã duyệt hay chưa, phải "Làm rỗng tank" về đúng 0 trước khi
    dùng lại tank cho lô lọc mới, yêu cầu người dùng 2026-09-02)."""
    lines = db.execute(select(ProductionLine).where(
        ProductionLine.kind == "tank_bbt", ProductionLine.active == true())).scalars().all()
    agg = _bbt_aggregate(db)
    out = []
    for l in sorted(lines, key=lambda x: x.code):
        a = agg.get(l.code)
        occupied = bool(a) and (not a["all_finished"] or a["on_hand_bbt"] < -1e-6
                                or (a["on_hand_bbt"] > 1e-6 and a["any_qc_approved"]))
        out.append({"code": l.code, "name": l.name, "occupied": occupied,
                   "on_hand_bbt": a["on_hand_bbt"] if a else 0.0})
    return out


def _latest_filter_lot_for_bbt(db: Session, to_bbt: str) -> Optional[BatchFilterLot]:
    """Lô lọc MỚI NHẤT còn tồn ứng với 1 tank BBT vật lý — mirror add_bottle tự tìm FilterRecord
    mới nhất theo to_bbt (module Nấu-Lọc-Chiết cũ, routers/brewing.py:1856-1859)."""
    lots = db.execute(select(BatchFilterLot).where(BatchFilterLot.to_bbt == to_bbt, BatchFilterLot.on_hand > 0)
                      .order_by(BatchFilterLot.created_at.desc())).scalars().all()
    return lots[0] if lots else None


def eligible_bbt_lines_for_pack(db: Session) -> list[dict]:
    """Tank BBT đủ điều kiện chọn "đi chiết" — mirror filter_order.py::available_bbt_tanks's
    eligible_for_chiet (module cũ): còn dịch (on_hand>0), TẤT CẢ lô lọc đổ vào đã lọc xong
    (all_finished) VÀ đã được KCS duyệt HẾT (all_qc_approved — khác available_bbt_lines ở trên,
    vốn chỉ cần any_qc_approved để CHẶN nạp thêm; ở đây phải chắc chắn 100% đã duyệt mới cho
    chiết)."""
    lines = db.execute(select(ProductionLine).where(
        ProductionLine.kind == "tank_bbt", ProductionLine.active == true())).scalars().all()
    agg = _bbt_aggregate(db)
    out = []
    for l in sorted(lines, key=lambda x: x.code):
        a = agg.get(l.code)
        if not (a and a["on_hand_bbt"] > 1e-6 and a["all_finished"] and a["all_qc_approved"]):
            continue
        fl = _latest_filter_lot_for_bbt(db, l.code)
        out.append({"code": l.code, "name": l.name, "on_hand_bbt": a["on_hand_bbt"],
                    "product_id": fl.product_id if fl else None,
                    "beer_type_id": fl.beer_type_id if fl else None,
                    "finished_product_id": fl.finished_product_id if fl else None})
    return out


def draw_from_filter_order(db: Session, order_id: str, payload: dict, user: User) -> BatchFilterLot:
    """Tạo 1 Lô lọc (BatchFilterLot) từ 1 Lệnh lọc đã khai báo — nhân bản các dòng nguồn kế
    hoạch (BatchFilterOrderSource) thành BatchFilterLotSource thật, kế thừa Loại bia/Sản phẩm
    đích từ lệnh (mirror add_filter). Gọi lại được nhiều lần trên CÙNG 1 lệnh (VD rút dịch
    nhiều đợt) miễn lệnh chưa complete/chưa bị tiêu thụ hạ lưu. Bắt buộc chọn `to_bbt` (tank
    thành phẩm đích) — dịch lọc xong phải biết đưa vào tank vật lý nào."""
    require_perm(user, "batch.execute")
    order = db.get(BatchFilterOrder, order_id)
    if not order:
        raise NotFoundError("Lệnh lọc không tồn tại.")
    _assert_unlocked(order)
    status = _filter_order_status(db, order)
    if status["is_complete"]:
        raise DomainError("Lệnh lọc này đã đủ sản lượng kế hoạch — không thể tạo thêm lô lọc.")
    if status["consumed_downstream"]:
        raise DomainError("Đã có lô thành phẩm tách từ lô lọc của lệnh này — không thể tạo thêm lô lọc.")
    templates = list_filter_order_sources(db, order_id)
    if not templates:
        raise DomainError("Lệnh lọc chưa khai báo nguồn nào.")

    filter_lot_code = (payload.get("filter_lot_code") or "").strip()
    if not filter_lot_code:
        raise DomainError("Nhập mã lô lọc.")
    to_bbt = (payload.get("to_bbt") or "").strip()
    if not to_bbt:
        raise DomainError("Chọn tank thành phẩm (BBT) để đưa dịch lọc vào.")
    bbt_row = next((l for l in available_bbt_lines(db) if l["code"] == to_bbt), None)
    if not bbt_row:
        raise NotFoundError(f"Tank thành phẩm '{to_bbt}' không tồn tại trong Danh mục.")
    if bbt_row["occupied"]:
        raise DomainError(f"Tank thành phẩm '{to_bbt}' đang bị chiếm dụng (còn mẻ chưa kết thúc, "
                         "hoặc đã duyệt KCS còn dịch) — chọn tank khác.")
    filter_lot_year = utcnow().year
    if db.execute(select(BatchFilterLot).where(BatchFilterLot.filter_lot_code == filter_lot_code,
                  BatchFilterLot.filter_lot_year == filter_lot_year)).scalar_one_or_none():
        raise DomainError(f"Mã lô lọc '{filter_lot_code}' đã tồn tại trong năm {filter_lot_year}.")

    product_ids = set()
    for t in templates:
        if t.source_type == "tank":
            tank = db.get(BatchTank, t.source_tank_id)
            if tank and tank.product_id:
                product_ids.add(tank.product_id)
        else:
            src_fl = db.get(BatchFilterLot, t.source_filter_lot_id)
            if src_fl and src_fl.product_id:
                product_ids.add(src_fl.product_id)

    fl = BatchFilterLot(
        filter_lot_id=new_id(), filter_lot_code=filter_lot_code, filter_lot_year=filter_lot_year,
        order_id=order_id, to_bbt=to_bbt, status="dang_loc",
        product_id=next(iter(product_ids)) if len(product_ids) == 1 else None,
        beer_type_id=order.beer_type_id, finished_product_id=order.finished_product_id,
        note=payload.get("note"), created_by=user.username, created_at=utcnow(),
    )
    db.add(fl)
    db.flush()
    src_rows = []
    for t in templates:
        src = BatchFilterLotSource(link_id=new_id(), filter_lot_id=fl.filter_lot_id, source_type=t.source_type,
                                   source_tank_id=t.source_tank_id, source_filter_lot_id=t.source_filter_lot_id,
                                   reason=t.reason, seq=t.seq)
        db.add(src)
        db.flush()
        src_rows.append(src)
        if t.source_type == "tank":
            genealogy.add_edge(db, from_type="batch_tank", from_id=t.source_tank_id, to_type="batch_filter_lot",
                               to_id=fl.filter_lot_id, relation="lọc")
        else:
            genealogy.add_edge(db, from_type="batch_filter_lot", from_id=t.source_filter_lot_id,
                               to_type="batch_filter_lot", to_id=fl.filter_lot_id, relation="lọc lại")
    _open_first_batch(db, fl, src_rows)
    record_audit(db, entity_type="batch_filter_lot", entity_id=fl.filter_lot_id, action="create",
                actor=user, after={"filter_lot_code": filter_lot_code, "order_id": order_id})
    db.commit()
    db.refresh(fl)
    return _stamp_filter_lot_label(fl)


# ==================== BatchFilterLot (lô lọc) ====================

def _resync_filter_lot_status_if_stale(db: Session, fl: BatchFilterLot) -> None:
    """Tự sửa lại status nếu bị lệch so với on_hand/volume_hl thật — phòng trường hợp 1 lô lọc đã
    tách lô thành phẩm TỪ TRƯỚC khi có _sync_filter_lot_chiet_status (hoặc 1 đường mutation nào
    đó lỡ quên gọi sync), status lưu (cột DB) không tự cập nhật lại nên hiện sai vĩnh viễn dù
    tồn/tổng đã đổi thật (VD lô lọc "1": on_hand 26.99/28.1 vẫn hiện "Chờ chiết" dù đã tách lô TP
    PKG-934995 — yêu cầu người dùng 2026-09-01). Gọi ở MỌI lần đọc (list/get) để tự "chữa lành",
    không chỉ đúng lúc mutate."""
    old_status = fl.status
    _sync_filter_lot_chiet_status(fl)
    if fl.status != old_status:
        db.commit()
        db.refresh(fl)


def list_filter_lots(db: Session) -> list[BatchFilterLot]:
    lots = db.execute(select(BatchFilterLot).order_by(BatchFilterLot.created_at.desc())).scalars().all()
    for fl in lots:
        _resync_filter_lot_status_if_stale(db, fl)
    return [_stamp_filter_lot_label(fl) for fl in lots]


def get_filter_lot(db: Session, filter_lot_id: str) -> BatchFilterLot:
    fl = db.get(BatchFilterLot, filter_lot_id)
    if not fl:
        raise NotFoundError("Lô lọc không tồn tại.")
    _resync_filter_lot_status_if_stale(db, fl)
    return _stamp_filter_lot_label(fl)


def list_filter_lot_sources(db: Session, filter_lot_id: str) -> list[BatchFilterLotSource]:
    return db.execute(select(BatchFilterLotSource).where(BatchFilterLotSource.filter_lot_id == filter_lot_id)
                      .order_by(BatchFilterLotSource.seq)).scalars().all()


def list_filter_lot_sources_out(db: Session, filter_lot_id: str) -> list[dict]:
    """Mirror list_filter_order_sources_out — trước đây router trả thẳng ORM rows (không có
    source_label), frontend phải tự bịa nhãn từ 8 ký tự đầu của source_tank_id (VD "Tank
    acb191c2") vì không biết tên tank thật (yêu cầu người dùng 2026-09-01)."""
    return [{"link_id": s.link_id, "filter_lot_id": s.filter_lot_id, "source_type": s.source_type,
             "source_tank_id": s.source_tank_id, "source_filter_lot_id": s.source_filter_lot_id,
             "source_label": _source_label(db, s), "reason": s.reason, "seq": s.seq}
            for s in list_filter_lot_sources(db, filter_lot_id)]


def draw_from_tank_into_filter_lot(db: Session, sources: list[dict], payload: dict, user: User) -> BatchFilterLot:
    """Tạo 1 lô lọc mới, rút dịch từ 1..N BatchTank (phối) hoặc 1..N BatchFilterLot khác (lọc
    lại) — mirror add_filter. `sources`: [{"source_type": "tank"|"filter_lot", "source_tank_id"
    | "source_filter_lot_id", "reason" (bắt buộc khi lọc lại)}]. Thể tích rút RIÊNG từng nguồn
    chưa biết lúc tạo — nhập khi "Kết thúc" (xem finish_filter_lot_source)."""
    require_perm(user, "batch.execute")
    if not sources:
        raise DomainError("Chọn ít nhất 1 nguồn (tank hoặc lô lọc) để rút dịch.")
    tanks, filter_lots = [], []
    for src in sources:
        if src.get("source_type") == "filter_lot":
            if not (src.get("reason") or "").strip():
                raise DomainError("Nhập lý do lọc lại khi nguồn là 1 lô lọc khác.")
            src_fl = get_filter_lot(db, src["source_filter_lot_id"])
            filter_lots.append(src_fl)
        else:
            src_tank = get_tank(db, src["source_tank_id"])
            tanks.append(src_tank)
    filter_lot_code = (payload.get("filter_lot_code") or "").strip()
    if not filter_lot_code:
        raise DomainError("Nhập mã lô lọc.")
    to_bbt = (payload.get("to_bbt") or "").strip()
    if not to_bbt:
        raise DomainError("Chọn tank thành phẩm (BBT) để đưa dịch lọc vào.")
    bbt_row = next((l for l in available_bbt_lines(db) if l["code"] == to_bbt), None)
    if not bbt_row:
        raise NotFoundError(f"Tank thành phẩm '{to_bbt}' không tồn tại trong Danh mục.")
    if bbt_row["occupied"]:
        raise DomainError(f"Tank thành phẩm '{to_bbt}' đang bị chiếm dụng (còn mẻ chưa kết thúc, "
                         "hoặc đã duyệt KCS còn dịch) — chọn tank khác.")
    filter_lot_year = utcnow().year
    if db.execute(select(BatchFilterLot).where(BatchFilterLot.filter_lot_code == filter_lot_code,
                  BatchFilterLot.filter_lot_year == filter_lot_year)).scalar_one_or_none():
        raise DomainError(f"Mã lô lọc '{filter_lot_code}' đã tồn tại trong năm {filter_lot_year}.")
    product_ids = {t.product_id for t in tanks if t.product_id} | {f.product_id for f in filter_lots if f.product_id}
    fl = BatchFilterLot(
        filter_lot_id=new_id(), filter_lot_code=filter_lot_code, filter_lot_year=filter_lot_year,
        to_bbt=to_bbt, status="dang_loc", product_id=next(iter(product_ids)) if len(product_ids) == 1 else None,
        beer_type_id=payload.get("beer_type_id"), finished_product_id=payload.get("finished_product_id"),
        note=payload.get("note"), created_by=user.username, created_at=utcnow(),
    )
    db.add(fl)
    db.flush()
    src_rows = []
    seq = 1
    for src, tank in zip((s for s in sources if s.get("source_type") != "filter_lot"), tanks):
        row = BatchFilterLotSource(link_id=new_id(), filter_lot_id=fl.filter_lot_id, source_type="tank",
                                   source_tank_id=tank.tank_id, seq=seq)
        db.add(row)
        db.flush()
        src_rows.append(row)
        genealogy.add_edge(db, from_type="batch_tank", from_id=tank.tank_id, to_type="batch_filter_lot",
                           to_id=fl.filter_lot_id, relation="lọc")
        seq += 1
    for src, src_fl in zip((s for s in sources if s.get("source_type") == "filter_lot"), filter_lots):
        row = BatchFilterLotSource(link_id=new_id(), filter_lot_id=fl.filter_lot_id, source_type="filter_lot",
                                   source_filter_lot_id=src_fl.filter_lot_id, reason=src["reason"], seq=seq)
        db.add(row)
        db.flush()
        src_rows.append(row)
        genealogy.add_edge(db, from_type="batch_filter_lot", from_id=src_fl.filter_lot_id,
                           to_type="batch_filter_lot", to_id=fl.filter_lot_id, relation="lọc lại")
        seq += 1
    _open_first_batch(db, fl, src_rows)
    record_audit(db, entity_type="batch_filter_lot", entity_id=fl.filter_lot_id, action="create",
                actor=user, after={"filter_lot_code": filter_lot_code})
    db.commit()
    db.refresh(fl)
    return _stamp_filter_lot_label(fl)


def _open_first_batch(db: Session, fl: BatchFilterLot, src_rows: list[BatchFilterLotSource]) -> BatchFilterLotBatch:
    """Mở sẵn mẻ lọc số 1 lúc tạo lô lọc, có sẵn 1 khoản rút (draw) trống cho MỖI nguồn đã khai
    báo — người dùng chỉ cần điền V dịch nha từng nguồn lúc "Kết thúc" mẻ."""
    b = BatchFilterLotBatch(batch_link_id=new_id(), filter_lot_id=fl.filter_lot_id, created_at=utcnow())
    db.add(b)
    db.flush()
    for src in src_rows:
        db.add(BatchFilterLotBatchDraw(draw_id=new_id(), batch_link_id=b.batch_link_id, source_link_id=src.link_id))
    return b


def list_filter_lot_batches(db: Session, filter_lot_id: str) -> list[BatchFilterLotBatch]:
    # Tie-breaker phụ (batch_link_id) TRÊN created_at — created_at (DATETIMEOFFSET trên MSSQL)
    # có thể trùng giữa 2 request tạo mẻ gần như đồng thời, khiến "mẻ cuối" (batches[-1], xem
    # add_filter_lot_batch/frontend canAdd) không ổn định giữa các lần gọi — thêm tie-breaker để
    # thứ tự LUÔN xác định (2026-09-03, audit pipeline "Mẻ SX" đợt 2).
    return db.execute(select(BatchFilterLotBatch).where(BatchFilterLotBatch.filter_lot_id == filter_lot_id)
                      .order_by(BatchFilterLotBatch.created_at, BatchFilterLotBatch.batch_link_id)).scalars().all()


def list_batch_draws(db: Session, batch_link_id: str) -> list[BatchFilterLotBatchDraw]:
    return db.execute(select(BatchFilterLotBatchDraw).where(
        BatchFilterLotBatchDraw.batch_link_id == batch_link_id)).scalars().all()


def batch_with_draws(db: Session, b: BatchFilterLotBatch) -> dict:
    """Gắn danh sách khoản rút (draws) vào 1 mẻ lọc để trả về API — BatchFilterLotBatch không
    có relationship ORM, ghép thủ công (mirror cách các API khác trong module này trả dict)."""
    return {
        "batch_link_id": b.batch_link_id, "filter_lot_id": b.filter_lot_id,
        "batch_seq_no": b.batch_seq_no, "nuoc_bai_khi_hl": b.nuoc_bai_khi_hl,
        "is_final_batch": b.is_final_batch, "ended_at": b.ended_at, "created_at": b.created_at,
        "draws": [{"source_link_id": d.source_link_id, "dich_nha_hl": d.dich_nha_hl}
                 for d in list_batch_draws(db, b.batch_link_id)],
    }


def _all_batches_for_filter_lot(db: Session, filter_lot_id: str) -> list[BatchFilterLotBatch]:
    return list_filter_lot_batches(db, filter_lot_id)


def _sync_filter_lot_aggregate(db: Session, fl: BatchFilterLot) -> None:
    """Tổng hợp v_dich_hl/nuoc_bai_khi_hl/volume_hl/on_hand của BatchFilterLot = tổng cộng dồn
    từ MỌI mẻ lọc (BatchFilterLotBatch) — v_dich_hl cộng dồn TỪNG KHOẢN RÚT (BatchFilterLotBatchDraw)
    của mọi mẻ (1 mẻ có thể có N khoản, mỗi nguồn 1 khoản), nuoc_bai_khi_hl cộng theo TỪNG MẺ
    (mirror _sync_filter_aggregate module cũ, v_beer_hl = v_dich_hl + nuoc_bai_khi_hl). on_hand
    điều chỉnh theo CHÊNH LỆCH, giữ nguyên phần đã tách vào lô thành phẩm. ended_at chỉ có giá
    trị khi TẤT CẢ mẻ đã kết thúc."""
    batches = _all_batches_for_filter_lot(db, fl.filter_lot_id)
    old_volume = fl.volume_hl or 0.0
    consumed = old_volume - fl.on_hand
    v_dich = 0.0
    nuoc_bai_khi = 0.0
    for b in batches:
        nuoc_bai_khi += b.nuoc_bai_khi_hl or 0.0
        v_dich += sum(d.dich_nha_hl or 0.0 for d in list_batch_draws(db, b.batch_link_id))
    new_volume = v_dich + nuoc_bai_khi
    fl.v_dich_hl = round(v_dich, 3)
    fl.nuoc_bai_khi_hl = round(nuoc_bai_khi, 3)
    fl.volume_hl = round(new_volume, 3)
    fl.on_hand = max(0.0, round(new_volume - consumed, 3))
    fl.ended_at = (max(b.ended_at for b in batches)
                  if batches and all(b.ended_at is not None for b in batches) else None)


def add_filter_lot_batch(db: Session, filter_lot_id: str, user: User) -> BatchFilterLotBatch:
    """"+ Thêm mẻ" — mở 1 mẻ lọc MỚI cho lô lọc (VD 1 tank thành phẩm cần vài mẻ mới đầy) —
    mirror add_filter_tank_batch. Chỉ thêm được khi mẻ GẦN NHẤT đã "Kết thúc" — tránh mở nhiều
    mẻ dở dang cùng lúc. Mẻ mới có sẵn 1 khoản rút trống cho MỖI nguồn đã khai báo của lô lọc."""
    require_perm(user, "batch.execute")
    fl = get_filter_lot(db, filter_lot_id)
    _assert_unlocked(fl)
    batches = list_filter_lot_batches(db, filter_lot_id)
    if batches and batches[-1].ended_at is None:
        raise DomainError("Mẻ lọc gần nhất chưa kết thúc — kết thúc mẻ đó trước khi thêm mẻ mới.")
    src_rows = list_filter_lot_sources(db, filter_lot_id)
    b = _open_first_batch(db, fl, src_rows)
    # Mẻ mới chưa "Kết thúc" -> lô lọc KHÔNG còn "đã lọc xong hết" (ended_at phải về None ngay,
    # không đợi tới lần "Kết thúc" mẻ tiếp theo mới cập nhật lại).
    _sync_filter_lot_aggregate(db, fl)
    db.commit()
    db.refresh(b)
    return b


def _assert_no_ebr_signature(db: Session, entity_id: str) -> None:
    """Chặn xóa nếu đã có chữ ký điện tử (Signature scope_type="ebr") ký cho entity này — trước
    đây sign_tank/sign_filter_lot/sign_pack_lot (services/ebr.py) cho ký TRƯỚC khi khóa
    (`.locked`), và delete_tank/delete_filter_lot/delete_pack_lot chỉ chặn xóa theo `.locked`/
    `qc_approved`/`approved`, không kiểm tra đã ký hay chưa — ký xong nhưng CHƯA khóa vẫn xóa
    được, làm chữ ký điện tử (bằng chứng GMP) trỏ tới 1 bản ghi không còn tồn tại (2026-09-03,
    audit pipeline "Mẻ SX" đợt 2)."""
    if db.execute(select(Signature.sig_id).where(
            Signature.scope_type == "ebr", Signature.scope_id == entity_id)).first():
        raise DomainError("Bản ghi này đã có chữ ký điện tử (EBR) — không thể xóa.")


def _lock_origin(db: Session, source: BatchFilterLotSource):
    """Khóa hàng (SELECT ... FOR UPDATE) tank/lô lọc NGUỒN của 1 khoản rút — tuần tự hoá đọc-
    rồi-ghi on_hand khi 2 thao tác (Kết thúc mẻ lọc/Xóa mẻ lọc/Xóa lô lọc) cùng lúc động vào
    CÙNG 1 nguồn, tránh mất-cập-nhật (lost update) trên DB có row-lock thật (SQL Server/
    Postgres — SQLite bỏ qua, xem 2026-09-03, audit pipeline "Mẻ SX" đợt 2)."""
    if source.source_type == "filter_lot":
        return db.execute(select(BatchFilterLot).where(
            BatchFilterLot.filter_lot_id == source.source_filter_lot_id).with_for_update()).scalar_one_or_none()
    return db.execute(select(BatchTank).where(
        BatchTank.tank_id == source.source_tank_id).with_for_update()).scalar_one_or_none()


def finish_filter_lot_batch(db: Session, batch_link_id: str, draws: list[dict],
                            nuoc_bai_khi_hl: float, batch_seq_no: str, user: User,
                            started_at=None, ended_at=None) -> BatchFilterLot:
    """Kết thúc/sửa 1 mẻ lọc — mirror finish_filter_tank, gọi lại được nhiều lần để sửa. `draws`:
    [{"source_link_id", "dich_nha_hl"}] — 1 khoản/nguồn, trừ/hoàn on_hand tank/lô lọc NGUỒN
    tương ứng theo CHÊNH LỆCH dich_nha_hl (nuoc_bai_khi_hl là nước DAW phối thêm CHUNG cho cả
    mẻ, KHÔNG rút từ tank nào nên không trừ on_hand nguồn nào) — tổng hợp lại BatchFilterLot
    (xem _sync_filter_lot_aggregate: volume_hl = v_dich_hl + nuoc_bai_khi_hl). `started_at`/
    `ended_at`: sửa lại giờ thực tế qua popup "Sửa" — không truyền thì giữ nguyên created_at,
    ended_at mặc định = giờ hiện tại (yêu cầu người dùng 2026-09-01)."""
    require_perm(user, "batch.execute")
    b = db.get(BatchFilterLotBatch, batch_link_id)
    if not b:
        raise NotFoundError("Mẻ lọc không tồn tại.")
    fl = get_filter_lot(db, b.filter_lot_id)
    _assert_unlocked(fl)
    if nuoc_bai_khi_hl is not None and nuoc_bai_khi_hl < 0:
        raise DomainError("Nước bài khí (hl) không được âm.")
    existing_draws = {d.source_link_id: d for d in list_batch_draws(db, batch_link_id)}
    total_v = 0.0
    for item in draws:
        d = existing_draws.get(item["source_link_id"])
        if d is None:
            raise DomainError("Nguồn rút dịch không thuộc mẻ lọc này.")
        v = item.get("dich_nha_hl") or 0.0
        # Trước đây chỉ check TỔNG > 0 — 1 nguồn âm bù 1 nguồn dương lớn hơn vẫn qua được, cộng
        # khống tồn ảo cho nguồn kia (2026-09-03, audit pipeline "Mẻ SX" đợt 2).
        if v < 0:
            raise DomainError("V dịch nha từng nguồn không được âm.")
        old_v = d.dich_nha_hl or 0.0
        delta = v - old_v
        source = db.get(BatchFilterLotSource, d.source_link_id)
        origin = _lock_origin(db, source)
        if origin:
            origin.on_hand = round(origin.on_hand - delta, 3)
        d.dich_nha_hl = v
        total_v += v
    if total_v <= 0:
        raise DomainError("Tổng V dịch nha (các nguồn) phải lớn hơn 0 mới được kết thúc.")
    b.nuoc_bai_khi_hl = nuoc_bai_khi_hl or 0.0
    b.batch_seq_no = batch_seq_no
    if started_at:
        b.created_at = started_at
    b.ended_at = ended_at or utcnow()
    db.flush()
    _sync_filter_lot_aggregate(db, fl)
    _assert_within_capacity(fl.on_hand, usable_capacity_for_code(db, fl.to_bbt, "tank_bbt"),
                            fl.to_bbt, "tank thành phẩm")
    db.commit()
    db.refresh(fl)
    return _stamp_filter_lot_label(fl)


def toggle_final_batch(db: Session, batch_link_id: str, user: User) -> BatchFilterLotBatch:
    """Đánh dấu/bỏ đánh dấu 1 mẻ lọc là "mẻ cuối" (mẻ vét) — mirror toggle_final_batch. CHỈ ảnh
    hưởng phân loại hiệu suất (loại mẻ vét ra khỏi so sánh Thấp/Bình thường/Cao vì sản lượng
    thấp không phản ánh hiệu suất thật), không ảnh hưởng tổng hợp/khoá/xóa."""
    require_perm(user, "batch.execute")
    b = db.get(BatchFilterLotBatch, batch_link_id)
    if not b:
        raise NotFoundError("Mẻ lọc không tồn tại.")
    b.is_final_batch = not b.is_final_batch
    db.commit()
    db.refresh(b)
    return b


def delete_filter_lot_batch(db: Session, batch_link_id: str, user: User) -> BatchFilterLot:
    """Xóa 1 mẻ lọc, hoàn tác tồn về tank/lô lọc gốc của MỖI khoản rút — mirror
    delete_filter_tank_batch. Chặn nếu là mẻ DUY NHẤT của lô lọc, hoặc nếu tách lô TP đã lấy
    nhiều hơn mức tồn sẽ còn lại sau khi xóa."""
    require_perm(user, "batch.execute")
    b = db.get(BatchFilterLotBatch, batch_link_id)
    if not b:
        raise NotFoundError("Mẻ lọc không tồn tại.")
    fl = get_filter_lot(db, b.filter_lot_id)
    _assert_unlocked(fl)
    all_batches = _all_batches_for_filter_lot(db, fl.filter_lot_id)
    if len(all_batches) <= 1:
        raise DomainError("Đây là mẻ lọc duy nhất của lô lọc này — xóa cả lô lọc nếu muốn bỏ hẳn.")
    draws = list_batch_draws(db, batch_link_id)
    this_total = sum((d.dich_nha_hl or 0.0) for d in draws) + (b.nuoc_bai_khi_hl or 0.0)
    # with_for_update(): khóa lô lọc TRƯỚC khi so sánh tồn đã tách lô TP — 2 thao tác đồng thời
    # (VD tách lô TP + xóa mẻ lọc) trên CÙNG lô lọc có thể cùng đọc on_hand cũ (2026-09-03, audit
    # pipeline "Mẻ SX" đợt 2).
    fl = db.execute(select(BatchFilterLot).where(
        BatchFilterLot.filter_lot_id == fl.filter_lot_id).with_for_update()).scalar_one()
    consumed = (fl.volume_hl or 0.0) - (fl.on_hand or 0.0)
    remaining_after = (fl.volume_hl or 0.0) - this_total
    if consumed > remaining_after + 1e-6:
        raise DomainError("Không thể xóa — đã tách lô thành phẩm nhiều hơn mức tồn sẽ còn lại sau khi xóa mẻ này.")
    for d in draws:
        if d.dich_nha_hl:
            source = db.get(BatchFilterLotSource, d.source_link_id)
            origin = _lock_origin(db, source)
            if origin:
                origin.on_hand = round(origin.on_hand + d.dich_nha_hl, 3)
        db.delete(d)
    db.delete(b)
    db.flush()
    _sync_filter_lot_aggregate(db, fl)
    db.commit()
    db.refresh(fl)
    return _stamp_filter_lot_label(fl)


def update_filter_lot(db: Session, filter_lot_id: str, payload: dict, user: User) -> BatchFilterLot:
    """Sửa mã lô/ghi chú của 1 BatchFilterLot đã tồn tại (gõ nhầm lúc tạo) — mirror update_tank
    (2026-09-02, audit module "Mẻ sản xuất"). KHÔNG cho sửa `to_bbt` ở đây — đổi tank BBT đích
    sau khi đã rút dịch/dùng NVL thật sẽ làm sai lệch on_hand/tổng hợp của CẢ 2 tank BBT (cũ/mới),
    phức tạp và rủi ro hơn hẳn giá trị của việc sửa 1 field — muốn đổi đích thật sự thì xóa tạo
    lại (chỉ được khi chưa dùng gì, xem delete_filter_lot)."""
    require_perm(user, "batch.execute")
    fl = get_filter_lot(db, filter_lot_id)
    _assert_unlocked(fl)
    if "filter_lot_code" in payload:
        new_code = (payload["filter_lot_code"] or "").strip()
        if not new_code:
            raise DomainError("Mã lô lọc không được để trống.")
        if new_code != fl.filter_lot_code and db.execute(select(BatchFilterLot).where(
                BatchFilterLot.filter_lot_code == new_code,
                BatchFilterLot.filter_lot_year == fl.filter_lot_year)).scalar_one_or_none():
            raise DomainError(f"Mã lô lọc '{new_code}' đã tồn tại trong năm {fl.filter_lot_year}.")
        fl.filter_lot_code = new_code
    if "note" in payload:
        fl.note = payload["note"]
    record_audit(db, entity_type="batch_filter_lot", entity_id=filter_lot_id, action="edit", actor=user, after=payload)
    db.commit()
    db.refresh(fl)
    return _stamp_filter_lot_label(fl)


def delete_filter_lot(db: Session, filter_lot_id: str, user: User) -> None:
    """Xóa 1 BatchFilterLot — mirror delete_filter (module cũ, routers/brewing.py:1786-1818):
    hoàn NVL đã dùng thật (BatchFilterLotMaterialUsage, undo_issue trả kho) + dọn QualityResult
    con — trước đây bỏ sót cả 2, để lại NVL đã xuất kho không hoàn/rác QualityResult mồ côi
    (2026-09-02, audit module "Mẻ sản xuất"). Cũng chặn xóa khi đã KCS duyệt (`qc_approved`) —
    mirror delete_pack_lot's check `p.approved` (bất đối xứng vô lý trước đây: xóa lô TP đã
    duyệt bị chặn, xóa lô lọc đã duyệt lại KHÔNG — phá hủy 1 bản ghi QC đã ký duyệt)."""
    require_perm(user, "batch.execute")
    fl = get_filter_lot(db, filter_lot_id)
    _assert_unlocked(fl)
    _assert_no_ebr_signature(db, filter_lot_id)
    if fl.qc_approved:
        raise DomainError("Lô lọc này đã được KCS duyệt — không thể xóa.")
    if db.execute(select(BatchPackLot).where(BatchPackLot.filter_lot_id == filter_lot_id)).first():
        raise DomainError("Đã có lô thành phẩm tách từ lô lọc này — xóa lô thành phẩm trước.")
    if db.execute(select(BatchFilterLotSource).where(
            BatchFilterLotSource.source_filter_lot_id == filter_lot_id)).first():
        raise DomainError("Đã có lô lọc khác lọc lại từ lô lọc này — xóa lô lọc lại đó trước.")
    # Xóa TẤT CẢ draw (con) + flush TRƯỚC khi xóa batch (cha): model không có relationship() +
    # autoflush=False nên SQLAlchemy KHÔNG tự xếp con-trước-cha trong 1 flush chung → MSSQL enforce
    # FK batch_filter_lot_batch_draw.batch_link_id sẽ vỡ 547 (SQLite bỏ qua). DEPLOY-CONTRACT lớp con-ẩn.
    filter_batches = list_filter_lot_batches(db, filter_lot_id)
    for b in filter_batches:
        for d in list_batch_draws(db, b.batch_link_id):
            if d.dich_nha_hl:
                source = db.get(BatchFilterLotSource, d.source_link_id)
                origin = _lock_origin(db, source)
                if origin:
                    origin.on_hand = round(origin.on_hand + d.dich_nha_hl, 3)
            db.delete(d)
    db.flush()
    for b in filter_batches:
        db.delete(b)
    db.flush()
    for source in list_filter_lot_sources(db, filter_lot_id):
        db.delete(source)
    for u in list_filter_lot_materials(db, filter_lot_id):
        if u.movement_id:
            warehouse_svc.undo_issue(db, u.movement_id, user, strict=False, skip_perm_check=True)
        db.delete(u)
    for r in db.execute(select(QualityResult).where(
            QualityResult.scope_type == "batch_filter_lot", QualityResult.scope_id == filter_lot_id)).scalars().all():
        db.delete(r)
    for dv in db.execute(select(Deviation).where(
            Deviation.scope_type == "batch_filter_lot", Deviation.scope_id == filter_lot_id)).scalars().all():
        db.delete(dv)
    db.flush()
    genealogy.delete_edges_for(db, "batch_filter_lot", filter_lot_id)
    db.delete(fl)
    record_audit(db, entity_type="batch_filter_lot", entity_id=filter_lot_id, action="delete", actor=user)
    db.commit()


def approve_filter_lot(db: Session, filter_lot_id: str, user: User) -> dict:
    """KCS ký duyệt lô lọc — yêu cầu đã khai đủ chỉ tiêu bắt buộc (stage "loc", scope_type
    "batch_filter_lot"), mirror approve_filter. Set `qc_approved` (cờ riêng, KHÁC
    quality_status vốn đã mặc định RELEASED ngay từ lúc tạo) — đây là tín hiệu THẬT để biết
    lô lọc đã được KCS ký duyệt hay chưa (dùng bởi available_bbt_lines để biết tank BBT có
    còn "khoá" không cho đổ thêm mẻ khác vào sau khi đã duyệt)."""
    require_perm(user, "quality.release")
    fl = get_filter_lot(db, filter_lot_id)
    _assert_unlocked(fl)
    if fl.qc_approved:
        raise DomainError("Lô lọc này đã được duyệt.")
    if fl.ended_at is None:
        raise DomainError("Lô lọc đang lọc (chưa kết thúc hết các nguồn) — chỉ duyệt khi đã lọc xong.")
    status = qc_catalog.stage_qc_status(db, "loc", "batch_filter_lot", filter_lot_id,
                                        product_id=fl.product_id, beer_type_id=fl.beer_type_id,
                                        finished_product_id=fl.finished_product_id)
    if status["pending"]:
        raise DomainError(f"Còn thiếu chỉ tiêu bắt buộc (lọc): {', '.join(status['pending'])}.")
    fl.qc_approved = True
    fl.qc_approved_by = user.username
    fl.qc_approved_at = utcnow()
    record_audit(db, entity_type="batch_filter_lot", entity_id=filter_lot_id, action="approve", actor=user)
    db.commit()
    return {"filter_lot_id": filter_lot_id, "qc_approved": True, "qc_has_fail": status["has_fail"]}


def finish_filtering(db: Session, filter_lot_id: str, user: User) -> BatchFilterLot:
    """"Hoàn thành lọc" — mốc XÁC NHẬN riêng của vận hành (KHÁC "✔ Duyệt KCS" ở trên, đúng sơ đồ
    tổ chức đã áp dụng cho BatchPackLot: vận hành xác nhận xong việc, KCS ký duyệt chỉ tiêu là
    2 bước tách biệt) — chuyển trạng thái "dang_loc" -> "cho_chiet", yêu cầu người dùng
    2026-09-01. Yêu cầu mọi mẻ lọc đã "Kết thúc" (fl.ended_at) — chưa xong mà xác nhận thì sai."""
    require_perm(user, "batch.execute")
    fl = get_filter_lot(db, filter_lot_id)
    _assert_unlocked(fl)
    if fl.status != "dang_loc":
        raise DomainError("Lô lọc không ở trạng thái đang lọc.")
    if fl.ended_at is None:
        raise DomainError("Còn mẻ lọc chưa kết thúc — kết thúc hết các mẻ lọc trước khi xác nhận hoàn thành lọc.")
    fl.status = "cho_chiet"
    record_audit(db, entity_type="batch_filter_lot", entity_id=filter_lot_id, action="finish_filtering", actor=user)
    db.commit()
    db.refresh(fl)
    return _stamp_filter_lot_label(fl)


# ==================== BatchPackLot (lô thành phẩm) ====================

PACK_LOT_STATUS_LABEL = {"dang_chiet": "Đang chiết", "chiet_1_phan": "Chiết 1 phần", "chiet_het": "Chiết hết"}


def _pack_lot_status(db: Session, p: BatchPackLot) -> str:
    """Suy hoàn toàn từ dữ liệu (không lưu cột status riêng), mirror _tank_status/
    _sync_filter_lot_chiet_status — yêu cầu người dùng 2026-09-02: "Chiết thì bổ sung thêm cột
    trạng thái, Nếu tạo ra lô chiết thì là đang chiết, khi thể tích chiết có sai số bằng +- sai
    số làm rỗng tank và số lượng chiết ra của tổng 3 ca >0 thì lô đó được coi là chiết hết, nếu
    thể tích cấp chiết >0 nhưng chưa chiết hết thì được coi là chiết 1 phần".

    "tổng 3 ca" (ca1_qty+ca2_qty+ca3_qty, đơn vị vỉ/két/keg — KHÁC qty/lít, xem
    release_pack_lot_to_wms) = tín hiệu DUY NHẤT phân biệt "vừa tạo, chưa ai ghi ca nào"
    (dang_chiet) khỏi "đã có tiến độ chiết thật" (chiet_1_phan/chiet_het) — bản thân qty (SL cấp
    chiết) luôn > 0 ngay từ lúc tạo nên không dùng được để phân biệt 2 trạng thái này. "sai số
    làm rỗng tank" = settings.empty_bbt_tolerance_hl (đúng ngưỡng dùng cho nút "Làm rỗng tank" ở
    Lô lọc) — lô lọc NGUỒN (filter_lot.on_hand) đã về gần 0 trong ngưỡng đó nghĩa là tank BBT đã
    chiết cạn thật, không còn gì để chiết tiếp cho lô TP này."""
    ca_total = (p.ca1_qty or 0.0) + (p.ca2_qty or 0.0) + (p.ca3_qty or 0.0)
    if ca_total <= 0:
        return "dang_chiet"
    fl = db.get(BatchFilterLot, p.filter_lot_id)
    tolerance = ops_setting.get_settings(db).empty_bbt_tolerance_hl
    if fl is not None and abs(fl.on_hand) <= tolerance:
        return "chiet_het"
    return "chiet_1_phan"


def _stamp_pack_lot_status(db: Session, p: BatchPackLot) -> BatchPackLot:
    status = _pack_lot_status(db, p)
    p.status = status
    p.status_label = PACK_LOT_STATUS_LABEL[status]
    return p


def list_pack_lots(db: Session, filter_lot_id: str = None) -> list[BatchPackLot]:
    stmt = select(BatchPackLot).order_by(BatchPackLot.created_at.desc())
    if filter_lot_id:
        stmt = stmt.where(BatchPackLot.filter_lot_id == filter_lot_id)
    rows = db.execute(stmt).scalars().all()
    return [_stamp_pack_lot_status(db, p) for p in rows]


def get_pack_lot(db: Session, pack_lot_id: str) -> BatchPackLot:
    p = db.get(BatchPackLot, pack_lot_id)
    if not p:
        raise NotFoundError("Lô thành phẩm không tồn tại.")
    return _stamp_pack_lot_status(db, p)


def split_filter_lot_to_pack_lot(db: Session, filter_lot_id: str, payload: dict, user: User) -> BatchPackLot:
    """Tách 1 lô thành phẩm từ lô lọc nguồn (gọi lặp lại để tách nhiều lô) — trừ on_hand lô lọc
    ngay lúc tách (mirror finish_bottle, không cho tách vượt quá tồn). `qty` (Số lượng cấp
    chiết) đơn vị LÍT — lô lọc nguồn (on_hand/volume_hl) đơn vị hl, quy đổi 1 hl = 100 lít khi
    trừ/hoàn tồn."""
    require_perm(user, "batch.execute")
    fl = get_filter_lot(db, filter_lot_id)
    _assert_unlocked(fl)
    qty = payload.get("qty") or 0.0
    if qty <= 0:
        raise DomainError("Số lượng cấp chiết (lít) phải lớn hơn 0.")
    qty_hl = qty / L_PER_HL
    # with_for_update(): khóa lô lọc TRƯỚC khi check "đủ tồn" — 2 request tách lô TP gần như
    # đồng thời từ CÙNG lô lọc có thể cùng đọc on_hand cũ rồi cùng qua được check, tách vượt tồn
    # thật (2026-09-03, audit pipeline "Mẻ SX" đợt 2).
    fl = db.execute(select(BatchFilterLot).where(
        BatchFilterLot.filter_lot_id == filter_lot_id).with_for_update()).scalar_one()
    if qty_hl > fl.on_hand + 1e-6:
        raise DomainError(f"Không đủ tồn để tách — lô lọc còn {fl.on_hand:g} hl ({fl.on_hand * L_PER_HL:g} lít), "
                         f"yêu cầu tách {qty:g} lít.")
    pack_lot_code = (payload.get("pack_lot_code") or "").strip()
    if not pack_lot_code:
        raise DomainError("Nhập mã lô thành phẩm.")
    lot_no = (payload.get("lot_no") or "").strip()
    if not lot_no:
        raise DomainError("Nhập số lô bia.")
    pack_lot_year = utcnow().year
    if db.execute(select(BatchPackLot).where(BatchPackLot.pack_lot_code == pack_lot_code,
                  BatchPackLot.pack_lot_year == pack_lot_year)).scalar_one_or_none():
        raise DomainError(f"Mã lô thành phẩm '{pack_lot_code}' đã tồn tại trong năm {pack_lot_year}.")
    # Số lô bia (lot_no) là số lô GMP thật in trên bao bì — phải DUY NHẤT toàn hệ thống trong
    # cùng 1 năm (mirror quy ước mã lô/mã nấu khác — pack_lot_code/filter_lot_code/batch_code —
    # đều unique theo (năm, mã), yêu cầu người dùng 2026-09-01: 2 lô thành phẩm khác nhau đã lỡ
    # trùng cùng "Số lô bia" 1).
    if db.execute(select(BatchPackLot).where(BatchPackLot.lot_no == lot_no,
                  BatchPackLot.pack_lot_year == pack_lot_year)).scalar_one_or_none():
        raise DomainError(f"Số lô bia '{lot_no}' đã tồn tại trong năm {pack_lot_year} — mỗi số lô bia phải duy nhất.")
    p = BatchPackLot(
        pack_lot_id=new_id(), pack_lot_code=pack_lot_code, pack_lot_year=pack_lot_year,
        filter_lot_id=filter_lot_id, qty=qty,
        finished_product_id=payload.get("finished_product_id") or fl.finished_product_id,
        lot_no=lot_no, line=payload.get("line"),
        from_bbt=payload.get("from_bbt") or fl.to_bbt,
        pack_date=payload.get("pack_date") or utcnow(),
        note=payload.get("note"),
        created_by=user.username, created_at=utcnow(),
    )
    fl.on_hand = round(fl.on_hand - qty_hl, 3)
    _sync_filter_lot_chiet_status(fl)
    db.add(p)
    db.flush()
    genealogy.add_edge(db, from_type="batch_filter_lot", from_id=filter_lot_id, to_type="batch_pack_lot",
                       to_id=p.pack_lot_id, relation="chiết", quantity=qty, uom="L")
    record_audit(db, entity_type="batch_pack_lot", entity_id=p.pack_lot_id, action="create",
                actor=user, after={"pack_lot_code": pack_lot_code, "qty": qty})
    db.commit()
    db.refresh(p)
    return _stamp_pack_lot_status(db, p)


def create_pack_lot_from_bbt(db: Session, payload: dict, user: User) -> BatchPackLot:
    """Tạo lô thành phẩm bằng cách chọn "Tank BBT nào đi chiết" (mirror add_bottle's from_bbt) —
    server tự tìm lô lọc nguồn mới nhất còn tồn ứng với tank đó, người dùng không cần tự chọn
    lô lọc. Đây là lối vào MỚI cho màn "Lô thành phẩm (Mẻ SX)"; split_filter_lot_to_pack_lot
    (chọn thẳng filter_lot_id) vẫn giữ nguyên cho API cấp thấp."""
    require_perm(user, "batch.execute")
    from_bbt = (payload.get("from_bbt") or "").strip()
    if not from_bbt:
        raise DomainError("Chọn tank thành phẩm (BBT) để chiết.")
    row = next((r for r in eligible_bbt_lines_for_pack(db) if r["code"] == from_bbt), None)
    if not row:
        raise DomainError(f"Tank BBT '{from_bbt}' chưa đủ điều kiện chiết "
                         "(chưa lọc xong hết/chưa được KCS duyệt hết/hết dịch).")
    fl = _latest_filter_lot_for_bbt(db, from_bbt)
    if not fl:
        raise NotFoundError(f"Không tìm thấy lô lọc nguồn cho tank BBT '{from_bbt}'.")
    payload = {**payload, "from_bbt": from_bbt}
    return split_filter_lot_to_pack_lot(db, fl.filter_lot_id, payload, user)


def update_pack_lot_qty(db: Session, pack_lot_id: str, qty: float, user: User) -> BatchPackLot:
    """Sửa Số lượng cấp chiết đã tách (bấm nhầm) — điều chỉnh on_hand lô lọc theo CHÊNH LỆCH
    (mirror finish_bottle sửa v_cap_chiet_hl). `qty` đơn vị lít, quy đổi sang hl khi trừ tồn
    lô lọc (xem split_filter_lot_to_pack_lot)."""
    require_perm(user, "batch.execute")
    p = get_pack_lot(db, pack_lot_id)
    _assert_unlocked(p)
    if qty <= 0:
        raise DomainError("Số lượng cấp chiết (lít) phải lớn hơn 0.")
    # with_for_update(): khóa CẢ lô TP (đọc p.qty cũ) LẪN lô lọc nguồn (đọc/ghi on_hand) trước
    # khi tính chênh lệch — 2 request sửa SL cấp chiết gần như đồng thời có thể cùng đọc giá trị
    # cũ rồi cùng ghi, làm sai on_hand lô lọc (2026-09-03, audit pipeline "Mẻ SX" đợt 2).
    p = db.execute(select(BatchPackLot).where(
        BatchPackLot.pack_lot_id == pack_lot_id).with_for_update()).scalar_one()
    fl = db.execute(select(BatchFilterLot).where(
        BatchFilterLot.filter_lot_id == p.filter_lot_id).with_for_update()).scalar_one()
    delta_hl = (qty - p.qty) / L_PER_HL
    if delta_hl > fl.on_hand + 1e-6:
        raise DomainError(f"Không đủ tồn để tăng số lượng — lô lọc còn {fl.on_hand:g} hl "
                         f"({fl.on_hand * L_PER_HL:g} lít), cần thêm {(qty - p.qty):g} lít.")
    fl.on_hand = round(fl.on_hand - delta_hl, 3)
    _sync_filter_lot_chiet_status(fl)
    p.qty = qty
    db.commit()
    db.refresh(p)
    return _stamp_pack_lot_status(db, p)


def update_pack_lot_pack_date(db: Session, pack_lot_id: str, pack_date, user: User) -> BatchPackLot:
    """Sửa giờ bắt đầu chiết (bấm nhầm/nhập bổ sung sau)."""
    require_perm(user, "batch.execute")
    p = get_pack_lot(db, pack_lot_id)
    _assert_unlocked(p)
    p.pack_date = pack_date
    db.commit()
    db.refresh(p)
    return _stamp_pack_lot_status(db, p)


def update_pack_lot_shifts(db: Session, pack_lot_id: str, payload: dict, user: User) -> BatchPackLot:
    """Ghi SL chiết theo ca 1/2/3 + giờ bắt đầu/kết thúc từng ca — mirror finish_bottle's
    ca1/ca2/ca3 (module Nấu-Lọc-Chiết cũ), sửa lại được nhiều lần. Trạng thái (dang_chiet/
    chiet_1_phan/chiet_het, xem _pack_lot_status) suy lại NGAY sau khi ghi ca — đây chính là nơi
    duy nhất ca_total có thể chuyển từ 0 sang >0.

    SL từng ca KHÔNG được âm — trước đây không validate gì (khác update_pack_lot_qty đã chặn
    qty<=0), số âm/rác lọt được thẳng vào ca_total quyết định trạng thái "chiết hết" VÀ vào
    release_pack_lot_to_wms's ca_total*pack_size tạo tồn kho WMS thật (2026-09-02, audit module
    "Mẻ sản xuất")."""
    require_perm(user, "batch.execute")
    p = get_pack_lot(db, pack_lot_id)
    _assert_unlocked(p)
    for qty_key in ("ca1_qty", "ca2_qty", "ca3_qty"):
        v = payload.get(qty_key)
        if v is not None and v < 0:
            raise DomainError(f"SL chiết ({qty_key}) không được âm.")
    for key in ("ca1_qty", "ca1_start_at", "ca1_end_at", "ca2_qty", "ca2_start_at", "ca2_end_at",
                "ca3_qty", "ca3_start_at", "ca3_end_at"):
        if key in payload:
            setattr(p, key, payload[key])
    db.commit()
    db.refresh(p)
    return _stamp_pack_lot_status(db, p)


def delete_pack_lot(db: Session, pack_lot_id: str, user: User) -> None:
    """Xóa 1 BatchPackLot — mirror delete_bottle (module cũ, routers/brewing.py:1911-1942):
    hoàn NVL đã dùng thật (BatchPackLotMaterialUsage, undo_issue trả kho) + dọn QualityResult
    con — trước đây bỏ sót cả 2, để lại NVL đã xuất kho không hoàn/rác QualityResult mồ côi
    (2026-09-02, audit module "Mẻ sản xuất")."""
    require_perm(user, "batch.execute")
    p = get_pack_lot(db, pack_lot_id)
    _assert_unlocked(p)
    _assert_no_ebr_signature(db, pack_lot_id)
    if p.approved:
        raise DomainError("Lô thành phẩm đã được duyệt KCS — không thể xóa.")
    # with_for_update(): khóa lô lọc trước khi hoàn on_hand — cùng lớp race với split/update qty
    # (2026-09-03, audit pipeline "Mẻ SX" đợt 2).
    fl = db.execute(select(BatchFilterLot).where(
        BatchFilterLot.filter_lot_id == p.filter_lot_id).with_for_update()).scalar_one()
    fl.on_hand = round(fl.on_hand + p.qty / L_PER_HL, 3)
    _sync_filter_lot_chiet_status(fl)
    for u in list_pack_lot_materials(db, pack_lot_id):
        if u.movement_id:
            warehouse_svc.undo_issue(db, u.movement_id, user, strict=False, skip_perm_check=True)
        db.delete(u)
    for r in db.execute(select(QualityResult).where(
            QualityResult.scope_type == "batch_pack_lot", QualityResult.scope_id == pack_lot_id)).scalars().all():
        db.delete(r)
    for dv in db.execute(select(Deviation).where(
            Deviation.scope_type == "batch_pack_lot", Deviation.scope_id == pack_lot_id)).scalars().all():
        db.delete(dv)
    db.flush()
    genealogy.delete_edges_for(db, "batch_pack_lot", pack_lot_id)
    db.delete(p)
    record_audit(db, entity_type="batch_pack_lot", entity_id=pack_lot_id, action="delete", actor=user)
    db.commit()


def approve_pack_lot(db: Session, pack_lot_id: str, user: User) -> dict:
    """KCS ký duyệt lô thành phẩm — yêu cầu đã khai đủ chỉ tiêu bắt buộc (stage "thanh_pham",
    scope_type "batch_pack_lot"). Đây là bước KCS RIÊNG (khai/khóa chỉ tiêu) — quyết định cho
    nhập kho thành phẩm hay không nằm ở release_pack_lot_to_wms bên dưới (mirror approve_bottle
    module Nấu-Lọc-Chiết cũ, ở đó 2 việc này gộp vào 1 hành động; tách ra đây theo đúng sơ đồ tổ
    chức thật đã ghi trong docstring cũ: KCS nhập/khóa chỉ tiêu, Giám đốc/Phó GĐ SX quyết định
    nhập kho)."""
    require_perm(user, "quality.release")
    p = get_pack_lot(db, pack_lot_id)
    _assert_unlocked(p)
    if p.approved:
        raise DomainError("Lô thành phẩm này đã được duyệt.")
    fl = get_filter_lot(db, p.filter_lot_id)
    status = qc_catalog.stage_qc_status(db, "thanh_pham", "batch_pack_lot", pack_lot_id,
                                        product_id=fl.product_id, beer_type_id=fl.beer_type_id,
                                        finished_product_id=p.finished_product_id)
    if status["pending"]:
        raise DomainError(f"Còn thiếu chỉ tiêu bắt buộc (thành phẩm): {', '.join(status['pending'])}.")
    p.approved = True
    p.approved_by = user.username
    p.approved_at = utcnow()
    record_audit(db, entity_type="batch_pack_lot", entity_id=pack_lot_id, action="approve", actor=user)
    db.commit()
    return {"pack_lot_id": pack_lot_id, "approved": True, "qc_has_fail": status["has_fail"]}


def release_pack_lot_to_wms(db: Session, pack_lot_id: str, user: User) -> dict:
    """Giám đốc/Phó GĐ Sản xuất - Kỹ thuật duyệt cho nhập kho thành phẩm — mirror
    routers/brewing.py::approve_bottle (module Nấu-Lọc-Chiết cũ; module đó đã THÁO khỏi WMS,
    Lô thành phẩm là nơi thay thế duy nhất tạo FinishedGoodsUnit từ sản xuất). Yêu cầu đã Duyệt
    KCS (p.approved) và đã khai SL theo ca (ca1+ca2+ca3 > 0, đơn vị vỉ/két/keg theo
    FinishedProduct.unit_type — KHÁC qty (lít) ở trên). Tạo 1 dòng FinishedGoodsUnit
    (source="chiet" — tái dùng đúng giá trị cũ để không phải sửa mọi nơi trong services/wms.py
    đang lọc theo source, VD confirm_receipt_by_lot/_consume_lot_rows), lot_code=lot_no. Sau
    khi tạo, dòng này vẫn cần Trưởng bộ phận kho duyệt nhập kho riêng
    (wms_svc.confirm_receipt_by_lot, y hệt luồng cũ, không đổi gì ở services/wms.py) mới khoá
    lại/mở khoá xuất được — xem UI Kho TP (WMS) hiện có, tự động thấy dòng mới này qua cùng
    tiêu chí lọc (product_name/lot_code/unit_type/source)."""
    require_perm(user, "production.release_to_wms")
    p = get_pack_lot(db, pack_lot_id)
    _assert_unlocked(p)
    if p.stocked:
        raise DomainError("Lô thành phẩm này đã nhập kho thành phẩm.")
    if not p.approved:
        raise DomainError("Chưa Duyệt KCS — không thể nhập kho thành phẩm.")
    ca_total = (p.ca1_qty or 0.0) + (p.ca2_qty or 0.0) + (p.ca3_qty or 0.0)
    if ca_total <= 0:
        raise DomainError("Chưa nhập SL theo ca (Ca 1/2/3) — không thể duyệt nhập kho thành phẩm.")
    finished_product = db.get(FinishedProduct, p.finished_product_id) if p.finished_product_id else None
    pack_size = finished_product.pack_size if finished_product else 24
    unit_type = finished_product.unit_type if finished_product else "vi"
    product_name = finished_product.code if finished_product else p.pack_lot_code
    units = wms_svc._create_units(db, {
        "finished_product_id": p.finished_product_id, "product_name": product_name,
        "lot_code": p.lot_no or p.pack_lot_code, "total": ca_total * pack_size, "pack_size": pack_size,
        "unit_type": unit_type, "source": "chiet",
    }, created_by=user.username, actor=user)
    for u in units:
        genealogy.add_edge(db, from_type="batch_pack_lot", from_id=pack_lot_id, to_type="finished_goods_unit",
                           to_id=u.unit_id, relation="nhập kho", quantity=u.quantity, uom=u.unit_type)
    p.stocked = True
    p.stocked_by = user.username
    p.stocked_at = utcnow()
    record_audit(db, entity_type="batch_pack_lot", entity_id=pack_lot_id, action="release_to_wms", actor=user)
    db.commit()
    return {"pack_lot_id": pack_lot_id, "stocked": True, "unit_type": unit_type, "count": ca_total,
            "unit_codes": [u.unit_code for u in units]}


# ==================== NVL dùng cho lô thành phẩm (chiết) ====================
# Mirror add_bottle_material/update/delete (routers/brewing.py:1935-2015, module Nấu-Lọc-Chiết
# cũ) — trừ/hoàn tồn kho thật qua warehouse_svc.issue()/undo_issue(), giữ movement_id để hoàn
# kho khi sửa/xóa.

def list_pack_lot_materials(db: Session, pack_lot_id: str) -> list[BatchPackLotMaterialUsage]:
    return db.execute(select(BatchPackLotMaterialUsage).where(
        BatchPackLotMaterialUsage.pack_lot_id == pack_lot_id)).scalars().all()


def add_pack_lot_material(db: Session, pack_lot_id: str, payload: dict, user: User) -> BatchPackLotMaterialUsage:
    require_perm(user, "batch.execute")
    p = get_pack_lot(db, pack_lot_id)
    _assert_unlocked(p)
    data = dict(payload)
    lot_id = data.get("lot_id")
    reason = (data.get("reason") or "").strip() or None
    if lot_id:
        lot = db.get(MaterialLot, lot_id)
        if not lot:
            raise NotFoundError("Lô nguyên liệu không tồn tại.")
        if not warehouse_svc._is_workshop_location(lot.location):
            raise DomainError(f"Lô {lot.lot_code} không ở Kho phân xưởng — chỉ được dùng nguyên liệu "
                             "từ Kho phân xưởng cho lô thành phẩm.")
        material = db.get(Material, lot.material_id) if lot.material_id else None
        data["material_name"] = material.name if material else lot.lot_code
        data["lot_pm"] = lot.lot_code
        data["lot_date"] = lot.created_at
        # fifo_ok=False (còn lô khác cũ hơn chưa dùng hết) bắt buộc ghi rõ lý do (mirror
        # services/dispense.py::_plan_consume, yêu cầu người dùng 2026-09-01) — kiểm tra TRƯỚC
        # khi issue() trừ kho thật, tránh trừ tồn rồi mới báo lỗi.
        data["fifo_ok"] = warehouse_svc.is_oldest_workshop_lot(db, lot.material_id, lot_id)
        if not data["fifo_ok"] and not reason:
            raise DomainError(f"Lô {lot.lot_code} không phải lô FIFO (cũ nhất) của vật tư này — "
                             "bắt buộc nhập lý do chọn lô khác.")
        data["uom"] = lot.uom
        result = warehouse_svc.issue(db, lot_id, data["quantity"], user, mode="tu_do",
                                     reason=f"Dùng cho lô thành phẩm {p.pack_lot_code}",
                                     ref_doc=p.pack_lot_code, skip_perm_check=True)
        data["movement_id"] = result["movement_id"]
    elif not (data.get("material_name") or "").strip():
        raise DomainError("Chọn nguyên liệu từ tồn kho Kho phân xưởng, hoặc nhập tên tự do.")
    u = BatchPackLotMaterialUsage(
        usage_id=new_id(), pack_lot_id=pack_lot_id, lot_id=lot_id, movement_id=data.get("movement_id"),
        material_name=data.get("material_name"), lot_pm=data.get("lot_pm"), lot_date=data.get("lot_date"),
        fifo_ok=data.get("fifo_ok"), reason=reason, quantity=data["quantity"], uom=data.get("uom") or "kg",
        created_at=utcnow(),
    )
    db.add(u)
    record_audit(db, entity_type="batch_pack_lot", entity_id=pack_lot_id, action="material_add", actor=user,
                after={"material_name": u.material_name, "lot_pm": u.lot_pm, "quantity": u.quantity, "uom": u.uom})
    db.commit()
    db.refresh(u)
    return u


def delete_pack_lot_material(db: Session, usage_id: str, user: User) -> None:
    require_perm(user, "batch.execute")
    u = db.get(BatchPackLotMaterialUsage, usage_id)
    if not u:
        raise NotFoundError("Dòng nguyên liệu không tồn tại.")
    p = get_pack_lot(db, u.pack_lot_id)
    _assert_unlocked(p)
    if u.movement_id:
        warehouse_svc.undo_issue(db, u.movement_id, user, strict=False, skip_perm_check=True)
    before = {"material_name": u.material_name, "lot_pm": u.lot_pm, "quantity": u.quantity, "uom": u.uom}
    db.delete(u)
    record_audit(db, entity_type="batch_pack_lot", entity_id=u.pack_lot_id, action="material_delete",
                 actor=user, before=before)
    db.commit()


# ==================== NVL dùng cho Lô lọc — mirror BatchPackLotMaterialUsage trên ====================

def list_filter_lot_materials(db: Session, filter_lot_id: str) -> list[BatchFilterLotMaterialUsage]:
    return db.execute(select(BatchFilterLotMaterialUsage).where(
        BatchFilterLotMaterialUsage.filter_lot_id == filter_lot_id)).scalars().all()


def add_filter_lot_material(db: Session, filter_lot_id: str, payload: dict, user: User) -> BatchFilterLotMaterialUsage:
    require_perm(user, "batch.execute")
    fl = get_filter_lot(db, filter_lot_id)
    _assert_unlocked(fl)
    data = dict(payload)
    lot_id = data.get("lot_id")
    reason = (data.get("reason") or "").strip() or None
    if lot_id:
        lot = db.get(MaterialLot, lot_id)
        if not lot:
            raise NotFoundError("Lô nguyên liệu không tồn tại.")
        if not warehouse_svc._is_workshop_location(lot.location):
            raise DomainError(f"Lô {lot.lot_code} không ở Kho phân xưởng — chỉ được dùng nguyên liệu "
                             "từ Kho phân xưởng cho lô lọc.")
        material = db.get(Material, lot.material_id) if lot.material_id else None
        data["material_name"] = material.name if material else lot.lot_code
        data["lot_pm"] = lot.lot_code
        data["lot_date"] = lot.created_at
        data["fifo_ok"] = warehouse_svc.is_oldest_workshop_lot(db, lot.material_id, lot_id)
        if not data["fifo_ok"] and not reason:
            raise DomainError(f"Lô {lot.lot_code} không phải lô FIFO (cũ nhất) của vật tư này — "
                             "bắt buộc nhập lý do chọn lô khác.")
        data["uom"] = lot.uom
        result = warehouse_svc.issue(db, lot_id, data["quantity"], user, mode="tu_do",
                                     reason=f"Dùng cho lô lọc {fl.filter_lot_code}",
                                     ref_doc=fl.filter_lot_code, skip_perm_check=True)
        data["movement_id"] = result["movement_id"]
    elif not (data.get("material_name") or "").strip():
        raise DomainError("Chọn nguyên liệu từ tồn kho Kho phân xưởng, hoặc nhập tên tự do.")
    u = BatchFilterLotMaterialUsage(
        usage_id=new_id(), filter_lot_id=filter_lot_id, lot_id=lot_id, movement_id=data.get("movement_id"),
        material_name=data.get("material_name"), lot_pm=data.get("lot_pm"), lot_date=data.get("lot_date"),
        fifo_ok=data.get("fifo_ok"), reason=reason, quantity=data["quantity"], uom=data.get("uom") or "kg",
        created_at=utcnow(),
    )
    db.add(u)
    record_audit(db, entity_type="batch_filter_lot", entity_id=filter_lot_id, action="material_add", actor=user,
                after={"material_name": u.material_name, "lot_pm": u.lot_pm, "quantity": u.quantity, "uom": u.uom})
    db.commit()
    db.refresh(u)
    return u


def delete_filter_lot_material(db: Session, usage_id: str, user: User) -> None:
    require_perm(user, "batch.execute")
    u = db.get(BatchFilterLotMaterialUsage, usage_id)
    if not u:
        raise NotFoundError("Dòng nguyên liệu không tồn tại.")
    fl = get_filter_lot(db, u.filter_lot_id)
    _assert_unlocked(fl)
    if u.movement_id:
        warehouse_svc.undo_issue(db, u.movement_id, user, strict=False, skip_perm_check=True)
    before = {"material_name": u.material_name, "lot_pm": u.lot_pm, "quantity": u.quantity, "uom": u.uom}
    db.delete(u)
    record_audit(db, entity_type="batch_filter_lot", entity_id=u.filter_lot_id, action="material_delete",
                 actor=user, before=before)
    db.commit()
