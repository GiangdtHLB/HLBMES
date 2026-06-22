"""Lớp Historian: ingest, query, latest, downsample + bộ sinh telemetry mô phỏng.

Tag theo UNS (§9.4): brewery/site01/<area>/<device>/<metric>. Bộ sinh mô phỏng
random-walk quanh setpoint cho nhiệt độ/áp suất/°P/DO/flow/năng lượng — đại diện
dữ liệu từ PLC/SCADA/cân/lưu lượng kế qua edge gateway.
"""

import random
from datetime import timedelta

from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from ..common import new_id, utcnow
from ..models.historian import HistorianPoint

# Định nghĩa tag mô phỏng: setpoint, biên dao động, min/max.
TAGS = {
    "brewery/site01/fermentation/FV07/temperature": {"unit": "°C", "sp": 12.0, "amp": 0.4, "lo": 1.0, "hi": 16.0},
    "brewery/site01/fermentation/FV07/gravity":     {"unit": "°P", "sp": 6.0, "amp": 0.15, "lo": 2.4, "hi": 12.5, "drift": -0.05},
    "brewery/site01/fermentation/FV07/pressure":    {"unit": "bar", "sp": 0.8, "amp": 0.05, "lo": 0.0, "hi": 1.5},
    "brewery/site01/fermentation/FV07/DO":          {"unit": "ppb", "sp": 25.0, "amp": 5.0, "lo": 0.0, "hi": 400.0},
    "brewery/site01/brewhouse/MashTun/temperature": {"unit": "°C", "sp": 65.0, "amp": 0.8, "lo": 20.0, "hi": 100.0},
    "brewery/site01/utility/Boiler/steam_flow":     {"unit": "t/h", "sp": 4.5, "amp": 0.6, "lo": 0.0, "hi": 10.0},
    "brewery/site01/utility/Main/power":            {"unit": "kW", "sp": 850.0, "amp": 120.0, "lo": 0.0, "hi": 2000.0},
    "brewery/site01/packaging/Line1/flow":          {"unit": "cans/min", "sp": 480.0, "amp": 60.0, "lo": 0.0, "hi": 600.0},
}


def ingest(db: Session, points: list, source: str = "api") -> int:
    n = 0
    for p in points:
        db.add(HistorianPoint(point_id=new_id(), tag=p["tag"], value=float(p["value"]),
                              unit=p.get("unit"), quality=p.get("quality", "good"),
                              source=p.get("source", source),
                              ts=p["ts"] if p.get("ts") else utcnow()))
        n += 1
    db.commit()
    return n


def tags(db: Session) -> list:
    rows = db.execute(select(distinct(HistorianPoint.tag))).scalars().all()
    return sorted(rows)


def latest(db: Session, tag: str):
    p = db.execute(select(HistorianPoint).where(HistorianPoint.tag == tag)
                   .order_by(HistorianPoint.ts.desc()).limit(1)).scalar_one_or_none()
    if not p:
        return None
    return {"tag": p.tag, "value": p.value, "unit": p.unit, "quality": p.quality, "ts": p.ts}


def query(db: Session, tag: str, hours: float = 6, limit: int = 5000) -> list:
    since = utcnow() - timedelta(hours=hours)
    rows = db.execute(select(HistorianPoint).where(
        HistorianPoint.tag == tag, HistorianPoint.ts >= since)
        .order_by(HistorianPoint.ts).limit(limit)).scalars().all()
    return [{"ts": r.ts, "value": r.value} for r in rows]


def series(db: Session, tag: str, hours: float = 6, buckets: int = 60) -> dict:
    """Downsample về `buckets` bin: avg/min/max mỗi bin (cho biểu đồ)."""
    pts = query(db, tag, hours)
    spec = TAGS.get(tag, {})
    if not pts:
        return {"tag": tag, "unit": spec.get("unit"), "points": [], "last": None}
    t0 = pts[0]["ts"]
    t1 = pts[-1]["ts"]
    span = (t1 - t0).total_seconds() or 1
    width = span / buckets
    bins = {}
    for p in pts:
        idx = min(int((p["ts"] - t0).total_seconds() / width), buckets - 1)
        b = bins.setdefault(idx, {"vals": [], "ts": p["ts"]})
        b["vals"].append(p["value"])
    out = []
    for idx in sorted(bins):
        v = bins[idx]["vals"]
        out.append({"ts": bins[idx]["ts"].isoformat(), "value": round(sum(v) / len(v), 3),
                    "min": round(min(v), 3), "max": round(max(v), 3), "n": len(v)})
    return {"tag": tag, "unit": spec.get("unit"), "points": out, "last": pts[-1]["value"]}


# ---- Bộ sinh telemetry mô phỏng (edge) ----
def _next_value(db: Session, tag: str, spec: dict) -> float:
    last = latest(db, tag)
    base = last["value"] if last else spec["sp"]
    drift = spec.get("drift", 0.0)
    nv = base + drift + random.uniform(-spec["amp"], spec["amp"])
    # kéo nhẹ về setpoint (mean-reversion), trừ tag có drift (gravity giảm dần)
    if not drift:
        nv += (spec["sp"] - base) * 0.1
    return round(max(spec["lo"], min(spec["hi"], nv)), 3)


def tick(db: Session, source: str = "edge-sim") -> int:
    """Sinh 1 điểm hiện tại cho mỗi tag (random-walk có liên tục từ giá trị cuối)."""
    now = utcnow()
    pts = [{"tag": t, "value": _next_value(db, t, s), "unit": s["unit"], "ts": now, "source": source}
           for t, s in TAGS.items()]
    return ingest(db, pts, source)


def backfill(db: Session, hours: float = 6, step_min: float = 5, source: str = "seed") -> int:
    """Tạo dữ liệu lịch sử cho mọi tag từ now-hours đến now."""
    now = utcnow()
    steps = int(hours * 60 / step_min)
    state = {t: s["sp"] for t, s in TAGS.items()}
    rows = []
    for i in range(steps + 1):
        ts = now - timedelta(minutes=step_min * (steps - i))
        for t, s in TAGS.items():
            drift = s.get("drift", 0.0)
            nv = state[t] + drift + random.uniform(-s["amp"], s["amp"])
            if not drift:
                nv += (s["sp"] - state[t]) * 0.1
            nv = max(s["lo"], min(s["hi"], nv))
            state[t] = nv
            rows.append({"tag": t, "value": round(nv, 3), "unit": s["unit"], "ts": ts, "source": source})
    return ingest(db, rows, source)
