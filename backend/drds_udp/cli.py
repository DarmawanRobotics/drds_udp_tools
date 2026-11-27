"""ezra-udp — EZRA UDP Debugger command line.

    ezra-udp serve                       # API + GUI on http://127.0.0.1:8765
    ezra-udp serve --mock                # same, plus a fake robot in the same process
    ezra-udp mock                        # fake robot on 127.0.0.1 (udp 30000 / dtls 30004 / tcp 30001 / tls 30003)
    ezra-udp list                        # every command in the docs
    ezra-udp probe                       # which mode/port does the robot answer on?
    ezra-udp send heartbeat -t dtls --host 10.21.33.103
    ezra-udp send gait --items '{"GaitParam": 4097}'
    ezra-udp listen -s 10                # heartbeat + print status reports
    ezra-udp suite --allow-caution       # run the doc conformance checks
    ezra-udp decode "eb 91 eb 90 ..."    # decode a captured APDU
"""

from __future__ import annotations

import argparse
import asyncio
import errno
import json
import sys
import time
import webbrowser
from pathlib import Path

from . import __version__
from .protocol import COMMANDS, REPORTS, AsduFormat, decode_asdu, get_command, hex32, hexdump, message_name, parse_datagram, parse_hex
from .protocol.codes import DEFAULT_ROBOT_HOST, PORT_DTLS, PORT_TCP_PLAIN, PORT_TLS, PORT_UDP_PLAIN, describe_error

DEFAULT_PORTS = {"dtls": PORT_DTLS, "tls": PORT_TLS, "udp": PORT_UDP_PLAIN, "tcp": PORT_TCP_PLAIN}


def _conn_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("connection")
    g.add_argument("-t", "--transport", choices=["dtls", "udp", "tls", "tcp"], default="dtls",
                   help="dtls (robot default, UDP+encrypted) | udp (plain) | tls | tcp")
    g.add_argument("--host", default=DEFAULT_ROBOT_HOST)
    g.add_argument("--port", type=int, help="default: dtls 30004, tls 30003, udp 30000, tcp 30001")
    g.add_argument("--bind-port", type=int, default=0, help="local port (0 = random)")
    g.add_argument("--xml", action="store_true", help="send XML ASDU instead of JSON")
    g.add_argument("--hb-hz", type=float, default=2.0, help="heartbeat rate (docs: >= 1 Hz)")
    g.add_argument("--no-heartbeat", action="store_true")
    g.add_argument("--timeout", type=float, default=1.5, help="response timeout [s]")
    g.add_argument("--verify", action="store_true", help="verify robot TLS/DTLS certificate")
    g.add_argument("--ca", help="CA file for --verify")
    g.add_argument("--cert", help="client certificate (mutual TLS)")
    g.add_argument("--key", help="client private key")
    g.add_argument("--compat", action="store_true", help="allow old TLS/DTLS versions and weak ciphers")


def _session_cfg(a):
    from .engine import SessionConfig
    from .transport import TlsOptions, TransportConfig

    port = a.port or DEFAULT_PORTS[a.transport]
    tls = TlsOptions(verify=a.verify, ca_file=a.ca, cert_file=a.cert, key_file=a.key, compat=a.compat)
    t = TransportConfig(kind=a.transport, host=a.host, port=port, bind_port=a.bind_port, tls=tls)
    return SessionConfig(transport=t, fmt=AsduFormat.XML if a.xml else AsduFormat.JSON,
                         heartbeat_enabled=not a.no_heartbeat, heartbeat_hz=a.hb_hz, response_timeout=a.timeout)


async def _connect(a):
    from .engine import Session

    s = Session()
    cfg = _session_cfg(a)
    print(f"→ connecting {cfg.transport.kind.upper()} {cfg.transport.host}:{cfg.transport.port} ...", flush=True)
    await s.connect(cfg)
    d = s.transport.describe()
    extra = f"  [{d.get('protocol')} {d.get('cipher')}]" if d.get("protocol") else ""
    print(f"✓ connected  local {d['local']}{extra}", flush=True)
    return s


def _print_response(r: dict) -> None:
    status = r["status"]
    print(f"  msg_id={r['msg_id']}  status={status}  latency={r.get('latency_ms')} ms")
    resp = r.get("response")
    if resp:
        info = resp.get("error_info")
        if info:
            ok = "✓" if info.get("ok") else "✗"
            print(f"  {ok} ErrorCode {info['code']} ({info['hex']}) {info['label']}")
        print(json.dumps(resp.get("data"), indent=2, ensure_ascii=False))


