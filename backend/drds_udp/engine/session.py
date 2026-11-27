"""Client session: one transport, message ids, heartbeat, response matching,
repeat jobs, report bookkeeping and the safety stop/E-STOP helpers."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal

from ..protocol import (
    HEADER_SIZE,
    MAX_FRAME_ASDU,
    AsduFormat,
    HeaderOverrides,
    build_apdu,
    build_asdu,
    decode_asdu,
    describe_error,
    encode_asdu,
    find_command,
    find_report,
    get_command,
    message_name,
    parse_datagram,
    parse_hex,
    split_apdus,
)
from ..protocol.catalog import ReportDef
from ..protocol.codes import FAULT_CODES, HEARTBEAT_COMMAND, HEARTBEAT_TYPE
from ..transport import TransportConfig, TransportError, create_transport
from .events import EventBus
from .reassembly import Assembled, Reassembler

Expect = Literal["auto", "general", "data", "none", "deferred"]
HEX_LIMIT = 16384
TEXT_LIMIT = 32768
RATE_WINDOW = 5.0


class NotConnected(RuntimeError):
    pass


@dataclass
class SessionConfig:
    transport: TransportConfig = field(default_factory=TransportConfig)
    fmt: int = AsduFormat.JSON
    heartbeat_enabled: bool = True
    heartbeat_hz: float = 2.0  # docs: >= 1 Hz, reporting stops after 2 s without heartbeat
    response_timeout: float = 1.5
    auto_split: bool = True

    def to_dict(self) -> dict:
        return {
            "transport": self.transport.to_dict(),
            "fmt": "XML" if int(self.fmt) == AsduFormat.XML else "JSON",
            "heartbeat_enabled": self.heartbeat_enabled,
            "heartbeat_hz": self.heartbeat_hz,
            "response_timeout": self.response_timeout,
            "auto_split": self.auto_split,
        }


@dataclass
class SendSpec:
    type: int | None = None
    command: int | None = None
    items: Any = None
    fmt: int | None = None
    body_text: str | None = None  # raw ASDU override, sent byte-for-byte
    raw_hex: str | None = None  # whole APDU override (header included)
    overrides: HeaderOverrides | None = None
    expect: Expect = "auto"
    timeout: float | None = None
    wait: bool = True
    kind: str = "request"  # request | heartbeat | repeat | suite | stop | estop
    label: str | None = None
    time_str: str | None = None


@dataclass
class Pending:
    msg_id: int
    type: int | None
    command: int | None
    expect: str
    kind: str
    sent_at: float
    keep_until: float
    future: asyncio.Future
    responses: list[dict] = field(default_factory=list)
    tx_seq: int | None = None


def _has_overrides(ov: HeaderOverrides | None) -> bool:
    return bool(ov) and any(v is not None for v in asdict(ov).values())


class Session:
    def __init__(self, bus: EventBus | None = None) -> None:
        self.bus = bus or EventBus()
        self.state = "disconnected"
        self.error: str | None = None
        self.cfg = SessionConfig()
        self.transport = None
        self.connected_at: float | None = None
        self._connected_mono: float | None = None
        self._msg_id = 0
        self._pending: dict[int, Pending] = {}
        self._reasm = Reassembler()
        self._tasks: list[asyncio.Task] = []
        self._repeat: dict[str, dict] = {}
        self._lock = asyncio.Lock()
        self._reset_stats()

    # ------------------------------------------------------------ lifecycle
    def _reset_stats(self) -> None:
        self.counters = dict(tx_packets=0, tx_bytes=0, rx_packets=0, rx_bytes=0, rx_messages=0, responses=0,
                             reports=0, unknown=0, timeouts=0, parse_errors=0, decode_errors=0, multi_packet=0,
                             incomplete=0)
        self._rates: dict[tuple, deque] = defaultdict(lambda: deque(maxlen=512))
        self.reports: dict[str, dict] = {}
        self._report_times: dict[str, deque] = defaultdict(lambda: deque(maxlen=256))
        self._faults: set = set()
        self.hb = dict(enabled=self.cfg.heartbeat_enabled, hz=self.cfg.heartbeat_hz, sent=0, acked=0, missed=0,
                       last_latency_ms=None, last_error_code=None, last_ack_ts=None)
        self._last_report_mono: float | None = None
        self._reasm = Reassembler()

    async def connect(self, cfg: SessionConfig) -> dict:
        async with self._lock:
            if self.state in ("connected", "connecting"):
                await self._disconnect_locked("reconnect")
            self.cfg = cfg
            self._reset_stats()
            self._set_state("connecting")
            t = create_transport(cfg.transport, self._on_frame, self._on_transport_event, self._on_transport_closed)
            try:
                await t.open()
            except Exception as exc:
                msg = str(exc) if isinstance(exc, TransportError) else f"{exc.__class__.__name__}: {exc}"
                self._set_state("error", msg)
                raise TransportError(msg) from exc
            self.transport = t
            self.connected_at = time.time()
            self._connected_mono = time.monotonic()
            self._set_state("connected")
            self._log("info", f"connected via {t.kind.upper()} {t.describe().get('local')} -> "
                              f"{cfg.transport.host}:{cfg.transport.port}")
            self._tasks = [asyncio.create_task(self._heartbeat_loop()),
                           asyncio.create_task(self._housekeeping_loop())]
            return self.snapshot()

    async def disconnect(self, reason: str = "user") -> dict:
        async with self._lock:
            await self._disconnect_locked(reason)
        return self.snapshot()

    async def _disconnect_locked(self, reason: str) -> None:
        for job in list(self._repeat.values()):
            job["task"].cancel()
        self._repeat.clear()
        for t in self._tasks:
            t.cancel()
        self._tasks = []
        if self.transport is not None:
            try:
                await self.transport.close()
            except Exception:
                pass
        self.transport = None
        for p in self._pending.values():
            if not p.future.done():
                p.future.cancel()
        self._pending.clear()
        self._connected_mono = None
        if reason in ("user", "reconnect", "shutdown"):
            self._set_state("disconnected")
        else:
            self._set_state("error", reason)

    def _on_transport_closed(self, reason: str) -> None:
        self._log("error", f"transport closed: {reason}")
        asyncio.get_running_loop().create_task(self.disconnect(reason))

    def _on_transport_event(self, level: str, message: str) -> None:
        self._log(level, message)

    def _set_state(self, state: str, error: str | None = None) -> None:
        self.state = state
        self.error = error
        self.bus.publish("session", {"state": state, "error": error, "snapshot": self.snapshot(light=True)})

    def _log(self, level: str, message: str, **extra) -> None:
        self.bus.publish("log", {"level": level, "message": message, **extra})

    def set_heartbeat(self, enabled: bool | None = None, hz: float | None = None) -> dict:
        if enabled is not None:
            self.hb["enabled"] = bool(enabled)
            self.cfg.heartbeat_enabled = bool(enabled)
        if hz is not None:
            hz = max(0.2, min(float(hz), 50.0))
            self.hb["hz"] = hz
            self.cfg.heartbeat_hz = hz
        self._log("info", f"heartbeat {'ON' if self.hb['enabled'] else 'OFF'} @ {self.hb['hz']:.1f} Hz")
        return dict(self.hb)

    # ----------------------------------------------------------------- send
    def _next_msg_id(self) -> int:
        mid = self._msg_id
        self._msg_id = (self._msg_id + 1) & 0xFFFF  # 0..65535 then wrap (§1.1.5)
        return mid

    async def send(self, spec: SendSpec) -> dict:
        if self.state != "connected" or self.transport is None:
            raise NotConnected("not connected — connect first")
        fmt = int(spec.fmt if spec.fmt is not None else self.cfg.fmt)
        ov = spec.overrides
        typ, cmd = spec.type, spec.command
        asdu_obj = None

        if spec.raw_hex:
            raw = parse_hex(spec.raw_hex)
            frames, _ = parse_datagram(raw)
            msg_id = frames[0].header.msg_id if frames else None
            if frames:
                d = decode_asdu(frames[0].body, frames[0].header.asdu_format)
                if d.ok:
                    typ, cmd = d.type, d.command
            apdus = [raw]
        else:
            msg_id = ov.msg_id if ov and ov.msg_id is not None else self._next_msg_id()
            if spec.body_text is not None:
                body = spec.body_text.encode("utf-8")
                d = decode_asdu(body, fmt)
                if d.ok:
                    typ, cmd = d.type, d.command
                    asdu_obj = d.data
            else:
                if typ is None or cmd is None:
                    raise ValueError("type and command are required")
                asdu_obj = build_asdu(typ, cmd, spec.items if spec.items is not None else {}, spec.time_str)
                body = encode_asdu(asdu_obj, fmt)
            if len(body) > MAX_FRAME_ASDU and self.cfg.auto_split and not _has_overrides(ov):
                apdus = split_apdus(body, msg_id, fmt)
            else:
                seq = ov.seq if ov and ov.seq is not None else 0
                apdus = [build_apdu(body, msg_id, fmt, seq, ov)]

        expect = spec.expect
        if expect == "auto":
            cdef = find_command(typ, cmd)
            expect = cdef.response if cdef else "general"
        timeout = float(spec.timeout or self.cfg.response_timeout)

        loop = asyncio.get_running_loop()
        now = time.monotonic()
        pend = None
        if msg_id is not None:
            if spec.kind == "heartbeat":
                keep = max(2.0, 2.0 / max(self.hb["hz"], 0.2))
            elif expect == "deferred":
                keep = 1800.0
            elif expect == "none":
                keep = 2.0
            else:
                keep = max(15.0, timeout * 4)
            pend = Pending(msg_id, typ, cmd, expect, spec.kind, now, now + keep, loop.create_future())
            old = self._pending.get(msg_id)
            if old and not old.future.done():
                old.future.cancel()
            self._pending[msg_id] = pend

        for apdu in apdus:
            await self.transport.send(apdu)
            self.counters["tx_packets"] += 1
            self.counters["tx_bytes"] += len(apdu)
        tx_ev = self._emit_tx(spec, msg_id, typ, cmd, fmt, apdus, asdu_obj, expect)
        if pend:
            pend.tx_seq = tx_ev["seq"]

        result: dict = {"msg_id": msg_id, "type": typ, "command": cmd, "name": message_name(typ, cmd),
                        "expect": expect, "status": "sent", "response": None, "latency_ms": None,
                        "tx": tx_ev}
        if expect == "none":
            result["status"] = "sent_no_response_expected"
            return result
        if not spec.wait or pend is None:
            return result
        try:
            first = await asyncio.wait_for(asyncio.shield(pend.future), timeout)
            result.update(status="ok", response=first, latency_ms=first["latency_ms"])
        except asyncio.TimeoutError:
            result["status"] = "timeout"
            self.counters["timeouts"] += 1
        except asyncio.CancelledError:
            if pend.future.cancelled():
                result["status"] = "cancelled"
            else:
                raise
        return result

    def _emit_tx(self, spec: SendSpec, msg_id, typ, cmd, fmt, apdus: list[bytes], asdu_obj, expect) -> dict:
        from ..protocol.header import ApduHeader, HeaderError

        raw = b"".join(apdus)
        try:
            hdr = ApduHeader.unpack(apdus[0], strict_sync=False).to_dict()
        except HeaderError:
            hdr = None
        body = b"".join(a[HEADER_SIZE:] for a in apdus)
        return self.bus.publish("tx", {
            "dir": "tx", "class": spec.kind, "msg_id": msg_id, "type": typ, "command": cmd,
            "name": message_name(typ, cmd), "label": spec.label, "fmt": "XML" if fmt == AsduFormat.XML else "JSON",
            "size": len(raw), "packets": len(apdus), "header": hdr, "expect": expect,
            "hex": raw[:HEX_LIMIT].hex(), "text": body[:TEXT_LIMIT].decode("utf-8", "replace"),
            "data": asdu_obj,
        })

    # -------------------------------------------------------------- receive
    def _on_frame(self, data: bytes, src) -> None:
        now = time.monotonic()
        self.counters["rx_packets"] += 1
        self.counters["rx_bytes"] += len(data)
        frames, errors = parse_datagram(data)
        for err in errors:
            self.counters["parse_errors"] += 1
            self._log("warn", f"rx from {src[0]}:{src[1]}: {err}")
        if not frames:
            self.bus.publish("rx", {
                "dir": "rx", "class": "garbage", "msg_id": None, "type": None, "command": None,
                "name": "Unparseable datagram", "size": len(data), "src": f"{src[0]}:{src[1]}",
                "hex": data[:HEX_LIMIT].hex(), "ok": False, "error": "; ".join(errors), "warnings": [],
                "text": data[:TEXT_LIMIT].decode("utf-8", "replace"), "data": None, "header": None,
                "fragments": [], "complete": True,
            })
            return
        for fr in frames:
            raw = data[fr.offset: fr.offset + HEADER_SIZE + len(fr.body)]
            for asm in self._reasm.push(fr, raw, src, now):
                self._handle_message(asm, now)

    def _match_pending(self, asm: Assembled, typ, cmd) -> tuple[Pending | None, list[str]]:
        warns: list[str] = []
        p = self._pending.get(asm.header.msg_id)
        if p is not None:
            if typ is None or (p.type, p.command) == (typ, cmd):
                return p, warns
            warns.append(f"msg id {asm.header.msg_id} matches a pending request but Type/Command differ "
                         f"({message_name(p.type, p.command)})")
            return p, warns
        if typ is None:
            return None, warns
        # fallback: oldest unanswered request with the same Type/Command
        cands = [q for q in self._pending.values() if (q.type, q.command) == (typ, cmd) and not q.responses]
        if cands:
            q = min(cands, key=lambda x: x.sent_at)
            warns.append(f"matched by Type/Command only — response msg id {asm.header.msg_id} != request {q.msg_id}")
            return q, warns
        return None, warns

    def _handle_message(self, asm: Assembled, now: float) -> None:
        d = asm.decoded
        typ, cmd = d.type, d.command
        self.counters["rx_messages"] += 1
        if len(asm.fragments) > 1:
            self.counters["multi_packet"] += 1
        if not asm.complete:
            self.counters["incomplete"] += 1
        if not d.ok:
            self.counters["decode_errors"] += 1
        self._rates[(typ, cmd)].append(now)
        warns = list(asm.warnings) + list(d.warnings)
        cls, link, latency, idx = "unknown", None, None, None
        items = d.items if isinstance(d.items, dict) else None
        err_code = items.get("ErrorCode") if items else None
        report = find_report(typ, cmd) if d.ok else None

        if report is not None:
            cls = "report"
            self.counters["reports"] += 1
            self._on_report(report, d, asm, now)
        else:
            p, mw = self._match_pending(asm, typ, cmd)
            warns += mw
            if p is not None:
                cls = "heartbeat_ack" if p.kind == "heartbeat" else "response"
                latency = round((now - p.sent_at) * 1000.0, 2)
                link = p.msg_id
                if p.expect == "none":
                    warns.append("robot replied to a command documented as 'no response frame'")
                resp = {
                    "msg_id": asm.header.msg_id, "latency_ms": latency, "index": len(p.responses) + 1,
                    "type": typ, "command": cmd, "name": message_name(typ, cmd), "ok": d.ok, "fmt": d.fmt,
                    "data": d.data, "items": d.items, "text": d.text[:TEXT_LIMIT], "error": d.error,
                    "error_code": err_code, "error_info": describe_error(err_code) if err_code is not None else None,
                    "header": asm.header.to_dict(), "hex": asm.raw[:HEX_LIMIT].hex(), "fragments": asm.fragments,
                    "warnings": warns, "src": f"{asm.src[0]}:{asm.src[1]}",
                }
                p.responses.append(resp)
                idx = resp["index"]
                if not p.future.done():
                    p.future.set_result(resp)
                if p.kind == "heartbeat":
                    self.hb["acked"] += 1
                    self.hb["last_latency_ms"] = latency
                    self.hb["last_error_code"] = err_code
                    self.hb["last_ack_ts"] = time.time()
                else:
                    self.counters["responses"] += 1
            else:
                self.counters["unknown"] += 1

        self.bus.publish("rx", {
            "dir": "rx", "class": cls, "msg_id": asm.header.msg_id, "type": typ, "command": cmd,
            "name": message_name(typ, cmd), "report_id": report.id if report else None, "fmt": d.fmt,
            "size": len(asm.raw), "src": f"{asm.src[0]}:{asm.src[1]}", "header": asm.header.to_dict(),
            "fragments": asm.fragments, "complete": asm.complete, "ok": d.ok, "error": d.error,
            "warnings": warns, "data": d.data, "text": d.text[:TEXT_LIMIT], "hex": asm.raw[:HEX_LIMIT].hex(),
            "request_msg_id": link, "latency_ms": latency, "response_index": idx, "error_code": err_code,
            "error_info": describe_error(err_code) if err_code is not None else None,
        })

    def _on_report(self, report: ReportDef, d, asm: Assembled, now: float) -> None:
        self._last_report_mono = now
        times = self._report_times[report.id]
        times.append(now)
        r = self.reports.setdefault(report.id, {"id": report.id, "name": report.name, "count": 0,
                                                "expected_hz": report.hz})
        r["count"] += 1
        r["items"] = d.items
        r["time"] = d.time
        r["last_ts"] = time.time()
        r["fragments"] = len(asm.fragments)
        if report.id == "abnormal" and isinstance(d.items, dict):
            self._diff_faults(d.items.get("ErrorList") or [])

    def _diff_faults(self, errors: list) -> None:
        current = set()
        for e in errors if isinstance(errors, list) else [errors]:
            if not isinstance(e, dict):
                continue
            res = e.get("Resources")
            res_t = tuple(res) if isinstance(res, list) else (res,)
            current.add((e.get("Code"), e.get("Name"), res_t, e.get("Type")))
        for f in current - self._faults:
            code, name, res, typ = f
            label = FAULT_CODES.get(int(code), "") if isinstance(code, int) else ""
            hex_code = f"0x{code:04X}" if isinstance(code, int) else str(code)
            self._log("warn" if typ == 1 else "info",
                      f"fault {'START' if typ == 1 else 'STOP' if typ == 2 else typ}: {name} "
                      f"{hex_code} ({label or 'not in table'}) resources={list(res)}")
        for f in self._faults - current:
            self._log("info", f"fault gone from report: {f[1]} code={f[0]}")
        self._faults = current

    # ----------------------------------------------------- background loops
    async def _heartbeat_loop(self) -> None:
        hb = get_command("heartbeat")
        assert (hb.type, hb.command) == (HEARTBEAT_TYPE, HEARTBEAT_COMMAND)
        try:
            while True:
                if self.hb["enabled"] and self.state == "connected":
                    try:
                        await self.send(SendSpec(type=hb.type, command=hb.command, items={}, kind="heartbeat",
                                                 wait=False, expect="general"))
                        self.hb["sent"] += 1
                    except (TransportError, NotConnected, OSError) as exc:
                        self._log("error", f"heartbeat send failed: {exc}")
                await asyncio.sleep(1.0 / max(self.hb["hz"], 0.2))
        except asyncio.CancelledError:
            return

    async def _housekeeping_loop(self) -> None:
        last_stats = 0.0
        try:
            while True:
                await asyncio.sleep(0.25)
                now = time.monotonic()
                for asm in self._reasm.expire(now):
                    self._handle_message(asm, now)
                for mid, p in list(self._pending.items()):
                    if now > p.keep_until:
                        del self._pending[mid]
                        if not p.responses and p.kind == "heartbeat":
                            self.hb["missed"] += 1
                if now - last_stats >= 1.0:
                    last_stats = now
                    self.bus.publish("stats", {"stats": self.stats_snapshot()})
        except asyncio.CancelledError:
            return

    # ---------------------------------------------------------- repeat jobs
    async def start_repeat(self, spec: SendSpec, hz: float, duration: float | None = None,
                           count: int | None = None) -> dict:
        if self.state != "connected":
            raise NotConnected("not connected — connect first")
        hz = max(0.2, min(float(hz), 50.0))
        job_id = uuid.uuid4().hex[:8]
        job = {"id": job_id, "name": message_name(spec.type, spec.command), "type": spec.type,
               "command": spec.command, "hz": hz, "duration": duration, "count": count, "sent": 0,
               "started": time.time(), "items": spec.items}
        rspec = replace(spec, wait=False, kind="repeat")

        async def loop() -> None:
            t0 = time.monotonic()
            next_t = t0
            try:
                while True:
                    await self.send(rspec)
                    job["sent"] += 1
                    if count and job["sent"] >= count:
                        break
                    if duration and time.monotonic() - t0 >= duration:
                        break
                    next_t += 1.0 / hz
                    await asyncio.sleep(max(0.0, next_t - time.monotonic()))
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                self._log("error", f"repeat job {job_id} stopped: {exc}")
            finally:
                self._repeat.pop(job_id, None)
                self.bus.publish("repeat", {"action": "stopped", "job": _public_job(job)})

        job["task"] = asyncio.create_task(loop())
        self._repeat[job_id] = job
        self.bus.publish("repeat", {"action": "started", "job": _public_job(job)})
        return _public_job(job)

    def stop_repeat(self, job_id: str) -> bool:
        job = self._repeat.get(job_id)
        if not job:
            return False
        job["task"].cancel()
        return True

    def stop_all_repeat(self) -> int:
        jobs = list(self._repeat.values())
        for job in jobs:
            job["task"].cancel()
        return len(jobs)

    def repeat_jobs(self) -> list[dict]:
        return [_public_job(j) for j in self._repeat.values()]

    # --------------------------------------------------------------- safety
    async def stop_motion(self) -> dict:
        """Stop repeat jobs, send zero axis + zero velocity, cancel navigation."""
        stopped = self.stop_all_repeat()
        sent = []
        if self.state == "connected":
            zero = {"X": 0.0, "Y": 0.0, "Z": 0.0, "Roll": 0.0, "Pitch": 0.0, "Yaw": 0.0}
            for cid in ("axis", "velocity", "nav_cancel"):
                c = get_command(cid)
                items = dict(zero) if cid != "nav_cancel" else {}
                try:
                    await self.send(SendSpec(type=c.type, command=c.command, items=items, kind="stop", wait=False))
                    sent.append(cid)
                except Exception as exc:
                    self._log("error", f"stop: {cid} failed: {exc}")
        self._log("warn", f"STOP — {stopped} repeat job(s) stopped, sent {', '.join(sent) or 'nothing'}")
        return {"stopped_jobs": stopped, "sent": sent}

    async def estop(self) -> dict:
        """STOP + soft emergency stop (MotionParam = -2, joint damping)."""
        res = await self.stop_motion()
        out = {**res, "estop": "not_connected"}
        if self.state == "connected":
            c = get_command("motion_state")
            r = await self.send(SendSpec(type=c.type, command=c.command, items={"MotionParam": -2}, kind="estop",
                                         timeout=1.0))
            out["estop"] = r["status"]
            out["response"] = r.get("response")
        self._log("error", f"E-STOP sent (soft emergency stop) — {out['estop']}")
        return out

    # ------------------------------------------------------------- snapshots
    def _rate(self, times: deque, now: float) -> float:
        if not times or self._connected_mono is None:
            return 0.0
        window = min(RATE_WINDOW, max(now - self._connected_mono, 1e-3))
        n = sum(1 for t in times if now - t <= window)
        return round(n / window, 2)

    def stats_snapshot(self) -> dict:
        now = time.monotonic()
        rates = []
        for (typ, cmd), times in self._rates.items():
            hz = self._rate(times, now)
            rates.append({"type": typ, "command": cmd, "name": message_name(typ, cmd), "hz": hz,
                          "count": len(times)})
        reports = {}
        for rid, r in self.reports.items():
            reports[rid] = {k: v for k, v in r.items() if k != "items"}
            reports[rid]["hz"] = self._rate(self._report_times[rid], now)
        active = self._last_report_mono is not None and now - self._last_report_mono < 2.5
        return {
            "counters": dict(self.counters),
            "heartbeat": {**self.hb, "reporting_active": active},
            "rates": sorted(rates, key=lambda r: -r["hz"]),
            "reports": reports,
            "pending": len(self._pending),
            "repeat_jobs": self.repeat_jobs(),
            "reassembly": {"pending_groups": self._reasm.pending_groups,
                           "completed_multi": self._reasm.completed_multi,
                           "incomplete": self._reasm.incomplete},
            "uptime_s": round(now - self._connected_mono, 1) if self._connected_mono else 0,
            "ws_dropped": self.bus.dropped,
        }

    def snapshot(self, light: bool = False) -> dict:
        snap = {
            "state": self.state,
            "error": self.error,
            "config": self.cfg.to_dict(),
            "transport": self.transport.describe() if self.transport else None,
            "connected_at": self.connected_at,
        }
        if not light:
            snap["stats"] = self.stats_snapshot()
        return snap

    def latest_reports(self) -> dict:
        return {rid: dict(r) for rid, r in self.reports.items()}


def _public_job(job: dict) -> dict:
    return {k: v for k, v in job.items() if k != "task"}
