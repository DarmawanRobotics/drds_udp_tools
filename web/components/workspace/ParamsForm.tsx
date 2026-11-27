"use client";

import { Minus, Plus } from "lucide-react";
import { defaultFor } from "@/lib/format";
import type { FieldDef } from "@/lib/types";
import { Switch } from "../ui/primitives";

type Path = (string | number)[];

function setAt(root: unknown, path: Path, value: unknown): unknown {
  if (!path.length) return value;
  const [head, ...rest] = path;
  if (Array.isArray(root)) {
    const copy = [...root];
    copy[head as number] = setAt(copy[head as number], rest, value);
    return copy;
  }
  const obj = { ...((root as Record<string, unknown>) ?? {}) };
  obj[head as string] = setAt(obj[head as string], rest, value);
  return obj;
}

function getAt(root: unknown, path: Path): unknown {
  return path.reduce<unknown>((acc, k) => (acc == null ? undefined : (acc as Record<string | number, unknown>)[k]), root);
}

export function ParamsForm({ fields, value, onChange }: { fields: FieldDef[]; value: unknown; onChange: (v: unknown) => void }) {
  if (!fields.length) {
    return (
      <p className="text-[13px] text-muted">
        This request has no parameters — <code className="font-mono">Items</code> is sent as an empty object.
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      {fields.map((f) => (
        <FieldRow key={f.name} f={f} path={[f.name]} root={value} onChange={onChange} />
      ))}
    </div>
  );
}

function FieldRow({ f, path, root, onChange }: { f: FieldDef; path: Path; root: unknown; onChange: (v: unknown) => void }) {
  const v = getAt(root, path);
  const set = (nv: unknown) => onChange(setAt(root, path, nv));
  const label = (
    <div className="flex min-w-[150px] flex-col">
      <span className="text-[13px] font-semibold">{f.label || f.name}</span>
      <span className="font-mono text-[11px] text-faint">
        {f.name}
        {f.unit ? ` · ${f.unit}` : ""}
      </span>
    </div>
  );

  if (f.kind === "object") {
    return (
      <fieldset className="min-w-0 rounded-md border border-line p-3">
        <legend className="px-1 text-[13px] font-semibold">{f.label || f.name}</legend>
        <div className="grid grid-cols-1 gap-2.5 lg:grid-cols-2">
          {(f.fields ?? []).map((sub) => (
            <FieldRow key={sub.name} f={sub} path={[...path, sub.name]} root={root} onChange={onChange} />
          ))}
        </div>
        {f.help ? <p className="mt-2 text-[12px] text-muted">{f.help}</p> : null}
      </fieldset>
    );
  }

  if (f.kind === "array" && f.fields) {
    const list = Array.isArray(v) ? v : v && typeof v === "object" ? [v] : [];
    const canAdd = f.max_items === undefined || list.length < f.max_items;
    const canRemove = list.length > (f.min_items ?? 0);
    return (
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-semibold">{f.label || f.name}</span>
          <span className="font-mono text-[11px] text-faint">{f.name}[{list.length}]</span>
          {canAdd ? (
            <button type="button" className="btn ml-auto h-7 px-2 text-xs"
              onClick={() => set([...list, defaultFor({ name: "", kind: "object", fields: f.fields })])}>
              <Plus size={13} /> Add {f.item_labels ? "" : "point"}
            </button>
          ) : null}
        </div>
        {list.map((_, i) => (
          <fieldset key={i} className="min-w-0 rounded-md border border-line p-3">
            <legend className="flex items-center gap-2 px-1 text-[12.5px] font-semibold">
              {f.item_labels?.[i] ?? `#${i}`}
              {canRemove ? (
                <button type="button" className="text-faint hover:text-bad" aria-label={`Remove ${i}`}
                  onClick={() => set(list.filter((__, j) => j !== i))}>
                  <Minus size={13} />
                </button>
              ) : null}
            </legend>
            <div className="grid grid-cols-1 gap-2.5 lg:grid-cols-2">
              {f.fields!.map((sub) => (
                <FieldRow key={sub.name} f={sub} path={[...path, i, sub.name]} root={root} onChange={onChange} />
              ))}
            </div>
          </fieldset>
        ))}
      </div>
    );
  }

  let control: React.ReactNode;
  if (f.kind === "enum" && f.enum) {
    control = (
      <select className="field min-w-[220px]" value={String(v ?? "")} onChange={(e) => set(Number(e.target.value))}>
        {!(String(v) in f.enum) ? <option value={String(v ?? "")}>{String(v ?? "")} (not in docs)</option> : null}
        {Object.entries(f.enum).map(([k, lbl]) => (
          <option key={k} value={k}>
            {lbl} — {k}
            {Number(k) > 255 ? ` (0x${Number(k).toString(16).toUpperCase()})` : ""}
          </option>
        ))}
      </select>
    );
  } else if (f.kind === "array" && f.item_kind === "enum" && f.enum) {
    const arr = Array.isArray(v) ? (v as number[]) : v === undefined ? [] : [v as number];
    control = (
      <div className="flex flex-wrap gap-1.5">
        {Object.entries(f.enum).map(([k, lbl]) => {
          const on = arr.includes(Number(k));
          return (
            <button key={k} type="button" aria-pressed={on}
              onClick={() => set(on ? arr.filter((x) => x !== Number(k)) : [...arr, Number(k)])}
              className={`h-7 rounded border px-2 text-[12.5px] font-semibold ${on ? "border-tx bg-tx text-white" : "border-line bg-well text-muted"}`}>
              {lbl}
            </button>
          );
        })}
      </div>
    );
  } else if (f.kind === "bool") {
    control = <Switch checked={Boolean(v)} onChange={set} label={v ? "true" : "false"} />;
  } else if (f.kind === "int" || f.kind === "float") {
    const n = typeof v === "number" ? v : Number(v ?? 0);
    const slider = f.kind === "float" && f.min !== undefined && f.max !== undefined;
    control = (
      <div className="flex items-center gap-3">
        {slider ? (
          <input type="range" min={f.min} max={f.max} step={f.step ?? 0.01} value={n} aria-label={f.name}
            className="w-[200px] accent-[var(--tx)]" onChange={(e) => set(Number(e.target.value))} />
        ) : null}
        <input className="field w-[120px] font-mono" type="number" value={Number.isFinite(n) ? n : 0}
          step={f.step ?? (f.kind === "int" ? 1 : 0.01)} min={f.min} max={f.max}
          onChange={(e) => set(e.target.value === "" ? 0 : f.kind === "int" ? Math.trunc(Number(e.target.value)) : Number(e.target.value))} />
        {f.min !== undefined || f.max !== undefined ? (
          <span className="text-[12px] text-faint">
            {f.min ?? "−∞"} … {f.max ?? "∞"}
          </span>
        ) : null}
      </div>
    );
  } else {
    control = <input className="field" value={String(v ?? "")} onChange={(e) => set(e.target.value)} />;
  }

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
      {label}
      <div className="min-w-0">{control}</div>
      {f.help ? <span className="basis-full pl-0 text-[12px] text-muted lg:pl-[166px]">{f.help}</span> : null}
    </div>
  );
}
