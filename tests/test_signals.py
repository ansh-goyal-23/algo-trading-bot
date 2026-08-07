"""
Quick sanity check on synthetic OHLC data — no Kite API needed.
Run: python strategy/test_signals.py
"""
import numpy as np
import pandas as pd
from strategy.signals import generate_signals

np.random.seed(42)
n = 200
close = 100 + np.cumsum(np.random.randn(n))
open_ = close + np.random.randn(n) * 0.5
high = np.maximum(open_, close) + np.abs(np.random.randn(n))
low = np.minimum(open_, close) - np.abs(np.random.randn(n))
volume = np.random.randint(1000, 5000, n)

df = pd.DataFrame({
    "open": open_, "high": high, "low": low, "close": close, "volume": volume
})

result = generate_signals(df)
signals = result[result["signal"].notna()][["close", "rsi", "signal"]]
print(signals.tail(20))
print(f"\nTotal signals: {len(signals)} (BUY: {(signals['signal']=='BUY').sum()}, SELL: {(signals['signal']=='SELL').sum()})")
