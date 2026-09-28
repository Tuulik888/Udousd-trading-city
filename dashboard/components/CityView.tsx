"use client";

import type { AgentActivity } from "@/lib/types";
import { Building } from "./Building";

const AGENTS: string[] = ["Trend", "Reverter", "Breaker"];

export function CityView({
  agents,
  onSelect,
}: {
  agents: Record<string, AgentActivity>;
  onSelect: (name: string) => void;
}) {
  return (
    <div className="rounded-3xl border border-city-border bg-[radial-gradient(circle_at_50%_0%,rgba(139,92,246,0.12),transparent_60%)] p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-xs font-mono uppercase tracking-[0.2em] text-violet-300/80">
          City Grid
        </h2>
        <span className="text-[10px] font-mono text-white/40">EUR/USD · practice</span>
      </div>
      <div className="grid grid-cols-3 gap-2">
        {AGENTS.map((name) => (
          <Building
            key={name}
            name={name}
            status={agents[name] ?? "idle"}
            onSelect={() => onSelect(name)}
          />
        ))}
      </div>
    </div>
  );
}
