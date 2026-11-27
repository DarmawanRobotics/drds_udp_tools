"""Field helpers: port probe, link watchdog, compat mode, wrong-protocol hints."""

import asyncio
import socket

import pytest

from drds_udp.engine import SendSpec, Session, SessionConfig
from drds_udp.engine.probe import probe
from drds_udp.cli import main as cli_main
from drds_udp.mock import MockRobot, PortBusyError
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


async def _busy_port_case(kind: str) -> None:
    stype = socket.SOCK_DGRAM if kind in ("udp", "dtls") else socket.SOCK_STREAM
    taken = socket.socket(socket.AF_INET, stype)
    taken.bind(("127.0.0.1", 0))
    if stype == socket.SOCK_STREAM:
        taken.listen()
    port = taken.getsockname()[1]
    robot = _mock(**{f"{kind}_port": port})
    try:
        await robot.start()
    except PortBusyError as exc:
        msg = exc.strerror
    else:
        await robot.stop()
        raise AssertionError("start() should fail on a busy port")
    finally:
        taken.close()
    assert f"{kind.upper()} port {port}" in msg and "already in use" in msg
    # ports bound before the failure are released again
    for other, bound in robot.bound.items():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM if other in ("udp", "dtls") else socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", bound))
        s.close()


@pytest.mark.parametrize("kind", ["udp", "tls"])
@pytest.mark.parametrize("loop", ["asyncio", "uvloop"])
def test_mock_names_the_busy_port_and_releases_the_rest(kind, loop):
    if loop == "uvloop":  # what `ezra-udp serve --mock` runs on (uvicorn picks uvloop when installed)
        uvloop = pytest.importorskip("uvloop")
        uvloop.run(_busy_port_case(kind))
    else:
        asyncio.run(_busy_port_case(kind))


def test_serve_refuses_a_busy_port(capsys):
    taken = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    taken.bind(("127.0.0.1", 0))
    taken.listen()
    port = taken.getsockname()[1]
    try:
        rc = cli_main(["serve", "--no-web", "--port", str(port)])
    finally:
        taken.close()
    assert rc == 1
    assert f"port {port} is already in use" in capsys.readouterr().err


def test_hints_for_what_the_factory_robot_answered():
    from drds_udp.transport.tlsconf import handshake_hint

    dtls = handshake_hint("SSL routines:tls alert handshake failure", "dtls")
    assert "client certificate" in dtls and "compat" in dtls
    assert "client certificate" not in handshake_hint("SSL routines:tls alert handshake failure", "dtls", client_cert=True)
    tls13 = handshake_hint("[SSL: TLSV13_ALERT_CERTIFICATE_REQUIRED] tlsv13 alert certificate required", "tls")
    assert "client certificate" in tls13
    assert "rejected our client certificate" in handshake_hint("tlsv1 alert unknown ca", "tls", client_cert=True)


def test_probe_explains_and_passes_a_required_client_certificate():
    async def main():
        robot = _mock(require_client_cert=True)
        await robot.start()
        b = robot.bound
        cands = [("dtls", b["dtls"]), ("tls", b["tls"])]
        try:
            bare = await probe("127.0.0.1", cands, timeout=2.0)
            with_cert = await probe("127.0.0.1", cands, timeout=2.0,
                                    tls=TlsOptions(cert_file=robot.client_cert_file, key_file=robot.client_key_file))
        finally:
            await robot.stop()
        for r in bare["results"]:
            assert r["status"] == "handshake_failed" and "client certificate" in r["detail"], r
        assert [r["status"] for r in with_cert["results"]] == ["ok", "ok"], with_cert["results"]
        assert with_cert["best"]["transport"] == "dtls"

    asyncio.run(main())
