"""Field helpers: port probe, link watchdog, compat mode, wrong-protocol hints."""

import asyncio
import socket

from drds_udp.engine import SendSpec, Session, SessionConfig
from drds_udp.engine.probe import probe
from drds_udp.mock import MockRobot
from drds_udp.transport import TlsOptions, TransportConfig, TransportError


def _free_udp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _mock(**ports) -> MockRobot:
    base = dict(udp_port=0, dtls_port=0, tcp_port=0, tls_port=0)
    base.update(ports)
    return MockRobot(host="127.0.0.1", verbose=False, **base)


def test_probe_finds_every_mode_and_flags_closed_port():
    async def main():
        robot = _mock()
        await robot.start()
        closed = _free_udp_port()
        b = robot.bound
        try:
            rep = await probe("127.0.0.1", [("dtls", b["dtls"]), ("tls", b["tls"]), ("udp", b["udp"]),
                                            ("tcp", b["tcp"]), ("udp", closed), ("tcp", b["tls"])], timeout=2.0)
        finally:
            await robot.stop()
        st = {(r["transport"], r["port"]): r for r in rep["results"]}
        for kind in ("dtls", "tls", "udp", "tcp"):
            assert st[(kind, b[kind])]["status"] == "ok", st[(kind, b[kind])]
        assert st[("udp", closed)]["status"] == "refused"
        tcp_on_tls = st[("tcp", b["tls"])]
        assert tcp_on_tls["status"] == "no_reply" and "expects TLS" in tcp_on_tls["detail"].replace(
            "probably expects TLS", "expects TLS"), tcp_on_tls
        assert rep["best"]["transport"] == "dtls"
        assert st[("dtls", b["dtls"])]["protocol"].startswith("DTLS")

    asyncio.run(main())


def test_dtls_against_plain_udp_port_gives_clear_error():
    async def main():
        robot = _mock(dtls_port=None, tcp_port=None, tls_port=None)
        await robot.start()
        s = Session()
        cfg = SessionConfig(transport=TransportConfig(kind="dtls", host="127.0.0.1", port=robot.bound["udp"],
                                                      connect_timeout=1.5))
        try:
            await s.connect(cfg)
            raise AssertionError("handshake should fail")
        except TransportError as exc:
            assert "timeout" in str(exc).lower() or "plain" in str(exc).lower(), exc
        finally:
            await robot.stop()

    asyncio.run(main())


def test_compat_mode_still_connects():
    async def main():
        robot = _mock(udp_port=None, tcp_port=None)
        await robot.start()
        try:
            for kind in ("dtls", "tls"):
                s = Session()
                cfg = SessionConfig(transport=TransportConfig(kind=kind, host="127.0.0.1", port=robot.bound[kind],
                                                              connect_timeout=2.0, tls=TlsOptions(compat=True)),
                                    heartbeat_enabled=False)
                await s.connect(cfg)
                r = await s.send(SendSpec(type=0x00100064, command=5, items={}))
                assert r["status"] == "ok", (kind, r)
                await s.disconnect()
        finally:
            await robot.stop()

    asyncio.run(main())


def test_link_watchdog_reports_loss_and_recovery():
    async def main():
        robot = _mock(dtls_port=None, tcp_port=None, tls_port=None)
        await robot.start()
        port = robot.bound["udp"]
        s = Session()
        await s.connect(SessionConfig(transport=TransportConfig(kind="udp", host="127.0.0.1", port=port),
                                      heartbeat_hz=5.0))
        try:
            await asyncio.sleep(1.0)
            assert s.stats_snapshot()["heartbeat"]["link_lost"] is False
            await robot.stop()  # robot "reboots"
            await asyncio.sleep(3.8)
            hb = s.stats_snapshot()["heartbeat"]
            assert hb["link_lost"] is True and hb["ack_age_s"] > 3.0
            assert any("link lost" in e.get("message", "") for e in s.bus.history if e["kind"] == "log")
            robot2 = MockRobot(host="127.0.0.1", udp_port=port, dtls_port=None, tcp_port=None, tls_port=None,
                               verbose=False)
            await robot2.start()
            await asyncio.sleep(1.0)
            assert s.stats_snapshot()["heartbeat"]["link_lost"] is False
            assert any("link restored" in e.get("message", "") for e in s.bus.history if e["kind"] == "log")
            await robot2.stop()
        finally:
            await s.disconnect()

    asyncio.run(main())
