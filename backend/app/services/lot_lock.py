"""Khóa lô theo TỪNG CÔNG ĐOẠN độc lập: Nấu → Lên men → Lọc → Chiết. KCS khóa xuôi theo thứ
tự (không khóa được công đoạn sau khi công đoạn nguồn chưa khóa); chỉ admin mở khóa được,
và phải mở ngược thứ tự (Chiết → Lọc → Lên men → Nấu) — không mở được 1 công đoạn khi công
đoạn hạ lưu của nó còn khóa. Xem routers/brewing.py::_assert_unlocked (giữ nguyên — chỉ check
cờ .locked của từng bản ghi + parent trực tiếp được truyền vào, vẫn đúng với mô hình này).

Lệnh nấu (BrewOrder) / Lệnh lọc lớn+nhỏ (FilterMasterOrder/FilterOrder) KHÔNG có thao tác
khóa/mở khóa riêng — trạng thái `locked` tự suy ra từ TẤT CẢ con của nó (xem
_recompute_brew_order_lock/_recompute_filter_order_lock/_recompute_filter_master_order_lock),
khóa khi mọi con đã khóa, tự mở ngay khi có 1 con được mở."""

from sqlalchemy import select, true
from sqlalchemy.orm import Session

from ..common import utcnow
from ..errors import DomainError
from ..models.brewing import (
    BottleRecord,
    BrewBatch,
    BrewMasterOrder,
    BrewOrder,
    BrewRecord,
    FermentBrewLink,
    FermentRecord,
    FilterMasterOrder,
    FilterOrder,
    FilterOrderTank,
    FilterRecord,
)
from ..security import User
from . import qc_catalog

_AUTO = "(tự động)"  # locked_by cho Lệnh nấu/Lệnh lọc — không phải người bấm nút, suy ra từ con


def _stage_ok(db: Session, stage: str, scope_type: str, scope_id: str, product_id=None,
             beer_type_id=None, finished_product_id=None) -> bool:
    """Chỉ chặn khóa lô khi còn chỉ tiêu bắt buộc CHƯA KHAI BÁO (pending). Chỉ tiêu FAIL
    (vượt giới hạn) không còn chặn — chỉ cảnh báo (xem badge màu/pill trên bảng danh sách,
    vẫn tính theo can_release đầy đủ để hiển thị)."""
    st = qc_catalog.stage_qc_status(db, stage, scope_type, scope_id, product_id,
                                    finished_product_id=finished_product_id, beer_type_id=beer_type_id)
    return not st["pending"]


def _lock(obj, user: User) -> None:
    obj.locked = True
    obj.locked_by = user.username
    obj.locked_at = utcnow()


def _unlock(obj) -> None:
    obj.locked = False
    obj.locked_by = None
    obj.locked_at = None


# ===== Nấu (BrewRecord = mã nấu, khóa kèm mọi BrewBatch/mẻ của nó) =====

def lock_brew(db: Session, brew_id: str, user: User) -> BrewRecord:
    brew = db.get(BrewRecord, brew_id)
    if not brew:
        raise DomainError("Mã nấu không tồn tại.")
    if brew.locked:
        raise DomainError("Mã nấu này đã được khóa.")
    batches = db.execute(select(BrewBatch).where(BrewBatch.brew_id == brew_id)).scalars().all()
    if not batches:
        raise DomainError("Mã nấu chưa có mẻ nào — không thể khóa.")
    for batch in batches:
        if batch.ended_at is None:
            raise DomainError(f"Mẻ '{batch.batch_code}' chưa hoàn thành (chưa bấm Kết thúc).")
        if not _stage_ok(db, "nau", "brew_batch", batch.batch_id, brew.product_id):
            raise DomainError(f"Mẻ '{batch.batch_code}' chưa đủ chỉ tiêu bắt buộc.")
    _lock(brew, user)
    for batch in batches:
        _lock(batch, user)
    db.commit()
    _recompute_brew_order_lock(db, brew.brew_order_id)
    db.commit()
    return brew


def unlock_brew(db: Session, brew_id: str, user: User) -> BrewRecord:
    brew = db.get(BrewRecord, brew_id)
    if not brew:
        raise DomainError("Mã nấu không tồn tại.")
    if not brew.locked:
        raise DomainError("Mã nấu này chưa bị khóa.")
    dependents = db.execute(select(FermentRecord).join(
        FermentBrewLink, FermentBrewLink.ferment_id == FermentRecord.ferment_id
    ).where(FermentBrewLink.brew_id == brew_id, FermentRecord.locked == true())).scalars().all()
    if dependents:
        names = ", ".join(f.lm_code for f in dependents)
        raise DomainError(f"Phải mở khóa Lên men trước (lô LM: {names}).")
    _unlock(brew)
    for batch in db.execute(select(BrewBatch).where(BrewBatch.brew_id == brew_id)).scalars().all():
        _unlock(batch)
    db.commit()
    _recompute_brew_order_lock(db, brew.brew_order_id)
    db.commit()
    return brew


