# AI Trading City

Three LLM agents compete to find a profitable EURUSD strategy — on an
**OANDA practice account only** — and a mobile-first isometric neon
dashboard lets you watch them think, backtest, and trade.

See [AGENTS.md](./AGENTS.md) for the full architecture, safety rules
(Risk Vault, kill switch, practice-only enforcement), and build order.

## Layout

- `backend/` — FastAPI + APScheduler service (data_hub, news_tower,
  research_lab, backtest_lab, risk_vault, paper_park, library,
  main_tower, telegram_alerts). Deploys to Railway via
  `backend/Dockerfile`.
- `dashboard/` — Next.js 15 / React 19 dashboard. Deploys to Vercel.

## Quickstart

### Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp ../.env.example ../.env   # fill in secrets, or leave blank for local dev
pytest                       # 146 tests, no secrets required
uvicorn app.main:app --reload
```

### Dashboard

```bash
cd dashboard
npm install
cp .env.example .env.local   # point NEXT_PUBLIC_API_BASE_URL at the backend
npm run dev
```

## Safety

- LLM agents only ever produce a JSON strategy config (whitelisted
  indicators: EMA, RSI, ATR, Bollinger, session breakout) —
  deterministic Python backtests and executes.
- The Risk Vault hardcodes 0.5% max risk/trade, 2% max daily loss, 10%
  max drawdown (freezes the agent), and a kill switch (env var or
  dashboard button).
- Any non-practice OANDA URL is hard-blocked at the HTTP client layer.
