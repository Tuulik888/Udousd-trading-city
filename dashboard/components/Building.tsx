"use client";

import type { AgentActivity } from "@/lib/types";
import { IsoBuilding } from "./IsoBuilding";

const STATUS_LABEL: Record<AgentActivity, string> = {
  idle: "idle",
  thinking: "thinking…",
  backtesting: "backtesting…",
  trading: "trading",
  frozen: "FROZEN",
};

const STATUS_TEXT_COLOR: Record<AgentActivity, string> = {
  idle: "text-violet-300",
  thinking: "text-violet-300",
  backtesting: "text-cyan-300",
  trading: "text-emerald-300",
  frozen: "text-red-400",
};

export function Building({
  name,
  status,
  onSelect,
}: {
  name: string;
  status: AgentActivity;
  onSelect: () => void;
}) {
  return (
    <button
      onClick={onSelect}
      className="flex flex-col items-center gap-2 rounded-2xl border border-city-border bg-city-panel/60 px-3 py-4 transition hover:border-neon-violet active:scale-95"
    >
      <IsoBuilding status={status} size={56} />
      <div className="text-center">
        <div className="text-sm font-semibold tracking-wide text-white">{name}</div>
        <div className={`text-[11px] font-mono uppercase ${STATUS_TEXT_COLOR[status]}`}>
          {STATUS_LABEL[status]}
        </div>
      </div>
    </button>
  );
}
