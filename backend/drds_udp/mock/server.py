"""Mock robot server: UDP / DTLS / TCP / TLS endpoints speaking the inspection protocol.

    ezra-udp mock                 # 127.0.0.1 udp:30000 dtls:30004 tcp:30001 tls:30003
"""

from __future__ import annotations

import asyncio
import datetime as dt
import errno
import logging
import random
import ssl
import tempfile
import time
from pathlib import Path
from typing import Callable

from ..protocol import (
    AsduFormat,
    StreamFramer,
    build_asdu,
    decode_asdu,
    encode_asdu,
    message_name,
    parse_datagram,
    split_apdus,
)
from .sim import E_FORMAT, Reply, RobotSim, general

log = logging.getLogger("ezra.mock")


class PortBusyError(OSError):
    """A mock robot port is taken, usually by another mock robot."""


def _addr_in_use(exc: BaseException | None) -> bool:
    """EADDRINUSE anywhere in the chain (uvloop wraps the UDP bind error without an errno)."""
    while exc is not None:
        if isinstance(exc, OSError) and exc.errno == errno.EADDRINUSE:
            return True
        exc = exc.__cause__ or exc.__context__
    return False


class MockClient:
    def __init__(self, kind: str, addr: tuple, send_raw: Callable[[bytes], None], loss: float = 0.0) -> None:
        self.kind = kind
        self.addr = addr
        self._send_raw = send_raw
        self.loss = loss
        self.fmt = int(AsduFormat.JSON)
        self.last_hb: float | None = None
        self.report_id = 0
        self.alive = True

    @property
    def label(self) -> str:
        return f"{self.kind}://{self.addr[0]}:{self.addr[1]}"

    def send(self, reply: Reply, msg_id: int, fmt: int | None = None) -> None:
        if not self.alive:
            return
        body = encode_asdu(build_asdu(reply.type, reply.command, reply.items), self.fmt if fmt is None else fmt)
        for apdu in split_apdus(body, msg_id, self.fmt if fmt is None else fmt):  # >1000 B -> multi-packet
            if self.loss and random.random() < self.loss:
                continue
            try:
                self._send_raw(apdu)
            except Exception as exc:  # client gone
                log.debug("send to %s failed: %s", self.label, exc)
                self.alive = False
                return

    def next_report_id(self) -> int:
        self.report_id = (self.report_id + 1) & 0xFFFF
        return self.report_id

    @property
    def reporting(self) -> bool:
        return self.alive and self.last_hb is not None and time.monotonic() - self.last_hb < 2.0


