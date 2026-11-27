# Protocol notes — Inspection Communication Protocol V1.0.3-0

What `drds_udp_tools` implements, and every place where the PDF (last updated 2026-11-21) was
ambiguous or clipped and we had to choose. Search for **Assumption** to find them.

## Transport

| Mode | Robot endpoint | Status |
|---|---|---|
| DTLS (UDP + encrypted) | `10.21.33.103:30004` | robot default |
| TLS (TCP + encrypted) | `10.21.33.103:30003` | robot default |
| UDP plain | `10.21.33.103:30000` | **Assumption** — only after encryption is disabled in the `robotserver` config |
| TCP plain | `10.21.33.103:30001` | **Assumption** — same |

- The robot is the server; the host computer is the client.
- DTLS is implemented with pyOpenSSL memory BIOs over an asyncio UDP socket (`DTLS_CLIENT_METHOD`,
  cookie exchange and retransmission timers handled by OpenSSL). Certificate verification is **off** by
  default because robot certificates are typically self-signed; a CA, client cert/key (mutual TLS),
  SNI, cipher list and DTLS MTU are configurable.
- One socket is used for everything, so heartbeats, commands and the robot's pushed reports share the
  same local `IP:port` — the robot reports to whoever sends heartbeats (§1.2.1).
- UDP sockets are *connected* by default so an ICMP "port unreachable" shows up as an error
  (useful when the plain port is closed). Turn it off to accept replies from another source port.

## APDU header (§1.1.5) — 16 bytes, little endian

| Offset | Size | Field | Value |
|---|---|---|---|
| 0 | 4 | sync | `EB 91 EB 90` |
| 4 | 2 | length | ASDU bytes |
| 6 | 2 | message id | 0 → 65535, then wraps; reply echoes it |
| 8 | 1 | ASDU format | `0x00` XML, `0x01` JSON (**Assumption**: the JSON value is clipped in the PDF) |
| 9 | 1 | packet sequence | 0 → 255 |
| 10 | 1 | protocol version | 1 |
| 11 | 5 | reserved | zero |

**Multi-packet (Assumption).** A single frame carries at most 1000 ASDU bytes; the sentence describing
how larger payloads are split is clipped. The engine therefore:

1. accepts a frame as-is when its body already decodes to a full `PatrolDevice` document;
2. otherwise groups frames by (source, message id, format) and joins them in `seq` order (falling back to
   arrival order) until the result decodes;
3. reports a group that never completes after 1 s as *incomplete*, with all bytes kept for inspection;
4. tolerates a `length` field larger than the datagram (in case it carries the total length).

Outgoing ASDUs above 1000 bytes are split into sub-packets with the same message id and `seq` 0..n.
The mock robot sends Device State (~1.8 KB) as 2 sub-packets so this path is always exercised.

## ASDU (§1.1.6)

```json
{"PatrolDevice": {"Type": 1048676, "Command": 5, "Time": "2026-01-01 00:00:00.000", "Items": {}}}
```

- `Time` is local time `YYYY-MM-DD HH:MM:SS.mmm`.
- XML: lists become repeated elements (`<Led>…</Led><Led>…</Led>`, `<Color>1</Color>`), booleans are
  `true`/`false`, empty Items is `<Items/>`. On decode, a tag that repeats becomes a list; the
  `0x0010 0002` notation seen in one XML sample is parsed as hex.
- The format byte and the body are cross-checked; a mismatch is a warning, not an error.

## Requests

