"""
EXPERIMENTAL — not wired into production. A copy of ChecklistStrategyV2 with
configurable exit/risk parameters, used to test whether tightening entries,
widening/ATR-basing the stop, or moving to breakeven sooner improves returns
versus the current 3-confirmation / fixed-2%-stop / +4%-+6% target scheme.

Every variant is driven purely by params — no hardcoded behavior — so the
same class can reproduce the current production strategy exactly (as a
baseline check) and also run each hypothesis.

Usage: see optimization/exit_variant_sweep.py which drives this across all
49 stocks per variant.
"""
import backtrader as bt
import pandas as pd
import numpy as np
from strategy.signals import generate_signals


class ExperimentalStrategy(bt.Strategy):
    params = dict(
        min_confirmations=3,
        stop_loss_pct=0.02,
        risk_per_trade=0.015,
        target1_pct=0.04,
        target2_pct=0.06,
        breakeven_trigger_pct=None,   # if set, move stop to breakeven at this
                                       # unrealized gain BEFORE target1, instead
                                       # of only at target1. None = off (V2 behavior).
        use_atr_stop=False,           # if True, stop_distance = atr * atr_mult
                                       # instead of close * stop_loss_pct
        atr_mult=2.0,
        atr_period=14,
        disable_target2=False,        # if True, let the un-sold half run on
                                       # trailing/signal exit instead of a hard +6% cap
    )

    def __init__(self):
        self.order        = None
        self.entry_price  = None
        self.stop_price   = None
        self.target1      = None
        self.target2      = None
        self.partial_done = False
        self.breakeven_moved = False
        self.pending_exit_reason = None
        self.last_sell_reason    = None
        self.entry_atr    = None

        if self.p.use_atr_stop:
            self.atr = bt.indicators.ATR(self.datas[0], period=self.p.atr_period)

    def log(self, txt):
        pass  # silent by default for sweep speed

    def notify_order(self, order):
        if order.status == order.Completed:
            if order.isbuy():
                self.entry_price  = order.executed.price
                if self.p.use_atr_stop:
                    self.entry_atr  = self.atr[0]
                    stop_distance   = self.entry_atr * self.p.atr_mult
                    self.stop_price = self.entry_price - stop_distance
                else:
                    self.stop_price = self.entry_price * (1 - self.p.stop_loss_pct)
                self.target1      = self.entry_price * (1 + self.p.target1_pct)
                self.target2      = self.entry_price * (1 + self.p.target2_pct)
                self.partial_done = False
                self.breakeven_moved = False
            elif order.issell():
                self.last_sell_reason = self.pending_exit_reason
            self.order = None
            self.pending_exit_reason = None
        elif order.status in (order.Canceled, order.Margin, order.Rejected, order.Expired):
            self.order = None
            self.pending_exit_reason = None

    def notify_trade(self, trade):
        pass

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
            # early breakeven move (optional hypothesis)
            if (self.p.breakeven_trigger_pct is not None and not self.breakeven_moved
                    and not self.partial_done):
                trigger = self.entry_price * (1 + self.p.breakeven_trigger_pct)
                if current_close >= trigger:
                    self.stop_price = max(self.stop_price, self.entry_price * 1.001)
                    self.breakeven_moved = True

            # stop loss check
            if self.stop_price and current_close <= self.stop_price:
                self.pending_exit_reason = "STOP_LOSS" if not self.partial_done else "STOP_LOSS_AFTER_PARTIAL"
                self.order = self.close()
                return

            # partial exit at target 1
            if not self.partial_done and self.target1 and current_close >= self.target1:
                partial_size = max(1, self.position.size // 2)
                self.pending_exit_reason = "TARGET1_PARTIAL"
                self.order = self.sell(size=partial_size)
                self.partial_done = True
                self.stop_price = self.entry_price * 1.001
                return

            # full exit at target 2 (unless disabled — then let it run to SIGNAL)
            if (not self.p.disable_target2 and self.partial_done and self.target2
                    and current_close >= self.target2):
                self.pending_exit_reason = "TARGET2"
                self.order = self.close()
                return

            # exit on SELL signal
            if row is not None and row["signal"] == "SELL":
                self.pending_exit_reason = "SIGNAL_AFTER_PARTIAL" if self.partial_done else "SIGNAL"
                self.order = self.close()

    def get_row(self):
        current_date = self.datas[0].datetime.date(0)
        try:
            return self.signals_df.loc[pd.Timestamp(current_date)]
        except KeyError:
            return None

    def get_position_size(self):
        cash = self.broker.get_cash()
        risk_amount = cash * self.p.risk_per_trade
        if self.p.use_atr_stop:
            stop_distance = self.atr[0] * self.p.atr_mult
        else:
            stop_distance = self.data.close[0] * self.p.stop_loss_pct
        if stop_distance <= 0:
            return 1
        size = int(risk_amount / stop_distance)
        return max(size, 1)
