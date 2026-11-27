"""Field helper: find which transport + port the robot actually answers on.

Each candidate gets its own short-lived session (own local port), a connect /
handshake and one heartbeat. Results:

    ok                heartbeat answered (link works)
    no_reply          connected / sent, but nothing came back
    refused           ICMP port unreachable or TCP RST — nothing listens there
    unreachable       no route to the robot (this Mac is not on the robot subnet / wrong IP)
    handshake_failed  DTLS/TLS handshake rejected (reason + hint in `detail`)
    timeout           no answer to connect / handshake at all
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import replace

from ..protocol.codes import (
    DEFAULT_ROBOT_HOST,
    HEARTBEAT_COMMAND,
    HEARTBEAT_TYPE,
    PORT_DTLS,
    PORT_TCP_PLAIN,
    PORT_TLS,
    PORT_UDP_PLAIN,
    describe_error,
)
from ..transport import TlsOptions, TransportConfig, TransportError
from .session import SendSpec, Session, SessionConfig

# robot defaults first, then the plain fallbacks (encryption disabled: assumed ports and the same ports)
DEFAULT_CANDIDATES: list[tuple[str, int]] = [
    ("dtls", PORT_DTLS),
    ("tls", PORT_TLS),
    ("udp", PORT_UDP_PLAIN),
    ("udp", PORT_DTLS),
    ("tcp", PORT_TCP_PLAIN),
    ("tcp", PORT_TLS),
]
PREFERENCE = {"dtls": 0, "tls": 1, "udp": 2, "tcp": 3}


_ERRNO = {
    # Linux / macOS errno numbers as they appear in "[Errno N] ..."
    111: "refused", 61: "refused",  # ECONNREFUSED
    113: "unreachable", 65: "unreachable",  # EHOSTUNREACH
    101: "unreachable", 51: "unreachable",  # ENETUNREACH
    112: "unreachable", 64: "unreachable",  # EHOSTDOWN
    110: "timeout", 60: "timeout",  # ETIMEDOUT
}


def _classify_error(msg: str) -> str:
    m = msg.lower()
    match = re.search(r"\[errno (\d+)\]", m)
    if match and int(match.group(1)) in _ERRNO:
        return _ERRNO[int(match.group(1))]
    if "port unreachable" in m or "connection refused" in m:
        return "refused"
    if "no route to host" in m or "network is unreachable" in m or "host is down" in m:
        return "unreachable"
    if "timeout" in m or "timed out" in m:
        return "timeout"
    if "handshake" in m or "certificate" in m or "ssl" in m:
        return "handshake_failed"
    return "error"


async def probe_one(host: str, kind: str, port: int, timeout: float = 2.5, tls: TlsOptions | None = None,
                    reply_timeout: float = 1.5) -> dict:
    session = Session()
    cfg = SessionConfig(
        transport=TransportConfig(kind=kind, host=host, port=port, connect_timeout=timeout,
                                  tls=replace(tls) if tls else TlsOptions()),
        heartbeat_enabled=False,
        response_timeout=reply_timeout,
    )
    out: dict = {"transport": kind, "port": port, "status": "error", "detail": "", "latency_ms": None,
                 "error_code": None, "protocol": None, "cipher": None}
    t0 = time.monotonic()
    try:
        await session.connect(cfg)
    except TransportError as exc:
        out.update(status=_classify_error(str(exc)), detail=str(exc))
        out["elapsed_ms"] = round((time.monotonic() - t0) * 1000, 1)
        return out
    try:
        info = session.transport.describe() if session.transport else {}
        out.update(protocol=info.get("protocol"), cipher=info.get("cipher"))
        res = await session.send(SendSpec(type=HEARTBEAT_TYPE, command=HEARTBEAT_COMMAND, items={}, kind="probe",
                                          expect="general", timeout=reply_timeout))
        if res["status"] == "ok":
            resp = res["response"] or {}
            code = resp.get("error_code")
            label = describe_error(code)["label"] if code is not None else "data reply"
            out.update(status="ok", latency_ms=res["latency_ms"], error_code=code,
                       detail=f"heartbeat answered: {label} in {res['latency_ms']} ms"
                              + (f" ({info.get('protocol')})" if info.get("protocol") else ""))
        else:
            await asyncio.sleep(0.15)  # let a late ICMP error / close event land
            logs = [e.get("message", "") for e in session.bus.history if e["kind"] == "log"]
            if any("ICMP port unreachable" in m for m in logs):
                out.update(status="refused", detail="ICMP port unreachable — nothing listens on this UDP port")
            elif session.state == "error" and session.error:
                out.update(status="no_reply", detail=f"connection closed: {session.error}")
            else:
                out.update(status="no_reply",
                           detail="sent a heartbeat, no answer" + (" (UDP: wrong mode/port, or replies from another port)"
                                                                   if kind == "udp" else ""))
    except Exception as exc:  # keep probing the others
        out.update(status="error", detail=f"{exc.__class__.__name__}: {exc}")
    finally:
        await session.disconnect()
    out["elapsed_ms"] = round((time.monotonic() - t0) * 1000, 1)
    return out


async def probe(host: str = DEFAULT_ROBOT_HOST, candidates: list[tuple[str, int]] | None = None,
                timeout: float = 2.5, tls: TlsOptions | None = None) -> dict:
    cands = candidates or DEFAULT_CANDIDATES
    results = await asyncio.gather(*(probe_one(host, k, p, timeout, tls) for k, p in cands))
    ok = [r for r in results if r["status"] == "ok"]
    best = min(ok, key=lambda r: (PREFERENCE.get(r["transport"], 9), r["latency_ms"] or 0)) if ok else None
    return {"host": host, "results": list(results), "best": best}
