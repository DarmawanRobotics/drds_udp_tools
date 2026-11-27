from __future__ import annotations

import abc
from dataclasses import asdict, dataclass, field
from typing import Callable, Literal

TransportKind = Literal["udp", "dtls", "tcp", "tls"]
Addr = tuple  # (host, port)

FrameCallback = Callable[[bytes, Addr], None]
EventCallback = Callable[[str, str], None]  # (level, message)
ClosedCallback = Callable[[str], None]


class TransportError(RuntimeError):
    pass


@dataclass
class TlsOptions:
    verify: bool = False  # robot certs are usually self-signed
    ca_file: str | None = None
    cert_file: str | None = None  # client cert (mutual TLS)
    key_file: str | None = None
    ciphers: str | None = None
    server_name: str | None = None  # SNI / hostname check
    dtls_mtu: int = 1400
    compat: bool = False  # allow old protocol versions / weak ciphers (OpenSSL security level 0)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TransportConfig:
    kind: TransportKind = "dtls"
    host: str = "10.21.33.103"
    port: int = 30004
    bind_host: str = "0.0.0.0"
    bind_port: int = 0  # 0 = ephemeral
    connect_timeout: float = 5.0
    udp_connect: bool = True  # connected UDP socket -> ICMP "port unreachable" surfaces as error
    tls: TlsOptions = field(default_factory=TlsOptions)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tls"] = self.tls.to_dict()
        return d


class Transport(abc.ABC):
    """A connected client channel to the robot.

    `on_frame` receives: UDP -> raw datagram, DTLS -> decrypted record,
    TCP/TLS -> one framed APDU (header + body). The session parses all of
    them the same way with `parse_datagram`.
    """

    kind: TransportKind = "udp"
    is_stream = False

    def __init__(
        self,
        cfg: TransportConfig,
        on_frame: FrameCallback,
        on_event: EventCallback,
        on_closed: ClosedCallback,
    ) -> None:
        self.cfg = cfg
        self.on_frame = on_frame
        self.on_event = on_event
        self.on_closed = on_closed
        self.local_addr: Addr | None = None
        self.remote_addr: Addr | None = None
        self.bytes_in = 0  # on the wire (ciphertext for DTLS/TLS)
        self.bytes_out = 0
        self.info: dict = {}

    @abc.abstractmethod
    async def open(self) -> None: ...

    @abc.abstractmethod
    async def send(self, data: bytes) -> None: ...

    @abc.abstractmethod
    async def close(self) -> None: ...

    def describe(self) -> dict:
        return {
            "kind": self.kind,
            "local": _fmt_addr(self.local_addr),
            "remote": _fmt_addr(self.remote_addr),
            "bytes_in": self.bytes_in,
            "bytes_out": self.bytes_out,
            **self.info,
        }


def _fmt_addr(a: Addr | None) -> str | None:
    if not a:
        return None
    return f"{a[0]}:{a[1]}"
