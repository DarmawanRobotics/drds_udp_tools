"use client";

import { create } from "zustand";
import type {
  Catalog,
  ConnectConfig,
  LogEvent,
  Overrides,
  PacketEvent,
  RepeatJob,
  SendResult,
  SendStatus,
  SessionSnapshot,
  Stats,
  SuiteCheck,
  SuiteReport,
  SuiteResult,
} from "./types";

const MAX_PACKETS = 4000;
const MAX_LOGS = 500;
const MAX_TRAIL = 900;
const MAX_HISTORY = 80;

export interface Draft {
  items: unknown;
  fmt: "JSON" | "XML";
  useRaw: boolean;
  bodyText: string;
  overrides: Overrides;
  hz: number;
  type?: number;
  command?: number;
}

export interface HistoryItem {
  id: string;
  at: number;
  commandId: string;
  name: string;
  type: number | null;
  command: number | null;
  items: unknown;
  fmt: "JSON" | "XML";
  status: SendStatus | "error";
  code: number | null;
  latency: number | null;
  msgId: number | null;
  error?: string;
}

export interface ReportSlot {
  items: Record<string, unknown> | null;
  time: string | null;
  ts: number;
  fragments: number;
  seq: number;
}

export interface Toast {
  id: number;
  level: "info" | "warn" | "error";
  text: string;
}

type AnyEvent = { kind: string; [k: string]: unknown };

export const DEFAULT_CONN: ConnectConfig = {
  transport: "dtls",
  host: "10.21.33.103",
  port: 30004,
  bind_host: "0.0.0.0",
  bind_port: 0,
  fmt: "JSON",
  heartbeat_enabled: true,
  heartbeat_hz: 2,
  response_timeout: 1.5,
  connect_timeout: 5,
  udp_connect: true,
  auto_split: true,
  tls: { verify: false, ca_file: null, cert_file: null, key_file: null, ciphers: null, server_name: null, dtls_mtu: 1400 },
};

function load<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? { ...fallback, ...JSON.parse(raw) } : fallback;
  } catch {
    return fallback;
  }
}

function loadList<T>(key: string): T[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(key);
    const v = raw ? JSON.parse(raw) : [];
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

function save(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable — keep in memory only */
  }
}

interface State {
  catalog: Catalog | null;
  backend: "unknown" | "online" | "offline";
  ws: "connecting" | "open" | "closed";
  session: SessionSnapshot | null;
  stats: Stats | null;
  packets: PacketEvent[];
  logs: LogEvent[];
  reports: Record<string, ReportSlot>;
  trail: { x: number; y: number; yaw: number; ts: number }[];
  responses: Record<number, PacketEvent[]>;
  repeatJobs: RepeatJob[];
  suite: { running: boolean; runId: string | null; checks: SuiteCheck[]; results: SuiteResult[]; report: SuiteReport | null };
  hbBeat: number;
  armed: boolean;
  conn: ConnectConfig;
  drafts: Record<string, Draft>;
  selected: string;
  result: { forId: string; res: SendResult; at: number } | null;
  sending: boolean;
  history: HistoryItem[];
  toasts: Toast[];
  hydrated: boolean;

  hydrate: () => void;
  setCatalog: (c: Catalog) => void;
  setBackend: (b: State["backend"]) => void;
  setWs: (w: State["ws"]) => void;
  setSession: (s: SessionSnapshot) => void;
  setArmed: (a: boolean) => void;
  setConn: (p: Partial<ConnectConfig>) => void;
  setDraft: (id: string, p: Partial<Draft>) => void;
  select: (id: string) => void;
  setResult: (forId: string, res: SendResult) => void;
  setSending: (s: boolean) => void;
  addHistory: (h: HistoryItem) => void;
  clearHistory: () => void;
  clearTraffic: () => void;
  toast: (level: Toast["level"], text: string) => void;
  dismiss: (id: number) => void;
  ingest: (events: AnyEvent[]) => void;
}