class MockRobot:
    def __init__(self, host: str = "127.0.0.1", udp_port: int | None = 30000, dtls_port: int | None = 30004,
                 tcp_port: int | None = 30001, tls_port: int | None = 30003, version: str = "PRO",
                 sdk_unlocked: bool = False, faults: bool = False, loss: float = 0.0, verbose: bool = True,
                 require_client_cert: bool = False) -> None:
        self.host = host
        self.ports = {"udp": udp_port, "dtls": dtls_port, "tcp": tcp_port, "tls": tls_port}
        self.sim = RobotSim(version=version, sdk_unlocked=sdk_unlocked, faults=faults)
        self.loss = loss
        self.verbose = verbose
        self.clients: dict[tuple, MockClient] = {}
        self._closers: list[Callable] = []
        self._tasks: list[asyncio.Task] = []
        self._certdir = tempfile.TemporaryDirectory(prefix="ezra-mock-")
        self.cert_file, self.key_file = _make_self_signed(Path(self._certdir.name))
        # like the real robot: DTLS/TLS only talk to clients with a certificate signed by this CA
        self.client_ca_file = self.client_cert_file = self.client_key_file = None
        if require_client_cert:
            self.client_ca_file, self.client_cert_file, self.client_key_file = _make_client_ca(Path(self._certdir.name))
        self.bound: dict[str, int] = {}

    # ---------------------------------------------------------------- core
    def _process(self, client: MockClient, data: bytes) -> None:
        frames, errors = parse_datagram(data)
        for e in errors:
            self._log(client, f"parse error: {e}")
        for fr in frames:
            fmt = fr.header.asdu_format
            if fmt not in (0, 1):
                client.send(Reply(0, 0, general(E_FORMAT)), fr.header.msg_id, fmt=int(AsduFormat.JSON))
                self._log(client, f"#{fr.header.msg_id} E001 unsupported ASDU format 0x{fmt:02X}")
                continue
            client.fmt = fmt
            d = decode_asdu(fr.body, fmt)
            if not d.ok:
                if d.fmt == "?":
                    client.send(Reply(0, 0, general(E_FORMAT)), fr.header.msg_id)
                    self._log(client, f"#{fr.header.msg_id} E001 body is neither JSON nor XML")
                else:
                    client.send(Reply(d.type or 0, d.command or 0, general(0xE002)), fr.header.msg_id)
                    self._log(client, f"#{fr.header.msg_id} E002 {d.error}")
                continue
            msg_id = fr.header.msg_id
            payload = d.payload
            if (d.type, d.command) == (0x00100064, 5):
                client.last_hb = time.monotonic()
            what = self.sim.handle(payload, lambda r, c=client, m=msg_id: c.send(r, m))
            if what != "heartbeat":
                self._log(client, f"#{msg_id} {message_name(d.type, d.command)} {d.items or ''} -> {what}")

    def _log(self, client: MockClient, msg: str) -> None:
        if self.verbose:
            print(f"[mock {time.strftime('%H:%M:%S')}] {client.label} {msg}", flush=True)

    async def _report_loop(self) -> None:
        tick = 0
        last = time.monotonic()
        while True:
            await asyncio.sleep(0.1)
            now = time.monotonic()
            self.sim.step(now - last)
            last = now
            tick += 1
            targets = [c for c in self.clients.values() if c.reporting]
            if not targets:
                continue
            for rep in self.sim.reports(tick):
                for c in targets:
                    c.send(rep, c.next_report_id())

    # ---------------------------------------------------------- transports
    async def _bind(self, kind: str, opener):
        try:
            return await opener()
        except OSError as exc:
            if _addr_in_use(exc):
                raise PortBusyError(errno.EADDRINUSE, f"{kind.upper()} port {self.ports[kind]} on {self.host} is already "
                                    "in use (another mock robot running? make demo / make mock / ezra-udp serve --mock)") from exc
            raise

    async def start(self) -> None:
        try:
            await self._start()
        except OSError:
            await self.stop()  # close whatever did bind
            raise

    async def _start(self) -> None:
        loop = asyncio.get_running_loop()
        if self.ports["udp"] is not None:
            t, _ = await self._bind("udp", lambda: loop.create_datagram_endpoint(
                lambda: _UdpServer(self), local_addr=(self.host, self.ports["udp"])))
            self.bound["udp"] = t.get_extra_info("sockname")[1]
            self._closers.append(t.close)
        if self.ports["dtls"] is not None:
            t, _ = await self._bind("dtls", lambda: loop.create_datagram_endpoint(
                lambda: _DtlsServer(self), local_addr=(self.host, self.ports["dtls"])))
            self.bound["dtls"] = t.get_extra_info("sockname")[1]
            self._closers.append(t.close)
        if self.ports["tcp"] is not None:
            srv = await self._bind("tcp", lambda: asyncio.start_server(
                lambda r, w: self._stream_client("tcp", r, w), self.host, self.ports["tcp"]))
            self.bound["tcp"] = srv.sockets[0].getsockname()[1]
            self._closers.append(srv.close)
        if self.ports["tls"] is not None:
            sctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            sctx.load_cert_chain(self.cert_file, self.key_file)
            if self.client_ca_file:
                sctx.verify_mode = ssl.CERT_REQUIRED
                sctx.load_verify_locations(self.client_ca_file)
            srv = await self._bind("tls", lambda: asyncio.start_server(
                lambda r, w: self._stream_client("tls", r, w), self.host, self.ports["tls"], ssl=sctx))
            self.bound["tls"] = srv.sockets[0].getsockname()[1]
            self._closers.append(srv.close)
        self._tasks.append(asyncio.create_task(self._report_loop()))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for c in self._closers:
            c()
        self._tasks.clear()
        self._closers.clear()
        self._certdir.cleanup()
        await asyncio.sleep(0)  # datagram transports close their socket on the next loop iteration

    async def _stream_client(self, kind: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        addr = writer.get_extra_info("peername")
        client = MockClient(kind, addr, writer.write, self.loss)
        self.clients[(kind, addr)] = client
        self._log(client, "connected")
        framer = StreamFramer()
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                for fr in framer.feed(data):
                    self._process(client, fr.header.pack() + fr.body)
        except (ConnectionError, ssl.SSLError, OSError):
            pass
        finally:
            client.alive = False
            self.clients.pop((kind, addr), None)
            self._log(client, "disconnected")
            writer.close()


class _UdpServer(asyncio.DatagramProtocol):
    def __init__(self, robot: MockRobot) -> None:
        self.robot = robot

    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        key = ("udp", addr)
        client = self.robot.clients.get(key)
        if client is None:
            client = self.robot.clients[key] = MockClient("udp", addr, lambda b, a=addr: self.transport.sendto(b, a),
                                                          self.robot.loss)
        self.robot._process(client, data)


class _DtlsPeer:
    def __init__(self, robot: MockRobot, transport, addr) -> None:
        from OpenSSL import SSL

        from ..transport.base import TlsOptions
        from ..transport.tlsconf import make_dtls_context

        ctx = make_dtls_context(TlsOptions(cert_file=robot.cert_file, key_file=robot.key_file), server=True)
        if robot.client_ca_file:
            ctx.set_verify(SSL.VERIFY_PEER | SSL.VERIFY_FAIL_IF_NO_PEER_CERT, lambda conn, cert, err, depth, ok: bool(ok))
            ctx.load_verify_locations(robot.client_ca_file)
        self.conn = SSL.Connection(ctx, None)
        self.conn.set_accept_state()
        try:
            self.conn.set_ciphertext_mtu(1400)
        except Exception:
            pass
        self.robot, self.transport, self.addr = robot, transport, addr
        self.ready = False
        self.client = MockClient("dtls", addr, self._send_app, robot.loss)

    def _flush(self) -> None:
        from OpenSSL import SSL

        while True:
            try:
                out = self.conn.bio_read(65535)
            except SSL.WantReadError:
                break
            if not out:
                break
            self.transport.sendto(out, self.addr)

    def _send_app(self, data: bytes) -> None:
        self.conn.send(data)
        self._flush()

    def feed(self, data: bytes) -> bool:
        """Returns False when the peer should be dropped."""
        from OpenSSL import SSL

        self.conn.bio_write(data)
        if not self.ready:
            try:
                self.conn.do_handshake()
                self.ready = True
                self.robot._log(self.client, f"DTLS handshake OK ({self.conn.get_cipher_name()})")
            except SSL.WantReadError:
                pass
            except SSL.Error as exc:
                self._flush()
                self.robot._log(self.client, f"DTLS handshake failed: {exc}")
                return False
            self._flush()
            if not self.ready:
                return True
        while True:
            try:
                plain = self.conn.recv(65535)
            except SSL.WantReadError:
                break
            except SSL.ZeroReturnError:
                self.robot._log(self.client, "DTLS close_notify")
                self.client.alive = False
                return False
            except SSL.Error as exc:
                self.robot._log(self.client, f"DTLS error: {exc}")
                return False
            self.robot._process(self.client, plain)
        self._flush()
        return True


class _DtlsServer(asyncio.DatagramProtocol):
    def __init__(self, robot: MockRobot) -> None:
        self.robot = robot
        self.peers: dict[tuple, _DtlsPeer] = {}

    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        peer = self.peers.get(addr)
        if peer is None:
            peer = self.peers[addr] = _DtlsPeer(self.robot, self.transport, addr)
            self.robot.clients[("dtls", addr)] = peer.client
        if not peer.feed(data):
            self.peers.pop(addr, None)
            self.robot.clients.pop(("dtls", addr), None)


def _make_self_signed(directory: Path) -> tuple[str, str]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ezra-mock-robot"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "EZRA Robotics (mock)")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=30))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = directory / "mock-cert.pem", directory / "mock-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    return str(cert_path), str(key_path)


def _make_client_ca(directory: Path) -> tuple[str, str, str]:
    """A CA plus a client certificate/key signed by it, for a mock that requires mutual TLS."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = dt.datetime.now(dt.timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ezra-mock-client-ca")])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=5))
          .not_valid_after(now + dt.timedelta(days=30))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False,
                                       key_encipherment=False, data_encipherment=False, key_agreement=False,
                                       encipher_only=False, decipher_only=False), critical=True)
          .sign(ca_key, hashes.SHA256()))
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ezra-mock-client")]))
            .issuer_name(ca_name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    paths = directory / "client-ca.pem", directory / "client-cert.pem", directory / "client-key.pem"
    paths[0].write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    paths[1].write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    paths[2].write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    return str(paths[0]), str(paths[1]), str(paths[2])


async def run_mock(**kw) -> None:
    robot = MockRobot(**kw)
    await robot.start()
    ports = ", ".join(f"{k.upper()}:{v}" for k, v in robot.bound.items())
    print(f"[mock] EZRA mock robot ({robot.sim.version}) listening on {robot.host} — {ports}", flush=True)
    print("[mock] reports start once a client sends heartbeat (Type 1048676 / Command 5) at >= 1 Hz", flush=True)
    if robot.client_cert_file:
        print(f"[mock] DTLS/TLS require a client certificate — use --cert {robot.client_cert_file} "
              f"--key {robot.client_key_file}", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await robot.stop()


__all__ = ["MockRobot", "PortBusyError", "run_mock"]
