"""
Tick Aggregator.

Collects live ticks throughout the day and builds a daily OHLC candle.
At 3:20 PM, treats the latest tick as the closing price for signal generation.
"""

from collections import defaultdict
from datetime import datetime


class TickAggregator:
    """
    Builds a daily OHLC candle from a stream of live ticks.
    """

    def __init__(self):
        # symbol → {open, high, low, close, volume, tick_count}
        self._candles = defaultdict(lambda: {
            "open":       None,
            "high":       None,
            "low":        None,
            "close":      None,
            "volume":     0,
            "tick_count": 0,
            "first_tick_time": None,
            "last_tick_time":  None,
        })

    def on_tick(self, symbol: str, ltp: float, volume: int = 0):
        c = self._candles[symbol]

        if c["open"] is None:
            c["open"]            = ltp
            c["first_tick_time"] = datetime.now().strftime("%H:%M:%S")

        c["high"]          = max(c["high"] or ltp, ltp)
        c["low"]           = min(c["low"]  or ltp, ltp)
        c["close"]         = ltp
        c["volume"]       += volume
        c["tick_count"]   += 1
        c["last_tick_time"] = datetime.now().strftime("%H:%M:%S")

    def get_candle(self, symbol: str) -> dict | None:
        c = self._candles.get(symbol)
        if not c or c["open"] is None:
            return None
        return {
            "date":       datetime.now().strftime("%Y-%m-%d"),
            "open":       c["open"],
            "high":       c["high"],
            "low":        c["low"],
            "close":      c["close"],   # latest tick = today's close at 3:20
            "volume":     c["tick_count"],  # tick count as proxy for volume
        }

    def get_all_candles(self) -> dict:
        return {
            sym: self.get_candle(sym)
            for sym in self._candles
            if self.get_candle(sym) is not None
        }

    def summary(self):
        print("\n📊 Today's OHLC (built from live ticks):")
        for sym, c in self._candles.items():
            if c["open"]:
                chg = round((c["close"] - c["open"]) / c["open"] * 100, 2)
                direction = "🟢" if chg >= 0 else "🔴"
                print(
                    f"  {sym:12s} | O={c['open']:.2f} H={c['high']:.2f} "
                    f"L={c['low']:.2f} C={c['close']:.2f} | "
                    f"{direction} {chg:+.2f}% | ticks={c['tick_count']}"
                )
