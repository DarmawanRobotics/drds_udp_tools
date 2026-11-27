"use client";

import type { ReactNode } from "react";

export function Lamp({ on, title, beat }: { on?: "ok" | "warn" | "bad" | false; title?: string; beat?: number }) {
  return (
    <span
      key={beat}
      title={title}
      className={`lamp ${beat ? "lamp-beat" : ""}`}
      data-on={on || undefined}
      role="img"
      aria-label={title}
    />
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  disabled,
  size = "md",
  label,
}: {
  value: T;
  options: { value: T; label: ReactNode; title?: string }[];
  onChange: (v: T) => void;
  disabled?: boolean;
  size?: "sm" | "md";
  label?: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={`inline-flex rounded-md border border-line bg-well p-0.5 ${disabled ? "opacity-60" : ""}`}
    >
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          title={o.title}
          disabled={disabled}
          onClick={() => onChange(o.value)}
          className={`rounded-[5px] px-2.5 font-semibold transition-colors ${size === "sm" ? "h-6 text-xs" : "h-7 text-[13px]"} ${
            value === o.value ? "bg-panel text-ink shadow-[var(--shadow-hard)]" : "text-muted hover:text-ink"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Tabs<T extends string>({
  value,
  tabs,
  onChange,
  right,
}: {
  value: T;
  tabs: { value: T; label: ReactNode; badge?: ReactNode }[];
  onChange: (v: T) => void;
  right?: ReactNode;
}) {
  return (
    <div className="flex items-end gap-1 border-b border-line px-3" role="tablist">
      {tabs.map((t) => (
        <button
          key={t.value}
          role="tab"
          aria-selected={value === t.value}
          onClick={() => onChange(t.value)}
          className={`-mb-px flex h-9 items-center gap-1.5 border-b-2 px-2.5 text-[13px] font-semibold ${
            value === t.value ? "border-tx text-ink" : "border-transparent text-muted hover:text-ink"
          }`}
        >
          {t.label}
          {t.badge}
        </button>
      ))}
      <div className="ml-auto flex items-center gap-2 pb-1.5">{right}</div>
    </div>
  );
}

const CHIP_TONES = {
  neutral: "bg-well text-muted border-line",
  tx: "bg-[color-mix(in_oklab,var(--tx)_14%,transparent)] text-tx border-[color-mix(in_oklab,var(--tx)_35%,transparent)]",
  rx: "bg-[color-mix(in_oklab,var(--rx)_14%,transparent)] text-rx border-[color-mix(in_oklab,var(--rx)_35%,transparent)]",
  ok: "bg-[color-mix(in_oklab,var(--lamp)_14%,transparent)] text-lamp border-[color-mix(in_oklab,var(--lamp)_35%,transparent)]",
  warn: "bg-[color-mix(in_oklab,var(--signal)_20%,transparent)] text-warn border-[color-mix(in_oklab,var(--signal)_45%,transparent)]",
  bad: "bg-[color-mix(in_oklab,var(--estop)_12%,transparent)] text-bad border-[color-mix(in_oklab,var(--estop)_35%,transparent)]",
} as const;

export type Tone = keyof typeof CHIP_TONES;

export function Chip({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className={`inline-flex h-[20px] items-center gap-1 whitespace-nowrap rounded border px-1.5 text-[11.5px] font-semibold leading-none ${CHIP_TONES[tone]}`}
    >
      {children}
    </span>
  );
}

export function Labeled({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="flex min-w-0 flex-col gap-1">
      <span className="text-[12.5px] font-medium text-muted">{label}</span>
      {children}
      {hint ? <span className="text-[12px] text-faint">{hint}</span> : null}
    </label>
  );
}

export function Empty({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex h-full min-h-[160px] flex-col items-center justify-center gap-2 p-6 text-center">
      {icon ? <div className="text-faint">{icon}</div> : null}
      <div className="font-cond text-[17px] font-semibold">{title}</div>
      {children ? <div className="max-w-[46ch] text-[13px] text-muted">{children}</div> : null}
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded border border-line bg-well px-1 font-sans text-[11px] font-semibold text-muted">{children}</kbd>
  );
}

export function Switch({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: ReactNode;
  disabled?: boolean;
}) {
  return (
    <label className={`inline-flex cursor-pointer items-center gap-2 text-[13px] ${disabled ? "opacity-50" : ""}`}>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative h-[18px] w-8 rounded-full border transition-colors ${
          checked ? "border-tx bg-tx" : "border-line-strong bg-well"
        }`}
      >
        <span
          className={`absolute top-[1px] h-[14px] w-[14px] rounded-full bg-panel shadow transition-all ${
            checked ? "left-[15px]" : "left-[1px]"
          }`}
        />
      </button>
      <span>{label}</span>
    </label>
  );
}
