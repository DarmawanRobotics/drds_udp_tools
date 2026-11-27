"""HTTP + WebSocket API consumed by the Next.js GUI."""

from __future__ import annotations

import asyncio
import functools
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from ..engine import EventBus, NotConnected, SendSpec, Session, SessionConfig
from ..engine.suite import list_checks, run_suite
from ..protocol import (
    AsduFormat,
    HeaderOverrides,
    build_apdu,
    build_asdu,
    catalog_dict,
    decode_asdu,
    describe_error,
    encode_asdu,
    find_report,
    get_command,
    hexdump,
    message_name,
    parse_datagram,
    parse_hex,
    split_apdus,
)
from ..protocol.header import HeaderError
from ..transport import TlsOptions, TransportConfig, TransportError


# ------------------------------------------------------------------ models
class TlsIn(BaseModel):
    verify: bool = False
    ca_file: str | None = None
    cert_file: str | None = None
    key_file: str | None = None
    ciphers: str | None = None
    server_name: str | None = None
    dtls_mtu: int = 1400
    compat: bool = False


class ConnectIn(BaseModel):
    transport: Literal["udp", "dtls", "tcp", "tls"] = "dtls"
    host: str = "10.21.33.103"
    port: int = 30004
    bind_host: str = "0.0.0.0"
    bind_port: int = 0
    fmt: Literal["JSON", "XML"] = "JSON"
    heartbeat_enabled: bool = True
    heartbeat_hz: float = 2.0
    response_timeout: float = 1.5
    connect_timeout: float = 5.0
    udp_connect: bool = True
    auto_split: bool = True
    tls: TlsIn = Field(default_factory=TlsIn)


class OverridesIn(BaseModel):
    msg_id: int | None = None
    asdu_format: int | None = None
    seq: int | None = None
    version: int | None = None
    reserved_hex: str | None = None
    sync_hex: str | None = None
    length: int | None = None


class SendIn(BaseModel):
    command_id: str | None = None
    type: int | None = None
    command: int | None = None
    items: Any = None
    fmt: Literal["JSON", "XML"] | None = None
    body_text: str | None = None
    raw_hex: str | None = None
    overrides: OverridesIn | None = None
    expect: Literal["auto", "general", "data", "none", "deferred"] = "auto"
    timeout: float | None = None
    wait: bool = True
    time_str: str | None = None
    label: str | None = None


class RepeatIn(SendIn):
    hz: float = 10.0
    duration: float | None = None
    count: int | None = None


class HeartbeatIn(BaseModel):
    enabled: bool | None = None
    hz: float | None = None


class SuiteIn(BaseModel):
    checks: list[str] | None = None
    allow_caution: bool = False
    allow_motion: bool = False
    report_window: float = 3.0


class ProbeCandidate(BaseModel):
    transport: Literal["udp", "dtls", "tcp", "tls"]
    port: int


class ProbeIn(BaseModel):
    host: str = "10.21.33.103"
    timeout: float = 2.5
    candidates: list[ProbeCandidate] | None = None
    tls: TlsIn = Field(default_factory=TlsIn)


class EncodeIn(SendIn):
    msg_id: int = 0


class DecodeIn(BaseModel):
    hex: str


# ----------------------------------------------------------------- helpers
def _fmt(v: str | None) -> int | None:
    return None if v is None else int(AsduFormat.parse(v))


def _overrides(o: OverridesIn | None) -> HeaderOverrides | None:
    return HeaderOverrides(**o.model_dump()) if o else None


def _spec(body: SendIn, kind: str = "request") -> SendSpec:
    typ, cmd, items = body.type, body.command, body.items
    if body.command_id:
        c = get_command(body.command_id)
        typ = c.type if typ is None else typ
        cmd = c.command if cmd is None else cmd
        items = c.example if items is None else items
    return SendSpec(type=typ, command=cmd, items=items, fmt=_fmt(body.fmt), body_text=body.body_text,
                    raw_hex=body.raw_hex, overrides=_overrides(body.overrides), expect=body.expect,
                    timeout=body.timeout, wait=body.wait, kind=kind, label=body.label, time_str=body.time_str)


