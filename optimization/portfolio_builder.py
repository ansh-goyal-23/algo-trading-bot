"""
Portfolio Builder.

Selects the best stocks from the universe and allocates capital
across them using three strategies:
1. Equal Weight       — split capital evenly across selected stocks
2. Sharpe Weighted    — allocate more to higher Sharpe stocks
3. Calmar Weighted    — allocate more to higher Calmar (return/drawdown) stocks

Usage:
    python -m optimization.portfolio_builder reports/RUN_XXXXXXXX_XXXXXX/
"""

import sys
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime


# Minimum criteria for a stock to enter the portfolio
MIN_RETURN_PCT    =  5.0   # at least 5% return
MAX_DRAWDOWN_PCT  = 20.0   # no more than 20% drawdown
MIN_WIN_RATE      = 35.0   # at least 35% win rate
MIN_SHARPE        =  0.3   # positive risk-adjusted return
MAX_STOCKS        =  None  # maximum portfolio size (None = no cap, let filters decide)


def load_data(run_dir: str) -> tuple:
    run_path = Path(run_dir)

    summary = pd.read_csv(run_path / "summary.csv")
    metrics = pd.read_csv(run_path / "performance_metrics.csv")
    trade_a = pd.read_csv(run_path / "trade_analysis.csv")

    # merge all into one view
    merged = summary.merge(
        metrics[["stock", "sharpe", "calmar", "max_dd_duration_days", "rolling_win_rate_pct"]],
        left_on="symbol", right_on="stock", how="left"
    ).merge(
        trade_a[["stock", "expectancy", "rrr", "profit_factor", "avg_win", "avg_loss"]],
        on="stock", how="left"
    )
    merged = merged.drop(columns=["stock"])
    return merged


def filter_candidates(df: pd.DataFrame) -> pd.DataFrame:
    filtered = df[
        (df["total_return_pct"]  >= MIN_RETURN_PCT)  &
        (df["max_drawdown_pct"]  <= MAX_DRAWDOWN_PCT) &
        (df["win_rate_pct"]      >= MIN_WIN_RATE)     &
        (df["sharpe_ratio"]      >= MIN_SHARPE)
    ].copy()

    filtered = filtered.sort_values("sharpe_ratio", ascending=False)
    if MAX_STOCKS is not None:
        filtered = filtered.head(MAX_STOCKS)
    return filtered.reset_index(drop=True)


def equal_weight(candidates: pd.DataFrame, total_capital: float) -> pd.DataFrame:
    n = len(candidates)
    candidates = candidates.copy()
    candidates["weight_pct"]     = round(100 / n, 2)
    candidates["allocated_capital"] = round(total_capital / n, 2)
    return candidates


def sharpe_weighted(candidates: pd.DataFrame, total_capital: float) -> pd.DataFrame:
    """
    Weight capital by each stock's Sharpe ratio. Fixed 2026-09-22: the
    original version divided by the raw (unclipped) sum of sharpe_ratio,
    so a candidate that qualified under MIN_SHARPE at one risk_per_trade
    setting but has negative risk-adjusted performance under the risk
    setting actually used live (sizing scales with risk_per_trade, and a
    stock's Sharpe is NOT invariant to it — larger positions amplify both
    winners and losers, so a marginal stock can flip from positive to
    negative Sharpe as risk_per_trade increases) would get a NEGATIVE
    allocation_pct — meaningless for a long-only portfolio, and it also
    silently inflates every other stock's weight by dividing by a smaller
    sum than the positive-only total. Clip to zero for weighting purposes:
    a negative-Sharpe candidate gets 0% allocation instead of distorting
    everyone else's weight or going short.
    """
    candidates = candidates.copy()
    sharpe_clipped = candidates["sharpe_ratio"].clip(lower=0)
    sharpe_sum = sharpe_clipped.sum()
    if sharpe_sum <= 0:
        # every candidate has non-positive Sharpe — nothing sensible to
        # weight by; fall back to equal weight rather than dividing by zero
        candidates["weight_pct"] = round(100 / len(candidates), 2)
    else:
        candidates["weight_pct"] = round(sharpe_clipped / sharpe_sum * 100, 2)
    candidates["allocated_capital"] = round(
        candidates["weight_pct"] / 100 * total_capital, 2
    )
    return candidates


def calmar_weighted(candidates: pd.DataFrame, total_capital: float) -> pd.DataFrame:
    """Same negative-weight guard as sharpe_weighted() — see its docstring."""
    candidates = candidates.copy()
    # use calmar if available, else fall back to sharpe
    weight_col = "calmar" if candidates["calmar"].notna().all() else "sharpe_ratio"
    col_clipped = candidates[weight_col].clip(lower=0)
    col_sum     = col_clipped.sum()
    if col_sum <= 0:
        candidates["weight_pct"] = round(100 / len(candidates), 2)
    else:
        candidates["weight_pct"] = round(col_clipped / col_sum * 100, 2)
    candidates["allocated_capital"] = round(
        candidates["weight_pct"] / 100 * total_capital, 2
    )
    return candidates


