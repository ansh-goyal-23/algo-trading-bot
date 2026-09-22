"""
EXPERIMENTAL sweep: tests exit/risk-management and sizing variants against
the current V2 strategy (3 confirmations / fixed 2% stop / +4%,+6% targets)
across all 49 available Nifty50 stocks, using the same START_DATE/CASH/
COMMISSION as the production backtests so results are directly comparable.

Usage: python -m optimization.exit_variant_sweep
"""
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import backtrader as bt
from pathlib import Path
from datetime import datetime

from data.loader import load_stock, available_stocks
from strategy.signals import generate_signals
from backtest.run_backtest_v3_experiment import ExperimentalStrategy

START_DATE  = "2024-01-01"
CASH        = 100000
COMMISSION  = 0.0003
REPORTS_DIR = Path("reports")

VARIANTS = {
    "baseline_v2":            dict(),  # reproduces current production behavior exactly
    "wider_stop_3pct":        dict(stop_loss_pct=0.03),
    "wider_stop_2_5pct":      dict(stop_loss_pct=0.025),
    "atr_stop_2x":            dict(use_atr_stop=True, atr_mult=2.0),
    "atr_stop_2_5x":          dict(use_atr_stop=True, atr_mult=2.5),
    "atr_stop_1_5x":          dict(use_atr_stop=True, atr_mult=1.5),
    "early_breakeven_1_5pct": dict(breakeven_trigger_pct=0.015),
    "early_breakeven_2pct":   dict(breakeven_trigger_pct=0.02),
    "no_target2_let_run":     dict(disable_target2=True),
    "confirmations_4":        dict(min_confirmations=4),
    "higher_risk_2pct":       dict(risk_per_trade=0.02),
}


def run_single(symbol: str, variant_params: dict) -> dict | None:
    try:
        df = load_stock(symbol)
        df = df[df["date"] >= START_DATE].reset_index(drop=True)
        if len(df) < 60:
            return None
        df = df[["date", "open", "high", "low", "close", "volume"]]

        min_conf = variant_params.get("min_confirmations", 3)
        signals_df = generate_signals(df.copy(), min_confirmations=min_conf)
        signals_df.index = pd.to_datetime(signals_df["date"])

        ExperimentalStrategy.signals_df = signals_df

        data_feed = df.copy()
        data_feed["date"] = pd.to_datetime(data_feed["date"])
        data_feed.set_index("date", inplace=True)

        cerebro = bt.Cerebro()
        cerebro.addstrategy(ExperimentalStrategy, **variant_params)
        cerebro.adddata(bt.feeds.PandasData(dataname=data_feed))
        cerebro.broker.set_cash(CASH)
        cerebro.broker.setcommission(commission=COMMISSION)
        cerebro.addanalyzer(bt.analyzers.SharpeRatio,  _name="sharpe")
        cerebro.addanalyzer(bt.analyzers.DrawDown,     _name="drawdown")
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer,_name="trades")

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
            "ending_capital":   round(ending, 2),
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
    all_results = []

    for variant_name, params in VARIANTS.items():
        print(f"\n=== Variant: {variant_name} {params} ===")
        variant_results = []
        for symbol in stocks:
            r = run_single(symbol, params)
            if r:
                r["variant"] = variant_name
                variant_results.append(r)
                all_results.append(r)
        vdf = pd.DataFrame(variant_results)
        total_pnl = (vdf["ending_capital"] - CASH).sum()
        avg_return = vdf["total_return_pct"].mean()
        avg_sharpe = vdf["sharpe_ratio"].dropna().mean()
        avg_dd = vdf["max_drawdown_pct"].mean()
        avg_trades = vdf["total_trades"].mean()
        avg_winrate = vdf["win_rate_pct"].mean()
        profitable = (vdf["total_return_pct"] > 0).sum()
        print(f"  Stocks: {len(vdf)} | Profitable: {profitable}/{len(vdf)} | "
              f"Avg return: {avg_return:.2f}% | Avg Sharpe: {avg_sharpe:.3f} | "
              f"Avg DD: {avg_dd:.2f}% | Avg trades: {avg_trades:.1f} | Avg win rate: {avg_winrate:.1f}% | "
              f"Sum PnL (100k/stock): Rs{total_pnl:,.0f}")

    full_df = pd.DataFrame(all_results)
    run_id = datetime.now().strftime("EXITVAR_%Y%m%d_%H%M%S")
    out_dir = REPORTS_DIR / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    full_df.to_csv(out_dir / "exit_variant_results.csv", index=False)

    print(f"\n{'='*70}")
    print("SUMMARY: variant comparison (avg across 49 stocks)")
    print(f"{'='*70}")
    summary = full_df.groupby("variant").agg(
        stocks=("symbol", "count"),
        profitable=("total_return_pct", lambda x: (x > 0).sum()),
        avg_return_pct=("total_return_pct", "mean"),
        avg_sharpe=("sharpe_ratio", "mean"),
        avg_dd_pct=("max_drawdown_pct", "mean"),
        avg_trades=("total_trades", "mean"),
        avg_winrate=("win_rate_pct", "mean"),
    ).round(3).sort_values("avg_sharpe", ascending=False)
    print(summary.to_string())
    summary.to_csv(out_dir / "variant_summary.csv")
    print(f"\nSaved -> {out_dir}")
    print(f"RUN_ID={run_id}")


if __name__ == "__main__":
    main()