def _guard(fn):
    """Map engine exceptions to HTTP errors the GUI can show verbatim."""

    @functools.wraps(fn)
    async def wrapper(*a, **kw):
        try:
            return await fn(*a, **kw)
        except NotConnected as exc:
            raise HTTPException(409, str(exc)) from exc
        except (KeyError, ValueError, HeaderError) as exc:
            raise HTTPException(400, str(exc).strip("'\"")) from exc
        except TransportError as exc:
            raise HTTPException(502, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(502, f"socket error: {exc}") from exc

    return wrapper


def default_web_dir() -> Path | None:
    here = Path(__file__).resolve()
    for cand in (here.parents[3] / "web" / "out", Path.cwd() / "web" / "out", Path.cwd().parent / "web" / "out"):
        if (cand / "index.html").exists():
            return cand
    return None


async def _start_mock(kwargs: dict):
    from ..mock import MockRobot

    robot = MockRobot(**kwargs)
    try:
        await robot.start()
    except OSError as exc:
        await robot.stop()  # close whatever did bind
        print(f"  ! built-in mock not started: {exc} — is `ezra-udp mock` already running?", flush=True)
        return None
    ports = ", ".join(f"{k.upper()} {v}" for k, v in robot.bound.items())
    print(f"  Mock robot: {robot.host} — {ports}  (pick a Mock preset in the GUI)", flush=True)
    return robot


# --------------------------------------------------------------------- app
def create_app(web_dir: Path | None = None, session: Session | None = None, mock: dict | None = None) -> FastAPI:
    """`mock` = MockRobot kwargs to run a simulated robot inside this process (one terminal, one Ctrl+C)."""
    bus = session.bus if session else EventBus()
    sess = session or Session(bus)
    state: dict[str, Any] = {"suite_task": None, "suite_last": None}

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        robot = await _start_mock(mock) if mock is not None else None
        _app.state.mock = robot
        yield
        await sess.disconnect("shutdown")
        if robot is not None:
            await robot.stop()

    app = FastAPI(title="EZRA UDP Debugger", version=__version__, lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.state.session = sess
    app.state.mock = None

    @app.get("/api/health")
    async def health():
        robot = app.state.mock
        return {"ok": True, "name": "EZRA UDP Debugger", "version": __version__, "state": sess.state,
                "mock": dict(robot.bound) if robot is not None else None}

    @app.get("/api/catalog")
    async def catalog():
        return catalog_dict()

    @app.get("/api/session")
    async def get_session():
        return sess.snapshot()

    @app.post("/api/session/connect")
    @_guard
    async def connect(body: ConnectIn):
        tcfg = TransportConfig(kind=body.transport, host=body.host.strip(), port=body.port, bind_host=body.bind_host,
                               bind_port=body.bind_port, connect_timeout=body.connect_timeout,
                               udp_connect=body.udp_connect, tls=TlsOptions(**body.tls.model_dump()))
        cfg = SessionConfig(transport=tcfg, fmt=int(AsduFormat.parse(body.fmt)),
                            heartbeat_enabled=body.heartbeat_enabled, heartbeat_hz=body.heartbeat_hz,
                            response_timeout=body.response_timeout, auto_split=body.auto_split)
        return await sess.connect(cfg)

    @app.post("/api/session/disconnect")
    async def disconnect():
        return await sess.disconnect()

    @app.put("/api/session/heartbeat")
    async def heartbeat(body: HeartbeatIn):
        return sess.set_heartbeat(body.enabled, body.hz)

    @app.post("/api/send")
    @_guard
    async def send(body: SendIn):
        return await sess.send(_spec(body))

    @app.post("/api/repeat")
    @_guard
    async def repeat(body: RepeatIn):
        return await sess.start_repeat(_spec(body), body.hz, body.duration, body.count)

    @app.get("/api/repeat")
    async def repeat_list():
        return sess.repeat_jobs()

    @app.delete("/api/repeat/{job_id}")
    async def repeat_stop(job_id: str):
        if not sess.stop_repeat(job_id):
            raise HTTPException(404, "no such job")
        return {"stopped": job_id}

    @app.post("/api/stop")
    async def stop():
        return await sess.stop_motion()

    @app.post("/api/estop")
    @_guard
    async def estop():
        return await sess.estop()

    @app.get("/api/reports")
    async def reports():
        return sess.latest_reports()

    @app.get("/api/events")
    async def events(limit: int = 300):
        return bus.recent(limit)

    # ------------------------------------------------------ codec (offline)
    @app.post("/api/codec/encode")
    @_guard
    async def encode(body: EncodeIn):
        spec = _spec(body)
        fmt = spec.fmt if spec.fmt is not None else int(AsduFormat.JSON)
        if spec.body_text is not None:
            payload = spec.body_text.encode()
        else:
            if spec.type is None or spec.command is None:
                raise ValueError("type and command are required")
            payload = encode_asdu(build_asdu(spec.type, spec.command, spec.items or {}, spec.time_str), fmt)
        ov = spec.overrides
        if ov and any(v is not None for v in ov.__dict__.values()):
            frames = [build_apdu(payload, ov.msg_id if ov.msg_id is not None else body.msg_id, fmt, ov.seq or 0, ov)]
        else:
            frames = split_apdus(payload, body.msg_id, fmt)
        raw = b"".join(frames)
        return {"hex": raw.hex(), "hexdump": hexdump(raw), "size": len(raw), "packets": len(frames),
                "body_text": payload.decode("utf-8", "replace"),
                "headers": [parse_datagram(f)[0][0].header.to_dict() for f in frames]}

    @app.post("/api/codec/decode")
    @_guard
    async def decode(body: DecodeIn):
        raw = parse_hex(body.hex)
        frames, errors = parse_datagram(raw)
        out = []
        for fr in frames:
            d = decode_asdu(fr.body, fr.header.asdu_format)
            items = d.items if isinstance(d.items, dict) else {}
            code = items.get("ErrorCode")
            rep = find_report(d.type, d.command)
            out.append({"header": fr.header.to_dict(), "warnings": fr.warnings + d.warnings, "ok": d.ok,
                        "error": d.error, "fmt": d.fmt, "data": d.data, "text": d.text, "type": d.type,
                        "command": d.command, "name": message_name(d.type, d.command),
                        "report_id": rep.id if rep else None, "error_code": code,
                        "error_info": describe_error(code) if code is not None else None,
                        "size": 16 + len(fr.body)})
        joined = None
        if len(frames) > 1 and not all(f["ok"] for f in out):
            d = decode_asdu(b"".join(fr.body for fr in frames), frames[0].header.asdu_format)
            joined = {"ok": d.ok, "error": d.error, "data": d.data, "name": message_name(d.type, d.command)}
        return {"size": len(raw), "frames": out, "errors": errors, "joined": joined, "hexdump": hexdump(raw)}

    # ---------------------------------------------------------------- probe
    @app.post("/api/probe")
    @_guard
    async def probe_ports(body: ProbeIn):
        """Try every transport/port combination with its own socket and one heartbeat."""
        from ..engine.probe import probe

        cands = [(c.transport, c.port) for c in body.candidates] if body.candidates else None
        return await probe(body.host.strip(), cands, body.timeout, TlsOptions(**body.tls.model_dump()))

    # ---------------------------------------------------------------- suite
    @app.get("/api/suite/checks")
    async def suite_checks():
        return list_checks()

    @app.post("/api/suite/run")
    async def suite_run(body: SuiteIn):
        t = state["suite_task"]
        if t and not t.done():
            raise HTTPException(409, "a suite run is already in progress")

        async def job():
            state["suite_last"] = await run_suite(sess, body.checks, body.allow_caution, body.allow_motion,
                                                  body.report_window)

        state["suite_task"] = asyncio.create_task(job())
        return {"started": True}

    @app.get("/api/suite/last")
    async def suite_last():
        return state["suite_last"] or JSONResponse({"detail": "no run yet"}, 404)

    # ------------------------------------------------------------ websocket
    @app.websocket("/api/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        q = bus.subscribe()
        hello = {"kind": "hello", "snapshot": sess.snapshot(), "history": bus.recent(400),
                 "reports": sess.latest_reports(), "version": __version__}
        await websocket.send_text(json.dumps(hello, default=str))

        async def pump():
            while True:
                ev = await q.get()
                await websocket.send_text(json.dumps(ev, default=str))

        sender = asyncio.create_task(pump())
        try:
            while True:
                await websocket.receive_text()  # client pings; ignore
        except WebSocketDisconnect:
            pass
        finally:
            bus.unsubscribe(q)
            sender.cancel()

    if web_dir is not None and (Path(web_dir) / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
    else:
        @app.get("/")
        async def root():
            return {"name": "EZRA UDP Debugger API", "version": __version__,
                    "hint": "GUI not built — run `npm run build` in web/ (or `npm run dev` on :3000)."}

    return app
