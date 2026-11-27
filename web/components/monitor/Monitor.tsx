"use client";

import { Gauge } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { enumLabel, faultLabel, fmtNum, hex16 } from "@/lib/format";
import { useStore } from "@/lib/store";
import type { Enums } from "@/lib/types";
import { Chip, Empty, Lamp } from "../ui/primitives";

type Obj = Record<string, unknown>;
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const deg = (rad: unknown) => (num(rad) === null ? null : ((num(rad) as number) * 180) / Math.PI);

function useNow(ms = 500) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now() / 1000), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

function Instrument({ id, title, section, children, className = "", tools }: {
  id?: string; title: string; section?: string; children: ReactNode; className?: string; tools?: ReactNode;
}) {
  const stat = useStore((s) => (id ? s.stats?.reports?.[id] : undefined));
  const slot = useStore((s) => (id ? s.reports[id] : undefined));
  const expected = useStore((s) => s.catalog?.reports.find((r) => r.id === id)?.hz);
  const now = useNow();
  const age = slot ? Math.max(0, now - slot.ts) : null;
  const hz = stat?.hz ?? 0;
  const ok = expected ? hz / expected > 0.6 && hz / expected < 1.5 : true;
  return (
    <section className={`panel flex min-h-0 flex-col ${className}`}>
      <header className="flex items-center gap-2 border-b border-line px-3 py-2">
        <h3 className="font-cond text-[16px] font-semibold">{title}</h3>
        {section ? <span className="text-[12px] text-faint">§{section}</span> : null}
        <div className="ml-auto flex items-center gap-2 text-[12px] text-muted">
          {tools}
          {id ? (
            <>
              {slot && slot.fragments > 1 ? <Chip>{slot.fragments} packets</Chip> : null}
              <span title="measured / documented rate" className={ok ? "" : "text-warn"}>
                {hz.toFixed(1)}/{expected} Hz
              </span>
              <Lamp on={age === null ? false : age < 2.5 ? (ok ? "ok" : "warn") : "bad"} title={age === null ? "no data" : `last ${age.toFixed(1)} s ago`} />
            </>
          ) : null}
        </div>
      </header>
      <div className="min-h-0 flex-1 p-3">{children}</div>
    </section>
  );
}

function Readout({ label, value, raw, tone }: { label: string; value: ReactNode; raw?: ReactNode; tone?: "ok" | "warn" | "bad" }) {
  const color = tone === "bad" ? "text-bad" : tone === "warn" ? "text-warn" : tone === "ok" ? "text-lamp" : "text-ink";
  return (
    <div className="min-w-0 border-l border-line pl-3 first:border-l-0 first:pl-0">
      <div className="text-[12px] text-muted">{label}</div>
      <div className={`truncate font-cond text-[22px] leading-tight font-semibold ${color}`} title={typeof value === "string" ? value : undefined}>{value ?? "—"}</div>
      {raw !== undefined ? <div className="font-mono text-[10.5px] text-faint">{raw}</div> : null}
    </div>
  );
}

