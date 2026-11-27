"use client";

import { CircleCheck, CircleX, Clock3, Send } from "lucide-react";
import { useState } from "react";
import { fmtTime, hex16 } from "@/lib/format";
import { useStore } from "@/lib/store";
import type { HeaderInfo, PacketEvent, ResponseInfo } from "@/lib/types";
import { ByteRibbon } from "../ui/ByteRibbon";
import { HexView } from "../ui/HexView";
import { JsonView } from "../ui/JsonView";
import { Chip, Empty, Tabs } from "../ui/primitives";
import { useCurrent } from "./RequestPanel";

type T = "reply" | "raw" | "bytes" | "header" | "timeline";

export function ResponsePanel() {
  const { cmd } = useCurrent();
  const result = useStore((s) => s.result);
  const timeout = useStore((s) => s.conn.response_timeout);
  const later = useStore((s) => (s.result?.res.msg_id != null ? s.responses[s.result.res.msg_id] : undefined));
  const [tab, setTab] = useState<T>("reply");

  if (!result || result.forId !== cmd.id) {
    return (
      <section className="min-h-0 bg-panel">
        <Empty title="No reply yet" icon={<Send size={22} />}>
          Send the request to see the robot&apos;s reply, its bytes and timing here. Late replies (like a finished navigation
          task) are added to the timeline automatically.
        </Empty>
      </section>
    );
  }
  const res = result.res;
  // newest reply from the live stream (covers deferred results), falling back to the HTTP result
  const replies: (ResponseInfo | PacketEvent)[] = later?.length ? later : res.response ? [res.response] : [];
  const last = replies[replies.length - 1] as (ResponseInfo & PacketEvent) | undefined;
  const info = last?.error_info ?? null;

  let status: React.ReactNode;
  if (res.status === "ok" || last) {
    const ok = info ? info.ok !== false : last?.ok !== false;
    status = (
      <span className={`flex items-center gap-2 ${ok ? "text-lamp" : "text-bad"}`}>
        {ok ? <CircleCheck size={18} /> : <CircleX size={18} />}
        <span className="font-cond text-[18px] font-semibold">
          {info ? `${info.code === 0 ? "0" : info.hex} ${info.label}` : last?.ok === false ? "Reply did not decode" : "Data reply"}
        </span>
      </span>
    );
  } else if (res.status === "timeout") {
    status = (
      <span className="flex items-center gap-2 text-bad">
        <Clock3 size={18} />
        <span className="font-cond text-[18px] font-semibold">No reply within {timeout} s</span>
      </span>
    );
  } else {
    status = (
      <span className="flex items-center gap-2 text-muted">
        <Send size={17} />
        <span className="font-cond text-[18px] font-semibold">
          {res.status === "sent_no_response_expected" ? "Sent — the docs define no reply frame for this command" : "Sent"}
        </span>
      </span>
    );
  }

  const tabs: { value: T; label: string; badge?: React.ReactNode }[] = [
    { value: "reply", label: "Reply" },
    { value: "raw", label: "Raw" },
    { value: "bytes", label: "Bytes" },
    { value: "header", label: "Header" },
    { value: "timeline", label: "Timeline", badge: <Chip>{replies.length + 1}</Chip> },
  ];

  return (
    <section className="flex min-h-0 flex-col bg-panel">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 px-4 pt-3 pb-2">
        {status}
        <dl className="flex flex-wrap gap-x-4 text-[12.5px] text-muted">
          <Meta k="Msg id" v={res.msg_id ?? "—"} />
          {last?.latency_ms != null ? <Meta k="Time" v={`${last.latency_ms} ms`} /> : null}
          {last ? <Meta k="Size" v={`${last.header ? last.header.length + 16 : "?"} B`} /> : <Meta k="Sent" v={`${res.tx.size} B`} />}
          {last?.src ? <Meta k="From" v={last.src} /> : null}
          {last?.fmt ? <Meta k="Format" v={last.fmt} /> : null}
          {last && (last.fragments?.length ?? 1) > 1 ? <Meta k="Packets" v={last.fragments!.length} /> : null}
          {replies.length > 1 ? <Meta k="Replies" v={replies.length} /> : null}
        </dl>
      </div>
      {res.status === "timeout" && !last ? <TimeoutHints /> : null}
      {last?.warnings?.length ? (
        <div className="mx-4 mb-2 rounded-md border border-signal bg-[color-mix(in_oklab,var(--signal)_12%,transparent)] px-3 py-2 text-[12.5px]">
          {last.warnings.map((w) => (
            <div key={w}>{w}</div>
          ))}
        </div>
      ) : null}
      <Tabs value={tab} onChange={setTab} tabs={tabs} />
      <div className="min-h-0 flex-1 overflow-auto px-4 py-3">
        {tab === "reply" ? (
          last ? <JsonView value={last.data ?? null} empty={last.error ?? "Reply could not be decoded."} /> : <p className="text-[13px] text-muted">Nothing received for this request.</p>
        ) : null}
        {tab === "raw" ? (
          <pre className="font-mono text-[12.5px] whitespace-pre-wrap break-all">{last?.text ?? res.tx.text}</pre>
        ) : null}
        {tab === "bytes" ? (
          <div className="flex flex-col gap-4">
            {last ? (
              <>
                <ByteRibbon hex={last.hex} caption="Reply" />
                <HexView hex={last.hex} />
              </>
            ) : null}
            <div className="border-t border-line pt-3">
              <div className="mb-2 text-[13px] font-semibold">Sent</div>
              <ByteRibbon hex={res.tx.hex} caption="Request" />
            </div>
          </div>
        ) : null}
        {tab === "header" ? (
          <div className="grid gap-6 lg:grid-cols-2">
            <HeaderTable title="Request header" h={res.tx.header} />
            <HeaderTable title="Reply header" h={last?.header ?? null} />
          </div>
        ) : null}
        {tab === "timeline" ? <Timeline tx={res.tx} replies={replies} /> : null}
      </div>
    </section>
  );
}

