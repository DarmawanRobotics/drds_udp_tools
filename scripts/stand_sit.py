#!/usr/bin/env python3
"""EZRA: heartbeat + stand + sit for the Deep Robotics Inspection Protocol V1.0.3, in one file.

Needs only standard Python 3.6+ (copy it to any host: robot, Linux PC, Mac). Mode dtls also needs pyOpenSSL
(pip install pyOpenSSL, or apt install python3-openssl).

  python3 stand_sit.py --host 10.21.33.103 --mode tls --cert client.crt --key client.key
  python3 stand_sit.py --host 10.21.33.103 --mode dtls --cert client.crt --key client.key
  python3 stand_sit.py --host 10.21.33.103 --mode udp --port 30000      # robot with encryption disabled
  python3 stand_sit.py ... --check                                      # heartbeat + reports only, no motion

Steps: connect -> heartbeat 2 Hz until ACK -> read MotionState from Basic Status -> confirm -> stand (MotionParam 1)
-> wait until MotionState 1 -> confirm -> sit (MotionParam 4) -> wait until MotionState 4.
"""

import argparse
import json
import random
import socket
import ssl
import struct
import sys
import threading
import time
from datetime import datetime

SYNC = b"\xeb\x91\xeb\x90"
HEARTBEAT = (0x00100064, 0x00000005)
MOTION_STATE = (0x00100001, 0x00200002)  # Items {"MotionParam": 1 stand | 4 sit | -2 soft emergency stop}
REPORT_COMMAND = 0x00F00000
REPORTS = {0x00100064: "basic", 0x00100001: "motion", 0x00100002: "device", 0x0010007F: "abnormal",
           0x00100003: "navigation"}
STATE_NAMES = {1: "Stand", 4: "Sit", -2: "Soft emergency stop"}
DEFAULT_PORTS = {"dtls": 30004, "tls": 30003, "udp": 30000, "tcp": 30001}


def stamp():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


_PRINT = threading.Lock()


def log(msg):
    with _PRINT:
        print(f"[{stamp()}] {msg}", flush=True)


def state_name(v):
    return f"{v} ({STATE_NAMES.get(v, '?')})"


def build_apdu(msg_id, typ, cmd, items):
    now = datetime.now()
    asdu = {"PatrolDevice": {"Type": typ, "Command": cmd,
                             "Time": now.strftime("%Y-%m-%d %H:%M:%S.") + f"{now.microsecond // 1000:03d}",
                             "Items": items}}
    body = json.dumps(asdu, separators=(",", ":")).encode()
    # sync | length | message id | format 0x01 = JSON | packet seq | protocol version 1 | 5 reserved bytes
    return SYNC + struct.pack("<HHBBB5x", len(body), msg_id, 0x01, 0, 1) + body


def split_frames(buf):
    """Pull complete APDUs out of `buf` (bytearray). Returns [(msg_id, fmt, seq, body)], keeps the tail."""
    out = []
    while True:
        i = buf.find(SYNC)
        if i < 0:
            del buf[:max(0, len(buf) - 3)]
            return out
        del buf[:i]
        if len(buf) < 16:
            return out
        length, msg_id, fmt, seq, _ver = struct.unpack_from("<HHBBB", buf, 4)
        if len(buf) < 16 + length:
            return out
        out.append((msg_id, fmt, seq, bytes(buf[16:16 + length])))
        del buf[:16 + length]


# ------------------------------------------------------------------ links (all calls guarded by one lock)
class Link:
    stream = False

    def send(self, data):
        raise NotImplementedError

    def poll(self):
        """Return a list of received chunks (datagrams, or stream bytes); [] after ~20 ms without data."""
        raise NotImplementedError

    def close(self):
        pass


class UdpLink(Link):
    def __init__(self, host, port):
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s.connect((host, port))
        self.s.settimeout(0.02)
        self.info = f"UDP {self.s.getsockname()[0]}:{self.s.getsockname()[1]} -> {host}:{port}"

    def send(self, data):
        self.s.send(data)

    def poll(self):
        try:
            return [self.s.recv(65535)]
        except socket.timeout:
            return []
        except ConnectionRefusedError:
            raise ConnectionError("ICMP port unreachable: nothing listens on this UDP port")

    def close(self):
        self.s.close()


