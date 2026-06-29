"""Luồng sản xuất bia theo công đoạn (mô phỏng hệ PX Đông Mai).

Nguyên liệu → Nấu → Lên men (tank LM/CCT) → Lọc (vào tank BBT) → Chiết.
Mỗi công đoạn có bản ghi riêng, liên kết với công đoạn trước qua mã, và có
chỉ tiêu phân tích (StageIndicator). Đây là biểu diễn chi tiết, song song với
mô hình BatchExecution trừu tượng của lõi MES.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Text, Boolean, DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from ..common import new_id, utcnow
from ..database import Base


class MaterialReceipt(Base):
    """Thông tin nguyên liệu nhập (kèm số lô PM/KCS, nhà cung cấp)."""
    __tablename__ = "material_receipt"

    receipt_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    mskt: Mapped[str] = mapped_column(String(255), index=True)          # mã số kiểm tra
    receipt_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    material_name: Mapped[str] = mapped_column(String(255))
    lot_pm: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)   # số lô PM
    lot_kcs: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # số lô KCS
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    uom: Mapped[str] = mapped_column(String(255), default="kg")
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # nơi nhập
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    supplier: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    has_indicators: Mapped[bool] = mapped_column(Boolean, default=False)


class BrewRecord(Base):
    """Thông tin nấu (mẻ dịch nha)."""
    __tablename__ = "brew_record"

    brew_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    brew_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)   # mã nấu
    brew_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    wort_type: Mapped[str] = mapped_column(String(255))                            # dịch nha
    volume_hl: Mapped[float] = mapped_column(Float, default=0.0)              # SL nấu/hl
    original_extract: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # độ hòa tan nguyên thủy
    plato: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class FermentRecord(Base):
    """Thông tin quá trình lên men (lô LM trong tank)."""
    __tablename__ = "ferment_record"

    ferment_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    lm_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)     # Lô LM
    brew_code: Mapped[Optional[str]] = mapped_column(String(64), index=True)      # mã nấu
    brew_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    kt_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)  # ngày KT
    batch_numbers: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # số mẻ
    wort_type: Mapped[str] = mapped_column(String(255))                           # dịch nha
    yeast_gen: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # đời men
    tank_lm: Mapped[str] = mapped_column(String(255), index=True)                 # Tank LM
    volume_hl: Mapped[float] = mapped_column(Float, default=0.0)             # SL nấu/hl
    on_hand_cct: Mapped[float] = mapped_column(Float, default=0.0)           # đang tồn CCT/hl
    status: Mapped[str] = mapped_column(String(255), default="len_men")          # len_men/cho_loc/da_loc
    ferment_days: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # số ngày LM (text)


class FilterRecord(Base):
    """Thông tin lọc (từ tank LM vào tank BBT)."""
    __tablename__ = "filter_record"

    filter_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    filter_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # mã lọc
    brew_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)    # mã nấu
    lot_loc: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)      # mã lô lọc
    filter_phoi_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    filter_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    filter_type: Mapped[str] = mapped_column(String(255), default="thuong")        # thuong/phoi/ve_bbt_phoi
    wort_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)    # loại dịch nha lọc
    from_cct: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)     # lọc từ CCT
    v_dich_hl: Mapped[float] = mapped_column(Float, default=0.0)              # V dịch/hl
    beer_type: Mapped[str] = mapped_column(String(255))                           # loại bia lọc
    v_beer_hl: Mapped[float] = mapped_column(Float, default=0.0)             # V bia/hl
    to_bbt: Mapped[Optional[str]] = mapped_column(String(255), index=True)        # lọc cho vào (tank BBT)
    status: Mapped[str] = mapped_column(String(255), default="cho_chiet")         # cho_chiet/chiet_1_phan/da_chiet_het
    on_hand_bbt: Mapped[float] = mapped_column(Float, default=0.0)           # đang tồn BBT/hl
    has_indicators: Mapped[bool] = mapped_column(Boolean, default=False)
    has_nvl: Mapped[bool] = mapped_column(Boolean, default=False)


class BottleRecord(Base):
    """Thông tin chiết (từ tank BBT ra dây chuyền theo ca)."""
    __tablename__ = "bottle_record"

    bottle_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    bottle_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # mã chiết
    filter_code: Mapped[Optional[str]] = mapped_column(String(64), index=True)     # mã lọc
    bottle_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    beer_type: Mapped[str] = mapped_column(String(255))                            # loại bia
    lot_no: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)       # số lô bia
    v_cap_chiet_hl: Mapped[float] = mapped_column(Float, default=0.0)         # V cấp chiết/hl
    from_bbt: Mapped[Optional[str]] = mapped_column(String(255), index=True)       # chiết từ tank BBT
    line: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)        # dây chuyền
    ca1: Mapped[float] = mapped_column(Float, default=0.0)
    ca2: Mapped[float] = mapped_column(Float, default=0.0)
    ca3: Mapped[float] = mapped_column(Float, default=0.0)
    stocked: Mapped[bool] = mapped_column(Boolean, default=False)             # đã nhập kho
    approved: Mapped[bool] = mapped_column(Boolean, default=False)            # chiết duyệt
    has_indicators: Mapped[bool] = mapped_column(Boolean, default=False)
    has_nvl: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class StageIndicator(Base):
    """Chỉ tiêu phân tích gắn với một bản ghi công đoạn."""
    __tablename__ = "stage_indicator"

    indicator_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    stage: Mapped[str] = mapped_column(String(255), index=True)        # nau/len_men/loc/chiet
    scope_code: Mapped[str] = mapped_column(String(64), index=True)   # mã nấu/lô LM/mã lọc/mã chiết
    name: Mapped[str] = mapped_column(String(255))                     # tên chỉ tiêu
    unit: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    value_text: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    warning: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    analyst: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # NV PT
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
