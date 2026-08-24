"""
Tick Aggregator.

Collects live ticks throughout the day and builds a daily OHLC candle.
At 3:20 PM, treats the latest tick as the closing price for signal generation.
"""

from collections import defaultdict
from datetime import datetime
from pathlib import Path


class TickAggregator:
    """
    Builds a daily OHLC candle from a stream of live ticks.
    Persists candle state on every tick so restarts don't lose the day's
    accumulated OHLC.

    Two persistence backends, chosen by which arguments are passed:
      - persist_path (default, unchanged behavior): saves to a local JSON
        file. Used by paper_trader.py when running locally.
      - save_fn / load_fn: optional callables for a different backend
        (e.g. Supabase, via execution.state_store) — used by run_daily.py
        on Render, where the local filesystem doesn't persist between
        cron runs. save_fn(dict_of_candles) -> None, load_fn() -> dict.
        When both are given, they take priority over persist_path.
    """

    def __init__(self, persist_path: str = None, save_fn=None, load_fn=None):
        self._persist_path = persist_path
        self._save_fn = save_fn
        self._load_fn = load_fn
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
        # reload from disk if file exists (handles restarts)
        if load_fn:
            try:
                saved = load_fn() or {}
                for sym, c in saved.items():
                    self._candles[sym] = c
                if saved:
                    print(f"📂 Reloaded OHLC state for {list(saved.keys())} from previous run")
            except Exception as e:
                print(f"⚠️  Could not reload OHLC state via load_fn: {e}")
        elif persist_path and Path(persist_path).exists():
            self._load()

    def _load(self):
        import json
        try:
            with open(self._persist_path) as f:
                saved = json.load(f)
            for sym, c in saved.items():
                self._candles[sym] = c
            print(f"📂 Reloaded OHLC state for {list(saved.keys())} from previous session")
        except Exception as e:
            print(f"⚠️  Could not reload OHLC state: {e}")

    def _save(self):
        if self._save_fn:
            try:
                self._save_fn(dict(self._candles))
            except Exception as e:
                print(f"⚠️  Could not save OHLC state via save_fn: {e}")
            return
        if not self._persist_path:
            return
        import json
        try:
            with open(self._persist_path, "w") as f:
                json.dump(dict(self._candles), f)
        except Exception as e:
            print(f"⚠️  Could not save OHLC state: {e}")

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

        # persist every tick so restarts don't lose OHLC state
        self._save()

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
