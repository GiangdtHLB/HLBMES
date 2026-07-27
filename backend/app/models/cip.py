"""CIP (Cleaning-In-Place) — theo dõi vệ sinh thiết bị theo 21 biểu mẫu giấy hiện có
(QT-KCS-QT-BM). Thiết kế linh hoạt:

- `CipFormType`: danh mục LOẠI biểu mẫu (mã BM, khu vực, "full" CIP đầy đủ hay "light" vệ
  sinh nhẹ/tráng nước — vd tank thành phẩm xen kẽ 2 loại khác chu kỳ).
- `CipEquipment`: danh mục THIẾT BỊ được vệ sinh — có thể gắn (không bắt buộc) tới đúng 1
  `ProductionLine` (tank/dây chuyền) đã có trong Danh mục sản xuất, để tự lọc gợi ý theo mã
  thiết bị khi "Gắn CIP liên quan" (equipment không phải tank/dây chuyền dùng chung — đường
  ống, máy nghiền... — để trống `production_line_id`, luôn hiện trong gợi ý vì bản thân nó
  chỉ có 1 cái duy nhất trong nhà máy).
- `CipRecord`: 1 lần thực hiện vệ sinh — bảng bước lưu dạng JSON linh hoạt (thêm/bớt dòng tự
  do), KHÔNG hard-code cứng theo từng loại biểu mẫu.
- `CipLink`: gắn TAY 1 CipRecord với 1 hoặc nhiều mẻ/lô sản xuất (không tự động suy đoán) —
  cùng vocabulary scope_type/scope_id đã dùng cho Hold/Deviation (xem services/quality.py).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, Unicode, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..common import UTCDateTime, new_id, utcnow
from ..database import Base


class CipFormType(Base):
    __tablename__ = "cip_form_type"

    form_type_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)  # "2.1.2/2025/QT-KCS-QT-BM-01"
    name: Mapped[str] = mapped_column(Unicode(255))  # "Tank lên men (CIP full)"
    area: Mapped[str] = mapped_column(Unicode(32), index=True)  # nau | len_men | loc | chiet | kho_tp
    kind: Mapped[str] = mapped_column(Unicode(16), default="full")  # full | light (vd tráng nước DAW)
    # Đơn vị của từng cột thông số — khai báo 1 lần cho cả biểu mẫu (khớp đúng cột trên giấy
    # gốc, VD "Thời gian (giây)" ở tank lên men nhưng "Thời gian (phút)" ở hầu hết mẫu khác).
    time_unit: Mapped[str] = mapped_column(Unicode(16), default="phút")
    temp_unit: Mapped[str] = mapped_column(Unicode(16), default="°C")
    conc_unit: Mapped[str] = mapped_column(Unicode(16), default="%")
    # Bảng bước MẪU (khai báo trước theo đúng biểu mẫu giấy gốc — các cột "Tiêu chuẩn/Quy
    # định") — cùng shape với CipRecord.steps; khi khai báo 1 lần CIP mới, chọn form_type sẽ
    # tự điền bảng bước từ đây (tiêu chuẩn khoá — chỉ sửa/thêm/bớt được ở khu vực Khai báo
    # biểu mẫu; phần Khai báo CIP chỉ nhập THỰC TẾ bên cạnh, xem CipRecord.steps).
    default_steps: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class CipEquipment(Base):
    __tablename__ = "cip_equipment"

    equipment_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(Unicode(255))
    area: Mapped[str] = mapped_column(Unicode(32), index=True)
    # Gắn đúng 1 tank/dây chuyền đã có trong Danh mục sản xuất nếu có — để tự lọc gợi ý theo
    # mã thiết bị thực tế mẻ/lô đó dùng. Để trống với thiết bị dùng chung (đường ống, máy nghiền...).
    production_line_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("production_line.line_id"), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class CipRecord(Base):
    __tablename__ = "cip_record"

    cip_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    cip_code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)  # CIP-2026-00001
    cip_year: Mapped[int] = mapped_column(Integer, index=True)
    form_type_id: Mapped[str] = mapped_column(ForeignKey("cip_form_type.form_type_id"), index=True)
    equipment_id: Mapped[str] = mapped_column(ForeignKey("cip_equipment.equipment_id"), index=True)

    # Bắt buộc — đối chiếu ngược với Batch/Order Number bên Braumat (cùng khái niệm đã dùng ở
    # Ghi chép nấu/Lên men, xem services/braumat_import.py, services/ferment_log.py) để truy
    # vết 1 lần CIP về đúng lệnh/mẻ nấu Braumat đang chạy.
    batch_number: Mapped[str] = mapped_column(Unicode(64), index=True)
    order_number: Mapped[str] = mapped_column(Unicode(64), index=True)

    shift: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)  # ca
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    performed_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    duty_officer: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)  # trực ca

    # Bảng bước linh hoạt — list[{step_no, content, time_spec, temp, concentration,
    # check_result, time_actual, temp_actual, conc_actual, check_actual, performed_by, note}].
    # 4 trường đầu (time_spec/temp/concentration/check_result) là TIÊU CHUẨN, sao chép nguyên
    # từ CipFormType.default_steps lúc tạo — hiển thị khoá (chỉ sửa được ở Khai báo biểu mẫu).
    # 4 trường *_actual là THỰC TẾ, người vận hành tự nhập khi thực hiện — thêm/bớt dòng tự do,
    # không hard-code theo từng loại biểu mẫu (21 mẫu giấy có số cột/loại thông số khác nhau).
    steps: Mapped[list] = mapped_column(JSON, default=list)

    result: Mapped[Optional[str]] = mapped_column(Unicode(16), nullable=True)  # dat | khong_dat
    note: Mapped[Optional[str]] = mapped_column(Unicode(1000), nullable=True)
    checked_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)  # KCS nghiệm thu
    approved_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)

    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class CipLink(Base):
    """Gắn tay 1 CipRecord với 1 mẻ/lô sản xuất cụ thể — scope_type dùng đúng vocabulary đã có
    ở Hold/Deviation (services/quality.py): brew_batch | ferment | filter | bottle."""
    __tablename__ = "cip_link"
    __table_args__ = (UniqueConstraint("cip_id", "scope_type", "scope_id", name="uq_cip_link"),)

    link_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    cip_id: Mapped[str] = mapped_column(ForeignKey("cip_record.cip_id"), index=True)
    scope_type: Mapped[str] = mapped_column(Unicode(32))
    scope_id: Mapped[str] = mapped_column(Unicode(64), index=True)
    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
