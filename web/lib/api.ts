import type {
  Catalog,
  ConnectConfig,
  DecodeResult,
  EncodeResult,
  ProbeReport,
  RepeatJob,
  SendBody,
  SendResult,
  SessionSnapshot,
  SuiteCheck,
  SuiteReport,
} from "./types";

// Empty = same origin (GUI served by `ezra-udp serve`). Dev server sets it via .env.development.
export const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(API_BASE + path, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, `Backend unreachable at ${API_BASE || window.location.origin}. Start it with: ezra-udp serve`);
  }
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const detail = (data as { detail?: unknown })?.detail;
    const msg = typeof detail === "string" ? detail : Array.isArray(detail) ? JSON.stringify(detail) : res.statusText;
    throw new ApiError(res.status, msg);
  }
  return data as T;
}

export const api = {
  health: () => call<{ ok: boolean; version: string; state: string }>("GET", "/api/health"),
  catalog: () => call<Catalog>("GET", "/api/catalog"),
  session: () => call<SessionSnapshot>("GET", "/api/session"),
  connect: (cfg: ConnectConfig) => call<SessionSnapshot>("POST", "/api/session/connect", cfg),
  disconnect: () => call<SessionSnapshot>("POST", "/api/session/disconnect"),
  heartbeat: (enabled?: boolean, hz?: number) => call("PUT", "/api/session/heartbeat", { enabled, hz }),
  send: (body: SendBody) => call<SendResult>("POST", "/api/send", body),
  repeat: (body: SendBody & { hz: number; duration?: number | null; count?: number | null }) =>
    call<RepeatJob>("POST", "/api/repeat", body),
  stopRepeat: (id: string) => call("DELETE", `/api/repeat/${id}`),
  stop: () => call<{ stopped_jobs: number; sent: string[] }>("POST", "/api/stop"),
  estop: () => call<{ estop: string }>("POST", "/api/estop"),
  encode: (body: SendBody & { msg_id: number }) => call<EncodeResult>("POST", "/api/codec/encode", body),
  decode: (hex: string) => call<DecodeResult>("POST", "/api/codec/decode", { hex }),
  probe: (host: string, tls: ConnectConfig["tls"], timeout = 2.5) =>
    call<ProbeReport>("POST", "/api/probe", { host, tls, timeout }),
  suiteChecks: () => call<SuiteCheck[]>("GET", "/api/suite/checks"),
  suiteRun: (body: { checks: string[]; allow_caution: boolean; allow_motion: boolean; report_window?: number }) =>
    call<{ started: boolean }>("POST", "/api/suite/run", body),
  suiteLast: () => call<SuiteReport>("GET", "/api/suite/last"),
};

export function wsUrl(): string {
  const base = API_BASE || window.location.origin;
  return base.replace(/^http/, "ws") + "/api/ws";
}
