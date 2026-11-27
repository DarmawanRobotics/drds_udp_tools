"use client";

import { Lock, LockOpen, SlidersHorizontal, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, ApiError } from "@/lib/api";
import { useStore } from "@/lib/store";
import type { TransportKind } from "@/lib/types";
import { Lamp, Labeled, Segmented, Switch } from "./ui/primitives";

const DEFAULT_PORT: Record<TransportKind, number> = { dtls: 30004, tls: 30003, udp: 30000, tcp: 30001 };

export function TopBar() {
  return (
    <header className="flex h-[60px] flex-none items-center gap-3 overflow-hidden border-b border-line bg-panel px-3">
      <Brand />
      <ConnectionBar />
      <div className="ml-auto flex flex-none items-center gap-3">
        <LinkStatus />
        <SafetyControls />
      </div>
    </header>
  );
}

function Brand() {
  return (
    <div className="flex flex-none items-center gap-2.5 pr-1">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/ezra-robotics-logo.svg" alt="EZRA Robotics" width={42} height={40} className="h-10 w-auto rounded-[3px]" />
      <div className="leading-tight whitespace-nowrap">
        <div className="font-cond text-[17px] font-semibold">UDP Debugger</div>
        <div className="hidden text-[11.5px] text-muted 2xl:block">Inspection protocol V1.0.3</div>
      </div>
    </div>
  );
}

