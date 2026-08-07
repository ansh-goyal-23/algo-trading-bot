"""
Performance Metrics.

Computes portfolio-level and per-stock performance metrics
beyond what backtrader's built-in analyzers provide:
- Sharpe Ratio (from trade returns)
- Calmar Ratio (return / max drawdown)
- Max drawdown duration
- Monthly PnL breakdown
- Rolling win rate

Usage:
    python -m analytics.performance_metrics reports/RUN_XXXXXXXX_XXXXXX/
"""

import sys
import pandas as pd
import numpy as np
from pathlib import Path


def compute_metrics(run_dir: str) -> dict:
    run_path = Path(run_dir)

    trade_path   = run_path / "trade_history.csv"
    summary_path = run_path / "summary.csv"

    if not trade_path.exists():
        raise FileNotFoundError(f"trade_history.csv not found in {run_path}")
    if not summary_path.exists():
        raise FileNotFoundError(f"summary.csv not found in {run_path}")

    trades  = pd.read_csv(trade_path)
    summary = pd.read_csv(summary_path)

    trades["entry_date"] = pd.to_datetime(trades["entry_date"])
    trades["exit_date"]  = pd.to_datetime(trades["exit_date"])

    per_stock = _per_stock_metrics(trades, summary)
    monthly   = _monthly_pnl(trades)
    portfolio = _portfolio_metrics(trades, summary)

    return {
        "per_stock": per_stock,
        "monthly":   monthly,
        "portfolio": portfolio,
    }


def _per_stock_metrics(trades: pd.DataFrame, summary: pd.DataFrame) -> pd.DataFrame:
    results = []

    for stock, group in trades.groupby("stock"):
        group = group.sort_values("exit_date").reset_index(drop=True)

        # match to summary for return and drawdown
        row = summary[summary["symbol"] == stock]
        total_return = row["total_return_pct"].values[0] if len(row) else None
        max_dd       = row["max_drawdown_pct"].values[0]  if len(row) else None

        # Sharpe from per-trade PnL (annualized, assuming ~250 trading days)
        pnl_series = group["pnl"]
        sharpe = None
        if len(pnl_series) > 1 and pnl_series.std() > 0:
            sharpe = round(
                (pnl_series.mean() / pnl_series.std()) * np.sqrt(len(pnl_series)),
                3
            )

        # Calmar = total_return / max_drawdown
        calmar = None
        if total_return is not None and max_dd and max_dd > 0:
            calmar = round(total_return / max_dd, 3)

        # Max drawdown duration (days between peak equity and recovery)
        cumulative = group["pnl"].cumsum()
        peak       = cumulative.cummax()
        in_dd      = cumulative < peak
        if in_dd.any():
            dd_groups = (in_dd != in_dd.shift()).cumsum()
            dd_lengths = group.loc[in_dd, "holding_days"].groupby(dd_groups[in_dd]).sum()
            max_dd_duration = int(dd_lengths.max()) if len(dd_lengths) > 0 else 0
        else:
            max_dd_duration = 0

        # Rolling 10-trade win rate (last 10 trades)
        last_10 = group.tail(10)
        rolling_win = round(len(last_10[last_10["pnl"] > 0]) / len(last_10) * 100, 1)

        results.append({
            "stock":            stock,
            "total_return_pct": total_return,
            "max_drawdown_pct": max_dd,
            "sharpe":           sharpe,
            "calmar":           calmar,
            "max_dd_duration_days": max_dd_duration,
            "rolling_win_rate_pct": rolling_win,
        })

    df = pd.DataFrame(results)
    df = df.sort_values("calmar", ascending=False, na_position="last")
    return df.reset_index(drop=True)


def _monthly_pnl(trades: pd.DataFrame) -> pd.DataFrame:
    trades["month"] = trades["exit_date"].dt.to_period("M")
    monthly = (
        trades.groupby("month")["pnl"]
        .agg(total_pnl="sum", trade_count="count", win_count=lambda x: (x > 0).sum())
        .reset_index()
    )
    monthly["win_rate_pct"] = round(monthly["win_count"] / monthly["trade_count"] * 100, 1)
    monthly["total_pnl"]    = monthly["total_pnl"].round(2)
    monthly["month"]        = monthly["month"].astype(str)
    return monthly


