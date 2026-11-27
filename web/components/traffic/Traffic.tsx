"use client";

import { Download, Pause, Play, Trash2, X } from "lucide-react";
import { useMemo, useState } from "react";
import { classLabel, download, fmtTime, hex32 } from "@/lib/format";
import { useStore } from "@/lib/store";
import type { PacketEvent } from "@/lib/types";
import { ByteRibbon } from "../ui/ByteRibbon";
import { HexView } from "../ui/HexView";
import { JsonView } from "../ui/JsonView";
import { Chip, Empty, Tabs, type Tone } from "../ui/primitives";

const FILTERS = [
  { id: "requests", label: "Requests & replies" },
  { id: "reports", label: "Reports" },
  { id: "heartbeat", label: "Heartbeat" },
  { id: "streams", label: "Streams" },
  { id: "problems", label: "Problems only" },
] as const;
type FilterId = (typeof FILTERS)[number]["id"];

function bucket(p: PacketEvent): FilterId {
  if (p.class === "heartbeat" || p.class === "heartbeat_ack") return "heartbeat";
  if (p.class === "report") return "reports";
  if (p.class === "repeat" || p.class === "stop") return "streams";
  return "requests";
}

function isProblem(p: PacketEvent): boolean {
  return (
    p.ok === false ||
    (p.error_info ? p.error_info.ok === false : false) ||
    (p.warnings?.length ?? 0) > 0 ||
    p.class === "unknown" ||
    p.class === "garbage" ||
    p.complete === false
  );
}

function tone(p: PacketEvent): Tone {
  if (p.dir === "tx") return "tx";
  if (isProblem(p)) return "bad";
  return "rx";
}

