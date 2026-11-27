"use client";

import { ChevronDown, ChevronRight, Download, Play } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { download } from "@/lib/format";
import { useStore } from "@/lib/store";
import type { CheckLevel, CheckStatus, SuiteCheck, SuiteResult } from "@/lib/types";
import { Chip, Empty, Switch, type Tone } from "../ui/primitives";

const LEVEL_TEXT: Record<CheckLevel, { title: string; body: string }> = {
  safe: { title: "Safe", body: "Read-only queries and error-path probes. Robot state is not changed." },
  caution: { title: "Caution", body: "Re-applies the current mode/gait, resets lights, cancels navigation. Robot should be idle." },
  motion: { title: "Motion", body: "Stands up, sits down and streams axis commands. Clear the area and keep the E-STOP close." },
};

const STATUS_TONE: Record<CheckStatus, Tone> = { pass: "ok", warn: "warn", fail: "bad", error: "bad", skip: "neutral" };

export function Runner() {
  const live = useStore((s) => s.session?.state === "connected");
  const armed = useStore((s) => s.armed);
  const suite = useStore((s) => s.suite);
  const toast = useStore((s) => s.toast);
  const [checks, setChecks] = useState<SuiteCheck[]>([]);
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const [allowCaution, setAllowCaution] = useState(false);
  const [open, setOpen] = useState<Record<string, boolean>>({});

  useEffect(() => {
    api.suiteChecks().then((c) => {
      setChecks(c);
      setPicked(Object.fromEntries(c.map((x) => [x.id, x.level === "safe"])));
    }).catch(() => undefined);
  }, []);

  const byLevel = useMemo(() => {
    const m: Record<CheckLevel, SuiteCheck[]> = { safe: [], caution: [], motion: [] };
    for (const c of checks) m[c.level].push(c);
    return m;
  }, [checks]);

  const results = useMemo(() => Object.fromEntries(suite.results.map((r) => [r.id, r])), [suite.results]);
  const counts = suite.report?.counts;

  const run = async () => {
    const ids = checks.filter((c) => picked[c.id]).map((c) => c.id);
    if (!ids.length) return toast("warn", "Pick at least one check.");
    const motion = ids.some((id) => checks.find((c) => c.id === id)?.level === "motion");
    if (motion && !armed) return toast("warn", "Motion checks selected — set the lock in the top bar to \"Armed\" first.");
    try {
      await api.suiteRun({ checks: ids, allow_caution: allowCaution, allow_motion: motion && armed });
    } catch (e) {
      toast("error", e instanceof ApiError ? e.message : String(e));
    }
  };

  const exportMd = () => {
    const r = suite.report;
    if (!r) return;
    const t = r.target?.transport;
    const lines = [
      `# EZRA UDP Debugger — conformance run ${r.run_id}`,
      "",
      `- Target: ${t?.kind?.toUpperCase()} ${t?.remote ?? ""} (${t?.protocol ?? "plain"})`,
      `- Started: ${new Date(r.started * 1000).toLocaleString()} · ${r.duration_s} s`,
      `- Result: ${r.counts.pass} pass · ${r.counts.warn} warn · ${r.counts.fail} fail · ${r.counts.skip} skip · ${r.counts.error} error`,
      "",
      "| Status | Check | § | Summary |",
      "|---|---|---|---|",
      ...r.results.map((x) => `| ${x.status} | ${x.name} | ${x.section} | ${x.summary.replace(/\|/g, "\\|")} |`),
    ];
    download(`ezra-suite-${r.run_id}.md`, lines.join("\n"), "text/markdown");
  };

  return (
    <div className="grid h-full min-h-0 grid-cols-[400px_minmax(0,1fr)]">
      <aside className="flex min-h-0 flex-col border-r border-line bg-panel">
        <div className="border-b border-line p-4">
          <h2 className="font-cond text-[20px] font-semibold">Conformance run</h2>
          <p className="mt-1 text-[13px] text-muted">
            Checks every message in the protocol docs against the connected robot: heartbeat, the five report rates, query
            replies and error codes.
          </p>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {(Object.keys(byLevel) as CheckLevel[]).map((lvl) => (
            <section key={lvl} className="border-b border-line px-4 py-3">
              <div className="flex items-center gap-2">
                {lvl === "motion" ? <span className="hazard h-3 w-3 rounded-sm" /> : lvl === "caution" ? <span className="h-3 w-3 rounded-sm bg-signal" /> : <span className="h-3 w-3 rounded-sm bg-lamp" />}
                <h3 className="text-[14px] font-semibold">{LEVEL_TEXT[lvl].title}</h3>
                <button className="ml-auto text-[12px] text-tx hover:underline"
                  onClick={() => {
                    const all = byLevel[lvl].every((c) => picked[c.id]);
                    setPicked({ ...picked, ...Object.fromEntries(byLevel[lvl].map((c) => [c.id, !all])) });
                  }}>
                  {byLevel[lvl].every((c) => picked[c.id]) ? "Select none" : "Select all"}
                </button>
              </div>
              <p className="mt-1 mb-2 text-[12.5px] text-muted">{LEVEL_TEXT[lvl].body}</p>
              <ul className="flex flex-col gap-1">
                {byLevel[lvl].map((c) => (
                  <li key={c.id}>
                    <label className="flex cursor-pointer items-start gap-2 rounded px-1 py-1 hover:bg-well">
                      <input type="checkbox" className="mt-1 accent-[var(--tx)]" checked={!!picked[c.id]}
                        onChange={(e) => setPicked({ ...picked, [c.id]: e.target.checked })} />
                      <span className="min-w-0">
                        <span className="block text-[13px] font-medium">{c.name}</span>
                        <span className="block text-[12px] text-faint">§{c.section} · {c.description}</span>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
        <div className="flex flex-col gap-3 border-t border-line p-4">
          <Switch checked={allowCaution} onChange={setAllowCaution} label="Allow caution checks to change robot state" />
          <button className="btn btn-primary h-10" disabled={!live || suite.running} onClick={run}>
            <Play size={15} /> {suite.running ? `Running ${suite.results.length}/${suite.checks.length}…` : "Run selected checks"}
          </button>
          {!live ? <span className="text-[12.5px] text-muted">Connect first — try the Mock preset with `ezra-udp mock`.</span> : null}
        </div>
      </aside>

      <section className="flex min-h-0 flex-col bg-panel">
        <div className="flex items-center gap-3 border-b border-line px-4 py-3">
          <h2 className="font-cond text-[20px] font-semibold">Results</h2>
          {counts ? (
            <div className="flex gap-1.5">
              <Chip tone="ok">{counts.pass} pass</Chip>
              <Chip tone="warn">{counts.warn} warn</Chip>
              <Chip tone="bad">{counts.fail + counts.error} fail</Chip>
              <Chip>{counts.skip} skipped</Chip>
            </div>
          ) : null}
          <div className="ml-auto flex gap-2">
            <button className="btn h-8 text-xs" disabled={!suite.report} onClick={exportMd}>
              <Download size={13} /> Markdown
            </button>
            <button className="btn h-8 text-xs" disabled={!suite.report}
              onClick={() => suite.report && download(`ezra-suite-${suite.report.run_id}.json`, JSON.stringify(suite.report, null, 2))}>
              <Download size={13} /> JSON
            </button>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {suite.checks.length ? (
            <ul>
              {suite.checks.map((c) => {
                const r: SuiteResult | undefined = results[c.id];
                const isOpen = open[c.id];
                return (
                  <li key={c.id} className="border-b border-line/70">
                    <button className="flex w-full items-start gap-3 px-4 py-2.5 text-left hover:bg-well/60" onClick={() => setOpen({ ...open, [c.id]: !isOpen })}>
                      <span className="mt-0.5 w-[54px] flex-none">
                        {r ? <Chip tone={STATUS_TONE[r.status]}>{r.status}</Chip> : suite.running ? <Chip>…</Chip> : <Chip>—</Chip>}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-[13.5px] font-medium">{c.name} <span className="font-normal text-faint">§{c.section}</span></span>
                        <span className="block text-[12.5px] text-muted">{r?.summary ?? c.description}</span>
                      </span>
                      <span className="flex-none text-[12px] text-faint">{r ? `${r.duration_ms} ms` : ""}</span>
                      {r ? isOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} /> : null}
                    </button>
                    {r && isOpen ? (
                      <pre className="mx-4 mb-3 overflow-x-auto rounded bg-well p-3 font-mono text-[11.5px]">{JSON.stringify(r.details, null, 2)}</pre>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          ) : (
            <Empty title="No run yet">Pick checks on the left and run them. Each result links back to the section of the docs it verifies.</Empty>
          )}
        </div>
      </section>
    </div>
  );
}
