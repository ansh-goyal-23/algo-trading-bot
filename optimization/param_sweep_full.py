"""
Full-universe parameter sweep (adapted from param_sweep.py).
Sweeps min_confirmations, stop_loss_pct, and risk_per_trade across
ALL available stocks (not just a hardcoded top-5), ranks by average
Sharpe ratio to find the best universal parameter set.

Usage:
    python -m optimization.param_sweep_full
"""
import warnings
warnings.filterwarnings("ignore")

import itertools
import pandas as pd
import backtrader as bt
from pathlib import Path
from datetime import datetime

from data.loader import load_stock, available_stocks
from strategy.signals import generate_signals
from backtest.run_backtest import ChecklistStrategy

START_DATE  = "2024-01-01"
CASH        = 100000
COMMISSION  = 0.0003
REPORTS_DIR = Path("reports")

PARAM_GRID  = {
    "min_confirmations": [2, 3, 4],
    "stop_loss_pct":     [0.015, 0.02, 0.025],
    "risk_per_trade":    [0.005, 0.01, 0.015],
}


def run_single(symbol: str, params: dict) -> dict | None:
    try:
        df = load_stock(symbol)
        df = df[df["date"] >= START_DATE].reset_index(drop=True)
        if len(df) < 60:
            return None
        df = df[["date", "open", "high", "low", "close", "volume"]]

        signals_df = generate_signals(df.copy(), min_confirmations=params["min_confirmations"])
        signals_df.index = (
            pd.to_datetime(signals_df["date"])
            if "date" in signals_df.columns
            else pd.to_datetime(signals_df.index)
        )
        ChecklistStrategy.signals_df = signals_df
        ChecklistStrategy.silent     = True

        data_feed = df.copy()
        data_feed["date"] = pd.to_datetime(data_feed["date"])
        data_feed.set_index("date", inplace=True)

        cerebro = bt.Cerebro()
        cerebro.addstrategy(
            ChecklistStrategy,
            stop_loss_pct = params["stop_loss_pct"],
            risk_per_trade= params["risk_per_trade"],
            min_confirmations = params["min_confirmations"],
        )
        cerebro.adddata(bt.feeds.PandasData(dataname=data_feed))
        cerebro.broker.set_cash(CASH)
        cerebro.broker.setcommission(commission=COMMISSION)
        cerebro.addanalyzer(bt.analyzers.SharpeRatio,   _name="sharpe")
        cerebro.addanalyzer(bt.analyzers.DrawDown,       _name="drawdown")
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer,  _name="trades")

        results = cerebro.run()
        strat   = results[0]

        ending  = cerebro.broker.getvalue()
        dd      = strat.analyzers.drawdown.get_analysis()
        trades  = strat.analyzers.trades.get_analysis()
        sharpe  = strat.analyzers.sharpe.get_analysis()

        total_trades = trades.total.total if "total" in trades else 0
        won          = trades.won.total   if "won"   in trades else 0
        win_rate     = (won / total_trades * 100) if total_trades > 0 else 0
        max_dd       = dd.max.drawdown if dd.max.drawdown else 0
        sharpe_ratio = sharpe.get("sharperatio", None)
        total_return = ((ending - CASH) / CASH) * 100

        return {
            "symbol":           symbol,
            "min_confirmations":params["min_confirmations"],
            "stop_loss_pct":    params["stop_loss_pct"],
            "risk_per_trade":   params["risk_per_trade"],
            "total_return_pct": round(total_return, 2),
            "total_trades":     total_trades,
            "win_rate_pct":     round(win_rate, 1),
            "max_drawdown_pct": round(max_dd, 2),
            "sharpe_ratio":     round(sharpe_ratio, 3) if sharpe_ratio else None,
        }

    except Exception as e:
        return None


def main():
    stocks = available_stocks()
    keys   = list(PARAM_GRID.keys())
    combos = list(itertools.product(*[PARAM_GRID[k] for k in keys]))
    total  = len(stocks) * len(combos)

    print(f"Full-universe parameter sweep: {len(stocks)} stocks x {len(combos)} combos = {total} runs\n")

    results = []
    run_num = 0

    for symbol in stocks:
        for combo in combos:
            params  = dict(zip(keys, combo))
            run_num += 1
            result  = run_single(symbol, params)
            if result:
                results.append(result)
        print(f"  ...{symbol} done ({run_num}/{total})")

    if not results:
        print("No results.")
        return

    df = pd.DataFrame(results)

    run_id   = datetime.now().strftime("OPT_FULL_%Y%m%d_%H%M%S")
    out_dir  = REPORTS_DIR / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_dir / "param_sweep_full.csv", index=False)

    print(f"\n{'='*65}")
    print("BEST UNIVERSAL PARAMETER SET (avg Sharpe across all stocks)")
    print(f"{'='*65}")
    universal = (
        df.dropna(subset=["sharpe_ratio"])
          .groupby(["min_confirmations", "stop_loss_pct", "risk_per_trade"])
          .agg(
              avg_sharpe   =("sharpe_ratio",     "mean"),
              avg_return   =("total_return_pct", "mean"),
              avg_dd       =("max_drawdown_pct", "mean"),
              avg_winrate  =("win_rate_pct",      "mean"),
              stocks_tested=("symbol",            "count"),
          )
          .reset_index()
          .sort_values("avg_sharpe", ascending=False)
    )
    print(universal.head(15).to_string(index=False))
    universal.to_csv(out_dir / "universal_params.csv", index=False)

    print(f"\nFull results saved -> {out_dir / 'param_sweep_full.csv'}")
    print(f"Universal params saved -> {out_dir / 'universal_params.csv'}")
    print(f"RUN_ID={run_id}")


if __name__ == "__main__":
    main()
