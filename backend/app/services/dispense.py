"""Cấp phát nguyên liệu (dispense) + backflush (tài liệu §7.4, §7.6).

- dispense: cấp liệu cho mẻ theo lô cụ thể HOẶC tự chọn lô theo FEFO (hết hạn trước
  xuất trước), tái dùng batches.consume_lot (trừ tồn + genealogy + chặn vượt định mức),
  bổ sung: chặn lô hết hạn, tách nhu cầu qua nhiều lô.
- backflush: tự khấu trừ NVL theo định mức BOM × tỉ lệ sản lượng đã sản xuất, trừ phần
  đã tiêu thụ trước đó (tránh trừ trùng), tự chọn lô FEFO.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import BatchState, GenealogyRelation, LotStatus, Role, new_id, utcnow
from ..errors import DomainError, NotFoundError
from ..models.batches import BatchExecution
from ..models.master import Material
from ..models.materials import GenealogyEdge, MaterialLot
from ..models.materials_ext import Dispense, DispenseLine
from ..security import User, require_role
from . import batches as batch_svc
from . import bom
from . import warehouse as warehouse_svc


def _is_expired(lot: MaterialLot) -> bool:
    if not lot.expiry:
        return False
    exp = lot.expiry
    now = utcnow()
    if exp.tzinfo is None:
        now = now.replace(tzinfo=None)
    return exp < now


# Mốc chốt mở rộng điều kiện #2 (bên dưới) sang các trạng thái planned/ready/completed/closed —
# CỐ Ý là hằng số 1 lần (KHÔNG tính theo "hôm nay" của utcnow() tại thời điểm hàm chạy, vì như
# vậy mốc sẽ tự trôi tới mỗi ngày, khiến các mẻ tạo hôm qua dần dần cũng bị coi là "mẻ cũ" được
# miễn) — chỉ mẻ có `start_at` TỪ mốc này trở đi mới có thể là "mẻ trước" chặn mẻ khác qua các
# trạng thái mới thêm; mẻ cũ trước mốc này (rất nhiều mẻ closed/completed từ trước không hề cấp
# liệu qua hệ thống, xem lịch sử) được miễn hẳn, tránh khóa cứng toàn bộ tính năng Cấp liệu cho
# mọi mẻ về sau (yêu cầu người dùng 2026-09-16: "tính từ hôm nay, thêm cho tôi cả ready vào nữa").
_ORDER_RULE_EXTENDED_STATES_SINCE = datetime(2026, 9, 15, 17, 0, 0, tzinfo=timezone.utc)  # 2026-09-16 00:00 giờ VN


def _assert_dispensable(db: Session, batch: BatchExecution) -> None:
    """2 điều kiện bắt buộc trước khi cấp liệu (áp dụng cho MỌI cách cấp — Cấp 1 vật tư/Áp dụng
    gợi ý/Backflush/tăng Thực tế qua adjust_actual; KHÔNG áp dụng cho nhánh HOÀN LẠI của
    adjust_actual — hoàn lại không "lấy" thêm tồn nên không cần xếp hàng) — yêu cầu người dùng
    2026-09-15:

    1. Mẻ phải có `start_at` (thời điểm bắt đầu nấu) — tồn kho phân xưởng dùng để đối chiếu
       (xem _workshop_fefo_lots's `as_of`) tính TẠI thời điểm này, không có mốc thì không tính
       được, cũng không có cơ sở xác định "hàng nào đã về trước lúc mẻ bắt đầu".
    2. Mẻ nào bắt đầu nấu TRƯỚC phải được cấp liệu TRƯỚC: chặn nếu còn mẻ khác có `start_at`
       sớm hơn mà CHƯA cấp liệu lần nào (0 dòng DispenseLine thật sự) — đảm bảo tồn phân xưởng
       được nhường đúng thứ tự, mẻ sau không "chen ngang" trước khi mẻ cần trước kịp lấy phần
       của mình. Chỉ cần mẻ trước đã cấp ÍT NHẤT 1 vật tư (không cần đủ 100% định mức) là coi
       như đã "đến lượt", không chặn mẻ sau nữa. Áp dụng cho mẻ khác đang running/held (như cũ)
       VÀ CẢ planned/ready/completed/closed (yêu cầu người dùng 2026-09-16: mẻ "sắp chạy"/"đã
       xong" mà lỡ quên cấp liệu vẫn phải xử lý trước, không chỉ mẻ đang chạy dở) — nhưng CHỈ mẻ
       "mẻ trước" có `start_at >= _ORDER_RULE_EXTENDED_STATES_SINCE` mới tính qua 4 trạng thái
       mới này, tránh mẻ cũ (closed/completed từ trước, không đi qua cấp liệu module này) khóa
       cứng vĩnh viễn mọi mẻ cấp liệu về sau. cancelled KHÔNG bao giờ tính (mẻ coi như chưa từng
       xảy ra)."""
    if batch.start_at is None:
        raise DomainError("Mẻ chưa có thời điểm bắt đầu nấu — không thể cấp liệu. "
                          "Vào Mẻ sản xuất nhập thời điểm bắt đầu trước.")
    always_states = [BatchState.RUNNING.value, BatchState.HELD.value]
    extended_states = [BatchState.PLANNED.value, BatchState.READY.value,
                       BatchState.COMPLETED.value, BatchState.CLOSED.value]
    earlier = db.execute(select(BatchExecution).where(
        BatchExecution.batch_id != batch.batch_id,
        BatchExecution.start_at.isnot(None),
        BatchExecution.start_at < batch.start_at,
        (BatchExecution.state.in_(always_states)) |
        (BatchExecution.state.in_(extended_states) &
         (BatchExecution.start_at >= _ORDER_RULE_EXTENDED_STATES_SINCE)),
    ).order_by(BatchExecution.start_at.asc())).scalars().all()
    if not earlier:
        return
    earlier_ids = [b.batch_id for b in earlier]
    # "Đã cấp liệu lần nào" phải tính CẢ 2 đường — qua Dispense/DispenseLine (Cấp 1 vật tư/Áp
    # dụng gợi ý/Backflush) VÀ qua GenealogyEdge consume trực tiếp (API "Tiêu thụ lô", KHÔNG tạo
    # DispenseLine — mirror đúng bug/fix workshop_usage_history đã gặp trong phiên này: chỉ nhìn
    # DispenseLine bỏ sót tiêu thụ trực tiếp, khiến mẻ ĐÃ dùng NVL vẫn bị coi nhầm là "chưa cấp
    # liệu" và chặn oan mẻ sau — lộ rõ nhất khi mở rộng rule sang completed/closed, vì mẻ cũ tiêu
    # thụ qua đường "Tiêu thụ lô" rồi đóng lại rất phổ biến).
    dispensed_via_line = {bid for (bid,) in db.execute(
        select(Dispense.batch_id).join(DispenseLine, DispenseLine.dispense_id == Dispense.dispense_id)
        .where(Dispense.batch_id.in_(earlier_ids)).distinct())}
    dispensed_via_consume = {bid for (bid,) in db.execute(
        select(GenealogyEdge.to_id).where(
            GenealogyEdge.to_type == "batch", GenealogyEdge.to_id.in_(earlier_ids),
            GenealogyEdge.relation == GenealogyRelation.CONSUME.value).distinct())}
    dispensed_ids = dispensed_via_line | dispensed_via_consume
    pending = [b for b in earlier if b.batch_id not in dispensed_ids]
    if pending:
        codes = ", ".join(b.batch_code for b in pending[:5])
        more = f" (+{len(pending) - 5} mẻ khác)" if len(pending) > 5 else ""
        raise DomainError(f"Mẻ {codes}{more} bắt đầu nấu trước mẻ này và chưa cấp liệu lần nào — "
                          "cấp liệu cho (các) mẻ đó trước.")


def _fefo_lots(db: Session, material_code: str) -> list:
    """Các lô khả dụng (available/released — mirror warehouse.py::stock_on_hand, KHÔNG chỉ
    "available") của một material_code Ở MỌI KHO, sắp theo FEFO (hết hạn trước) rồi FIFO — nếu
    `material_code` thực ra là mã 1 Nhóm vật tư thay thế (dòng BOM khai theo nhóm, không có mã
    vật tư cụ thể — xem bom.py::codes_for_dispense), gộp lô của MỌI thành viên rồi mới sắp
    chung 1 hàng đợi FEFO (thủ kho xuất mã thành viên nào cũng hợp lệ).

    CHỈ dùng làm building-block nội bộ cho _workshop_fefo_lots() — không lọc kho nên KHÔNG được
    gọi trực tiếp ở bất kỳ đường cấp liệu/gợi ý thật nào (bug thực tế đã gặp: _plan_consume và
    suggest_dispense từng gọi thẳng hàm này, khiến "Cấp 1 vật tư"/gợi ý theo nhóm có thể lấy
    nhầm lô đang ở Kho công ty — yêu cầu người dùng 2026-09-14, đã sửa toàn bộ sang
    _workshop_fefo_lots)."""
    real_codes = bom.codes_for_dispense(db, material_code)
    mats = db.execute(select(Material).where(Material.code.in_(real_codes))).scalars().all()
    material_ids = [m.material_id for m in mats]
    if not material_ids:
        return []
    lots = db.execute(select(MaterialLot).where(
        MaterialLot.material_id.in_(material_ids),
        MaterialLot.status.in_([LotStatus.AVAILABLE.value, LotStatus.RELEASED.value]),
        MaterialLot.quantity > 0)).scalars().all()
    lots = [l for l in lots if not _is_expired(l)]
    # expiry None → cuối hàng đợi (giá trị lớn); cùng expiry → FIFO theo created_at
    far = utcnow().replace(tzinfo=None) + timedelta(days=36500)

    def key(l):
        e = l.expiry
        if e is None:
            e = far
        elif e.tzinfo is not None:
            e = e.replace(tzinfo=None)
        c = l.created_at
        if c is not None and c.tzinfo is not None:
            c = c.replace(tzinfo=None)
        return (e, c)
    return sorted(lots, key=key)


def _workshop_fefo_lots(db: Session, material_code: str, as_of=None) -> list:
    """Như _fefo_lots nhưng chỉ lấy lô ở Kho phân xưởng — nơi NVL thật sự cấp cho mẻ nấu
    (tài liệu §9.0: "nguyên liệu phân bổ vào mẻ nấu ... luôn lấy từ Kho phân xưởng").

    `as_of` (thường là batch.start_at, xem _assert_dispensable): nếu truyền, mỗi lô CHỈ được coi
    khả dụng tối đa bằng tồn dựng lại tính đến hết thời điểm đó (warehouse.py::lot_on_hand_as_of)
    — không cho mượn hàng về kho phân xưởng SAU khi mẻ đã bắt đầu nấu (yêu cầu người dùng
    2026-09-15). Lô nào tồn dựng lại = 0 tại thời điểm đó (chưa về kho lúc mẻ bắt đầu) bị loại
    hẳn khỏi hàng đợi FEFO của mẻ này. Gắn `asof_cap` tạm lên từng lô còn lại (đọc bởi
    _effective_qty) = MIN(tồn sống hiện tại, tồn dựng lại tại `as_of`) — vừa không vượt trần lịch
    sử (hàng mới về sau không tính), vừa không vượt tồn thật hiện có (nếu phần cũ đã bị mẻ khác
    lấy bớt từ đó tới giờ). Tiêu chí phụ FIFO vẫn theo `created_at` GỐC của lô (ngày nhập đầu
    tiên, xem _fefo_lots) — xác nhận lại với người dùng 2026-09-15: KHÔNG đổi sang ngày điều
    chuyển vào phân xưởng, chỉ cần đảm bảo lọc kho đúng (Kho phân xưởng, không lấy sang Kho công
    ty — đã tự nhiên đúng qua bộ lọc _is_workshop_location bên dưới)."""
    lots = [l for l in _fefo_lots(db, material_code) if warehouse_svc._is_workshop_location(l.location)]
    if as_of is None:
        return lots
    asof_by_lot = {r["lot_id"]: r["quantity"] for r in
                  warehouse_svc.lot_on_hand_as_of(db, as_of, "Kho phân xưởng")}
    out = []
    for l in lots:
        cap = asof_by_lot.get(l.lot_id, 0.0)
        if cap <= 1e-9:
            continue
        l.asof_cap = min(l.quantity, cap)
        out.append(l)
    return out


def _effective_qty(lot: MaterialLot, reserved: dict) -> float:
    """Tồn CÒN LẠI của 1 lô sau khi trừ phần đã "giữ chỗ" bởi các dòng KHÁC trong CÙNG 1 lần
    gọi dispense()/backflush() (chưa commit vào DB — 2 pha lập kế hoạch rồi mới thực thi, xem
    _plan_consume) — tránh 2 dòng trong cùng 1 phiếu cùng tưởng còn nguyên 1 lô rồi tính trùng.

    Nếu lô có `asof_cap` gắn kèm (xem _workshop_fefo_lots's `as_of`), trần thật sự là MIN(tồn
    sống, asof_cap) chứ không phải tồn sống — hàng về sau thời điểm mẻ bắt đầu không được tính."""
    cap = getattr(lot, "asof_cap", None)
    total_cap = lot.quantity if cap is None else min(lot.quantity, cap)
    return round(total_cap - reserved.get(lot.lot_id, 0.0), 4)


def _lot_avail_qty(lot: MaterialLot) -> float:
    """Tồn khả dụng của 1 lô cho MỤC ĐÍCH HIỂN THỊ/GỢI Ý (suggest_dispense) — không giữ chỗ
    (reserved) như _effective_qty vì đây chỉ là xem trước từng dòng độc lập. Tôn trọng `asof_cap`
    nếu có (xem _workshop_fefo_lots's `as_of`) — không gợi ý vượt quá tồn tại thời điểm mẻ bắt
    đầu nấu."""
    cap = getattr(lot, "asof_cap", None)
    return lot.quantity if cap is None else min(lot.quantity, cap)


def _is_fifo_choice(db: Session, material_code: str, lot_id: str, reserved: dict, as_of=None) -> bool:
    """1 lô được coi là "đúng FIFO/FEFO" nếu KHÔNG có lô nào xếp TRƯỚC nó (theo FEFO, Kho phân
    xưởng, cùng giới hạn `as_of` nếu có) mà còn tồn > 0 (SAU khi trừ phần đã giữ chỗ bởi dòng
    khác cùng phiếu) bị bỏ qua. Lô không nằm trong danh sách FEFO hợp lệ (khác Kho phân xưởng /
    đã hết hạn / khác vật tư / chưa tồn tại tại `as_of`) luôn coi là lệch."""
    order = _workshop_fefo_lots(db, material_code, as_of)
    idx = next((i for i, l in enumerate(order) if l.lot_id == lot_id), None)
    if idx is None:
        return False
    return not any(_effective_qty(l, reserved) > 1e-9 for l in order[:idx])


def _plan_consume(db: Session, material_code: str, qty: float, picked_lot_id: str = None,
                  reason: str = None, reserved: dict = None, as_of=None) -> tuple:
    """Lập kế hoạch cấp liệu cho `qty` của material_code — CHỈ TÍNH, KHÔNG trừ tồn (all-or-
    nothing: raise NGAY nếu không đủ 100%, tránh trừ 1 phần rồi mới báo thiếu). Nếu chỉ định lot
    mà lot đó KHÔNG phải lô FIFO/FEFO gợi ý (còn lô xếp trước còn tồn) thì bắt buộc có `reason`.
    `reserved` (dict lot_id -> đã giữ chỗ) dùng CHUNG cho mọi dòng trong 1 lần gọi dispense()/
    backflush() — CẬP NHẬT TRỰC TIẾP (mutate) để dòng sau thấy đúng phần lô mà dòng trước đã
    dùng, dù chưa commit DB thật. `as_of` (batch.start_at) — xem _workshop_fefo_lots — áp dụng
    CẢ cho lô chỉ định tay (picked_lot_id), không chỉ nhánh tự động FEFO. Trả về (plan, fifo_ok)
    — plan: list[(lot, take)] để _execute_plan thực thi thật khi đã chắc chắn đủ."""
    reserved = reserved if reserved is not None else {}
    remaining = round(qty, 4)
    plan = []
    fifo_ok = True
    if picked_lot_id:
        lot = db.get(MaterialLot, picked_lot_id)
        if not lot:
            raise NotFoundError("Lô vật tư không tồn tại.")
        if lot.material_id and not warehouse_svc._is_workshop_location(lot.location):
            raise DomainError(f"Lô {lot.lot_code} không ở Kho phân xưởng — chỉ được cấp liệu "
                              "từ Kho phân xưởng cho mẻ sản xuất.")
        if _is_expired(lot):
            raise DomainError(f"Lô {lot.lot_code} đã HẾT HẠN — không được cấp.")
        if as_of is not None:
            asof_by_lot = {r["lot_id"]: r["quantity"] for r in
                          warehouse_svc.lot_on_hand_as_of(db, as_of, "Kho phân xưởng")}
            cap = asof_by_lot.get(lot.lot_id, 0.0)
            if cap <= 1e-9:
                raise DomainError(f"Lô {lot.lot_code} chưa tồn tại ở Kho phân xưởng tính đến "
                                  "thời điểm mẻ bắt đầu nấu — không được chọn.")
            lot.asof_cap = min(lot.quantity, cap)
        fifo_ok = _is_fifo_choice(db, material_code, lot.lot_id, reserved, as_of)
        if not fifo_ok and not (reason or "").strip():
            raise DomainError(
                f"Lô {lot.lot_code} không phải lô FIFO/FEFO gợi ý cho {material_code} — "
                "bắt buộc nhập lý do chọn lô khác.")
        take = min(remaining, max(_effective_qty(lot, reserved), 0.0))
        if take > 0:
            plan.append((lot, take))
            reserved[lot.lot_id] = reserved.get(lot.lot_id, 0.0) + take
        remaining = round(remaining - take, 4)
    else:
        for lot in _workshop_fefo_lots(db, material_code, as_of):
            if remaining <= 1e-9:
                break
            take = min(remaining, max(_effective_qty(lot, reserved), 0.0))
            if take <= 0:
                continue
            plan.append((lot, take))
            reserved[lot.lot_id] = reserved.get(lot.lot_id, 0.0) + take
            remaining = round(remaining - take, 4)
    if remaining > 1e-6:
        hint = " (tính theo tồn kho phân xưởng tại thời điểm mẻ bắt đầu nấu)" if as_of is not None else ""
        raise DomainError(
            f"Không đủ lô khả dụng (còn hạn) cho {material_code}: thiếu {round(remaining, 4)}{hint} — "
            "không cấp liệu (all-or-nothing).")
    return plan, fifo_ok


def _execute_plan(db: Session, batch: BatchExecution, material_code: str, plan: list, user: User,
                  allow_over: bool, fifo_ok: bool, reason: str = None) -> list:
    """Thực thi thật 1 kế hoạch đã lập (_plan_consume) — trừ tồn + genealogy qua consume_lot.

    Ghi `material_code` THẬT theo từng lô (bom.material_code_for_lot), KHÔNG dùng thẳng
    `material_code` truyền vào — khi dòng BOM khai theo Nhóm vật tư thay thế, `material_code`
    truyền vào là mã NHÓM (không xuất kho trực tiếp được), còn lô thực tế tiêu thụ luôn thuộc
    1 mã vật tư CỤ THỂ (xem _fefo_lots) — ghi đúng mã đó để sổ sách/lịch sử cấp liệu chính xác.

    consume_lot(commit=False): không commit từng lô — nếu dòng SAU trong CÙNG phiếu (khác lời
    gọi _execute_plan, VD dòng 2 vượt trần định mức BOM) raise DomainError, cả phiếu phải rollback
    sạch (đúng lời hứa all-or-nothing của dispense()), không để lại phần đã trừ tồn của dòng
    trước — người gọi (dispense()/backflush()/adjust_actual()) tự commit một lần ở cuối
    (audit rủi ro 2026-09-15)."""
    lines = []
    for lot, take in plan:
        batch_svc.consume_lot(db, batch.batch_id, lot.lot_id, take, user, allow_over, commit=False)
        lines.append({"material_code": bom.material_code_for_lot(db, lot), "lot_id": lot.lot_id,
                      "lot_code": lot.lot_code, "quantity": take, "uom": lot.uom,
                      "fifo_ok": fifo_ok, "reason": reason})
    return lines


def suggest_dispense(db: Session, batch_id: str) -> dict:
    """Xem trước gợi ý cấp liệu cho 1 mẻ: với mỗi vật tư còn THIẾU theo Định mức (BOM, đã scale
    theo SL kế hoạch của mẻ — cùng phép tính hiển thị ở bảng Định mức↔Thực tế), tự chọn lô theo
    FEFO ở Kho phân xưởng — CHỈ TÍNH, không trừ tồn. `alternatives` liệt kê MỌI lô khả dụng
    (Kho phân xưởng, còn hạn) của vật tư đó để người dùng có thể chọn lô KHÁC lô FIFO gợi ý
    (kèm lý do, xem _plan_consume). Người dùng xem bảng này rồi bấm "Áp dụng" sẽ gọi lại
    dispense() với đúng lô/số lượng (có thể đã sửa) lấy từ đây.

    Mỗi dòng trả về CẢ 2 cặp tồn kho công ty/phân xưởng: `stock_company`/`stock_workshop` (tồn
    HIỆN TẠI, thời gian thực lúc gọi API) và `stock_company_asof`/`stock_workshop_asof` (tồn
    TẠI ĐÚNG THỜI ĐIỂM `batch.start_at` — dựng lại từ lịch sử StockMovement qua
    stock_on_hand_as_of, không lẫn biến động kho xảy ra SAU khi mẻ đã bắt đầu nấu — yêu cầu
    người dùng 2026-09-15, tránh nhầm với tồn hiện tại ở 2 cột đầu)."""
    batch = db.get(BatchExecution, batch_id)
    if not batch:
        raise NotFoundError("Batch không tồn tại.")
    _assert_dispensable(db, batch)
    cmp = bom.compare_batch(db, batch)
    # Tồn hiện tại theo material_code THẬT ở mỗi kho — dùng để hiển thị tham khảo "Tồn kho công
    # ty"/"Tồn kho phân xưởng" cạnh gợi ý (khác `alternatives`/`picks` vốn CHỈ xét Kho phân
    # xưởng — nơi duy nhất được cấp liệu thật, xem _workshop_fefo_lots). Vật tư khai theo Nhóm
    # thay thế (bom.codes_for_dispense) cộng dồn tồn của MỌI mã thành viên.
    company_stock = {r["material_code"]: r["on_hand"] for r in warehouse_svc.stock_on_hand(db, "Kho công ty")}
    workshop_stock = {r["material_code"]: r["on_hand"] for r in warehouse_svc.stock_on_hand(db, "Kho phân xưởng")}
    # Tồn TẠI THỜI ĐIỂM MẺ BẮT ĐẦU (khác 2 dict trên là tồn HIỆN TẠI) — người dùng cần đối chiếu
    # đúng số đã có lúc nấu, không lẫn với biến động kho xảy ra SAU đó (yêu cầu người dùng
    # 2026-09-15). batch.start_at chắc chắn có giá trị ở đây vì _assert_dispensable đã kiểm tra.
    company_stock_asof = {r["material_code"]: r["on_hand"]
                          for r in warehouse_svc.stock_on_hand_as_of(db, batch.start_at, "Kho công ty")}
    workshop_stock_asof = {r["material_code"]: r["on_hand"]
                           for r in warehouse_svc.stock_on_hand_as_of(db, batch.start_at, "Kho phân xưởng")}
    name_by_code = {m.code: m.name for m in db.execute(select(Material)).scalars().all()}
    lines = []
    for l in cmp["lines"]:
        need = round(-l["diff"], 4) if l["diff"] < 0 else 0.0
        if need <= 1e-6:
            continue
        member_codes = l.get("match_codes") or [l["material_code"]]
        if l.get("is_group") and len(member_codes) > 1:
            # Nhóm "dùng nhiều mã cùng lúc" khai CHUNG 1 định mức, không tách sẵn theo từng
            # thành viên (khác dòng member_qty, đã tách sẵn ở compare_batch) — hiện THÀNH TỪNG
            # DÒNG theo mã thành viên để người dùng tự do phân bổ số lượng/lô qua từng mã, vẫn
            # gợi ý trước theo FIFO chung (gộp tồn mọi thành viên rồi chia theo thứ tự FEFO) —
            # tổng số lượng qua các dòng này không được vượt định mức chung (chặn thật ở
            # consume_lot/ceiling_for_material, không phải ở đây)."""
            combined_lots = _workshop_fefo_lots(db, l["material_code"], batch.start_at)
            picks_by_member = {c: [] for c in member_codes}
            remaining = need
            for lot in combined_lots:
                if remaining <= 1e-9:
                    break
                take = min(remaining, _lot_avail_qty(lot))
                if take <= 0:
                    continue
                mcode = bom.material_code_for_lot(db, lot)
                picks_by_member.setdefault(mcode, []).append(
                    {"lot_id": lot.lot_id, "lot_code": lot.lot_code, "quantity": round(take, 4),
                     "uom": lot.uom, "expiry": lot.expiry.isoformat() if lot.expiry else None})
                remaining = round(remaining - take, 4)
            group_shortfall = round(remaining, 4) if remaining > 1e-6 else 0.0
            for mcode in member_codes:
                member_lots = _workshop_fefo_lots(db, mcode, batch.start_at)
                alternatives = [{"lot_id": lot.lot_id, "lot_code": lot.lot_code, "quantity": round(_lot_avail_qty(lot), 4),
                                "uom": lot.uom, "expiry": lot.expiry.isoformat() if lot.expiry else None}
                               for lot in member_lots]
                lines.append({"material_code": mcode, "material_name": name_by_code.get(mcode),
                             "uom": l["uom"], "planned": l["planned"],
                             "stock_company": round(company_stock.get(mcode, 0.0), 4),
                             "stock_workshop": round(workshop_stock.get(mcode, 0.0), 4),
                             "stock_company_asof": round(company_stock_asof.get(mcode, 0.0), 4),
                             "stock_workshop_asof": round(workshop_stock_asof.get(mcode, 0.0), 4),
                             "need": need, "picks": picks_by_member.get(mcode, []), "alternatives": alternatives,
                             "group_code": l["material_code"], "shortfall": group_shortfall})
            continue
        real_codes = bom.codes_for_dispense(db, l["material_code"])
        stock_company = round(sum(company_stock.get(c, 0.0) for c in real_codes), 4)
        stock_workshop = round(sum(workshop_stock.get(c, 0.0) for c in real_codes), 4)
        stock_company_asof = round(sum(company_stock_asof.get(c, 0.0) for c in real_codes), 4)
        stock_workshop_asof = round(sum(workshop_stock_asof.get(c, 0.0) for c in real_codes), 4)
        fefo_lots = _workshop_fefo_lots(db, l["material_code"], batch.start_at)
        alternatives = [{"lot_id": lot.lot_id, "lot_code": lot.lot_code, "quantity": round(_lot_avail_qty(lot), 4),
                        "uom": lot.uom, "expiry": lot.expiry.isoformat() if lot.expiry else None}
                       for lot in fefo_lots]
        picks = []
        remaining = need
        for lot in fefo_lots:
            if remaining <= 1e-9:
                break
            take = min(remaining, _lot_avail_qty(lot))
            if take <= 0:
                continue
            picks.append({"lot_id": lot.lot_id, "lot_code": lot.lot_code,
                         "quantity": round(take, 4), "uom": lot.uom,
                         "expiry": lot.expiry.isoformat() if lot.expiry else None})
            remaining = round(remaining - take, 4)
        lines.append({"material_code": l["material_code"], "material_name": l.get("material_name"),
                     "uom": l["uom"], "planned": l["planned"],
                     "stock_company": stock_company, "stock_workshop": stock_workshop,
                     "stock_company_asof": stock_company_asof, "stock_workshop_asof": stock_workshop_asof,
                     "need": need, "picks": picks, "alternatives": alternatives,
                     "shortfall": round(remaining, 4) if remaining > 1e-6 else 0.0})
    return {"batch_id": batch_id, "batch_code": batch.batch_code, "lines": lines}


def dispense(db: Session, batch_id: str, lines_in: list, user: User, note: str = None) -> dict:
    """Cấp liệu cho mẻ. lines_in = [{material_code, quantity, lot_id?, reason?}]. All-or-nothing:
    LẬP KẾ HOẠCH cho MỌI dòng trước (không trừ tồn) — nếu BẤT KỲ dòng nào không đủ tồn (hoặc
    chọn lô lệch FIFO mà thiếu lý do) thì KHÔNG cấp liệu dòng nào cả, báo lỗi gộp ngay."""
    require_role(user, Role.OPERATOR, Role.SUPERVISOR, Role.ENGINEER)
    batch = db.get(BatchExecution, batch_id)
    if not batch:
        raise NotFoundError("Batch không tồn tại.")
    _assert_dispensable(db, batch)
    if not lines_in:
        raise DomainError("Phiếu cấp liệu rỗng.")
    planned, errors, reserved = [], [], {}
    for ln in lines_in:
        code = ln.get("material_code")
        qty = float(ln.get("quantity") or 0)
        if not code or qty <= 0:
            continue
        try:
            plan, fifo_ok = _plan_consume(db, code, qty, picked_lot_id=ln.get("lot_id"),
                                          reason=ln.get("reason"), reserved=reserved, as_of=batch.start_at)
            planned.append((code, plan, bool(ln.get("allow_over")), fifo_ok, ln.get("reason")))
        except DomainError as e:
            errors.append(str(e))
    if errors:
        raise DomainError("Không cấp liệu — " + "; ".join(errors))
    disp = Dispense(dispense_id=new_id(),
                    dispense_code=f"DISP-{utcnow():%Y%m%d}-{new_id()[:5].upper()}",
                    batch_id=batch_id, mode="dispense", status="issued",
                    note=note, created_by=user.username, created_at=utcnow())
    db.add(disp)
    db.flush()
    all_lines = []
    for code, plan, allow_over, fifo_ok, reason in planned:
        rows = _execute_plan(db, batch, code, plan, user, allow_over, fifo_ok, reason)
        for r in rows:
            db.add(DispenseLine(line_id=new_id(), dispense_id=disp.dispense_id, **r))
            all_lines.append(r)
    record_audit(db, entity_type="batch", entity_id=batch_id, action="dispense", actor=user,
                 after={"dispense_code": disp.dispense_code, "lines": len(all_lines)})
    db.commit()
    return {"dispense_code": disp.dispense_code, "lines": all_lines,
            "bom": bom.compare_batch(db, batch)}


def backflush(db: Session, batch_id: str, produced_qty: float, user: User) -> dict:
    """Tự khấu trừ NVL theo định mức BOM cho `produced_qty` đã sản xuất.

    standard(material) = qty_BOM × (produced_qty / base_qty). Trừ phần đã consume trước đó."""
    require_role(user, Role.OPERATOR, Role.SUPERVISOR, Role.ENGINEER)
    batch = db.get(BatchExecution, batch_id)
    if not batch:
        raise NotFoundError("Batch không tồn tại.")
    _assert_dispensable(db, batch)
    snap = batch.recipe_snapshot or {}
    base = snap.get("base_qty") or 0
    if not base:
        raise DomainError("Recipe snapshot thiếu base_qty — không backflush được.")
    factor = produced_qty / base
    already = bom.actual_consumed(db, batch_id)
    disp = Dispense(dispense_id=new_id(),
                    dispense_code=f"BKF-{utcnow():%Y%m%d}-{new_id()[:5].upper()}",
                    batch_id=batch_id, mode="backflush", status="issued",
                    note=f"Backflush cho {produced_qty} {batch.uom}",
                    created_by=user.username, created_at=utcnow())
    db.add(disp)
    db.flush()
    all_lines, skipped, reserved = [], [], {}
    # Gộp định mức theo material_code (dòng khai theo Nhóm vật tư thay thế được chuẩn hoá về
    # material_code cụ thể/mã nhóm qua bom._expand_materials, xem compare_batch cùng module).
    req_by, uom_by, match_by = {}, {}, {}
    for m in bom._expand_materials(db, snap.get("materials"), brew_order_id=batch.order_id):
        code = m.get("material_code")
        req_by[code] = req_by.get(code, 0.0) + (m.get("qty", 0) or 0) * factor
        uom_by.setdefault(code, m.get("uom"))
        match_by.setdefault(code, m.get("match_codes") or {code})
    for code, std in req_by.items():
        already_code = sum(already.get(c, 0.0) for c in match_by[code])
        need = round(std - already_code, 4)
        if need <= 1e-6:
            continue
        try:
            # Backflush vẫn TÔN TRỌNG trần định mức BOM (không tự ý vượt); nếu vượt hoặc
            # thiếu tồn sẽ rơi vào DomainError → ghi vào 'skipped' để người dùng xử lý thủ công
            # (KHÔNG chặn toàn bộ backflush như dispense() — mỗi vật tư độc lập).
            plan, fifo_ok = _plan_consume(db, code, need, reserved=reserved, as_of=batch.start_at)
            rows = _execute_plan(db, batch, code, plan, user, allow_over=False, fifo_ok=fifo_ok)
            for r in rows:
                db.add(DispenseLine(line_id=new_id(), dispense_id=disp.dispense_id, **r))
                all_lines.append(r)
        except DomainError as e:
            skipped.append({"material_code": code, "need": need, "error": str(e)})
    record_audit(db, entity_type="batch", entity_id=batch_id, action="backflush", actor=user,
                 after={"dispense_code": disp.dispense_code, "produced_qty": produced_qty,
                        "lines": len(all_lines)})
    db.commit()
    return {"dispense_code": disp.dispense_code, "factor": round(factor, 4),
            "lines": all_lines, "skipped": skipped, "bom": bom.compare_batch(db, batch)}


def adjust_actual(db: Session, batch_id: str, material_code: str, new_actual: float,
                  user: User, reason: str) -> dict:
    """"Sửa" Thực tế của 1 vật tư ở bảng Định mức↔Thực tế (Cấp liệu cho mẻ) — tự tính CHÊNH LỆCH
    với thực tế hiện tại rồi TỰ ĐỘNG cấp thêm (tăng: qua FEFO ở Kho phân xưởng, all-or-nothing,
    mirror dispense()) hoặc hoàn lại (giảm: hoàn về lô đã dùng GẦN NHẤT của vật tư này trên mẻ,
    theo thứ tự LIFO — giảm dần quantity trên chính cạnh genealogy consume đã tạo trước đó, xoá
    cạnh nếu hoàn hết). Mọi thay đổi vẫn đi qua consume_lot thật/genealogy edge thật — không có
    số nào tồn tại ngoài sổ sách. Bắt buộc `reason` để truy vết. Chỉ sửa được khi mẻ CHƯA khóa
    hồ sơ (EBR)."""
    require_role(user, Role.OPERATOR, Role.SUPERVISOR, Role.ENGINEER)
    batch = db.get(BatchExecution, batch_id)
    if not batch:
        raise NotFoundError("Batch không tồn tại.")
    if batch.ebr_locked:
        raise DomainError("Hồ sơ mẻ (EBR) đã khóa — không thể sửa Thực tế; chỉ tạo amendment.")
    if not (reason or "").strip():
        raise DomainError("Bắt buộc nhập lý do khi sửa Thực tế.")
    current = round(bom.actual_consumed_for_match(db, batch, material_code), 4)
    new_actual = round(new_actual, 4)
    delta = round(new_actual - current, 4)
    if abs(delta) <= 1e-6:
        raise DomainError("Số Thực tế mới giống hệt hiện tại — không có gì để sửa.")

    disp = Dispense(dispense_id=new_id(),
                    dispense_code=f"ADJ-{utcnow():%Y%m%d}-{new_id()[:5].upper()}",
                    batch_id=batch_id, mode="adjust", status="issued",
                    note=f"Sửa Thực tế {material_code}: {current} → {new_actual} ({reason})",
                    created_by=user.username, created_at=utcnow())
    db.add(disp)
    db.flush()
    all_lines = []
    if delta > 0:
        # Chỉ nhánh TĂNG (lấy thêm tồn) mới cần qua _assert_dispensable — nhánh GIẢM (hoàn lại)
        # bên dưới không "lấy" thêm tồn nên không cần xếp hàng theo thứ tự mẻ.
        _assert_dispensable(db, batch)
        plan, fifo_ok = _plan_consume(db, material_code, delta, as_of=batch.start_at)
        rows = _execute_plan(db, batch, material_code, plan, user, allow_over=True,
                             fifo_ok=fifo_ok, reason=reason)
        for r in rows:
            db.add(DispenseLine(line_id=new_id(), dispense_id=disp.dispense_id, **r))
            all_lines.append(r)
    else:
        need_refund = round(-delta, 4)
        # material_code có thể là mã Nhóm vật tư thay thế (dòng BOM khai theo nhóm) — hoàn lại
        # phải khớp BẤT KỲ mã thành viên nào đã thực sự tiêu thụ, không chỉ đúng mã nhóm.
        refund_codes = set(bom.codes_for_dispense(db, material_code))
        edges = db.execute(select(GenealogyEdge).where(
            GenealogyEdge.to_type == "batch", GenealogyEdge.to_id == batch_id,
            GenealogyEdge.from_type == "lot", GenealogyEdge.relation == "consume")
            .order_by(GenealogyEdge.event_time.desc())).scalars().all()
        candidates = []
        for edge in edges:
            if not edge.quantity:
                continue
            # with_for_update(): khóa hàng trước khi đọc lot.quantity — 2 request hoàn lại/cấp
            # liệu gần như đồng thời trên CÙNG lô có thể cùng đọc quantity cũ (2026-09-03, audit
            # Kho công ty/phân xưởng).
            lot = db.execute(select(MaterialLot).where(
                MaterialLot.lot_id == edge.from_id).with_for_update()).scalar_one_or_none()
            if not lot or bom.material_code_for_lot(db, lot) not in refund_codes:
                continue
            candidates.append((edge, lot))
        plan_refund, remaining = [], need_refund
        for edge, lot in candidates:
            if remaining <= 1e-9:
                break
            take = min(remaining, edge.quantity)
            if take <= 0:
                continue
            plan_refund.append((edge, lot, take))
            remaining = round(remaining - take, 4)
        if remaining > 1e-6:
            raise DomainError(
                f"Không đủ lịch sử tiêu thụ (qua Cấp liệu/Consume) để hoàn lại — thiếu "
                f"{remaining} {material_code}.")
        for edge, lot, take in plan_refund:
            lot.quantity = round(lot.quantity + take, 4)
            if lot.status == LotStatus.CONSUMED.value:
                lot.status = LotStatus.AVAILABLE.value
            edge.quantity = round(edge.quantity - take, 4)
            if edge.quantity <= 1e-9:
                db.delete(edge)
            row = {"material_code": bom.material_code_for_lot(db, lot), "lot_id": lot.lot_id,
                  "lot_code": lot.lot_code, "quantity": -take, "uom": lot.uom,
                  "fifo_ok": True, "reason": reason}
            db.add(DispenseLine(line_id=new_id(), dispense_id=disp.dispense_id, **row))
            all_lines.append(row)
    record_audit(db, entity_type="batch", entity_id=batch_id, action="adjust_actual", actor=user,
                after={"material_code": material_code, "from": current, "to": new_actual, "reason": reason})
    db.commit()
    return {"dispense_code": disp.dispense_code, "lines": all_lines, "bom": bom.compare_batch(db, batch)}


def list_dispenses(db: Session, batch_id: str = None) -> list:
    stmt = select(Dispense).order_by(Dispense.created_at.desc())
    if batch_id:
        stmt = stmt.where(Dispense.batch_id == batch_id)
    out = []
    for d in db.execute(stmt).scalars().all():
        lines = db.execute(select(DispenseLine).where(
            DispenseLine.dispense_id == d.dispense_id)).scalars().all()
        out.append({"dispense_code": d.dispense_code, "batch_id": d.batch_id, "mode": d.mode,
                    "status": d.status, "note": d.note, "created_by": d.created_by,
                    "created_at": d.created_at,
                    "lines": [{"material_code": l.material_code, "lot_code": l.lot_code,
                               "quantity": l.quantity, "uom": l.uom, "fifo_ok": l.fifo_ok,
                               "reason": l.reason} for l in lines]})
    return out


def batch_dispense_summary(db: Session, batch_id: str, only_dispensed: bool = True) -> list[dict]:
    """Bảng Định mức↔Thực tế tách THEO MÃ VẬT TƯ THẬT đã cấp (KHÔNG gộp theo mã Nhóm vật tư
    thay thế như bom.py::compare_batch), kèm mã lô đã dùng + có đúng FIFO hay không (từ lịch sử
    cấp liệu — DispenseLine, luôn ghi mã THẬT theo lô, xem _execute_plan/adjust_actual). Dòng
    BOM khai theo nhóm (member_qty hoặc bare group) mà ĐÃ cấp cho ít nhất 1 thành viên hiện
    thành N dòng con (1/mã thật đã cấp — bỏ qua mã chưa cấp gì trong CÙNG dòng đó), Định mức/
    Chênh/Trạng thái CHỈ hiện ở dòng ĐẦU (dùng CHUNG cho cả nhóm, xem bom.py::_expand_materials).

    `only_dispensed=True` (màn "Cấp liệu"): bỏ hẳn dòng BOM nào CHƯA cấp gì (theo yêu cầu người
    dùng — không tự liệt kê sẵn định mức công thức khi chưa cấp). `only_dispensed=False` (Mẻ
    sản xuất/EBR — cần thấy ĐỦ mọi dòng BOM kể cả chưa cấp): dòng chưa cấp gì giữ nguyên GỘP
    THEO NHÓM y hệt compare_batch (chưa biết sẽ cấp qua thành viên nào nên không tách được)."""
    batch = db.get(BatchExecution, batch_id)
    if not batch:
        raise NotFoundError("Batch không tồn tại.")
    cmp = bom.compare_batch(db, batch)
    # "Thực tế" LUÔN lấy từ actual_consumed (genealogy — đúng dù tiêu thụ qua /consume trực
    # tiếp hay qua dispense(), xem bom.py::actual_consumed) — TUYỆT ĐỐI KHÔNG tự cộng dồn
    # DispenseLine.quantity cho việc này (chỉ có nếu đi qua dispense(), thiếu/lệch nếu mẻ có
    # dòng tiêu thụ qua /consume trực tiếp — bug thực tế đã gặp: 1 mẻ consume 8kg qua /consume
    # rồi "Sửa" xuống 3kg qua adjust_actual (tạo dòng hoàn -5kg) ra "Thực tế" -5kg thay vì 3kg).
    actual_by_code = bom.actual_consumed(db, batch_id)
    name_by_code = {m.code: m.name for m in db.execute(select(Material)).scalars().all()}
    # DispenseLine CHỈ dùng để tra mã lô/FIFO — vốn chỉ có khi đi qua dispense() (suggest/Cấp 1
    # vật tư/backflush/adjust), KHÔNG có với tiêu thụ qua /consume trực tiếp (lot_codes rỗng/
    # fifo_ok=None khi đó — không suy đoán được là ĐÚNG hay SAI FIFO).
    # "Cấp tự do" = ĐÃ từng cấp qua nút "Cấp 1 vật tư" (dp_go, luôn ghi note="Cấp tự do" — xem
    # views_ext.js) — KHÔNG phải "vật tư ngoài công thức" (yêu cầu người dùng 2026-09-14 làm rõ:
    # "Cấp 1 vật tư" chỉ cho chọn vật tư CÓ trong BOM (dropdown dp_mat lấy từ bom.lines), nên 1
    # vật tư CÓ định mức vẫn có thể vừa được "Áp dụng gợi ý" vừa được "Cấp 1 vật tư" thêm — chỉ
    # cần có ít nhất 1 lần qua "Cấp 1 vật tư" là đánh dấu cả dòng, mirror đúng cách "fifo_ok" bị
    # lật false nếu có BẤT KỲ lần cấp lệch FIFO nào).
    dispenses = db.execute(select(Dispense.dispense_id, Dispense.note, Dispense.created_by).where(
        Dispense.batch_id == batch_id)).all()
    free_dispense_ids = {did for did, note, _ in dispenses if note == "Cấp tự do"}
    dispense_ids = [did for did, _, _ in dispenses]
    actor_by_dispense_id = {did: by for did, _, by in dispenses}
    dlines = db.execute(select(DispenseLine).where(
        DispenseLine.dispense_id.in_(dispense_ids))).scalars().all() if dispense_ids else []
    lot_info: dict[str, dict] = {}
    # Mã lô lấy từ GenealogyEdge(relation=consume) — nguồn DUY NHẤT ghi lại dù tiêu thụ qua
    # dispense()/backflush()/adjust_actual (đi qua DispenseLine) HAY qua endpoint "Tiêu thụ lô"
    # trực tiếp (KHÔNG tạo DispenseLine — trước đây lot_codes rỗng oan cho các dòng này dù thực
    # tế CÓ trừ đúng lô, yêu cầu người dùng 2026-09-15). edge.quantity đã LUÔN Ở DẠNG NET (hoàn
    # lại qua adjust_actual trừ thẳng vào edge.quantity, xóa hẳn cạnh nếu về 0 — xem nhánh delta<0
    # phía trên), không cần tự trừ hoàn lại như DispenseLine nữa.
    consume_edges = db.execute(select(GenealogyEdge).where(
        GenealogyEdge.to_type == "batch", GenealogyEdge.to_id == batch_id,
        GenealogyEdge.from_type == "lot", GenealogyEdge.relation == "consume")).scalars().all()
    lots_by_id = {l.lot_id: l for l in db.execute(select(MaterialLot).where(
        MaterialLot.lot_id.in_({e.from_id for e in consume_edges}))).scalars().all()} if consume_edges else {}
    for e in consume_edges:
        lot = lots_by_id.get(e.from_id)
        if not lot or not e.quantity:
            continue
        code = bom.material_code_for_lot(db, lot)
        # fifo_ok=None (KHÔNG phải True) — genealogy edge không ghi lại có đúng FIFO hay không,
        # chỉ dispense() (qua DispenseLine.fifo_ok) mới biết; None nghĩa là "không xác định",
        # khác hẳn True ("chắc chắn đúng FIFO") — tránh hiện nhầm ✔ FIFO cho tiêu thụ qua
        # /consume trực tiếp (không hề kiểm tra FIFO lúc đó).
        info = lot_info.setdefault(code, {"lot_qty": {}, "fifo_ok": None, "is_free": False, "created_at": None, "actor": None})
        info["lot_qty"][lot.lot_code] = info["lot_qty"].get(lot.lot_code, 0.0) + e.quantity
    # DispenseLine chỉ còn dùng để lấy fifo_ok/"Cấp tự do"/"Ngày tạo" — metadata không có trên
    # genealogy edge, chỉ tồn tại với đường đi qua dispense(). Lần đầu 1 dòng nào đó của vật tư
    # này đi qua dispense() mới có căn cứ để bắt đầu từ True (đúng FIFO), rồi lật False nếu có
    # BẤT KỲ dòng nào khác FIFO.
    for dl in dlines:
        info = lot_info.setdefault(dl.material_code, {"lot_qty": {}, "fifo_ok": None, "is_free": False,
                                                       "created_at": None, "actor": None})
        if info["fifo_ok"] is None:
            info["fifo_ok"] = True
        if dl.fifo_ok is False:
            info["fifo_ok"] = False
        if dl.dispense_id in free_dispense_ids:
            info["is_free"] = True
        # "Ngày tạo" = lần ghi/sửa GẦN NHẤT (dispense/backflush/sửa Thực tế) cho vật tư này — thời
        # điểm THẬT sự bấm nút trên hệ thống, khác "Ngày cấp" (batch.start_at, xem bên dưới) vốn
        # là ngày mẻ BẮT ĐẦU NẤU dùng cho hồ sơ (yêu cầu người dùng 2026-09-15). "actor" đi kèm
        # cùng lần ghi/sửa gần nhất đó (yêu cầu người dùng 2026-09-16: "cấp liệu cũng thêm thông
        # tin người nhập, ngày giờ nhập").
        if info["created_at"] is None or dl.created_at > info["created_at"]:
            info["created_at"] = dl.created_at
            info["actor"] = actor_by_dispense_id.get(dl.dispense_id)
    for info in lot_info.values():
        # Cộng dồn THEO LÔ, chỉ hiện lô còn đóng góp thật > 0 vào Thực tế hiện tại — 1 lô đã dùng
        # rồi HOÀN HẾT (net về 0) không nên còn hiện tên trong "Mã lô", gây hiểu lầm "vẫn đang
        # dùng lô đó" (yêu cầu người dùng 2026-09-15).
        info["lot_codes"] = [code for code, qty in info["lot_qty"].items() if qty > 1e-9]
    rows = []
    for l in cmp["lines"]:
        codes = l.get("match_codes") or [l["material_code"]]
        dispensed = [c for c in codes if abs(actual_by_code.get(c, 0.0)) > 1e-9]
        if not dispensed:
            if only_dispensed:
                continue
            rows.append({"material_code": l["material_code"], "material_name": l.get("material_name"),
                        "uom": l["uom"], "planned": l["planned"], "actual": l["actual"],
                        "diff": l["diff"], "pct": l["pct"], "status": l["status"],
                        "lot_codes": [], "fifo_ok": None, "is_free": False,
                        "created_at": None, "actor": None, "supply_date": batch.start_at})
            continue
        for i, code in enumerate(dispensed):
            info = lot_info.get(code)
            rows.append({
                "material_code": code,
                "material_name": l.get("material_name") if code == l["material_code"] else name_by_code.get(code),
                "uom": l["uom"],
                "planned": l["planned"] if i == 0 else None,
                "actual": round(actual_by_code.get(code, 0.0), 4),
                "diff": l["diff"] if i == 0 else None,
                "pct": l["pct"] if i == 0 else None,
                "status": l["status"] if i == 0 else None,
                "lot_codes": info["lot_codes"] if info else [],
                "fifo_ok": info["fifo_ok"] if info else None,
                "is_free": bool(info and info["is_free"]),
                "created_at": info["created_at"] if info else None,
                "actor": info["actor"] if info else None,
                "supply_date": batch.start_at,
            })
    # Vật tư đã tiêu thụ nhưng KHÔNG khớp mã/nhóm nào trong BOM công thức — compare_batch() đã
    # tính sẵn ở `extras`, trước đây bảng này BỎ QUA hoàn toàn, hiện gộp vào CÙNG 1 dòng thống
    # nhất thay vì render riêng ở phía frontend (is_free tính y hệt các dòng BOM ở trên, không
    # tự suy ra True chỉ vì ngoài công thức — xem giải thích "Cấp tự do" phía trên).
    for e in cmp.get("extras", []):
        code = e["material_code"]
        info = lot_info.get(code)
        rows.append({
            "material_code": code, "material_name": e.get("material_name"), "uom": e.get("uom"),
            "planned": None, "actual": e["actual"], "diff": None, "pct": None, "status": e["status"],
            "lot_codes": info["lot_codes"] if info else [], "fifo_ok": info["fifo_ok"] if info else None,
            "is_free": bool(info and info["is_free"]),
            "created_at": info["created_at"] if info else None,
            "actor": info["actor"] if info else None, "supply_date": batch.start_at,
        })
    return rows
