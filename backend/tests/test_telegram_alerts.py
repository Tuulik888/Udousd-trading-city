from __future__ import annotations

import httpx
import pytest
import respx

from app.telegram_alerts.bot import TELEGRAM_API_BASE, TelegramBot


def make_bot() -> TelegramBot:
    return TelegramBot(bot_token="TEST_TOKEN", chat_id="12345")


class TestSendMessage:
    @respx.mock
    def test_sends_expected_payload(self):
        route = respx.post(f"{TELEGRAM_API_BASE}/botTEST_TOKEN/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        make_bot().send_message("hello city")

        assert route.called
        request = route.calls[0].request
        import json

        payload = json.loads(request.content)
        assert payload["chat_id"] == "12345"
        assert payload["text"] == "hello city"

    @respx.mock
    def test_raises_on_http_error(self):
        respx.post(f"{TELEGRAM_API_BASE}/botTEST_TOKEN/sendMessage").mock(
            return_value=httpx.Response(400, json={"ok": False, "description": "bad chat id"})
        )
        with pytest.raises(httpx.HTTPStatusError):
            make_bot().send_message("hello")

    def test_noop_when_not_configured(self):
        bot = TelegramBot(bot_token="", chat_id="")
        # must not raise, and must not attempt any HTTP call
        bot.send_message("this should be dropped silently")


class TestNotificationHelpers:
    @respx.mock
    def test_notify_trade_opened(self):
        route = respx.post(f"{TELEGRAM_API_BASE}/botTEST_TOKEN/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        make_bot().notify_trade_opened("Trend", "EUR_USD", direction=1, units=8500, entry_price=1.0932)

        import json

        payload = json.loads(route.calls[0].request.content)
        assert "Trend" in payload["text"]
        assert "LONG" in payload["text"]
        assert "EUR_USD" in payload["text"]

    @respx.mock
    def test_notify_trade_closed_win_vs_loss_emoji(self):
        route = respx.post(f"{TELEGRAM_API_BASE}/botTEST_TOKEN/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        bot = make_bot()
        bot.notify_trade_closed("Trend", "EUR_USD", pips=42.0)
        bot.notify_trade_closed("Trend", "EUR_USD", pips=-10.0)

        import json

        win_payload = json.loads(route.calls[0].request.content)
        loss_payload = json.loads(route.calls[1].request.content)
        assert "✅" in win_payload["text"]
        assert "❌" in loss_payload["text"]

    @respx.mock
    def test_notify_agent_frozen(self):
        route = respx.post(f"{TELEGRAM_API_BASE}/botTEST_TOKEN/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        make_bot().notify_agent_frozen("Breaker", "Drawdown 11.3% exceeded the 10% limit")

        import json

        payload = json.loads(route.calls[0].request.content)
        assert "Breaker" in payload["text"]
        assert "FROZEN" in payload["text"]
        assert "11.3%" in payload["text"]

    @respx.mock
    def test_notify_daily_loss_halt(self):
        route = respx.post(f"{TELEGRAM_API_BASE}/botTEST_TOKEN/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        make_bot().notify_daily_loss_halt("Reverter")

        import json

        payload = json.loads(route.calls[0].request.content)
        assert "Reverter" in payload["text"]
        assert "daily loss" in payload["text"]

    @respx.mock
    def test_notify_kill_switch_both_states(self):
        route = respx.post(f"{TELEGRAM_API_BASE}/botTEST_TOKEN/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        bot = make_bot()
        bot.notify_kill_switch(True)
        bot.notify_kill_switch(False)

        import json

        activated = json.loads(route.calls[0].request.content)
        deactivated = json.loads(route.calls[1].request.content)
        assert "ACTIVATED" in activated["text"]
        assert "deactivated" in deactivated["text"]

    @respx.mock
    def test_notify_daily_summary_formats_rows(self):
        route = respx.post(f"{TELEGRAM_API_BASE}/botTEST_TOKEN/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        rows = [
            {"agent": "Trend", "sharpe": 1.8, "equity": 10315.0, "total_pips": 410.0},
            {"agent": "Reverter", "sharpe": None, "equity": None, "total_pips": 0.0},
        ]
        make_bot().notify_daily_summary(rows)

        import json

        payload = json.loads(route.calls[0].request.content)
        assert "Trend" in payload["text"]
        assert "1.80" in payload["text"]
        assert "Reverter" in payload["text"]
        assert "—" in payload["text"]  # missing sharpe/equity rendered as em-dash

    @respx.mock
    def test_notify_daily_summary_handles_no_agents(self):
        route = respx.post(f"{TELEGRAM_API_BASE}/botTEST_TOKEN/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        make_bot().notify_daily_summary([])

        import json

        payload = json.loads(route.calls[0].request.content)
        assert "no agents" in payload["text"].lower()