class StreamLink(Link):
    stream = True

    def __init__(self, host, port, tls, a):
        raw = socket.create_connection((host, port), timeout=a.timeout)
        if tls:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            if a.ca:
                ctx.load_verify_locations(a.ca)
            else:
                ctx.verify_mode = ssl.CERT_NONE
            if a.cert:
                ctx.load_cert_chain(a.cert, a.key or None)
            raw = ctx.wrap_socket(raw, server_hostname=host)
        self.s = raw
        self.s.settimeout(0.02)
        name = f"TLS ({raw.version()}, {raw.cipher()[0]})" if tls else "TCP"
        self.info = f"{name} {self.s.getsockname()[0]}:{self.s.getsockname()[1]} -> {host}:{port}"

    def send(self, data):
        self.s.settimeout(None)
        try:
            self.s.sendall(data)
        finally:
            self.s.settimeout(0.02)

    def poll(self):
        try:
            data = self.s.recv(65536)
        except (socket.timeout, ssl.SSLWantReadError):
            return []
        if not data:
            raise ConnectionError("robot closed the connection")
        return [data]

    def close(self):
        self.s.close()


class DtlsLink(Link):
    def __init__(self, host, port, a):
        try:
            from OpenSSL import SSL
        except ImportError:
            raise SystemExit("mode dtls needs pyOpenSSL: pip install pyOpenSSL (or apt install python3-openssl), "
                             "or use --mode tls")
        self.SSL = SSL
        ctx = SSL.Context(SSL.DTLS_CLIENT_METHOD)
        ctx.set_options(SSL.OP_NO_QUERY_MTU)
        if a.ca:
            ctx.set_verify(SSL.VERIFY_PEER, lambda conn, cert, err, depth, ok: bool(ok))
            ctx.load_verify_locations(a.ca)
        else:
            ctx.set_verify(SSL.VERIFY_NONE, lambda *args: True)
        if a.cert:
            ctx.use_certificate_chain_file(a.cert)
            ctx.use_privatekey_file(a.key or a.cert)
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s.connect((host, port))
        self.s.settimeout(0.02)
        self.c = SSL.Connection(ctx, None)
        self.c.set_connect_state()
        try:
            self.c.set_ciphertext_mtu(1400)
        except Exception:
            pass
        deadline = time.monotonic() + a.timeout
        while True:
            try:
                self.c.do_handshake()
                self._flush()
                break
            except SSL.WantReadError:
                self._flush()
            except SSL.Error as exc:
                self._flush()
                raise ConnectionError(f"DTLS handshake failed: {exc}")
            if time.monotonic() > deadline:
                raise ConnectionError("DTLS handshake timeout: wrong IP/port, or encryption disabled on the robot")
            try:
                self.c.bio_write(self.s.recv(65535))
            except socket.timeout:
                try:
                    self.c.DTLSv1_handle_timeout()  # retransmit the last flight
                except Exception:
                    pass
            except ConnectionRefusedError:
                raise ConnectionError("ICMP port unreachable: nothing listens on this UDP port")
        self.info = (f"DTLS ({self.c.get_protocol_version_name()}, {self.c.get_cipher_name()}) "
                     f"{self.s.getsockname()[0]}:{self.s.getsockname()[1]} -> {host}:{port}")

    def _flush(self):
        while True:
            try:
                out = self.c.bio_read(65535)
            except self.SSL.WantReadError:
                return
            if not out:
                return
            self.s.send(out)

    def send(self, data):
        self.c.send(data)
        self._flush()

    def poll(self):
        try:
            self.c.bio_write(self.s.recv(65535))
        except socket.timeout:
            return []
        out = []
        while True:
            try:
                out.append(self.c.recv(65535))
            except self.SSL.WantReadError:
                break
            except self.SSL.ZeroReturnError:
                raise ConnectionError("robot closed the DTLS session")
            except self.SSL.Error as exc:
                raise ConnectionError(f"DTLS error: {exc}")
        self._flush()
        return out


