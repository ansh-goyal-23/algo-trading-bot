"""
Multi-stock runner.
Loops through all 49 Nifty 50 stocks, runs the backtest strategy on each,
collects results, and writes a ranked summary CSV + full trade history CSV.

Usage: python -m scripts.run_all_stocks
"""
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
from datetime import datetime
from pathlib import Path

import backtrader as bt
from data.loader import load_stock, available_stocks
from strategy.signals import generate_signals
from backtest.run_backtest import ChecklistStrategy, run as bt_run
from backtest.trade_analyzer import TradeCapture
from backtest.run_info import generate_run_id

CASH = 100000
COMMISSION = 0.0003
START_DATE = "2024-01-01"
REPORTS_DIR = Path("reports")


def run_single(symbol: str, run_id: str):
    try:
        df = load_stock(symbol)
        df = df[df["date"] >= START_DATE].reset_index(drop=True)

        if len(df) < 60:
            print(f"SKIP {symbol}: insufficient data ({len(df)} rows)")
            return None, None

        df = df[["date", "open", "high", "low", "close", "volume"]]

        # generate signals
        signals_df = generate_signals(df.copy())
        signals_df.index = (
            pd.to_datetime(signals_df["date"])
            if "date" in signals_df.columns
            else pd.to_datetime(signals_df.index)
        )
        ChecklistStrategy.signals_df = signals_df
        ChecklistStrategy.silent = True

        # build cerebro manually so we can add TradeCapture
        data_feed = df.copy()
        data_feed["date"] = pd.to_datetime(data_feed["date"])
        data_feed.set_index("date", inplace=True)

        cerebro = bt.Cerebro()
        cerebro.addstrategy(ChecklistStrategy)
        cerebro.adddata(bt.feeds.PandasData(dataname=data_feed))
        cerebro.broker.set_cash(CASH)
        cerebro.broker.setcommission(commission=COMMISSION)

        # standard analyzers
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
        cerebro.addanalyzer(bt.analyzers.DrawDown,    _name="drawdown")
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

        # trade capture analyzer
        cerebro.addanalyzer(
            TradeCapture,
            _name="trade_capture",
            stock=symbol,
            run_id=run_id,
        )

        bt_results = cerebro.run()
        strat = bt_results[0]

        ending_capital = cerebro.broker.getvalue()
        dd     = strat.analyzers.drawdown.get_analysis()
        trades = strat.analyzers.trades.get_analysis()
        sharpe = strat.analyzers.sharpe.get_analysis()
        logger = strat.analyzers.trade_capture.get_logger()

        total_trades = trades.total.total if "total" in trades else 0
        won      = trades.won.total if "won" in trades else 0
        win_rate = (won / total_trades * 100) if total_trades > 0 else 0
        max_dd   = dd.max.drawdown if dd.max.drawdown else 0
        sharpe_ratio   = sharpe.get("sharperatio", None)
        total_return   = ((ending_capital - CASH) / CASH) * 100

        summary = {
            "symbol":           symbol,
            "ending_capital":   round(ending_capital, 2),
            "total_return_pct": round(total_return, 2),
            "total_trades":     total_trades,
            "win_rate_pct":     round(win_rate, 1),
            "max_drawdown_pct": round(max_dd, 2),
            "sharpe_ratio":     round(sharpe_ratio, 3) if sharpe_ratio else None,
        }

        return summary, logger

    except Exception as e:
        print(f"  ERROR {symbol}: {e}")
        return None, None


def main():
    run_id = generate_run_id()
    stocks = available_stocks()
    print(f"Run ID: {run_id}")
    print(f"Running strategy on {len(stocks)} stocks from {START_DATE}...\n")

    results  = []
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
        print("No results collected.")
        return

    # rank by total return
    summary_df = pd.DataFrame(results)
    summary_df = summary_df.sort_values("total_return_pct", ascending=False)
    summary_df.insert(0, "rank", range(1, len(summary_df) + 1))
    summary_df = summary_df.reset_index(drop=True)

    # save reports
    run_dir = REPORTS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    summary_path = run_dir / "summary.csv"
    summary_df.to_csv(summary_path, index=False)

    trades_path = run_dir / "trade_history.csv"
    if all_trades:
        trades_df = pd.DataFrame(all_trades)
        trades_df.to_csv(trades_path, index=False)
        print(f"\nTrade history saved → {trades_path} ({len(trades_df)} trades)")
    else:
        print("\nNo trades to save.")

    print(f"\n{'='*60}")
    print(f"RESULTS - {run_id}")
    print(f"{'='*60}")
    print(summary_df.to_string(index=False))
    print(f"\nTop 5 for parameter optimization:")
    print(summary_df.head(5)[["rank","symbol","total_return_pct","win_rate_pct","max_drawdown_pct"]].to_string(index=False))
    print(f"\nSummary saved → {summary_path}")


if __name__ == "__main__":
    main()
