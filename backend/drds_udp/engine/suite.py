"""Collection-runner style test suite: "does everything in the docs work on this robot?"

Levels:
  safe     — read-only / error-path checks, robot state untouched (default)
  caution  — re-applies current state or harmless settings (opt-in)
  motion   — moves the robot (opt-in, keep the E-STOP close)
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal

from ..protocol import AsduFormat, get_command
from ..protocol.catalog import REPORTS
from .session import SendSpec, Session

Level = Literal["safe", "caution", "motion"]
Status = Literal["pass", "warn", "fail", "skip", "error"]


@dataclass
class CheckResult:
    status: Status
    summary: str
    details: dict = field(default_factory=dict)


@dataclass
class Check:
    id: str
    name: str
    level: Level
    section: str
    description: str
    fn: Callable[["Ctx"], Awaitable[CheckResult]]

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "level": self.level, "section": self.section,
                "description": self.description}


@dataclass
class Ctx:
    s: Session
    report_window: float = 3.0
    _rates: dict | None = None


def _cmd(cid: str, items=None, **kw) -> SendSpec:
    c = get_command(cid)
    return SendSpec(type=c.type, command=c.command, items=c.example if items is None else items, kind="suite", **kw)


def _resp_summary(r: dict) -> dict:
    resp = r.get("response") or {}
    return {"status": r["status"], "msg_id": r["msg_id"], "latency_ms": r.get("latency_ms"),
            "error_code": resp.get("error_code"), "error_info": resp.get("error_info"), "items": resp.get("items")}


def _expect_code(r: dict, code: int, what: str) -> CheckResult:
    d = _resp_summary(r)
    if r["status"] != "ok":
        return CheckResult("fail", f"no response within timeout ({what})", d)
    got = d["error_code"]
    if got == code:
        return CheckResult("pass", f"ErrorCode {code:#06x} as documented — {d['latency_ms']} ms", d)
    return CheckResult("fail", f"expected ErrorCode {code:#06x}, got {got!r}", d)


def _nav_guard(r: dict) -> CheckResult | None:
    resp = r.get("response") or {}
    if resp.get("error_code") == 0xE00A:
        return CheckResult("warn", "E00A Unsupported function — navigation needs the PRO version", _resp_summary(r))
    return None


# ------------------------------------------------------------------- checks
async def c_link(ctx: Ctx) -> CheckResult:
    s = ctx.s
    if s.state != "connected":
        return CheckResult("fail", f"session not connected ({s.state}: {s.error})")
    t = s.transport.describe()
    extra = f" — {t.get('protocol')} {t.get('cipher')}" if t.get("protocol") else ""
    return CheckResult("pass", f"{t['kind'].upper()} {t['local']} -> {t['remote']}{extra}", t)


async def c_heartbeat(ctx: Ctx) -> CheckResult:
    return _expect_code(await ctx.s.send(_cmd("heartbeat")), 0, "heartbeat")


async def _measure(ctx: Ctx) -> dict:
    if ctx._rates is None:
        s = ctx.s
        if not s.hb["enabled"]:
            s.set_heartbeat(True)
        before = {rid: r["count"] for rid, r in s.reports.items()}
        t0 = time.monotonic()
        await asyncio.sleep(ctx.report_window)
        dt_s = time.monotonic() - t0
        ctx._rates = {}
        for rep in REPORTS:
            now_count = s.reports.get(rep.id, {}).get("count", 0)
            n = now_count - before.get(rep.id, 0)
            ctx._rates[rep.id] = {"count": n, "hz": round(n / dt_s, 2), "expected_hz": rep.hz,
                                  "fragments": s.reports.get(rep.id, {}).get("fragments")}
    return ctx._rates


def _report_check(rid: str):
    async def fn(ctx: Ctx) -> CheckResult:
        m = (await _measure(ctx))[rid]
        exp = m["expected_hz"]
        if m["count"] == 0:
            hb = ctx.s.hb
            hint = ("heartbeat ACKed but no reports — robot may report to another port"
                    if hb["acked"] else "no heartbeat ACK either — link/port/encryption problem")
            return CheckResult("fail", f"no report received in {ctx.report_window:.0f}s — {hint}", m)
        ratio = m["hz"] / exp
        txt = f"{m['hz']} Hz (expected {exp} Hz)"
        if m.get("fragments") and m["fragments"] > 1:
            txt += f" · multi-packet x{m['fragments']}"
        if 0.6 <= ratio <= 1.5:
            return CheckResult("pass", txt, m)
        return CheckResult("warn", txt + " — rate outside ±40%", m)

    return fn


def _query_check(cid: str, keys: list[str]):
    async def fn(ctx: Ctx) -> CheckResult:
        r = await ctx.s.send(_cmd(cid))
        guard = _nav_guard(r)
        if guard:
            return guard
        d = _resp_summary(r)
        if r["status"] != "ok":
            return CheckResult("fail", "no response within timeout", d)
        items = d["items"] if isinstance(d["items"], dict) else {}
        missing = [k for k in keys if k not in items]
        if missing:
            return CheckResult("fail", f"response missing {missing} (ErrorCode {d['error_code']})", d)
        return CheckResult("pass", ", ".join(f"{k}={items[k]}" for k in keys[:4]) + f" — {d['latency_ms']} ms", d)

    return fn


async def c_unknown(ctx: Ctx) -> CheckResult:
    r = await ctx.s.send(SendSpec(type=0x0010_0064, command=0x0099_0099, items={}, kind="suite", expect="general"))
    return _expect_code(r, 0xE003, "unknown Type/Command")


async def c_bad_json(ctx: Ctx) -> CheckResult:
    r = await ctx.s.send(SendSpec(type=0x0010_0064, command=5, body_text='{"PatrolDevice": {"Type": 1048676,',
                                  kind="suite", expect="general"))
    d = _resp_summary(r)
    if r["status"] != "ok":
        return CheckResult("warn", "no response to malformed JSON (robot may silently drop it)", d)
    if d["error_code"] in (0xE002, 0xE001):
        return CheckResult("pass", f"ErrorCode {d['error_code']:#06x} — {d['latency_ms']} ms", d)
    return CheckResult("fail", f"expected E002, got {d['error_code']!r}", d)


async def c_xml(ctx: Ctx) -> CheckResult:
    r = await ctx.s.send(_cmd("heartbeat", fmt=AsduFormat.XML))
    res = _expect_code(r, 0, "XML heartbeat")
    if res.status == "pass":
        fmt = (r.get("response") or {}).get("fmt")
        res.summary += f" · reply format {fmt}"
    return res


async def c_missing(ctx: Ctx) -> CheckResult:
    return _expect_code(await ctx.s.send(_cmd("lights", items={})), 0xE004, "lights without fields")


async def c_lights_default(ctx: Ctx) -> CheckResult:
    items = {"CustomMode": False, "Led": [{"Type": 0, "Color": [1], "Cycle": 1}, {"Type": 0, "Color": [1], "Cycle": 1}]}
    return _expect_code(await ctx.s.send(_cmd("lights", items=items)), 0, "disable custom lights")


def _basic(ctx: Ctx) -> dict | None:
    r = ctx.s.reports.get("basic")
    items = (r or {}).get("items") or {}
    return items.get("BasicStatus") if isinstance(items, dict) else None


async def c_mode_same(ctx: Ctx) -> CheckResult:
    b = _basic(ctx)
    if not b or "ControlUsageMode" not in b:
        return CheckResult("skip", "no Basic Status report yet — cannot read current mode")
    return _expect_code(await ctx.s.send(_cmd("usage_mode", {"Mode": int(b["ControlUsageMode"])})), 0,
                        "re-apply current usage mode")


async def c_gait_same(ctx: Ctx) -> CheckResult:
    b = _basic(ctx)
    if not b or not b.get("Gait"):
        return CheckResult("skip", "no Basic Status gait yet")
    return _expect_code(await ctx.s.send(_cmd("gait", {"GaitParam": int(b["Gait"])})), 0, "re-apply current gait")


async def c_nav_cancel_idle(ctx: Ctx) -> CheckResult:
    r = await ctx.s.send(_cmd("nav_cancel"))
    guard = _nav_guard(r)
    if guard:
        return guard
    d = _resp_summary(r)
    if r["status"] != "ok":
        return CheckResult("fail", "no response", d)
    return CheckResult("pass", f"ErrorCode {d['error_code']} (1 = nothing to cancel) — {d['latency_ms']} ms", d)


async def c_axis_zero(ctx: Ctx) -> CheckResult:
    s = ctx.s
    before = s.counters["responses"]
    job = await s.start_repeat(_cmd("axis"), hz=10, duration=1.0)
    await asyncio.sleep(1.4)
    extra = s.counters["responses"] - before
    d = {"sent": job["id"], "unexpected_responses": extra}
    if extra:
        return CheckResult("warn", f"robot sent {extra} response(s) to axis command (docs: none)", d)
    return CheckResult("pass", "10 zero axis frames sent, no response frame (as documented)", d)


async def _wait_motion(ctx: Ctx, state: int, timeout: float) -> bool:
    t_end = time.monotonic() + timeout
    while time.monotonic() < t_end:
        b = _basic(ctx)
        if b and int(b.get("MotionState", 999)) == state:
            return True
        await asyncio.sleep(0.2)
    return False


async def c_stand_sit(ctx: Ctx) -> CheckResult:
    r1 = await ctx.s.send(_cmd("motion_state", {"MotionParam": 1}))
    if (r1.get("response") or {}).get("error_code") != 0:
        return CheckResult("fail", "stand rejected", _resp_summary(r1))
    stood = await _wait_motion(ctx, 1, 12.0)
    r2 = await ctx.s.send(_cmd("motion_state", {"MotionParam": 4}))
    sat = await _wait_motion(ctx, 4, 12.0)
    d = {"stand": _resp_summary(r1), "sit": _resp_summary(r2), "stood": stood, "sat": sat}
    if stood and sat:
        return CheckResult("pass", "Stand -> MotionState 1, Sit -> MotionState 4 (seen in Basic Status)", d)
    return CheckResult("fail", f"state not confirmed in Basic Status (stood={stood}, sat={sat})", d)


CHECKS: list[Check] = [
    Check("link", "Transport link", "safe", "1.1.2", "Socket / DTLS / TLS session is up.", c_link),
    Check("heartbeat", "Heartbeat ACK", "safe", "1.2.1", "Heartbeat returns ErrorCode 0.", c_heartbeat),
    *[Check(f"report.{r.id}", f"Report: {r.name}", "safe", r.section,
            f"Actively reported at {r.hz:g} Hz after heartbeat.", _report_check(r.id)) for r in REPORTS],
    Check("query.location", "Get location", "safe", "1.4.2", "Data response with pose + confidence.",
          _query_check("location_get", ["Location", "PosX", "PosY", "Yaw", "Confidence", "Relocation"])),
    Check("query.perception", "Get navigation (perception) status", "safe", "1.4.3",
          "Data response with Location + ObsState.", _query_check("nav_perception", ["Location", "ObsState"])),
    Check("query.nav_state", "Query navigation task state", "safe", "1.4.6",
          "Data response with Value / Status / ErrorCode.", _query_check("nav_state", ["Value", "Status", "ErrorCode"])),
    Check("error.unknown", "Unknown Type/Command -> E003", "safe", "1.5", "Robot rejects undefined messages.",
          c_unknown),
    Check("error.parse", "Malformed JSON -> E002", "safe", "1.5", "Robot reports parse failures.", c_bad_json),
    Check("format.xml", "XML ASDU support", "safe", "1.1.6", "Heartbeat in XML (ASDU format 0x00).", c_xml),
    Check("error.missing", "Missing fields -> E004", "caution", "1.5", "Light command without Items fields.",
          c_missing),
    Check("control.lights", "Disable custom light effect", "caution", "1.2.8", "CustomMode=false (default lights).",
          c_lights_default),
    Check("control.mode", "Re-apply current usage mode", "caution", "1.2.2", "Sends the mode from Basic Status.",
          c_mode_same),
    Check("control.gait", "Re-apply current gait", "caution", "1.2.4", "Robot must be stopped.", c_gait_same),
    Check("nav.cancel", "Cancel navigation (idle)", "caution", "1.4.5", "Cancels any running nav task!",
          c_nav_cancel_idle),
    Check("motion.axis_zero", "Zero axis command stream", "motion", "1.2.5", "10 Hz zeros for 1 s, expect no reply.",
          c_axis_zero),
    Check("motion.stand_sit", "Stand then sit", "motion", "1.2.3", "ROBOT MOVES. Clear space around it.",
          c_stand_sit),
]

_BY_ID = {c.id: c for c in CHECKS}


def list_checks() -> list[dict]:
    return [c.to_dict() for c in CHECKS]


async def run_suite(session: Session, ids: list[str] | None = None, allow_caution: bool = False,
                    allow_motion: bool = False, report_window: float = 3.0) -> dict:
    run_id = uuid.uuid4().hex[:8]
    if ids:
        unknown = [i for i in ids if i not in _BY_ID]
        if unknown:
            raise ValueError(f"unknown check id(s): {', '.join(unknown)}")
        chosen = [_BY_ID[i] for i in ids]
    else:
        levels = {"safe"} | ({"caution"} if allow_caution else set()) | ({"motion"} if allow_motion else set())
        chosen = [c for c in CHECKS if c.level in levels]
    ctx = Ctx(session, report_window=report_window)
    bus = session.bus
    started = time.time()
    bus.publish("suite", {"run_id": run_id, "phase": "start", "checks": [c.to_dict() for c in chosen]})
    results = []
    for c in chosen:
        t0 = time.monotonic()
        bus.publish("suite", {"run_id": run_id, "phase": "check_start", "check": c.to_dict()})
        if c.level == "caution" and not allow_caution:
            res = CheckResult("skip", "caution checks not allowed (enable 'allow caution')")
        elif c.level == "motion" and not allow_motion:
            res = CheckResult("skip", "motion checks not allowed (enable 'allow motion')")
        elif c.id != "link" and session.state != "connected":
            res = CheckResult("skip", "not connected")
        else:
            try:
                res = await c.fn(ctx)
            except Exception as exc:  # keep running the rest
                res = CheckResult("error", f"{exc.__class__.__name__}: {exc}")
        row = {**c.to_dict(), "status": res.status, "summary": res.summary, "details": res.details,
               "duration_ms": round((time.monotonic() - t0) * 1000, 1)}
        results.append(row)
        bus.publish("suite", {"run_id": run_id, "phase": "check_done", "result": row})
    counts = {k: sum(1 for r in results if r["status"] == k) for k in ("pass", "warn", "fail", "skip", "error")}
    report = {"run_id": run_id, "started": started, "duration_s": round(time.time() - started, 2),
              "target": session.snapshot(light=True), "counts": counts, "results": results}
    bus.publish("suite", {"run_id": run_id, "phase": "done", "report": report})
    return report