# ------------------------------------------------------------------ client
class Robot:
    def __init__(self, link):
        self.link = link
        self.lock = threading.Lock()
        self.msg_id = random.randint(1, 60000)
        self.pending = {}  # msg_id -> [event, (typ, cmd), reply]
        self.parts = {}  # msg_id -> body bytes (multi-packet)
        self.hb_sent = self.hb_acked = 0
        self.first_ack = threading.Event()
        self.motion_state = None
        self.state_changed = threading.Condition()
        self.report_count = {}
        self.error = None
        self.alive = True
        self.buf = bytearray()
        threading.Thread(target=self._rx, daemon=True).start()
        threading.Thread(target=self._heartbeat, daemon=True).start()

    def _next_id(self):
        self.msg_id = self.msg_id % 65535 + 1
        return self.msg_id

    def _send(self, typ, cmd, items, track=True):
        with self.lock:
            mid = self._next_id()
            slot = None
            if track:
                slot = self.pending[mid] = [threading.Event(), (typ, cmd), None]
            self.link.send(build_apdu(mid, typ, cmd, items))
            sent_at = time.monotonic()
        return mid, slot, sent_at

    def request(self, typ, cmd, items, timeout=2.0):
        mid, slot, sent_at = self._send(typ, cmd, items)
        slot[0].wait(timeout)
        self.pending.pop(mid, None)
        return mid, slot[2], round((time.monotonic() - sent_at) * 1000, 1)

    def _heartbeat(self):
        while self.alive:
            try:
                self._send(*HEARTBEAT, {}, track=False)
                self.hb_sent += 1
            except OSError as exc:
                self.error = self.error or f"send failed: {exc}"
            time.sleep(0.5)

    def _rx(self):
        while self.alive:
            try:
                with self.lock:
                    chunks = self.link.poll()
            except (ConnectionError, OSError) as exc:
                self.error = str(exc)
                self.alive = False
                with self.state_changed:
                    self.state_changed.notify_all()
                return
            if not chunks:
                time.sleep(0.005)
                continue
            for chunk in chunks:
                if self.link.stream:
                    self.buf += chunk
                    frames = split_frames(self.buf)
                else:
                    frames = split_frames(bytearray(chunk))
                for frame in frames:
                    self._on_frame(*frame)

    def _on_frame(self, msg_id, fmt, seq, body):
        if fmt != 0x01:
            log(f"← #{msg_id} non-JSON reply (format {fmt}): {body[:120]!r}")
            return
        data = self.parts.pop(msg_id, b"") + body if seq else body
        try:
            pd = json.loads(data.decode("utf-8")).get("PatrolDevice", {})
        except ValueError:
            self.parts[msg_id] = data  # first part of a multi-packet message
            return
        typ, cmd, items = pd.get("Type"), pd.get("Command"), pd.get("Items") or {}
        if cmd == REPORT_COMMAND:
            name = REPORTS.get(typ, hex(typ or 0))
            self.report_count[name] = self.report_count.get(name, 0) + 1
            if name == "basic":
                state = (items.get("BasicStatus") or {}).get("MotionState")
                if state is not None and state != self.motion_state:
                    with self.state_changed:
                        old, self.motion_state = self.motion_state, state
                        self.state_changed.notify_all()
                    if old is not None:
                        log(f"← Basic Status: MotionState {state_name(old)} -> {state_name(state)}")
            return
        slot = self.pending.get(msg_id)
        if slot is None:  # robot did not echo our message id: match by Type/Command
            slot = next((s for s in list(self.pending.values()) if s[1] == (typ, cmd) and s[2] is None), None)
        if (typ, cmd) == HEARTBEAT:
            self.hb_acked += 1
            self.first_ack.set()
        if slot is not None:
            slot[2] = items
            slot[0].set()
        elif (typ, cmd) != HEARTBEAT:
            log(f"← #{msg_id} unexpected Type 0x{typ or 0:08X} Command 0x{cmd or 0:08X}: {items}")

    def wait_state(self, want, timeout):
        end = time.monotonic() + timeout
        with self.state_changed:
            while self.motion_state != want and self.alive:
                left = end - time.monotonic()
                if left <= 0:
                    return False
                self.state_changed.wait(left)
        return self.motion_state == want

    def close(self):
        self.alive = False
        time.sleep(0.15)
        with self.lock:
            self.link.close()


def confirm(question, yes):
    if yes:
        return True
    try:
        return input(f"? {question} [y/N] ").strip().lower() in ("y", "yes", "ya")
    except EOFError:
        return False


