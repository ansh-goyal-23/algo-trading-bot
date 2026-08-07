"""
Trade capture analyzer for Backtrader.
Tracks order fills to correctly capture exit_price and quantity,
since trade.size and trade.value are zeroed out by Backtrader after close.
"""

import backtrader as bt
from backtest.trade_logger import TradeLogger


class TradeCapture(bt.Analyzer):

    params = dict(
        stock="UNKNOWN",
        run_id="RUN_UNKNOWN",
        strategy_name="ChecklistStrategy",
    )

    def __init__(self):
        self.logger = TradeLogger(self.p.run_id)
        self._entry_size = None
        self._entry_price = None

    def notify_order(self, order):
        if order.status != order.Completed:
            return

        if order.isbuy():
            self._entry_size  = order.executed.size
            self._entry_price = order.executed.price

        elif order.issell():
            self._exit_price = order.executed.price
            self._exit_size  = order.executed.size

    def notify_trade(self, trade):
        if not trade.isclosed:
            return

        entry_date  = bt.num2date(trade.dtopen).date()
        exit_date   = bt.num2date(trade.dtclose).date()

        entry_price = round(self._entry_price, 2) if self._entry_price else round(trade.price, 2)
        exit_price  = round(self._exit_price, 2)  if hasattr(self, "_exit_price") else entry_price
        quantity    = abs(self._entry_size) if self._entry_size else 0

        stop_level  = round(entry_price * 0.98, 2)
        exit_reason = "STOP_LOSS" if exit_price <= stop_level else "SIGNAL"

        self.logger.log_trade(
            strategy    = self.p.strategy_name,
            stock       = self.p.stock,
            entry_date  = entry_date,
            exit_date   = exit_date,
            direction   = "LONG",
            entry_price = entry_price,
            exit_price  = exit_price,
            quantity    = quantity,
            pnl         = round(trade.pnl, 2),
            exit_reason = exit_reason,
        )

        # reset for next trade
        self._entry_size  = None
        self._entry_price = None
        self._exit_price  = None
        self._exit_size   = None

    def get_logger(self):
        return self.logger
