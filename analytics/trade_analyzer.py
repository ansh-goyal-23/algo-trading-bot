"""
Trade Analyzer.

Reads trade_history.csv from a run and computes per-stock and
overall metrics that backtrader's built-in analyzers don't provide:
- Average win / average loss
- Reward-to-Risk ratio (RRR)
- Expectancy per trade
- Max consecutive losses
- Best and worst single trade
- Profit factor

Usage:
    python -m analytics.trade_analyzer reports/RUN_XXXXXXXX_XXXXXX/trade_history.csv
"""

import sys
import pandas as pd
import numpy as np
from pathlib import Path


def analyze(trade_history_path: str) -> pd.DataFrame:
    path = Path(trade_history_path)
    if not path.exists():
        raise FileNotFoundError(f"Not found: {path}")

    df = pd.read_csv(path)
    df["entry_date"] = pd.to_datetime(df["entry_date"])
    df["exit_date"]  = pd.to_datetime(df["exit_date"])

    results = []

    for stock, group in df.groupby("stock"):
        group = group.sort_values("entry_date").reset_index(drop=True)

        total_trades = len(group)
        wins  = group[group["pnl"] > 0]
        losses= group[group["pnl"] <= 0]

        win_count  = len(wins)
        loss_count = len(losses)
        win_rate   = round(win_count / total_trades * 100, 1) if total_trades > 0 else 0

        avg_win  = round(wins["pnl"].mean(), 2)  if len(wins)   > 0 else 0
        avg_loss = round(losses["pnl"].mean(), 2) if len(losses) > 0 else 0

        # Reward-to-Risk: avg win / abs(avg loss)
        rrr = round(avg_win / abs(avg_loss), 2) if avg_loss != 0 else None

        # Expectancy = (win_rate * avg_win) + (loss_rate * avg_loss)
        loss_rate  = loss_count / total_trades if total_trades > 0 else 0
        expectancy = round(
            (win_rate / 100 * avg_win) + (loss_rate * avg_loss), 2
        )

        # Profit factor = gross profit / abs(gross loss)
        gross_profit = wins["pnl"].sum()
        gross_loss   = abs(losses["pnl"].sum())
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None

        # Max consecutive losses
        max_consec_losses = _max_consecutive_losses(group["pnl"].tolist())

        # Best and worst trade
        best_trade  = round(group["pnl"].max(), 2)
        worst_trade = round(group["pnl"].min(), 2)

        # Total PnL
        total_pnl = round(group["pnl"].sum(), 2)

        # Avg holding days
        avg_holding = round(group["holding_days"].mean(), 1)

        # Stop loss rate
        stop_count  = len(group[group["exit_reason"] == "STOP_LOSS"])
        stop_rate   = round(stop_count / total_trades * 100, 1) if total_trades > 0 else 0

        results.append({
            "stock":              stock,
            "total_trades":       total_trades,
            "win_count":          win_count,
            "loss_count":         loss_count,
            "win_rate_pct":       win_rate,
            "avg_win":            avg_win,
            "avg_loss":           avg_loss,
            "rrr":                rrr,
            "expectancy":         expectancy,
            "profit_factor":      profit_factor,
            "max_consec_losses":  max_consec_losses,
            "best_trade":         best_trade,
            "worst_trade":        worst_trade,
            "total_pnl":          total_pnl,
            "avg_holding_days":   avg_holding,
            "stop_loss_rate_pct": stop_rate,
        })

    result_df = pd.DataFrame(results)
    result_df = result_df.sort_values("total_pnl", ascending=False).reset_index(drop=True)
    return result_df


def _max_consecutive_losses(pnl_list: list) -> int:
    max_streak = 0
    current    = 0
    for pnl in pnl_list:
        if pnl <= 0:
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0
    return max_streak


def print_summary(df: pd.DataFrame):
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 200)
    pd.set_option("display.float_format", "{:.2f}".format)

    print("\n=== PER-STOCK TRADE ANALYSIS ===\n")
    print(df[[
        "stock", "total_trades", "win_rate_pct",
        "avg_win", "avg_loss", "rrr",
        "expectancy", "profit_factor",
        "max_consec_losses", "stop_loss_rate_pct"
    ]].to_string(index=False))

    print("\n=== TOP 5 BY EXPECTANCY ===\n")
    print(df.nlargest(5, "expectancy")[[
        "stock", "expectancy", "rrr", "win_rate_pct", "profit_factor"
    ]].to_string(index=False))

    print("\n=== BOTTOM 5 BY EXPECTANCY ===\n")
    print(df.nsmallest(5, "expectancy")[[
        "stock", "expectancy", "rrr", "win_rate_pct", "profit_factor"
    ]].to_string(index=False))

    print("\n=== OVERALL PORTFOLIO METRICS ===\n")
    print(f"  Total trades across all stocks : {df['total_trades'].sum()}")
    print(f"  Overall win rate               : {round(df['win_count'].sum() / df['total_trades'].sum() * 100, 1)}%")
    print(f"  Avg expectancy per trade       : {round(df['expectancy'].mean(), 2)}")
    print(f"  Avg RRR                        : {round(df['rrr'].dropna().mean(), 2)}")
    print(f"  Stocks with positive expectancy: {len(df[df['expectancy'] > 0])} / {len(df)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m analytics.trade_analyzer <path_to_trade_history.csv>")
        sys.exit(1)

    path = sys.argv[1]
    df   = analyze(path)

    # save alongside the trade history
    out_path = Path(path).parent / "trade_analysis.csv"
    df.to_csv(out_path, index=False)
    print(f"Analysis saved → {out_path}")

    print_summary(df)
