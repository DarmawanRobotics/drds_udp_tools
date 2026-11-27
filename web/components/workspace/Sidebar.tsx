"use client";

import { Search, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { fmtTime, hex32 } from "@/lib/format";
import { useStore } from "@/lib/store";
import type { CommandDef } from "@/lib/types";
import { Chip, Segmented } from "../ui/primitives";

const REPLY_LABEL: Record<CommandDef["response"], { text: string; title: string }> = {
  general: { text: "status", title: "Replies with ErrorCode / ErrorMessage (§1.5)" },
  data: { text: "data", title: "Replies with data items" },
  none: { text: "no reply", title: "Documented as sending no response frame" },
  deferred: { text: "deferred", title: "Status reply now, result frame when the task finishes" },
};

export function Sidebar() {
  const catalog = useStore((s) => s.catalog);
  const selected = useStore((s) => s.selected);
  const select = useStore((s) => s.select);
  const history = useStore((s) => s.history);
  const clearHistory = useStore((s) => s.clearHistory);
  const setDraft = useStore((s) => s.setDraft);
  const [tab, setTab] = useState<"collection" | "history">("collection");
  const [q, setQ] = useState("");

  const groups = useMemo(() => {
    const cmds = (catalog?.commands ?? []).filter((c) =>
      `${c.name} ${c.id} ${c.section} ${c.type_hex} ${c.command_hex} ${c.type} ${c.command}`.toLowerCase().includes(q.toLowerCase()),
    );
    const out = new Map<string, CommandDef[]>();
    for (const c of cmds) out.set(c.group, [...(out.get(c.group) ?? []), c]);
    return out;
  }, [catalog, q]);

  return (
    <aside className="flex min-h-0 flex-col border-r border-line bg-panel">
      <div className="flex flex-col gap-2 border-b border-line p-3">
        <Segmented
          size="sm"
          value={tab}
          onChange={setTab}
          options={[
            { value: "collection", label: "Collection" },
            { value: "history", label: `History${history.length ? ` (${history.length})` : ""}` },
          ]}
        />
        {tab === "collection" ? (
          <label className="relative">
            <Search size={14} className="pointer-events-none absolute top-[9px] left-2.5 text-faint" />
            <input className="field w-full pl-8 text-[13px]" placeholder="Search name, section or 0x code" value={q}
              onChange={(e) => setQ(e.target.value)} />
          </label>
        ) : null}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {tab === "collection" ? (
          <>
            {[...groups.entries()].map(([group, cmds]) => (
              <section key={group} className="py-2">
                <h3 className="px-3 pb-1 text-[12.5px] font-semibold text-muted">
                  {group === "Control" ? "Control · §1.2" : group === "Navigation" ? "Navigation · §1.4" : group}
                </h3>
                <ul>
                  {cmds.map((c) => (
                    <li key={c.id}>
                      <button
                        onClick={() => select(c.id)}
                        aria-current={selected === c.id}
                        className={`group relative flex w-full items-center gap-2 py-1.5 pr-3 pl-4 text-left ${
                          selected === c.id ? "bg-well" : "hover:bg-well/60"
                        }`}
                      >
                        {c.danger === "motion" ? (
                          <span className="hazard absolute top-1 bottom-1 left-0 w-[5px] rounded-r" title="Moves the robot" />
                        ) : c.danger === "caution" ? (
                          <span className="absolute top-1 bottom-1 left-0 w-[5px] rounded-r bg-signal" title="Changes robot state" />
                        ) : null}
                        {selected === c.id ? <span className="absolute top-0 right-0 bottom-0 w-[2px] bg-tx" /> : null}
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[13.5px] font-medium">{c.name}</span>
                          <span className="block truncate font-mono text-[10.5px] whitespace-nowrap text-faint" title={`Type ${c.type_hex} · Command ${c.command_hex}`}>
                            §{c.section} · {c.command_hex}
                          </span>
                        </span>
                        <span title={REPLY_LABEL[c.response].title}>
                          <Chip tone={c.response === "none" ? "neutral" : c.response === "deferred" ? "warn" : "tx"}>
                            {REPLY_LABEL[c.response].text}
                          </Chip>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
            <section className="border-t border-line py-2">
              <button
                onClick={() => select("custom")}
                aria-current={selected === "custom"}
                className={`relative flex w-full flex-col py-1.5 pr-3 pl-4 text-left ${selected === "custom" ? "bg-well" : "hover:bg-well/60"}`}
              >
                {selected === "custom" ? <span className="absolute top-0 right-0 bottom-0 w-[2px] bg-tx" /> : null}
                <span className="text-[13.5px] font-medium">Custom message</span>
                <span className="text-[11.5px] text-faint">Any Type / Command, raw body or raw hex</span>
              </button>
            </section>
            <ReportList />
          </>
        ) : (
          <div className="py-1">
            {history.length ? (
              <>
                {history.map((h) => (
                  <button
                    key={h.id}
                    onClick={() => {
                      select(h.commandId);
                      setDraft(h.commandId, {
                        items: structuredClone(h.items),
                        fmt: h.fmt,
                        useRaw: false,
                        ...(h.commandId === "custom" && h.type !== null && h.command !== null
                          ? { type: h.type, command: h.command }
                          : {}),
                      });
                    }}
                    className="flex w-full items-center gap-2 border-b border-line/60 px-3 py-2 text-left hover:bg-well"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] font-medium">{h.name}</span>
                      <span className="block text-[11.5px] text-faint">
                        {fmtTime(h.at / 1000)} · msg {h.msgId ?? "—"} · {h.fmt}
                        {h.latency != null ? ` · ${h.latency} ms` : ""}
                      </span>
                    </span>
                    <HistoryStatus status={h.status} code={h.code} />
                  </button>
                ))}
                <button className="btn btn-ghost m-2 h-7 text-xs text-muted" onClick={clearHistory}>
                  <Trash2 size={13} /> Clear history
                </button>
              </>
            ) : (
              <p className="p-4 text-[13px] text-muted">Requests you send show up here so you can resend them.</p>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}

function HistoryStatus({ status, code }: { status: string; code: number | null }) {
  if (status === "error") return <Chip tone="bad">error</Chip>;
  if (status === "timeout") return <Chip tone="bad">timeout</Chip>;
  if (status === "sent_no_response_expected" || status === "sent") return <Chip>sent</Chip>;
  if (code === null || code === undefined) return <Chip tone="ok">ok</Chip>;
  return <Chip tone={code === 0 || code === 0x2300 ? "ok" : "bad"}>{code === 0 ? "0" : `0x${code.toString(16).toUpperCase()}`}</Chip>;
}

function ReportList() {
  const reports = useStore((s) => s.catalog?.reports ?? []);
  const stats = useStore((s) => s.stats?.reports);
  const live = useStore((s) => s.session?.state === "connected");
  return (
    <section className="border-t border-line py-2">
      <h3 className="px-3 pb-1 text-[12.5px] font-semibold text-muted">Status reports · §1.3 (pushed)</h3>
      <ul>
        {reports.map((r) => {
          const st = stats?.[r.id];
          const hz = st?.hz ?? 0;
          const ok = live && hz > 0 && hz / r.hz > 0.6 && hz / r.hz < 1.5;
          return (
            <li key={r.id} className="flex items-center gap-2 px-4 py-1" title={`${r.summary} ${hex32(r.type)} / ${hex32(r.command)}`}>
              <span className="lamp" data-on={!live ? undefined : ok ? "ok" : hz > 0 ? "warn" : "bad"} />
              <span className="min-w-0 flex-1 truncate text-[13px]">{r.name}</span>
              <span className="font-mono text-[11px] text-muted">
                {live ? hz.toFixed(1) : "–"}/{r.hz} Hz
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
