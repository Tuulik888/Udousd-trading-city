"""paper_park: executes a promoted strategy's signals against the OANDA
practice account. Every single order goes through the Risk Vault first
— this module has no authority to place a trade the vault rejects.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from app.backtest_lab.engine import candles_to_frame, compute_entry_signal, compute_stop_distance
from app.data_hub.models import Candle
from app.data_hub.oanda_client import OandaClient
from app.backtest_lab.schema import StrategyConfig
from app.library.repository import Library
from app.news_tower.calendar import NewsCalendar
from app.risk_vault.vault import RiskVault, RiskViolation


@dataclass
class TradeDecision:
    should_trade: bool
    direction: int = 0
    reason: str = ""
    trade_id: int | None = None


class PaperPark:
    def __init__(
        self,
        oanda_client: OandaClient,
        risk_vault: RiskVault,
        library: Library,
        news_calendar: NewsCalendar,
        instrument: str = "EUR_USD",
        value_per_unit: float = 1.0,
    ) -> None:
        self.oanda_client = oanda_client
        self.risk_vault = risk_vault
        self.library = library
        self.news_calendar = news_calendar
        self.instrument = instrument
        self.value_per_unit = value_per_unit

    def evaluate_and_trade(
        self,
        agent_name: str,
        config: StrategyConfig,
        recent_candles: list[Candle],
        now: datetime | None = None,
    ) -> TradeDecision:
        now = now or datetime.now(timezone.utc)

        if not self.risk_vault.can_trade(agent_name):
            return TradeDecision(False, reason="Risk Vault blocked trading (kill switch / frozen / daily halted)")

        if "news_blackout" in config.filters:
            reason = self.news_calendar.blackout_reason(now)
            if reason is not None:
                return TradeDecision(False, reason=f"news blackout: {reason}")

        if self.library.get_open_trades(agent_name):
            return TradeDecision(False, reason="agent already has an open position")

        df = candles_to_frame(recent_candles)
        if df.empty:
            return TradeDecision(False, reason="no candle data")

        signal = compute_entry_signal(df, config)
        last_signal = int(signal.iloc[-1])
        if last_signal == 0:
            return TradeDecision(False, reason="no entry signal on latest candle")

        sl_distance = float(compute_stop_distance(df, config.exit.stop_loss).iloc[-1])
        tp_distance = float(compute_stop_distance(df, config.exit.take_profit).iloc[-1])
        if pd.isna(sl_distance) or sl_distance <= 0:
            return TradeDecision(False, reason="invalid stop-loss distance (insufficient warm-up data)")

        units = self.risk_vault.max_position_units(
            agent_name, stop_loss_distance_price=sl_distance, value_per_unit=self.value_per_unit
        )
        signed_units = units * last_signal

        try:
            self.risk_vault.assert_can_trade(agent_name)
            self.risk_vault.validate_trade_risk(
                agent_name,
                stop_loss_distance_price=sl_distance,
                units=signed_units,
                value_per_unit=self.value_per_unit,
            )
        except RiskViolation as exc:
            return TradeDecision(False, reason=f"risk vault rejected trade: {exc}")

        entry_price = float(df["close"].iloc[-1])
        sl_price = entry_price - last_signal * sl_distance
        tp_price = entry_price + last_signal * tp_distance

        order = self.oanda_client.place_market_order(self.instrument, signed_units, sl_price, tp_price)
        oanda_trade_id = (
            order.get("orderFillTransaction", {}).get("tradeOpened", {}).get("tradeID", "")
        )

        trade_id = self.library.log_trade_open(
            agent_name,
            instrument=self.instrument,
            direction=last_signal,
            units=signed_units,
            entry_price=entry_price,
            entry_time=now,
            oanda_trade_id=oanda_trade_id,
            reasoning=config.notes,
        )
        return TradeDecision(True, direction=last_signal, reason="order placed", trade_id=trade_id)
