"use client";

import { Binary, BookOpen, Gauge, ListChecks, Moon, Send, Sun, Waypoints } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { API_BASE, api, wsUrl } from "@/lib/api";
import { useStore } from "@/lib/store";
import { Inspector } from "./inspector/Inspector";
import { Monitor } from "./monitor/Monitor";
import { Runner } from "./runner/Runner";
import { TopBar } from "./TopBar";
import { Traffic } from "./traffic/Traffic";
import { Toasts } from "./ui/Toasts";
import { Workspace } from "./workspace/Workspace";

type View = "workspace" | "monitor" | "traffic" | "runner" | "inspector";
const VIEWS: { id: View; label: string; icon: ReactNode }[] = [
  { id: "workspace", label: "Requests", icon: <Send size={19} /> },
  { id: "monitor", label: "Monitor", icon: <Gauge size={19} /> },
  { id: "traffic", label: "Traffic", icon: <Waypoints size={19} /> },
  { id: "runner", label: "Test run", icon: <ListChecks size={19} /> },
  { id: "inspector", label: "Bytes", icon: <Binary size={19} /> },
];
const DOCS_URL = "https://github.com/DarmawanRobotics/drds_udp_tools/blob/main/docs/ROS2_TOPIC_DEBUG.md";

function useHashView(): [View, (v: View) => void] {
  const read = (): View => {
    const h = typeof window === "undefined" ? "" : window.location.hash.replace(/^#\/?/, "");
    return (VIEWS.find((v) => v.id === h)?.id ?? "workspace") as View;
  };
  const [view, setView] = useState<View>("workspace");
  useEffect(() => {
    setView(read());
    const on = () => setView(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return [view, (v) => { window.location.hash = `/${v}`; }];
}

function useEngineSocket() {
  useEffect(() => {
    let ws: WebSocket | null = null;
    let buf: unknown[] = [];
    let dead = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    const st = useStore.getState;
    const flush = setInterval(() => {
      if (!buf.length) return;
      const b = buf;
      buf = [];
      st().ingest(b as { kind: string }[]);
    }, 80);
    const open = () => {
      st().setWs("connecting");
      ws = new WebSocket(wsUrl());
      ws.onopen = () => st().setWs("open");
      ws.onmessage = (m) => {
        try {
          buf.push(JSON.parse(m.data as string));
        } catch {
          /* ignore malformed frame */
        }
      };
      ws.onclose = () => {
        st().setWs("closed");
        if (!dead) retry = setTimeout(open, 1500);
      };
      ws.onerror = () => ws?.close();
    };
    open();
    const ping = setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send("ping"), 15000);
    return () => {
      dead = true;
      clearInterval(flush);
      clearInterval(ping);
      clearTimeout(retry);
      ws?.close();
    };
  }, []);
}

function useCatalog() {
  const setCatalog = useStore((s) => s.setCatalog);
  const setBackend = useStore((s) => s.setBackend);
  useEffect(() => {
    let stop = false;
    let t: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        setCatalog(await api.catalog());
        setBackend("online");
      } catch {
        setBackend("offline");
        if (!stop) t = setTimeout(load, 2000);
      }
    };
    load();
    return () => {
      stop = true;
      clearTimeout(t);
    };
  }, [setCatalog, setBackend]);
}

function ThemeToggle() {
  const [theme, setTheme] = useState<string>("light");
  useEffect(() => setTheme(document.documentElement.dataset.theme ?? "light"), []);
  const flip = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("ezra.theme", next);
    } catch {
      /* private mode */
    }
    setTheme(next);
  };
  return (
    <button className="flex h-10 w-10 items-center justify-center rounded-md text-muted hover:bg-well hover:text-ink" onClick={flip}
      title={theme === "dark" ? "Switch to light" : "Switch to dark"} aria-label="Toggle theme">
      {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
    </button>
  );
}

export function App() {
  const hydrate = useStore((s) => s.hydrate);
  const backend = useStore((s) => s.backend);
  const catalog = useStore((s) => s.catalog);
  const [view, go] = useHashView();
  useEffect(() => hydrate(), [hydrate]);
  useCatalog();
  useEngineSocket();

  if (!catalog) {
    return (
      <main className="flex h-full items-center justify-center p-6">
        <div className="panel max-w-[560px] p-6">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/ezra-robotics-logo.svg" alt="EZRA Robotics" className="mb-4 h-16 w-auto" />
          <h1 className="font-cond text-[24px] font-semibold">{backend === "offline" ? "Backend is not running" : "Connecting to the backend…"}</h1>
          {backend === "offline" ? (
            <div className="mt-2 text-[14px] text-muted">
              <p>
                The GUI talks to the Python engine at <code className="font-mono">{API_BASE || window.location.origin}</code>. Start it and this page
                reconnects on its own:
              </p>
              <pre className="mt-3 rounded bg-well p-3 font-mono text-[12.5px] text-ink">cd backend && ezra-udp serve</pre>
            </div>
          ) : null}
        </div>
      </main>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        <nav className="flex w-[68px] flex-none flex-col items-center gap-1 border-r border-line bg-panel py-2" aria-label="Views">
          {VIEWS.map((v) => (
            <button key={v.id} onClick={() => go(v.id)} aria-current={view === v.id ? "page" : undefined}
              className={`flex w-[58px] flex-col items-center gap-1 rounded-md py-2 text-[11px] font-semibold ${
                view === v.id ? "bg-well text-ink" : "text-muted hover:bg-well/60 hover:text-ink"
              }`}>
              {v.icon}
              {v.label}
            </button>
          ))}
          <div className="mt-auto flex flex-col items-center gap-1">
            <a href={DOCS_URL} target="_blank" rel="noreferrer" title="ROS 2 topic debugging guide (robot side)"
              className="flex w-[58px] flex-col items-center gap-1 rounded-md py-2 text-[11px] font-semibold text-muted hover:bg-well/60 hover:text-ink">
              <BookOpen size={18} />
              ROS 2
            </a>
            <ThemeToggle />
          </div>
        </nav>
        <main className="min-h-0 min-w-0 flex-1">
          {view === "workspace" ? <Workspace /> : null}
          {view === "monitor" ? <Monitor /> : null}
          {view === "traffic" ? <Traffic /> : null}
          {view === "runner" ? <Runner /> : null}
          {view === "inspector" ? <Inspector /> : null}
        </main>
      </div>
      <Toasts />
    </div>
  );
}
