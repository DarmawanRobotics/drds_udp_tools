import type { Catalog, CodeInfo, Enums, FieldDef, PatrolDoc } from "./types";

export const SYNC = [0xeb, 0x91, 0xeb, 0x90];
export const HEADER_SIZE = 16;

export function hex32(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  const u = v >>> 0;
  return `0x${(u >>> 16).toString(16).toUpperCase().padStart(4, "0")} ${(u & 0xffff)
    .toString(16)
    .toUpperCase()
    .padStart(4, "0")}`;
}

export function hex16(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `0x${(v >>> 0).toString(16).toUpperCase().padStart(4, "0")}`;
}

export function hexToBytes(hex: string): Uint8Array {
  const clean = hex.replace(/[^0-9a-f]/gi, "");
  const out = new Uint8Array(clean.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(clean.slice(i * 2, i * 2 + 2), 16);
  return out;
}

export function bytesToHex(b: Uint8Array, sep = " "): string {
  return Array.from(b, (x) => x.toString(16).toUpperCase().padStart(2, "0")).join(sep);
}

export function fmtTime(ts: number): string {
  const d = new Date(ts * 1000);
  const p = (n: number, w = 2) => String(n).padStart(w, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`;
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

export function fmtNum(v: unknown, digits = 2): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  return v.toFixed(digits);
}

export function items(doc: PatrolDoc | null | undefined): unknown {
  return doc?.PatrolDevice?.Items;
}

// ------------------------------------------------------------- code labels
export function codeLabel(enums: Enums | undefined, code: number | null | undefined): CodeInfo | null {
  if (!enums || code === null || code === undefined) return null;
  const k = String(code);
  return enums.general_errors[k] ?? enums.nav_errors[k] ?? null;
}

export function faultLabel(enums: Enums | undefined, code: unknown): CodeInfo | null {
  if (!enums || typeof code !== "number") return null;
  return enums.fault_codes[String(code)] ?? null;
}

export function enumLabel(enums: Enums | undefined, table: string, value: unknown): string | null {
  if (!enums || value === null || value === undefined) return null;
  const t = enums[table] as Record<string, string> | undefined;
  if (!t || Array.isArray(t)) return null;
  const hit = t[String(typeof value === "boolean" ? Number(value) : value)];
  return typeof hit === "string" ? hit : null;
}

/** Field-name aware annotation for JSON viewers (path = keys from Items down). */
export function annotate(enums: Enums | undefined, key: string, value: unknown, parent: string): string | null {
  if (!enums) return null;
  switch (key) {
    case "ErrorCode": {
      const c = codeLabel(enums, value as number);
      return c ? `${c.hex} ${c.label}` : typeof value === "number" && value !== 0 ? hex16(value) : null;
    }
    case "Code":
      return faultLabel(enums, value)?.label ?? (typeof value === "number" ? hex16(value) : null);
    case "MotionState":
    case "MotionParam":
    case "state":
      return enumLabel(enums, "motion_state", value);
    case "Gait":
    case "GaitParam":
      return enumLabel(enums, "gait", value) ?? (typeof value === "number" && value ? hex16(value) : null);
    case "HES":
      return enumLabel(enums, "hes", value);
    case "ControlUsageMode":
    case "Mode":
      return enumLabel(enums, "usage_mode", value);
    case "Sleep":
      return typeof value === "number" ? enumLabel(enums, "sleep_state", value) : null;
    case "Charge":
      return parent === "BasicStatus" ? enumLabel(enums, "charge_state", value) : enumLabel(enums, "charge_request", value);
    case "Location":
      return enumLabel(enums, "location", value);
    case "Relocation":
      return enumLabel(enums, "relocation", value);
    case "ObsState":
      return enumLabel(enums, "obs_state", value);
    case "Status":
      return enumLabel(enums, "nav_status", value);
    case "Lidar":
      return enumLabel(enums, "lidar_enable", value);
    case "Video":
      return enumLabel(enums, "video_enable", value);
    case "PointInfo":
      return enumLabel(enums, "point_info", value);
    case "Manner":
      return enumLabel(enums, "nav_manner", value);
    case "ObsMode":
      return enumLabel(enums, "obs_mode", value);
    case "NavMode":
      return enumLabel(enums, "nav_mode", value);
    case "Type":
      if (parent === "Led") return enumLabel(enums, "light_mode", value);
      if (parent === "ErrorList") return enumLabel(enums, "fault_event_type", value);
      return null;
    case "Color":
      return enumLabel(enums, "light_color", value);
    case "Severities":
      return enumLabel(enums, "severity", value);
    default:
      return null;
  }
}

// ------------------------------------------------------------ form values
export function defaultFor(f: FieldDef): unknown {
  switch (f.kind) {
    case "object": {
      const o: Record<string, unknown> = {};
      for (const sub of f.fields ?? []) o[sub.name] = defaultFor(sub);
      return o;
    }
    case "array": {
      if (f.default !== undefined) return structuredClone(f.default);
      const n = Math.max(f.min_items ?? 1, f.item_labels?.length ?? 0, 1);
      if (f.fields) {
        return Array.from({ length: n }, () => defaultFor({ name: "", kind: "object", fields: f.fields }));
      }
      return [];
    }
    default:
      return f.default ?? (f.kind === "bool" ? false : f.kind === "string" ? "" : 0);
  }
}

// --------------------------------------------------------- APDU preview
export function nowTimeStr(d = new Date()): string {
  const p = (n: number, w = 2) => String(n).padStart(w, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(
    d.getSeconds(),
  )}.${p(d.getMilliseconds(), 3)}`;
}

function xmlEscape(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function xmlFill(key: string, v: unknown, out: string[], indent: string, pretty: boolean): void {
  const nl = pretty ? "\n" : "";
  if (Array.isArray(v)) {
    for (const it of v) xmlFill(key, it, out, indent, pretty);
    return;
  }
  if (v && typeof v === "object") {
    const entries = Object.entries(v as Record<string, unknown>);
    if (!entries.length) {
      out.push(`${indent}<${key}/>${nl}`);
      return;
    }
    out.push(`${indent}<${key}>${nl}`);
    for (const [k, sub] of entries) xmlFill(k, sub, out, pretty ? indent + "    " : "", pretty);
    out.push(`${indent}</${key}>${nl}`);
    return;
  }
  const text = typeof v === "boolean" ? (v ? "true" : "false") : v === null || v === undefined ? "" : String(v);
  out.push(`${indent}<${key}>${xmlEscape(text)}</${key}>${nl}`);
}

export function toXml(doc: PatrolDoc, pretty = false): string {
  const pd = doc.PatrolDevice ?? {};
  const out: string[] = [];
  xmlFill("PatrolDevice", pd, out, "", pretty);
  return `<?xml version="1.0" encoding="UTF-8"?>${pretty ? "\n" : ""}${out.join("")}`.trimEnd();
}

export function buildDoc(type: number, command: number, its: unknown, time = nowTimeStr()): PatrolDoc {
  return { PatrolDevice: { Type: type, Command: command, Time: time, Items: its ?? {} } };
}

export function encodeBody(doc: PatrolDoc, fmt: "JSON" | "XML", pretty = false): string {
  return fmt === "XML" ? toXml(doc, pretty) : JSON.stringify(doc, null, pretty ? 2 : undefined);
}

export function buildHeader(opts: {
  length: number;
  msgId: number;
  fmt: number;
  seq?: number;
  version?: number;
  reserved?: number[];
  sync?: number[];
}): Uint8Array {
  const h = new Uint8Array(HEADER_SIZE);
  (opts.sync ?? SYNC).forEach((b, i) => (h[i] = b));
  h[4] = opts.length & 0xff;
  h[5] = (opts.length >> 8) & 0xff;
  h[6] = opts.msgId & 0xff;
  h[7] = (opts.msgId >> 8) & 0xff;
  h[8] = opts.fmt & 0xff;
  h[9] = (opts.seq ?? 0) & 0xff;
  h[10] = (opts.version ?? 1) & 0xff;
  (opts.reserved ?? [0, 0, 0, 0, 0]).forEach((b, i) => (h[11 + i] = b));
  return h;
}

export function utf8(s: string): Uint8Array {
  return new TextEncoder().encode(s);
}

/** Split concatenated APDUs (for colouring multi-packet hex). */
export function segmentApdus(b: Uint8Array): { start: number; bodyStart: number; end: number }[] {
  const segs: { start: number; bodyStart: number; end: number }[] = [];
  let pos = 0;
  while (pos + HEADER_SIZE <= b.length) {
    if (!(b[pos] === 0xeb && b[pos + 1] === 0x91 && b[pos + 2] === 0xeb && b[pos + 3] === 0x90)) break;
    const len = b[pos + 4] | (b[pos + 5] << 8);
    const end = Math.min(b.length, pos + HEADER_SIZE + len);
    segs.push({ start: pos, bodyStart: pos + HEADER_SIZE, end });
    pos = end;
  }
  return segs;
}

export type ByteRole = "sync" | "len" | "id" | "fmt" | "seq" | "ver" | "res" | "body";

export function headerRole(offset: number): ByteRole {
  if (offset < 4) return "sync";
  if (offset < 6) return "len";
  if (offset < 8) return "id";
  if (offset === 8) return "fmt";
  if (offset === 9) return "seq";
  if (offset === 10) return "ver";
  if (offset < 16) return "res";
  return "body";
}

export const ROLE_COLOR: Record<ByteRole, string> = {
  sync: "var(--b-sync)",
  len: "var(--b-len)",
  id: "var(--b-id)",
  fmt: "var(--b-fmt)",
  seq: "var(--b-seq)",
  ver: "var(--b-ver)",
  res: "var(--b-res)",
  body: "transparent",
};

export const ROLE_LABEL: Record<ByteRole, string> = {
  sync: "sync",
  len: "length",
  id: "message id",
  fmt: "format",
  seq: "seq",
  ver: "version",
  res: "reserved",
  body: "ASDU",
};

export function commandById(cat: Catalog | null, id: string): Catalog["commands"][number] | undefined {
  return cat?.commands.find((c) => c.id === id);
}

export function classLabel(cls: string): string {
  switch (cls) {
    case "heartbeat_ack":
      return "heartbeat ack";
    case "heartbeat":
      return "heartbeat";
    default:
      return cls;
  }
}

export function download(name: string, content: string, type = "application/json"): void {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
