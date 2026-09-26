"""Pipeline thực thi MỚI cho "Mẻ sản xuất" (BatchExecution) theo blueprint 4 lớp: mẻ nấu →
tank lên men (BatchTank) → lô lọc (BatchFilterLot) → lô thành phẩm (BatchPackLot).

Mirror đúng pattern đã chứng minh hoạt động ở module Nấu-Lọc-Chiết cũ (on_hand giảm theo
DELTA — xem routers/brewing.py::finish_filter_tank/finish_bottle; genealogy edge tạo lúc gộp/
rút dịch — xem add_ferment/add_filter) nhưng độc lập hoàn toàn, KHÔNG đụng module cũ.

Chỉ tiêu chất lượng tái dùng đúng stage cũ ("len_men_chinh"/"loc"/"thanh_pham") qua scope_type
mới ("batch_tank"/"batch_filter_lot"/"batch_pack_lot") — xem services/qc_catalog.py::stage_qc_status.
"""

import math
import re
from datetime import timedelta
from typing import Optional

from sqlalchemy import func, select, true
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import new_id, utcnow
from ..errors import DomainError, NotFoundError
from ..models.audit import AuditLog
from ..models.batch_pipeline import (
    BatchFilterLot,
    BatchFilterLotBatch,
    BatchFilterLotBatchDraw,
    BatchFilterLotMaterialUsage,
    BatchFilterLotSource,
    BatchFilterOrder,
    BatchFilterOrderMaterialLine,
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
from ..models.master import BeerType, FinishedProduct, Material, PackingSpec, Product
from ..models.materials import MaterialLot
from ..models.quality import Deviation, QualityResult
from ..models.signature import Signature
from ..models.wms import Pallet, WmsLocation
from ..models.workorder import WorkOrder
from ..security import User, require_perm
from . import dispense as dispense_svc
from . import genealogy, ops_setting, qc_catalog, quality
from . import warehouse as warehouse_svc
from . import wms as wms_svc

L_PER_HL = 100.0   # 1 hectolít = 100 lít — quy đổi Số lượng cấp chiết (lít) <-> on_hand lô lọc (hl)

# Trạng thái hiển thị (yêu cầu người dùng 2026-09-01) — mirror đúng mã/nhãn đã dùng ở module
# Nấu-Lọc-Chiết cũ (routers/brewing.py::FILTER_STATUS, services/derived.py::ferment_status) cho
# nhất quán, dù 2 hệ không liên kết. BatchTank suy hoàn toàn từ dữ liệu (không lưu cột status —
# xem _tank_status); BatchFilterLot lưu cột status thật vì "hoan_thanh" cần 1 mốc XÁC NHẬN của
# vận hành ("Hoàn thành lọc") không suy được từ on_hand/ended_at; BatchFilterOrder suy hoàn toàn
# từ lot_count/is_complete (xem _filter_order_status).
#
# "planned" (Chưa nấu — yêu cầu người dùng 2026-09-06: "nếu 1 trong các mẻ sản xuất nấu ít nhất
# là running/Completed/closed thì được coi là đang điền dịch, nếu không đều ở trạng thái Planned")
# — tank đã gộp mẻ nhưng CHƯA mẻ nào thật sự bắt đầu nấu (running/held/completed/closed), chỉ mới
# "đặt chỗ", KHÁC hẳn "dang_nau" (đã có ít nhất 1 mẻ bắt đầu, dịch thật đã/đang chảy vào tank).
TANK_STATUS_LABEL = {"planned": "Chưa nấu", "dang_nau": "Đang điền dịch", "len_men": "Đang lên men",
                     "cho_loc": "Chờ lọc", "loc_1_phan": "Lọc 1 phần", "da_loc_het": "Lọc hết",
                     "am": "⚠ Âm (lệch số liệu)"}
# Lô lọc CHỈ còn 2 mốc: "dang_loc" (đang lọc) -> "hoan_thanh" (đã "Hoàn thành lọc") — KHÔNG còn
# tự chuyển tiếp theo tiến độ rút dịch vào lô thành phẩm (yêu cầu người dùng 2026-09-06: "lọc này
# để ở trạng thái completed thôi, không mở đến trạng thái chiết, chiết 1 phần chiết hết. các
# trạng thái chiết sẽ ở bên chiết thôi" — tiến độ chiết đã có sẵn riêng ở BatchPackLot, xem
# _pack_lot_status, không cần lặp lại ở đây).
FILTER_LOT_STATUS_LABEL = {"dang_loc": "Đang lọc", "hoan_thanh": "Hoàn thành", "am": "⚠ Âm (lệch số liệu)"}
FILTER_ORDER_STATUS_LABEL = {"planned": "Lập kế hoạch", "dang_loc": "Đang lọc", "hoan_thanh": "Hoàn thành"}


def _filter_lot_chiet_status(db: Session, fl: BatchFilterLot) -> Optional[str]:
    """Trạng thái CHIẾT (đóng gói) của lô lọc này — tóm tắt tiến độ rút dịch qua các Lô thành
    phẩm (BatchPackLot) đã tách ra, dùng ĐÚNG 3 mốc/logic đã có sẵn cho BatchPackLot.status (xem
    _pack_lot_status, yêu cầu người dùng gốc 2026-09-02), chỉ khác là GỘP tất cả Lô TP con của lô
    lọc này lại thay vì tính riêng từng lô — cột hiển thị THÊM, THUẦN THÔNG TIN ở màn "Lô lọc",
    KHÔNG đụng gì tới BatchFilterLot.status (mốc "Hoàn thành lọc" riêng, đã tách hẳn khỏi tiến độ
    chiết theo yêu cầu người dùng 2026-09-06 — xem _sync_filter_lot_status) (yêu cầu người dùng
    2026-09-25: "thêm cho tôi trạng thái chiết vào đây, khi tạo lô chiết thì sẽ là đang chiết, khi
    chiết > 0 nhưng nhỏ hơn tổng hl, thì là chiết 1 phần, khi tồn là 0 thì là chiết hết"). Trả về
    None nếu CHƯA có Lô thành phẩm nào tách từ lô lọc này (chưa chiết gì cả — không hiện badge)."""
    pack_lots = db.execute(select(BatchPackLot).where(
        BatchPackLot.filter_lot_id == fl.filter_lot_id)).scalars().all()
    if not pack_lots:
        return None
    tolerance = ops_setting.get_settings(db).empty_bbt_tolerance_hl
    if abs(fl.on_hand) <= tolerance:
        return "chiet_het"
    ca_total = sum((p.ca1_qty or 0.0) + (p.ca2_qty or 0.0) + (p.ca3_qty or 0.0) for p in pack_lots)
    if ca_total <= 0:
        return "dang_chiet"
    return "chiet_1_phan"


def _stamp_filter_lot_label(db: Session, fl: BatchFilterLot) -> BatchFilterLot:
    """BatchFilterLot trả thẳng ORM object qua response_model=BatchFilterLotOut (không qua dict
    "_out" như BatchTank/BatchFilterOrder) — gắn status_label làm thuộc tính TẠM trên instance
    (không phải cột DB) để Pydantic (from_attributes) đọc được, mirror routers/brewing.py::FILTER_STATUS
    nhưng tính ngay ở đây cho gọn."""
    fl.status_label = FILTER_LOT_STATUS_LABEL.get(fl.status, fl.status)
    chiet_status = _filter_lot_chiet_status(db, fl)
    fl.chiet_status = chiet_status
    fl.chiet_status_label = PACK_LOT_STATUS_LABEL.get(chiet_status, "") if chiet_status else ""
    return fl


def _sync_filter_lot_status(fl: BatchFilterLot) -> None:
    """Gọi sau MỌI lần đổi fl.on_hand do lô thành phẩm (tạo/sửa SL/xóa). CHỈ còn 2 mốc:
    "dang_loc" (đang lọc, chưa bấm "Hoàn thành lọc") <-> "hoan_thanh" (đã xong) — KHÔNG còn tự
    chuyển tiếp theo tiến độ rút dịch vào lô thành phẩm nữa (trước đây tới 2026-09-06 còn
    cho_chiet/chiet_1_phan/da_chiet_het — bỏ hẳn theo yêu cầu người dùng: "lọc này để ở trạng
    thái completed thôi, không mở đến trạng thái chiết, chiết 1 phần chiết hết. các trạng thái
    chiết sẽ ở bên chiết thôi" — tiến độ chiết đã có sẵn riêng ở BatchPackLot, xem
    _pack_lot_status, không cần lặp lại ở đây). Nếu lô lọc chưa từng bấm "Hoàn thành lọc" (còn
    "dang_loc") mà đã có mẻ chiết rồi (VD do thao tác cũ/test không qua bước đó) thì coi như đã
    bỏ qua bước đó, tự chuyển luôn sang "hoan_thanh" — mirror hành vi cũ, chỉ khác không còn
    phân biệt chiết 1 phần/chiết hết nữa. Dữ liệu CŨ còn lưu 3 giá trị deprecated (cho_chiet/
    chiet_1_phan/da_chiet_het) tự "chữa lành" về "hoan_thanh" qua đúng nhánh này (status khác
    "dang_loc" → luôn hoan_thanh), gọi ở mọi lần đọc — xem _resync_filter_lot_status_if_stale.

    "am" (tồn ÂM — đồng hồ đo lúc chiết ra số vượt tồn phần mềm đang có, yêu cầu người dùng
    2026-09-02: cho phép ghi nhận thay vì chặn cứng, nhưng phải cảnh báo RÕ) — chỉ zero được qua
    empty_filter_lot (trong ngưỡng dung sai); available_bbt_lines coi tank BBT còn "am" là VẪN
    CHIẾM DỤNG, không cho mẻ lọc mới nào khác dùng lại tank đó tới khi = 0."""
    if fl.on_hand < -1e-6:
        fl.status = "am"
    elif fl.volume_hl <= 1e-6:
        # Chưa từng có mẻ lọc nào "Kết thúc" (volume_hl vẫn = 0, chưa rút được hl nào) — LUÔN
        # "dang_loc" bất kể status cột DB đang lưu gì (kể cả giá trị cũ/deprecated đã lỡ lệch).
        fl.status = "dang_loc"
    elif fl.on_hand < fl.volume_hl - 1e-6 or fl.status != "dang_loc":
        fl.status = "hoan_thanh"


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
    nhánh lên men/lọc bên dưới.

    "planned" (yêu cầu người dùng 2026-09-06: "nếu 1 trong các mẻ sản xuất nấu ít nhất là
    running/Completed/closed thì được coi là đang điền dịch, nếu không đều ở trạng thái Planned")
    — tách khỏi "dang_nau": chỉ coi là "đang điền dịch" (dịch THẬT đã/đang chảy vào tank) khi có
    ÍT NHẤT 1 mẻ đã thật sự bắt đầu nấu (running/held — đã qua "running" nên start_at đã có/
    completed/closed); nếu TẤT CẢ mẻ đã gộp còn planned/ready (chưa mẻ nào chạy) thì tank mới chỉ
    "đặt chỗ", CHƯA có gì đổ vào — không tính là "đang điền dịch" (trước đây gộp chung với
    "dang_nau" khiến tank chưa hề bắt đầu nấu cũng hiện "Đang điền dịch", gây hiểu lầm)."""
    if tank.on_hand < -1e-6:
        return "am"
    batch_ids = tank_batch_ids(db, tank.tank_id)
    if batch_ids:
        states = set(db.execute(select(BatchExecution.state).where(
            BatchExecution.batch_id.in_(batch_ids))).scalars().all())
        started = {"running", "held", "completed", "closed"}
        if not (states & started):
            return "planned"
        if db.execute(select(BatchExecution.batch_id).where(
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
        "product_code": product.code if product else None, "product_name": product.name if product else None,
        "beer_type_name": beer_type.name if beer_type else None,
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


def list_tank_empty_history(db: Session, tank_id: str) -> list[dict]:
    """Lịch sử làm rỗng tank — đọc lại từ AuditLog (đã ghi sẵn ở empty_tank(), before.on_hand =
    tồn còn lại lúc làm rỗng, after.on_hand luôn 0.0) thay vì lưu thêm bảng/JSON riêng — đây là
    log HỆ THỐNG tự ghi mỗi lần bấm "Làm rỗng tank" (không phải dữ liệu người dùng tự nhập/sửa
    tay như mốc hạ phụ), mirror cách services/ebr.py dựng lại lịch sử thao tác từ AuditLog."""
    rows = db.execute(select(AuditLog).where(
        AuditLog.entity_type == "batch_tank", AuditLog.entity_id == tank_id, AuditLog.action == "empty",
    ).order_by(AuditLog.ts.desc())).scalars().all()
    return [{"at": a.ts.isoformat(), "residual_hl": (a.before or {}).get("on_hand"), "by": a.actor}
            for a in rows]


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
    _sync_filter_lot_status(fl)
    db.commit()
    db.refresh(fl)
    return _stamp_filter_lot_label(db, fl)


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


def _order_tank_sources_drained(db: Session, order_id: str) -> bool:
    """TẤT CẢ tank lên men nguồn (source_type="tank") của lệnh lọc này đã "Lọc hết" (_tank_status
    == "da_loc_het", tức tank.on_hand <= 0 sau khi rút dịch) chưa — lệnh KHÔNG có nguồn tank nào
    (VD lệnh lọc lại thuần từ Lô lọc khác, source_type="filter_lot") trả về False, không tự động
    hoàn thành theo tiêu chí này (yêu cầu người dùng 2026-09-25: "khi lô lên men đó đã báo lọc
    hết, thì toàn bộ lệnh lọc đi theo lô đó sẽ sang hoàn thành luôn" — áp dụng cho CẢ lệnh phối
    nhiều tank: phải HẾT CẢ, không phải chỉ 1 tank trong số đó, mới coi là lệnh đã xong nguồn)."""
    tank_ids = db.execute(select(BatchFilterOrderSource.source_tank_id).where(
        BatchFilterOrderSource.order_id == order_id, BatchFilterOrderSource.source_type == "tank",
        BatchFilterOrderSource.source_tank_id.isnot(None))).scalars().all()
    if not tank_ids:
        return False
    tanks = db.execute(select(BatchTank).where(BatchTank.tank_id.in_(tank_ids))).scalars().all()
    return len(tanks) == len(tank_ids) and all(_tank_status(db, t) == "da_loc_het" for t in tanks)


def _filter_order_status(db: Session, order: BatchFilterOrder) -> dict:
    """`is_complete` = tổng SL thực tế (volume_hl) các Lô lọc đã tạo từ lệnh này đã đạt kế hoạch
    - dung sai chưa. Khi True, lệnh lọc TỰ ĐỘNG coi là "hoàn thành" (status="hoan_thanh") — KHÔNG
    cần bấm gì (yêu cầu người dùng 2026-09-23, làm rõ lại: "sản lượng thực tế >= sản lượng kế
    hoạch - sai số thì lệnh lọc đó được coi là hoàn thành"). Việc 1 Lô lọc (BatchFilterLot) con tự
    bấm "Hoàn thành lọc" (finish_filtering) của riêng nó KHÔNG ảnh hưởng gì tới is_complete/status
    ở đây — is_complete chỉ suy từ tổng volume_hl, tách biệt hoàn toàn khỏi mốc lô con. Nút "Hoàn
    thành lệnh lọc" (order.completed, xem finish_filter_order) dùng cho trường hợp NGƯỢC LẠI: vận
    hành CHỦ ĐỘNG dừng sớm khi CHƯA đạt đủ SL kế hoạch (VD chỉ lọc một nửa kế hoạch rồi quyết định
    không lọc thêm nữa) — cũng cho ra status="hoan_thanh" y hệt. `tank_sources_drained` (yêu cầu
    người dùng 2026-09-25) là tiêu chí TỰ ĐỘNG thứ 3, độc lập với `is_complete`: lô lên men nguồn
    có thể có ÍT dịch hơn kế hoạch (hao hụt thật) khiến `is_complete` không bao giờ đạt — nhưng
    tank đã rút cạn (không còn gì để lọc thêm nữa) thì lệnh lọc cũng coi như xong, không cần đợi
    vận hành bấm "Hoàn thành lệnh lọc" thủ công. "Đã tiêu thụ hạ lưu" (mirror _chiet_started) khi
    đã có Lô thành phẩm tách từ 1 trong các Lô lọc của lệnh này — KHÔNG đổi status, chỉ vẫn dùng
    để chặn tạo thêm Lô lọc mới (ràng buộc vật lý thật, xem VIEWS.batchfilterlots — khác hẳn
    "hoàn thành")."""
    lots = db.execute(select(BatchFilterLot).where(BatchFilterLot.order_id == order.order_id)).scalars().all()
    actual = sum(l.volume_hl or 0.0 for l in lots)
    is_complete = actual >= (order.planned_volume_hl - order.volume_tolerance_hl)
    tank_sources_drained = _order_tank_sources_drained(db, order.order_id)
    consumed_downstream = any(
        db.execute(select(BatchPackLot.pack_lot_id).where(
            BatchPackLot.filter_lot_id == l.filter_lot_id)).first()
        for l in lots
    )
    # Trạng thái hiển thị: planned (chưa tạo lô lọc nào) -> dang_loc (đã có lô lọc, chưa đủ SL kế
    # hoạch VÀ chưa bấm "Hoàn thành lệnh lọc" VÀ tank nguồn chưa lọc hết) -> hoan_thanh (is_complete
    # TỰ ĐỘNG, HOẶC tank_sources_drained TỰ ĐỘNG, HOẶC order.completed = mốc dừng sớm thủ công —
    # xem finish_filter_order).
    status = "planned" if not lots else ("hoan_thanh" if (is_complete or tank_sources_drained or order.completed) else "dang_loc")
    return {"lot_count": len(lots), "actual_volume_hl": round(actual, 3),
            "is_complete": is_complete, "tank_sources_drained": tank_sources_drained,
            "consumed_downstream": consumed_downstream,
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
        "completed": order.completed, "completed_by": order.completed_by, "completed_at": order.completed_at,
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


def _filter_order_stock_snapshot(db: Session) -> tuple[dict, dict]:
    """Trả 2 dict {material_id: on_hand} — mirror brew_order.py::_stock_snapshot, dùng cho vật
    tư dự kiến khai báo lúc lập lệnh lọc (BatchFilterOrderMaterialLine)."""
    company = {r["material_id"]: r["on_hand"] for r in warehouse_svc.stock_on_hand(db, "Kho công ty")}
    workshop = {r["material_id"]: r["on_hand"] for r in warehouse_svc.stock_on_hand(db, "Kho phân xưởng")}
    return company, workshop


def _assert_filter_order_material_stock(lines: list[dict], company_stock: dict, workshop_stock: dict) -> None:
    """Chặn hẳn việc lập lệnh lọc nếu có dòng vật tư dự kiến thiếu tồn (tổng 2 kho) — mirror
    brew_order.py::_assert_no_shortage nhưng đơn giản hơn (không có header/nhóm vật tư thay
    thế). Dòng chỉ có material_name tự do (không chọn từ danh mục) bỏ qua kiểm tra tồn vì
    không tra được tồn kho cho vật tư không có trong danh mục."""
    shortages = []
    for line in lines:
        material_id = line.get("material_id")
        qty_planned = line.get("qty_planned") or 0.0
        if not material_id or qty_planned <= 0:
            continue
        company = company_stock.get(material_id, 0.0)
        workshop = workshop_stock.get(material_id, 0.0)
        if qty_planned > company + workshop:
            name = line.get("material_name") or material_id
            shortages.append(
                f"{name}: cần {qty_planned}, hiện có {round(company + workshop, 3)} "
                f"(Kho công ty {round(company, 3)} + Kho phân xưởng {round(workshop, 3)})")
    if shortages:
        raise DomainError("Không đủ tồn kho để lập lệnh lọc — " + "; ".join(shortages) + ".")


def list_filter_order_materials(db: Session, order_id: str) -> list[dict]:
    lines = db.execute(select(BatchFilterOrderMaterialLine).where(
        BatchFilterOrderMaterialLine.order_id == order_id
    ).order_by(BatchFilterOrderMaterialLine.seq)).scalars().all()
    out = []
    for l in lines:
        mat = db.get(Material, l.material_id) if l.material_id else None
        out.append({
            "line_id": l.line_id, "order_id": l.order_id, "seq": l.seq,
            "material_id": l.material_id,
            "material_code": mat.code if mat else None,
            "material_name": (mat.name if mat else None) or l.material_name,
            "uom": l.uom, "qty_planned": l.qty_planned,
            "stock_company_snapshot": l.stock_company_snapshot,
            "stock_workshop_snapshot": l.stock_workshop_snapshot,
        })
    return out


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

    material_lines = payload.get("lines") or []
    company_stock, workshop_stock = ({}, {})
    if material_lines:
        company_stock, workshop_stock = _filter_order_stock_snapshot(db)
        _assert_filter_order_material_stock(material_lines, company_stock, workshop_stock)

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
    for i, line in enumerate(material_lines):
        material_id = line.get("material_id")
        db.add(BatchFilterOrderMaterialLine(
            line_id=new_id(), order_id=order.order_id, seq=i,
            material_id=material_id, material_name=line.get("material_name"), uom=line.get("uom"),
            qty_planned=line.get("qty_planned") or 0.0,
            stock_company_snapshot=company_stock.get(material_id, 0.0) if material_id else None,
            stock_workshop_snapshot=workshop_stock.get(material_id, 0.0) if material_id else None,
        ))
    record_audit(db, entity_type="batch_filter_order", entity_id=order.order_id, action="create",
                actor=user, after={"order_code": order_code, "blend_mode": blend_mode,
                                   "planned_volume_hl": planned_volume})
    db.commit()
    return _filter_order_out(db, order)


def update_filter_order(db: Session, order_id: str, payload: dict, user: User) -> dict:
    """Sửa "SL dự kiến" (planned_v_dich_hl) theo từng nguồn + "SL kế hoạch" (qty_planned) theo
    từng vật tư của 1 Lệnh lọc — CHỈ khi lệnh CHƯA có Lô lọc nào tạo ra (status="planned", mirror
    đúng điều kiện của delete_filter_order — đã có lô lọc thì kế hoạch coi như đã dùng, sửa lại
    sẽ làm sai lệch lô lọc đã tạo dựa trên kế hoạch đó). Không thêm/xóa nguồn hay dòng vật tư,
    không đổi order_code/blend_mode — chỉ sửa 2 con số trên (yêu cầu người dùng 2026-09-23: "lệnh
    lọc chưa hoàn thành thì cho thêm nút sửa, để tôi sửa số lượng theo kế hoạch, số lượng vật
    tư"). Kiểm tra TRƯỚC, ghi SAU (mirror create_filter_order/dispense._plan_consume) — thiếu tồn
    ở BẤT KỲ dòng vật tư nào thì KHÔNG ghi dòng nào cả."""
    require_perm(user, "batch.execute")
    order = db.get(BatchFilterOrder, order_id)
    if not order:
        raise NotFoundError("Lệnh lọc không tồn tại.")
    _assert_unlocked(order)
    if db.execute(select(BatchFilterLot).where(BatchFilterLot.order_id == order_id)).first():
        raise DomainError("Đã có lô lọc tạo từ lệnh này — không thể sửa.")

    source_updates = payload.get("sources") or []
    sources_by_id = {s.link_id: s for s in list_filter_order_sources(db, order_id)}
    for upd in source_updates:
        src = sources_by_id.get(upd["link_id"])
        if not src:
            raise NotFoundError(f"Nguồn '{upd['link_id']}' không thuộc lệnh lọc này.")

    line_updates = payload.get("lines") or []
    lines_by_id = {l.line_id: l for l in db.execute(select(BatchFilterOrderMaterialLine).where(
        BatchFilterOrderMaterialLine.order_id == order_id)).scalars().all()}
    if line_updates:
        company_stock, workshop_stock = _filter_order_stock_snapshot(db)
        check_lines = []
        for upd in line_updates:
            line = lines_by_id.get(upd["line_id"])
            if not line:
                raise NotFoundError(f"Vật tư '{upd['line_id']}' không thuộc lệnh lọc này.")
            check_lines.append({"material_id": line.material_id, "material_name": line.material_name,
                                "qty_planned": upd["qty_planned"]})
        _assert_filter_order_material_stock(check_lines, company_stock, workshop_stock)

    for upd in source_updates:
        sources_by_id[upd["link_id"]].planned_v_dich_hl = upd["planned_v_dich_hl"]
    for upd in line_updates:
        lines_by_id[upd["line_id"]].qty_planned = upd["qty_planned"]
    # planned_volume_hl LUÔN = tổng planned_v_dich_hl mọi nguồn (mirror create_filter_order) —
    # tính lại TOÀN BỘ (không chỉ các nguồn vừa sửa) để không lệch nếu chỉ sửa 1/nhiều nguồn.
    order.planned_volume_hl = sum(s.planned_v_dich_hl or 0.0 for s in sources_by_id.values())
    record_audit(db, entity_type="batch_filter_order", entity_id=order_id, action="update", actor=user,
                after={"sources": source_updates, "lines": line_updates,
                      "planned_volume_hl": order.planned_volume_hl})
    db.commit()
    return _filter_order_out(db, order)


def finish_filter_order(db: Session, order_id: str, user: User) -> dict:
    """"Hoàn thành lệnh lọc" SỚM — vận hành CHỦ ĐỘNG dừng lọc dù CHƯA đạt đủ SL kế hoạch trừ dung
    sai (VD chỉ lọc một nửa kế hoạch rồi quyết định không lọc thêm nữa), TÁCH BIỆT hoàn toàn khỏi
    việc từng Lô lọc (BatchFilterLot) con tự bấm "Hoàn thành lọc" (finish_filtering) của riêng nó
    (yêu cầu người dùng 2026-09-23). Khi ĐÃ đạt đủ SL kế hoạch trừ dung sai, lệnh lọc TỰ ĐỘNG coi
    là hoàn thành (is_complete, xem _filter_order_status) — không cần/không cho bấm nút này nữa
    (yêu cầu người dùng 2026-09-23, làm rõ lại sau khi thấy lệnh đủ SL vẫn còn hiện ở dropdown
    "chọn lệnh lọc" do version trước đòi ĐỦ SL mới cho bấm, ngược hẳn với nhu cầu thật)."""
    require_perm(user, "batch.execute")
    order = db.get(BatchFilterOrder, order_id)
    if not order:
        raise NotFoundError("Lệnh lọc không tồn tại.")
    _assert_unlocked(order)
    if order.completed:
        raise DomainError("Lệnh lọc này đã hoàn thành rồi.")
    lots = db.execute(select(BatchFilterLot).where(BatchFilterLot.order_id == order_id)).scalars().all()
    if not lots:
        raise DomainError("Chưa có lô lọc nào tạo từ lệnh này — chưa thể hoàn thành.")
    actual = round(sum(l.volume_hl or 0.0 for l in lots), 3)
    target = round(order.planned_volume_hl - order.volume_tolerance_hl, 3)
    if actual >= target:
        raise DomainError(
            f"Thể tích lọc thực tế ({actual} hl) đã đạt kế hoạch trừ dung sai ({target} hl) "
            "— lệnh lọc tự động coi là hoàn thành, không cần bấm nút này."
        )
    if _order_tank_sources_drained(db, order_id):
        raise DomainError(
            "Tank lên men nguồn của lệnh này đã lọc hết — lệnh lọc tự động coi là hoàn thành, "
            "không cần bấm nút này."
        )
    order.completed = True
    order.completed_by = user.username
    order.completed_at = utcnow()
    record_audit(db, entity_type="batch_filter_order", entity_id=order_id, action="finish", actor=user,
                after={"actual_volume_hl": actual, "target_volume_hl": target})
    db.commit()
    db.refresh(order)
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
    for m in db.execute(select(BatchFilterOrderMaterialLine).where(
            BatchFilterOrderMaterialLine.order_id == order_id)).scalars().all():
        db.delete(m)
    db.flush()
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
        all_qc_approved = all(fl.qc_approved for fl in group)
        out[code] = {"on_hand_bbt": on_hand, "all_finished": all_finished,
                    "all_qc_approved": all_qc_approved}
    return out


def available_bbt_lines(db: Session) -> list[dict]:
    """Danh mục "Tank thành phẩm (BBT)" (ProductionLine kind=tank_bbt) kèm cờ đang chiếm dụng —
    mirror _bbt_target_blocked_by (module cũ): tank bị chặn (không chọn được làm đích mới) nếu
    CÒN mẻ chưa kết thúc (!all_finished, không thể vừa rót vừa cho mẻ khác vào cùng lúc) HOẶC
    còn tồn KHÁC 0 (dương: còn dịch CHƯA chiết hết — kể cả đã duyệt KCS hay chưa, không còn mốc
    "chỉ chặn sau khi duyệt" như bản cũ; âm: đồng hồ đo lúc lọc/chiết ra số vượt tồn phần mềm) —
    trước đây cho phép NHIỀU lô lọc (kể cả khác hẳn Lệnh lọc, khác nguồn) cùng rót vào 1 tank
    MIỄN LÀ chưa duyệt KCS, dẫn tới bug thực tế: 1 lô lọc CŨ lọc xong nhưng bị quên duyệt KCS
    (còn nguyên tồn trong tank) vẫn bị 1 Lệnh lọc HOÀN TOÀN KHÁC (nguồn tank lên men khác) rót
    tiếp vào CÙNG tank vật lý đó, trộn lẫn 2 mẻ không liên quan (yêu cầu người dùng 2026-09-26:
    "cứ tank thành phẩm đó có thể tích tồn >0 thì không cho lọc vào đó")."""
    lines = db.execute(select(ProductionLine).where(
        ProductionLine.kind == "tank_bbt", ProductionLine.active == true())).scalars().all()
    agg = _bbt_aggregate(db)
    out = []
    for l in sorted(lines, key=lambda x: x.code):
        a = agg.get(l.code)
        occupied = bool(a) and (not a["all_finished"] or abs(a["on_hand_bbt"]) > 1e-6)
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
    (all_finished) VÀ đã được KCS duyệt HẾT (all_qc_approved) — khác available_bbt_lines ở trên
    (chỉ cần còn tồn khác 0 là đã chặn nạp thêm, không cần đợi duyệt); ở đây phải chắc chắn
    100% đã duyệt mới cho chiết."""
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
    đích từ lệnh (mirror add_filter). Gọi lại được nhiều lần trên CÙNG 1 lệnh (VD rút dịch nhiều
    đợt) miễn lệnh CHƯA ở status "hoàn thành" (mirror _filter_order_status — TỰ ĐỘNG khi đủ SL kế
    hoạch trừ dung sai, HOẶC order.completed khi vận hành chủ động dừng sớm, xem finish_filter_order)
    và chưa bị tiêu thụ hạ lưu. Bắt buộc chọn `to_bbt` (tank thành phẩm đích) — dịch lọc xong phải
    biết đưa vào tank vật lý nào."""
    require_perm(user, "batch.execute")
    order = db.get(BatchFilterOrder, order_id)
    if not order:
        raise NotFoundError("Lệnh lọc không tồn tại.")
    _assert_unlocked(order)
    status = _filter_order_status(db, order)
    if status["status"] == "hoan_thanh":
        raise DomainError("Lệnh lọc này đã hoàn thành — không thể tạo thêm lô lọc.")
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
    # quality_status khởi tạo ĐÚNG theo chỉ tiêu Lọc bắt buộc thật (ON_HOLD nếu còn thiếu) thay
    # vì mặc định cứng RELEASED của cột (bug thực tế 2026-09-23: lô lọc mới tạo, chưa khai chỉ
    # tiêu nào, vẫn hiện "released" — xem qc_catalog.sync_stage_quality_status).
    qc_catalog.sync_stage_quality_status(db, "loc", "batch_filter_lot", fl.filter_lot_id)
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
    return _stamp_filter_lot_label(db, fl)


# ==================== BatchFilterLot (lô lọc) ====================

def _resync_filter_lot_status_if_stale(db: Session, fl: BatchFilterLot) -> None:
    """Tự sửa lại status nếu bị lệch so với on_hand/volume_hl thật — phòng trường hợp 1 lô lọc đã
    tách lô thành phẩm TỪ TRƯỚC khi có _sync_filter_lot_status (hoặc 1 đường mutation nào
    đó lỡ quên gọi sync), status lưu (cột DB) không tự cập nhật lại nên hiện sai vĩnh viễn dù
    tồn/tổng đã đổi thật (VD lô lọc "1": on_hand 26.99/28.1 vẫn hiện "Chờ chiết" dù đã tách lô TP
    PKG-934995 — yêu cầu người dùng 2026-09-01). Gọi ở MỌI lần đọc (list/get) để tự "chữa lành",
    không chỉ đúng lúc mutate."""
    old_status = fl.status
    _sync_filter_lot_status(fl)
    if fl.status != old_status:
        db.commit()
        db.refresh(fl)


def list_filter_lots(db: Session) -> list[BatchFilterLot]:
    lots = db.execute(select(BatchFilterLot).order_by(BatchFilterLot.created_at.desc())).scalars().all()
    for fl in lots:
        _resync_filter_lot_status_if_stale(db, fl)
    return [_stamp_filter_lot_label(db, fl) for fl in lots]


def get_filter_lot(db: Session, filter_lot_id: str) -> BatchFilterLot:
    fl = db.get(BatchFilterLot, filter_lot_id)
    if not fl:
        raise NotFoundError("Lô lọc không tồn tại.")
    _resync_filter_lot_status_if_stale(db, fl)
    return _stamp_filter_lot_label(db, fl)


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
    qc_catalog.sync_stage_quality_status(db, "loc", "batch_filter_lot", fl.filter_lot_id)
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
    return _stamp_filter_lot_label(db, fl)


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
    return _stamp_filter_lot_label(db, fl)


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
    return _stamp_filter_lot_label(db, fl)


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
    return _stamp_filter_lot_label(db, fl)


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
    2 bước tách biệt) — chuyển trạng thái "dang_loc" -> "hoan_thanh" (yêu cầu người dùng
    2026-09-01, đổi tên từ "cho_chiet" — không mở đến khái niệm chiết ở đây, tiến độ chiết ở
    riêng BatchPackLot, xem _sync_filter_lot_status, 2026-09-06). Yêu cầu mọi mẻ lọc đã "Kết
    thúc" (fl.ended_at) — chưa xong mà xác nhận thì sai."""
    require_perm(user, "batch.execute")
    fl = get_filter_lot(db, filter_lot_id)
    _assert_unlocked(fl)
    if fl.status != "dang_loc":
        raise DomainError("Lô lọc không ở trạng thái đang lọc.")
    if fl.ended_at is None:
        raise DomainError("Còn mẻ lọc chưa kết thúc — kết thúc hết các mẻ lọc trước khi xác nhận hoàn thành lọc.")
    fl.status = "hoan_thanh"
    record_audit(db, entity_type="batch_filter_lot", entity_id=filter_lot_id, action="finish_filtering", actor=user)
    db.commit()
    db.refresh(fl)
    return _stamp_filter_lot_label(db, fl)


# ==================== BatchPackLot (lô thành phẩm) ====================

PACK_LOT_STATUS_LABEL = {"dang_chiet": "Đang chiết", "chiet_1_phan": "Chiết 1 phần",
                         "chiet_het": "Chiết hết", "hoan_thanh": "Hoàn thành"}


def _pack_lot_status(db: Session, p: BatchPackLot) -> str:
    """Suy hoàn toàn từ dữ liệu (không lưu cột status riêng), mirror _tank_status/
    _sync_filter_lot_status — yêu cầu người dùng 2026-09-02: "Chiết thì bổ sung thêm cột
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
    if p.finished:
        return "hoan_thanh"
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


def finish_pack_lot(db: Session, pack_lot_id: str, user: User) -> BatchPackLot:
    """"Hoàn thành chiết" — mốc XÁC NHẬN riêng của vận hành (mirror finish_filtering — "Hoàn
    thành lọc"), TÁCH BIỆT khỏi `status` (suy tự động từ ca1/2/3 + độ rỗng tank BBT nguồn) và
    khỏi approved (Duyệt KCS)/stocked (nhập kho) — 3 luồng độc lập, làm theo thứ tự bất kỳ. Yêu
    cầu đã "Kết thúc" ít nhất 1 ca chiết (p.ended_at, tính từ ca1/2/3) — chưa chiết gì mà xác
    nhận hoàn thành thì sai (yêu cầu người dùng 2026-09-23)."""
    require_perm(user, "batch.execute")
    p = get_pack_lot(db, pack_lot_id)
    _assert_unlocked(p)
    if p.finished:
        raise DomainError("Lô thành phẩm này đã hoàn thành chiết rồi.")
    if p.ended_at is None:
        raise DomainError('Lô thành phẩm chưa có "Giờ kết thúc chiết" — kết thúc ít nhất 1 ca '
                          "chiết (nhập đủ SL + giờ kết thúc) trước khi xác nhận hoàn thành.")
    p.finished = True
    p.finished_by = user.username
    p.finished_at = utcnow()
    record_audit(db, entity_type="batch_pack_lot", entity_id=pack_lot_id, action="finish_chiet", actor=user)
    db.commit()
    db.refresh(p)
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
    _sync_filter_lot_status(fl)
    db.add(p)
    db.flush()
    qc_catalog.sync_stage_quality_status(db, "thanh_pham", "batch_pack_lot", p.pack_lot_id)
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
    (chọn thẳng filter_lot_id) vẫn giữ nguyên cho API cấp thấp, KHÔNG bắt buộc Sản phẩm/Dây
    chuyền (VD gọi nội bộ/test không cần khai 2 trường này) — bắt buộc CHỈ áp cho lối vào UI
    "Tạo lô thành phẩm (chiết)" ở đây (yêu cầu người dùng 2026-09-23: chọn đúng 1 Sản phẩm + 1
    Dây chuyền là bắt buộc, không được để trống/chọn nhiều)."""
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
    finished_product_id = (payload.get("finished_product_id") or "").strip()
    if not finished_product_id:
        raise DomainError("Chọn sản phẩm để chiết.")
    line = (payload.get("line") or "").strip()
    if not line:
        raise DomainError("Chọn dây chuyền để chiết.")
    payload = {**payload, "from_bbt": from_bbt, "finished_product_id": finished_product_id, "line": line}
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
    _sync_filter_lot_status(fl)
    before_qty = p.qty
    p.qty = qty
    record_audit(db, entity_type="batch_pack_lot", entity_id=pack_lot_id, action="update_qty",
                actor=user, before={"qty": before_qty}, after={"qty": qty})
    db.commit()
    db.refresh(p)
    return _stamp_pack_lot_status(db, p)


def update_pack_lot_pack_date(db: Session, pack_lot_id: str, pack_date, user: User) -> BatchPackLot:
    """Sửa giờ bắt đầu chiết (bấm nhầm/nhập bổ sung sau)."""
    require_perm(user, "batch.execute")
    p = get_pack_lot(db, pack_lot_id)
    _assert_unlocked(p)
    before_date = p.pack_date.isoformat() if p.pack_date else None
    p.pack_date = pack_date
    record_audit(db, entity_type="batch_pack_lot", entity_id=pack_lot_id, action="update_pack_date",
                actor=user, before={"pack_date": before_date}, after={"pack_date": pack_date.isoformat()})
    db.commit()
    db.refresh(p)
    return _stamp_pack_lot_status(db, p)


def update_pack_lot_shifts(db: Session, pack_lot_id: str, payload: dict, user: User) -> BatchPackLot:
    """Ghi SL chiết theo ca 1/2/3 + giờ bắt đầu/kết thúc từng ca — mirror finish_bottle's
    ca1/ca2/ca3 (module Nấu-Lọc-Chiết cũ), sửa lại được nhiều lần (kể cả CHỈ 1 ca — `payload` chỉ
    cần có đúng 3 khóa của ca đó, dùng cho nút Lưu RIÊNG từng ca ở UI). Trạng thái (dang_chiet/
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
    now = utcnow()
    for n in (1, 2, 3):
        keys = (f"ca{n}_qty", f"ca{n}_start_at", f"ca{n}_end_at")
        if not any(k in payload for k in keys):
            continue
        before = tuple(getattr(p, k) for k in keys)
        for k in keys:
            if k in payload:
                setattr(p, k, payload[k])
        after = tuple(getattr(p, k) for k in keys)
        if not any(v is not None for v in after):
            setattr(p, f"ca{n}_by", None)
            setattr(p, f"ca{n}_at", None)
        elif after != before or getattr(p, f"ca{n}_at") is None:
            setattr(p, f"ca{n}_by", user.username)
            setattr(p, f"ca{n}_at", now)
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
    _sync_filter_lot_status(fl)
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
    # with_for_update(): khóa lô TP trước khi ghi approved — 2 lần bấm "Duyệt KCS" gần như đồng
    # thời đều có thể qua được check "p.approved" ở trên rồi cùng ghi audit (cùng lớp race đã
    # sửa cho split/update_qty, 2026-09-15).
    p = db.execute(select(BatchPackLot).where(
        BatchPackLot.pack_lot_id == pack_lot_id).with_for_update()).scalar_one()
    if p.approved:
        raise DomainError("Lô thành phẩm này đã được duyệt.")
    p.approved = True
    p.approved_by = user.username
    p.approved_at = utcnow()
    record_audit(db, entity_type="batch_pack_lot", entity_id=pack_lot_id, action="approve", actor=user)
    db.commit()
    return {"pack_lot_id": pack_lot_id, "approved": True, "qc_has_fail": status["has_fail"]}


def save_pack_lot_allocations(db: Session, pack_lot_id: str, allocations: list[dict], user: User) -> BatchPackLot:
    """Nhân viên chiết khai phân bổ quy cách đóng gói pallet (spec_id + số lượng) — LƯU NGAY
    trong lúc chiết, cùng quyền `batch.execute` như update_pack_lot_shifts, KHÔNG chờ Duyệt KCS
    hay Giám đốc/Phó GĐ SX duyệt nhập kho (yêu cầu người dùng 2026-09-20: "hiện ra luôn để nhân
    viên chiết thực hiện"). Mỗi dòng lưu lại rõ AI vừa lưu (saved_by/saved_at) — TÁCH biệt với
    ai đã bấm "Duyệt nhập kho TP" cho ĐÚNG dòng đó (released_by/released_at, xem
    release_pack_lot_allocation — mỗi dòng/quy cách giờ có nút duyệt RIÊNG, yêu cầu người dùng
    2026-09-20: "Mỗi quy cách sẽ có 1 nút duyệt nhập kho TP").

    KHÔNG chặn nếu tổng chưa khớp ca_total ở đây (SL theo ca có thể còn đang khai tiếp) — validate
    khớp đúng tổng không còn áp dụng cứng ở release (release giờ theo TỪNG dòng độc lập), thay
    vào đó dùng pack_lot_unstocked_remainder() để CẢNH BÁO phần còn thiếu.

    Dòng đã released=True là BẤT BIẾN (đã tạo pallet thật) — nếu client không gửi lại đúng dòng
    đó (mất do state cũ) thì tự khôi phục lại nguyên trạng; nếu gửi lại NHƯNG đổi spec/số lượng
    thì chặn cứng (không cho sửa dữ liệu đã phát sinh pallet)."""
    require_perm(user, "batch.execute")
    p = get_pack_lot(db, pack_lot_id)
    _assert_unlocked(p)
    existing_by_id = {r["row_id"]: r for r in (p.pack_allocations or []) if r.get("row_id")}
    released_ids = {rid for rid, r in existing_by_id.items() if r.get("released")}
    incoming = [a for a in (allocations or []) if a.get("spec_id") and float(a.get("quantity") or 0) > 0]
    if incoming and not p.finished_product_id:
        raise DomainError("Lô thành phẩm chưa gán Sản phẩm (SKU) — không thể chọn quy cách đóng gói pallet.")
    now = utcnow()
    seen_ids = set()
    new_rows = []
    for a in incoming:
        rid = a.get("row_id")
        if rid and rid in released_ids:
            existing = existing_by_id[rid]
            if (abs(float(a.get("quantity") or 0) - float(existing["quantity"])) > 1e-6
                    or a.get("spec_id") != existing["spec_id"]):
                raise DomainError("Dòng đã Duyệt nhập kho thành phẩm — không thể sửa.")
            new_rows.append(existing)
            seen_ids.add(rid)
            continue
        existing = existing_by_id.get(rid) if rid else None
        # Dòng CHƯA release nhưng KHÔNG hề đổi gì (client luôn gửi lại TOÀN BỘ rows mỗi lần Lưu,
        # kể cả các dòng không đang sửa) — giữ nguyên saved_by/saved_at cũ thay vì đóng dấu người
        # vừa bấm Lưu cho MỌI dòng, kể cả dòng người đó không hề động vào (yêu cầu người dùng
        # 2026-09-25: "sửa 1 dòng mà cả 2 đều đổi tên lưu bởi/ngày giờ").
        if (existing and existing.get("spec_id") == a.get("spec_id")
                and abs(float(existing.get("quantity") or 0) - float(a.get("quantity") or 0)) < 1e-6
                and (existing.get("loc_id") or None) == (a.get("loc_id") or None)):
            new_rows.append(existing)
            seen_ids.add(rid)
            continue
        spec = db.get(PackingSpec, a["spec_id"])
        if not spec:
            raise NotFoundError("Quy cách đóng gói không tồn tại.")
        if spec.finished_product_id != p.finished_product_id:
            raise DomainError(f"Quy cách '{spec.code}' không thuộc SKU của lô thành phẩm này.")
        new_rows.append({
            "row_id": rid or new_id(), "spec_id": a["spec_id"], "quantity": float(a["quantity"]),
            "saved_by": user.username, "saved_at": now.isoformat(),
            "released": False, "released_by": None, "released_at": None, "pallet_codes": [],
            # Lưu lại vị trí kho đã chọn (chưa Duyệt nhập kho TP nên chưa có `location` thật) —
            # trước đây chỉ giữ ở state trình duyệt, mất khi tải lại trang khiến người dùng tưởng
            # "đã lưu vị trí" nhưng biến mất (yêu cầu người dùng 2026-09-25).
            "loc_id": a.get("loc_id"),
        })
        if rid:
            seen_ids.add(rid)
    for rid in released_ids - seen_ids:
        new_rows.append(existing_by_id[rid])
    p.pack_allocations = new_rows
    record_audit(db, entity_type="batch_pack_lot", entity_id=pack_lot_id, action="save_pack_allocations",
                actor=user, after={"allocations": new_rows})
    db.commit()
    db.refresh(p)
    return p


def release_pack_lot_allocation(db: Session, pack_lot_id: str, row_id: str, user: User, loc_id: str) -> dict:
    """Vận hành (hoặc Giám đốc/Phó GĐ Sản xuất - Kỹ thuật) duyệt nhập kho THEO TỪNG DÒNG phân
    bổ/quy cách — mirror routers/brewing.py::approve_bottle (module Nấu-Lọc-Chiết cũ; module đó
    đã THÁO khỏi WMS, Lô thành phẩm là nơi thay thế duy nhất tạo hàng nhập kho từ sản xuất),
    nhưng áp dụng RIÊNG cho 1 dòng/quy cách thay vì cả lô 1 lần (yêu cầu người dùng 2026-09-20:
    "Mỗi quy cách sẽ có 1 nút duyệt nhập kho TP") — vẫn yêu cầu đã Duyệt KCS (p.approved) như
    trước, đây là chốt chặn chất lượng thật sự, không phải quyền `production.release_to_wms`
    (quyền đó giờ vận hành cũng có — yêu cầu người dùng 2026-09-26: "vận hành được quyền nhập,
    khi KCS đã duyệt" — chỉ bớt 1 bước chờ Giám đốc SX duyệt THAO TÁC KHO thuần túy, KHÔNG bỏ
    qua bước KCS), chỉ khác thứ tự "duyệt" giờ tính theo dòng. Lưu released_by/released_at RIÊNG cho dòng đó — khác
    saved_by/saved_at (ai lưu phân bổ, xem save_pack_lot_allocations). Tạo `quantity //
    spec.units_per_pallet` pallet đầy + 1 pallet lẻ nếu còn dư, giống đúng logic release toàn
    lô trước đây, chỉ khác phạm vi là 1 dòng.

    `loc_id` BẮT BUỘC (yêu cầu người dùng 2026-09-20: "không gán vị trí thì không cho duyệt") —
    khác trước đây pallet tạo ra ở trạng thái "building" không vị trí, chờ Kho TP tự "Cất" sau.
    Giờ TẤT CẢ pallet của dòng này được "Cất" thẳng vào ĐÚNG 1 vị trí đã chọn ngay khi duyệt
    (status="stored" luôn, không qua "building"/không vị trí nữa) — KHÔNG gọi thẳng
    wms_svc.putaway() vì hàm đó tự đòi quyền warehouse.issue (người duyệt ở đây chỉ chắc chắn có
    production.release_to_wms), nên kiểm tra sức chứa + gán vị trí NGAY TẠI ĐÂY, không qua lớp
    quyền của putaway. Kiểm tra sức chứa 1 LẦN cho TOÀN BỘ số pallet dòng này sẽ tạo ra (không
    phải từng pallet — nếu không đủ chỗ thì KHÔNG tạo pallet nào cả, mirror pattern "kiểm tra
    trước, xuất sau" đã dùng ở warehouse.py::fulfill_request_line)."""
    require_perm(user, "production.release_to_wms")
    p = get_pack_lot(db, pack_lot_id)
    _assert_unlocked(p)
    if not p.approved:
        raise DomainError("Chưa Duyệt KCS — không thể nhập kho thành phẩm.")
    if not p.finished_product_id:
        raise DomainError("Lô thành phẩm chưa gán Sản phẩm (SKU) — không thể chọn quy cách đóng gói pallet.")
    if not loc_id:
        raise DomainError("Chưa chọn vị trí kho — không thể duyệt nhập kho thành phẩm.")
    loc = db.get(WmsLocation, loc_id)
    if not loc:
        raise NotFoundError("Vị trí kho không tồn tại.")
    rows = list(p.pack_allocations or [])
    idx = next((i for i, r in enumerate(rows) if r.get("row_id") == row_id), None)
    if idx is None:
        raise NotFoundError("Dòng phân bổ không tồn tại.")
    if rows[idx].get("released"):
        raise DomainError("Dòng này đã được Duyệt nhập kho thành phẩm rồi.")
    spec = db.get(PackingSpec, rows[idx]["spec_id"])
    if not spec:
        raise NotFoundError("Quy cách đóng gói không tồn tại.")
    if spec.finished_product_id != p.finished_product_id:
        raise DomainError(f"Quy cách '{spec.code}' không thuộc SKU của lô thành phẩm này.")
    # with_for_update(): khóa lô TP trước khi ghi — 2 lần bấm gần như đồng thời cùng dòng đều có
    # thể qua check "released" ở trên rồi cùng tạo pallet trùng (cùng lớp race đã sửa nhiều nơi
    # khác trong module này, 2026-09-15/20).
    p = db.execute(select(BatchPackLot).where(
        BatchPackLot.pack_lot_id == pack_lot_id).with_for_update()).scalar_one()
    rows = list(p.pack_allocations or [])
    if rows[idx].get("released"):
        raise DomainError("Dòng này đã được Duyệt nhập kho thành phẩm rồi.")
    finished_product = db.get(FinishedProduct, p.finished_product_id)
    pack_size = finished_product.pack_size if finished_product else 24
    product_name = finished_product.code if finished_product else p.pack_lot_code
    lot_code = p.lot_no or p.pack_lot_code
    qty_int = int(round(float(rows[idx]["quantity"])))
    full_pallets, remainder_units = divmod(qty_int, spec.units_per_pallet)
    case_counts = [spec.units_per_pallet] * full_pallets
    if remainder_units > 0:
        case_counts.append(remainder_units)
    # Chặn sớm nếu số lượng nhập nhầm sinh ra quá nhiều pallet trong 1 lần duyệt (mỗi pallet là
    # 1 db.commit() + N dòng Case riêng — hàng nghìn pallet/lần khiến request treo/timeout, trả
    # về lỗi 500 khó hiểu thay vì thông báo rõ ràng). SL thật của 1 dòng/ca không bao giờ cần đến
    # mức này — đây gần như chắc chắn là nhập nhầm số lượng.
    if len(case_counts) > 500:
        raise DomainError(
            f"Số lượng {qty_int} sẽ tạo {len(case_counts)} pallet trong 1 lần duyệt — vượt quá "
            f"giới hạn an toàn (500 pallet/lần). Kiểm tra lại số lượng đã nhập cho dòng này.")
    used = db.execute(select(func.count(Pallet.pallet_id)).where(
        Pallet.location_id == loc.loc_id, Pallet.status == "stored")).scalar() or 0
    if used + len(case_counts) > loc.capacity:
        raise DomainError(
            f"Vị trí {loc.code} không đủ chỗ cho {len(case_counts)} pallet "
            f"(còn trống {max(loc.capacity - used, 0)}/{loc.capacity}).")
    pallet_codes = []
    for case_count in case_counts:
        pallet = wms_svc._build_pallet(db, {
            "product": product_name, "lot_code": lot_code,
            "case_count": case_count, "units_per_case": pack_size,
        }, user, source="production")
        pallet.location_id = loc.loc_id
        pallet.status = "stored"
        genealogy.add_edge(db, from_type="batch_pack_lot", from_id=pack_lot_id, to_type="pallet",
                           to_id=pallet.pallet_id, relation="nhập kho", quantity=case_count, uom="case")
        pallet_codes.append(pallet.pallet_code)
    row = dict(rows[idx])
    row["released"] = True
    row["released_by"] = user.username
    row["released_at"] = utcnow().isoformat()
    row["pallet_codes"] = pallet_codes
    row["location"] = loc.code
    rows[idx] = row
    p.pack_allocations = rows
    if not p.stocked and p.unstocked_remainder <= 0:
        p.stocked = True
        p.stocked_by = user.username
        p.stocked_at = utcnow()
    record_audit(db, entity_type="batch_pack_lot", entity_id=pack_lot_id, action="release_pack_allocation",
                actor=user, after={"row_id": row_id, "spec_id": row["spec_id"], "quantity": row["quantity"],
                                   "pallet_codes": pallet_codes, "location": loc.code})
    db.commit()
    return {"pack_lot_id": pack_lot_id, "row_id": row_id, "released": True,
            "pallet_codes": pallet_codes, "stocked": p.stocked, "location": loc.code}


# ==================== NVL dùng cho lô thành phẩm (chiết) ====================
# Mirror add_bottle_material/update/delete (routers/brewing.py:1935-2015, module Nấu-Lọc-Chiết
# cũ) — trừ/hoàn tồn kho thật qua warehouse_svc.issue()/undo_issue(), giữ movement_id để hoàn
# kho khi sửa/xóa.

def list_pack_lot_materials(db: Session, pack_lot_id: str) -> list[BatchPackLotMaterialUsage]:
    return db.execute(select(BatchPackLotMaterialUsage).where(
        BatchPackLotMaterialUsage.pack_lot_id == pack_lot_id)).scalars().all()


def suggest_pack_lot_material(db: Session, pack_lot_id: str, material_id: str, quantity: float) -> dict:
    """Xem trước lô sẽ dùng (FIFO, Kho phân xưởng, tại đúng "Ngày cấp" = ended_at) cho 1 vật tư +
    số lượng SẮP thêm vào lô thành phẩm — mirror suggest_filter_lot_material (yêu cầu người dùng
    2026-09-16)."""
    p = get_pack_lot(db, pack_lot_id)
    if p.ended_at is None:
        raise DomainError('Lô thành phẩm chưa có "Giờ kết thúc chiết" — chưa có "Ngày cấp" để tính tồn.')
    material = db.get(Material, material_id)
    if not material:
        raise NotFoundError("Vật tư không tồn tại.")
    fefo_lots = dispense_svc._workshop_fefo_lots(db, material.code, p.ended_at)
    picks, remaining = [], round(quantity, 4)
    for lot in fefo_lots:
        if remaining <= 1e-9:
            break
        take = min(remaining, dispense_svc._lot_avail_qty(lot))
        if take <= 0:
            continue
        picks.append({"lot_id": lot.lot_id, "lot_code": lot.lot_code, "quantity": round(take, 4),
                     "uom": lot.uom, "expiry": lot.expiry.isoformat() if lot.expiry else None})
        remaining = round(remaining - take, 4)
    return {"supply_date": p.ended_at, "picks": picks,
           "shortfall": round(remaining, 4) if remaining > 1e-6 else 0.0}


def add_pack_lot_material(db: Session, pack_lot_id: str, payload: dict, user: User) -> list[BatchPackLotMaterialUsage]:
    """Ghi NVL dùng cho 1 lô thành phẩm — chọn theo VẬT TƯ (material_id), hệ thống TỰ CHỌN lô
    theo FIFO tại đúng thời điểm "Ngày cấp" = BatchPackLot.ended_at (mirror
    services/dispense.py::_plan_consume — dùng CHUNG logic FEFO/as_of/all-or-nothing với Nấu,
    yêu cầu người dùng 2026-09-16). `lot_id` (tuỳ chọn) chỉ dùng khi cố ý chọn khác lô FIFO gợi ý
    (bắt buộc `reason`). Không đủ tồn kho phân xưởng TẠI THỜI ĐIỂM `ended_at` cho đủ `quantity`
    thì CHẶN HẲN (all-or-nothing, không trừ dở dang) — _plan_consume tự raise. 1 lần gọi có thể
    tạo NHIỀU dòng usage (1 dòng/lô thực sự dùng, nếu 1 lô không đủ phải lấy tiếp lô sau)."""
    require_perm(user, "batch.execute")
    p = get_pack_lot(db, pack_lot_id)
    _assert_unlocked(p)
    supply_date = p.ended_at
    if supply_date is None:
        raise DomainError('Lô thành phẩm chưa có "Giờ kết thúc chiết" (ended_at, tính từ SL chiết '
                          "theo ca) — ghi đủ SL + giờ kết thúc ít nhất 1 ca trước khi thêm nguyên liệu.")
    data = dict(payload)
    material_id = data.get("material_id")
    if not material_id:
        raise DomainError("Chọn nguyên liệu từ tồn kho Kho phân xưởng.")
    material = db.get(Material, material_id)
    if not material:
        raise NotFoundError("Vật tư không tồn tại.")
    quantity = data["quantity"]
    reason = (data.get("reason") or "").strip() or None
    plan, fifo_ok = dispense_svc._plan_consume(db, material.code, quantity, picked_lot_id=data.get("lot_id"),
                                               reason=reason, as_of=supply_date)
    rows = []
    for lot, take in plan:
        result = warehouse_svc.issue(db, lot.lot_id, take, user, mode="tu_do",
                                     reason=f"Dùng cho lô thành phẩm {p.pack_lot_code}",
                                     ref_doc=p.pack_lot_code, skip_perm_check=True, issued_at=supply_date)
        u = BatchPackLotMaterialUsage(
            usage_id=new_id(), pack_lot_id=pack_lot_id, lot_id=lot.lot_id, movement_id=result["movement_id"],
            material_name=material.name, lot_pm=lot.lot_code, lot_date=lot.created_at, supply_date=supply_date,
            fifo_ok=fifo_ok, reason=reason, quantity=take, uom=lot.uom, created_at=utcnow(),
            created_by=user.username,
        )
        db.add(u)
        rows.append(u)
    record_audit(db, entity_type="batch_pack_lot", entity_id=pack_lot_id, action="material_add", actor=user,
                after={"material_name": material.name, "quantity": quantity, "lots": [r.lot_pm for r in rows]})
    db.commit()
    for u in rows:
        db.refresh(u)
    return rows


def delete_pack_lot_material(db: Session, usage_id: str, user: User) -> None:
    require_perm(user, "batch.execute")
    u = db.get(BatchPackLotMaterialUsage, usage_id)
    if not u:
        raise NotFoundError("Dòng nguyên liệu không tồn tại.")
    p = get_pack_lot(db, u.pack_lot_id)
    _assert_unlocked(p)
    # Mirror đúng chặn của delete_pack_lot (xóa cả lô) — lô thành phẩm đã KCS duyệt thì hồ sơ
    # NVL dùng cho nó không còn được coi là "khai nhầm" nữa, dù chỉ xóa/sửa 1 dòng (yêu cầu
    # người dùng 2026-09-21: "đã dùng rồi thì không thể xóa, hoàn tác, hay sửa").
    if p.approved:
        raise DomainError("Lô thành phẩm đã được KCS duyệt — không thể sửa/xóa nguyên liệu.")
    if u.movement_id:
        warehouse_svc.undo_issue(db, u.movement_id, user, strict=False, skip_perm_check=True)
    before = {"material_name": u.material_name, "lot_pm": u.lot_pm, "quantity": u.quantity, "uom": u.uom}
    db.delete(u)
    record_audit(db, entity_type="batch_pack_lot", entity_id=u.pack_lot_id, action="material_delete",
                 actor=user, before=before)
    db.commit()


# ==================== NVL dùng cho Lô lọc — mirror BatchPackLotMaterialUsage trên ====================

def _assert_filter_material_addable(db: Session, filter_lot: BatchFilterLot) -> None:
    """Lô lọc nào MỞ (tạo) trước phải được thêm NVL trước — mirror services/dispense.py::
    _assert_dispensable áp dụng cho Nấu, nay áp dụng thêm cho Lọc (yêu cầu người dùng
    2026-09-15: "cấp liệu thì mẻ sản xuất trước phải cấp trước... áp dụng cho Lọc luôn").
    Dùng `created_at` làm mốc "bắt đầu" (Lô lọc không có trường start_at riêng như Mẻ nấu —
    tạo lô lọc chính là lúc THỰC SỰ mở ra để lọc, khác Mẻ nấu có thể tạo trước rồi mới khai
    "Bắt đầu" sau). Chỉ xét lô lọc ĐANG LỌC (status="dang_loc") — lô đã "Hoàn thành lọc" không
    còn "chiếm hàng" (mirror chỉ xét RUNNING/HELD ở Nấu, không xét COMPLETED/CLOSED/CANCELLED).
    Chỉ cần lô đó đã thêm NVL ÍT NHẤT 1 lần (không cần đủ hết) là coi như "đến lượt", không
    chặn lô sau nữa."""
    earlier = db.execute(select(BatchFilterLot).where(
        BatchFilterLot.status == "dang_loc",
        BatchFilterLot.filter_lot_id != filter_lot.filter_lot_id,
        BatchFilterLot.created_at < filter_lot.created_at,
    ).order_by(BatchFilterLot.created_at.asc())).scalars().all()
    if not earlier:
        return
    earlier_ids = [f.filter_lot_id for f in earlier]
    has_usage = set(db.execute(select(BatchFilterLotMaterialUsage.filter_lot_id).where(
        BatchFilterLotMaterialUsage.filter_lot_id.in_(earlier_ids)).distinct()).scalars().all())
    blocking = [f for f in earlier if f.filter_lot_id not in has_usage]
    if not blocking:
        return
    codes = ", ".join(f.filter_lot_code for f in blocking[:5])
    raise DomainError(f"Lô lọc {codes} mở trước lô này và chưa thêm nguyên liệu lần nào — "
                      "thêm nguyên liệu cho (các) lô đó trước.")


def list_filter_lot_materials(db: Session, filter_lot_id: str) -> list[BatchFilterLotMaterialUsage]:
    return db.execute(select(BatchFilterLotMaterialUsage).where(
        BatchFilterLotMaterialUsage.filter_lot_id == filter_lot_id)).scalars().all()


def suggest_filter_lot_material(db: Session, filter_lot_id: str, material_id: str, quantity: float) -> dict:
    """Xem trước lô sẽ dùng (FIFO, Kho phân xưởng, tại đúng "Ngày cấp" = ended_at) cho 1 vật tư +
    số lượng SẮP thêm — CHỈ TÍNH, không trừ tồn (mirror services/dispense.py::suggest_dispense) —
    cho biết "sẽ lấy lô nào" TRƯỚC khi bấm "+ Thêm" thật (yêu cầu người dùng 2026-09-16: "hiện
    tại không biết lấy lô nào khi chọn vật tư trong list"). Không raise khi thiếu tồn — trả
    `shortfall` > 0 để frontend tự cảnh báo/chặn nút "+ Thêm" (khác add_filter_lot_material vốn
    chặn hẳn bằng exception khi submit thật)."""
    fl = get_filter_lot(db, filter_lot_id)
    if fl.ended_at is None:
        raise DomainError('Lô lọc chưa "Kết thúc" mẻ lọc nào — chưa có "Ngày cấp" để tính tồn.')
    material = db.get(Material, material_id)
    if not material:
        raise NotFoundError("Vật tư không tồn tại.")
    fefo_lots = dispense_svc._workshop_fefo_lots(db, material.code, fl.ended_at)
    picks, remaining = [], round(quantity, 4)
    for lot in fefo_lots:
        if remaining <= 1e-9:
            break
        take = min(remaining, dispense_svc._lot_avail_qty(lot))
        if take <= 0:
            continue
        picks.append({"lot_id": lot.lot_id, "lot_code": lot.lot_code, "quantity": round(take, 4),
                     "uom": lot.uom, "expiry": lot.expiry.isoformat() if lot.expiry else None})
        remaining = round(remaining - take, 4)
    return {"supply_date": fl.ended_at, "picks": picks,
           "shortfall": round(remaining, 4) if remaining > 1e-6 else 0.0}


def add_filter_lot_material(db: Session, filter_lot_id: str, payload: dict, user: User) -> list[BatchFilterLotMaterialUsage]:
    """Ghi NVL dùng cho 1 lô lọc — chọn theo VẬT TƯ (material_id), hệ thống TỰ CHỌN lô theo FIFO
    tại đúng thời điểm "Ngày cấp" = BatchFilterLot.ended_at (mirror services/dispense.py::
    _plan_consume — dùng CHUNG logic FEFO/as_of/all-or-nothing với Nấu, yêu cầu người dùng
    2026-09-16). `lot_id` (tuỳ chọn) chỉ dùng khi cố ý chọn khác lô FIFO gợi ý (bắt buộc
    `reason`). Không đủ tồn kho phân xưởng TẠI THỜI ĐIỂM `ended_at` cho đủ `quantity` thì CHẶN
    HẲN (all-or-nothing) — _plan_consume tự raise. 1 lần gọi có thể tạo NHIỀU dòng usage (1
    dòng/lô thực sự dùng, nếu 1 lô không đủ phải lấy tiếp lô sau)."""
    require_perm(user, "batch.execute")
    fl = get_filter_lot(db, filter_lot_id)
    _assert_unlocked(fl)
    _assert_filter_material_addable(db, fl)
    supply_date = fl.ended_at
    if supply_date is None:
        raise DomainError('Lô lọc chưa "Kết thúc" mẻ lọc nào (ended_at) — kết thúc ít nhất 1 mẻ '
                          "lọc trước khi thêm nguyên liệu.")
    data = dict(payload)
    material_id = data.get("material_id")
    if not material_id:
        raise DomainError("Chọn nguyên liệu từ tồn kho Kho phân xưởng.")
    material = db.get(Material, material_id)
    if not material:
        raise NotFoundError("Vật tư không tồn tại.")
    quantity = data["quantity"]
    reason = (data.get("reason") or "").strip() or None
    plan, fifo_ok = dispense_svc._plan_consume(db, material.code, quantity, picked_lot_id=data.get("lot_id"),
                                               reason=reason, as_of=supply_date)
    rows = []
    for lot, take in plan:
        result = warehouse_svc.issue(db, lot.lot_id, take, user, mode="tu_do",
                                     reason=f"Dùng cho lô lọc {fl.filter_lot_code}",
                                     ref_doc=fl.filter_lot_code, skip_perm_check=True, issued_at=supply_date)
        u = BatchFilterLotMaterialUsage(
            usage_id=new_id(), filter_lot_id=filter_lot_id, lot_id=lot.lot_id, movement_id=result["movement_id"],
            material_name=material.name, lot_pm=lot.lot_code, lot_date=lot.created_at, supply_date=supply_date,
            fifo_ok=fifo_ok, reason=reason, quantity=take, uom=lot.uom, created_at=utcnow(),
            created_by=user.username,
        )
        db.add(u)
        rows.append(u)
    record_audit(db, entity_type="batch_filter_lot", entity_id=filter_lot_id, action="material_add", actor=user,
                after={"material_name": material.name, "quantity": quantity, "lots": [r.lot_pm for r in rows]})
    db.commit()
    for u in rows:
        db.refresh(u)
    return rows


def delete_filter_lot_material(db: Session, usage_id: str, user: User) -> None:
    require_perm(user, "batch.execute")
    u = db.get(BatchFilterLotMaterialUsage, usage_id)
    if not u:
        raise NotFoundError("Dòng nguyên liệu không tồn tại.")
    fl = get_filter_lot(db, u.filter_lot_id)
    _assert_unlocked(fl)
    # Mirror đúng chặn của delete_filter_lot (xóa cả lô) — lô lọc đã KCS duyệt, hoặc đã có lô
    # thành phẩm tách từ lô lọc này, thì hồ sơ NVL dùng cho nó không còn được coi là "khai nhầm"
    # nữa, dù chỉ xóa/sửa 1 dòng (yêu cầu người dùng 2026-09-21).
    if fl.qc_approved:
        raise DomainError("Lô lọc này đã được KCS duyệt — không thể sửa/xóa nguyên liệu.")
    if db.execute(select(BatchPackLot).where(BatchPackLot.filter_lot_id == u.filter_lot_id)).first():
        raise DomainError("Đã có lô thành phẩm tách từ lô lọc này — không thể sửa/xóa nguyên liệu.")
    if u.movement_id:
        warehouse_svc.undo_issue(db, u.movement_id, user, strict=False, skip_perm_check=True)
    before = {"material_name": u.material_name, "lot_pm": u.lot_pm, "quantity": u.quantity, "uom": u.uom}
    db.delete(u)
    record_audit(db, entity_type="batch_filter_lot", entity_id=u.filter_lot_id, action="material_delete",
                 actor=user, before=before)
    db.commit()
