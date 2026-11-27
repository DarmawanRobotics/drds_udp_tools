export type TransportKind = "dtls" | "udp" | "tls" | "tcp";
export type FieldKind = "int" | "float" | "bool" | "enum" | "object" | "array" | "string";
export type ResponseKind = "general" | "data" | "none" | "deferred";
export type Danger = "safe" | "caution" | "motion";

export interface FieldDef {
  name: string;
  kind: FieldKind;
  label?: string;
  unit?: string;
  default?: unknown;
  enum?: Record<string, string>;
  min?: number;
  max?: number;
  step?: number;
  help?: string;
  fields?: FieldDef[];
  item_kind?: FieldKind;
  item_labels?: string[];
  min_items?: number;
  max_items?: number;
}

export interface CommandDef {
  id: string;
  section: string;
  group: string;
  name: string;
  type: number;
  command: number;
  type_hex: string;
  command_hex: string;
  response: ResponseKind;
  summary: string;
  fields: FieldDef[];
  example: Record<string, unknown>;
  notes: string[];
  danger: Danger;
  repeat_hz: number | null;
  response_fields: Record<string, string>;
}

export interface ReportDef {
  id: string;
  section: string;
  name: string;
  type: number;
  command: number;
  hz: number;
  root: string;
  summary: string;
  notes: string[];
  type_hex: string;
  command_hex: string;
}

export interface Preset {
  id: string;
  label: string;
  transport: TransportKind;
  host: string;
  port: number;
  note: string;
}

export interface CodeInfo {
  hex: string;
  label: string;
  detail?: string;
}

export interface Enums {
  general_errors: Record<string, CodeInfo>;
  nav_errors: Record<string, CodeInfo>;
  fault_codes: Record<string, CodeInfo>;
  joint_names: string[];
  [name: string]: Record<string, string> | Record<string, CodeInfo> | string[];
}

export interface Catalog {
  protocol: {
    name: string;
    doc_version: string;
    sync: string;
    header_size: number;
    max_frame_asdu: number;
    version: number;
    report_command: number;
  };
  commands: CommandDef[];
  reports: ReportDef[];
  enums: Enums;
  presets: Preset[];
}

export interface HeaderInfo {
  sync: string;
  length: number;
  msg_id: number;
  asdu_format: number;
  asdu_format_name: string;
  seq: number;
  version: number;
  reserved: string;
}

export interface ErrorInfo {
  code: number | null;
  hex: string | null;
  label: string;
  detail: string;
  table: string | null;
  ok: boolean | null;
}

export type PatrolDoc = { PatrolDevice?: { Type?: number; Command?: number; Time?: string; Items?: unknown } };

export interface PacketEvent {
  seq: number;
  kind: "tx" | "rx";
  ts: number;
  dir: "tx" | "rx";
  class: string;
  msg_id: number | null;
  type: number | null;
  command: number | null;
  name: string;
  label?: string | null;
  fmt?: string;
  size: number;
  packets?: number;
  header: HeaderInfo | null;
  expect?: string;
  hex: string;
  text: string;
  data: PatrolDoc | null;
  src?: string;
  report_id?: string | null;
  fragments?: { seq: number; length: number }[];
  complete?: boolean;
  ok?: boolean;
  error?: string | null;
  warnings?: string[];
  request_msg_id?: number | null;
  latency_ms?: number | null;
  response_index?: number | null;
  error_code?: number | null;
  error_info?: ErrorInfo | null;
}

export interface LogEvent {
  seq: number;
  kind: "log";
  ts: number;
  level: "info" | "warn" | "error";
  message: string;
}

export interface TransportInfo {
  kind: TransportKind;
  local: string | null;
  remote: string | null;
  bytes_in: number;
  bytes_out: number;
  protocol?: string;
  cipher?: string;
  peer_cert?: string | null;
  connected_socket?: boolean;
}

export interface RepeatJob {
  id: string;
  name: string;
  type: number;
  command: number;
  hz: number;
  duration: number | null;
  count: number | null;
  sent: number;
  started: number;
  items: unknown;
}

export interface ReportStat {
  id: string;
  name: string;
  count: number;
  expected_hz: number;
  time?: string | null;
  last_ts?: number;
  fragments?: number;
  hz: number;
}

export interface Stats {
  counters: Record<string, number>;
  heartbeat: {
    enabled: boolean;
    hz: number;
    sent: number;
    acked: number;
    missed: number;
    last_latency_ms: number | null;
    last_error_code: number | null;
    last_ack_ts: number | null;
    reporting_active: boolean;
    ack_age_s: number | null;
    link_lost: boolean;
  };
  rates: { type: number | null; command: number | null; name: string; hz: number; count: number }[];
  reports: Record<string, ReportStat>;
  pending: number;
  repeat_jobs: RepeatJob[];
  reassembly: { pending_groups: number; completed_multi: number; incomplete: number };
  uptime_s: number;
  ws_dropped: number;
}

