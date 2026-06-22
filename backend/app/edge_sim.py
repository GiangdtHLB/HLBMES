"""Edge connector simulator — mô phỏng gateway OPC UA/MQTT đẩy telemetry vào MES.

Đây là tiến trình ĐỘC LẬP (giống edge gateway thật): đọc tag từ "thiết bị" mô phỏng
và POST theo lô vào /api/historian/ingest bằng X-API-Key (store-and-forward đơn giản).
Trong production, thay phần sinh giá trị bằng client OPC UA (vd asyncua) hoặc subscribe
MQTT/Sparkplug — phần đẩy lên MES giữ nguyên.

Chạy:  python -m app.edge_sim            (cần MES đang chạy ở :8077)
Biến môi trường: MES_BASE_URL, MES_EDGE_KEY, EDGE_INTERVAL (giây).
"""

import json
import os
import time
import urllib.request

from .services.historian import TAGS  # tái dùng định nghĩa tag/setpoint

BASE = os.environ.get("MES_BASE_URL", "http://localhost:8077")
KEY = os.environ.get("MES_EDGE_KEY", "mes_edge_writer_key_0001")
INTERVAL = float(os.environ.get("EDGE_INTERVAL", "3"))

import random

_state = {t: s["sp"] for t, s in TAGS.items()}


def _next(t, s):
    drift = s.get("drift", 0.0)
    nv = _state[t] + drift + random.uniform(-s["amp"], s["amp"])
    if not drift:
        nv += (s["sp"] - _state[t]) * 0.1
    nv = max(s["lo"], min(s["hi"], nv))
    _state[t] = nv
    return round(nv, 3)


def push(points):
    body = json.dumps({"points": points}).encode()
    req = urllib.request.Request(BASE + "/api/historian/ingest", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "X-API-Key": KEY})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def main():
    print(f"[edge-sim] → {BASE}  mỗi {INTERVAL}s  | {len(TAGS)} tag (OPC UA/MQTT giả lập)")
    while True:
        pts = [{"tag": t, "value": _next(t, s), "unit": s["unit"], "source": "edge-sim"}
               for t, s in TAGS.items()]
        try:
            res = push(pts)
            print(f"[edge-sim] đẩy {res.get('ingested')} điểm")
        except Exception as e:  # noqa: BLE001
            print(f"[edge-sim] lỗi: {e} (thử lại sau)")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
