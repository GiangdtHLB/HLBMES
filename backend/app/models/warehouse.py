"""Kho NVL: sổ cái dịch chuyển kho (StockMovement) trên nền MaterialLot.

MaterialLot giữ tồn hiện tại; StockMovement là ledger bất biến mọi nhập/xuất/
hoàn/sang ngang để dựng thẻ kho và báo cáo nhập-xuất-tồn (tài liệu §7.4, §8.1).

MaterialRequest + MaterialRequestLine: đề nghị nhận kho — 1 phiếu (header) do phân
xưởng tạo có thể gồm NHIỀU dòng vật tư khác nhau (line). Thủ kho công ty xử lý
(duyệt/từ chối) TỪNG dòng độc lập vì mỗi vật tư cần chọn lô riêng.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, UnicodeText, Float, ForeignKey, Unicode
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
    mode: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)  # tu_do|tra_ncc|xuat_theo_de_nghi|dieu_chuyen|dieu_chuyen_nha_may
    reason: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    ref_doc: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    actor: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    # "Hoàn lại" xuất tự do (không áp dụng cho trả NCC): đánh dấu đã hoàn + trỏ tới giao dịch hoàn.
    reversed: Mapped[bool] = mapped_column(default=False)
    reversal_of: Mapped[Optional[str]] = mapped_column(ForeignKey("stock_movement.movement_id"), nullable=True)
    # Chỉ dùng cho mode="dieu_chuyen_nha_may" (Điều chuyển Kho công ty → Nhà máy khác) — các
    # mode khác luôn NULL. destination_factory_id = nhà máy đích; approved_by/approved_at =
    # Trưởng phòng Kế hoạch đã duyệt (xem services/warehouse.py::approve_transfer_to_factory).
    # Một khi đã duyệt, undo_issue() khoá lại — chỉ ADMIN mới "Hoàn lại" được nữa.
    destination_factory_id: Mapped[Optional[str]] = mapped_column(ForeignKey("factory_location.factory_id"), nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    # Chỉ có giá trị khi giao dịch phát sinh từ 1 dòng Đề nghị nhận kho (fulfill_request_line/
    # fulfill_all_lines) — liên kết trực tiếp bằng khóa ngoại thay vì so khớp chuỗi văn bản
    # `reason` (xem delete_request_history) vốn dễ vỡ nếu định dạng lý do từng bị sửa tay.
    request_id: Mapped[Optional[str]] = mapped_column(ForeignKey("material_request.request_id"), nullable=True, index=True)
    request_line_id: Mapped[Optional[str]] = mapped_column(ForeignKey("material_request_line.line_id"), nullable=True)


class FactoryLocation(Base):
    """Danh mục nhà máy khác — đích của Điều chuyển Kho công ty → Nhà máy khác (khác nơi xuất
    đến của WMS/ShipToLocation, vốn dành cho nhà phân phối thành phẩm)."""
    __tablename__ = "factory_location"

    factory_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(Unicode(255))
    address: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    contact: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class TransferPxRequest(Base):
    """Đề nghị điều chuyển Kho phân xưởng → Kho công ty — CHƯA động tồn kho lúc tạo, chỉ khi
    Thủ kho công ty duyệt (approve_transfer_px_request) mới thật sự gọi transfer() dịch chuyển
    lô. status: pending -> approved | rejected. Sau khi approved, `reversed=True` đánh dấu ADMIN
    đã hoàn tác (xem undo_transfer_px_request) — chỉ admin mới hoàn tác được sau khi đã duyệt."""
    __tablename__ = "transfer_px_request"

    request_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    request_code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    lot_id: Mapped[str] = mapped_column(ForeignKey("material_lot.lot_id"), index=True)
    quantity: Mapped[float] = mapped_column(Float)
    uom: Mapped[str] = mapped_column(Unicode(255), default="kg")
    reason: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    status: Mapped[str] = mapped_column(Unicode(255), default="pending", index=True)  # pending|approved|rejected
    movement_id: Mapped[Optional[str]] = mapped_column(ForeignKey("stock_movement.movement_id"), nullable=True)
    reversed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    approved_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    rejected_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    rejected_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    reject_reason: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)


class SangNgangRequest(Base):
    """Đề nghị "Xuất sang ngang" — hàng về CẬP KHO CÔNG TY nhưng đích thực sự là Kho phân
    xưởng. Thủ kho công ty tạo qua create_sang_ngang(): gọi receive() bình thường (tăng tồn Kho
    công ty, ghi StockMovement type=receipt như nhập kho thường — lô vẫn đứng tên Kho công ty),
    rồi tạo bản ghi này với status="pending" — CHƯA chuyển vị trí lô. Chỉ khi Thủ kho phân xưởng
    duyệt (approve_sang_ngang) mới thật sự gọi transfer() đổi lô sang "Kho phân xưởng". Nếu vật
    tư có chỉ tiêu chất lượng bắt buộc, lô sẽ ở trạng thái ON_HOLD (như nhập kho thường) — phân
    xưởng KHÔNG duyệt được cho tới khi KCS duyệt xong (lot.status rời ON_HOLD).

    status: pending -> approved | rejected. Sau khi approved, `reversed=True` đánh dấu ADMIN đã
    hoàn tác (xem undo_sang_ngang) — chỉ admin mới hoàn tác được sau khi đã duyệt."""
    __tablename__ = "sang_ngang_request"

    request_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    request_code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    lot_id: Mapped[str] = mapped_column(ForeignKey("material_lot.lot_id"), index=True)
    quantity: Mapped[float] = mapped_column(Float)
    uom: Mapped[str] = mapped_column(Unicode(255), default="kg")
    reason: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    status: Mapped[str] = mapped_column(Unicode(255), default="pending", index=True)  # pending|approved|rejected
    movement_id: Mapped[Optional[str]] = mapped_column(ForeignKey("stock_movement.movement_id"), nullable=True)
    reversed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    approved_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    rejected_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    rejected_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    reject_reason: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)


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
    # Kỳ kiểm kê thực tế (ngày bắt đầu/kết thúc đếm tại kho) — khác với created_at/posted_at
    # (mốc thao tác trên hệ thống), khai báo tay lúc tạo phiếu, có thể sửa khi còn draft.
    start_date: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    end_date: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
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