export type SessionState = "disconnected" | "connecting" | "connected" | "error";

export interface SessionSnapshot {
  state: SessionState;
  error: string | null;
  config: {
    transport: { kind: TransportKind; host: string; port: number };
    fmt: "JSON" | "XML";
    heartbeat_enabled: boolean;
    heartbeat_hz: number;
  };
  transport: TransportInfo | null;
  connected_at: number | null;
  stats?: Stats;
}

export interface ResponseInfo {
  msg_id: number;
  latency_ms: number;
  index: number;
  type: number | null;
  command: number | null;
  name: string;
  ok: boolean;
  fmt: string;
  data: PatrolDoc | null;
  items: unknown;
  text: string;
  error: string | null;
  error_code: number | null;
  error_info: ErrorInfo | null;
  header: HeaderInfo;
  hex: string;
  fragments: { seq: number; length: number }[];
  warnings: string[];
  src: string;
}

export type SendStatus = "ok" | "timeout" | "sent" | "sent_no_response_expected" | "cancelled";

export interface SendResult {
  msg_id: number | null;
  type: number | null;
  command: number | null;
  name: string;
  expect: string;
  status: SendStatus;
  response: ResponseInfo | null;
  latency_ms: number | null;
  tx: PacketEvent;
}

export interface Overrides {
  msg_id?: number | null;
  asdu_format?: number | null;
  seq?: number | null;
  version?: number | null;
  reserved_hex?: string | null;
  sync_hex?: string | null;
  length?: number | null;
}

export interface SendBody {
  command_id?: string;
  type?: number;
  command?: number;
  items?: unknown;
  fmt?: "JSON" | "XML";
  body_text?: string;
  raw_hex?: string;
  overrides?: Overrides;
  expect?: "auto" | ResponseKind;
  timeout?: number;
  wait?: boolean;
  label?: string;
}

export interface ConnectConfig {
  transport: TransportKind;
  host: string;
  port: number;
  bind_host: string;
  bind_port: number;
  fmt: "JSON" | "XML";
  heartbeat_enabled: boolean;
  heartbeat_hz: number;
  response_timeout: number;
  connect_timeout: number;
  udp_connect: boolean;
  auto_split: boolean;
  tls: {
    verify: boolean;
    ca_file: string | null;
    cert_file: string | null;
    key_file: string | null;
    ciphers: string | null;
    server_name: string | null;
    dtls_mtu: number;
    compat: boolean;
  };
}

export type CheckLevel = Danger;

export interface SuiteCheck {
  id: string;
  name: string;
  level: CheckLevel;
  section: string;
  description: string;
}

export type CheckStatus = "pass" | "warn" | "fail" | "skip" | "error";

export interface SuiteResult extends SuiteCheck {
  status: CheckStatus;
  summary: string;
  details: unknown;
  duration_ms: number;
}

export interface SuiteReport {
  run_id: string;
  started: number;
  duration_s: number;
  target: SessionSnapshot;
  counts: Record<CheckStatus, number>;
  results: SuiteResult[];
}

export interface DecodedFrame {
  header: HeaderInfo;
  warnings: string[];
  ok: boolean;
  error: string | null;
  fmt: string;
  data: PatrolDoc | null;
  text: string;
  type: number | null;
  command: number | null;
  name: string;
  report_id: string | null;
  error_code: number | null;
  error_info: ErrorInfo | null;
  size: number;
}

export interface DecodeResult {
  size: number;
  frames: DecodedFrame[];
  errors: string[];
  joined: { ok: boolean; error: string | null; data: PatrolDoc | null; name: string } | null;
  hexdump: string;
}

export interface EncodeResult {
  hex: string;
  hexdump: string;
  size: number;
  packets: number;
  body_text: string;
  headers: HeaderInfo[];
}

export type ProbeStatus = "ok" | "no_reply" | "refused" | "unreachable" | "handshake_failed" | "timeout" | "error";

export interface ProbeResult {
  transport: TransportKind;
  port: number;
  status: ProbeStatus;
  detail: string;
  latency_ms: number | null;
  error_code: number | null;
  protocol: string | null;
  cipher: string | null;
  elapsed_ms: number;
}

export interface ProbeReport {
  host: string;
  results: ProbeResult[];
  best: ProbeResult | null;
}