# ---------------------------------------------------------------- commands
def cmd_list(a) -> int:
    print(f"{'id':<16} {'§':<7} {'Type':<13} {'Command':<13} {'reply':<9} {'level':<8} name")
    for c in COMMANDS:
        print(f"{c.id:<16} {c.section:<7} {hex32(c.type):<13} {hex32(c.command):<13} {c.response:<9} "
              f"{c.danger:<8} {c.name}")
    print("\nreports (pushed after heartbeat):")
    for r in REPORTS:
        print(f"  {r.id:<11} §{r.section:<8} {hex32(r.type)} / {hex32(r.command)}  {r.hz:g} Hz  {r.name}")
    return 0


def cmd_send(a) -> int:
    from .engine import SendSpec

    c = get_command(a.command_id)
    items = json.loads(a.items) if a.items else c.example
    if c.danger == "motion" and not a.yes:
        print(f"! '{c.name}' can move the robot. Re-run with --yes to send.", file=sys.stderr)
        return 2

    async def main():
        s = await _connect(a)
        try:
            print(f"→ {c.name}  ({hex32(c.type)} / {hex32(c.command)})  items={json.dumps(items)}")
            r = await s.send(SendSpec(type=c.type, command=c.command, items=items, timeout=a.timeout))
            _print_response(r)
            if c.response == "deferred" and a.wait_deferred:
                print(f"  waiting up to {a.wait_deferred}s for the deferred result ...")
                p = s._pending.get(r["msg_id"])
                t_end = time.monotonic() + a.wait_deferred
                while p and len(p.responses) < 2 and time.monotonic() < t_end:
                    await asyncio.sleep(0.2)
                if p and len(p.responses) >= 2:
                    print(json.dumps(p.responses[-1]["data"], indent=2))
            return 0 if r["status"] in ("ok", "sent_no_response_expected") else 1
        finally:
            await s.disconnect()

    return asyncio.run(main())


def cmd_listen(a) -> int:
    async def main():
        s = await _connect(a)
        last: dict[str, float] = {}

        def on_event(ev):
            if ev["kind"] == "rx" and ev.get("class") == "report":
                rid = ev["report_id"]
                now = time.monotonic()
                if a.all or now - last.get(rid, 0) >= 1.0:
                    last[rid] = now
                    items = json.dumps(((ev.get("data") or {}).get("PatrolDevice") or {}).get("Items"))
                    frag = f" x{len(ev['fragments'])}pk" if len(ev.get("fragments") or []) > 1 else ""
                    print(f"[{time.strftime('%H:%M:%S')}] {rid:<10}{frag} {items[: a.width]}")
            elif ev["kind"] == "log" and ev["level"] in ("warn", "error"):
                print(f"[{ev['level']}] {ev['message']}")

        q = s.bus.subscribe()
        t_end = time.monotonic() + a.seconds
        try:
            while time.monotonic() < t_end:
                try:
                    ev = await asyncio.wait_for(q.get(), 0.5)
                except asyncio.TimeoutError:
                    continue
                on_event(ev)
        finally:
            st = s.stats_snapshot()
            print("\nmeasured report rates:")
            for rid, r in st["reports"].items():
                print(f"  {rid:<11} {r['hz']:>5} Hz (expected {r['expected_hz']})  count={r['count']}")
            hb = st["heartbeat"]
            print(f"heartbeat: sent={hb['sent']} acked={hb['acked']} missed={hb['missed']}")
            await s.disconnect()
        return 0

    return asyncio.run(main())


def cmd_suite(a) -> int:
    from .engine.suite import run_suite

    async def main():
        s = await _connect(a)
        try:
            q = s.bus.subscribe()

            async def printer():
                icons = {"pass": "✓", "warn": "!", "fail": "✗", "skip": "-", "error": "✗"}
                while True:
                    ev = await q.get()
                    if ev["kind"] == "suite" and ev["phase"] == "check_done":
                        r = ev["result"]
                        print(f"  {icons[r['status']]} {r['status']:<5} {r['name']:<42} {r['summary']}")

            pt = asyncio.create_task(printer())
            checks = a.checks.split(",") if a.checks else None
            rep = await run_suite(s, checks, a.allow_caution, a.allow_motion)
            await asyncio.sleep(0.05)
            pt.cancel()
            c = rep["counts"]
            print(f"\n{c['pass']} pass · {c['warn']} warn · {c['fail']} fail · {c['skip']} skip · {c['error']} error"
                  f"  ({rep['duration_s']} s)")
            if a.json:
                Path(a.json).write_text(json.dumps(rep, indent=2, default=str))
                print(f"report written to {a.json}")
            return 0 if c["fail"] == 0 and c["error"] == 0 else 1
        finally:
            await s.disconnect()

    return asyncio.run(main())


