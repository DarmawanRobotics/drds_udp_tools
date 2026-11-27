"use client";

import { Copy, Hand, Play, Repeat2, Send, Square } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { buildDoc, buildHeader, commandById, encodeBody, hex32, utf8 } from "@/lib/format";
import { type Draft, useStore } from "@/lib/store";
import type { CommandDef, Overrides, SendBody } from "@/lib/types";
import { ByteRibbon } from "../ui/ByteRibbon";
import { Chip, Kbd, Labeled, Switch, Tabs } from "../ui/primitives";
import { ParamsForm } from "./ParamsForm";

const CUSTOM: CommandDef = {
  id: "custom",
  section: "—",
  group: "Custom",
  name: "Custom message",
  type: 0x00100064,
  command: 5,
  type_hex: "",
  command_hex: "",
  response: "general",
  summary: "Craft any Type / Command / Items — e.g. to probe undocumented messages or error handling.",
  fields: [],
  example: {},
  notes: ["Unknown Type/Command pairs should be answered with E003 (Unsupported protocol type)."],
  danger: "safe",
  repeat_hz: null,
  response_fields: {},
};

function cleanOverrides(o: Overrides): Overrides | undefined {
  const out = Object.fromEntries(Object.entries(o).filter(([, v]) => v !== null && v !== undefined && v !== ""));
  return Object.keys(out).length ? (out as Overrides) : undefined;
}

export function useCurrent(): { cmd: CommandDef; draft: Draft } {
  const catalog = useStore((s) => s.catalog);
  const selected = useStore((s) => s.selected);
  const drafts = useStore((s) => s.drafts);
  const fmt = useStore((s) => s.conn.fmt);
  const cmd = selected === "custom" ? CUSTOM : commandById(catalog, selected) ?? CUSTOM;
  const draft: Draft = drafts[cmd.id] ?? {
    items: structuredClone(cmd.example),
    fmt,
    useRaw: false,
    bodyText: "",
    overrides: {},
    hz: cmd.repeat_hz ?? 10,
    ...(cmd.id === "custom" ? { type: CUSTOM.type, command: CUSTOM.command } : {}),
  };
  return { cmd, draft };
}

