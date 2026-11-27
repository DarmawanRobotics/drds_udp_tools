"use client";

import { useMemo } from "react";
import { ROLE_COLOR, ROLE_LABEL, hexToBytes, segmentApdus, type ByteRole } from "@/lib/format";

const GROUPS: { role: ByteRole; from: number; to: number }[] = [
  { role: "sync", from: 0, to: 4 },
  { role: "len", from: 4, to: 6 },
  { role: "id", from: 6, to: 8 },
  { role: "fmt", from: 8, to: 9 },
  { role: "seq", from: 9, to: 10 },
  { role: "ver", from: 10, to: 11 },
  { role: "res", from: 11, to: 16 },
];

function meaning(role: ByteRole, b: Uint8Array): string {
  const le = (o: number) => b[o] | (b[o + 1] << 8);
  switch (role) {
    case "sync":
      return b[0] === 0xeb && b[1] === 0x91 && b[2] === 0xeb && b[3] === 0x90 ? "EB 91 EB 90 — valid" : "unexpected sync";
    case "len":
      return `${le(4)} bytes of ASDU (little endian)`;
    case "id":
      return `message id ${le(6)} (little endian)`;
    case "fmt":
      return b[8] === 1 ? "0x01 — JSON" : b[8] === 0 ? "0x00 — XML" : `0x${b[8].toString(16)} — unknown format`;
    case "seq":
      return `packet sequence ${b[9]}`;
    case "ver":
      return `protocol version ${b[10]}${b[10] === 1 ? "" : " (expected 1)"}`;
    case "res":
      return Array.from(b.slice(11, 16)).every((x) => x === 0) ? "reserved, zero" : "reserved bytes are not zero";
    default:
      return "";
  }
}

export function ByteRibbon({
  hex,
  bytes: given,
  caption,
  dense,
}: {
  hex?: string;
  bytes?: Uint8Array;
  caption?: string;
  dense?: boolean;
}) {
  const bytes = useMemo(() => given ?? hexToBytes(hex ?? ""), [given, hex]);
  const segs = useMemo(() => segmentApdus(bytes), [bytes]);
  if (bytes.length < 16 || !segs.length) {
    return (
      <div className="rounded-md border border-dashed border-line px-3 py-2 text-[12.5px] text-muted">
        {bytes.length ? `${bytes.length} byte(s) — not a valid APDU (no EB 91 EB 90 header)` : "No bytes yet"}
      </div>
    );
  }
  const first = segs[0];
  const head = bytes.slice(first.start, first.start + 16);
  const body = new TextDecoder().decode(bytes.slice(first.bodyStart, first.end));
  const cell = dense ? "h-7 text-[11.5px]" : "h-8 text-[12.5px]";
  return (
    <figure className="m-0 min-w-0">
      <div className="flex min-w-0 items-stretch gap-1 overflow-hidden">
        {GROUPS.map((g) => {
          const dark = g.role !== "res";
          return (
            <div key={g.role} className="flex flex-none flex-col items-center gap-1" title={meaning(g.role, head)}>
              <div
                className={`flex items-center rounded-[4px] px-1 font-mono ${cell}`}
                style={{
                  background: g.role === "res" ? "transparent" : ROLE_COLOR[g.role],
                  color: dark ? "#fff" : "var(--muted)",
                  border: g.role === "res" ? "1px dashed var(--line-strong)" : "1px solid transparent",
                }}
              >
                {Array.from(head.slice(g.from, g.to)).map((x, i) => (
                  <span key={i} className="w-[2.6ch] text-center">
                    {x.toString(16).toUpperCase().padStart(2, "0")}
                  </span>
                ))}
              </div>
              {!dense && <span className="text-[11px] leading-none text-faint">{ROLE_LABEL[g.role]}</span>}
            </div>
          );
        })}
        <div className="flex min-w-0 flex-1 flex-col gap-1" title={body}>
          <div
            className={`flex min-w-0 items-center rounded-[4px] border border-line bg-well px-2 font-mono text-ink ${cell}`}
          >
            <span className="truncate">{body || "(empty ASDU)"}</span>
          </div>
          {!dense && (
            <span className="truncate text-[11px] leading-none text-faint">
              {caption ?? `ASDU · ${first.end - first.bodyStart} B`}
              {segs.length > 1 ? ` · ${segs.length} sub-packets (seq ${segs.map((s) => bytes[s.start + 9]).join(", ")})` : ""}
            </span>
          )}
        </div>
      </div>
    </figure>
  );
}