def cmd_probe(a) -> int:
    from .engine.probe import DEFAULT_CANDIDATES, probe
    from .transport import TlsOptions

    cands = DEFAULT_CANDIDATES
    if a.ports:
        cands = []
        for item in a.ports.split(","):
            kind, _, port = item.strip().partition(":")
            cands.append((kind.lower(), int(port)))
    tls = TlsOptions(verify=a.verify, ca_file=a.ca, cert_file=a.cert, key_file=a.key, compat=a.compat)
    print(f"→ probing {a.host} on {len(cands)} transport/port combinations (≈{a.timeout + 1.6:.0f} s) ...", flush=True)
    rep = asyncio.run(probe(a.host, cands, a.timeout, tls))
    icon = {"ok": "✓", "no_reply": "·", "refused": "✗", "unreachable": "✗", "handshake_failed": "!", "timeout": "…",
            "error": "✗"}
    print(f"\n{'mode':<6} {'port':<6} {'result':<17} detail")
    for r in rep["results"]:
        print(f"{r['transport'].upper():<6} {r['port']:<6} {icon[r['status']]} {r['status']:<15} {r['detail']}")
    best = rep["best"]
    if best:
        print(f"\n→ use: ezra-udp ... -t {best['transport']} --port {best['port']}  "
              f"(GUI: transport {best['transport'].upper()}, port {best['port']})")
        return 0
    print("\n✗ nothing answered a heartbeat. Check: ping, IP/subnet of this Mac, robot powered and robotserver running,"
          " certificates (--ca/--cert/--key) or --compat.")
    return 1


def cmd_decode(a) -> int:
    raw = parse_hex(" ".join(a.hex) if a.hex else sys.stdin.read())
    frames, errors = parse_datagram(raw)
    print(hexdump(raw))
    for e in errors:
        print(f"! {e}")
    for i, fr in enumerate(frames):
        d = decode_asdu(fr.body, fr.header.asdu_format)
        print(f"\nframe {i}: {fr.header.to_dict()}")
        for w in fr.warnings + d.warnings:
            print(f"  ! {w}")
        print(f"  {message_name(d.type, d.command)}")
        if d.ok:
            print(json.dumps(d.data, indent=2, ensure_ascii=False))
            code = (d.items or {}).get("ErrorCode") if isinstance(d.items, dict) else None
            if code is not None:
                print(f"  ErrorCode → {describe_error(code)}")
        else:
            print(f"  ✗ {d.error}\n  {d.text[:500]}")
    return 0


def cmd_mock(a) -> int:
    from .mock import run_mock

    try:
        asyncio.run(run_mock(host=a.host, udp_port=None if a.udp < 0 else a.udp, dtls_port=None if a.dtls < 0 else a.dtls,
                             tcp_port=None if a.tcp < 0 else a.tcp, tls_port=None if a.tls < 0 else a.tls,
                             version="STD" if a.std else "PRO", sdk_unlocked=a.sdk_unlocked, faults=a.faults,
                             loss=a.loss, verbose=not a.quiet))
    except KeyboardInterrupt:
        pass
    except OSError as exc:
        print(f"✗ mock robot not started: {exc.strerror or exc}", file=sys.stderr)
        return 1
    return 0


def _tcp_port_busy(host: str, port: int) -> bool:
    import socket

    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError as exc:
            return exc.errno == errno.EADDRINUSE
    return False


