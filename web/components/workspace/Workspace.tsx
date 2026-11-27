"use client";

import { RequestPanel } from "./RequestPanel";
import { ResponsePanel } from "./ResponsePanel";
import { Sidebar } from "./Sidebar";

export function Workspace() {
  return (
    <div className="grid h-full min-h-0 grid-cols-[288px_minmax(0,1fr)]">
      <Sidebar />
      <div className="grid min-h-0 min-w-0 grid-cols-1 grid-rows-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <RequestPanel />
        <ResponsePanel />
      </div>
    </div>
  );
}
