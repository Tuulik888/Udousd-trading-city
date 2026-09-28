"use client";

import { useEffect, useState } from "react";
import { getAgentDetail, unfreezeAgent } from "@/lib/api";
import type { AgentDetail } from "@/lib/types";
import { EquitySparkline } from "./EquitySparkline";

function fmtPct(n: number | undefined, digits = 1): string {
  if (n === undefined || Number.isNaN(n)) return "—";
  return `${(n * 100).toFixed(digits)}%`;
}

function fmtNum(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toFixed(digits);
}

export function AgentDetailPanel({ agentName, onClose }: { agentName: string; onClose: () => void }) {
  const [detail, setDetail] = useState<AgentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [unfreezing, setUnfreezing] = useState(false);

  async function load() {
    try {
      const data = await getAgentDetail(agentName);
      setDetail(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load agent");
    }
  }

  useEffect(() => {
    load();
    const id = window.setInterval(load, 8000);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentName]);

  async function handleUnfreeze() {
    setUnfreezing(true);
    try {
      await unfreezeAgent(agentName);
      await load();
    } finally {
      setUnfreezing(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/70 backdrop-blur-sm sm:items-center">
      <div className="max-h-[85dvh] w-full max-w-lg overflow-y-auto rounded-t-3xl border border-city-border bg-city-panel p-5 sm:rounded-3xl">
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h2 className="text-xl font-bold text-white">{agentName}</h2>
            {detail && <p className="text-xs text-white/50">{detail.style}</p>}
          </div>
          <button
            onClick={onClose}
            className="rounded-full border border-white/10 px-3 py-1 text-xs text-white/60 hover:text-white"
          >
            Close
          </button>
        </div>

        {error && <p className="text-sm text-red-400">{error}</p>}

        {detail && (
          <div className="flex flex-col gap-5">
            {detail.status === "frozen" && (
              <div className="flex items-center justify-between rounded-xl border border-red-500/40 bg-red-500/10 px-3 py-2">
                <span className="text-xs font-mono uppercase text-red-300">
                  Frozen — drawdown limit breached
                </span>
                <button
                  onClick={handleUnfreeze}
                  disabled={unfreezing}
                  className="rounded-full bg-red-500 px-3 py-1 text-xs font-semibold text-white disabled:opacity-50"
                >
                  {unfreezing ? "…" : "Unfreeze"}
                </button>
              </div>
            )}

            <section>
              <h3 className="mb-2 text-xs font-mono uppercase tracking-wide text-violet-300/80">
                Equity curve
              </h3>
              <EquitySparkline points={detail.equity_curve} />
            </section>

            {detail.latest_backtest && (
              <section>
                <h3 className="mb-2 text-xs font-mono uppercase tracking-wide text-violet-300/80">
                  Latest backtest (out-of-sample)
                </h3>
                <div className="grid grid-cols-4 gap-2 text-center font-mono text-xs">
                  <Metric label="Sharpe" value={fmtNum(detail.latest_backtest.sharpe_test)} />
                  <Metric label="Max DD" value={fmtPct(detail.latest_backtest.max_dd_test)} />
                  <Metric
                    label="Win rate"
                    value={fmtPct(detail.latest_backtest.win_rate_test)}
                  />
                  <Metric label="Trades" value={String(detail.latest_backtest.trade_count_test)} />
                </div>
                {detail.latest_backtest.passed_promotion_bar ? (
                  <p className="mt-2 text-center text-[11px] text-emerald-300">
                    ✓ passed promotion bar — live on practice
                  </p>
                ) : (
                  <p className="mt-2 text-center text-[11px] text-white/40">
                    did not pass promotion bar yet
                  </p>
                )}
              </section>
            )}

            <section>
              <h3 className="mb-2 text-xs font-mono uppercase tracking-wide text-violet-300/80">
                Open positions ({detail.open_trades.length})
              </h3>
              {detail.open_trades.length === 0 ? (
                <p className="text-xs text-white/40">No open positions.</p>
              ) : (
                <ul className="flex flex-col gap-1.5">
                  {detail.open_trades.map((t) => (
                    <li
                      key={t.id}
                      className="flex items-center justify-between rounded-lg bg-white/[0.04] px-3 py-2 text-xs"
                    >
                      <span className={t.direction === 1 ? "text-emerald-300" : "text-red-300"}>
                        {t.direction === 1 ? "LONG" : "SHORT"} {t.instrument}
                      </span>
                      <span className="font-mono text-white/60">@ {t.entry_price.toFixed(5)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section>
              <h3 className="mb-2 text-xs font-mono uppercase tracking-wide text-violet-300/80">
                Decision log
              </h3>
              {detail.decisions.length === 0 ? (
                <p className="text-xs text-white/40">No decisions logged yet.</p>
              ) : (
                <ul className="flex flex-col gap-2">
                  {detail.decisions.map((d) => (
                    <li key={d.id} className="rounded-lg border border-white/5 bg-white/[0.03] p-3 text-xs">
                      <div className="mb-1 text-[10px] font-mono text-white/40">
                        {new Date(d.created_at).toLocaleString()}
                      </div>
                      <p className="text-white/80">{d.reasoning}</p>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        )}
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-white/[0.04] py-2">
      <div className="text-white/40">{label}</div>
      <div className="text-sm text-white">{value}</div>
    </div>
  );
}