// ------------------------------------------------------------------ strip
function StatusStrip({ e }: { e?: Enums }) {
  const basic = useStore((s) => (s.reports.basic?.items?.BasicStatus as Obj) ?? null);
  const battery = useStore((s) => ((s.reports.device?.items?.BatteryList as Obj[]) ?? [])[0] ?? null);
  const ms = basic?.MotionState;
  return (
    <Instrument id="basic" title="Robot" section="1.3.1.1" className="col-span-12">
      {basic ? (
        <div className="grid grid-cols-2 gap-y-3 sm:grid-cols-4 xl:grid-cols-8">
          <Readout label="Motion state" value={enumLabel(e, "motion_state", ms) ?? String(ms)} raw={String(ms)}
            tone={ms === -2 ? "bad" : ms === 1 ? "ok" : undefined} />
          <Readout label="Gait" value={enumLabel(e, "gait", basic.Gait) ?? String(basic.Gait)} raw={hex16(num(basic.Gait))} />
          <Readout label="Usage mode" value={enumLabel(e, "usage_mode", basic.ControlUsageMode)} raw={String(basic.ControlUsageMode)} />
          <Readout label="Hard e-stop" value={basic.HES ? "Triggered" : "Released"} tone={basic.HES ? "bad" : "ok"} raw={String(basic.HES)} />
          <Readout label="Sleep" value={typeof basic.Sleep === "boolean" ? (basic.Sleep ? "Sleeping" : "Awake") : enumLabel(e, "sleep_state", basic.Sleep)} raw={String(basic.Sleep)} />
          <Readout label="Charge" value={enumLabel(e, "charge_state", basic.Charge) ?? String(basic.Charge)} raw={String(basic.Charge)} />
          <Readout label="Model / version" value={`${basic.Model ?? "?"} ${basic.Version ?? ""}`} raw={`power mgmt ${basic.PowerManagement}`} />
          <Readout label="Battery" value={battery ? `${battery.BatteryLevel}%` : "—"} raw={battery ? `${fmtNum(battery.Voltage, 1)} V · ${fmtNum(battery.battery_temperature, 1)} °C` : undefined}
            tone={battery && num(battery.BatteryLevel) !== null && (battery.BatteryLevel as number) < 20 ? "bad" : undefined} />
        </div>
      ) : (
        <p className="text-[13px] text-muted">Waiting for Basic Status (2 Hz). Reports start after the robot receives heartbeats.</p>
      )}
    </Instrument>
  );
}

// ----------------------------------------------------------------- motion
function Attitude({ roll, pitch }: { roll: number; pitch: number }) {
  const r = (roll * 180) / Math.PI;
  const p = Math.max(-40, Math.min(40, (pitch * 180) / Math.PI)) * 1.5;
  return (
    <svg viewBox="-60 -60 120 120" className="h-[120px] w-[120px]" role="img" aria-label={`roll ${r.toFixed(1)}°, pitch ${((pitch * 180) / Math.PI).toFixed(1)}°`}>
      <defs>
        <clipPath id="att"><circle r="56" /></clipPath>
      </defs>
      <g clipPath="url(#att)">
        <g transform={`rotate(${-r}) translate(0 ${p})`}>
          <rect x="-120" y="-120" width="240" height="120" fill="color-mix(in oklab, var(--tx) 28%, var(--panel))" />
          <rect x="-120" y="0" width="240" height="120" fill="color-mix(in oklab, var(--rx) 26%, var(--panel))" />
          <line x1="-120" x2="120" y1="0" y2="0" stroke="var(--ink)" strokeWidth="1.2" />
          {[-20, -10, 10, 20].map((d) => (
            <line key={d} x1={-10 + Math.abs(d) / 4} x2={10 - Math.abs(d) / 4} y1={-d * 1.5} y2={-d * 1.5} stroke="var(--ink)" strokeOpacity=".5" strokeWidth="1" />
          ))}
        </g>
      </g>
      <circle r="56" fill="none" stroke="var(--line-strong)" strokeWidth="2" />
      <path d="M-30 0H-10L-5 5H5L10 0H30" fill="none" stroke="var(--signal)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
      <circle r="2.5" fill="var(--signal)" />
    </svg>
  );
}

