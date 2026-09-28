"""Central settings, loaded from environment variables.

Every secret and every tunable that Risk Vault enforcement depends on is
read here and nowhere else, so tests can override `Settings` without
touching real env vars, and so there's one obvious place to audit what
the process reads from its environment.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

OANDA_PRACTICE_URL = "https://api-fxpractice.oanda.com"
OANDA_PRACTICE_STREAM_URL = "https://stream-fxpractice.oanda.com"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # OANDA (practice account only — see risk_vault.vault.assert_practice_url)
    oanda_api_key: str = ""
    oanda_account_id: str = ""
    oanda_base_url: str = OANDA_PRACTICE_URL

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Safety
    trading_kill_switch: bool = False

    # Persistence
    database_url: str = "sqlite:///./trading_city.db"

    # Scheduler cadence
    research_interval_hours: int = 6
    trade_loop_timeframe: str = "M15"


@lru_cache
def get_settings() -> Settings:
    return Settings()