export function Traffic() {
  const packets = useStore((s) => s.packets);
  const logs = useStore((s) => s.logs);
  const clear = useStore((s) => s.clearTraffic);
  const [on, setOn] = useState<Record<FilterId, boolean>>({ requests: true, reports: true, heartbeat: false, streams: true, problems: false });
  const [q, setQ] = useState("");
  const [frozen, setFrozen] = useState<PacketEvent[] | null>(null);
  const [sel, setSel] = useState<PacketEvent | null>(null);
  const [view, setView] = useState<"packets" | "log">("packets");

  const source = frozen ?? packets;
  const rows = useMemo(() => {
    const ql = q.trim().toLowerCase();
    const out: PacketEvent[] = [];
    for (let i = source.length - 1; i >= 0 && out.length < 500; i--) {
      const p = source[i];
      if (on.problems ? !isProblem(p) : !on[bucket(p)]) continue;
      if (ql && !`${p.name} ${p.msg_id} ${p.class} ${hex32(p.type)} ${hex32(p.command)} ${p.src ?? ""}`.toLowerCase().includes(ql)) continue;
      out.push(p);
    }
    return out;
  }, [source, on, q]);

  return (
    <div className="grid h-full min-h-0 grid-cols-[minmax(0,1fr)_auto] bg-panel">
      <div className="flex min-h-0 min-w-0 flex-col">
        <Tabs
          value={view}
          onChange={setView}
          tabs={[
            { value: "packets", label: "Packets", badge: <Chip>{source.length}</Chip> },
            { value: "log", label: "Engine log", badge: <Chip>{logs.length}</Chip> },
          ]}
          right={
            <>
              <button className="btn h-7 text-xs" onClick={() => setFrozen(frozen ? null : [...packets])}>
                {frozen ? <Play size={13} /> : <Pause size={13} />} {frozen ? "Resume" : "Pause"}
              </button>
              <button className="btn h-7 text-xs" onClick={() => download(`ezra-traffic-${Date.now()}.json`, JSON.stringify(source, null, 1))}>
                <Download size={13} /> Export
              </button>
              <button className="btn h-7 text-xs" onClick={() => { clear(); setFrozen(null); setSel(null); }}>
                <Trash2 size={13} /> Clear
              </button>
            </>
          }
        />
        {view === "packets" ? (
          <>
            <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
              {FILTERS.map((f) => (
                <button
                  key={f.id}
                  aria-pressed={on[f.id]}
                  onClick={() => setOn({ ...on, [f.id]: !on[f.id] })}
                  className={`h-7 rounded-full border px-3 text-[12.5px] font-semibold ${
                    on[f.id] ? "border-ink bg-ink text-panel" : "border-line text-muted hover:text-ink"
                  }`}
                >
                  {f.label}
                </button>
              ))}
              <input className="field ml-auto h-7 min-h-7 w-[240px] text-[13px]" placeholder="Filter by name, msg id, 0x code, address" value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
            <div className="min-h-0 flex-1 overflow-auto">
              {rows.length ? (
                <table className="w-full border-collapse text-left text-[12.5px]">
                  <thead className="sticky top-0 z-10 bg-panel text-muted shadow-[0_1px_0_var(--line)]">
                    <tr>
                      {["Time", "", "Kind", "Msg", "Message", "Type / Command", "Size", "Result"].map((h, i) => (
                        <th key={i} className="px-2 py-1.5 font-medium whitespace-nowrap">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((p) => (
                      <tr
                        key={p.seq}
                        onClick={() => setSel(p)}
                        className={`cursor-pointer border-b border-line/50 ${sel?.seq === p.seq ? "bg-well" : "hover:bg-well/60"}`}
                      >
                        <td className="px-2 py-1 font-mono text-[11px] whitespace-nowrap text-muted">{fmtTime(p.ts)}</td>
                        <td className="px-1 py-1">
                          <span className={`font-semibold ${p.dir === "tx" ? "text-tx" : "text-rx"}`} title={p.dir === "tx" ? "sent" : "received"}>
                            {p.dir === "tx" ? "↑" : "↓"}
                          </span>
                        </td>
                        <td className="px-2 py-1"><Chip tone={tone(p)}>{classLabel(p.class)}</Chip></td>
                        <td className="px-2 py-1 font-mono text-[11.5px]">{p.msg_id ?? "—"}</td>
                        <td className="max-w-[280px] truncate px-2 py-1 font-medium">{p.name}</td>
                        <td className="px-2 py-1 font-mono text-[11px] whitespace-nowrap text-muted">{hex32(p.type)} / {hex32(p.command)}</td>
                        <td className="px-2 py-1 whitespace-nowrap text-muted">
                          {p.size} B{(p.fragments?.length ?? 1) > 1 ? ` · ${p.fragments!.length} pk` : ""}
                        </td>
                        <td className="px-2 py-1 whitespace-nowrap">
                          <ResultCell p={p} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <Empty title="No packets match">Connect to a robot (or the mock) and traffic shows up here live. Heartbeats are hidden by default.</Empty>
              )}
            </div>
          </>
        ) : (
          <div className="min-h-0 flex-1 overflow-auto px-3 py-2 font-mono text-[12px]">
            {logs.length ? (
              [...logs].reverse().map((l) => (
                <div key={l.seq} className="flex gap-3 border-b border-line/40 py-1">
                  <span className="text-faint">{fmtTime(l.ts)}</span>
                  <span className={l.level === "error" ? "text-bad" : l.level === "warn" ? "text-warn" : "text-muted"}>{l.level}</span>
                  <span className="min-w-0 break-words text-ink">{l.message}</span>
                </div>
              ))
            ) : (
              <Empty title="Log is empty">Connection events, DTLS handshakes, ICMP errors and fault changes are logged here.</Empty>
            )}
          </div>
        )}
      </div>
      {sel ? <PacketDetail p={sel} onClose={() => setSel(null)} /> : null}
    </div>
  );
}

function ResultCell({ p }: { p: PacketEvent }) {
  if (p.dir === "tx") return <span className="text-muted">{p.expect === "none" ? "no reply expected" : ""}</span>;
  if (p.ok === false) return <span className="text-bad">{p.error ?? "decode error"}</span>;
  if (p.error_info)
    return (
      <span className={p.error_info.ok ? "text-lamp" : "text-bad"}>
        {p.error_info.code === 0 ? "0" : p.error_info.hex} {p.error_info.label}
        {p.latency_ms != null ? <span className="text-muted"> · {p.latency_ms} ms</span> : null}
      </span>
    );
  if (p.latency_ms != null) return <span className="text-muted">{p.latency_ms} ms</span>;
  if (p.warnings?.length) return <span className="text-warn">{p.warnings[0]}</span>;
  return null;
}

function PacketDetail({ p, onClose }: { p: PacketEvent; onClose: () => void }) {
  const [tab, setTab] = useState<"decoded" | "bytes" | "text">("decoded");
  return (
    <aside className="flex min-h-0 w-[520px] flex-col border-l border-line bg-panel">
      <div className="flex items-start gap-2 border-b border-line px-4 py-3">
        <div className="min-w-0 flex-1">
          <div className="font-cond text-[17px] font-semibold">{p.name}</div>
          <div className="text-[12.5px] text-muted">
            {p.dir === "tx" ? "Sent" : `Received from ${p.src}`} at {fmtTime(p.ts)} · msg {p.msg_id ?? "—"} · {p.size} B
          </div>
        </div>
        <button className="btn btn-ghost w-8 px-0" onClick={onClose} aria-label="Close details">
          <X size={16} />
        </button>
      </div>
      <div className="px-4 py-3">
        <ByteRibbon hex={p.hex} />
      </div>
      {p.warnings?.length ? (
        <div className="mx-4 mb-2 rounded-md border border-signal px-3 py-2 text-[12.5px]">
          {p.warnings.map((w) => (
            <div key={w}>{w}</div>
          ))}
        </div>
      ) : null}
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { value: "decoded", label: "Decoded" },
          { value: "bytes", label: "Bytes" },
          { value: "text", label: "Text" },
        ]}
      />
      <div className="min-h-0 flex-1 overflow-auto px-4 py-3">
        {tab === "decoded" ? <JsonView value={p.data} empty={p.error ?? "Not decodable."} /> : null}
        {tab === "bytes" ? <HexView hex={p.hex} /> : null}
        {tab === "text" ? <pre className="font-mono text-[12px] whitespace-pre-wrap break-all">{p.text}</pre> : null}
      </div>
    </aside>
  );
}