| § | Message | Type | Command | Reply |
|---|---|---|---|---|
| 1.2.1 | Heartbeat | `0x0010 0064` | `0x0000 0005` | status |
| 1.2.2 | Usage mode | `0x0010 0002` | `0x0050 0002` | status |
| 1.2.3 | Motion state | `0x0010 0001` | `0x0020 0002` | status |
| 1.2.4 | Gait | `0x0010 0001` | `0x0030 0002` | status |
| 1.2.5 | Axis command | `0x0010 0001` | `0x0010 0002` | **none** |
| 1.2.6 | Velocity command | `0x0010 0001` | `0x0011 0002` | **none** |
| 1.2.7 | Velocity + position | `0x0010 0001` | `0x0012 0002` | status |
| 1.2.8 | Light effects | `0x0010 0005` | `0x0020 0002` | status |
| 1.2.9 | Autonomous charging | `0x0010 0004` | `0x0010 0002` | status |
| 1.2.10 | Locomotion SDK mode | `0x0010 0005` | `0x0030 0002` | status |
| 1.2.11 | Sleep settings | `0x0010 0002` | `0x0040 0002` | status |
| 1.4.1 | Location init / reset | `0x0010 0003` | `0x0020 0002` | status |
| 1.4.2 | Get location | `0x0010 0003` | `0x0020 0001` | data |
| 1.4.3 | Navigation (perception) status | `0x0010 0003` | `0x0011 0001` | data |
| 1.4.4 | Issue navigation task | `0x0010 0003` | `0x0010 0002` | status now + result when finished |
| 1.4.5 | Cancel navigation | `0x0010 0003` | `0x0010 0004` | data (`ErrorCode` 0/1) |
| 1.4.6 | Query navigation task state | `0x0010 0003` | `0x0010 0001` | data |

**Reply matching.** A reply is matched by message id and Type/Command. If the id matches but
Type/Command differ, or only Type/Command match, it is still attached with a warning — that is exactly
the kind of thing a debugger should surface. A request keeps listening for further replies (15 s, or
30 min for navigation tasks), so the deferred navigation result lands on the same request.

**Assumption — data commands.** §1.5 says every request gets a general call-status reply, while §1.4.x
show data replies. The engine accepts either or both; the mock answers data commands with the data
reply only, and navigation tasks with a status reply plus the deferred result.

## Status reports (§1.3) — all use Command `0x00F0 0000`

| § | Report | Type | Rate |
|---|---|---|---|
| 1.3.1.1 | Basic status | `0x0010 0064` | 2 Hz |
| 1.3.1.2 | Motion control status | `0x0010 0001` | 10 Hz |
| 1.3.1.3 | Device state | `0x0010 0002` | 2 Hz |
| 1.3.1.4 | Abnormal status | `0x0010 007F` | 2 Hz + on change |
| 1.3.1.5 | Navigation status | `0x0010 0003` | 1 Hz |

Reports stop 2 s after the last heartbeat; the debugger sends heartbeats at 2 Hz by default.

## Enumerations that were clipped (Assumptions)

| Field | What the PDF shows | What we use |
|---|---|---|
| `BasicStatus.Charge` | names only: idle, goToPile, charging, exitPile, error, onPiling, line_charging | 0 … 6 in that order |
| `NavStatus.Status` / nav reply `Status` | "Entering charging dock = …" value cut | 5 |
| `ObsState` | "In obstacle avoidance …" value cut | 1 |
| `Charge` request | Stop / Start values cut, Clear = 2 confirmed by a note | 0 = stop, 1 = start, 2 = clear |
| Navigation success code | both `0x0000` (normal) and `0x2300` (completed) listed | both treated as success |
| Abnormal example codes | sample uses 32783 / 32789, table lists 0x8014 / 0x8017 for the same names | table is used for labels, the `Name` field is always shown |

## Error codes

- General (§1.5): `0` success, `0xE001` … `0xE00B`.
- Navigation (Appendix 1): `0x2300` completed, `0x2302` cancelled, `0xA3xx` / `0xA4xx` module errors.
- Faults (§1.3.1.4 / §2.5): `0x80xx` joints/drivers, `0x81xx` battery, `0x82xx` IMU, `0x83xx` compute,
  `0x94xx` charging dock.

All three tables live in `backend/drds_udp/protocol/codes.py` and drive the labels in the GUI.

## Not covered by the PDF

- Figures (request/response sequence, motion-state transition diagram, axis directions) did not render
  in V1.0.3 — they are image placeholders in the file.
- No authentication beyond DTLS/TLS is described.
