"""Kho NVL: sổ cái dịch chuyển kho (StockMovement) trên nền MaterialLot.

MaterialLot giữ tồn hiện tại; StockMovement là ledger bất biến mọi nhập/xuất/
hoàn/sang ngang để dựng thẻ kho và báo cáo nhập-xuất-tồn (tài liệu §7.4, §8.1).

MaterialRequest + MaterialRequestLine: đề nghị nhận kho — 1 phiếu (header) do phân
xưởng tạo có thể gồm NHIỀU dòng vật tư khác nhau (line). Thủ kho công ty xử lý
(duyệt/từ chối) TỪNG dòng độc lập vì mỗi vật tư cần chọn lô riêng.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import UnicodeText, Float, ForeignKey, Unicode
from sqlalchemy.orm import Mapped, mapped_column

from ..common import UTCDateTime, new_id, utcnow
from ..database import Base


class StockMovement(Base):
    __tablename__ = "stock_movement"

    movement_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    # receipt=nhập | issue=xuất | return=nhập hoàn | transfer=xuất sang ngang | adjust
    movement_type: Mapped[str] = mapped_column(Unicode(255), index=True)
    material_id: Mapped[Optional[str]] = mapped_column(ForeignKey("material.material_id"), index=True)
    lot_id: Mapped[Optional[str]] = mapped_column(ForeignKey("material_lot.lot_id"), index=True)
    lot_code: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    quantity: Mapped[float] = mapped_column(Float)        # luôn dương; dấu suy từ type
    uom: Mapped[str] = mapped_column(Unicode(255), default="kg")
    location_from: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    location_to: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    mode: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)  # tu_do|tra_ncc|xuat_theo_de_nghi|dieu_chuyen
    reason: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    ref_doc: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    actor: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    # "Hoàn lại" xuất tự do (không áp dụng cho trả NCC): đánh dấu đã hoàn + trỏ tới giao dịch hoàn.
    reversed: Mapped[bool] = mapped_column(default=False)
    reversal_of: Mapped[Optional[str]] = mapped_column(ForeignKey("stock_movement.movement_id"), nullable=True)


class MaterialRequest(Base):
    """Phiếu đề nghị nhận kho (header) — 1 phiếu có thể gồm nhiều dòng vật tư (MaterialRequestLine).

    `source_type`/`source_id` (tuỳ chọn): gắn phiếu với 1 Lệnh nấu (brew_order) hoặc 1 Lệnh
    lọc lớn (filter_master_order) — chỉ để tham chiếu/lọc/báo cáo (KHÔNG ràng buộc số lượng
    dòng theo lệnh), vì phòng xưởng vẫn tự do thêm/sửa/xoá dòng sau khi hệ thống tự động điền
    sẵn từ định mức NVL của lệnh (xem services/warehouse.py::preview_source_materials)."""

    __tablename__ = "material_request"

    request_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    request_code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    requested_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    source_type: Mapped[Optional[str]] = mapped_column(Unicode(32), nullable=True, index=True)  # brew_order|filter_master_order
    source_id: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True, index=True)


class MaterialRequestLine(Base):
    """Một dòng vật tư trong phiếu — xử lý (duyệt/từ chối) độc lập theo từng dòng."""

    __tablename__ = "material_request_line"

    line_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    request_id: Mapped[str] = mapped_column(ForeignKey("material_request.request_id"), index=True)
    seq: Mapped[int] = mapped_column(default=0)
    material_id: Mapped[str] = mapped_column(ForeignKey("material.material_id"), index=True)
    quantity: Mapped[float] = mapped_column(Float)
    uom: Mapped[str] = mapped_column(Unicode(255), default="kg")
    preferred_lot_id: Mapped[Optional[str]] = mapped_column(ForeignKey("material_lot.lot_id"), nullable=True)
    # pending -> fulfilled | rejected
    status: Mapped[str] = mapped_column(Unicode(255), default="pending", index=True)
    fulfilled_lot_id: Mapped[Optional[str]] = mapped_column(ForeignKey("material_lot.lot_id"), nullable=True)
    fulfilled_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fulfilled_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    fulfilled_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    # Chỉ có giá trị SAU khi fulfilled — chụp lại (snapshot) ngay lúc xuất xem lô đã chọn có
    # phải lô cũ nhất (FIFO) hiện có lúc đó hay không; None khi còn pending (chưa xuất, xem
    # cảnh báo FIFO trực tiếp/live ở frontend thay vì suy đoán trước).
    fifo_ok: Mapped[Optional[bool]] = mapped_column(nullable=True)


class StockCount(Base):
    """Phiếu kiểm kê định kỳ (header) — đối chiếu tồn hệ thống (MaterialLot.quantity) với
    tồn thực tế đếm tại kho. Tạo phiếu = chụp (snapshot) tồn hệ thống hiện tại của mọi lô
    tại 1 kho vào StockCountLine.system_qty; nhân viên điền counted_qty; khi "post" (chốt),
    lệch (nếu có) được ghi thành StockMovement(movement_type="adjust") và MaterialLot.quantity
    được cập nhật thẳng bằng counted_qty (MaterialLot.quantity là nguồn sự thật duy nhất về
    tồn kho, không phải suy ra từ tổng StockMovement — xem stock_on_hand)."""
    __tablename__ = "stock_count"

    count_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    count_code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    location: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)  # lọc theo Kho công ty/phân xưởng, giống MaterialLot.location
    note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    status: Mapped[str] = mapped_column(Unicode(255), default="draft", index=True)  # draft -> posted
    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    posted_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    posted_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    # Duyệt (bởi giám đốc nhà máy trở lên) — CHỈ áp dụng sau khi đã chốt (post), chỉ để xác
    # nhận đã xem/đồng ý, không đổi lại số liệu. Một khi đã duyệt thì khóa hẳn — không cho
    # hoàn tác nữa (xem services/warehouse.py::undo_count).
    approved_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)


class StockCountLine(Base):
    """1 dòng lô trong phiếu kiểm kê — mỗi lô đang có tồn tại kho được kiểm kê thành 1 dòng."""
    __tablename__ = "stock_count_line"

    line_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    count_id: Mapped[str] = mapped_column(ForeignKey("stock_count.count_id"), index=True)
    material_id: Mapped[str] = mapped_column(ForeignKey("material.material_id"), index=True)
    lot_id: Mapped[str] = mapped_column(ForeignKey("material_lot.lot_id"), index=True)
    system_qty: Mapped[float] = mapped_column(Float)  # chụp lúc tạo phiếu
    counted_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # None = chưa đếm
    uom: Mapped[str] = mapped_column(Unicode(255), default="kg")
    note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
