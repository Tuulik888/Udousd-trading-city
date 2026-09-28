"""FastAPI routes the dashboard talks to."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.research_lab.personas import PERSONAS

from .orchestrator import MainTower

AGENT_NAMES = list(PERSONAS.keys())


def create_app(main_tower: MainTower, allow_origins: list[str] | None = None) -> FastAPI:
    app = FastAPI(title="AI Trading City")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins or ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/status")
    def get_status() -> dict:
        return {
            "kill_switch_active": main_tower.risk_vault.is_kill_switch_active(),
            "agents": {name: main_tower.status_for(name).value for name in AGENT_NAMES},
        }

    @app.get("/api/leaderboard")
    def get_leaderboard() -> list[dict]:
        return main_tower.library.get_leaderboard()

    @app.get("/api/agents/{agent_name}")
    def get_agent_detail(agent_name: str) -> dict:
        if agent_name not in AGENT_NAMES:
            raise HTTPException(status_code=404, detail=f"unknown agent: {agent_name}")
        return {
            "agent": agent_name,
            "style": PERSONAS[agent_name]["style"],
            "status": main_tower.status_for(agent_name).value,
            "decisions": main_tower.library.get_decisions(agent_name),
            "open_trades": main_tower.library.get_open_trades(agent_name),
            "trades": main_tower.library.get_trades(agent_name),
            "equity_curve": main_tower.library.get_equity_curve(agent_name),
            "latest_backtest": main_tower.library.get_latest_backtest(agent_name),
        }

    @app.get("/api/kill-switch")
    def get_kill_switch() -> dict:
        return {"active": main_tower.risk_vault.is_kill_switch_active()}

    @app.post("/api/kill-switch/activate")
    def activate_kill_switch() -> dict:
        main_tower.risk_vault.activate_kill_switch()
        return {"active": True}

    @app.post("/api/kill-switch/deactivate")
    def deactivate_kill_switch() -> dict:
        main_tower.risk_vault.deactivate_kill_switch()
        return {"active": False}

    @app.post("/api/agents/{agent_name}/unfreeze")
    def unfreeze_agent(agent_name: str) -> dict:
        if agent_name not in AGENT_NAMES:
            raise HTTPException(status_code=404, detail=f"unknown agent: {agent_name}")
        try:
            main_tower.risk_vault.unfreeze_agent(agent_name)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"agent not registered: {agent_name}")
        return {"agent": agent_name, "status": main_tower.status_for(agent_name).value}

    return app
