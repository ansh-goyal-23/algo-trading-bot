"""
Trade Logger

Stores every completed trade from a backtest.
"""

from pathlib import Path
import pandas as pd


class TradeLogger:

    def __init__(self, run_id):
        self.run_id = run_id
        self.trades = []

    def log_trade(
        self,
        strategy,
        stock,
        entry_date,
        exit_date,
        direction,
        entry_price,
        exit_price,
        quantity,
        pnl,
        exit_reason,
    ):

        holding_days = (exit_date - entry_date).days

        return_pct = (
            (exit_price - entry_price)
            / entry_price
        ) * 100

        self.trades.append({

            "run_id": self.run_id,

            "strategy": strategy,

            "stock": stock,

            "entry_date": entry_date,

            "exit_date": exit_date,

            "direction": direction,

            "entry_price": round(entry_price, 2),

            "exit_price": round(exit_price, 2),

            "quantity": quantity,

            "holding_days": holding_days,

            "pnl": round(pnl, 2),

            "return_pct": round(return_pct, 2),

            "exit_reason": exit_reason,

        })

    def dataframe(self):

        return pd.DataFrame(self.trades)

    def save(self, filepath):

        filepath = Path(filepath)

        filepath.parent.mkdir(parents=True, exist_ok=True)

        self.dataframe().to_csv(filepath, index=False)

        print(f"Trade history saved → {filepath}")