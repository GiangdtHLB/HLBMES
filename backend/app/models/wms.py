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


class WmsWarehouse(Base):
    """Kho thành phẩm (VD "Kho Đông Mai", "Kho Hạ Long") — cấp cha của WmsLocation. Mỗi kho
    chứa nhiều vị trí (WmsLocation.warehouse_id) — tách riêng để biết 1 lô đang nằm ở KHO nào,
    VỊ TRÍ nào trong kho đó, thay vì chỉ có 1 cấp "vị trí" phẳng như trước (xem migration
    d8f3a1c2b4e6_wms_warehouse.py — mỗi vị trí hiện có tự động được nâng cấp thành 1 kho cùng
    mã/tên để không đổi dữ liệu cũ, người dùng khai báo thêm vị trí mới trong kho đó sau)."""
    __tablename__ = "wms_warehouse"

    warehouse_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(Unicode(255))
    address: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class WmsLocation(Base):
    __tablename__ = "wms_location"

    loc_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(Unicode(255))
    zone: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    kind: Mapped[str] = mapped_column(Unicode(255), default="bin")     # bin | staging | cold | dock
    capacity: Mapped[int] = mapped_column(Integer, default=10)   # số vỉ/keg tối đa
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Kho thành phẩm cha — nullable để không phá các nơi tạo vị trí qua API cũ (test/import)
    # chưa kịp gửi trường này, nhưng UI luôn bắt chọn khi khai báo vị trí mới (xem VIEWS.wms).
    warehouse_id: Mapped[Optional[str]] = mapped_column(ForeignKey("wms_warehouse.warehouse_id"), nullable=True, index=True)


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
    ship_to_id: Mapped[Optional[str]] = mapped_column(ForeignKey("supplier.supplier_id"), nullable=True, index=True)
    # Đánh dấu vỉ/keg này đến từ "Nhập bia cận date" (xem NearExpiryEntry) — cho phép Xuất
    # kho lọc riêng để xuất đúng lô cận date khi cần, tách biệt khỏi FIFO mặc định.
    is_near_expiry: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # Đánh dấu vỉ/keg này đến từ "Nhập bia gửi" (xem ConsignedEntry) — bia đã xuất phiếu
    # trong ngày nhưng xe giao không hết, mang về gửi lại kho (KHÔNG phải cận date, KHÔNG
    # phải đổi trả nhà phân phối) — tách riêng khỏi FIFO mặc định như is_near_expiry, và
    # được ưu tiên xuất TRƯỚC cả bia cận date (xem VIEWS.wms sort trong xuatkho).
    is_consigned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # Nguồn gốc dòng nhập kho: "chiet" (tự động sau khi duyệt chiết, xem routers/brewing.py::
    # approve_bottle), "manual" ("Nhập kho thủ công" thường, không phải tồn đầu — xem
    # services/wms.py::build_units) hay NULL (tồn đầu/import/near-expiry/consigned/dữ liệu cũ).
    # Cả "chiet" lẫn "manual" đều cần Trưởng bộ phận kho duyệt nhập kho (received_confirmed_by/
    # at, quyền wms.confirm_receipt, xem confirm_receipt_by_lot) — sau khi duyệt, không xóa
    # được nữa (delete_unit/delete_units/delete_units_by_criteria). Riêng "manual" còn bị chặn
    # XUẤT (create_shipment) tới khi duyệt (xem _consume_lot_rows(block_pending_manual=True)) —
    # "chiet" thì không chặn xuất (chỉ chặn xóa), giữ nguyên hành vi cũ để không phá luồng
    # duyệt chiết → xuất ngay đã có sẵn nhiều nơi dùng. Tồn đầu (is_opening_balance) tự động
    # được coi là đã duyệt ngay lúc tạo (_create_units) vì đã yêu cầu quyền ADMIN riêng.
    source: Mapped[Optional[str]] = mapped_column(Unicode(32), nullable=True, index=True)
    received_confirmed_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    received_confirmed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    # "Loại xuất" (normal/promo/return) của CHÍNH dòng này tại thời điểm xuất — riêng từng
    # đơn vị, KHÔNG còn dùng chung 1 giá trị cho cả Shipment (1 phiếu xuất cho 1 nhà phân phối
    # có thể gồm nhiều sản phẩm với loại xuất khác nhau). NULL nếu chưa xuất hoặc dữ liệu cũ
    # trước khi có field này — coi như "normal". Shipment.shipment_type vẫn giữ nguyên cột cũ,
    # nay chỉ còn ý nghĩa tóm tắt (giống nhau -> giá trị đó, khác nhau -> "mixed").
    shipment_line_type: Mapped[Optional[str]] = mapped_column(Unicode(32), nullable=True, index=True)
    # Phiếu điều chuyển nội bộ GẦN NHẤT đã chạm vào dòng này (xem WmsTransfer/create_transfer) —
    # mirror shipment_id nhưng KHÔNG đổi status (điều chuyển không làm giảm tồn kho, đơn vị vẫn
    # "stored" và có thể bị 1 thao tác khác (điều chuyển/xuất kho) chạm vào tiếp sau đó, lúc này
    # trường này bị ghi đè/xóa — dùng để undo_transfer() phát hiện đơn vị đã bị "chạm" bởi thao
    # tác khác từ sau khi phiếu này tạo, tránh hoàn tác sai vị trí).
    transfer_id: Mapped[Optional[str]] = mapped_column(ForeignKey("wms_transfer.transfer_id"), nullable=True, index=True)


