"""DTLS client over asyncio UDP using pyOpenSSL memory BIOs.

Wire path:  APDU -> SSL_write -> memory BIO -> UDP datagram -> robot:30004
"""

from __future__ import annotations

import asyncio
import socket

from .base import Transport, TransportError
from .tlsconf import handshake_hint, make_dtls_context, ssl_error_text
from .udp import resolve_ipv4


class _DtlsProto(asyncio.DatagramProtocol):
    def __init__(self, owner: "DtlsTransport") -> None:
        self.owner = owner

    def datagram_received(self, data: bytes, addr) -> None:
        self.owner._on_datagram(data)

    def error_received(self, exc: Exception) -> None:
        self.owner._on_socket_error(exc)

    def connection_lost(self, exc) -> None:
        if exc:
            self.owner.on_closed(f"UDP socket lost: {exc!r}")


class DtlsTransport(Transport):
    kind = "dtls"

    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)
        self._conn = None
        self._transport = None
        self._handshake_done = False
        self._rx = asyncio.Event()
        self._sock_error: Exception | None = None
        self._closed = False

    async def open(self) -> None:
        from OpenSSL import SSL

        loop = asyncio.get_running_loop()
        self.remote_addr = await resolve_ipv4(self.cfg.host, self.cfg.port)
        ctx = make_dtls_context(self.cfg.tls, server=False)
        conn = SSL.Connection(ctx, None)  # None -> memory BIOs
        conn.set_connect_state()
        try:
            conn.set_ciphertext_mtu(int(self.cfg.tls.dtls_mtu))
        except (AttributeError, SSL.Error):
            pass
        if self.cfg.tls.server_name:
            conn.set_tlsext_host_name(self.cfg.tls.server_name.encode())
        self._conn = conn
        local = (self.cfg.bind_host, self.cfg.bind_port)
        try:
            self._transport, _ = await loop.create_datagram_endpoint(
                lambda: _DtlsProto(self), local_addr=local, remote_addr=self.remote_addr, family=socket.AF_INET
            )
        except OSError as exc:
            raise TransportError(f"cannot bind UDP {local[0]}:{local[1]}: {exc}") from exc
        self.local_addr = self._transport.get_extra_info("sockname")
        try:
            await self._handshake()
        except BaseException:
            self._transport.close()
            raise

    async def _handshake(self) -> None:
        from OpenSSL import SSL

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.cfg.connect_timeout
        flights = 0
        while True:
            try:
                self._conn.do_handshake()
                self._flush()
                break
            except SSL.WantReadError:
                if self._flush():
                    flights += 1
            except SSL.Error as exc:
                self._flush()  # deliver our alert to the peer
                text = ssl_error_text(exc)
                hint = handshake_hint(text, "dtls", bool(self.cfg.tls.cert_file))
                raise TransportError(f"DTLS handshake failed: {text}{hint}") from exc
            if self._sock_error:
                raise TransportError(f"DTLS handshake aborted: {self._sock_error}")
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TransportError(
                    f"DTLS handshake timeout after {self.cfg.connect_timeout:.1f}s, {flights} flight(s) sent, "
                    f"{self.bytes_in} B received — robot unreachable, port closed, or encryption disabled "
                    "(try plain UDP)"
                )
            t = self._conn.DTLSv1_get_timeout()
            wait = min(remaining, t if t is not None else 0.25)
            self._rx.clear()
            try:
                await asyncio.wait_for(self._rx.wait(), timeout=max(wait, 0.01))
            except asyncio.TimeoutError:
                try:
                    if self._conn.DTLSv1_handle_timeout():
                        self._flush()  # retransmitted flight
                except SSL.Error as exc:
                    raise TransportError(f"DTLS retransmit failed: {ssl_error_text(exc)}") from exc
        self._handshake_done = True
        self.info = {
            "protocol": self._conn.get_protocol_version_name(),
            "cipher": self._conn.get_cipher_name(),
            "peer_cert": _peer_subject(self._conn),
        }
        self.on_event("info", f"DTLS handshake OK — {self.info['protocol']} {self.info['cipher']}")

    def _on_socket_error(self, exc: Exception) -> None:
        if isinstance(exc, ConnectionRefusedError):
            msg = (f"ICMP port unreachable from {self.cfg.host}:{self.cfg.port} — "
                   "no DTLS server there (encryption disabled? wrong port?)")
        else:
            msg = f"UDP socket error: {exc!r}"
        self._sock_error = TransportError(msg)
        self.on_event("error", msg)
        self._rx.set()

    def _on_datagram(self, data: bytes) -> None:
        from OpenSSL import SSL

        self.bytes_in += len(data)
        if self._conn is None:
            return
        try:
            self._conn.bio_write(data)
        except SSL.Error as exc:
            self.on_event("error", f"DTLS bio_write: {ssl_error_text(exc)}")
            return
        if not self._handshake_done:
            self._rx.set()
            return
        self._pump_read()

    def _pump_read(self) -> None:
        from OpenSSL import SSL

        while True:
            try:
                chunk = self._conn.recv(65535)
            except SSL.WantReadError:
                break
            except SSL.ZeroReturnError:
                self._flush()
                if not self._closed:
                    self._closed = True
                    self.on_closed("robot sent DTLS close_notify")
                break
            except SSL.Error as exc:
                self.on_event("error", f"DTLS read error: {ssl_error_text(exc)}")
                break
            if chunk:
                self.on_frame(chunk, self.remote_addr)
        self._flush()

    def _flush(self) -> int:
        """Move ciphertext from the memory BIO to the socket. Returns bytes sent."""
        from OpenSSL import SSL

        sent = 0
        while True:
            try:
                out = self._conn.bio_read(65535)
            except SSL.WantReadError:
                break
            if not out:
                break
            self._transport.sendto(out)
            self.bytes_out += len(out)
            sent += len(out)
        return sent

    async def send(self, data: bytes) -> None:
        from OpenSSL import SSL

        if not self._handshake_done:
            raise TransportError("DTLS not connected")
        try:
            self._conn.send(data)
        except SSL.Error as exc:
            raise TransportError(f"DTLS write failed ({len(data)} B — larger than MTU?): {ssl_error_text(exc)}") from exc
        self._flush()

    async def close(self) -> None:
        from OpenSSL import SSL

        if self._conn is not None and self._handshake_done and not self._closed:
            try:
                self._conn.shutdown()
            except SSL.Error:
                pass
            try:
                self._flush()
            except Exception:
                pass
        self._closed = True
        if self._transport:
            self._transport.close()


def _peer_subject(conn) -> str | None:
    try:
        cert = conn.get_peer_certificate(as_cryptography=True)
    except Exception:
        return None
    return cert.subject.rfc4514_string() if cert is not None else None
