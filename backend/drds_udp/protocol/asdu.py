"""ASDU codec — §1.1.6. JSON (recommended) and XML bodies.

    {"PatrolDevice": {"Type": int, "Command": int, "Time": "YYYY-MM-DD HH:MM:SS.mmm", "Items": {...}}}
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .header import AsduFormat

ROOT = "PatrolDevice"
XML_DECL = '<?xml version="1.0" encoding="UTF-8"?>'


def now_time_str(dt: datetime | None = None) -> str:
    dt = dt or datetime.now()
    return dt.strftime("%Y-%m-%d %H:%M:%S.") + f"{dt.microsecond // 1000:03d}"


def build_asdu(type_: int, command: int, items: dict | None = None, time_str: str | None = None) -> dict:
    return {
        ROOT: {
            "Type": int(type_),
            "Command": int(command),
            "Time": time_str or now_time_str(),
            "Items": items if items is not None else {},
        }
    }


# ----------------------------------------------------------------- encoding
def encode_asdu(asdu: dict, fmt: int = AsduFormat.JSON, pretty: bool = False) -> bytes:
    if int(fmt) == AsduFormat.XML:
        return dict_to_xml(asdu, pretty=pretty).encode("utf-8")
    if pretty:
        return json.dumps(asdu, ensure_ascii=False, indent=2).encode("utf-8")
    return json.dumps(asdu, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _xml_scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return ""
    if isinstance(v, float):
        return repr(v)
    return str(v)


def _xml_fill(parent: ET.Element, key: str, value: Any) -> None:
    if isinstance(value, list):
        # repeated elements, same tag (matches the PDF: <Led>..</Led><Led>..</Led>, <Color>1</Color>)
        for item in value:
            _xml_fill(parent, key, item)
        return
    el = ET.SubElement(parent, key)
    if isinstance(value, dict):
        for k, v in value.items():
            _xml_fill(el, k, v)
    else:
        el.text = _xml_scalar(value)


def dict_to_xml(asdu: dict, pretty: bool = False) -> str:
    if len(asdu) != 1:
        raise ValueError("ASDU dict must have exactly one root key")
    (root_key, payload), = asdu.items()
    root = ET.Element(root_key)
    for k, v in (payload or {}).items():
        _xml_fill(root, k, v)
    if pretty:
        ET.indent(root, space="    ")
    body = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    return XML_DECL + ("\n" if pretty else "") + body


# ----------------------------------------------------------------- decoding
_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")
_HEXSPACED_RE = re.compile(r"^0x[0-9a-fA-F]{1,4}(\s?[0-9a-fA-F]{4})?$")


def _xml_typed(text: str | None) -> Any:
    if text is None:
        return ""
    t = text.strip()
    if t == "":
        return ""
    low = t.lower()
    if low in ("true", "false"):
        return low == "true"
    if _INT_RE.match(t):
        return int(t)
    if _FLOAT_RE.match(t):
        return float(t)
    if _HEXSPACED_RE.match(t):  # "0x0010 0002" as printed in some XML samples
        return int(t[2:].replace(" ", ""), 16)
    return t


def _xml_to_obj(el: ET.Element) -> Any:
    children = list(el)
    if not children:
        return _xml_typed(el.text)
    counts = Counter(ch.tag for ch in children)
    out: dict[str, Any] = {}
    for ch in children:
        val = _xml_to_obj(ch)
        if counts[ch.tag] > 1:  # repeated tag -> list (<Led/><Led/>, <Joint/>x16, ...)
            out.setdefault(ch.tag, []).append(val)
        else:
            out[ch.tag] = val
    return out


def xml_to_dict(text: str) -> dict:
    root = ET.fromstring(text)
    val = _xml_to_obj(root)
    if val == "":
        val = {}
    if isinstance(val, dict) and "Items" in val and val["Items"] == "":
        val["Items"] = {}
    return {root.tag: val}


@dataclass
class DecodedAsdu:
    ok: bool
    fmt: str  # "JSON" | "XML" | "?"
    text: str
    data: dict | None = None
    error: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def payload(self) -> dict:
        if not self.data:
            return {}
        return self.data.get(ROOT) or {}

    @property
    def type(self) -> int | None:
        return _as_int(self.payload.get("Type"))

    @property
    def command(self) -> int | None:
        return _as_int(self.payload.get("Command"))

    @property
    def time(self) -> str | None:
        t = self.payload.get("Time")
        return None if t is None else str(t)

    @property
    def items(self) -> Any:
        return self.payload.get("Items")

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "fmt": self.fmt,
            "text": self.text,
            "data": self.data,
            "error": self.error,
            "warnings": self.warnings,
            "type": self.type,
            "command": self.command,
        }


def _as_int(v: Any) -> int | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    s = str(v).strip()
    try:
        if s.lower().startswith("0x"):
            return int(s[2:].replace(" ", ""), 16)
        return int(float(s))
    except ValueError:
        return None


def sniff_format(body: bytes) -> str:
    s = body.lstrip(b"\x00 \t\r\n\xef\xbb\xbf")
    if s.startswith(b"{") or s.startswith(b"["):
        return "JSON"
    if s.startswith(b"<"):
        return "XML"
    return "?"


def decode_asdu(body: bytes, header_fmt: int | None = None) -> DecodedAsdu:
    """Decode an ASDU. Format comes from the header but is double-checked by
    sniffing — a mismatch is reported as a warning, not an error."""
    text = body.rstrip(b"\x00").decode("utf-8", errors="replace")
    sniffed = sniff_format(body)
    declared = {0: "XML", 1: "JSON"}.get(header_fmt) if header_fmt is not None else None
    warnings: list[str] = []
    fmt = declared or sniffed
    if declared and sniffed != "?" and declared != sniffed:
        warnings.append(f"header says {declared} but body looks like {sniffed}")
        fmt = sniffed
    if fmt == "?":
        return DecodedAsdu(False, "?", text, error="body is neither JSON nor XML", warnings=warnings)
    try:
        if fmt == "JSON":
            data = json.loads(text.strip().lstrip("﻿"))
        else:
            data = xml_to_dict(text.strip().lstrip("﻿"))
    except (json.JSONDecodeError, ET.ParseError) as exc:
        return DecodedAsdu(False, fmt, text, error=f"{fmt} parse error: {exc}", warnings=warnings)
    if not isinstance(data, dict) or ROOT not in data:
        return DecodedAsdu(False, fmt, text, data=data if isinstance(data, dict) else None,
                           error=f"missing root '{ROOT}'", warnings=warnings)
    payload = data.get(ROOT)
    if isinstance(payload, dict):
        for f in ("Type", "Command", "Items"):
            if f not in payload:
                warnings.append(f"missing field '{f}'")
    return DecodedAsdu(True, fmt, text, data=data, warnings=warnings)


def is_complete_asdu(body: bytes, header_fmt: int | None = None) -> bool:
    """True if `body` alone is a full PatrolDevice document (used by reassembly)."""
    d = decode_asdu(body, header_fmt)
    return d.ok
