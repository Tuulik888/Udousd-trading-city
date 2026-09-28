# AGENTS.md — AI Trading City

## 0. What this is

**AI Trading City** is an MVP where three LLM agents compete to discover a
profitable EURUSD trading strategy, entirely on an **OANDA practice
(paper) account**. A Next.js dashboard renders the agents as buildings in
an isometric neon city so a human can watch them think, backtest, and
trade in near-real-time.

This document is the single source of truth for the system's
architecture, safety rules, and build order. Any implementation that
contradicts this document is a bug — fix the code, not the doc, unless
the human operator explicitly changes the spec here first.

## 1. Non-negotiable architecture rule

> **LLM agents never place orders.** An agent's only output is a
> **strategy config**: a JSON document describing entry/exit rules, a
> timeframe, and stop-loss/take-profit logic built from a fixed whitelist
> of indicators. All execution — backtesting, position sizing, order
> placement, risk enforcement — is deterministic Python code that the LLM
> cannot influence at runtime.

Indicator whitelist (strategy configs may only reference these):

- `EMA` (exponential moving average, configurable period, fast/slow cross)
- `RSI` (relative strength index, configurable period + thresholds)
- `ATR` (average true range, for volatility-based SL/TP sizing)
- `BOLLINGER` (Bollinger Bands, configurable period + std-dev)
- `SESSION_BREAKOUT` (breakout of a session's high/low, e.g. London open range)

A strategy config that references anything outside this whitelist, or
that tries to embed executable code, is rejected before it ever reaches
the backtester.

## 2. Safety: the Risk Vault

The **Risk Vault** (`backend/app/risk_vault/`) is hardcoded, deterministic
Python that no agent (and no strategy config) can alter. It is the single
gate between "a strategy wants to trade" and "an order is sent to
OANDA". Rules, currently fixed at:

| Rule | Limit | Effect when breached |
|---|---|---|
| Risk per trade | 0.5% of account equity | Order size capped or rejected |
| Daily loss | 2% of equity (day start) | Agent's trading halted until next UTC day |
| Drawdown (peak-to-current equity) | 10% | Agent **frozen** — no further trades until a human unfreezes it |
| Global kill switch | env var `TRADING_KILL_SWITCH=true` **or** dashboard button | All agents halted, no orders of any kind |
| OANDA endpoint | must be the practice host | Any non-practice (live) URL is hard-blocked at the HTTP client layer, not just at config-read time |

These are enforced in `RiskVault`, covered by tests written **before**
the implementation (`backend/tests/test_risk_vault.py`), and are treated
as security-critical: changes to `backend/app/risk_vault/vault.py`
require the tests to be extended, never relaxed, to cover the change.

### Practice-only enforcement

`backend/app/data_hub/oanda_client.py` refuses to construct an HTTP
client for any base URL that isn't
`https://api-fxpractice.oanda.com`. This check happens in the client
constructor (defense in depth — even if config/env vars are
misconfigured, the process cannot talk to a live OANDA endpoint).

## 3. Buildings (modules)

Each "building" in the dashboard maps 1:1 to a backend module under
`backend/app/`:

- **data_hub** — fetches and locally caches OANDA candles (M15, H1) so
  backtests and the live loop don't hammer the OANDA API.
- **news_tower** — economic calendar ingestion; blocks trading 30
  minutes before/after high-impact USD/EUR events.
- **research_lab** — for each agent, calls the Anthropic API
  (`claude-sonnet-4-5` family, see `research_lab/claude_client.py`) with
  the agent's persona + its past backtest results, and gets back a
  strategy config proposal/refinement.
- **backtest_lab** — backtests a strategy config over the last 2 years of
  cached candles, including spread + commission costs, with a
  walk-forward train/test split. Produces Sharpe, max drawdown, win
  rate, trade count, and total pips.
- **paper_park** — promotes strategies that pass the bar (Sharpe > 1,
  max DD < 10%, ≥ 50 trades) to live execution on the OANDA practice
  account, gated by the Risk Vault on every order.
- **library** — SQLite-backed log (via SQLAlchemy, swappable to
  Postgres) of every research decision, backtest run, and trade,
  including the agent's LLM reasoning text.
- **main_tower** — the orchestrator: a scheduler that runs the research
  loop every 6 hours and the trading loop on every M15 candle close,
  and allocates capital across agents by a risk-adjusted score
  (Sharpe-weighted).

## 4. The three agents

| Name | Style | Primary indicators |
|---|---|---|
| **Trend** | Trend following | EMA fast/slow cross, ATR-based SL/TP |
| **Reverter** | Mean reversion | RSI extremes, Bollinger Band touches |
| **Breaker** | London session breakout | `SESSION_BREAKOUT` of the Asian range at London open |

Each agent has a fixed persona prompt (its "style") and is given its own
history of backtest/trade results each research cycle so it can refine
its own strategy config — it never sees or copies the other agents'
configs directly, though the dashboard/leaderboard is visible to all.

## 5. Strategy config schema (contract between LLM and backtester)

```json
{
  "agent": "Trend",
  "version": 1,
  "timeframe": "M15",
  "entry": {
    "indicator": "EMA",
    "params": {"fast": 20, "slow": 50},
    "rule": "fast_cross_above_slow"
  },
  "exit": {
    "stop_loss": {"type": "ATR", "params": {"period": 14, "multiple": 1.5}},
    "take_profit": {"type": "ATR", "params": {"period": 14, "multiple": 3.0}}
  },
  "filters": ["news_blackout"],
  "notes": "LLM's free-text reasoning for this revision"
}
```

`research_lab` validates every LLM response against a Pydantic schema
(`backend/app/research_lab/schema.py`) before it's accepted; invalid
output is discarded and logged, never passed to the backtester.

## 6. Promotion pipeline

```
research_lab (propose/refine config)
        │
        ▼
backtest_lab (2yr walk-forward backtest, spread+commission)
        │  pass? Sharpe>1, maxDD<10%, trades>=50
        ▼
paper_park (trade on OANDA practice, gated by risk_vault on every order)
        │
        ▼
library (every decision/backtest/trade logged with reasoning)
```

A strategy that fails the bar goes back to `research_lab` for the next
6-hour research cycle with its backtest metrics attached as feedback.

## 7. Dashboard

Next.js app (`dashboard/`), mobile-first, deployed to Vercel:

- Isometric neon-city view; each agent is a building whose visual state
  reflects its `status`: `thinking` (research_lab running),
  `backtesting`, `trading`, `frozen`.
- Tapping a building opens that agent's detail panel: decision log
  (with LLM reasoning), open positions, equity curve, pips, and
  backtest metrics.
- Leaderboard ranks agents by **Sharpe ratio**, not raw pips.
- A kill switch button calls the backend's
  `POST /api/kill-switch` endpoint, which flips the Risk Vault's
  dashboard-level kill switch (independent of the `TRADING_KILL_SWITCH`
  env var — either one halts trading).

## 8. Infra

- Backend: Python, FastAPI + APScheduler, containerized via
  `backend/Dockerfile`, deployed to Railway.
- Dashboard: Next.js, deployed to Vercel.
- Secrets (env vars, never committed):
  - `OANDA_API_KEY`, `OANDA_ACCOUNT_ID` (practice account only)
  - `ANTHROPIC_API_KEY`
  - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
  - `TRADING_KILL_SWITCH` (optional, defaults unset/false)
  - `DATABASE_URL` (optional, defaults to local SQLite file)
- Telegram alerts fire on: trade opened/closed, agent frozen, daily
  summary (per-agent equity, Sharpe, open positions).

## 9. Build order

This is the order the codebase was actually built in, and the order any
future rework should follow:

1. `AGENTS.md` (this file)
2. **Risk Vault tests** (`backend/tests/test_risk_vault.py`) — written
   against the intended `RiskVault` interface before it exists (TDD for
   the safety-critical component).
3. `data_hub` — OANDA candle fetch + local cache.
4. `backtest_lab` — backtest engine + metrics.
5. `risk_vault` — implementation, made to pass the tests from step 2.
6. `research_lab` — Claude-backed strategy proposal/refinement.
7. `paper_park` — live (practice) execution gated by the vault.
8. `library` — persistence layer (built incrementally alongside 3–7,
   since every module logs through it).
9. `main_tower` — orchestrator loop tying it all together.
10. `dashboard` — Next.js city view.
11. Telegram alerts.

## 10. Testing philosophy

- The Risk Vault is tested first and most thoroughly — it's the only
  thing standing between a bad LLM output and real (if practice-money)
  orders.
- `backtest_lab` and `data_hub` get unit tests on their pure-function
  cores (metrics math, candle caching) without requiring live OANDA
  credentials — tests must run in CI with no secrets configured.
- Anything that calls an external API (OANDA, Anthropic, Telegram) is
  wrapped behind a thin client class so it can be mocked in tests.
