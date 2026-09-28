"""Library: the single read/write facade every other module logs
through. Wraps the SQLAlchemy models behind plain dicts so callers
(FastAPI routes, main_tower, tests) never need to import ORM classes.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.backtest_lab.engine import BacktestMetrics

from . import models as m
from .db import init_db, make_engine, make_session_factory, session_scope


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Library:
    def __init__(self, database_url: str = "sqlite:///./trading_city.db") -> None:
        self.engine = make_engine(database_url)
        init_db(self.engine)
        self._session_factory: sessionmaker = make_session_factory(self.engine)

    # ------------------------------------------------------------------
    # Agents
    # ------------------------------------------------------------------

    def get_or_create_agent(self, name: str, style: str = "") -> int:
        with session_scope(self._session_factory) as session:
            agent = session.execute(select(m.Agent).where(m.Agent.name == name)).scalar_one_or_none()
            if agent is None:
                agent = m.Agent(name=name, style=style)
                session.add(agent)
                session.flush()
            return agent.id

    def _agent_id(self, session, agent_name: str) -> int:
        agent = session.execute(select(m.Agent).where(m.Agent.name == agent_name)).scalar_one_or_none()
        if agent is None:
            agent = m.Agent(name=agent_name)
            session.add(agent)
            session.flush()
        return agent.id

    # ------------------------------------------------------------------
    # Decisions (research_lab output)
    # ------------------------------------------------------------------

    def log_decision(self, agent_name: str, strategy_config: dict, reasoning: str = "") -> int:
        with session_scope(self._session_factory) as session:
            agent_id = self._agent_id(session, agent_name)
            decision = m.Decision(
                agent_id=agent_id,
                strategy_config_json=json.dumps(strategy_config),
                reasoning=reasoning,
            )
            session.add(decision)
            session.flush()
            return decision.id

    def get_decisions(self, agent_name: str, limit: int = 20) -> list[dict]:
        with session_scope(self._session_factory) as session:
            agent_id = self._agent_id(session, agent_name)
            rows = session.execute(
                select(m.Decision)
                .where(m.Decision.agent_id == agent_id)
                .order_by(m.Decision.created_at.desc())
                .limit(limit)
            ).scalars().all()
            return [
                {
                    "id": r.id,
                    "strategy_config": json.loads(r.strategy_config_json),
                    "reasoning": r.reasoning,
                    "created_at": r.created_at,
                }
                for r in rows
            ]

    # ------------------------------------------------------------------
    # Backtests
    # ------------------------------------------------------------------

    def log_backtest(
        self,
        agent_name: str,
        train: BacktestMetrics,
        test: BacktestMetrics,
        passed_promotion_bar: bool,
        decision_id: int | None = None,
    ) -> int:
        with session_scope(self._session_factory) as session:
            agent_id = self._agent_id(session, agent_name)
            run = m.BacktestRun(
                agent_id=agent_id,
                decision_id=decision_id,
                sharpe_train=train.sharpe,
                sharpe_test=test.sharpe,
                max_dd_train=train.max_drawdown_pct,
                max_dd_test=test.max_drawdown_pct,
                win_rate_train=train.win_rate,
                win_rate_test=test.win_rate,
                trade_count_train=train.trade_count,
                trade_count_test=test.trade_count,
                pips_train=train.total_pips,
                pips_test=test.total_pips,
                passed_promotion_bar=passed_promotion_bar,
            )
            session.add(run)
            session.flush()
            return run.id

    def get_latest_backtest(self, agent_name: str) -> dict | None:
        with session_scope(self._session_factory) as session:
            agent_id = self._agent_id(session, agent_name)
            row = session.execute(
                select(m.BacktestRun)
                .where(m.BacktestRun.agent_id == agent_id)
                .order_by(m.BacktestRun.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            return _backtest_to_dict(row) if row else None

    # ------------------------------------------------------------------
    # Trades
    # ------------------------------------------------------------------

    def log_trade_open(
        self,
        agent_name: str,
        instrument: str,
        direction: int,
        units: float,
        entry_price: float,
        entry_time: datetime,
        oanda_trade_id: str = "",
        reasoning: str = "",
    ) -> int:
        with session_scope(self._session_factory) as session:
            agent_id = self._agent_id(session, agent_name)
            trade = m.Trade(
                agent_id=agent_id,
                oanda_trade_id=oanda_trade_id,
                instrument=instrument,
                direction=direction,
                units=units,
                entry_price=entry_price,
                entry_time=entry_time,
                status="open",
                reasoning=reasoning,
            )
            session.add(trade)
            session.flush()
            return trade.id

    def log_trade_close(self, trade_id: int, exit_price: float, exit_time: datetime, pips: float) -> None:
        with session_scope(self._session_factory) as session:
            trade = session.get(m.Trade, trade_id)
            if trade is None:
                raise KeyError(f"No trade with id {trade_id}")
            trade.exit_price = exit_price
            trade.exit_time = exit_time
            trade.pips = pips
            trade.status = "closed"

    def get_open_trades(self, agent_name: str) -> list[dict]:
        with session_scope(self._session_factory) as session:
            agent_id = self._agent_id(session, agent_name)
            rows = session.execute(
                select(m.Trade).where(m.Trade.agent_id == agent_id, m.Trade.status == "open")
            ).scalars().all()
            return [_trade_to_dict(r) for r in rows]

    def get_trades(self, agent_name: str, limit: int = 50) -> list[dict]:
        with session_scope(self._session_factory) as session:
            agent_id = self._agent_id(session, agent_name)
            rows = session.execute(
                select(m.Trade)
                .where(m.Trade.agent_id == agent_id)
                .order_by(m.Trade.created_at.desc())
                .limit(limit)
            ).scalars().all()
            return [_trade_to_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Equity curve
    # ------------------------------------------------------------------

    def log_equity_snapshot(self, agent_name: str, equity: float, at: datetime | None = None) -> None:
        with session_scope(self._session_factory) as session:
            agent_id = self._agent_id(session, agent_name)
            snap = m.EquitySnapshot(agent_id=agent_id, equity=equity, created_at=at or _utcnow())
            session.add(snap)

    def get_equity_curve(self, agent_name: str) -> list[dict]:
        with session_scope(self._session_factory) as session:
            agent_id = self._agent_id(session, agent_name)
            rows = session.execute(
                select(m.EquitySnapshot)
                .where(m.EquitySnapshot.agent_id == agent_id)
                .order_by(m.EquitySnapshot.created_at.asc())
            ).scalars().all()
            return [{"equity": r.equity, "at": r.created_at} for r in rows]

    # ------------------------------------------------------------------
    # Leaderboard — ranked by Sharpe, not pips (AGENTS.md section 7)
    # ------------------------------------------------------------------

    def get_leaderboard(self) -> list[dict]:
        with session_scope(self._session_factory) as session:
            agents = session.execute(select(m.Agent)).scalars().all()
            board: list[dict] = []
            for agent in agents:
                latest_backtest = session.execute(
                    select(m.BacktestRun)
                    .where(m.BacktestRun.agent_id == agent.id)
                    .order_by(m.BacktestRun.created_at.desc())
                    .limit(1)
                ).scalar_one_or_none()
                latest_equity = session.execute(
                    select(m.EquitySnapshot)
                    .where(m.EquitySnapshot.agent_id == agent.id)
                    .order_by(m.EquitySnapshot.created_at.desc())
                    .limit(1)
                ).scalar_one_or_none()
                total_pips = sum(
                    t.pips or 0.0
                    for t in session.execute(
                        select(m.Trade).where(m.Trade.agent_id == agent.id, m.Trade.status == "closed")
                    ).scalars()
                )
                board.append(
                    {
                        "agent": agent.name,
                        "sharpe": latest_backtest.sharpe_test if latest_backtest else None,
                        "equity": latest_equity.equity if latest_equity else None,
                        "total_pips": total_pips,
                    }
                )
            board.sort(key=lambda row: (row["sharpe"] is None, -(row["sharpe"] or 0.0)))
            return board


def _trade_to_dict(t: m.Trade) -> dict[str, Any]:
    return {
        "id": t.id,
        "oanda_trade_id": t.oanda_trade_id,
        "instrument": t.instrument,
        "direction": t.direction,
        "units": t.units,
        "entry_price": t.entry_price,
        "exit_price": t.exit_price,
        "entry_time": t.entry_time,
        "exit_time": t.exit_time,
        "pips": t.pips,
        "status": t.status,
        "reasoning": t.reasoning,
    }


def _backtest_to_dict(r: m.BacktestRun) -> dict[str, Any]:
    return {
        "id": r.id,
        "sharpe_train": r.sharpe_train,
        "sharpe_test": r.sharpe_test,
        "max_dd_train": r.max_dd_train,
        "max_dd_test": r.max_dd_test,
        "win_rate_train": r.win_rate_train,
        "win_rate_test": r.win_rate_test,
        "trade_count_train": r.trade_count_train,
        "trade_count_test": r.trade_count_test,
        "pips_train": r.pips_train,
        "pips_test": r.pips_test,
        "passed_promotion_bar": r.passed_promotion_bar,
        "created_at": r.created_at,
    }