def describe(items):
    if items is None:
        return "no reply (timeout)"
    code, text = items.get("ErrorCode"), items.get("ErrorMessage", "")
    return f"ErrorCode {code}" + (f" {text}" if text else "")


def move(robot, param, label, a):
    if not confirm(f"Robot akan {label}. Area aman, remote + E-stop siap?", a.yes):
        log("dibatalkan")
        return False
    mid, items, ms = robot.request(*MOTION_STATE, {"MotionParam": param})
    log(f"→ #{mid} motion state MotionParam {param} ({STATE_NAMES[param]}) ← {describe(items)} ({ms} ms)")
    if items is None or items.get("ErrorCode") not in (0, None):
        return False
    t0 = time.monotonic()
    if robot.wait_state(param, a.wait):
        log(f"✓ MotionState {state_name(param)} after {time.monotonic() - t0:.1f} s")
        return True
    log(f"✗ MotionState still {state_name(robot.motion_state) if robot.motion_state is not None else '?'} "
        f"after {a.wait:.0f} s" + (f" ({robot.error})" if robot.error else ""))
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="10.21.33.103")
    ap.add_argument("--mode", choices=["tls", "dtls", "udp", "tcp"], default="tls")
    ap.add_argument("--port", type=int, help="default: tls 30003, dtls 30004, udp 30000, tcp 30001")
    ap.add_argument("--cert", help="client certificate (PEM) — the robot requires one on its encrypted ports")
    ap.add_argument("--key", help="client private key (PEM)")
    ap.add_argument("--ca", help="CA file to verify the robot's certificate (default: no verification)")
    ap.add_argument("--timeout", type=float, default=5.0, help="connect / handshake timeout [s]")
    ap.add_argument("--wait", type=float, default=10.0, help="max wait for MotionState to change [s]")
    ap.add_argument("--check", action="store_true", help="heartbeat + reports only, do not move the robot")
    ap.add_argument("-y", "--yes", action="store_true", help="do not ask before standing / sitting")
    a = ap.parse_args()
    port = a.port or DEFAULT_PORTS[a.mode]

    try:
        if a.mode == "udp":
            link = UdpLink(a.host, port)
        elif a.mode == "dtls":
            link = DtlsLink(a.host, port, a)
        else:
            link = StreamLink(a.host, port, a.mode == "tls", a)
    except (OSError, ConnectionError, ssl.SSLError) as exc:
        text = str(exc)
        log(f"✗ connect {a.mode.upper()} {a.host}:{port} failed: {text}")
        if "certificate" in text.lower() or "handshake failure" in text.lower():
            log("  → the robot wants a client certificate: --cert client.crt --key client.key")
        return 1
    log(f"connected: {link.info}")

    robot = Robot(link)
    try:
        if not robot.first_ack.wait(3.0):
            why = robot.error or "no heartbeat ACK in 3 s"
            log(f"✗ {why}")
            if "certificate" in why.lower() or (a.mode == "tls" and not a.cert and "closed" in why):
                log("  → the robot probably wants a client certificate: --cert client.crt --key client.key")
            return 1
        log(f"✓ heartbeat ACK (2 Hz, {robot.hb_acked}/{robot.hb_sent})")
        deadline = time.monotonic() + 3.0
        while robot.motion_state is None and time.monotonic() < deadline and robot.alive:
            time.sleep(0.05)
        if robot.motion_state is None:
            log("✗ no Basic Status report in 3 s (robot reports to the address that sends heartbeats)")
            return 1
        log(f"✓ Basic Status: MotionState {state_name(robot.motion_state)}")
        if a.check:
            time.sleep(3.0)
            log(f"reports in ~6 s: {robot.report_count}, heartbeat ACK {robot.hb_acked}/{robot.hb_sent}")
            return 0
        if not move(robot, 1, "BERDIRI (stand)", a):
            return 1
        if not move(robot, 4, "DUDUK (sit)", a):
            return 1
        log("✓ selesai: heartbeat, stand, sit")
        return 0
    except KeyboardInterrupt:
        log("stopped (Ctrl+C)")
        return 130
    finally:
        robot.close()


if __name__ == "__main__":
    sys.exit(main())
