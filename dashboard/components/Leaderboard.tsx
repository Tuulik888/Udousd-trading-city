"use client";

import type { LeaderboardRow } from "@/lib/types";

function fmt(n: number | null, digits = 2): string {
  if (n === null || Number.isNaN(n)) return "—";
  return n.toFixed(digits);
}

export function Leaderboard({
  rows,
  onSelect,
}: {
  rows: LeaderboardRow[];
  onSelect: (name: string) => void;
}) {
  return (
    <div className="rounded-3xl border border-city-border bg-city-panel/60 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-xs font-mono uppercase tracking-[0.2em] text-violet-300/80">
          Leaderboard
        </h2>
        <span className="text-[10px] font-mono text-white/40">ranked by Sharpe</span>
      </div>
      {rows.length === 0 ? (
        <p className="py-6 text-center text-sm text-white/40">No backtests logged yet.</p>
      ) : (
        <ol className="flex flex-col gap-2">
          {rows.map((row, i) => (
            <li key={row.agent}>
              <button
                onClick={() => onSelect(row.agent)}
                className="flex w-full items-center justify-between rounded-xl border border-white/5 bg-white/[0.03] px-3 py-2.5 text-left transition hover:border-neon-cyan/40"
              >
                <div className="flex items-center gap-3">
                  <span className="w-5 text-center font-mono text-xs text-white/40">
                    {i + 1}
                  </span>
                  <span className="font-semibold text-white">{row.agent}</span>
                </div>
                <div className="flex items-center gap-4 text-right font-mono text-xs">
                  <div>
                    <div className="text-white/40">Sharpe</div>
                    <div className={row.sharpe && row.sharpe > 1 ? "text-emerald-300" : "text-white/80"}>
                      {fmt(row.sharpe)}
                    </div>
                  </div>
                  <div>
                    <div className="text-white/40">Pips</div>
                    <div className="text-white/80">{fmt(row.total_pips, 1)}</div>
                  </div>
                </div>
              </button>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