let toastId = 0;

export const useStore = create<State>((set, get) => ({
  catalog: null,
  backend: "unknown",
  ws: "connecting",
  session: null,
  stats: null,
  packets: [],
  logs: [],
  reports: {},
  trail: [],
  responses: {},
  repeatJobs: [],
  suite: { running: false, runId: null, checks: [], results: [], report: null },
  hbBeat: 0,
  armed: false,
  conn: DEFAULT_CONN,
  drafts: {},
  selected: "heartbeat",
  result: null,
  sending: false,
  history: [],
  toasts: [],
  hydrated: false,

  hydrate: () => {
    if (get().hydrated) return;
    const conn = load<ConnectConfig>("ezra.conn", DEFAULT_CONN);
    conn.tls = { ...DEFAULT_CONN.tls, ...(conn.tls ?? {}) };
    set({ conn, history: loadList<HistoryItem>("ezra.history"), hydrated: true });
  },
  setCatalog: (c) => set({ catalog: c }),
  setBackend: (b) => set({ backend: b }),
  setWs: (w) => set({ ws: w }),
  setSession: (s) => set({ session: s, stats: s.stats ?? get().stats }),
  setArmed: (a) => set({ armed: a }),
  setConn: (p) => {
    const conn = { ...get().conn, ...p, tls: { ...get().conn.tls, ...(p.tls ?? {}) } };
    save("ezra.conn", conn);
    set({ conn });
  },
  setDraft: (id, p) => {
    const cur = get().drafts[id];
    set({ drafts: { ...get().drafts, [id]: { ...(cur as Draft), ...p } } });
  },
  select: (id) => set({ selected: id }),
  setResult: (forId, res) => set({ result: { forId, res, at: Date.now() } }),
  setSending: (s) => set({ sending: s }),
  addHistory: (h) => {
    const history = [h, ...get().history].slice(0, MAX_HISTORY);
    save("ezra.history", history);
    set({ history });
  },
  clearHistory: () => {
    save("ezra.history", []);
    set({ history: [] });
  },
  clearTraffic: () => set({ packets: [], logs: [] }),
  toast: (level, text) => {
    const id = ++toastId;
    set({ toasts: [...get().toasts.slice(-3), { id, level, text }] });
    setTimeout(() => get().dismiss(id), level === "error" ? 9000 : 4500);
  },
  dismiss: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),

  ingest: (events) => {
    const st = get();
    // copy-on-write accumulators: only touched collections get a new reference
    const acc = {
      packets: null as PacketEvent[] | null,
      logs: null as LogEvent[] | null,
      reports: null as Record<string, ReportSlot> | null,
      trail: null as State["trail"] | null,
      responses: null as Record<number, PacketEvent[]> | null,
      suite: st.suite,
      session: st.session,
      stats: st.stats,
      repeatJobs: st.repeatJobs,
      hbBeat: st.hbBeat,
    };
    const packets = () => (acc.packets ??= [...st.packets]);
    const logs = () => (acc.logs ??= [...st.logs]);
    const reports = () => (acc.reports ??= { ...st.reports });
    const trail = () => (acc.trail ??= [...st.trail]);
    const responses = () => (acc.responses ??= { ...st.responses });

    const pushPacket = (p: PacketEvent) => {
      packets().push(p);
      if (p.kind === "tx" && p.msg_id !== null && p.class !== "heartbeat") {
        responses()[p.msg_id] = [];
      }
      if (p.kind !== "rx") return;
      if (p.class === "heartbeat_ack") {
        acc.hbBeat++;
        return;
      }
      if (p.request_msg_id !== null && p.request_msg_id !== undefined) {
        const r = responses();
        r[p.request_msg_id] = [...(r[p.request_msg_id] ?? []), p];
      }
      if (p.class === "report" && p.report_id) {
        const it = (p.data?.PatrolDevice?.Items ?? null) as Record<string, unknown> | null;
        reports()[p.report_id] = {
          items: it,
          time: p.data?.PatrolDevice?.Time ?? null,
          ts: p.ts,
          fragments: p.fragments?.length ?? 1,
          seq: p.seq,
        };
        if (p.report_id === "navigation" && it) {
          const loc = it.LocationStatus as Record<string, number> | undefined;
          if (loc && typeof loc.PosX === "number") {
            const t = trail();
            const last = t[t.length - 1];
            if (!last || Math.hypot(last.x - loc.PosX, last.y - loc.PosY) > 0.005 || p.ts - last.ts > 5) {
              t.push({ x: loc.PosX, y: loc.PosY, yaw: loc.Yaw ?? 0, ts: p.ts });
            }
          }
        }
      }
    };

    for (const ev of events) {
      switch (ev.kind) {
        case "hello": {
          acc.packets = [];
          acc.logs = [];
          acc.responses = {};
          acc.reports = {};
          acc.trail = [];
          acc.session = ev.snapshot as SessionSnapshot;
          acc.stats = acc.session?.stats ?? null;
          acc.repeatJobs = acc.stats?.repeat_jobs ?? [];
          for (const h of (ev.history as AnyEvent[]) ?? []) {
            if (h.kind === "tx" || h.kind === "rx") pushPacket(h as unknown as PacketEvent);
            else if (h.kind === "log") logs().push(h as unknown as LogEvent);
          }
          type Latest = { items: Record<string, unknown>; time: string; last_ts: number; fragments: number };
          for (const [rid, r] of Object.entries((ev.reports as Record<string, Latest>) ?? {})) {
            reports()[rid] = { items: r.items, time: r.time, ts: r.last_ts, fragments: r.fragments ?? 1, seq: 0 };
          }
          break;
        }
        case "session":
          acc.session = { ...(ev.snapshot as SessionSnapshot), stats: acc.stats ?? undefined };
          if (ev.state === "connected") {
            acc.reports = {};
            acc.trail = [];
          }
          break;
        case "stats":
          acc.stats = ev.stats as Stats;
          acc.repeatJobs = acc.stats.repeat_jobs;
          break;
        case "tx":
        case "rx":
          pushPacket(ev as unknown as PacketEvent);
          break;
        case "log":
          logs().push(ev as unknown as LogEvent);
          break;
        case "repeat": {
          const job = ev.job as RepeatJob;
          const rest = acc.repeatJobs.filter((j) => j.id !== job.id);
          acc.repeatJobs = ev.action === "started" ? [...rest, job] : rest;
          break;
        }
        case "suite": {
          const s = acc.suite;
          if (ev.phase === "start") {
            acc.suite = { running: true, runId: ev.run_id as string, checks: ev.checks as SuiteCheck[], results: [], report: null };
          } else if (ev.phase === "check_done" && ev.run_id === s.runId) {
            acc.suite = { ...s, results: [...s.results, ev.result as SuiteResult] };
          } else if (ev.phase === "done" && ev.run_id === s.runId) {
            acc.suite = { ...s, running: false, report: ev.report as SuiteReport };
          }
          break;
        }
      }
    }

    const patch: Partial<State> = {
      suite: acc.suite,
      session: acc.session,
      stats: acc.stats,
      repeatJobs: acc.repeatJobs,
      hbBeat: acc.hbBeat,
    };
    if (acc.packets) patch.packets = acc.packets.slice(-MAX_PACKETS);
    if (acc.logs) patch.logs = acc.logs.slice(-MAX_LOGS);
    if (acc.reports) patch.reports = acc.reports;
    if (acc.trail) patch.trail = acc.trail.slice(-MAX_TRAIL);
    if (acc.responses) {
      const keys = Object.keys(acc.responses);
      for (const k of keys.slice(0, Math.max(0, keys.length - 400))) delete acc.responses[Number(k)];
      patch.responses = acc.responses;
    }
    set(patch);
  },
}));
