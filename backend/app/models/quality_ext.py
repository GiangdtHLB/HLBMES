"""Quality hardcore (tài liệu §7.5):

- QCParameter: định nghĩa chỉ tiêu SPC (target + spec limit USL/LSL) để vẽ control
  chart, tính Cp/Cpk, áp luật Western Electric. Cũng là danh mục "chỉ tiêu chất lượng"
  gốc dùng chung cho khai báo chỉ tiêu NVL khi nhập kho.
- QCParameterGroup / QCParameterGroupItem: nhóm chỉ tiêu (vd "Chỉ tiêu Malt Anh (bao)")
  gồm nhiều QCParameter, gán được cho nguyên liệu qua MaterialQcGroup (materials_ext.py)
  để cổng nhập kho biết nguyên liệu nào cần khai báo chỉ tiêu nào.
- CAPA: hành động khắc phục/phòng ngừa gắn với deviation (workflow open→...→closed).
- Sample: phiếu mẫu LIMS-lite (đăng ký mẫu → chờ test → hoàn thành), gom QualityResult.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import UnicodeText, Date, Float, ForeignKey, Integer, Unicode
from sqlalchemy.orm import Mapped, mapped_column

from ..common import UTCDateTime, new_id, utcnow
from ..database import Base


class QCParameter(Base):
    __tablename__ = "qc_parameter"

    param_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(Unicode(255))
    unit: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    target: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    usl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # upper spec limit
    lsl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # lower spec limit
    stage: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)  # nau|len_men|loc|chiet
    method: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)  # phương pháp thử mặc định
    note: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    active: Mapped[bool] = mapped_column(default=True)
    # "numeric" (mặc định, nhập số so target/usl/lsl) hoặc "pass_fail" (chỉ ghi Đạt/Không đạt
    # — quy ước value=1/lower=1/upper=1 là Đạt, value=0/lower=1/upper=1 là Không đạt, để tái
    # dùng nguyên vẹn hàm đánh giá numeric hiện có ở qc_catalog.py/quality.py, không phải sửa
    # logic đánh giá).
    value_type: Mapped[str] = mapped_column(Unicode(16), default="numeric")


class QCParameterGroup(Base):
    """Nhóm chỉ tiêu chất lượng — thường đặt tên theo nguyên liệu/biến thể cụ thể
    (vd "Chỉ tiêu Malt Anh (bao)"), gồm nhiều QCParameter qua QCParameterGroupItem."""

    __tablename__ = "qc_parameter_group"

    group_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(Unicode(255))
    note: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    active: Mapped[bool] = mapped_column(default=True)


class QCParameterGroupItem(Base):
    """Một chỉ tiêu trong một nhóm — có thể ghi đè target/usl/lsl riêng cho nhóm đó."""

    __tablename__ = "qc_parameter_group_item"

    item_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    group_id: Mapped[str] = mapped_column(ForeignKey("qc_parameter_group.group_id"), index=True)
    param_id: Mapped[str] = mapped_column(ForeignKey("qc_parameter.param_id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    mandatory: Mapped[bool] = mapped_column(default=True)
    target_override: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    usl_override: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lsl_override: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class StageQcGroup(Base):
    """Gán nhóm chỉ tiêu chất lượng (QCParameterGroup) cho một công đoạn sản xuất
    (nau|len_men_chinh|len_men_phu|loc|thanh_pham) — cùng cơ chế với MaterialQcGroup
    nhưng khoá theo (stage, product_id|beer_type_id, finished_product_id) thay vì
    material_id. 2 cột `product_id`/`beer_type_id` LOẠI TRỪ LẪN NHAU theo stage (không
    dùng đồng thời trên 1 bản ghi):
    - stage nau|len_men_chinh|len_men_phu: dùng `product_id` (Dịch bia, phân biệt cả độ
      oP) — hành vi y hệt trước khi có beer_type_id.
    - stage loc|thanh_pham: dùng `beer_type_id` (Loại bia — thương hiệu, KHÔNG phân biệt
      oP) — vì lọc phối có thể gộp nhiều Dịch bia cùng 1 Loại bia (xem
      services/filter_order.py::_validate_tanks), nên chỉ tiêu phải tra theo Loại bia
      chứ không theo 1 Dịch bia cụ thể.
    Cột tương ứng để trống = áp dụng cho mọi dịch bia/loại bia; finished_product_id (SKU
    đóng gói, chỉ có ý nghĩa với stage=thanh_pham) để trống = áp dụng cho mọi sản phẩm."""

    __tablename__ = "stage_qc_group"

    link_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    stage: Mapped[str] = mapped_column(Unicode(64), index=True)
    product_id: Mapped[Optional[str]] = mapped_column(ForeignKey("product.product_id"), nullable=True, index=True)
    beer_type_id: Mapped[Optional[str]] = mapped_column(ForeignKey("beer_type.beer_type_id"), nullable=True, index=True)
    finished_product_id: Mapped[Optional[str]] = mapped_column(ForeignKey("finished_product.finished_product_id"), nullable=True, index=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("qc_parameter_group.group_id"), index=True)
    mandatory: Mapped[bool] = mapped_column(default=True)
    active: Mapped[bool] = mapped_column(default=True)


class CAPA(Base):
    __tablename__ = "capa"

    capa_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    capa_code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    deviation_id: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True, index=True)
    title: Mapped[str] = mapped_column(Unicode(255))
    capa_type: Mapped[str] = mapped_column(Unicode(255), default="corrective")  # corrective | preventive
    severity: Mapped[str] = mapped_column(Unicode(255), default="minor")
    # open → investigation → action → verification → closed
    state: Mapped[str] = mapped_column(Unicode(255), default="open")
    root_cause: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    action_plan: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    effectiveness: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    owner: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    due_date: Mapped[Optional[datetime]] = mapped_column(Date, nullable=True)
    opened_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    closed_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    closed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)


class Sample(Base):
    """Phiếu mẫu LIMS-lite — gom các QualityResult cùng sample_id."""

    __tablename__ = "lims_sample"

    sample_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    sample_code: Mapped[str] = mapped_column(Unicode(64), unique=True, index=True)
    scope_type: Mapped[str] = mapped_column(Unicode(255), default="batch")
    scope_id: Mapped[str] = mapped_column(Unicode(64), index=True)
    stage: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    # registered → in_test → completed
    status: Mapped[str] = mapped_column(Unicode(255), default="registered")
    test_set: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)  # csv tên parameter cần test
    registered_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    registered_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
