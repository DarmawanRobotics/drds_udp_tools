from .base import (
    Addr,
    ClosedCallback,
    EventCallback,
    FrameCallback,
    TlsOptions,
    Transport,
    TransportConfig,
    TransportError,
    TransportKind,
)


def create_transport(cfg: TransportConfig, on_frame: FrameCallback, on_event: EventCallback,
                     on_closed: ClosedCallback) -> Transport:
    if cfg.kind == "udp":
        from .udp import UdpTransport

        return UdpTransport(cfg, on_frame, on_event, on_closed)
    if cfg.kind == "dtls":
        from .dtls import DtlsTransport

        return DtlsTransport(cfg, on_frame, on_event, on_closed)
    if cfg.kind in ("tcp", "tls"):
        from .stream import StreamTransport

        return StreamTransport(cfg, on_frame, on_event, on_closed)
    raise TransportError(f"unknown transport '{cfg.kind}' (udp|dtls|tcp|tls)")


__all__ = [
    "Addr", "ClosedCallback", "EventCallback", "FrameCallback", "TlsOptions", "Transport", "TransportConfig",
    "TransportError", "TransportKind", "create_transport",
]
