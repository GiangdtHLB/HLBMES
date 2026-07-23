"""WMS — kho thành phẩm: vị trí (location) + đơn vị tồn kho (vỉ/keg), có barcode.

Quản lý trực tiếp theo vỉ/keg (KHÔNG qua pallet/case): mỗi FinishedGoodsUnit là 1 dòng
tồn kho độc lập (1 vỉ = 24 lon cố định theo SKU, 1 keg = 1 đơn vị) — nhập/xuất/FIFO tính
trực tiếp trên từng dòng, không có lớp gom nhóm phía trên. unit_code in được mã vạch
Code39 cho đầu đọc cầm tay/kiosk.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Float, ForeignKey, Integer, Unicode, UnicodeText
from sqlalchemy.orm import Mapped, mapped_column

from ..common import UTCDateTime, new_id, utcnow
from ..database import Base


class WmsLocation(Base):
    __tablename__ = "wms_location"

    loc_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(Unicode(255))
    zone: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    kind: Mapped[str] = mapped_column(Unicode(255), default="bin")     # bin | staging | cold | dock
    capacity: Mapped[int] = mapped_column(Integer, default=10)   # số vỉ/keg tối đa
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class FinishedGoodsUnit(Base):
    """1 vỉ hoặc 1 keg thành phẩm — đơn vị tồn kho nhỏ nhất, độc lập (không gom vào
    pallet/case). Sinh tự động khi duyệt chiết (xem routers/brewing.py::approve_bottle,
    services/wms.py::_create_units — số dòng = ceil(tổng SL / FinishedProduct.pack_size),
    dòng cuối có thể lẻ) hoặc nhập tay (build_units). Nhập/xuất/FIFO/xóa thao tác trực
    tiếp trên từng dòng — không còn khái niệm xuất một phần 1 vỉ/keg."""
    __tablename__ = "finished_goods_unit"

    unit_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    unit_code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)  # "VI-{yymmdd}-{seq}" | "KEG-{yymmdd}-{seq}"
    unit_type: Mapped[str] = mapped_column(Unicode(16), index=True)  # vi | keg
    finished_product_id: Mapped[Optional[str]] = mapped_column(ForeignKey("finished_product.finished_product_id"), nullable=True, index=True)
    product_name: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)  # fallback hiển thị nếu chưa chọn SKU
    lot_code: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=0)  # SL đơn vị nhỏ thật trong vỉ/keg này (dòng cuối có thể lẻ)
    status: Mapped[str] = mapped_column(Unicode(255), default="stored", index=True)  # stored | shipped
    location_id: Mapped[Optional[str]] = mapped_column(ForeignKey("wms_location.loc_id"), nullable=True, index=True)
    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)  # mốc FIFO
    shipped_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    shipment_id: Mapped[Optional[str]] = mapped_column(ForeignKey("shipment.shipment_id"), nullable=True, index=True)
    ship_to_id: Mapped[Optional[str]] = mapped_column(ForeignKey("ship_to_location.ship_to_id"), nullable=True, index=True)
    # Đánh dấu vỉ/keg này đến từ "Nhập bia cận date" (xem NearExpiryEntry) — cho phép Xuất
    # kho lọc riêng để xuất đúng lô cận date khi cần, tách biệt khỏi FIFO mặc định.
    is_near_expiry: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class ShipToLocation(Base):
    """Danh mục nơi xuất đến (thường là nhà phân phối) — gắn vào từng vỉ/keg lúc xuất kho
    để truy xuất/thu hồi biết lô nào đã đi đâu (xem genealogy.NODE_REGISTRY["ship_to"])."""
    __tablename__ = "ship_to_location"

    ship_to_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(Unicode(255))
    kind: Mapped[str] = mapped_column(Unicode(255), default="distributor")  # distributor|retailer|export|other
    address: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    contact: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Vehicle(Base):
    """Danh mục xe/lái xe vận chuyển hàng — tra cứu nhanh biển số/lái xe/tải trọng/số pallet
    chở được khi lập Lệnh đóng hàng hoặc Phiếu xuất kho."""
    __tablename__ = "wms_vehicle"

    vehicle_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    plate: Mapped[str] = mapped_column(Unicode(32), unique=True, index=True)
    driver_name: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    driver_short_name: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    capacity_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pallet_capacity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(Unicode(32), nullable=True)
    team: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Shipment(Base):
    """1 phiếu xuất kho — gồm nhiều FinishedGoodsUnit (vỉ/keg) được gắn shipment_id khi
    xuất (cho phép chọn nhiều vỉ/keg từ nhiều lô khác nhau trong cùng 1 phiếu); không còn
    bảng dòng riêng (ShipmentLine) — khi in phiếu, gom nhóm theo (product, lot_code) trực
    tiếp trên các unit thuộc phiếu đó."""
    __tablename__ = "shipment"

    shipment_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    shipment_code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    ship_to_id: Mapped[str] = mapped_column(ForeignKey("ship_to_location.ship_to_id"), index=True)
    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    note: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)  # Lý do xuất kho
    fifo_ok: Mapped[bool] = mapped_column(Boolean, default=True)  # phiếu có tuân đúng thứ tự FIFO không
    shipment_type: Mapped[str] = mapped_column(Unicode(32), default="normal")  # normal|promo|return — nhãn phân loại
    # Các trường còn lại để in đúng mẫu "PHIẾU XUẤT KHO" (Mẫu số 02-VT, TT 99/2025/TT-BTC).
    recipient_name: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)   # Họ tên người nhận hàng
    recipient_dept: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)   # Địa chỉ (bộ phận)
    driver_name: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)      # Lái xe
    vehicle_plate: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)     # Biển số xe
    from_location: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)    # Xuất tại kho (ngăn lô)
    delivery_place: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)   # Địa điểm


class NearExpiryEntry(Base):
    """Lịch sử riêng cho "Nhập bia cận date" — bia đã xuất/tồn lâu, cận hạn, được nhập lại
    (tăng tồn kho công ty) và tách theo dõi riêng khỏi lịch sử nhập/xuất thông thường.
    direction="in": lúc khai báo nhập lại (tự nhận lô chiết theo ngày giờ khai báo, xem
    services/wms.py::find_bottle_for_datetime). direction="out": tự động ghi thêm 1 dòng khi
    1 phiếu xuất kho (Shipment) có chọn "chỉ xuất bia cận date" — cùng is_near_expiry=True
    trên các FinishedGoodsUnit liên quan."""
    __tablename__ = "near_expiry_entry"

    entry_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    direction: Mapped[str] = mapped_column(Unicode(16), index=True)  # in | out
    product_name: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    lot_code: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    unit_type: Mapped[str] = mapped_column(Unicode(16))  # vi | keg
    quantity: Mapped[int] = mapped_column(Integer)  # số vỉ/keg
    declared_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)  # ngày giờ khai báo (chỉ có ở direction="in")
    bottle_id: Mapped[Optional[str]] = mapped_column(ForeignKey("bottle_record.bottle_id"), nullable=True, index=True)  # lô chiết tự nhận
    shipment_id: Mapped[Optional[str]] = mapped_column(ForeignKey("shipment.shipment_id"), nullable=True, index=True)  # phiếu xuất (chỉ có ở direction="out")
    note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    # unit_code các vỉ/keg do chính lần khai báo direction="in" này tạo ra (nối bằng dấu phẩy)
    # — cho phép Hoàn tác xoá đúng các đơn vị đó, không đụng tới đơn vị của lần khai báo khác
    # dùng chung bottle_id/lot_code. Chỉ có ở direction="in".
    unit_codes: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    reversed: Mapped[bool] = mapped_column(Boolean, default=False)


class LoadSlip(Base):
    """1 "Biên bản bàn giao hàng hóa" cho 1 xe — gộp từ mọi dòng cùng SỐ XE trong 1 sheet
    (HL/ĐM) của file Excel "Lệnh đóng hàng" ngày đó (do bộ phận điều vận lập). Đây là chứng
    từ nội bộ bàn giao hàng từ Kho thành phẩm sang xe/lái xe đi giao — KHÔNG trừ tồn kho
    WMS (khác với Shipment/Pallet — file lệnh đóng hàng không gắn với pallet cụ thể nào)."""
    __tablename__ = "load_slip"

    load_slip_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    slip_code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    sheet_type: Mapped[str] = mapped_column(Unicode(16), index=True)  # "HL" | "ĐM"
    shift_label: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)   # "Ca 3" (từ ô A2)
    order_date: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)  # Ngày (từ ô A2)
    vehicle_plate: Mapped[str] = mapped_column(Unicode(64), index=True)   # SỐ XE
    driver_name: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)   # TÊN LX
    routes: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)   # NPP VÀ NVBH, gộp các tuyến
    note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)   # GHI CHÚ gộp
    source_file_name: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    # Bên giao/Bên nhận — điền tay trước khi in, giống mẫu "BIÊN BẢN BÀN GIAO HÀNG HÓA".
    issuer_name: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    issuer_title: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    issuer_dept: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    recipient_name: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    recipient_title: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    recipient_unit: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class LoadSlipLine(Base):
    """1 dòng hàng hóa bàn giao — mỗi cột SKU có SL > 0 trong lệnh đóng hàng của xe đó ra
    đúng 1 dòng ở đây. Cột "LON/Lốc ... KM" (khuyến mại rời, không đủ 1 vỉ/thùng) tách thành
    dòng riêng (is_promo=True, ĐVT Lon/Lốc) — đúng như cách file nguồn đã tách sẵn, không
    cần tính lại số lẻ."""
    __tablename__ = "load_slip_line"

    line_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    load_slip_id: Mapped[str] = mapped_column(ForeignKey("load_slip.load_slip_id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    product_name: Mapped[str] = mapped_column(Unicode(255))   # tên cột gốc từ Excel, VD "Vỉ SP Sleek"
    uom: Mapped[str] = mapped_column(Unicode(64))   # Vỉ|Két|Hộp|Lon|Lốc|Gông|Chai|Keg...
    quantity: Mapped[float] = mapped_column(Float, default=0)
    is_promo: Mapped[bool] = mapped_column(Boolean, default=False)   # dòng KM rời hay dòng chính
    note: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)   # VD "Theo QĐ KM 371"