function Meta({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex gap-1.5">
      <dt>{k}</dt>
      <dd className="font-medium text-ink">{v}</dd>
    </div>
  );
}

function TimeoutHints() {
  const hb = useStore((s) => s.stats?.heartbeat);
  return (
    <div className="mx-4 mb-2 rounded-md border border-line bg-well px-3 py-2 text-[12.5px] text-muted">
      {hb && hb.acked === 0
        ? "The robot has not acknowledged any heartbeat either, so the link itself is down: check host/port, that DTLS vs plain UDP matches the robot's robotserver config, and that your Mac is on the robot network."
        : "Heartbeats are acknowledged, so the link works. The robot may not implement this message, may reply from another port (turn off 'Connected UDP socket'), or may need more time — raise the response timeout in connection settings."}
    </div>
  );
}

function HeaderTable({ title, h }: { title: string; h: HeaderInfo | null }) {
  if (!h) return <div className="text-[13px] text-muted">{title}: none</div>;
  const rows: [string, string, string][] = [
    ["Sync", h.sync, "bytes 0–3, fixed EB 91 EB 90"],
    ["Length", String(h.length), "bytes 4–5, ASDU length, little endian"],
    ["Message ID", `${h.msg_id} (${hex16(h.msg_id)})`, "bytes 6–7, little endian"],
    ["ASDU format", `${h.asdu_format} — ${h.asdu_format_name}`, "byte 8, 0 = XML, 1 = JSON"],
    ["Packet seq", String(h.seq), "byte 9"],
    ["Version", String(h.version), "byte 10, fixed 1"],
    ["Reserved", h.reserved, "bytes 11–15, zero"],
  ];
  return (
    <div>
      <div className="mb-2 text-[13px] font-semibold">{title}</div>
      <table className="w-full text-left text-[13px]">
        <tbody>
          {rows.map(([k, v, d]) => (
            <tr key={k} className="border-b border-line/60">
              <td className="py-1.5 pr-3 text-muted">{k}</td>
              <td className="py-1.5 pr-3 font-mono text-[12px]">{v}</td>
              <td className="py-1.5 text-[12px] text-faint">{d}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Timeline({ tx, replies }: { tx: PacketEvent; replies: (ResponseInfo | PacketEvent)[] }) {
  return (
    <ol className="relative ml-2 border-l border-line pl-5">
      <li className="mb-4">
        <span className="absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full bg-tx" />
        <div className="text-[13px] font-semibold text-tx">Sent {tx.name}</div>
        <div className="text-[12.5px] text-muted">
          {fmtTime(tx.ts)} · msg {tx.msg_id} · {tx.size} B{tx.packets && tx.packets > 1 ? ` in ${tx.packets} packets` : ""}
        </div>
      </li>
      {replies.map((r, i) => {
        const ri = r as ResponseInfo & PacketEvent;
        const code = ri.error_info;
        return (
          <li key={i} className="mb-4">
            <span className="absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full bg-rx" />
            <div className="flex items-center gap-2 text-[13px] font-semibold text-rx">
              Reply {i + 1} · +{ri.latency_ms} ms
              {code ? <Chip tone={code.ok ? "ok" : "bad"}>{code.code === 0 ? "0" : code.hex} {code.label}</Chip> : null}
            </div>
            <div className="mt-1 font-mono text-[12px] text-muted">{JSON.stringify(ri.items ?? ri.data?.PatrolDevice?.Items ?? null)}</div>
          </li>
        );
      })}
    </ol>
  );
}
