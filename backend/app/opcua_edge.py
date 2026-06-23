"""Edge connector OPC UA THẬT (asyncua) + ánh xạ chuẩn Weihenstephan → MES historian.

Đọc các điểm dữ liệu theo chuẩn Weihenstephan (WS Pack — bộ tag chuẩn cho máy
đóng gói/chiết) từ một OPC UA server (PLC/SCADA của line chiết), ánh xạ sang tag
UNS rồi POST vào /api/historian/ingest (X-API-Key) — store-and-forward.

Chạy với PLC thật:
    MES_OPCUA_URL=opc.tcp://192.168.0.10:4840  python -m app.opcua_edge
Chạy DEMO (tự dựng OPC UA server cục bộ có node WS để kiểm chứng, không cần PLC):
    python -m app.opcua_edge --demo
Cần MES đang chạy ở MES_BASE_URL để nhận ingest. Cài: pip install asyncua.
"""

import asyncio
import json
import math
import os
import urllib.request

WS_NS_URI = "http://weihenstephan.org/ws"          # namespace chuẩn Weihenstephan
DEMO_ENDPOINT = "opc.tcp://127.0.0.1:4842/mes/ws/"

# Ánh xạ điểm dữ liệu Weihenstephan (object/variable) → tag UNS + đơn vị + loss/ý nghĩa.
WS_MAP = [
    {"obj": "WS_Filler01", "var": "WS_Cur_State", "tag": "brewery/site01/chiet/filler01/state", "unit": ""},
    {"obj": "WS_Filler01", "var": "WS_Cur_Speed", "tag": "brewery/site01/chiet/filler01/speed", "unit": "lon/phút"},
    {"obj": "WS_Filler01", "var": "WS_Cur_OutPut", "tag": "brewery/site01/chiet/filler01/output_good", "unit": "lon"},
    {"obj": "WS_Filler01", "var": "WS_Cur_Reject", "tag": "brewery/site01/chiet/filler01/reject", "unit": "lon"},
    {"obj": "WS_Filler01", "var": "WS_Cur_FillLevel", "tag": "brewery/site01/chiet/filler01/fill_level", "unit": "mL"},
    {"obj": "WS_Filler01", "var": "WS_Cur_Temperature", "tag": "brewery/site01/chiet/filler01/temp", "unit": "°C"},
]

BASE = os.environ.get("MES_BASE_URL", "http://localhost:8077")
KEY = os.environ.get("MES_EDGE_KEY", "mes_edge_writer_key_0001")
INTERVAL = float(os.environ.get("EDGE_INTERVAL", "3"))


# ----------------------- OPC UA client (đọc WS → UNS) -----------------------
async def read_once(endpoint: str) -> list:
    """Kết nối OPC UA, đọc toàn bộ điểm WS_MAP, trả list point {tag,value,unit,source}."""
    from asyncua import Client
    points = []
    async with Client(url=endpoint) as client:
        ns = await client.get_namespace_index(WS_NS_URI)
        for m in WS_MAP:
            node = await client.nodes.objects.get_child([f"{ns}:{m['obj']}", f"{ns}:{m['var']}"])
            val = await node.read_value()
            points.append({"tag": m["tag"], "value": float(val), "unit": m["unit"], "source": "opcua-ws"})
    return points


def _push(points: list) -> dict:
    body = json.dumps({"points": points}).encode()
    req = urllib.request.Request(BASE + "/api/historian/ingest", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "X-API-Key": KEY})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


async def run(endpoint: str) -> None:
    print(f"[opcua-edge] OPC UA {endpoint} → MES {BASE} mỗi {INTERVAL}s | {len(WS_MAP)} điểm WS")
    while True:
        try:
            pts = await read_once(endpoint)
            res = await asyncio.to_thread(_push, pts)
            print(f"[opcua-edge] đọc {len(pts)} điểm WS, ingest {res.get('ingested')}")
        except Exception as e:  # noqa: BLE001
            print(f"[opcua-edge] lỗi: {e} (thử lại sau)")
        await asyncio.sleep(INTERVAL)


# ----------------------- OPC UA server DEMO (thay PLC) -----------------------
async def demo_server(endpoint: str = DEMO_ENDPOINT):
    """Dựng OPC UA server cục bộ phơi node WS thay đổi theo thời gian (để kiểm chứng)."""
    from asyncua import Server
    server = Server()
    await server.init()
    server.set_endpoint(endpoint)
    server.set_server_name("MES Weihenstephan Demo PLC")
    ns = await server.register_namespace(WS_NS_URI)
    obj = await server.nodes.objects.add_object(ns, "WS_Filler01")
    vars_ = {}
    init = {"WS_Cur_State": 4.0, "WS_Cur_Speed": 1800.0, "WS_Cur_OutPut": 0.0,
            "WS_Cur_Reject": 0.0, "WS_Cur_FillLevel": 330.0, "WS_Cur_Temperature": 3.5}
    for name, v in init.items():
        node = await obj.add_variable(ns, name, v)
        await node.set_writable()
        vars_[name] = node
    return server, vars_


async def _demo_updater(vars_: dict):
    t = 0
    out = 0.0
    while True:
        t += 1
        out += 28 + (t % 5)
        await vars_["WS_Cur_OutPut"].write_value(out)
        await vars_["WS_Cur_Reject"].write_value(round(out * 0.012, 0))
        await vars_["WS_Cur_Speed"].write_value(round(1800 + 120 * math.sin(t / 6), 1))
        await vars_["WS_Cur_FillLevel"].write_value(round(330 + 1.5 * math.sin(t / 4), 2))
        await vars_["WS_Cur_Temperature"].write_value(round(3.5 + 0.4 * math.sin(t / 8), 2))
        await vars_["WS_Cur_State"].write_value(4.0)   # 4 = đang chạy (WS state)
        await asyncio.sleep(1)


async def _main_demo():
    server, vars_ = await demo_server()
    async with server:
        upd = asyncio.create_task(_demo_updater(vars_))
        await asyncio.sleep(1.5)   # chờ server sẵn sàng
        try:
            await run(DEMO_ENDPOINT)
        finally:
            upd.cancel()


def main():
    import sys
    if "--demo" in sys.argv:
        print("[opcua-edge] DEMO: dựng OPC UA server WS cục bộ + edge client đọc/ingest")
        asyncio.run(_main_demo())
    else:
        endpoint = os.environ.get("MES_OPCUA_URL")
        if not endpoint:
            print("Đặt MES_OPCUA_URL=opc.tcp://host:4840 (hoặc chạy --demo).")
            return
        asyncio.run(run(endpoint))


if __name__ == "__main__":
    main()