def simulate_portfolio(candidates: pd.DataFrame,
                       allocation_col: str = "allocated_capital") -> dict:
    """
    Simulates portfolio return assuming each stock's historical
    return_pct is applied to its allocated capital.
    """
    candidates = candidates.copy()
    candidates["simulated_pnl"] = round(
        candidates[allocation_col] * candidates["total_return_pct"] / 100, 2
    )
    total_pnl    = round(candidates["simulated_pnl"].sum(), 2)
    total_capital= candidates[allocation_col].sum()
    portfolio_return = round(total_pnl / total_capital * 100, 2)
    weighted_dd  = round(
        (candidates["max_drawdown_pct"] * candidates["weight_pct"] / 100).sum(), 2
    )
    return {
        "total_pnl":        total_pnl,
        "portfolio_return": portfolio_return,
        "weighted_drawdown":weighted_dd,
    }


def print_portfolio(name: str, df: pd.DataFrame, stats: dict, capital: float):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    print(df[[
        "symbol", "weight_pct", "allocated_capital",
        "total_return_pct", "sharpe_ratio", "max_drawdown_pct"
    ]].to_string(index=False))
    print(f"\n  Total capital  : ₹{capital:,.2f}")
    print(f"  Simulated PnL  : ₹{stats['total_pnl']:,.2f}")
    print(f"  Portfolio return: {stats['portfolio_return']}%")
    print(f"  Weighted drawdown: {stats['weighted_drawdown']}%")


def save_portfolio(portfolios: dict, run_dir: str):
    run_path = Path(run_dir)
    out_path = run_path / "portfolio.csv"

    rows = []
    for name, (df, stats) in portfolios.items():
        for _, row in df.iterrows():
            rows.append({
                "allocation_method":  name,
                "symbol":             row["symbol"],
                "weight_pct":         row["weight_pct"],
                "allocated_capital":  row["allocated_capital"],
                "expected_return_pct":row["total_return_pct"],
                "sharpe_ratio":       row["sharpe_ratio"],
                "max_drawdown_pct":   row["max_drawdown_pct"],
                "portfolio_return":   stats["portfolio_return"],
                "weighted_drawdown":  stats["weighted_drawdown"],
            })

    pd.DataFrame(rows).to_csv(out_path, index=False)
    print(f"\nPortfolio saved → {out_path}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m optimization.portfolio_builder <run_dir>")
        sys.exit(1)

    run_dir = sys.argv[1]
    capital = 100000.0

    df = load_data(run_dir)

    print(f"\nUniverse: {len(df)} stocks")
    print(f"Filters : return>={MIN_RETURN_PCT}% | dd<={MAX_DRAWDOWN_PCT}% | "
          f"winrate>={MIN_WIN_RATE}% | sharpe>={MIN_SHARPE}")

    candidates = filter_candidates(df)

    if len(candidates) == 0:
        print("No stocks passed the filters. Relax the criteria.")
        return

    print(f"Qualified: {len(candidates)} stocks\n")
    print(candidates[[
        "symbol", "total_return_pct", "win_rate_pct",
        "max_drawdown_pct", "sharpe_ratio", "calmar", "expectancy"
    ]].to_string(index=False))

    # build three portfolios
    eq   = equal_weight(candidates,   capital)
    sh   = sharpe_weighted(candidates, capital)
    cal  = calmar_weighted(candidates, capital)

    eq_stats  = simulate_portfolio(eq)
    sh_stats  = simulate_portfolio(sh)
    cal_stats = simulate_portfolio(cal)

    print_portfolio("1. EQUAL WEIGHT",   eq,  eq_stats,  capital)
    print_portfolio("2. SHARPE WEIGHTED", sh,  sh_stats,  capital)
    print_portfolio("3. CALMAR WEIGHTED", cal, cal_stats, capital)

    # recommendation
    best_name  = max(
        [("Equal Weight", eq_stats),
         ("Sharpe Weighted", sh_stats),
         ("Calmar Weighted", cal_stats)],
        key=lambda x: x[1]["portfolio_return"]
    )[0]

    print(f"\n{'='*60}")
    print(f"  RECOMMENDATION: {best_name}")
    print(f"  Highest simulated portfolio return.")
    print(f"{'='*60}")

    portfolios = {
        "equal_weight":   (eq,  eq_stats),
        "sharpe_weighted":(sh,  sh_stats),
        "calmar_weighted":(cal, cal_stats),
    }
    save_portfolio(portfolios, run_dir)


if __name__ == "__main__":
    main()
