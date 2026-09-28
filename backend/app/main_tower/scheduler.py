"""APScheduler wiring: research every N hours, trade loop every M15."""
from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler

from .orchestrator import MainTower

TIMEFRAME_MINUTES = {"M15": 15, "H1": 60}


def build_scheduler(
    main_tower: MainTower,
    agent_names: list[str],
    research_interval_hours: int = 6,
    trade_timeframe: str = "M15",
) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    trade_interval_minutes = TIMEFRAME_MINUTES.get(trade_timeframe, 15)

    for name in agent_names:
        scheduler.add_job(
            main_tower.run_research_cycle,
            trigger="interval",
            hours=research_interval_hours,
            args=[name],
            id=f"research-{name}",
            replace_existing=True,
        )
        scheduler.add_job(
            main_tower.run_trade_cycle,
            trigger="interval",
            minutes=trade_interval_minutes,
            args=[name],
            id=f"trade-{name}",
            replace_existing=True,
        )
    return scheduler
