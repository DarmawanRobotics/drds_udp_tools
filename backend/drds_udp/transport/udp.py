from __future__ import annotations

import asyncio
import socket

from .base import Transport, TransportError


class _UdpProto(asyncio.DatagramProtocol):
    def __init__(self, owner: "UdpTransport") -> None:
        self.owner = owner

    def datagram_received(self, data: bytes, addr) -> None:
        self.owner.bytes_in += len(data)
        self.owner.on_frame(data, addr)

    def error_received(self, exc: Exception) -> None:
        if isinstance(exc, ConnectionRefusedError):
            self.owner.on_event("error", f"ICMP port unreachable from {self.owner.cfg.host}:{self.owner.cfg.port} "
                                         "— nothing listening on that UDP port (encryption on? wrong port?)")
        else:
            self.owner.on_event("error", f"UDP socket error: {exc!r}")

    def connection_lost(self, exc) -> None:
        if exc:
            self.owner.on_closed(f"UDP socket lost: {exc!r}")


async def resolve_ipv4(host: str, port: int) -> tuple[str, int]:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, family=socket.AF_INET, type=socket.SOCK_DGRAM)
    except socket.gaierror as exc:
        raise TransportError(f"cannot resolve host '{host}': {exc}") from exc
    return infos[0][4][0], infos[0][4][1]


class UdpTransport(Transport):
    kind = "udp"

    async def open(self) -> None:
        loop = asyncio.get_running_loop()
        self.remote_addr = await resolve_ipv4(self.cfg.host, self.cfg.port)
        local = (self.cfg.bind_host, self.cfg.bind_port)
        try:
            self._transport, _ = await loop.create_datagram_endpoint(
                lambda: _UdpProto(self),
                local_addr=local,
                remote_addr=self.remote_addr if self.cfg.udp_connect else None,
                family=socket.AF_INET,
            )
        except OSError as exc:
            raise TransportError(f"cannot bind UDP {local[0]}:{local[1]}: {exc}") from exc
        self.local_addr = self._transport.get_extra_info("sockname")
        self.info = {"connected_socket": self.cfg.udp_connect}

    async def send(self, data: bytes) -> None:
        if self.cfg.udp_connect:
            self._transport.sendto(data)
        else:
            self._transport.sendto(data, self.remote_addr)
        self.bytes_out += len(data)

    async def close(self) -> None:
        t = getattr(self, "_transport", None)
        if t:
            t.close()
