"""Test edge OPC UA + ánh xạ Weihenstephan: dựng OPC UA server cục bộ rồi
đọc qua client THẬT, kiểm tra map WS → tag UNS. Skip nếu chưa cài asyncua."""

import asyncio

import pytest


def test_opcua_ws_read_and_map():
    pytest.importorskip("asyncua")
    from app import opcua_edge as oe

    ep = "opc.tcp://127.0.0.1:4843/test/ws/"

    async def run():
        server, vars_ = await oe.demo_server(ep)
        async with server:
            await asyncio.sleep(0.6)              # chờ server sẵn sàng
            await vars_["WS_Cur_OutPut"].write_value(123.0)
            return await oe.read_once(ep)

    pts = asyncio.run(run())
    tags = {p["tag"]: p for p in pts}
    assert len(pts) == len(oe.WS_MAP) == 6
    # ánh xạ WS → UNS đúng
    assert "brewery/site01/chiet/filler01/speed" in tags
    assert tags["brewery/site01/chiet/filler01/output_good"]["value"] == 123.0
    assert tags["brewery/site01/chiet/filler01/speed"]["unit"] == "lon/phút"
    assert all(p["source"] == "opcua-ws" for p in pts)