function Heading({ yaw }: { yaw: number }) {
  const d = (yaw * 180) / Math.PI;
  return (
    <svg viewBox="-60 -60 120 120" className="h-[120px] w-[120px]" role="img" aria-label={`yaw ${d.toFixed(1)}°`}>
      <circle r="56" fill="var(--well)" stroke="var(--line-strong)" strokeWidth="2" />
      {Array.from({ length: 36 }, (_, i) => (
        <line key={i} y1="-56" y2={i % 9 === 0 ? "-46" : "-51"} stroke="var(--muted)" strokeWidth={i % 9 === 0 ? 1.6 : 0.8} transform={`rotate(${i * 10})`} />
      ))}
      {[["0°", 0], ["90°", -90], ["180°", 180], ["−90°", 90]].map(([t, a]) => (
        <text key={t as string} x={Math.sin(((a as number) * Math.PI) / 180) * 36} y={-Math.cos(((a as number) * Math.PI) / 180) * 36 + 3.5}
          textAnchor="middle" fontSize="9" fill="var(--muted)">{t}</text>
      ))}
      <g transform={`rotate(${-d})`}>
        <path d="M0 -40 L8 6 L0 0 L-8 6Z" fill="var(--tx)" />
      </g>
    </svg>
  );
}

function SignedBar({ label, value, max, unit }: { label: string; value: number | null; max: number; unit: string }) {
  const v = value ?? 0;
  const pct = Math.max(-1, Math.min(1, v / max)) * 50;
  return (
    <div className="grid grid-cols-[76px_1fr_92px] items-center gap-2 text-[12.5px]">
      <span className="text-muted">{label}</span>
      <div className="relative h-2 rounded-full bg-well">
        <span className="absolute top-[-3px] left-1/2 h-[14px] w-px bg-line-strong" />
        <span className="absolute top-0 h-2 rounded-full bg-tx" style={{ left: pct < 0 ? `${50 + pct}%` : "50%", width: `${Math.abs(pct)}%` }} />
      </div>
      <span className="text-right font-mono text-[11.5px] whitespace-nowrap">{value === null ? "—" : `${v.toFixed(2)} ${unit}`}</span>
    </div>
  );
}

function MotionInstrument() {
  const m = useStore((s) => (s.reports.motion?.items?.MotionStatus as Obj) ?? null);
  return (
    <Instrument id="motion" title="Motion" section="1.3.1.2" className="col-span-12 lg:col-span-4">
      {m ? (
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-around">
            <div className="text-center">
              <Attitude roll={num(m.Roll) ?? 0} pitch={num(m.Pitch) ?? 0} />
              <div className="font-mono text-[11px] text-muted">R {fmtNum(deg(m.Roll), 1)}° P {fmtNum(deg(m.Pitch), 1)}°</div>
            </div>
            <div className="text-center">
              <Heading yaw={num(m.Yaw) ?? 0} />
              <div className="font-mono text-[11px] text-muted">Yaw {fmtNum(deg(m.Yaw), 1)}°</div>
            </div>
          </div>
          <SignedBar label="Linear X" value={num(m.LinearX)} max={1.67} unit="m/s" />
          <SignedBar label="Linear Y" value={num(m.LinearY)} max={0.4} unit="m/s" />
          <SignedBar label="Angular Z" value={num(m.AngularZ)} max={1.0} unit="rad/s" />
          <div className="grid grid-cols-3 gap-2 border-t border-line pt-2 text-[12.5px]">
            <Mini k="Height" v={`${fmtNum(m.Height, 3)} m`} />
            <Mini k="Payload" v={`${fmtNum(m.Payload, 1)} kg`} />
            <Mini k="Range left" v={`${fmtNum(m.RemainMile, 2)} km`} />
            <Mini k="Acc x/y/z" v={`${fmtNum(m.AccX, 2)} ${fmtNum(m.AccY, 2)} ${fmtNum(m.AccZ, 2)}`} mono />
            <Mini k="ω x/y/z" v={`${fmtNum(m.OmegaX, 3)} ${fmtNum(m.OmegaY, 3)} ${fmtNum(m.OmegaZ, 3)}`} mono />
            <Mini k="State / gait" v={`${m.MotionState} / ${hex16(num(m.Gait))}`} mono />
          </div>
        </div>
      ) : (
        <Waiting what="Motion Control Status (10 Hz)" />
      )}
    </Instrument>
  );
}

