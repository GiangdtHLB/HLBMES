"""QualityResult + Deviation (tài liệu §7.5, §8.2).

Một kết quả chỉ có một SoR; pass/fail tính theo limit số học chứ không
phải text tùy ý. Deviation có workflow và liên kết tới batch/lot."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Date, UnicodeText, Float, Unicode
from sqlalchemy.orm import Mapped, mapped_column

from ..common import DeviationState, ResultStatus, UTCDateTime, new_id, utcnow
from ..database import Base


class QualityResult(Base):
    __tablename__ = "quality_result"

    result_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    sample_id: Mapped[str] = mapped_column(Unicode(64), index=True)
    # phạm vi: scope_type ∈ {batch, lot}, scope_id trỏ tới batch_id/lot_id
    scope_type: Mapped[str] = mapped_column(Unicode(255), default="batch")
    scope_id: Mapped[str] = mapped_column(Unicode(64), index=True)

    parameter: Mapped[str] = mapped_column(Unicode(255))
    method: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    instrument: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Giá trị dạng chữ — chỉ dùng khi QCParameter.value_type == "text" (ghi chú tự do, không so
    # target/USL/LSL, không tính pass/fail). NULL ở mọi chỉ tiêu số/đạt-không đạt.
    value_text: Mapped[Optional[str]] = mapped_column(Unicode(1000), nullable=True)
    # Giá trị in trên bao bì/CA của nhà cung cấp — khác `value` (nhà máy tự đo); chỉ mang tính
    # tham khảo/báo cáo, KHÔNG dùng để tính `status` (pass/fail vẫn chỉ theo `value` vs limit).
    ca_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    lower_limit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    upper_limit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(Unicode(255), default=ResultStatus.PENDING.value)

    recorded_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    # Mốc TẠO lần đầu — KHÔNG đổi sau đó nữa (2026-09-21: trước đây record_stage_result ghi đè
    # cả recorded_by/recorded_at mỗi lần sửa, làm mất luôn "ngày giờ tạo/nhập" gốc). Lần SỬA sau
    # đó ghi vào updated_by/updated_at bên dưới, không đụng 2 cột này.
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    # Mốc SỬA gần nhất (NULL nếu chưa từng sửa sau khi tạo) — xem QualityResultHistory để có
    # toàn bộ lịch sử các lần sửa trước đó, không chỉ lần gần nhất.
    updated_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    # Mốc ngày giờ LẤY MẪU do người dùng khai báo (có thể lùi lại nếu ghi trễ) — khác
    # recorded_at (mốc HỆ THỐNG lưu bản ghi). Trước đây chỉ dùng cho các stage lấy mẫu NHIỀU
    # LẦN (len_men_chinh/len_men_phu, xem qc_catalog.MULTI_SAMPLE_STAGES); từ 2026-09-21 cũng
    # dùng cho record_stage_result (mọi stage 1-dòng/chỉ tiêu, VD "nau") — vẫn NULL nếu người
    # dùng không khai (không bắt buộc).
    sampled_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)


class QualityResultHistory(Base):
    """Snapshot giá trị TRƯỚC MỖI LẦN sửa 1 QualityResult (record_stage_result ghi đè tại chỗ,
    record_qc_sample/update_qc_sample sửa 1 dòng đã lưu) — yêu cầu người dùng 2026-09-21: "ghi
    lại lịch sử" khi sửa chỉ tiêu đã khai. Không snapshot lúc TẠO mới (chưa có gì để mất)."""

    __tablename__ = "quality_result_history"

    history_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    result_id: Mapped[str] = mapped_column(Unicode(64), index=True)
    # Giá trị TRƯỚC lần sửa này (bản chụp, không phải FK sống).
    value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    value_text: Mapped[Optional[str]] = mapped_column(Unicode(1000), nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    lower_limit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    upper_limit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(Unicode(255))
    sampled_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    # Ai/lúc nào đã lưu bản GIÁ TRỊ NÀY (trước khi bị sửa) — khớp recorded_by/at (nếu đây là bản
    # đầu) hoặc updated_by/at (nếu đây đã là 1 lần sửa trước đó).
    saved_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    saved_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    # Ai/lúc nào THỰC HIỆN lần sửa khiến bản ghi này bị thay — luôn có giá trị (khác saved_by/at).
    changed_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Deviation(Base):
    __tablename__ = "deviation"

    deviation_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    deviation_code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    scope_type: Mapped[str] = mapped_column(Unicode(255), default="batch")
    scope_id: Mapped[str] = mapped_column(Unicode(64), index=True)
    severity: Mapped[str] = mapped_column(Unicode(255), default="minor")  # minor/major/critical
    reason: Mapped[str] = mapped_column(UnicodeText)
    state: Mapped[str] = mapped_column(Unicode(255), default=DeviationState.OPEN.value)
    investigation: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    disposition: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    opened_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    closed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    # Mã chỉ tiêu (QualityResult.parameter) liên quan tới deviation này, người mở TỰ CHỌN từ
    # danh sách chỉ tiêu đã khai báo/fail của scope — nhiều mã nối bằng dấu phẩy. Cho phép
    # người xem Deviation biết NGAY vì sao mở mà không phải đoán qua reason tự do (xem
    # frontend/app.js::VIEWS.quality — panel "Chỉ tiêu của phạm vi này").
    parameter: Mapped[Optional[str]] = mapped_column(Unicode(500), nullable=True)
    # Hạn xử lý (nhập tay lúc mở, không tự tính theo severity) + ghi chú đóng bắt buộc khi
    # transition sang closed — xem services/quality.py::transition_deviation nhánh CLOSED.
    due_date: Mapped[Optional[datetime]] = mapped_column(Date, nullable=True)
    close_note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
