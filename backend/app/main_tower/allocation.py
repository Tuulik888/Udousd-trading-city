"""Capital allocation across agents by risk-adjusted (Sharpe) score."""
from __future__ import annotations


def allocate_capital(total_capital: float, sharpe_by_agent: dict[str, float | None]) -> dict[str, float]:
    """Weight capital toward agents with a higher out-of-sample Sharpe.

    Agents with no backtest yet (`None`) or a non-positive Sharpe get no
    allocation unless *no* agent has a positive Sharpe, in which case
    capital is split evenly so the system can still explore.
    """
    positive = {name: sharpe for name, sharpe in sharpe_by_agent.items() if sharpe and sharpe > 0}

    if not positive:
        n = len(sharpe_by_agent) or 1
        return {name: total_capital / n for name in sharpe_by_agent}

    total_score = sum(positive.values())
    return {
        name: total_capital * (positive.get(name, 0.0) / total_score) for name in sharpe_by_agent
    }
