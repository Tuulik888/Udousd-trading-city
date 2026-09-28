"use client";

import { useEffect, useState } from "react";
import { getLeaderboard, getStatus } from "@/lib/api";
import type { LeaderboardRow, StatusResponse } from "@/lib/types";
import { AgentDetailPanel } from "./AgentDetailPanel";
import { CityView } from "./CityView";
import { KillSwitchButton } from "./KillSwitchButton";
import { Leaderboard } from "./Leaderboard";

const POLL_MS = 6000;

export function Dashboard() {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [leaderboard, setLeaderboard] = useState<LeaderboardRow[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [connectionError, setConnectionError] = useState(false);

  async function refresh() {
    try {
      const [s, l] = await Promise.all([getStatus(), getLeaderboard()]);
      setStatus(s);
      setLeaderboard(l);
      setConnectionError(false);
    } catch {
      setConnectionError(true);
    }
  }

  useEffect(() => {
    refresh();
    const id = window.setInterval(refresh, POLL_MS);
    return () => window.clearInterval(id);
  }, []);

  return (
    <main className="mx-auto flex min-h-dvh max-w-xl flex-col gap-5 px-4 pb-16 pt-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold tracking-tight text-white">
            AI Trading <span className="text-neon-cyan">City</span>
          </h1>
          <p className="text-[11px] text-white/40">EURUSD · OANDA practice account</p>
        </div>
        {status && (
          <KillSwitchButton
            active={status.kill_switch_active}
            onChanged={(active) => setStatus((s) => (s ? { ...s, kill_switch_active: active } : s))}
          />
        )}
      </header>

      {connectionError && (
        <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
          Can&apos;t reach the backend API. Retrying…
        </div>
      )}

      <CityView agents={status?.agents ?? {}} onSelect={setSelectedAgent} />

      <Leaderboard rows={leaderboard} onSelect={setSelectedAgent} />

      {selectedAgent && (
        <AgentDetailPanel agentName={selectedAgent} onClose={() => setSelectedAgent(null)} />
      )}
    </main>
  );
}
