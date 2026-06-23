"""ISA-88 procedural execution — log chạy phase của mẻ.

Định nghĩa thủ tục (procedure → unit procedure → operation → phase) lưu dạng JSON
trong RecipeVersion.procedure (snapshot vào batch). Mỗi lần chạy một phase tạo một
BatchPhaseRun với trạng thái theo ISA-88 (idle→running→held→complete/aborted).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..common import PhaseState, new_id, utcnow
from ..database import Base


class BatchPhaseRun(Base):
    __tablename__ = "batch_phase_run"

    run_id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batch_execution.batch_id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    unit_class: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # brewhouse|fv|filter|filler|cip|sip
    up_name: Mapped[str] = mapped_column(String)        # unit procedure
    op_name: Mapped[str] = mapped_column(String)        # operation
    phase_name: Mapped[str] = mapped_column(String)     # phase
    state: Mapped[str] = mapped_column(String, default=PhaseState.RUNNING.value, index=True)
    params: Mapped[dict] = mapped_column(JSON, default=dict)   # setpoint snapshot từ procedure
    values: Mapped[dict] = mapped_column(JSON, default=dict)   # actual ghi nhận
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    operator: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(String, nullable=True)