class Vehicle(Base):
    """Danh mục xe/lái xe vận chuyển hàng — tra cứu nhanh biển số/lái xe/tải trọng/số pallet
    chở được khi lập Lệnh đóng hàng hoặc Phiếu xuất kho."""
    __tablename__ = "wms_vehicle"

    vehicle_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    # Mã cố định do hệ thống tự sinh ("XE0001", ...) — biển số có thể đổi (đổi biển số, xe
    # khác thay xe cũ...) nhưng mã này không đổi, dùng làm liên kết ổn định cho báo cáo
    # lượt xe (xem services/wms.py::_gen_vehicle_code, vehicle_trip_report).
    vehicle_code: Mapped[str] = mapped_column(Unicode(32), unique=True, index=True)
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
    ship_to_id: Mapped[str] = mapped_column(ForeignKey("supplier.supplier_id"), index=True)
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
    # Liên kết ổn định tới Danh mục lái xe (Vehicle) — driver_name/vehicle_plate ở trên vẫn
    # giữ nguyên dạng text để in phiếu/lịch sử, vehicle_id dùng cho báo cáo lượt xe/tải trọng
    # (vehicle_trip_report) vì không đổi theo biển số như 2 cột text kia.
    vehicle_id: Mapped[Optional[str]] = mapped_column(ForeignKey("wms_vehicle.vehicle_id"), nullable=True, index=True)
    # Km và số lít xăng của chuyến — chỉ điền được sau khi phiếu đã Duyệt (confirmed_by), xem
    # services/wms.py::update_shipment_trip. Dùng cho báo cáo định mức nhiên liệu.
    km: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fuel_liters: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Trưởng bộ phận kho xác nhận (quyền wms.confirm_shipment) — sau khi xác nhận, chỉ ADMIN
    # mới "Hoàn tác" được (xem services/wms.py::confirm_shipment/undo_shipment).
    confirmed_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)


class WmsTransfer(Base):
    """1 phiếu điều chuyển nội bộ — mirror y hệt Shipment (chọn theo sản phẩm/lô/loại đơn vị/số
    lượng, hệ thống tự chọn FIFO cũ nhất, có xe/lái xe/km/lít xăng, Duyệt/Hoàn tác, in phiếu,
    lịch sử riêng) NHƯNG đích là 1 WmsLocation (không phải Supplier/ship_to) và KHÔNG làm giảm
    tổng tồn kho toàn công ty: create_transfer() chỉ đổi FinishedGoodsUnit.location_id, KHÔNG
    đổi status, KHÔNG tạo genealogy edge ra ngoài, KHÔNG đụng lot_code — giữ nguyên mã chiết để
    truy xuất nguồn gốc không đứt (xem services/wms.py::create_transfer). Vị trí TRƯỚC khi
    chuyển của mỗi đơn vị ghi ở WmsTransferLine.from_location_id để Hoàn tác trả đúng lại (khác
    Shipment — Xuất kho luôn xóa location_id nên undo_shipment không trả lại được vị trí gốc)."""
    __tablename__ = "wms_transfer"

    transfer_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    transfer_code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    to_location_id: Mapped[str] = mapped_column(ForeignKey("wms_location.loc_id"), index=True)
    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    note: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    fifo_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    driver_name: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    vehicle_plate: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    vehicle_id: Mapped[Optional[str]] = mapped_column(ForeignKey("wms_vehicle.vehicle_id"), nullable=True, index=True)
    # Vị trí xuất phát — tự suy ra từ location_id của các đơn vị được chọn TRƯỚC khi chuyển,
    # mirror Shipment.from_location (có thể gồm nhiều vị trí khác nhau, cách nhau dấu phẩy).
    from_location: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    km: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fuel_liters: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confirmed_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)