def cmd_serve(a) -> int:
    import uvicorn

    from .server import create_app, default_web_dir

    if _tcp_port_busy(a.host, a.port):
        print(f"✗ port {a.port} is already in use — EZRA UDP Debugger is probably running already: open "
              f"http://127.0.0.1:{a.port}, stop the other one (Ctrl+C), or use --port {a.port + 1}", file=sys.stderr)
        return 1
    web = None if a.no_web else (Path(a.web) if a.web else default_web_dir())
    mock = None
    if a.mock or a.mock_faults:
        mock = dict(host="127.0.0.1", faults=a.mock_faults, verbose=not a.mock_quiet)
    app = create_app(web, mock=mock)
    url = f"http://{'127.0.0.1' if a.host in ('0.0.0.0', '::') else a.host}:{a.port}"
    print(f"EZRA UDP Debugger {__version__}  →  {url}")
    gui = web or ("off (--no-web) — API only" if a.no_web else "not built (cd web && npm run build) — API only")
    print(f"  GUI: {gui}")
    if a.open:
        webbrowser.open(url)
    uvicorn.run(app, host=a.host, port=a.port, log_level=a.log_level, ws_ping_interval=20)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ezra-udp", description="EZRA UDP Debugger — Deep Robotics inspection protocol tool")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("serve", help="run API + GUI")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8765)
    sp.add_argument("--web", help="path to the built GUI (web/out)")
    sp.add_argument("--no-web", action="store_true")
    sp.add_argument("--open", action="store_true", help="open the browser")
    sp.add_argument("--log-level", default="warning")
    sp.add_argument("--mock", action="store_true",
                    help="also run the mock robot in this process (udp 30000, dtls 30004, tcp 30001, tls 30003)")
    sp.add_argument("--mock-faults", action="store_true", help="--mock with a fault injected every 15 s")
    sp.add_argument("--mock-quiet", action="store_true", help="do not print mock robot request logs")
    sp.set_defaults(fn=cmd_serve)

    sp = sub.add_parser("mock", help="run a fake robot for local testing")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--udp", type=int, default=PORT_UDP_PLAIN, help="-1 to disable")
    sp.add_argument("--dtls", type=int, default=PORT_DTLS, help="-1 to disable")
    sp.add_argument("--tcp", type=int, default=PORT_TCP_PLAIN, help="-1 to disable")
    sp.add_argument("--tls", type=int, default=PORT_TLS, help="-1 to disable")
    sp.add_argument("--std", action="store_true", help="STD version (navigation -> E00A)")
    sp.add_argument("--sdk-unlocked", action="store_true")
    sp.add_argument("--faults", action="store_true", help="inject a fault every 15 s")
    sp.add_argument("--loss", type=float, default=0.0, help="drop probability for outgoing packets (0..1)")
    sp.add_argument("--quiet", action="store_true")
    sp.set_defaults(fn=cmd_mock)

    sp = sub.add_parser("list", help="list commands and reports from the docs")
    sp.set_defaults(fn=cmd_list)

    sp = sub.add_parser("send", help="send one command and print the reply")
    sp.add_argument("command_id", help="see `ezra-udp list`")
    sp.add_argument("--items", help="Items JSON (default: example from the docs)")
    sp.add_argument("--yes", action="store_true", help="confirm commands that move the robot")
    sp.add_argument("--wait-deferred", type=float, default=0.0, help="for nav_task: wait N s for the final result")
    _conn_args(sp)
    sp.set_defaults(fn=cmd_send)

    sp = sub.add_parser("listen", help="heartbeat + print status reports")
    sp.add_argument("-s", "--seconds", type=float, default=10.0)
    sp.add_argument("--all", action="store_true", help="print every report (default: 1/s per type)")
    sp.add_argument("--width", type=int, default=160)
    _conn_args(sp)
    sp.set_defaults(fn=cmd_listen)

    sp = sub.add_parser("suite", help="run the conformance checks")
    sp.add_argument("--checks", help="comma separated ids (default: all safe checks)")
    sp.add_argument("--allow-caution", action="store_true")
    sp.add_argument("--allow-motion", action="store_true")
    sp.add_argument("--json", help="write the report to this file")
    _conn_args(sp)
    sp.set_defaults(fn=cmd_suite)

    sp = sub.add_parser("probe", help="find which transport/port the robot answers on")
    sp.add_argument("--host", default=DEFAULT_ROBOT_HOST)
    sp.add_argument("--ports", help="e.g. dtls:30004,tls:30003,udp:30000 (default: the 6 usual combinations)")
    sp.add_argument("--timeout", type=float, default=2.5, help="connect/handshake timeout per candidate [s]")
    sp.add_argument("--verify", action="store_true")
    sp.add_argument("--ca")
    sp.add_argument("--cert")
    sp.add_argument("--key")
    sp.add_argument("--compat", action="store_true")
    sp.set_defaults(fn=cmd_probe)

    sp = sub.add_parser("decode", help="decode a hex APDU (args or stdin)")
    sp.add_argument("hex", nargs="*")
    sp.set_defaults(fn=cmd_decode)

    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # friendly one-liner instead of a traceback
        from .transport import TransportError

        if isinstance(exc, (TransportError, KeyError, ValueError)):
            print(f"✗ {exc}", file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
