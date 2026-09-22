"""
Trade capture analyzer for Backtrader.

Logs every SELL fill as its own row (not one row per round-trip), tagged
with the strategy's own real exit reason (STOP_LOSS / TARGET1_PARTIAL /
TARGET2 / SIGNAL / SIGNAL_AFTER_PARTIAL / STOP_LOSS_AFTER_PARTIAL) rather
than guessing the reason after the fact from price alone.

Fixed 2026-09-22: the previous version inferred exit_reason by checking
whether exit_price sat near a hardcoded entry*0.98 (assumed always a 2%
stop, ignoring the strategy's actual stop_loss_pct param), and only ever
logged once per position lifecycle via notify_trade(isclosed) — so a
target1-partial followed by a target2-full exit collapsed into a single
row with the FINAL price/date and combined PnL, hiding the partial exit
entirely and making every profitable target hit look like a generic
"SIGNAL" exit. This version reads last_sell_reason off the strategy (set
in run_backtest_v2.ChecklistStrategyV2 right before each sell/close order)
and logs each fill — partial or final — as its own row, with per-fill PnL
computed from that fill's own quantity and price against the position's
entry price.
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
        self._entry_price = None
        self._entry_date  = None

    def notify_order(self, order):
        if order.status != order.Completed:
            return

        strat = self.strategy

        if order.isbuy():
            self._entry_price = order.executed.price
            self._entry_date  = bt.num2date(order.executed.dt).date()
            return

        if order.issell():
            exit_price  = order.executed.price
            # backtrader reports sell fills with a negative size
            quantity    = abs(order.executed.size)
            exit_date   = bt.num2date(order.executed.dt).date()
            exit_reason = getattr(strat, "last_sell_reason", None) or "UNKNOWN"

            entry_price = self._entry_price if self._entry_price else exit_price
            entry_date  = self._entry_date  if self._entry_date  else exit_date

            pnl = (exit_price - entry_price) * quantity

            self.logger.log_trade(
                strategy    = self.p.strategy_name,
                stock       = self.p.stock,
                entry_date  = entry_date,
                exit_date   = exit_date,
                direction   = "LONG",
                entry_price = round(entry_price, 2),
                exit_price  = round(exit_price, 2),
                quantity    = quantity,
                pnl         = round(pnl, 2),
                exit_reason = exit_reason,
            )

            # A full close (TARGET2 / STOP_LOSS / SIGNAL) ends this position's
            # lifecycle — reset entry tracking for the next BUY. A partial
            # exit (TARGET1_PARTIAL) leaves the position open, so entry_price/
            # entry_date must be kept for the eventual final-exit row.
            if exit_reason != "TARGET1_PARTIAL":
                self._entry_price = None
                self._entry_date  = None

    def notify_trade(self, trade):
        # No longer used for logging (each sell fill is logged directly in
        # notify_order above) — kept as a no-op override so existing callers
        # that expect this analyzer to hook notify_trade don't break.
        pass

    def get_logger(self):
        return self.logger
