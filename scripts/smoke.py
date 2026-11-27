#!/usr/bin/env python3
"""End-to-end smoke test: `ezra-udp serve --mock` driven over HTTP, the same way the GUI uses it.

    python scripts/smoke.py          # API + built-in mock robot, all four transports
    python scripts/smoke.py --gui    # also require the built GUI (web/out) to be served

Runs on a free port, so it does not clash with a GUI that is already open. Exit code 0 = everything passed.
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPORTS = ("basic", "motion", "device", "abnormal", "navigation")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Api:
    def __init__(self, base: str) -> None:
        self.base = base

    def __call__(self, path: str, body: dict | None = None, timeout: float = 20.0):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method="GET" if body is None else "POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw, ctype = r.read(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            raise AssertionError(f"{path}: HTTP {exc.code} {exc.read().decode(errors='replace')}") from None
        return json.loads(raw) if "json" in ctype else raw.decode("utf-8", "replace")


def check(cond: bool, what: str, detail: object = "") -> None:
    if not cond:
        raise AssertionError(f"{what}: {detail}")


def run(api: Api, need_gui: bool) -> None:
    health = api("/api/health")
    check(health.get("ok") is True, "health", health)
    mock = health.get("mock")
    check(bool(mock), "built-in mock robot did not start (ports busy?)", health)
    print(f"✓ backend {health['version']} up, mock robot on {mock}")

    if need_gui:
        html = api("/")
        check("<title>EZRA UDP Debugger</title>" in html, "GUI index.html not served", html[:160])
        print("✓ GUI served from web/out")

    cat = api("/api/catalog")
    check(len(cat["commands"]) >= 17 and len(cat["reports"]) == 5, "catalog", (len(cat["commands"]), len(cat["reports"])))
    print(f"✓ catalog: {len(cat['commands'])} commands, {len(cat['reports'])} reports")

    rep = api("/api/probe", {"host": "127.0.0.1", "timeout": 2.0,
                             "candidates": [{"transport": k, "port": p} for k, p in mock.items()]})
    oks = sorted(r["transport"] for r in rep["results"] if r["status"] == "ok")
    check(oks == ["dtls", "tcp", "tls", "udp"], "probe", rep["results"])
    check(rep["best"]["transport"] == "dtls", "probe best", rep["best"])
    print(f"✓ probe: {', '.join(oks)} ok, best {rep['best']['transport']}")

    for kind in ("dtls", "tls", "udp", "tcp"):
        snap = api("/api/session/connect", {"transport": kind, "host": "127.0.0.1", "port": mock[kind]})
        check(snap["state"] == "connected", f"{kind} connect", snap.get("error"))
        r = api("/api/send", {"command_id": "location_get"})
        check(r["status"] == "ok", f"{kind} location_get", r)
        r = api("/api/send", {"command_id": "nav_state", "fmt": "XML"})
        check(r["status"] == "ok", f"{kind} nav_state (XML)", r)
        if kind == "dtls":
            deadline = time.monotonic() + 6
            while time.monotonic() < deadline:
                got = api("/api/reports")
                if all(k in got for k in REPORTS):
                    break
                time.sleep(0.25)
            check(all(k in got for k in REPORTS), "status reports", sorted(got))
            sess = api("/api/session")
            hb = sess["stats"]["heartbeat"]
            check(hb["acked"] > 0 and not hb["link_lost"], "heartbeat", hb)
        api("/api/session/disconnect", {})
        print(f"✓ {kind.upper():4} connect, JSON + XML request/reply" + (", heartbeat ACK, 5 reports" if kind == "dtls" else ""))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gui", action="store_true", help="fail if the built GUI is not served")
    a = ap.parse_args()

    port = free_port()
    cmd = [sys.executable, "-m", "drds_udp.cli", "serve", "--mock", "--mock-quiet", "--port", str(port)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    api = Api(f"http://127.0.0.1:{port}")
    try:
        for _ in range(150):
            if proc.poll() is not None:
                break
            try:
                api("/api/health", timeout=1)
                break
            except (OSError, AssertionError):
                time.sleep(0.2)
        run(api, a.gui)
    except Exception as exc:  # noqa: BLE001 - report every failure the same way
        print(f"✗ {exc}", file=sys.stderr)
        proc.terminate()
        out = proc.communicate(timeout=10)[0]
        print("--- server output ---\n" + out, file=sys.stderr)
        return 1
    proc.terminate()
    proc.wait(timeout=10)
    print("smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
