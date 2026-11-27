"use client";

import { X } from "lucide-react";
import { useStore } from "@/lib/store";

export function Toasts() {
  const toasts = useStore((s) => s.toasts);
  const dismiss = useStore((s) => s.dismiss);
  return (
    <div className="pointer-events-none fixed right-4 bottom-4 z-50 flex w-[380px] flex-col gap-2" aria-live="polite">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`pointer-events-auto flex items-start gap-3 rounded-md border bg-panel px-3 py-2.5 text-[13px] shadow-lg ${
            t.level === "error" ? "border-estop" : t.level === "warn" ? "border-signal" : "border-line-strong"
          }`}
        >
          <span
            className="mt-1 h-2 w-2 flex-none rounded-full"
            style={{ background: t.level === "error" ? "var(--estop)" : t.level === "warn" ? "var(--signal)" : "var(--lamp)" }}
          />
          <span className="min-w-0 flex-1 break-words">{t.text}</span>
          <button className="text-faint hover:text-ink" onClick={() => dismiss(t.id)} aria-label="Dismiss">
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}