export function RequestPanel() {
  const { cmd, draft } = useCurrent();
  const setDraft = useStore((s) => s.setDraft);
  const armed = useStore((s) => s.armed);
  const live = useStore((s) => s.session?.state === "connected");
  const sending = useStore((s) => s.sending);
  const jobs = useStore((s) => s.repeatJobs);
  const toast = useStore((s) => s.toast);
  const [tab, setTab] = useState<"params" | "body" | "header" | "docs">("params");
  const update = (p: Partial<Draft>) => setDraft(cmd.id, { ...draft, ...p });

  const type = cmd.id === "custom" ? draft.type ?? CUSTOM.type : cmd.type;
  const command = cmd.id === "custom" ? draft.command ?? CUSTOM.command : cmd.command;
  const myJob = jobs.find((j) => j.type === type && j.command === command);
  const blocked = cmd.danger === "motion" && !armed;

  const preview = useMemo(() => {
    const text = draft.useRaw ? draft.bodyText : encodeBody(buildDoc(type, command, draft.items), draft.fmt);
    const body = utf8(text);
    const ov = draft.overrides;
    const header = buildHeader({
      length: ov.length ?? body.length,
      msgId: ov.msg_id ?? 0,
      fmt: ov.asdu_format ?? (draft.fmt === "XML" ? 0 : 1),
      seq: ov.seq ?? 0,
      version: ov.version ?? 1,
    });
    const out = new Uint8Array(header.length + body.length);
    out.set(header);
    out.set(body, header.length);
    return out;
  }, [draft, type, command]);

  const body = (): SendBody => {
    const base: SendBody = {
      fmt: draft.fmt,
      overrides: cleanOverrides(draft.overrides),
      label: cmd.name,
    };
    if (draft.useRaw) return { ...base, type, command, body_text: draft.bodyText, expect: cmd.id === "custom" ? "auto" : cmd.response };
    if (cmd.id === "custom") return { ...base, type, command, items: draft.items ?? {} };
    return { ...base, command_id: cmd.id, items: draft.items };
  };

  const guard = (): boolean => {
    if (!live) {
      toast("warn", "Connect to the robot first (top bar).");
      return false;
    }
    if (blocked) {
      toast("warn", `${cmd.name} moves the robot. Set the lock in the top bar to "Armed" first.`);
      return false;
    }
    return true;
  };

  const send = async () => {
    if (!guard() || sending) return;
    const st = useStore.getState();
    st.setSending(true);
    try {
      const res = await api.send(body());
      st.setResult(cmd.id, res);
      st.addHistory({
        id: `${Date.now()}-${res.msg_id}`,
        at: Date.now(),
        commandId: cmd.id,
        name: cmd.name,
        type: res.type,
        command: res.command,
        items: draft.items,
        fmt: draft.fmt,
        status: res.status,
        code: res.response?.error_code ?? null,
        latency: res.latency_ms,
        msgId: res.msg_id,
      });
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : String(e);
      toast("error", msg);
      st.addHistory({ id: `${Date.now()}`, at: Date.now(), commandId: cmd.id, name: cmd.name, type, command, items: draft.items,
        fmt: draft.fmt, status: "error", code: null, latency: null, msgId: null, error: msg });
    } finally {
      st.setSending(false);
    }
  };

  const startStream = async (): Promise<string | null> => {
    if (!guard()) return null;
    try {
      const job = await api.repeat({ ...body(), hz: draft.hz });
      return job.id;
    } catch (e) {
      toast("error", e instanceof ApiError ? e.message : String(e));
      return null;
    }
  };
  const stopStream = async (id?: string) => {
    const jid = id ?? myJob?.id;
    if (jid) await api.stopRepeat(jid).catch(() => undefined);
  };

  // hold-to-move (dead-man): stream while pressed, zero on release
  const holdJob = useRef<string | null>(null);
  const holdStart = async () => {
    holdJob.current = await startStream();
  };
  const holdEnd = async () => {
    const id = holdJob.current;
    holdJob.current = null;
    if (id) {
      await stopStream(id);
      const zero = { X: 0, Y: 0, Z: 0, Roll: 0, Pitch: 0, Yaw: 0 };
      await api.send({ command_id: cmd.id, items: zero, fmt: draft.fmt, wait: false }).catch(() => undefined);
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        send();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const docText = useMemo(
    () => encodeBody(buildDoc(type, command, draft.items, "2026-01-01 00:00:00.000"), draft.fmt, true),
    [type, command, draft.items, draft.fmt],
  );

  return (
    <section className="flex min-h-0 flex-col border-b border-line bg-panel">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 pt-3 pb-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h2 className="truncate font-cond text-[21px] leading-tight font-semibold">{cmd.name}</h2>
            {cmd.section !== "—" ? <span className="text-[13px] text-muted">§{cmd.section}</span> : null}
            {cmd.danger === "motion" ? <Chip tone="warn">moves the robot</Chip> : cmd.danger === "caution" ? <Chip tone="warn">changes state</Chip> : null}
          </div>
          <div className="mt-0.5 flex flex-wrap gap-x-3 text-[13px] text-muted">
            <span>{cmd.summary}</span>
            <span className="font-mono text-[11.5px] text-faint">Type {hex32(type)} · Command {hex32(command)}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {cmd.repeat_hz ? (
            <button
              type="button"
              className="btn select-none"
              title="Hold to stream at the rate below; releasing sends a zero command"
              onPointerDown={holdStart}
              onPointerUp={holdEnd}
              onPointerLeave={() => holdJob.current && holdEnd()}
              disabled={!live || blocked}
            >
              <Hand size={15} /> Hold to move
            </button>
          ) : null}
          <div className="flex items-center rounded-md border border-line-strong">
            <input aria-label="Stream rate (Hz)" className="h-[30px] w-14 rounded-l-md bg-transparent px-2 text-right font-mono text-[12px] outline-none"
              type="number" min={0.2} max={50} step={1} value={draft.hz} onChange={(e) => update({ hz: Number(e.target.value) || 1 })} />
            <span className="pr-2 text-[12px] text-muted">Hz</span>
            {myJob ? (
              <button type="button" className="flex h-[30px] items-center gap-1.5 border-l border-line-strong bg-signal px-2.5 text-[13px] font-semibold text-signal-ink" onClick={() => stopStream()}>
                <Square size={12} fill="currentColor" /> Stop stream ({myJob.sent})
              </button>
            ) : (
              <button type="button" className="flex h-[30px] items-center gap-1.5 border-l border-line-strong px-2.5 text-[13px] font-semibold hover:bg-well disabled:opacity-40"
                disabled={!live || blocked} onClick={() => startStream()}>
                <Repeat2 size={14} /> Stream
              </button>
            )}
          </div>
          <button type="button" className="btn btn-primary min-w-[96px]" onClick={send} disabled={sending} title="Send (Ctrl/⌘ + Enter)">
            <Send size={14} /> {sending ? "Sending…" : "Send"}
          </button>
        </div>
      </div>

      {cmd.id === "custom" ? (
        <div className="flex flex-wrap items-end gap-3 px-4 pb-2">
          <Labeled label="Type (decimal or 0x…)">
            <NumberHex value={type} onChange={(v) => update({ type: v })} />
          </Labeled>
          <Labeled label="Command (decimal or 0x…)">
            <NumberHex value={command} onChange={(v) => update({ command: v })} />
          </Labeled>
          <span className="pb-2 font-mono text-[12px] text-muted">{hex32(type)} / {hex32(command)}</span>
        </div>
      ) : null}

      <div className="px-4 pb-3">
        <ByteRibbon bytes={preview} caption={`ASDU preview · ${preview.length - 16} B · msg id is assigned on send`} />
      </div>

      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { value: "params", label: "Params", badge: cmd.fields.length ? <Chip>{cmd.fields.length}</Chip> : undefined },
          { value: "body", label: "Body", badge: draft.useRaw ? <Chip tone="warn">raw</Chip> : undefined },
          { value: "header", label: "Header", badge: cleanOverrides(draft.overrides) ? <Chip tone="warn">override</Chip> : undefined },
          { value: "docs", label: "Docs" },
        ]}
        right={
          <span className="flex items-center gap-1.5 text-[12px] text-muted">
            <Kbd>⌘/Ctrl</Kbd>+<Kbd>Enter</Kbd> send · <Kbd>Esc</Kbd> stop
          </span>
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {tab === "params" ? (
          cmd.id === "custom" ? (
            <ItemsJsonEditor value={draft.items} onChange={(v) => update({ items: v })} />
          ) : (
            <ParamsForm fields={cmd.fields} value={draft.items} onChange={(v) => update({ items: v })} />
          )
        ) : null}
        {tab === "body" ? <BodyEditor draft={draft} docText={docText} update={update} /> : null}
        {tab === "header" ? <HeaderEditor overrides={draft.overrides} onChange={(o) => update({ overrides: o })} /> : null}
        {tab === "docs" ? <DocsTab cmd={cmd} /> : null}
      </div>
    </section>
  );
}

function NumberHex({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  return (
    <input
      className="field w-[160px] font-mono"
      value={text}
      onChange={(e) => {
        setText(e.target.value);
        const t = e.target.value.trim().replace(/\s+/g, "");
        const n = t.toLowerCase().startsWith("0x") ? parseInt(t.slice(2), 16) : Number(t);
        if (Number.isFinite(n)) onChange(n);
      }}
    />
  );
}

function ItemsJsonEditor({ value, onChange }: { value: unknown; onChange: (v: unknown) => void }) {
  const [text, setText] = useState(JSON.stringify(value ?? {}, null, 2));
  const [err, setErr] = useState<string | null>(null);
  return (
    <div className="flex flex-col gap-2">
      <span className="text-[13px] font-semibold">Items (JSON)</span>
      <textarea
        className="field min-h-[160px] font-mono text-[12.5px]"
        spellCheck={false}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          try {
            onChange(JSON.parse(e.target.value || "{}"));
            setErr(null);
          } catch (ex) {
            setErr(String((ex as Error).message));
          }
        }}
      />
      {err ? <span className="text-[12.5px] text-bad">{err}</span> : <span className="text-[12px] text-faint">Valid JSON.</span>}
    </div>
  );
}

