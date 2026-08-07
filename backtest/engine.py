"""
Universal Backtest Engine

Responsible ONLY for trade execution.
"""

from strategy.signals import generate_signals


class BacktestEngine:

    def __init__(self, config, trade_logger):

        self.config = config

        self.trade_logger = trade_logger

        self.position = None

        self.cash = config.initial_capital

    def run(self, df):

        signals = generate_signals(df.copy())

        for _, row in signals.iterrows():

            self._process_bar(row)

    def _process_bar(self, row):

        if self.position is None:

            self._check_entry(row)

        else:

            self._check_exit(row)

    def _check_entry(self, row):

        pass

    def _check_exit(self, row):

        pass
