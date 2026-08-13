"""
Runs the strategy/signals.py logic through backtrader on historical (or synthetic) data.
Usage: python -m backtest.run_backtest
"""
import backtrader as bt
import pandas as pd
import numpy as np
from strategy.signals import generate_signals


class ChecklistStrategyV2(bt.Strategy):
    params = dict(
        min_confirmations=3,
        stop_loss_pct=0.02,    # 2% stop loss  (optimized)
        risk_per_trade=0.015,  # risk 1.5% of capital per trade (optimized)
        target1_pct=0.04,      # +4% partial exit (50%)
        target2_pct=0.06,      # +6% full exit
    )

    def __init__(self):
        self.order        = None
        self.entry_price  = None
        self.stop_price   = None
        self.target1      = None
        self.target2      = None
        self.partial_done = False
        self.trade_log    = []

    def log(self, txt):
        dt = self.datas[0].datetime.date(0)
        print(f"{dt} {txt}")

    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.isbuy():
                self.entry_price  = order.executed.price
                self.stop_price   = self.entry_price * (1 - self.p.stop_loss_pct)
                self.target1      = self.entry_price * (1 + self.p.target1_pct)
                self.target2      = self.entry_price * (1 + self.p.target2_pct)
                self.partial_done = False
                self.log(f"BUY EXECUTED @ {order.executed.price:.2f} | stop={self.stop_price:.2f} | t1={self.target1:.2f} | t2={self.target2:.2f}")
            elif order.issell():
                self.log(f"SELL EXECUTED @ {order.executed.price:.2f}")
        self.order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            self.trade_log.append(trade.pnl)
            self.log(f"TRADE CLOSED, PnL: {trade.pnl:.2f}")

    def next(self):
        if self.order:
            return

        row = self.get_row()
        current_close = self.data.close[0]

        if not self.position:
            if row is not None and row["signal"] == "BUY":
                size = self.get_position_size()
                self.order = self.buy(size=size)
        else:
            # stop loss check
            if self.stop_price and current_close <= self.stop_price:
                self.log(f"STOP LOSS HIT @ {current_close:.2f}")
                self.order = self.close()
                return

            # partial exit at target 1 (+4%)
            if not self.partial_done and self.target1 and current_close >= self.target1:
                partial_size = max(1, self.position.size // 2)
                self.log(f"TARGET 1 HIT (+4%) @ {current_close:.2f} — selling {partial_size} shares")
                self.order = self.sell(size=partial_size)
                self.partial_done = True
                # move stop to breakeven
                self.stop_price = self.entry_price * 1.001
                return

            # full exit at target 2 (+6%)
            if self.partial_done and self.target2 and current_close >= self.target2:
                self.log(f"TARGET 2 HIT (+6%) @ {current_close:.2f} — full exit")
                self.order = self.close()
                return

            # exit on SELL signal
            if row is not None and row["signal"] == "SELL":
                self.order = self.close()

    def get_row(self):
        """Pull the precomputed signal for the current bar's date."""
        current_date = self.datas[0].datetime.date(0)
        try:
            return self.signals_df.loc[pd.Timestamp(current_date)]
        except KeyError:
            return None

    def get_position_size(self):
        cash = self.broker.get_cash()
        risk_amount = cash * self.p.risk_per_trade
        stop_distance = self.data.close[0] * self.p.stop_loss_pct
        size = int(risk_amount / stop_distance)
        return max(size, 1)


def run(df, cash=100000, commission=0.0003, silent=False):
    signals_df = generate_signals(df.copy())
    signals_df.index = pd.to_datetime(signals_df["date"]) if "date" in signals_df.columns else pd.to_datetime(signals_df.index)

    ChecklistStrategyV2.signals_df = signals_df

    data_feed = df.copy()
    if "date" in data_feed.columns:
        data_feed["date"] = pd.to_datetime(data_feed["date"])
        data_feed.set_index("date", inplace=True)

    cerebro = bt.Cerebro()
    cerebro.addstrategy(ChecklistStrategyV2)
    cerebro.adddata(bt.feeds.PandasData(dataname=data_feed))
    cerebro.broker.set_cash(cash)
    cerebro.broker.setcommission(commission=commission)

    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    ChecklistStrategyV2.silent = silent

    if not silent:
        print(f"Starting capital: {cerebro.broker.getvalue():.2f}")
    results = cerebro.run()
    strat = results[0]

    if not silent:
        print(f"Ending capital: {cerebro.broker.getvalue():.2f}")

    dd = strat.analyzers.drawdown.get_analysis()
    trades = strat.analyzers.trades.get_analysis()

    if not silent:
        print(f"\nMax Drawdown: {dd.max.drawdown:.2f}%")
        print(f"Total trades: {trades.total.total if 'total' in trades else 0}")
        if trades.total.total > 0:
            won = trades.won.total if "won" in trades else 0
            print(f"Win rate: {won / trades.total.total * 100:.1f}%")
        cerebro.plot(style="candlestick")

    return cerebro, results


if __name__ == "__main__":
    df = pd.read_csv("data/ITBEES_2024.csv")
    df = df[["date", "open", "high", "low", "close", "volume"]]
    run(df)
