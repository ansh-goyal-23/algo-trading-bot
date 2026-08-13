"""
Multi-stock runner using v2 strategy (with partial exits).
Usage: python -m scripts.run_all_stocks_v2
"""
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
from datetime import datetime
from pathlib import Path

import backtrader as bt
from data.loader import load_stock, available_stocks
from strategy.signals import generate_signals
from backtest.run_backtest_v2 import ChecklistStrategyV2, run as bt_run
from backtest.trade_analyzer import TradeCapture
from backtest.run_info import generate_run_id

CASH       = 100000
COMMISSION = 0.0003
START_DATE = "2024-01-01"
REPORTS_DIR= Path("reports")


def run_single(symbol: str, run_id: str):
    try:
        df = load_stock(symbol)
        df = df[df["date"] >= START_DATE].reset_index(drop=True)
        if len(df) < 60:
            return None, None
        df = df[["date", "open", "high", "low", "close", "volume"]]

        signals_df = generate_signals(df.copy())
        signals_df.index = (
            pd.to_datetime(signals_df["date"])
            if "date" in signals_df.columns
            else pd.to_datetime(signals_df.index)
        )
        ChecklistStrategyV2.signals_df = signals_df
        ChecklistStrategyV2.silent     = True

        data_feed = df.copy()
        data_feed["date"] = pd.to_datetime(data_feed["date"])
        data_feed.set_index("date", inplace=True)

        cerebro = bt.Cerebro()
        cerebro.addstrategy(ChecklistStrategyV2)
        cerebro.adddata(bt.feeds.PandasData(dataname=data_feed))
        cerebro.broker.set_cash(CASH)
        cerebro.broker.setcommission(commission=COMMISSION)
        cerebro.addanalyzer(bt.analyzers.SharpeRatio,  _name="sharpe")
        cerebro.addanalyzer(bt.analyzers.DrawDown,     _name="drawdown")
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer,_name="trades")
        cerebro.addanalyzer(TradeCapture, _name="tc", stock=symbol, run_id=run_id)

        bt_results = cerebro.run()
        strat = bt_results[0]

        ending = cerebro.broker.getvalue()
        dd     = strat.analyzers.drawdown.get_analysis()
        trades = strat.analyzers.trades.get_analysis()
        sharpe = strat.analyzers.sharpe.get_analysis()
        logger = strat.analyzers.tc.get_logger()

        total_trades = trades.total.total if "total" in trades else 0
        won          = trades.won.total   if "won"   in trades else 0
        win_rate     = (won / total_trades * 100) if total_trades > 0 else 0
        max_dd       = dd.max.drawdown if dd.max.drawdown else 0
        sharpe_ratio = sharpe.get("sharperatio", None)
        total_return = ((ending - CASH) / CASH) * 100

        return {
            "symbol":           symbol,
            "ending_capital":   round(ending, 2),
            "total_return_pct": round(total_return, 2),
            "total_trades":     total_trades,
            "win_rate_pct":     round(win_rate, 1),
            "max_drawdown_pct": round(max_dd, 2),
            "sharpe_ratio":     round(sharpe_ratio, 3) if sharpe_ratio else None,
        }, logger

    except Exception as e:
        print(f"  ERROR {symbol}: {e}")
        return None, None


def main():
    run_id = generate_run_id() + "_V2"
    stocks = available_stocks()
    print(f"Run ID: {run_id}")
    print(f"Strategy: V2 (partial exits at +4% and +6%)")
    print(f"Running on {len(stocks)} stocks from {START_DATE}...\n")

    results    = []
    all_trades = []

    for i, symbol in enumerate(stocks, 1):
        print(f"[{i}/{len(stocks)}] {symbol}...", end=" ", flush=True)
        summary, logger = run_single(symbol, run_id)
        if summary:
            results.append(summary)
            if logger and len(logger.trades) > 0:
                all_trades.extend(logger.trades)
            print(
                f"Return: {summary['total_return_pct']}% | "
                f"Trades: {summary['total_trades']} | "
                f"Win: {summary['win_rate_pct']}% | "
                f"DD: {summary['max_drawdown_pct']}%"
            )

    if not results:
        print("No results.")
        return

    summary_df = pd.DataFrame(results)
    summary_df = summary_df.sort_values("total_return_pct", ascending=False)
    summary_df.insert(0, "rank", range(1, len(summary_df) + 1))
    summary_df = summary_df.reset_index(drop=True)

    run_dir = REPORTS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    summary_df.to_csv(run_dir / "summary.csv", index=False)
    if all_trades:
        pd.DataFrame(all_trades).to_csv(run_dir / "trade_history.csv", index=False)

    print(f"\n{'='*60}")
    print(f"V2 RESULTS (partial exits) — {run_id}")
    print(f"{'='*60}")
    print(summary_df.to_string(index=False))
    print(f"\nTop 5:")
    print(summary_df.head(5)[["rank","symbol","total_return_pct","win_rate_pct","max_drawdown_pct"]].to_string(index=False))
    print(f"\nSummary saved → {run_dir / 'summary.csv'}")


if __name__ == "__main__":
    main()
