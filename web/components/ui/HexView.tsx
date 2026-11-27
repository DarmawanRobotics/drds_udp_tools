"use client";

import { useMemo, useState } from "react";
import { ROLE_COLOR, ROLE_LABEL, headerRole, hexToBytes, segmentApdus } from "@/lib/format";

const ROW = 16;
const LIMIT_ROWS = 160;

export function HexView({ hex }: { hex: string }) {
  const bytes = useMemo(() => hexToBytes(hex), [hex]);
  const [all, setAll] = useState(false);
  const roles = useMemo(() => {
    const r = new Array<string>(bytes.length).fill("body");
    for (const s of segmentApdus(bytes)) for (let i = s.start; i < s.bodyStart; i++) r[i] = headerRole(i - s.start);
    return r;
  }, [bytes]);
  const rows = Math.ceil(bytes.length / ROW);
  const shown = all ? rows : Math.min(rows, LIMIT_ROWS);
  if (!bytes.length) return <div className="p-4 text-[13px] text-muted">No bytes.</div>;
  return (
    <div className="font-mono text-[12px] leading-[1.7]">
      <div className="mb-2 flex flex-wrap gap-x-3 gap-y-1 font-sans text-[12px] text-muted">
        {(["sync", "len", "id", "fmt", "seq", "ver", "res"] as const).map((r) => (
          <span key={r} className="inline-flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: ROLE_COLOR[r] }} />
            {ROLE_LABEL[r]}
          </span>
        ))}
        <span className="ml-auto">{bytes.length} bytes</span>
      </div>
      {Array.from({ length: shown }, (_, row) => {
        const off = row * ROW;
        const chunk = Array.from(bytes.slice(off, off + ROW));
        return (
          <div key={row} className="flex whitespace-pre">
            <span className="mr-3 select-none text-faint">{off.toString(16).toUpperCase().padStart(6, "0")}</span>
            <span className="flex">
              {chunk.map((b, i) => {
                const role = roles[off + i];
                const head = role !== "body";
                return (
                  <span
                    key={i}
                    className={`w-[3ch] text-center ${i === 8 ? "ml-[1ch]" : ""}`}
                    style={
                      head
                        ? {
                            background: role === "res" ? "var(--well)" : ROLE_COLOR[role as keyof typeof ROLE_COLOR],
                            color: role === "res" ? "var(--muted)" : "#fff",
                          }
                        : undefined
                    }
                  >
                    {b.toString(16).toUpperCase().padStart(2, "0")}
                  </span>
                );
              })}
              {Array.from({ length: ROW - chunk.length }, (_, i) => (
                <span key={`p${i}`} className="w-[3ch]" />
              ))}
            </span>
            <span className="ml-4 text-muted">
              {chunk.map((b) => (b >= 32 && b < 127 ? String.fromCharCode(b) : ".")).join("")}
            </span>
          </div>
        );
      })}
      {shown < rows ? (
        <button className="btn mt-2 h-7 text-xs" onClick={() => setAll(true)}>
          Show all {rows} rows
        </button>
      ) : null}
    </div>
  );
}
