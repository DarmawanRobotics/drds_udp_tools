"""Multi-packet (sub-packet) reassembly — §1.1.5 Packet Sequence Number.

The PDF cell describing the exact multi-packet rule is clipped, so this is
deliberately tolerant:
  * a frame whose body already decodes as a full PatrolDevice is emitted as-is;
  * otherwise frames are grouped by (src, msg_id, format) and re-joined in seq
    order (fallback: arrival order) until the result decodes;
  * groups that never complete are emitted as `complete=False` after a timeout
    so the debugger still shows what arrived.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..protocol.asdu import DecodedAsdu, decode_asdu
from ..protocol.header import MAX_FRAME_ASDU, ApduHeader, ParsedFrame


@dataclass
class Assembled:
    header: ApduHeader
    body: bytes
    raw: bytes
    decoded: DecodedAsdu
    fragments: list[dict]
    complete: bool
    src: tuple
    warnings: list[str] = field(default_factory=list)


@dataclass
class _Group:
    first_seen: float
    frames: list[tuple[ParsedFrame, bytes]] = field(default_factory=list)


class Reassembler:
    def __init__(self, timeout: float = 1.0, max_frame: int = MAX_FRAME_ASDU) -> None:
        self.timeout = timeout
        self.max_frame = max_frame
        self._groups: dict[tuple, _Group] = {}
        self.completed_multi = 0
        self.incomplete = 0

    def push(self, frame: ParsedFrame, raw: bytes, src: tuple, now: float) -> list[Assembled]:
        hdr = frame.header
        key = (src, hdr.msg_id, hdr.asdu_format)
        decoded = decode_asdu(frame.body, hdr.asdu_format)
        out: list[Assembled] = []
        if decoded.ok:
            if key in self._groups:  # stale fragments with the same id -> flush them first
                out.append(self._give_up(key))
            out.append(Assembled(hdr, frame.body, raw, decoded,
                                 [{"seq": hdr.seq, "length": len(frame.body)}], True, src, list(frame.warnings)))
            return out

        group = self._groups.get(key)
        looks_like_first_fragment = len(frame.body) >= self.max_frame
        if group is None and hdr.seq == 0 and not looks_like_first_fragment:
            # small standalone frame that just does not parse -> report now
            out.append(Assembled(hdr, frame.body, raw, decoded,
                                 [{"seq": hdr.seq, "length": len(frame.body)}], True, src, list(frame.warnings)))
            return out
        if group is None:
            group = self._groups[key] = _Group(now)
        group.frames.append((frame, raw))
        done = self._try_join(key, group)
        if done:
            out.append(done)
        return out

    def _try_join(self, key: tuple, group: _Group) -> Assembled | None:
        orders = [sorted(group.frames, key=lambda fr: fr[0].header.seq), list(group.frames)]
        for order in orders:
            body = b"".join(f.body for f, _ in order)
            first = order[0][0]
            decoded = decode_asdu(body, first.header.asdu_format)
            if decoded.ok:
                del self._groups[key]
                self.completed_multi += 1
                warns = [w for f, _ in order for w in f.warnings if "length field says" not in w]
                if order is orders[1] and order != orders[0]:
                    warns.append("fragments joined in arrival order (seq numbers not monotonic)")
                return Assembled(first.header, body, b"".join(r for _, r in order), decoded,
                                 [{"seq": f.header.seq, "length": len(f.body)} for f, _ in order], True,
                                 key[0], warns)
        if len(group.frames) >= 256:
            return self._give_up(key)
        return None

    def _give_up(self, key: tuple) -> Assembled:
        group = self._groups.pop(key)
        order = sorted(group.frames, key=lambda fr: fr[0].header.seq)
        body = b"".join(f.body for f, _ in order)
        first = order[0][0]
        decoded = decode_asdu(body, first.header.asdu_format)
        self.incomplete += 1
        warns = [f"incomplete multi-packet message: {len(order)} fragment(s), seq "
                 f"{[f.header.seq for f, _ in order]}"]
        return Assembled(first.header, body, b"".join(r for _, r in order), decoded,
                         [{"seq": f.header.seq, "length": len(f.body)} for f, _ in order], False, key[0], warns)

    def expire(self, now: float) -> list[Assembled]:
        stale = [k for k, g in self._groups.items() if now - g.first_seen > self.timeout]
        return [self._give_up(k) for k in stale]

    @property
    def pending_groups(self) -> int:
        return len(self._groups)
