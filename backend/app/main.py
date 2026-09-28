"""Process entrypoint: wires every building together from env-var
settings, starts the scheduler, and serves the dashboard API.

Run with: uvicorn app.main:app
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.data_hub.cache import CandleCache
from app.data_hub.oanda_client import OandaClient
from app.data_hub.service import DataHub
from app.library.repository import Library
from app.main_tower.api import create_app
from app.main_tower.orchestrator import MainTower
from app.main_tower.scheduler import build_scheduler
from app.news_tower.calendar import NewsCalendar
from app.paper_park.executor import PaperPark
from app.research_lab.claude_client import ClaudeClient
from app.research_lab.personas import PERSONAS
from app.research_lab.service import ResearchLab
from app.risk_vault.vault import RiskVault

logger = logging.getLogger("main_tower")

DEFAULT_STARTING_EQUITY_PER_AGENT = 1_000.0


def build_main_tower() -> MainTower:
    settings = get_settings()

    cache = CandleCache()
    oanda = OandaClient(
        api_key=settings.oanda_api_key,
        account_id=settings.oanda_account_id,
        base_url=settings.oanda_base_url,
    )
    data_hub = DataHub(client=oanda, cache=cache)
    library = Library(database_url=settings.database_url)
    risk_vault = RiskVault()
    news_calendar = NewsCalendar()
    claude_client = ClaudeClient(api_key=settings.anthropic_api_key, model=settings.anthropic_model)
    research_lab = ResearchLab(client=claude_client, library=library)
    paper_park = PaperPark(oanda_client=oanda, risk_vault=risk_vault, library=library, news_calendar=news_calendar)

    tower = MainTower(
        research_lab=research_lab,
        paper_park=paper_park,
        data_hub=data_hub,
        library=library,
        risk_vault=risk_vault,
    )

    starting_equity = DEFAULT_STARTING_EQUITY_PER_AGENT
    try:
        account = oanda.get_account_summary()
        balance = float(account["balance"])
        starting_equity = balance / max(len(PERSONAS), 1)
    except Exception:  # pragma: no cover - best-effort during startup
        logger.warning(
            "Could not fetch OANDA account summary at startup; "
            "registering agents with a default starting equity of %s",
            DEFAULT_STARTING_EQUITY_PER_AGENT,
        )

    for name in PERSONAS:
        risk_vault.register_agent(name, starting_equity=starting_equity)
        library.get_or_create_agent(name, style=PERSONAS[name]["style"])

    return tower


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    scheduler = build_scheduler(
        app.state.main_tower,
        agent_names=list(PERSONAS.keys()),
        research_interval_hours=settings.research_interval_hours,
        trade_timeframe=settings.trade_loop_timeframe,
    )
    scheduler.start()
    app.state.scheduler = scheduler
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


def create_application() -> FastAPI:
    tower = build_main_tower()
    app = create_app(tower)
    app.state.main_tower = tower
    app.router.lifespan_context = lifespan
    return app


app = create_application()