export function useConnectActions() {
  const toast = useStore((s) => s.toast);
  const setSession = useStore((s) => s.setSession);
  const [busy, setBusy] = useState(false);
  const connect = async () => {
    setBusy(true);
    try {
      const snap = await api.connect(useStore.getState().conn);
      setSession(snap);
      const t = snap.transport;
      toast("info", `Connected over ${t?.kind.toUpperCase()} ${t?.local ?? ""} → ${t?.remote ?? ""}${t?.protocol ? ` (${t.protocol})` : ""}`);
    } catch (e) {
      toast("error", e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const disconnect = async () => {
    setBusy(true);
    try {
      setSession(await api.disconnect());
    } catch (e) {
      toast("error", String(e));
    } finally {
      setBusy(false);
    }
  };
  return { connect, disconnect, busy };
}

function ConnectionBar() {
  const conn = useStore((s) => s.conn);
  const setConn = useStore((s) => s.setConn);
  const presets = useStore((s) => s.catalog?.presets ?? []);
  const state = useStore((s) => s.session?.state ?? "disconnected");
  const error = useStore((s) => s.session?.error);
  const { connect, disconnect, busy } = useConnectActions();
  const live = state === "connected" || state === "connecting";
  const [showAdv, setShowAdv] = useState(false);
  const gearRef = useRef<HTMLButtonElement>(null);

  const setTransport = (t: TransportKind) => {
    const wasDefault = Object.values(DEFAULT_PORT).includes(conn.port);
    setConn({ transport: t, port: wasDefault ? DEFAULT_PORT[t] : conn.port });
  };

  return (
    <form
      className="flex min-w-0 flex-none items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (live) disconnect();
        else connect();
      }}
    >
      <select
        aria-label="Target preset"
        className="field w-[104px] text-[13px]"
        disabled={live}
        value=""
        onChange={(e) => {
          const p = presets.find((x) => x.id === e.target.value);
          if (p) setConn({ transport: p.transport, host: p.host, port: p.port });
        }}
      >
        <option value="">Preset…</option>
        {presets.map((p) => (
          <option key={p.id} value={p.id} title={p.note}>
            {p.label}
          </option>
        ))}
      </select>
      <Segmented
        label="Transport"
        value={conn.transport}
        disabled={live}
        onChange={setTransport}
        options={[
          { value: "dtls", label: "DTLS", title: "UDP + encrypted (robot default, port 30004)" },
          { value: "udp", label: "UDP", title: "Plain UDP — only after encryption is disabled on the robot" },
          { value: "tls", label: "TLS", title: "TCP + encrypted (port 30003)" },
          { value: "tcp", label: "TCP", title: "Plain TCP" },
        ]}
      />
      <div className="flex items-center">
        <input
          aria-label="Robot host"
          className="field w-[124px] rounded-r-none font-mono text-[12.5px]"
          value={conn.host}
          disabled={live}
          spellCheck={false}
          onChange={(e) => setConn({ host: e.target.value })}
        />
        <input
          aria-label="Port"
          className="field -ml-px w-[80px] rounded-l-none font-mono text-[12.5px]"
          type="number"
          min={1}
          max={65535}
          value={conn.port}
          disabled={live}
          onChange={(e) => setConn({ port: Number(e.target.value) })}
        />
      </div>
      <Segmented
        label="ASDU format"
        value={conn.fmt}
        disabled={live}
        onChange={(v) => setConn({ fmt: v })}
        options={[
          { value: "JSON", label: "JSON" },
          { value: "XML", label: "XML" },
        ]}
      />
      <div className="relative">
        <button
          ref={gearRef}
          type="button"
          className="btn btn-ghost w-8 px-0"
          aria-label="Connection settings"
          aria-expanded={showAdv}
          onClick={() => setShowAdv(!showAdv)}
        >
          <SlidersHorizontal size={16} />
        </button>
        {showAdv ? <AdvancedSettings anchor={gearRef.current} onClose={() => setShowAdv(false)} /> : null}
      </div>
      <button type="submit" className={`btn min-w-[100px] ${live ? "" : "btn-primary"}`} disabled={busy}>
        {busy ? (state === "connected" ? "Disconnecting…" : "Connecting…") : live ? "Disconnect" : "Connect"}
      </button>
      {state === "error" && error ? (
        <span className="hidden max-w-[220px] truncate text-[12.5px] text-bad 2xl:inline" title={error}>
          {error}
        </span>
      ) : null}
    </form>
  );
}

function AdvancedSettings({ anchor, onClose }: { anchor: HTMLElement | null; onClose: () => void }) {
  const conn = useStore((s) => s.conn);
  const setConn = useStore((s) => s.setConn);
  const live = useStore((s) => s.session?.state === "connected");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node;
      if (ref.current && !ref.current.contains(t) && !anchor?.contains(t)) onClose();
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose, anchor]);
  const num = (v: string, d: number) => (v === "" || Number.isNaN(Number(v)) ? d : Number(v));
  const tls = conn.tls;
  // portal + fixed position: the header clips overflow, so the panel must live outside it
  const r = anchor?.getBoundingClientRect();
  const width = 440;
  const left = Math.max(8, Math.min((r?.left ?? 8) - 8, window.innerWidth - width - 8));
  const top = (r?.bottom ?? 52) + 8;
  return createPortal(
    <div ref={ref} role="dialog" aria-label="Connection settings" style={{ left, top, width }}
      className="panel fixed z-50 max-h-[calc(100vh-80px)] overflow-y-auto p-4 shadow-xl">
      <div className="mb-3 font-cond text-[16px] font-semibold">Connection settings</div>
      <div className="grid grid-cols-2 gap-3">
        <Labeled label="Heartbeat rate (Hz)" hint="Docs: at least 1 Hz; reports stop after 2 s of silence.">
          <input className="field" type="number" step={0.5} min={0.2} value={conn.heartbeat_hz}
            onChange={(e) => setConn({ heartbeat_hz: num(e.target.value, 2) })} />
        </Labeled>
        <Labeled label="Response timeout (s)">
          <input className="field" type="number" step={0.1} min={0.1} value={conn.response_timeout}
            onChange={(e) => setConn({ response_timeout: num(e.target.value, 1.5) })} />
        </Labeled>
        <Labeled label="Connect / handshake timeout (s)">
          <input className="field" type="number" step={0.5} min={0.5} value={conn.connect_timeout} disabled={live}
            onChange={(e) => setConn({ connect_timeout: num(e.target.value, 5) })} />
        </Labeled>
        <Labeled label="Local port" hint="0 = random. Reports go back to this port.">
          <input className="field" type="number" min={0} max={65535} value={conn.bind_port} disabled={live}
            onChange={(e) => setConn({ bind_port: num(e.target.value, 0) })} />
        </Labeled>
      </div>
      <div className="mt-3 flex flex-col gap-2">
        <Switch checked={conn.heartbeat_enabled} onChange={(v) => setConn({ heartbeat_enabled: v })} label="Send heartbeat automatically" disabled={live} />
        <Switch checked={conn.udp_connect} onChange={(v) => setConn({ udp_connect: v })} disabled={live}
          label="Connected UDP socket (shows ICMP port-unreachable errors; turn off to accept replies from any port)" />
        <Switch checked={conn.auto_split} onChange={(v) => setConn({ auto_split: v })} label="Split ASDU > 1000 B into sub-packets" />
      </div>
      <div className="mt-4 border-t border-line pt-3">
        <div className="mb-2 text-[13px] font-semibold">TLS / DTLS</div>
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2 flex flex-col gap-2">
            <Switch checked={tls.verify} disabled={live} onChange={(v) => setConn({ tls: { ...tls, verify: v } })}
              label="Verify the robot certificate (off = accept self-signed)" />
            <Switch checked={tls.compat} disabled={live} onChange={(v) => setConn({ tls: { ...tls, compat: v } })}
              label="Compat mode: allow old TLS/DTLS versions and weak ciphers" />
          </div>
          {(["ca_file", "cert_file", "key_file", "server_name"] as const).map((k) => (
            <Labeled key={k} label={{ ca_file: "CA file", cert_file: "Client certificate", key_file: "Client key", server_name: "Server name (SNI)" }[k]}>
              <input className="field font-mono text-[12px]" placeholder={k === "server_name" ? "optional" : "/path/on/this/mac.pem"}
                value={tls[k] ?? ""} disabled={live} spellCheck={false}
                onChange={(e) => setConn({ tls: { ...tls, [k]: e.target.value || null } })} />
            </Labeled>
          ))}
          <Labeled label="DTLS MTU">
            <input className="field" type="number" min={256} max={9000} value={tls.dtls_mtu} disabled={live}
              onChange={(e) => setConn({ tls: { ...tls, dtls_mtu: num(e.target.value, 1400) } })} />
          </Labeled>
          <Labeled label="Cipher list">
            <input className="field font-mono text-[12px]" placeholder="OpenSSL default" value={tls.ciphers ?? ""} disabled={live}
              onChange={(e) => setConn({ tls: { ...tls, ciphers: e.target.value || null } })} />
          </Labeled>
        </div>
      </div>
    </div>,
    document.body,
  );
}

