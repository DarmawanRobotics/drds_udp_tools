"use client";

import { useState, type ReactNode } from "react";
import { annotate } from "@/lib/format";
import { useStore } from "@/lib/store";

const IND = 16;

function Scalar({ v }: { v: unknown }) {
  if (v === null || v === undefined) return <span className="j-null">null</span>;
  if (typeof v === "string") return <span className="j-str">&quot;{v}&quot;</span>;
  if (typeof v === "number") return <span className="j-num">{v}</span>;
  if (typeof v === "boolean") return <span className="j-bool">{String(v)}</span>;
  return <span>{String(v)}</span>;
}

function isScalar(v: unknown) {
  return v === null || typeof v !== "object";
}

function Node({ k, v, depth, parent, last }: { k?: string; v: unknown; depth: number; parent: string; last: boolean }) {
  const enums = useStore((s) => s.catalog?.enums);
  const [open, setOpen] = useState(depth < 5);
  const comma = last ? "" : ",";
  const keyEl = k !== undefined ? (
    <>
      <span className="j-key">&quot;{k}&quot;</span>
      <span className="text-faint">: </span>
    </>
  ) : null;

  if (isScalar(v)) {
    const note = k ? annotate(enums, k, v, parent) : null;
    return (
      <div style={{ paddingLeft: depth * IND }} className="whitespace-pre-wrap break-all">
        {keyEl}
        <Scalar v={v} />
        {comma}
        {note ? <span className="j-note">{note}</span> : null}
      </div>
    );
  }

  if (Array.isArray(v) && v.every(isScalar) && v.length <= 64) {
    const notes = k ? v.map((x) => annotate(enums, k, x, parent)).filter(Boolean) : [];
    return (
      <div style={{ paddingLeft: depth * IND }} className="whitespace-pre-wrap break-words">
        {keyEl}
        <span className="text-faint">[</span>
        {v.map((x, i) => (
          <span key={i}>
            <Scalar v={x} />
            {i < v.length - 1 ? <span className="text-faint">, </span> : null}
          </span>
        ))}
        <span className="text-faint">]</span>
        {comma}
        {notes.length ? <span className="j-note">{Array.from(new Set(notes)).join(", ")}</span> : null}
      </div>
    );
  }

  const entries: [string | undefined, unknown][] = Array.isArray(v)
    ? v.map((x) => [undefined, x])
    : Object.entries(v as Record<string, unknown>);
  const [o, c] = Array.isArray(v) ? ["[", "]"] : ["{", "}"];
  const childParent = k ?? parent;
  return (
    <div>
      <div style={{ paddingLeft: depth * IND }} className="whitespace-pre">
        <button className="mr-1 inline-block w-3 text-faint hover:text-ink" onClick={() => setOpen(!open)} aria-label={open ? "collapse" : "expand"}>
          {open ? "−" : "+"}
        </button>
        {keyEl}
        <span className="text-faint">{o}</span>
        {!open ? (
          <>
            <span className="text-faint"> {entries.length} {Array.isArray(v) ? "items" : "keys"} </span>
            <span className="text-faint">{c}</span>
            {comma}
          </>
        ) : null}
      </div>
      {open ? (
        <>
          {entries.map(([ck, cv], i) => (
            <Node key={ck ?? i} k={ck} v={cv} depth={depth + 1} parent={childParent} last={i === entries.length - 1} />
          ))}
          <div style={{ paddingLeft: depth * IND }} className="whitespace-pre text-faint">
            <span className="mr-1 inline-block w-3" />
            {c}
            {comma}
          </div>
        </>
      ) : null}
    </div>
  );
}

export function JsonView({ value, empty }: { value: unknown; empty?: ReactNode }) {
  if (value === undefined || value === null) return <div className="p-3 text-[13px] text-muted">{empty ?? "No data."}</div>;
  return (
    <div className="font-mono text-[12.5px] leading-[1.65]">
      <Node v={value} depth={0} parent="" last />
    </div>
  );
}
