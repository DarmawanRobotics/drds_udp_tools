"""TCP and TLS (TCP + encrypted) client with APDU stream framing."""

from __future__ import annotations

import asyncio
import ssl

from ..protocol.header import HEADER_SIZE, StreamFramer
from .base import Transport, TransportError
from .tlsconf import handshake_hint, make_ssl_context


class StreamTransport(Transport):
    is_stream = True

    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._task: asyncio.Task | None = None
        self._closing = False
        self.kind = self.cfg.kind  # "tcp" | "tls"
        self.first_bytes = b""  # first bytes received (probe uses them to spot a TLS alert on a "plain" port)

    async def open(self) -> None:
        ctx = make_ssl_context(self.cfg.tls) if self.cfg.kind == "tls" else None
        kw = {}
        if ctx is not None:
            kw["ssl"] = ctx
            kw["server_hostname"] = self.cfg.tls.server_name or self.cfg.host
        if self.cfg.bind_port:
            kw["local_addr"] = (self.cfg.bind_host, self.cfg.bind_port)
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.cfg.host, self.cfg.port, **kw), self.cfg.connect_timeout
            )
        except asyncio.TimeoutError as exc:
            raise TransportError(f"{self.kind.upper()} connect timeout to {self.cfg.host}:{self.cfg.port}") from exc
        except ssl.SSLError as exc:
            text = f"{exc.reason or ''} {exc}".strip()
            raise TransportError(f"TLS handshake failed: {exc.reason or exc}{handshake_hint(text, 'tls')}") from exc
        except OSError as exc:
            raise TransportError(f"{self.kind.upper()} connect to {self.cfg.host}:{self.cfg.port} failed: {exc}") from exc
        self.local_addr = self._writer.get_extra_info("sockname")
        self.remote_addr = self._writer.get_extra_info("peername")
        if ctx is not None:
            sslobj = self._writer.get_extra_info("ssl_object")
            if sslobj is not None:
                self.info = {"protocol": sslobj.version(), "cipher": (sslobj.cipher() or [None])[0]}
                self.on_event("info", f"TLS handshake OK — {self.info['protocol']} {self.info['cipher']}")
        self._task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        framer = StreamFramer()
        last_junk = 0
        reason = "peer closed the connection"
        try:
            while True:
                data = await self._reader.read(65536)
                if not data:
                    break
                self.bytes_in += len(data)
                if len(self.first_bytes) < 16:
                    self.first_bytes += data[: 16 - len(self.first_bytes)]
                for fr in framer.feed(data):
                    self.on_frame(fr.header.pack() + fr.body, self.remote_addr)
                if framer.junk_bytes != last_junk:
                    self.on_event("warn", f"stream resync: dropped {framer.junk_bytes - last_junk} junk byte(s)")
                    last_junk = framer.junk_bytes
        except asyncio.CancelledError:
            return
        except (ConnectionError, ssl.SSLError, OSError) as exc:
            reason = f"connection error: {exc}"
        if self.kind == "tcp" and self.first_bytes[:1] in (b"\x15", b"\x16") and self.first_bytes[1:2] == b"\x03":
            reason += " — the robot answered with a TLS record: this port expects TLS, not plain TCP"
        elif self.kind == "tcp" and self.bytes_in == 0 and self.bytes_out > 0:
            reason += " — closed without replying to our first packet: the port probably expects TLS (try TLS mode)"
        if not self._closing:
            self.on_closed(reason)

    async def send(self, data: bytes) -> None:
        if not self._writer or self._writer.is_closing():
            raise TransportError("stream not connected")
        if len(data) < HEADER_SIZE:
            self.on_event("warn", f"sending {len(data)} B — shorter than an APDU header")
        self._writer.write(data)
        await self._writer.drain()
        self.bytes_out += len(data)

    async def close(self) -> None:
        self._closing = True
        if self._task:
            self._task.cancel()
        if self._writer:
            self._writer.close()
            try:
                await asyncio.wait_for(self._writer.wait_closed(), 1.0)
            except Exception:
                pass