function Mini({ k, v, mono }: { k: string; v: ReactNode; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <div className="text-[11.5px] text-muted">{k}</div>
      <div className={`truncate ${mono ? "font-mono text-[11px]" : "font-medium"}`}>{v}</div>
    </div>
  );
}

function Waiting({ what }: { what: string }) {
  return <p className="text-[13px] text-muted">Waiting for {what}.</p>;
}

// ----------------------------------------------------------------- joints
const LEGS = [
  ["LF", "Left front"],
  ["RF", "Right front"],
  ["LB", "Left back"],
  ["RB", "Right back"],
];
const JOINTS = ["Hip X", "Hip Y", "Knee", "Wheel"];

function tempTone(t: number | null) {
  if (t === null) return "text-faint";
  if (t >= 70) return "text-bad";
  if (t >= 55) return "text-warn";
  return "text-muted";
}

function JointsInstrument() {
  const joints = useStore((s) => ((s.reports.motion?.items?.MotorStatus as Obj)?.Joint as number[]) ?? null);
  const temps = useStore((s) => (s.reports.device?.items?.DeviceTemperature as Obj) ?? null);
  const motor = (temps?.Motor as number[]) ?? [];
  const driver = (temps?.Driver as number[]) ?? [];
  return (
    <Instrument title="Joints" section="1.3.1.2 + 1.3.1.3" className="col-span-12 lg:col-span-5"
      tools={<span className="text-faint">angle · motor / driver °C</span>}>
      {joints?.length ? (
        <table className="w-full table-fixed border-collapse text-[12.5px]">
          <thead>
            <tr className="text-muted">
              <th className="w-[92px] pb-1.5 text-left font-medium">Leg</th>
              {JOINTS.map((j) => (
                <th key={j} className="pb-1.5 text-left font-medium">{j}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {LEGS.map(([code, name], leg) => (
              <tr key={code} className="border-t border-line/70">
                <td className="py-1.5 font-medium" title={name}>{name}</td>
                {JOINTS.map((_, j) => {
                  const i = leg * 4 + j;
                  const a = joints[i];
                  const mt = num(motor[i]);
                  const dt = num(driver[i]);
                  return (
                    <td key={j} className="py-1.5 align-top">
                      <div className="flex items-baseline gap-1">
                        <span className="font-cond text-[17px] font-semibold">{num(a) === null ? "—" : ((a * 180) / Math.PI).toFixed(1)}</span>
                        <span className="text-[11px] text-faint">°</span>
                      </div>
                      <div className="font-mono text-[10.5px]">
                        <span className={tempTone(mt)}>{mt === null ? "–" : mt.toFixed(0)}</span>
                        <span className="text-faint"> / </span>
                        <span className={tempTone(dt)}>{dt === null ? "–" : dt.toFixed(0)}</span>
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <Waiting what="joint angles" />
      )}
    </Instrument>
  );
}

// ------------------------------------------------------------ power + cpu
function CpuBlock({ name, c }: { name: string; c: Obj | undefined }) {
  if (!c || !Array.isArray(c.Util)) return <div className="text-[12.5px] text-muted">{name}: no data</div>;
  const util = c.Util as number[];
  return (
    <div className="min-w-0">
      <div className="mb-1 flex items-baseline gap-2 text-[12.5px]">
        <span className="font-semibold">{name}</span>
        <span className="text-faint">{String(c.SocId ?? "")}</span>
        <span className="ml-auto text-muted">{String(c.AvgUtil)}% · {String(c.PackageTemp)} °C</span>
      </div>
      <div className="flex h-12 items-end gap-[3px] rounded bg-well p-1">
        {util.map((u, i) => (
          <span key={i} title={`core ${i}: ${u}% ${Array.isArray(c.Temps) ? `${(c.Temps as number[])[i]} °C` : ""}`}
            className="flex-1 rounded-sm" style={{ height: `${Math.max(4, u)}%`, background: u > 85 ? "var(--estop)" : u > 60 ? "var(--signal)" : "var(--tx)" }} />
        ))}
      </div>
      <div className="mt-1 truncate text-[11px] text-faint">{Array.isArray(c.GovPolicy) ? String((c.GovPolicy as string[])[0]) : ""}</div>
    </div>
  );
}

function PowerInstrument({ e }: { e?: Enums }) {
  const d = useStore((s) => s.reports.device?.items ?? null);
  const b = ((d?.BatteryList as Obj[]) ?? [])[0];
  const cpu = (d?.CPU as Obj) ?? {};
  const level = num(b?.BatteryLevel);
  return (
    <Instrument id="device" title="Power & compute" section="1.3.1.3" className="col-span-12 lg:col-span-3">
      {d ? (
        <div className="flex flex-col gap-3">
          <div>
            <div className="flex items-baseline gap-2">
              <span className="font-cond text-[30px] leading-none font-semibold">{level ?? "—"}%</span>
              <span className="text-[12.5px] text-muted">{b?.charge ? "charging" : "on battery"}</span>
            </div>
            <div className="mt-1.5 h-2.5 rounded-full bg-well">
              <div className="h-2.5 rounded-full" style={{ width: `${level ?? 0}%`, background: (level ?? 0) < 20 ? "var(--estop)" : "var(--lamp)" }} />
            </div>
            <div className="mt-1 text-[12px] text-muted">
              {fmtNum(b?.Voltage, 2)} V · {fmtNum(b?.battery_temperature, 1)} °C · {String(b?.serial ?? "")}
            </div>
          </div>
          <CpuBlock name="Locomotion host" c={cpu.AOS as Obj} />
          <CpuBlock name="Navigation host" c={cpu.NOS as Obj} />
          <div className="flex gap-4 border-t border-line pt-2 text-[12.5px]">
            {(["Lidar", "Video"] as const).map((k) => {
              const v = (d.DevEnable as Obj)?.[k];
              return (
                <span key={k} className="flex items-center gap-1.5">
                  <Lamp on={v === 1 ? "ok" : v === 2 ? "warn" : "bad"} />
                  {k} {enumLabel(e, k === "Lidar" ? "lidar_enable" : "video_enable", v)?.toLowerCase()}
                </span>
              );
            })}
          </div>
        </div>
      ) : (
        <Waiting what="Device State (2 Hz)" />
      )}
    </Instrument>
  );
}

// -------------------------------------------------------------- navigation
function Trail() {
  const trail = useStore((s) => s.trail);
  if (trail.length < 1) return <div className="flex h-[200px] items-center justify-center text-[12.5px] text-muted">Pose trail appears with Navigation Status.</div>;
  const xs = trail.map((p) => p.x);
  const ys = trail.map((p) => p.y);
  const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
  const cy = (Math.min(...ys) + Math.max(...ys)) / 2;
  const span = Math.max(2, Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)) * 1.25;
  const W = 300, H = 200;
  const k = Math.min(W, H) / span;
  const P = (x: number, y: number) => [W / 2 + (x - cx) * k, H / 2 - (y - cy) * k];
  const last = trail[trail.length - 1];
  const [lx, ly] = P(last.x, last.y);
  const grid = Math.pow(10, Math.floor(Math.log10(span / 2)));
  const lines = [];
  for (let g = Math.floor((cx - span) / grid) * grid; g <= cx + span; g += grid) {
    const [gx] = P(g, 0);
    lines.push(<line key={`x${g}`} x1={gx} x2={gx} y1={0} y2={H} stroke="var(--line)" strokeWidth="0.6" />);
  }
  for (let g = Math.floor((cy - span) / grid) * grid; g <= cy + span; g += grid) {
    const [, gy] = P(0, g);
    lines.push(<line key={`y${g}`} y1={gy} y2={gy} x1={0} x2={W} stroke="var(--line)" strokeWidth="0.6" />);
  }
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-[200px] w-full rounded bg-well" role="img" aria-label="Pose trail in map frame">
      {lines}
      <polyline fill="none" stroke="var(--tx)" strokeWidth="1.6" strokeLinejoin="round" points={trail.map((p) => P(p.x, p.y).join(",")).join(" ")} />
      <g transform={`translate(${lx} ${ly}) rotate(${(-last.yaw * 180) / Math.PI})`}>
        <path d="M9 0 L-6 5 L-3 0 L-6 -5Z" fill="var(--signal)" stroke="var(--ink)" strokeWidth="0.8" />
      </g>
      <text x={6} y={H - 6} fontSize="9" fill="var(--muted)">grid {grid} m · {trail.length} pts</text>
    </svg>
  );
}

function NavInstrument({ e }: { e?: Enums }) {
  const n = useStore((s) => s.reports.navigation?.items ?? null);
  const ns = (n?.NavStatus as Obj) ?? null;
  const ls = (n?.LocationStatus as Obj) ?? null;
  const conf = num(ls?.Confidence);
  const code = num(ns?.ErrorCode);
  const codeInfo = code === null ? null : e?.general_errors[String(code)] ?? e?.nav_errors[String(code)];
  return (
    <Instrument id="navigation" title="Navigation" section="1.3.1.5" className="col-span-12 lg:col-span-5">
      {n ? (
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-[1fr_300px]">
          <div className="flex flex-col gap-2 text-[12.5px]">
            <div className="flex items-baseline gap-2">
              <span className="font-cond text-[22px] font-semibold">{enumLabel(e, "nav_status", ns?.Status) ?? String(ns?.Status)}</span>
              <span className="text-muted">point {String(ns?.Value)}</span>
            </div>
            <div className={code && code !== 0x2300 ? "text-bad" : "text-muted"}>
              Error code {code === null ? "—" : `${hex16(code)} ${codeInfo?.label ?? ""}`}
            </div>
            <div className="text-muted">
              Task “{String(ns?.Name ?? "")}” · loops {String(ns?.LoopCnt)} · remaining {String(ns?.RemainingCnt)}
            </div>
            <div className="mt-1 grid grid-cols-3 gap-2 border-t border-line pt-2">
              <Mini k="X" v={`${fmtNum(ls?.PosX, 3)} m`} />
              <Mini k="Y" v={`${fmtNum(ls?.PosY, 3)} m`} />
              <Mini k="Yaw" v={`${fmtNum(deg(ls?.Yaw), 1)}°`} />
              <Mini k="Location" v={enumLabel(e, "location", ls?.Location) ?? String(ls?.Location)} />
              <Mini k="Relocation" v={enumLabel(e, "relocation", ls?.Relocation) ?? String(ls?.Relocation)} />
              <Mini k="Z" v={`${fmtNum(ls?.PosZ, 3)} m`} />
            </div>
            <div>
              <div className="mb-1 flex justify-between text-muted">
                <span>Localization confidence</span>
                <span>{conf === null ? "—" : conf.toFixed(2)}</span>
              </div>
              <div className="h-2 rounded-full bg-well">
                <div className="h-2 rounded-full" style={{ width: `${(conf ?? 0) * 100}%`, background: (conf ?? 0) < 0.5 ? "var(--signal)" : "var(--lamp)" }} />
              </div>
            </div>
          </div>
          <Trail />
        </div>
      ) : (
        <Waiting what="Navigation Status (1 Hz)" />
      )}
    </Instrument>
  );
}

// ------------------------------------------------------------------ faults
function FaultsInstrument({ e }: { e?: Enums }) {
  const list = useStore((s) => (s.reports.abnormal?.items?.ErrorList as Obj[] | Obj | undefined) ?? null);
  const faults = Array.isArray(list) ? list : list ? [list] : [];
  const slot = useStore((s) => s.reports.abnormal);
  return (
    <Instrument id="abnormal" title="Faults" section="1.3.1.4" className="col-span-12 lg:col-span-4">
      {!slot ? (
        <Waiting what="Abnormal Status (2 Hz)" />
      ) : faults.length ? (
        <ul className="flex flex-col gap-2">
          {faults.map((f, i) => {
            const sev = Array.isArray(f.Severities) ? Math.max(...(f.Severities as number[])) : num(f.Severities) ?? 0;
            const fl = faultLabel(e, f.Code);
            const ts = (f.Timestamp as Obj)?.Sec;
            return (
              <li key={i} className="rounded-md border border-line p-2 text-[12.5px]">
                <div className="flex items-center gap-2">
                  <Chip tone={sev >= 4 ? "bad" : "warn"}>{enumLabel(e, "severity", sev) ?? sev}</Chip>
                  <span className="font-semibold">{String(f.Name)}</span>
                  <span className="ml-auto font-mono text-[11px] text-muted">{hex16(num(f.Code))}</span>
                </div>
                <div className="mt-1 text-muted">
                  {fl?.label ?? "Code not in the docs table"} · resources {JSON.stringify(f.Resources)} · {f.Type === 2 ? "cleared" : "active"}
                </div>
                <div className="text-faint">
                  {Array.isArray(f.Source) ? (f.Source as string[]).join(", ") : String(f.Source ?? "")}
                  {typeof ts === "number" ? ` · ${new Date(ts * 1000).toLocaleTimeString()}` : ""}
                  {f.Details ? ` · ${String(f.Details)}` : ""}
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <div className="flex items-center gap-2 text-[13px] text-lamp">
          <Lamp on="ok" /> No active faults
        </div>
      )}
    </Instrument>
  );
}

function GpsInstrument() {
  const g = useStore((s) => (s.reports.device?.items?.GPS as Obj) ?? null);
  return (
    <Instrument title="GPS" section="1.3.1.3" className="col-span-12 lg:col-span-3">
      {g ? (
        <div className="grid grid-cols-2 gap-2 text-[12.5px]">
          <Mini k="Latitude" v={fmtNum(g.Latitude, 6)} mono />
          <Mini k="Longitude" v={fmtNum(g.Longitude, 6)} mono />
          <Mini k="Altitude" v={`${fmtNum(g.Altitude, 1)} m`} />
          <Mini k="Speed" v={`${fmtNum(g.Speed, 2)} km/h`} />
          <Mini k="Course" v={`${fmtNum(g.Course, 1)}°`} />
          <Mini k="Fix quality" v={String(g.FixQuality)} />
          <Mini k="Satellites" v={`${g.NumSatellites} used / ${g.VisibleSatellites} seen`} />
          <Mini k="H / V / P DOP" v={`${fmtNum(g.HDOP, 1)} ${fmtNum(g.VDOP, 1)} ${fmtNum(g.PDOP, 1)}`} mono />
        </div>
      ) : (
        <Waiting what="GPS (inside Device State)" />
      )}
    </Instrument>
  );
}

export function Monitor() {
  const e = useStore((s) => s.catalog?.enums);
  const live = useStore((s) => s.session?.state === "connected");
  const any = useStore((s) => Object.keys(s.reports).length > 0);
  if (!live && !any) {
    return (
      <Empty title="Connect to see live status" icon={<Gauge size={26} />}>
        The robot pushes five reports (Basic 2 Hz, Motion 10 Hz, Device 2 Hz, Abnormal 2 Hz, Navigation 1 Hz) to whoever sends
        it heartbeats. Connect in the top bar — or run <code className="font-mono">ezra-udp mock</code> and pick a Mock preset.
      </Empty>
    );
  }
  return (
    <div className="h-full overflow-y-auto p-3">
      <div className="grid grid-cols-12 gap-3">
        <StatusStrip e={e} />
        <MotionInstrument />
        <JointsInstrument />
        <PowerInstrument e={e} />
        <NavInstrument e={e} />
        <FaultsInstrument e={e} />
        <GpsInstrument />
      </div>
    </div>
  );
}