class WmsTransferLine(Base):
    """1 dòng trong phiếu điều chuyển — CHỈ ghi vị trí TRƯỚC khi chuyển của 1 FinishedGoodsUnit
    cụ thể (from_location_id), để undo_transfer() trả đúng lại. Không chép lại product/lot/
    quantity — đã có sẵn trên chính FinishedGoodsUnit qua unit_id, tránh lệch dữ liệu nếu đơn vị
    bị tách dòng (_consume_lot_rows) sau đó. Giữ lại NGUYÊN VẸN sau khi hoàn tác (không xóa) —
    coi như lịch sử; undo_transfer() gọi lại lần 2 sẽ thấy transfer_id trên FinishedGoodsUnit đã
    bị xóa/đổi khác nên tự nhiên báo "không còn gì để hoàn tác", không cần cờ riêng."""
    __tablename__ = "wms_transfer_line"

    line_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    transfer_id: Mapped[str] = mapped_column(ForeignKey("wms_transfer.transfer_id"), index=True)
    unit_id: Mapped[str] = mapped_column(ForeignKey("finished_goods_unit.unit_id"), index=True)
    from_location_id: Mapped[Optional[str]] = mapped_column(ForeignKey("wms_location.loc_id"), nullable=True)


class NearExpiryEntry(Base):
    """Lịch sử riêng cho "Nhập bia cận date" — bia đã xuất/tồn lâu, cận hạn, được nhập lại
    (tăng tồn kho công ty) và tách theo dõi riêng khỏi lịch sử nhập/xuất thông thường.
    direction="in": khai báo Sản phẩm + SL + Vị trí nhận trực tiếp (KHÔNG còn tự nhận lô chiết
    theo ngày giờ — thực tế tồn cận date thường gộp từ nhiều lô khác nhau nên không thể quy về
    đúng 1 lô chiết gốc). Từ khi có duyệt (approved_by/at): khai báo CHƯA tăng tồn kho ngay —
    chỉ giữ lot_code đã sinh sẵn (qua services/wms.py::_gen_candate_lot_code) làm chỗ đứng;
    Trưởng bộ phận kho (quyền wms.confirm_receipt) bấm "Duyệt" (services/wms.py::
    approve_near_expiry_entry) mới thực sự tạo FinishedGoodsUnit (is_near_expiry=True) và tăng
    tồn kho — lúc đó unit_codes mới được ghi. Trước khi duyệt: còn sửa được (quantity/vị trí/
    ghi chú, xem update_near_expiry_entry) và hủy được (undo_near_expiry_entry chỉ đánh dấu
    reversed, chưa có đơn vị nào để xoá). Sau khi duyệt: khoá hẳn — không sửa, không hoàn tác
    được nữa (mirror StockCount.approved_by, xem services/warehouse.py::approve_count).
    direction="out": tự động ghi thêm 1 dòng khi 1 phiếu xuất kho (Shipment) có chọn "chỉ xuất
    bia cận date" — cùng is_near_expiry=True trên các FinishedGoodsUnit liên quan, không qua
    bước duyệt (đã là hàng thật đang xuất). bottle_id giữ lại CHỈ để tương thích các bản khai cũ
    (tạo trước khi đổi cách khai báo này) — bản khai mới luôn NULL."""
    __tablename__ = "near_expiry_entry"

    entry_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    direction: Mapped[str] = mapped_column(Unicode(16), index=True)  # in | out
    finished_product_id: Mapped[Optional[str]] = mapped_column(ForeignKey("finished_product.finished_product_id"), nullable=True, index=True)
    product_name: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    lot_code: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    unit_type: Mapped[str] = mapped_column(Unicode(16))  # vi | keg
    quantity: Mapped[int] = mapped_column(Integer)  # số vỉ/keg
    location_id: Mapped[Optional[str]] = mapped_column(ForeignKey("wms_location.loc_id"), nullable=True, index=True)  # vị trí nhận (chỉ có ở direction="in")
    declared_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)  # ngày giờ khai báo (chỉ có ở direction="in")
    bottle_id: Mapped[Optional[str]] = mapped_column(ForeignKey("bottle_record.bottle_id"), nullable=True, index=True)  # lô chiết tự nhận — chỉ bản khai cũ
    shipment_id: Mapped[Optional[str]] = mapped_column(ForeignKey("shipment.shipment_id"), nullable=True, index=True)  # phiếu xuất (chỉ có ở direction="out")
    note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    # unit_code các vỉ/keg do chính lần khai báo direction="in" này tạo ra (nối bằng dấu phẩy),
    # chỉ được ghi lúc DUYỆT (không còn ghi ngay lúc tạo) — chỉ có ở direction="in".
    unit_codes: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    reversed: Mapped[bool] = mapped_column(Boolean, default=False)
    # Trưởng bộ phận kho duyệt (quyền wms.confirm_receipt) — trước khi duyệt, khai báo CHƯA
    # tăng tồn kho (chỉ có ở direction="in"). Sau khi duyệt: khoá, không sửa/hoàn tác được nữa.
    approved_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)