function LinkStatus() {
  const stats = useStore((s) => s.stats);
  const state = useStore((s) => s.session?.state);
  const t = useStore((s) => s.session?.transport);
  const beat = useStore((s) => s.hbBeat);
  const ws = useStore((s) => s.ws);
  if (ws !== "open") {
    return (
      <div className="flex items-center gap-2 text-[12.5px] whitespace-nowrap text-muted">
        <Lamp on="bad" title="GUI ↔ backend socket closed" /> Backend {ws}
      </div>
    );
  }
  if (state !== "connected" || !stats) {
    return <div className="text-[12.5px] whitespace-nowrap text-muted">Not connected</div>;
  }
  const hb = stats.heartbeat;
  const c = stats.counters;
  if (hb.link_lost) {
    return (
      <div className="flex items-center gap-2 text-[12.5px] font-semibold whitespace-nowrap text-bad"
        title="Heartbeats go out but the robot stopped answering. See Traffic → Engine log.">
        <Lamp on="bad" /> Link lost {hb.ack_age_s != null ? `· ${hb.ack_age_s.toFixed(0)} s` : "· no ACK yet"}
      </div>
    );
  }
  return (
    <div className="flex items-center gap-3 text-[12.5px] whitespace-nowrap">
      <div className="flex items-center gap-2" title={`Heartbeat ${hb.enabled ? "on" : "off"} — sent ${hb.sent}, acked ${hb.acked}, missed ${hb.missed}`}>
        <Lamp on={hb.enabled ? (hb.missed > 0 && hb.acked === 0 ? "bad" : "ok") : false} beat={beat} />
        <span>
          HB <span className="text-muted">{hb.acked}/{hb.sent}</span>
        </span>
      </div>
      <div className="flex items-center gap-2" title="Robot pushes status reports while it receives heartbeats">
        <Lamp on={hb.reporting_active ? "ok" : "warn"} />
        <span>{hb.reporting_active ? "Reports" : "No reports"}</span>
      </div>
      <div className="hidden text-muted 2xl:block" title={t ? `${t.kind.toUpperCase()} ${t.local} → ${t.remote}` : ""}>
        <span className="text-tx">↑{c.tx_packets}</span> <span className="text-rx">↓{c.rx_packets}</span>
        {t?.protocol ? <span className="ml-2">{t.protocol}</span> : null}
      </div>
    </div>
  );
}

