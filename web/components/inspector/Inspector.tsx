"use client";

import { Copy } from "lucide-react";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useStore } from "@/lib/store";
import type { DecodeResult, EncodeResult } from "@/lib/types";
import { ByteRibbon } from "../ui/ByteRibbon";
import { HexView } from "../ui/HexView";
import { JsonView } from "../ui/JsonView";
import { Chip, Labeled, Segmented } from "../ui/primitives";

const SAMPLE =
  "eb 91 eb 90 59 00 07 00 01 00 01 00 00 00 00 00 7b 22 50 61 74 72 6f 6c 44 65 76 69 63 65 22 3a 7b 22 54 79 70 65 22 3a 31 30 34 38 36 37 36 2c 22 43 6f 6d 6d 61 6e 64 22 3a 35 2c 22 54 69 6d 65 22 3a 22 32 30 32 36 2d 31 31 2d 32 37 20 30 38 3a 34 39 3a 34 36 2e 38 38 34 22 2c 22 49 74 65 6d 73 22 3a 7b 7d 7d 7d";

export function Inspector() {
  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-3 overflow-y-auto p-3 xl:grid-cols-2">
      <Decoder />
      <Encoder />
    </div>
  );
}

function Decoder() {
  const toast = useStore((s) => s.toast);
  const [hex, setHex] = useState("");
  const [res, setRes] = useState<DecodeResult | null>(null);
  const decode = async (h = hex) => {
    try {
      setRes(await api.decode(h));
    } catch (e) {
      toast("error", e instanceof ApiError ? e.message : String(e));
    }
  };
  return (
    <section className="panel flex min-h-0 flex-col">
      <header className="border-b border-line px-4 py-3">
        <h2 className="font-cond text-[19px] font-semibold">Decode captured bytes</h2>
        <p className="text-[12.5px] text-muted">Paste hex from Wireshark (“Copy as hex dump” works), tcpdump or a log. Several APDUs in a row are split automatically.</p>
      </header>
      <div className="flex flex-col gap-2 p-4">
        <textarea className="field min-h-[120px] font-mono text-[12px]" spellCheck={false} placeholder="eb 91 eb 90 …" value={hex}
          onChange={(e) => setHex(e.target.value)} />
        <div className="flex gap-2">
          <button className="btn btn-primary" onClick={() => decode()} disabled={!hex.trim()}>Decode</button>
          <button className="btn" onClick={() => { setHex(SAMPLE); decode(SAMPLE); }}>Try a heartbeat sample</button>
        </div>
      </div>
      {res ? (
        <div className="flex flex-col gap-4 border-t border-line p-4">
          {res.errors.map((e) => (
            <div key={e} className="rounded border border-signal px-3 py-1.5 text-[12.5px]">{e}</div>
          ))}
          {res.frames.map((f, i) => (
            <div key={i} className="flex flex-col gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">Frame {i + 1}: {f.name}</span>
                <Chip tone={f.ok ? "ok" : "bad"}>{f.ok ? f.fmt : "not decodable"}</Chip>
                {f.error_info ? <Chip tone={f.error_info.ok ? "ok" : "bad"}>{f.error_info.hex} {f.error_info.label}</Chip> : null}
                <span className="text-[12px] text-muted">msg {f.header.msg_id} · seq {f.header.seq} · {f.size} B</span>
              </div>
              {f.warnings.map((w) => (
                <div key={w} className="text-[12.5px] text-warn">{w}</div>
              ))}
              <JsonView value={f.data} empty={f.error ?? "—"} />
            </div>
          ))}
          {res.joined ? (
            <div className="rounded-md border border-line p-3">
              <div className="mb-2 text-[13px] font-semibold">Joined as one multi-packet ASDU: {res.joined.ok ? res.joined.name : res.joined.error}</div>
              <JsonView value={res.joined.data} />
            </div>
          ) : null}
          <pre className="overflow-x-auto rounded bg-well p-3 font-mono text-[11.5px]">{res.hexdump}</pre>
        </div>
      ) : null}
    </section>
  );
}

function Encoder() {
  const catalog = useStore((s) => s.catalog);
  const toast = useStore((s) => s.toast);
  const [cid, setCid] = useState("heartbeat");
  const [items, setItems] = useState("{}");
  const [msgId, setMsgId] = useState(0);
  const [fmt, setFmt] = useState<"JSON" | "XML">("JSON");
  const [res, setRes] = useState<EncodeResult | null>(null);
  const cmd = catalog?.commands.find((c) => c.id === cid);

  const encode = async () => {
    try {
      setRes(await api.encode({ command_id: cid, items: JSON.parse(items || "{}"), fmt, msg_id: msgId }));
    } catch (e) {
      toast("error", e instanceof ApiError ? e.message : e instanceof SyntaxError ? `Items: ${e.message}` : String(e));
    }
  };
  const asC = res ? res.hex.match(/../g)!.map((b) => `0x${b.toUpperCase()}`).join(", ") : "";
  return (
    <section className="panel flex min-h-0 flex-col">
      <header className="border-b border-line px-4 py-3">
        <h2 className="font-cond text-[19px] font-semibold">Build bytes offline</h2>
        <p className="text-[12.5px] text-muted">Produce the exact APDU for a command — handy for netcat, firmware tests or comparing captures.</p>
      </header>
      <div className="grid grid-cols-2 gap-3 p-4">
        <Labeled label="Command">
          <select className="field" value={cid} onChange={(e) => {
            setCid(e.target.value);
            const c = catalog?.commands.find((x) => x.id === e.target.value);
            setItems(JSON.stringify(c?.example ?? {}, null, 2));
          }}>
            {catalog?.commands.map((c) => (
              <option key={c.id} value={c.id}>{c.name} (§{c.section})</option>
            ))}
          </select>
        </Labeled>
        <div className="flex items-end gap-3">
          <Labeled label="Message ID">
            <input className="field w-[110px] font-mono" type="number" min={0} max={65535} value={msgId} onChange={(e) => setMsgId(Number(e.target.value))} />
          </Labeled>
          <Segmented value={fmt} onChange={setFmt} options={[{ value: "JSON", label: "JSON" }, { value: "XML", label: "XML" }]} />
        </div>
        <div className="col-span-2">
          <Labeled label={`Items${cmd ? ` — ${cmd.type_hex} / ${cmd.command_hex}` : ""}`}>
            <textarea className="field min-h-[110px] font-mono text-[12px]" spellCheck={false} value={items} onChange={(e) => setItems(e.target.value)} />
          </Labeled>
        </div>
        <div className="col-span-2">
          <button className="btn btn-primary" onClick={encode}>Build APDU</button>
        </div>
      </div>
      {res ? (
        <div className="flex flex-col gap-3 border-t border-line p-4">
          <ByteRibbon hex={res.hex} caption={`${res.size} B in ${res.packets} packet(s)`} />
          <HexView hex={res.hex} />
          <div className="flex flex-wrap gap-2">
            <button className="btn h-8 text-xs" onClick={() => navigator.clipboard?.writeText(res.hex)}><Copy size={13} /> Copy hex</button>
            <button className="btn h-8 text-xs" onClick={() => navigator.clipboard?.writeText(asC)}><Copy size={13} /> Copy as C bytes</button>
            <button className="btn h-8 text-xs" onClick={() => navigator.clipboard?.writeText(`echo '${res.hex}' | xxd -r -p | nc -u -w1 10.21.33.103 30000`)}>
              <Copy size={13} /> Copy netcat one-liner
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