class ConsignedEntry(Base):
    """Lịch sử riêng cho "Nhập bia gửi" — mirror y hệt NearExpiryEntry nhưng cho trường hợp
    KHÁC: xe đã xuất phiếu đi giao trong ngày nhưng giao không hết, mang phần dư về GỬI lại
    kho (không phải bia cận date, không phải đổi trả nhà phân phối). direction="in": khai
    báo Sản phẩm + SL + Vị trí nhận trực tiếp, tự sinh 1 lot_code GỬI RIÊNG (xem
    services/wms.py::_gen_consigned_lot_code) để không gộp chung dòng với tồn thường của SKU
    đó ở Xuất kho. direction="out": tự động ghi thêm 1 dòng khi 1 phiếu xuất kho (Shipment)
    có chọn "chỉ xuất bia gửi" — cùng is_consigned=True trên các FinishedGoodsUnit liên quan.
    Khác NearExpiryEntry ở chỗ: khi tính báo cáo xuất theo ca/ngày (finished_goods_shift_report),
    lượng xuất từ lô GỬI phải bị TRỪ ra khỏi tổng xuất trong kỳ — vì lô này thực chất là phần
    bia đã được tính vào lượt xuất buổi sáng (phiếu gốc), xuất lại lần 2 sẽ bị đếm trùng nếu
    không trừ. Bia cận date thì KHÔNG trừ vì không phải xuất trùng của cùng 1 chuyến.
    Cũng qua duyệt Trưởng bộ phận kho như NearExpiryEntry (xem approved_by/at ở đó và
    services/wms.py::approve_consigned_entry) — khai báo CHƯA tăng tồn kho tới khi duyệt."""
    __tablename__ = "consigned_entry"

    entry_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    direction: Mapped[str] = mapped_column(Unicode(16), index=True)  # in | out
    finished_product_id: Mapped[Optional[str]] = mapped_column(ForeignKey("finished_product.finished_product_id"), nullable=True, index=True)
    product_name: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    lot_code: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    unit_type: Mapped[str] = mapped_column(Unicode(16))  # vi | keg
    quantity: Mapped[int] = mapped_column(Integer)  # số vỉ/keg
    location_id: Mapped[Optional[str]] = mapped_column(ForeignKey("wms_location.loc_id"), nullable=True, index=True)  # vị trí nhận — chỉ có ở direction="in"
    declared_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)  # ngày giờ khai báo — chỉ có ở direction="in"
    # Xe đã mang bia gửi này về — bắt buộc ở tầng service/schema cho direction="in" (xem
    # create_consigned_entry), nullable ở DB vì dòng direction="out" do hệ thống tự tạo trong
    # create_shipment không có xe. Dùng để hiện "xe đã gửi" ở picker Xuất kho.
    vehicle_id: Mapped[Optional[str]] = mapped_column(ForeignKey("wms_vehicle.vehicle_id"), nullable=True, index=True)
    shipment_id: Mapped[Optional[str]] = mapped_column(ForeignKey("shipment.shipment_id"), nullable=True, index=True)  # phiếu xuất — chỉ có ở direction="out"
    note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    # unit_code các vỉ/keg do chính lần khai báo direction="in" này tạo ra (nối bằng dấu phẩy),
    # chỉ được ghi lúc DUYỆT. Chỉ có ở direction="in".
    unit_codes: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    reversed: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)


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