def _portfolio_metrics(trades: pd.DataFrame, summary: pd.DataFrame) -> dict:
    total_trades    = len(trades)
    win_rate        = round(len(trades[trades["pnl"] > 0]) / total_trades * 100, 1)
    total_pnl       = round(trades["pnl"].sum(), 2)
    avg_pnl         = round(trades["pnl"].mean(), 2)
    best_stock      = summary.loc[summary["total_return_pct"].idxmax(), "symbol"]
    worst_stock     = summary.loc[summary["total_return_pct"].idxmin(), "symbol"]
    profitable_stocks = len(summary[summary["total_return_pct"] > 0])

    # portfolio Sharpe across all trades
    pnl_series = trades["pnl"]
    portfolio_sharpe = None
    if pnl_series.std() > 0:
        portfolio_sharpe = round(
            (pnl_series.mean() / pnl_series.std()) * np.sqrt(len(pnl_series)), 3
        )

    return {
        "total_trades":       total_trades,
        "overall_win_rate":   win_rate,
        "total_pnl":          total_pnl,
        "avg_pnl_per_trade":  avg_pnl,
        "portfolio_sharpe":   portfolio_sharpe,
        "best_stock":         best_stock,
        "worst_stock":        worst_stock,
        "profitable_stocks":  profitable_stocks,
        "total_stocks":       len(summary),
    }


def print_report(metrics: dict):
    pd.set_option("display.float_format", "{:.2f}".format)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 200)

    print("\n=== PER-STOCK PERFORMANCE METRICS ===\n")
    print(metrics["per_stock"][[
        "stock", "total_return_pct", "max_drawdown_pct",
        "sharpe", "calmar", "max_dd_duration_days", "rolling_win_rate_pct"
    ]].to_string(index=False))

    print("\n=== MONTHLY PnL BREAKDOWN ===\n")
    monthly = metrics["monthly"]
    monthly["total_pnl_str"] = monthly["total_pnl"].apply(
        lambda x: f"+{x:,.0f}" if x >= 0 else f"{x:,.0f}"
    )
    print(monthly[["month", "total_pnl_str", "trade_count", "win_rate_pct"]].to_string(index=False))

    print("\n=== PORTFOLIO SUMMARY ===\n")
    p = metrics["portfolio"]
    print(f"  Total trades          : {p['total_trades']}")
    print(f"  Overall win rate      : {p['overall_win_rate']}%")
    print(f"  Total PnL (all stocks): ₹{p['total_pnl']:,.2f}")
    print(f"  Avg PnL per trade     : ₹{p['avg_pnl_per_trade']:,.2f}")
    print(f"  Portfolio Sharpe      : {p['portfolio_sharpe']}")
    print(f"  Best stock            : {p['best_stock']}")
    print(f"  Worst stock           : {p['worst_stock']}")
    print(f"  Profitable stocks     : {p['profitable_stocks']} / {p['total_stocks']}")


def save_reports(metrics: dict, run_dir: str):
    run_path = Path(run_dir)

    metrics["per_stock"].to_csv(run_path / "performance_metrics.csv", index=False)
    metrics["monthly"].to_csv(run_path / "monthly_pnl.csv", index=False)

    portfolio_df = pd.DataFrame([metrics["portfolio"]])
    portfolio_df.to_csv(run_path / "portfolio_summary.csv", index=False)

    print(f"\nSaved:")
    print(f"  {run_path / 'performance_metrics.csv'}")
    print(f"  {run_path / 'monthly_pnl.csv'}")
    print(f"  {run_path / 'portfolio_summary.csv'}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m analytics.performance_metrics <run_dir>")
        sys.exit(1)

    run_dir = sys.argv[1]
    metrics = compute_metrics(run_dir)
    print_report(metrics)
    save_reports(metrics, run_dir)