def _recompute_brew_order_lock(db: Session, brew_order_id) -> None:
    if not brew_order_id:
        return
    order = db.get(BrewOrder, brew_order_id)
    if not order:
        return
    brews = db.execute(select(BrewRecord).where(BrewRecord.brew_order_id == brew_order_id)).scalars().all()
    should_lock = bool(brews) and all(b.locked for b in brews)
    if should_lock and not order.locked:
        order.locked, order.locked_by, order.locked_at = True, _AUTO, utcnow()
    elif not should_lock and order.locked:
        _unlock(order)
    if order.master_order_id:
        _recompute_brew_master_order_lock(db, order.master_order_id)


def _recompute_brew_master_order_lock(db: Session, master_order_id: str) -> None:
    master = db.get(BrewMasterOrder, master_order_id)
    if not master:
        return
    orders = db.execute(select(BrewOrder).where(BrewOrder.master_order_id == master_order_id)).scalars().all()
    should_lock = bool(orders) and all(o.locked for o in orders)
    if should_lock and not master.locked:
        master.locked, master.locked_by, master.locked_at = True, _AUTO, utcnow()
    elif not should_lock and master.locked:
        _unlock(master)


# ===== Lên men (FermentRecord = lô LM) =====

def _filters_sourced_from_ferment(db: Session, ferment_id: str, locked_only: bool = False) -> list[FilterRecord]:
    """Mọi FilterRecord có 1 dòng FilterOrderTank (loại cct) trỏ tới ferment_id này — kể cả mẻ
    lọc PHỐI, vì mọi mẻ lọc (phối hay không) đều có bộ dòng FilterOrderTank kết quả riêng gắn
    filter_id của chính nó (xem add_filter, routers/brewing.py)."""
    filter_ids = {row[0] for row in db.execute(select(FilterOrderTank.filter_id).where(
        FilterOrderTank.tank_type == "cct", FilterOrderTank.ferment_id == ferment_id,
        FilterOrderTank.filter_id.is_not(None))).all()}
    if not filter_ids:
        return []
    filters = db.execute(select(FilterRecord).where(FilterRecord.filter_id.in_(filter_ids))).scalars().all()
    return [f for f in filters if not locked_only or f.locked]


def lock_ferment(db: Session, ferment_id: str, user: User) -> FermentRecord:
    ferment = db.get(FermentRecord, ferment_id)
    if not ferment:
        raise DomainError("Bản ghi lên men không tồn tại.")
    if ferment.locked:
        raise DomainError("Lô LM này đã được khóa.")
    brew_ids = [r[0] for r in db.execute(
        select(FermentBrewLink.brew_id).where(FermentBrewLink.ferment_id == ferment_id)).all()]
    if not brew_ids:
        raise DomainError("Lô LM chưa liên kết mã nấu nào — không thể khóa.")
    brews = db.execute(select(BrewRecord).where(BrewRecord.brew_id.in_(brew_ids))).scalars().all()
    if not all(b.locked for b in brews):
        raise DomainError("Phải khóa Nấu (mã nấu nguồn) trước khi khóa Lên men.")
    if not ferment.qc_approved:
        raise DomainError("Lô LM chưa được duyệt (Duyệt LM) — không thể khóa.")
    if not _stage_ok(db, "len_men_chinh", "ferment",
                     qc_catalog.ferment_scope_id(ferment.lm_code, ferment.ferment_year, "len_men_chinh"),
                     ferment.product_id):
        raise DomainError("Chưa đủ chỉ tiêu lên men chính bắt buộc.")
    _lock(ferment, user)
    db.commit()
    return ferment


def unlock_ferment(db: Session, ferment_id: str, user: User) -> FermentRecord:
    ferment = db.get(FermentRecord, ferment_id)
    if not ferment:
        raise DomainError("Bản ghi lên men không tồn tại.")
    if not ferment.locked:
        raise DomainError("Lô LM này chưa bị khóa.")
    dependents = _filters_sourced_from_ferment(db, ferment_id, locked_only=True)
    if dependents:
        names = ", ".join(f.filter_code for f in dependents)
        raise DomainError(f"Phải mở khóa Lọc trước (mẻ lọc: {names}).")
    _unlock(ferment)
    db.commit()
    return ferment


# ===== Lọc (FilterRecord = mẻ lọc/tank) =====

