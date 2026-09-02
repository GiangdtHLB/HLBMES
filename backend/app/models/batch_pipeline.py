"""Pipeline thực thi mới cho "Mẻ sản xuất" (BatchExecution) theo blueprint 4 lớp:
mẻ nấu (BatchExecution, có sẵn) → tank lên men (BatchTank) → lô lọc (BatchFilterLot) →
lô thành phẩm (BatchPackLot). Mirror đúng shape/quy ước của models/brewing.py (FermentRecord/
FilterOrderTank/FilterRecord/BottleRecord) nhưng độc lập hoàn toàn — module Nấu-Lọc-Chiết cũ
(BrewBatch/FermentRecord/FilterRecord/BottleRecord) giữ nguyên, không đụng tới.

Chỉ tiêu chất lượng (StageQcGroup) TÁI SỬ DỤNG đúng stage name cũ ("len_men_chinh"/"loc"/
"thanh_pham") qua scope_type mới ("batch_tank"/"batch_filter_lot"/"batch_pack_lot") — xem
services/qc_catalog.py::stage_qc_status (scope_type tự do, không hardwire theo model)."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Float, ForeignKey, Integer, Unicode, UnicodeText, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..common import QualityStatus, UTCDateTime, new_id, utcnow
from ..database import Base


class BatchTank(Base):
    """Tank lên men mới — gộp N mẻ nấu (BatchExecution) vào 1 tank (mirror FermentRecord).
    on_hand giảm theo DELTA khi rút vào lô lọc (mirror FermentRecord.on_hand_cct)."""
    __tablename__ = "batch_tank"
    __table_args__ = (UniqueConstraint("tank_year", "tank_code", name="uq_batch_tank_year_code"),)

    tank_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    tank_code: Mapped[str] = mapped_column(Unicode(64), index=True)
    tank_year: Mapped[int] = mapped_column(Integer, index=True)
    tank_lm: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True, index=True)  # tank vật lý
    product_id: Mapped[Optional[str]] = mapped_column(ForeignKey("product.product_id"), nullable=True, index=True)
    volume_hl: Mapped[float] = mapped_column(Float, default=0.0)     # tổng nạp ban đầu (= tổng actual_qty các mẻ)
    on_hand: Mapped[float] = mapped_column(Float, default=0.0)       # đang tồn
    # KHÔNG còn dùng để hiển thị — trạng thái thật suy hoàn toàn từ on_hand/volume_hl + có Lệnh
    # lọc tham chiếu chưa (xem services/batch_pipeline.py::_tank_status, yêu cầu người dùng
    # 2026-09-01: len_men/cho_loc/loc_1_phan/da_loc_het). Giữ cột lại cho tương thích, không đọc.
    status: Mapped[str] = mapped_column(Unicode(255), default="len_men")
    note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    locked_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    locked_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    quality_status: Mapped[str] = mapped_column(Unicode(255), default=QualityStatus.RELEASED.value)


class BatchTankLink(Base):
    """N mẻ nấu (BatchExecution) -> 1 BatchTank — mirror FermentBrewLink."""
    __tablename__ = "batch_tank_link"

    link_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    tank_id: Mapped[str] = mapped_column(ForeignKey("batch_tank.tank_id"), index=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batch_execution.batch_id"), index=True)


class BatchFilterOrder(Base):
    """Lệnh lọc — khai báo TRƯỚC các nguồn (tank lên men và/hoặc lô lọc lọc lại) + SL kế hoạch
    cho 1 đợt lọc, mirror FilterOrder (module Nấu-Lọc-Chiết cũ, bỏ lớp "Lệnh lọc lớn"
    FilterMasterOrder vì không cần thiết cho pipeline mới). Khi tạo Lô lọc thật
    (BatchFilterLot), người dùng CHỌN 1 lệnh lọc còn dùng được thay vì tự chọn lại nguồn — xem
    services/batch_pipeline.py::draw_from_filter_order (mirror routers/brewing.py::add_filter)."""
    __tablename__ = "batch_filter_order"
    __table_args__ = (UniqueConstraint("order_year", "order_code", name="uq_batch_filter_order_year_code"),)

    order_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    order_code: Mapped[str] = mapped_column(Unicode(64), index=True)
    order_year: Mapped[int] = mapped_column(Integer, index=True)
    blend_mode: Mapped[str] = mapped_column(Unicode(32), default="khong_phoi")   # khong_phoi/phoi
    planned_volume_hl: Mapped[float] = mapped_column(Float, default=0.0)    # = tổng planned_v_dich_hl các nguồn
    volume_tolerance_hl: Mapped[float] = mapped_column(Float, default=0.0)
    beer_type_id: Mapped[Optional[str]] = mapped_column(ForeignKey("beer_type.beer_type_id"), nullable=True, index=True)
    finished_product_id: Mapped[Optional[str]] = mapped_column(ForeignKey("finished_product.finished_product_id"),
                                                                nullable=True, index=True)
    kcs_lot_no: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)   # người lập tự đánh số
    note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    locked_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    locked_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)


class BatchFilterOrderSource(Base):
    """1 nguồn KẾ HOẠCH (chưa thực rút dịch) khai báo trong 1 BatchFilterOrder — mirror dòng
    "template" của FilterOrderTank (filter_id IS NULL). Khi tạo BatchFilterLot từ lệnh này, mỗi
    dòng ở đây được NHÂN BẢN thành 1 BatchFilterLotSource thật (mirror add_filter)."""
    __tablename__ = "batch_filter_order_source"

    link_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    order_id: Mapped[str] = mapped_column(ForeignKey("batch_filter_order.order_id"), index=True)
    source_type: Mapped[str] = mapped_column(Unicode(16), default="tank")   # tank | filter_lot (lọc lại)
    source_tank_id: Mapped[Optional[str]] = mapped_column(ForeignKey("batch_tank.tank_id"), nullable=True, index=True)
    source_filter_lot_id: Mapped[Optional[str]] = mapped_column(ForeignKey("batch_filter_lot.filter_lot_id"),
                                                                 nullable=True, index=True)
    reason: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)   # bắt buộc khi lọc lại
    planned_v_dich_hl: Mapped[float] = mapped_column(Float, default=0.0)
    seq: Mapped[int] = mapped_column(Integer, default=1)


class BatchFilterLot(Base):
    """Lô lọc mới — rút dịch từ 1..N BatchTank (phối) hoặc lọc lại từ 1..N BatchFilterLot khác
    (mirror FilterRecord). on_hand giảm theo DELTA khi tách vào lô thành phẩm."""
    __tablename__ = "batch_filter_lot"
    __table_args__ = (UniqueConstraint("filter_lot_year", "filter_lot_code", name="uq_batch_filter_lot_year_code"),)

    filter_lot_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    filter_lot_code: Mapped[str] = mapped_column(Unicode(64), index=True)
    filter_lot_year: Mapped[int] = mapped_column(Integer, index=True)
    order_id: Mapped[Optional[str]] = mapped_column(ForeignKey("batch_filter_order.order_id"), nullable=True, index=True)
    to_bbt: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True, index=True)  # tank thành phẩm đích (BBT)
    product_id: Mapped[Optional[str]] = mapped_column(ForeignKey("product.product_id"), nullable=True, index=True)
    beer_type_id: Mapped[Optional[str]] = mapped_column(ForeignKey("beer_type.beer_type_id"), nullable=True, index=True)
    finished_product_id: Mapped[Optional[str]] = mapped_column(ForeignKey("finished_product.finished_product_id"),
                                                                nullable=True, index=True)
    # volume_hl = v_dich_hl + nuoc_bai_khi_hl (mirror FilterRecord.v_beer_hl), cộng dồn từ MỌI
    # mẻ lọc (BatchFilterLotBatch, mỗi mẻ có thể rút từ NHIỀU nguồn qua BatchFilterLotBatchDraw)
    # — xem services/batch_pipeline.py::_sync_filter_lot_aggregate.
    v_dich_hl: Mapped[float] = mapped_column(Float, default=0.0)         # V dịch nha rút từ tank lên men
    nuoc_bai_khi_hl: Mapped[float] = mapped_column(Float, default=0.0)   # V nước DAW (bài khí) phối vào
    volume_hl: Mapped[float] = mapped_column(Float, default=0.0)    # tổng dự kiến (tổng nguồn)
    on_hand: Mapped[float] = mapped_column(Float, default=0.0)
    # dang_loc (mới tạo) -> cho_chiet ("Hoàn thành lọc", mốc XÁC NHẬN riêng của vận hành) ->
    # chiet_1_phan (đã tách ≥1 lô thành phẩm, còn tồn) -> da_chiet_het (on_hand về 0) — luôn set
    # rõ ràng ở services/batch_pipeline.py (draw_from_filter_order/draw_from_tank_into_filter_lot/
    # finish_filtering/_sync_filter_lot_chiet_status), default ở đây chỉ là an toàn dự phòng,
    # yêu cầu người dùng 2026-09-01.
    status: Mapped[str] = mapped_column(Unicode(255), default="dang_loc")
    note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    # Duyệt KCS — CỜ RIÊNG, khác quality_status (hold/release, mặc định RELEASED ngay từ lúc
    # tạo) — mirror FilterRecord.qc_approved (module cũ). Dùng cờ này (không phải
    # quality_status) để biết lô lọc đã thực sự được KCS ký duyệt hay chưa.
    qc_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    qc_approved_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    qc_approved_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    locked_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    locked_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    quality_status: Mapped[str] = mapped_column(Unicode(255), default=QualityStatus.RELEASED.value)


class BatchFilterLotSource(Base):
    """1 nguồn (tank hoặc lô lọc khác — lọc lại) tham gia 1 BatchFilterLot — mirror
    FilterOrderTank (dòng "template", filter_id NULL trong module cũ): chỉ khai báo NGUỒN nào,
    khối lượng thực tế rút theo TỪNG MẺ LỌC (BatchFilterLotBatch) qua BatchFilterLotBatchDraw —
    1 mẻ lọc có thể rút CÙNG LÚC từ NHIỀU nguồn (VD phối tank 01 + tank 02 trong 1 lần chạy máy)."""
    __tablename__ = "batch_filter_lot_source"

    link_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    filter_lot_id: Mapped[str] = mapped_column(ForeignKey("batch_filter_lot.filter_lot_id"), index=True)
    source_type: Mapped[str] = mapped_column(Unicode(16), default="tank")   # tank | filter_lot (lọc lại)
    source_tank_id: Mapped[Optional[str]] = mapped_column(ForeignKey("batch_tank.tank_id"), nullable=True, index=True)
    source_filter_lot_id: Mapped[Optional[str]] = mapped_column(ForeignKey("batch_filter_lot.filter_lot_id"),
                                                                 nullable=True, index=True)
    reason: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)   # bắt buộc khi lọc lại
    seq: Mapped[int] = mapped_column(Integer, default=1)


class BatchFilterLotBatch(Base):
    """1 mẻ lọc (1 lần chạy máy lọc) của 1 BatchFilterLot — 1 mẻ có thể rút dịch từ NHIỀU nguồn
    CÙNG LÚC (VD 1 lần chạy máy phối tank lên men 01 + tank 02), mỗi khoản rút theo từng nguồn
    xem BatchFilterLotBatchDraw. nuoc_bai_khi_hl (nước DAW) phối thêm CHUNG cho cả mẻ — KHÔNG rút
    từ tank nào. is_final_batch ("Mẻ cuối") đánh dấu mẻ vét cuối cùng — dùng để loại khỏi phân
    loại hiệu suất (mẻ vét thường có sản lượng thấp, không phản ánh hiệu suất thật)."""
    __tablename__ = "batch_filter_lot_batch"

    batch_link_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    filter_lot_id: Mapped[str] = mapped_column(ForeignKey("batch_filter_lot.filter_lot_id"), index=True)
    batch_seq_no: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)   # "Mẻ lọc số" — tự gõ, không auto-tăng
    nuoc_bai_khi_hl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_final_batch: Mapped[bool] = mapped_column(Boolean, default=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class BatchFilterLotBatchDraw(Base):
    """1 khoản rút dịch từ 1 NGUỒN (BatchFilterLotSource) trong 1 mẻ lọc (BatchFilterLotBatch) —
    1 mẻ có N khoản rút (mỗi nguồn 1 khoản, tự động tạo sẵn theo mọi nguồn đã khai báo của lô lọc
    lúc mở mẻ mới) khi phối nhiều tank lên men trong cùng 1 lần chạy máy."""
    __tablename__ = "batch_filter_lot_batch_draw"

    draw_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    batch_link_id: Mapped[str] = mapped_column(ForeignKey("batch_filter_lot_batch.batch_link_id"), index=True)
    source_link_id: Mapped[str] = mapped_column(ForeignKey("batch_filter_lot_source.link_id"), index=True)
    dich_nha_hl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class BatchPackLot(Base):
    """Lô thành phẩm mới — tách từ 1 BatchFilterLot (gọi lặp lại để tách nhiều lô, mirror
    BottleRecord). qty (Số lượng cấp chiết, đơn vị LÍT) trừ vào filter_lot.on_hand (đơn vị hl)
    theo DELTA, quy đổi 1 hl = 100 lít (mirror finish_bottle, xem services/batch_pipeline.py::L_PER_HL)."""
    __tablename__ = "batch_pack_lot"
    # lot_no ("Số lô bia" — số GMP thật in trên bao bì) trước đây chỉ được check-rồi-ghi ở tầng
    # service (split_filter_lot_to_pack_lot), không có backstop DB nào — khác mọi mã anh em khác
    # (pack_lot_code/filter_lot_code/batch_code đều có UniqueConstraint thật) nên 2 request gần
    # như đồng thời có thể lọt trùng lot_no. Thêm ràng buộc DB thật (2026-09-02, audit module
    # "Mẻ sản xuất"): NULL không đụng NULL trong UNIQUE constraint (SQLite/Postgres/SQL Server
    # đều vậy) nên không ảnh hưởng bản ghi cũ (nếu có) chưa có lot_no.
    __table_args__ = (UniqueConstraint("pack_lot_year", "pack_lot_code", name="uq_batch_pack_lot_year_code"),
                      UniqueConstraint("pack_lot_year", "lot_no", name="uq_batch_pack_lot_year_lotno"))

    pack_lot_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    pack_lot_code: Mapped[str] = mapped_column(Unicode(64), index=True)
    pack_lot_year: Mapped[int] = mapped_column(Integer, index=True)
    filter_lot_id: Mapped[str] = mapped_column(ForeignKey("batch_filter_lot.filter_lot_id"), index=True)
    qty: Mapped[float] = mapped_column(Float, default=0.0)   # Số lượng cấp chiết, đơn vị LÍT
    finished_product_id: Mapped[Optional[str]] = mapped_column(ForeignKey("finished_product.finished_product_id"),
                                                                nullable=True, index=True)
    lot_no: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    line: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    # Tank BBT vật lý đã chiết từ đó (mirror BottleRecord.from_bbt) + mốc bắt đầu chiết (mirror
    # BottleRecord.bottle_date) — điền lúc tạo, KHÁC created_at (giờ ghi vào hệ thống).
    from_bbt: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True, index=True)
    pack_date: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    # SL chiết theo ca (mirror BottleRecord.ca1/ca2/ca3), bổ sung giờ bắt đầu/kết thúc từng ca
    # (module cũ không có mốc giờ, chỉ có SL) — điền sau khi tạo, không bắt buộc lúc tạo.
    ca1_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ca1_start_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    ca1_end_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    ca2_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ca2_start_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    ca2_end_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    ca3_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ca3_start_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    ca3_end_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    # Đã nhập kho thành phẩm (mirror BottleRecord.stocked) — xem
    # services/batch_pipeline.py::release_pack_lot_to_wms. Tách khỏi `approved` (Duyệt KCS)
    # đúng sơ đồ tổ chức module cũ: KCS duyệt chỉ tiêu, Giám đốc/Phó GĐ SX duyệt nhập kho.
    stocked: Mapped[bool] = mapped_column(Boolean, default=False)
    stocked_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    stocked_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    locked_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    locked_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    quality_status: Mapped[str] = mapped_column(Unicode(255), default=QualityStatus.RELEASED.value)

    @property
    def ended_at(self) -> Optional[datetime]:
        """Giờ kết thúc chiết — MAX giờ kết thúc trong số các ca ĐÃ khai cả SL và giờ (ca
        thiếu 1 trong 2 không tính, vì chưa xác nhận ca đó thực sự đã chạy xong)."""
        ends = [end for qty, end in (
            (self.ca1_qty, self.ca1_end_at), (self.ca2_qty, self.ca2_end_at), (self.ca3_qty, self.ca3_end_at),
        ) if qty is not None and end is not None]
        return max(ends) if ends else None


class BatchPackLotMaterialUsage(Base):
    """NVL (VD CO2, hóa chất vệ sinh) dùng thật cho 1 lô thành phẩm (chiết) — mirror
    BottleMaterialUsage (module Nấu-Lọc-Chiết cũ)."""
    __tablename__ = "batch_pack_lot_material_usage"

    usage_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    pack_lot_id: Mapped[str] = mapped_column(ForeignKey("batch_pack_lot.pack_lot_id"), index=True)
    lot_id: Mapped[Optional[str]] = mapped_column(ForeignKey("material_lot.lot_id"), nullable=True, index=True)
    movement_id: Mapped[Optional[str]] = mapped_column(ForeignKey("stock_movement.movement_id"), nullable=True)
    material_name: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    lot_pm: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    lot_date: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    fifo_ok: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    # Bắt buộc khi fifo_ok=False (chọn lô KHÁC lô FIFO cũ nhất) — mirror DispenseLine.reason,
    # yêu cầu người dùng 2026-09-01.
    reason: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    uom: Mapped[str] = mapped_column(Unicode(32), default="kg")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class BatchFilterLotMaterialUsage(Base):
    """NVL (VD bột trợ lọc/diatomite) dùng thật cho 1 lô lọc — mirror BatchPackLotMaterialUsage/
    FilterMaterialUsage (module Nấu-Lọc-Chiết cũ), yêu cầu người dùng 2026-09-01."""
    __tablename__ = "batch_filter_lot_material_usage"

    usage_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    filter_lot_id: Mapped[str] = mapped_column(ForeignKey("batch_filter_lot.filter_lot_id"), index=True)
    lot_id: Mapped[Optional[str]] = mapped_column(ForeignKey("material_lot.lot_id"), nullable=True, index=True)
    movement_id: Mapped[Optional[str]] = mapped_column(ForeignKey("stock_movement.movement_id"), nullable=True)
    material_name: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    lot_pm: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    lot_date: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    fifo_ok: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    uom: Mapped[str] = mapped_column(Unicode(32), default="kg")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class BatchTankProcessLog(Base):
    """Ghi chép lên men (bảng thông tin đầu, biểu mẫu giấy BM 1.11 (06)) cho BatchTank — mirror
    FermentProcessLog (module Nấu-Lọc-Chiết cũ, xem services/ferment_log.py), 1 dòng/tank."""
    __tablename__ = "batch_tank_process_log"

    log_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    tank_id: Mapped[str] = mapped_column(ForeignKey("batch_tank.tank_id"), unique=True, index=True)
    manual_json: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)


class BatchTankDailyReading(Base):
    """1 dòng / 1 ngày theo dõi lên men (bảng dưới cùng biểu mẫu giấy BM 1.11 (06)) — mirror
    FermentDailyReading. Mỗi nhóm trường (đo đạc/KCS/trực ca) tự ghi audit trail (by/at) khi có
    giá trị — xem services/batch_tank_log.py::upsert_daily_readings."""
    __tablename__ = "batch_tank_daily_reading"
    __table_args__ = (UniqueConstraint("tank_id", "day_no", name="uq_batch_tank_daily_reading_day"),)

    reading_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    tank_id: Mapped[str] = mapped_column(ForeignKey("batch_tank.tank_id"), index=True)
    day_no: Mapped[int] = mapped_column(Integer)
    reading_date: Mapped[Optional[str]] = mapped_column(Unicode(32), nullable=True)  # ISO "YYYY-MM-DD"
    nhiet_do_c: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    do_s: Mapped[Optional[float]] = mapped_column(Float, nullable=True)          # °S (Plato)
    mat_do_tb: Mapped[Optional[float]] = mapped_column(Float, nullable=True)      # 10^6/ml
    measured_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    measured_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    kcs: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)  # "dat"|"khong_dat"
    kcs_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    kcs_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    truc_ca: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    truc_ca_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    truc_ca_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
