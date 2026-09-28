"""Telegram alerts: trades opened/closed, agent freezes, daily summary.

A thin wrapper around the Telegram Bot API's sendMessage endpoint,
injected with an httpx.Client so it's mockable in tests with no network
access or bot token required.
"""
from __future__ import annotations

import httpx

TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramBot:
    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._client = http_client or httpx.Client(base_url=TELEGRAM_API_BASE, timeout=10.0)

    def send_message(self, text: str) -> None:
        if not self.bot_token or not self.chat_id:
            return  # not configured — no-op rather than crash the trading loop
        resp = self._client.post(
            f"/bot{self.bot_token}/sendMessage",
            json={"chat_id": self.chat_id, "text": text, "parse_mode": "Markdown"},
        )
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # Trade lifecycle
    # ------------------------------------------------------------------

    def notify_trade_opened(
        self, agent_name: str, instrument: str, direction: int, units: float, entry_price: float
    ) -> None:
        side = "LONG" if direction == 1 else "SHORT"
        self.send_message(
            f"🏙️ *{agent_name}* opened {side} {instrument}\n"
            f"units: {abs(units):.0f} @ {entry_price:.5f}"
        )

    def notify_trade_closed(self, agent_name: str, instrument: str, pips: float) -> None:
        emoji = "✅" if pips > 0 else "❌"
        self.send_message(
            f"{emoji} *{agent_name}* closed {instrument}\n" f"result: {pips:+.1f} pips"
        )

    # ------------------------------------------------------------------
    # Risk events
    # ------------------------------------------------------------------

    def notify_agent_frozen(self, agent_name: str, reason: str) -> None:
        self.send_message(f"🧊 *{agent_name}* has been FROZEN by the Risk Vault\n{reason}")

    def notify_daily_loss_halt(self, agent_name: str) -> None:
        self.send_message(
            f"⏸️ *{agent_name}* hit its daily loss limit — trading paused until tomorrow (UTC)"
        )

    def notify_kill_switch(self, active: bool) -> None:
        state = "ACTIVATED — all trading halted" if active else "deactivated — trading resumed"
        self.send_message(f"🛑 Global kill switch {state}")

    # ------------------------------------------------------------------
    # Daily summary
    # ------------------------------------------------------------------

    def notify_daily_summary(self, rows: list[dict]) -> None:
        if not rows:
            self.send_message("📊 Daily summary: no agents registered yet.")
            return
        lines = ["📊 *Daily summary*"]
        for row in rows:
            sharpe = row.get("sharpe")
            sharpe_str = f"{sharpe:.2f}" if sharpe is not None else "—"
            equity = row.get("equity")
            equity_str = f"{equity:.2f}" if equity is not None else "—"
            lines.append(
                f"• {row['agent']}: equity {equity_str}, Sharpe {sharpe_str}, "
                f"pips {row.get('total_pips', 0.0):+.1f}"
            )
        self.send_message("\n".join(lines))
