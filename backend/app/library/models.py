"""SQLAlchemy models — the durable log of every decision, backtest, and
trade, each with the agent's reasoning attached. This is what the
dashboard's decision log and equity curves read from.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    style: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    decisions: Mapped[list["Decision"]] = relationship(back_populates="agent")
    backtests: Mapped[list["BacktestRun"]] = relationship(back_populates="agent")
    trades: Mapped[list["Trade"]] = relationship(back_populates="agent")
    equity_snapshots: Mapped[list["EquitySnapshot"]] = relationship(back_populates="agent")


class Decision(Base):
    """A single research_lab cycle's output for one agent."""

    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    strategy_config_json: Mapped[str] = mapped_column(Text)
    reasoning: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    agent: Mapped["Agent"] = relationship(back_populates="decisions")
    backtests: Mapped[list["BacktestRun"]] = relationship(back_populates="decision")


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    decision_id: Mapped[int | None] = mapped_column(ForeignKey("decisions.id"), nullable=True)

    sharpe_train: Mapped[float] = mapped_column(Float)
    sharpe_test: Mapped[float] = mapped_column(Float)
    max_dd_train: Mapped[float] = mapped_column(Float)
    max_dd_test: Mapped[float] = mapped_column(Float)
    win_rate_train: Mapped[float] = mapped_column(Float)
    win_rate_test: Mapped[float] = mapped_column(Float)
    trade_count_train: Mapped[int] = mapped_column(Integer)
    trade_count_test: Mapped[int] = mapped_column(Integer)
    pips_train: Mapped[float] = mapped_column(Float)
    pips_test: Mapped[float] = mapped_column(Float)
    passed_promotion_bar: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    agent: Mapped["Agent"] = relationship(back_populates="backtests")
    decision: Mapped["Decision | None"] = relationship(back_populates="backtests")


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    oanda_trade_id: Mapped[str] = mapped_column(String(64), default="")
    instrument: Mapped[str] = mapped_column(String(16), default="EUR_USD")
    direction: Mapped[int] = mapped_column(Integer)  # 1 long, -1 short
    units: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    exit_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pips: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|closed
    reasoning: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    agent: Mapped["Agent"] = relationship(back_populates="trades")


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    equity: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    agent: Mapped["Agent"] = relationship(back_populates="equity_snapshots")
