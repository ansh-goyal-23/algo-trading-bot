"""
Backtest Configuration
"""

from dataclasses import dataclass


@dataclass(slots=True)
class BacktestConfig:
    strategy_name: str = "Checklist_v1.0"

    initial_capital: float = 100000

    commission: float = 0.0003

    stop_loss_pct: float = 0.02

    risk_per_trade: float = 0.01

    min_confirmations: int = 3

    timeframe: str = "1D"

    start_date: str | None = None

    end_date: str | None = None