def lock_filter(db: Session, filter_id: str, user: User) -> FilterRecord:
    f = db.get(FilterRecord, filter_id)
    if not f:
        raise DomainError("Bản ghi lọc không tồn tại.")
    if f.locked:
        raise DomainError("Mẻ lọc này đã được khóa.")
    if f.ended_at is None:
        raise DomainError("Mẻ lọc chưa hoàn thành (chưa kết thúc đủ các tank nguồn).")
    if not f.qc_approved:
        raise DomainError("Mẻ lọc chưa được duyệt (Duyệt KCS) — không thể khóa.")
    lines = db.execute(select(FilterOrderTank).where(FilterOrderTank.filter_id == filter_id)).scalars().all()
    if not lines:
        raise DomainError("Mẻ lọc chưa có nguồn — không thể khóa.")
    for line in lines:
        if line.tank_type == "cct":
            ferment = db.get(FermentRecord, line.ferment_id)
            if not ferment or not ferment.locked:
                raise DomainError(
                    f"Phải khóa Lên men nguồn trước (tank {ferment.tank_lm if ferment else '?'}).")
        else:
            src = db.get(FilterRecord, line.source_filter_id)
            if not src or not src.locked:
                raise DomainError(
                    f"Phải khóa mẻ lọc nguồn trước (mẻ {src.filter_code if src else '?'}).")
    _lock(f, user)
    db.commit()
    _recompute_filter_order_lock(db, f.filter_order_id)
    db.commit()
    return f


def unlock_filter(db: Session, filter_id: str, user: User) -> FilterRecord:
    f = db.get(FilterRecord, filter_id)
    if not f:
        raise DomainError("Bản ghi lọc không tồn tại.")
    if not f.locked:
        raise DomainError("Mẻ lọc này chưa bị khóa.")
    dependent_bottles = db.execute(select(BottleRecord).where(
        BottleRecord.filter_id == filter_id, BottleRecord.locked == true())).scalars().all()
    if dependent_bottles:
        names = ", ".join(b.bottle_code for b in dependent_bottles)
        raise DomainError(f"Phải mở khóa Chiết trước (mẻ chiết: {names}).")
    # Mẻ lọc này có thể là nguồn "lọc lại" cho 1 mẻ lọc khác — phải mở khóa mẻ đó trước.
    downstream_ids = {row[0] for row in db.execute(select(FilterOrderTank.filter_id).where(
        FilterOrderTank.tank_type == "bbt", FilterOrderTank.source_filter_id == filter_id,
        FilterOrderTank.filter_id.is_not(None))).all()}
    if downstream_ids:
        locked_downstream = db.execute(select(FilterRecord).where(
            FilterRecord.filter_id.in_(downstream_ids), FilterRecord.locked == true())).scalars().all()
        if locked_downstream:
            names = ", ".join(x.filter_code for x in locked_downstream)
            raise DomainError(f"Phải mở khóa mẻ lọc lại trước (mẻ: {names}).")
    _unlock(f)
    db.commit()
    _recompute_filter_order_lock(db, f.filter_order_id)
    db.commit()
    return f


def _recompute_filter_order_lock(db: Session, filter_order_id) -> None:
    if not filter_order_id:
        return
    order = db.get(FilterOrder, filter_order_id)
    if not order:
        return
    filters = db.execute(select(FilterRecord).where(FilterRecord.filter_order_id == filter_order_id)).scalars().all()
    should_lock = bool(filters) and all(x.locked for x in filters)
    if should_lock and not order.locked:
        order.locked, order.locked_by, order.locked_at = True, _AUTO, utcnow()
    elif not should_lock and order.locked:
        _unlock(order)
    if order.master_order_id:
        _recompute_filter_master_order_lock(db, order.master_order_id)


def _recompute_filter_master_order_lock(db: Session, master_order_id: str) -> None:
    master = db.get(FilterMasterOrder, master_order_id)
    if not master:
        return
    orders = db.execute(select(FilterOrder).where(FilterOrder.master_order_id == master_order_id)).scalars().all()
    should_lock = bool(orders) and all(o.locked for o in orders)
    if should_lock and not master.locked:
        master.locked, master.locked_by, master.locked_at = True, _AUTO, utcnow()
    elif not should_lock and master.locked:
        _unlock(master)


# ===== Chiết (BottleRecord = mẻ chiết) =====

def lock_bottle(db: Session, bottle_id: str, user: User) -> BottleRecord:
    b = db.get(BottleRecord, bottle_id)
    if not b:
        raise DomainError("Bản ghi chiết không tồn tại.")
    if b.locked:
        raise DomainError("Mẻ chiết này đã được khóa.")
    if b.ended_at is None:
        raise DomainError("Mẻ chiết chưa hoàn thành (chưa bấm Kết thúc).")
    if not b.approved:
        raise DomainError("Mẻ chiết chưa được duyệt (Duyệt KCS) — không thể khóa.")
    if not b.filter_id:
        raise DomainError("Mẻ chiết chưa có tank BBT nguồn — không thể khóa.")
    src = db.get(FilterRecord, b.filter_id)
    if not src or not src.locked:
        raise DomainError(f"Phải khóa mẻ lọc nguồn trước (mẻ {src.filter_code if src else '?'}).")
    _lock(b, user)
    db.commit()
    return b


def unlock_bottle(db: Session, bottle_id: str, user: User) -> BottleRecord:
    b = db.get(BottleRecord, bottle_id)
    if not b:
        raise DomainError("Bản ghi chiết không tồn tại.")
    if not b.locked:
        raise DomainError("Mẻ chiết này chưa bị khóa.")
    _unlock(b)
    db.commit()
    return b