function BodyEditor({ draft, docText, update }: { draft: Draft; docText: string; update: (p: Partial<Draft>) => void }) {
  const err = useMemo(() => {
    if (!draft.useRaw || draft.fmt !== "JSON") return null;
    try {
      JSON.parse(draft.bodyText);
      return null;
    } catch (e) {
      return (e as Error).message;
    }
  }, [draft.useRaw, draft.bodyText, draft.fmt]);
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-3">
        <Switch
          checked={draft.useRaw}
          onChange={(v) => update({ useRaw: v, bodyText: v && !draft.bodyText ? docText : draft.bodyText })}
          label="Send this text byte-for-byte (raw body)"
        />
        <button type="button" className="btn btn-ghost h-7 text-xs" onClick={() => navigator.clipboard?.writeText(draft.useRaw ? draft.bodyText : docText)}>
          <Copy size={13} /> Copy
        </button>
        {draft.useRaw ? (
          <button type="button" className="btn btn-ghost h-7 text-xs" onClick={() => update({ bodyText: docText })}>
            <Play size={13} /> Reset from params
          </button>
        ) : null}
      </div>
      <textarea
        className="field min-h-[220px] font-mono text-[12.5px] leading-relaxed"
        spellCheck={false}
        readOnly={!draft.useRaw}
        value={draft.useRaw ? draft.bodyText : docText}
        onChange={(e) => update({ bodyText: e.target.value })}
      />
      <span className={`text-[12.5px] ${err ? "text-bad" : "text-faint"}`}>
        {draft.useRaw
          ? err
            ? `Not valid JSON: ${err} — useful to test E002, but check before sending.`
            : "Raw mode: Type/Command/Time are taken from this text. Malformed text is sent as-is (E002 test)."
          : "Generated from Params. The real Time stamp is filled in when you send. Switch on raw mode to edit."}
      </span>
    </div>
  );
}

