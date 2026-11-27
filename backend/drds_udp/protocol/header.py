"""APDU header codec — Inspection Communication Protocol §1.1.5.

Layout (16 bytes, little endian):

    off  size  field
    0    4     sync            EB 91 EB 90 (fixed)
    4    2     length          ASDU byte length (LE)
    6    2     message id      request/response pairing, 0..65535 wrap (LE)
    8    1     asdu format     0x00 = XML, 0x01 = JSON
    9    1     packet seq      0..255, used for multi-packet (sub-packet) transfer
    10   1     version         fixed 1
    11   5     reserved        zero
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Iterator

SYNC = bytes((0xEB, 0x91, 0xEB, 0x90))
HEADER_SIZE = 16
MAX_FRAME_ASDU = 1000  # max ASDU bytes in a single frame (§1.1.5)
PROTOCOL_VERSION = 1
MSG_ID_MAX = 0xFFFF

_STRUCT = struct.Struct("<4sHHBBB5s")
assert _STRUCT.size == HEADER_SIZE


class AsduFormat(IntEnum):
    XML = 0x00
    JSON = 0x01

    @classmethod
    def parse(cls, value: "str | int | AsduFormat") -> "AsduFormat":
        if isinstance(value, AsduFormat):
            return value
        if isinstance(value, int):
            return cls(value)
        return cls[str(value).strip().upper()]


class HeaderError(ValueError):
    """Raised when a buffer cannot be parsed as an APDU header."""


@dataclass
class ApduHeader:
    length: int
    msg_id: int
    asdu_format: int = AsduFormat.JSON
    seq: int = 0
    version: int = PROTOCOL_VERSION
    reserved: bytes = field(default=b"\x00" * 5)
    sync: bytes = field(default=SYNC)

    def pack(self) -> bytes:
        if len(self.sync) != 4:
            raise HeaderError("sync must be exactly 4 bytes")
        if len(self.reserved) != 5:
            raise HeaderError("reserved must be exactly 5 bytes")
        return _STRUCT.pack(
            self.sync,
            self.length & 0xFFFF,
            self.msg_id & 0xFFFF,
            self.asdu_format & 0xFF,
            self.seq & 0xFF,
            self.version & 0xFF,
            self.reserved,
        )

    @classmethod
    def unpack(cls, data: bytes, *, strict_sync: bool = True) -> "ApduHeader":
        if len(data) < HEADER_SIZE:
            raise HeaderError(f"need {HEADER_SIZE} bytes for header, got {len(data)}")
        sync, length, msg_id, fmt, seq, version, reserved = _STRUCT.unpack_from(data, 0)
        if strict_sync and sync != SYNC:
            raise HeaderError(f"bad sync {sync.hex(' ')} (expected {SYNC.hex(' ')})")
        return cls(length, msg_id, fmt, seq, version, reserved, sync)

    def warnings(self) -> list[str]:
        """Spec deviations worth flagging in a debugger (not fatal)."""
        out: list[str] = []
        if self.sync != SYNC:
            out.append(f"sync {self.sync.hex(' ')} != {SYNC.hex(' ')}")
        if self.asdu_format not in (AsduFormat.XML, AsduFormat.JSON):
            out.append(f"unknown ASDU format 0x{self.asdu_format:02X}")
        if self.version != PROTOCOL_VERSION:
            out.append(f"protocol version {self.version} != {PROTOCOL_VERSION}")
        if self.reserved != b"\x00" * 5:
            out.append(f"reserved bytes not zero: {self.reserved.hex(' ')}")
        if self.length > MAX_FRAME_ASDU:
            out.append(f"ASDU length {self.length} > {MAX_FRAME_ASDU} single-frame limit")
        return out

    def to_dict(self) -> dict:
        fmt_name = {0: "XML", 1: "JSON"}.get(self.asdu_format, f"0x{self.asdu_format:02X}")
        return {
            "sync": self.sync.hex(" ").upper(),
            "length": self.length,
            "msg_id": self.msg_id,
            "asdu_format": self.asdu_format,
            "asdu_format_name": fmt_name,
            "seq": self.seq,
            "version": self.version,
            "reserved": self.reserved.hex(" ").upper(),
        }


@dataclass
class HeaderOverrides:
    """Debug knobs to deliberately craft off-spec headers."""

    msg_id: int | None = None
    asdu_format: int | None = None
    seq: int | None = None
    version: int | None = None
    reserved_hex: str | None = None
    sync_hex: str | None = None
    length: int | None = None  # force a (wrong) length value


def build_apdu(
    body: bytes,
    msg_id: int,
    asdu_format: int = AsduFormat.JSON,
    seq: int = 0,
    overrides: HeaderOverrides | None = None,
) -> bytes:
    hdr = ApduHeader(length=len(body), msg_id=msg_id, asdu_format=asdu_format, seq=seq)
    if overrides:
        if overrides.msg_id is not None:
            hdr.msg_id = overrides.msg_id
        if overrides.asdu_format is not None:
            hdr.asdu_format = overrides.asdu_format
        if overrides.seq is not None:
            hdr.seq = overrides.seq
        if overrides.version is not None:
            hdr.version = overrides.version
        if overrides.reserved_hex:
            hdr.reserved = _hex_bytes(overrides.reserved_hex, 5, "reserved")
        if overrides.sync_hex:
            hdr.sync = _hex_bytes(overrides.sync_hex, 4, "sync")
        if overrides.length is not None:
            hdr.length = overrides.length
    return hdr.pack() + body


def split_apdus(
    body: bytes,
    msg_id: int,
    asdu_format: int = AsduFormat.JSON,
    max_asdu: int = MAX_FRAME_ASDU,
) -> list[bytes]:
    """Split a large ASDU into sub-packets (same msg id, seq 0..n)."""
    if len(body) <= max_asdu:
        return [build_apdu(body, msg_id, asdu_format, 0)]
    chunks = [body[i : i + max_asdu] for i in range(0, len(body), max_asdu)]
    if len(chunks) > 256:
        raise HeaderError("ASDU too large: more than 256 sub-packets")
    return [build_apdu(c, msg_id, asdu_format, seq) for seq, c in enumerate(chunks)]


@dataclass
class ParsedFrame:
    header: ApduHeader
    body: bytes
    warnings: list[str]
    offset: int  # where this frame started in the source buffer


def parse_datagram(buf: bytes) -> tuple[list[ParsedFrame], list[str]]:
    """Parse every APDU in a complete buffer (e.g. one UDP datagram).

    Returns (frames, errors). Never raises: junk is skipped up to the next
    sync and reported in `errors`. Lenient on purpose: if `length` claims
    more bytes than the buffer has, the frame is returned with what is
    available plus a warning (some stacks put the *total* multi-packet
    length there).
    """
    frames: list[ParsedFrame] = []
    errors: list[str] = []
    pos = 0
    n = len(buf)
    while pos < n:
        idx = buf.find(SYNC, pos)
        if idx < 0:
            errors.append(f"no sync in {n - pos} trailing byte(s) at offset {pos}")
            break
        if idx > pos:
            errors.append(f"skipped {idx - pos} junk byte(s) before sync at offset {pos}")
        if n - idx < HEADER_SIZE:
            errors.append(f"truncated header: only {n - idx} byte(s) after sync")
            break
        hdr = ApduHeader.unpack(buf[idx:])
        start = idx + HEADER_SIZE
        avail = n - start
        warns = hdr.warnings()
        take = hdr.length
        if hdr.length > avail:
            warns.append(
                f"length field says {hdr.length} B but only {avail} B in datagram "
                "(truncated, or total length of a multi-packet message)"
            )
            take = avail
        frames.append(ParsedFrame(hdr, buf[start : start + take], warns, idx))
        pos = start + take
    return frames, errors


def iter_frames(buf: bytes) -> Iterator[ParsedFrame]:
    frames, _ = parse_datagram(buf)
    yield from frames


class StreamFramer:
    """Incremental APDU framer for TCP/TLS byte streams (with resync)."""

    def __init__(self, max_length: int = 1 << 20) -> None:
        self._buf = bytearray()
        self.max_length = max_length
        self.junk_bytes = 0

    def feed(self, data: bytes) -> list[ParsedFrame]:
        self._buf += data
        out: list[ParsedFrame] = []
        while True:
            idx = self._buf.find(SYNC)
            if idx < 0:
                # keep the last 3 bytes in case a sync is split across reads
                keep = min(len(self._buf), 3)
                self.junk_bytes += len(self._buf) - keep
                del self._buf[: len(self._buf) - keep]
                break
            if idx > 0:
                self.junk_bytes += idx
                del self._buf[:idx]
            if len(self._buf) < HEADER_SIZE:
                break
            hdr = ApduHeader.unpack(bytes(self._buf[:HEADER_SIZE]))
            if hdr.length > self.max_length:
                # insane length -> drop the sync and resync further on
                self.junk_bytes += 4
                del self._buf[:4]
                continue
            total = HEADER_SIZE + hdr.length
            if len(self._buf) < total:
                break
            body = bytes(self._buf[HEADER_SIZE:total])
            del self._buf[:total]
            out.append(ParsedFrame(hdr, body, hdr.warnings(), 0))
        return out


def hexdump(data: bytes, width: int = 16) -> str:
    lines = []
    for off in range(0, len(data), width):
        chunk = data[off : off + width]
        hx = " ".join(f"{b:02X}" for b in chunk)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{off:08X}  {hx:<{width * 3}} {asc}")
    return "\n".join(lines)


_HEX = set("0123456789abcdef")


def parse_hex(text: str) -> bytes:
    """Accept '0xEB 0x91', 'eb91eb90', 'EB:91' and Wireshark/xxd style dumps
    ("0000  eb 91 eb 90 ...  ....") — offset + ASCII columns are dropped."""
    out: list[str] = []
    for line in text.splitlines():
        tokens = line.replace(",", " ").replace(":", " ").split()
        if not tokens:
            continue
        first = tokens[0].lower().rstrip(":")
        # offset column must match the running byte count (0000, 0010, ...)
        is_offset = (
            len(first) >= 4
            and set(first) <= _HEX
            and len(tokens) > 1
            and int(first, 16) == len("".join(out)) // 2
            and len(tokens[1]) == 2
            and set(tokens[1].lower()) <= _HEX
        )
        if is_offset:
            for t in tokens[1:]:
                tl = t.lower()
                if len(tl) == 2 and set(tl) <= _HEX:
                    out.append(tl)
                else:
                    break  # ASCII column starts
            continue
        for t in tokens:
            tl = t.lower()
            if tl.startswith("0x"):
                tl = tl[2:]
            out.append("".join(c for c in tl if c in _HEX))
    joined = "".join(out)
    if len(joined) % 2:
        raise ValueError("odd number of hex digits")
    return bytes.fromhex(joined)


def _hex_bytes(text: str, size: int, label: str) -> bytes:
    raw = parse_hex(text)
    if len(raw) != size:
        raise HeaderError(f"{label} must be {size} bytes, got {len(raw)}")
    return raw
