"""End-to-end: Session <-> MockRobot over UDP, DTLS, TCP and TLS (ephemeral ports)."""

import asyncio

import pytest

from drds_udp.engine import SendSpec, Session, SessionConfig
from drds_udp.mock import MockRobot
from drds_udp.protocol import AsduFormat, HeaderOverrides, get_command
from drds_udp.transport import TransportConfig


def _spec(cid: str, items=None, **kw) -> SendSpec:
    c = get_command(cid)
    return SendSpec(type=c.type, command=c.command, items=c.example if items is None else items, **kw)


async def _session(kind: str, port: int, fmt=AsduFormat.JSON) -> Session:
    s = Session()
    cfg = SessionConfig(transport=TransportConfig(kind=kind, host="127.0.0.1", port=port, connect_timeout=3.0),
                        fmt=fmt, heartbeat_hz=5.0)
    await s.connect(cfg)
    return s


@pytest.mark.parametrize("kind", ["udp", "dtls", "tcp", "tls"])
def test_transport_roundtrip(kind):
    async def main():
        robot = MockRobot(host="127.0.0.1", udp_port=0, dtls_port=0, tcp_port=0, tls_port=0, verbose=False)
        await robot.start()
        s = await _session(kind, robot.bound[kind])
        try:
            r = await s.send(_spec("heartbeat"))
            assert r["status"] == "ok", r
            assert r["response"]["error_code"] == 0
            await asyncio.sleep(1.3)  # let reports flow (heartbeat loop @5 Hz keeps them alive)
            reps = s.latest_reports()
            assert {"basic", "motion", "device", "abnormal", "navigation"} <= set(reps), reps.keys()
            assert reps["device"]["fragments"] >= 2  # device state is multi-packet in the mock
            st = s.stats_snapshot()
            assert st["reports"]["motion"]["count"] >= 8
            assert st["heartbeat"]["acked"] >= 3 and st["heartbeat"]["reporting_active"]
            # data response
            r = await s.send(_spec("location_get"))
            assert r["status"] == "ok" and "PosX" in r["response"]["items"]
            # no-response command
            r = await s.send(_spec("axis"))
            assert r["status"] == "sent_no_response_expected"
            # unknown command -> E003
            r = await s.send(SendSpec(type=0x00100064, command=0x00990099, items={}))
            assert r["response"]["error_code"] == 0xE003
            # missing field -> E004
            r = await s.send(_spec("lights", items={}))
            assert r["response"]["error_code"] == 0xE004
            # malformed body -> E002
            r = await s.send(SendSpec(type=0, command=0, body_text='{"PatrolDevice": {"Type": 1'))
            assert r["response"]["error_code"] == 0xE002, r
        finally:
            await s.disconnect()
            await robot.stop()

    asyncio.run(main())


def test_xml_and_nav_task_deferred_response():
    async def main():
        robot = MockRobot(host="127.0.0.1", udp_port=0, dtls_port=None, tcp_port=None, tls_port=None, verbose=False)
        await robot.start()
        s = await _session("udp", robot.bound["udp"], fmt=AsduFormat.XML)
        try:
            r = await s.send(_spec("heartbeat"))
            assert r["status"] == "ok" and r["response"]["fmt"] == "XML"
            # nav in regular mode -> general OK now, then deferred 0xA328
            r = await s.send(_spec("nav_task"))
            assert r["response"]["error_code"] == 0
            await asyncio.sleep(0.2)
            p = s._pending[r["msg_id"]]
            assert len(p.responses) == 2 and p.responses[1]["error_code"] == 0xA328
            # proper flow: navigation mode + stand + nav to (0.3, 0)
            await s.send(_spec("usage_mode", {"Mode": 1}))
            await s.send(_spec("motion_state", {"MotionParam": 1}))
            items = {"Item": [{**get_command("nav_task").example["Item"][0], "PosX": 0.3, "Speed": 2}]}
            r = await s.send(_spec("nav_task", items, fmt=AsduFormat.JSON))
            await asyncio.sleep(1.5)
            p = s._pending[r["msg_id"]]
            assert p.responses[-1]["items"]["Status"] == 4 and p.responses[-1]["error_code"] == 0x2300
            # header override: custom msg id echoed back
            r = await s.send(_spec("heartbeat", overrides=HeaderOverrides(msg_id=4242)))
            assert r["response"]["msg_id"] == 4242
        finally:
            await s.disconnect()
            await robot.stop()

    asyncio.run(main())


def test_repeat_and_estop():
    async def main():
        robot = MockRobot(host="127.0.0.1", udp_port=0, dtls_port=None, tcp_port=None, tls_port=None, verbose=False)
        await robot.start()
        s = await _session("udp", robot.bound["udp"])
        try:
            await s.send(_spec("motion_state", {"MotionParam": 1}))
            job = await s.start_repeat(_spec("axis", {"X": 0.5, "Y": 0, "Z": 0, "Roll": 0, "Pitch": 0, "Yaw": 0}),
                                       hz=20)
            await asyncio.sleep(0.6)
            assert robot.sim.vel[0] > 0.2
            res = await s.estop()
            assert res["stopped_jobs"] == 1 and res["estop"] == "ok"
            assert robot.sim.motion_state == -2
            assert s.repeat_jobs() == []
            assert job["id"]
        finally:
            await s.disconnect()
            await robot.stop()

    asyncio.run(main())
