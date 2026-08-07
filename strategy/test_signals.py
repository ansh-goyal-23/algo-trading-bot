"""
Quick sanity check on synthetic OHLC data.
Run: python -m strategy.test_signals
"""
import numpy as np
import pandas as pd
from strategy.signals import generate_signals

np.random.seed(42)
n = 200
close = 100 + np.cumsum(np.random.randn(n))
open_ = close + np.random.randn(n) * 0.5
high  = np.maximum(open_, close) + np.abs(np.random.randn(n))
low   = np.minimum(open_, close) - np.abs(np.random.randn(n))
volume= np.random.randint(1000, 5000, n)
dates = pd.date_range("2023-01-01", periods=n, freq="B")

df = pd.DataFrame({
    "date": dates, "open": open_, "high": high,
    "low": low, "close": close, "volume": volume
})

result = generate_signals(df)
signals = result[result["signal"].notna()][[
    "date", "close", "rsi", "prior_trend", "near_support", "near_resistance", "signal"
]]
print(signals)
print(f"\nTotal signals: {len(signals)} "
      f"(BUY: {(signals['signal']=='BUY').sum()}, "
      f"SELL: {(signals['signal']=='SELL').sum()})")