function HeaderEditor({ overrides, onChange }: { overrides: Overrides; onChange: (o: Overrides) => void }) {
  const row = (key: keyof Overrides, label: string, hint: string, kind: "num" | "hex" = "num") => {
    const v = overrides[key];
    const on = v !== undefined && v !== null && v !== "";
    return (
      <div className="grid grid-cols-[180px_auto_1fr] items-center gap-3 border-b border-line/60 py-2">
        <Switch
          checked={on}
          onChange={(c) => onChange({ ...overrides, [key]: c ? (kind === "hex" ? (key === "sync_hex" ? "EB 91 EB 90" : "00 00 00 00 00") : 0) : null })}
          label={label}
        />
        <input
          className={`field w-[180px] font-mono ${on ? "" : "opacity-40"}`}
          disabled={!on}
          value={on ? String(v) : "auto"}
          onChange={(e) =>
            onChange({ ...overrides, [key]: kind === "hex" ? e.target.value : e.target.value === "" ? 0 : Number(e.target.value) })
          }
        />
        <span className="text-[12.5px] text-muted">{hint}</span>
      </div>
    );
  };
  return (
    <div>
      <p className="mb-2 text-[13px] text-muted">
        Leave everything on auto for normal use. Overrides craft off-spec frames to see how the robot handles them.
      </p>
      {row("msg_id", "Message ID", "0–65535. Auto increments from 0 and wraps (§1.1.5).")}
      {row("asdu_format", "ASDU format byte", "0 = XML, 1 = JSON; anything else should give E001.")}
      {row("seq", "Packet sequence", "0–255, used for multi-packet transfers.")}
      {row("version", "Protocol version", "Fixed 1 in V1.0.3.")}
      {row("length", "Length field", "Force a wrong length (actual ASDU length is used otherwise).")}
      {row("reserved_hex", "Reserved bytes", "5 bytes hex, normally zero.", "hex")}
      {row("sync_hex", "Sync bytes", "4 bytes hex, normally EB 91 EB 90.", "hex")}
    </div>
  );
}

function DocsTab({ cmd }: { cmd: CommandDef }) {
  const rows: { name: string; kind: string; unit?: string; info: string }[] = [];
  const walk = (fs: CommandDef["fields"], prefix = "") => {
    for (const f of fs) {
      const info = f.enum
        ? Object.entries(f.enum).map(([k, v]) => `${v} = ${k}`).join(", ")
        : f.min !== undefined || f.max !== undefined
          ? `${f.min ?? "−∞"} … ${f.max ?? "∞"}`
          : f.help ?? "";
      rows.push({ name: prefix + f.name, kind: f.kind === "array" ? `array${f.item_kind ? `<${f.item_kind}>` : ""}` : f.kind, unit: f.unit, info });
      if (f.fields) walk(f.fields, prefix + f.name + (f.kind === "array" ? "[]." : "."));
    }
  };
  walk(cmd.fields);
  return (
    <div className="flex max-w-[860px] flex-col gap-4 text-[13.5px]">
      {cmd.id !== "custom" ? (
        <div className="flex flex-wrap gap-x-6 gap-y-1 font-mono text-[12.5px]">
          <span>Type {cmd.type} ({cmd.type_hex})</span>
          <span>Command {cmd.command} ({cmd.command_hex})</span>
          <span className="font-sans">Reply: {cmd.response}</span>
        </div>
      ) : null}
      {cmd.notes.length ? (
        <ul className="list-disc space-y-1 pl-5">
          {cmd.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      ) : null}
      {rows.length ? (
        <table className="w-full border-collapse text-left text-[13px]">
          <thead>
            <tr className="border-b border-line text-muted">
              <th className="py-1.5 pr-3 font-medium">Field</th>
              <th className="py-1.5 pr-3 font-medium">Type</th>
              <th className="py-1.5 pr-3 font-medium">Unit</th>
              <th className="py-1.5 font-medium">Values</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name} className="border-b border-line/60 align-top">
                <td className="py-1.5 pr-3 font-mono text-[12px]">{r.name}</td>
                <td className="py-1.5 pr-3">{r.kind}</td>
                <td className="py-1.5 pr-3">{r.unit || "—"}</td>
                <td className="py-1.5 text-muted">{r.info || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </div>
  );
}