function SafetyControls() {
  const armed = useStore((s) => s.armed);
  const setArmed = useStore((s) => s.setArmed);
  const toast = useStore((s) => s.toast);
  const live = useStore((s) => s.session?.state === "connected");
  const jobs = useStore((s) => s.repeatJobs.length);

  const stop = async () => {
    try {
      const r = await api.stop();
      toast("warn", `Stopped ${r.stopped_jobs} stream(s); sent zero axis + zero velocity + cancel navigation.`);
    } catch (e) {
      toast("error", String(e));
    }
  };
  const estop = async () => {
    try {
      const r = await api.estop();
      toast("error", `E-STOP sent (soft emergency stop, MotionParam −2): ${r.estop}`);
    } catch (e) {
      toast("error", e instanceof ApiError ? e.message : String(e));
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (e.key === "Escape" && !["INPUT", "TEXTAREA", "SELECT"].includes(tag) && live) stop();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live]);

  return (
    <div className="flex items-center gap-2 border-l border-line pl-3">
      <button
        type="button"
        onClick={() => setArmed(!armed)}
        aria-pressed={armed}
        title="Commands that move the robot are blocked until motion is armed"
        className={`flex h-9 items-center gap-2 rounded-md border px-1.5 text-[13px] font-semibold whitespace-nowrap ${
          armed ? "hazard border-ink text-ink" : "border-line-strong bg-well text-muted"
        }`}
      >
        <span className={`flex items-center gap-1.5 rounded px-1.5 py-0.5 ${armed ? "bg-signal text-signal-ink" : ""}`}>
          {armed ? <LockOpen size={15} /> : <Lock size={15} />}
          {armed ? "Armed" : "Locked"}
        </span>
      </button>
      <button type="button" className="btn h-9" onClick={stop} disabled={!live} title="Stop streams, send zero velocity and cancel navigation (Esc)">
        <Square size={14} fill="currentColor" /> Stop{jobs ? ` (${jobs})` : ""}
      </button>
      <button
        type="button"
        onClick={estop}
        disabled={!live}
        title="Soft emergency stop: stops everything, then MotionParam −2 (joint damping)"
        className="group flex h-11 w-11 flex-none items-center justify-center rounded-full bg-signal shadow-[0_1px_2px_rgb(0_0_0/0.3)] disabled:opacity-40"
      >
        <span className="flex h-9 w-9 items-center justify-center rounded-full bg-estop text-[9.5px] font-bold tracking-wide text-white shadow-[inset_0_-3px_0_rgb(0_0_0/0.25),0_2px_3px_rgb(0_0_0/0.35)] group-active:translate-y-px group-active:shadow-[inset_0_-1px_0_rgb(0_0_0/0.25)]">
          E-STOP
        </span>
      </button>
    </div>
  );
}
