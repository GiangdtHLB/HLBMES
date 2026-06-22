"""Tính OEE theo định nghĩa chuẩn (tài liệu §7.7).

Availability = Run Time / Planned Production Time, Run Time = Planned − Downtime
Performance  = Total Count / (Run Time × Ideal Rate)
Quality      = Good Count / Total Count
OEE          = Availability × Performance × Quality
"""

from ..models.metrics import OEERecord


def compute_oee(rec: OEERecord) -> dict:
    planned = rec.planned_time_min or 0.0
    run_time = max(planned - (rec.downtime_min or 0.0), 0.0)

    availability = (run_time / planned) if planned > 0 else 0.0

    ideal_capacity = run_time * (rec.ideal_rate_per_min or 0.0)
    performance = (rec.total_count / ideal_capacity) if ideal_capacity > 0 else 0.0
    performance = min(performance, 1.0)  # kẹp ≤ 100% (tránh dữ liệu nhập sai vượt ngưỡng)

    quality = (rec.good_count / rec.total_count) if rec.total_count > 0 else 0.0
    oee = availability * performance * quality

    return {
        "oee_id": rec.oee_id,
        "line": rec.line,
        "shift": rec.shift,
        "shift_date": rec.shift_date,
        "planned_time_min": planned,
        "downtime_min": rec.downtime_min,
        "run_time_min": run_time,
        "ideal_rate_per_min": rec.ideal_rate_per_min,
        "total_count": rec.total_count,
        "good_count": rec.good_count,
        "reject_count": rec.total_count - rec.good_count,
        "downtime_reasons": rec.downtime_reasons or [],
        "availability": round(availability, 4),
        "performance": round(performance, 4),
        "quality": round(quality, 4),
        "oee": round(oee, 4),
    }
