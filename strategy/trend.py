"""
Prior Trend Detection.

For swing trading on trending stocks/ETFs, we detect:
- UPTREND      : series of higher highs + higher lows (full uptrend)
- DOWNTREND    : series of lower highs + lower lows (full downtrend)  
- PULLBACK     : short-term dip within a larger uptrend (valid BUY context)
- RALLY        : short-term bounce within a larger downtrend (valid SELL context)
- SIDEWAYS     : no clear trend

Bullish patterns valid in: DOWNTREND or PULLBACK
Bearish patterns valid in: UPTREND or RALLY

Reference: Varsity Module 2, Ch.5-7
"""

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema


SWING_ORDER       = 3    # bars each side to qualify as swing point
MIN_SWING_POINTS  = 2    # minimum swing points to classify trend
LONG_LOOKBACK     = 20   # candles for long-term trend
SHORT_LOOKBACK    = 5    # candles for short-term pullback detection
PULLBACK_PCT      = 0.03 # 3% decline from recent high = pullback


def find_swing_highs(series: pd.Series, order: int = SWING_ORDER) -> np.ndarray:
    return argrelextrema(series.values, np.greater_equal, order=order)[0]


def find_swing_lows(series: pd.Series, order: int = SWING_ORDER) -> np.ndarray:
    return argrelextrema(series.values, np.less_equal, order=order)[0]


def classify_long_trend(close: pd.Series, lookback: int = LONG_LOOKBACK) -> str:
    """Classifies long-term trend using swing highs/lows."""
    if len(close) < lookback + SWING_ORDER * 2:
        return "sideways"

    window = close.iloc[-(lookback + SWING_ORDER * 2):].reset_index(drop=True)
    cutoff = len(window) - lookback

    high_idx   = find_swing_highs(window)
    low_idx    = find_swing_lows(window)

    highs = window.iloc[high_idx[high_idx >= cutoff]].values
    lows  = window.iloc[low_idx[low_idx   >= cutoff]].values

    if len(highs) < MIN_SWING_POINTS or len(lows) < MIN_SWING_POINTS:
        return "sideways"

    highs_rising  = all(highs[i] < highs[i+1] for i in range(len(highs)-1))
    highs_falling = all(highs[i] > highs[i+1] for i in range(len(highs)-1))
    lows_rising   = all(lows[i]  < lows[i+1]  for i in range(len(lows)-1))
    lows_falling  = all(lows[i]  > lows[i+1]  for i in range(len(lows)-1))

    if highs_rising  and lows_rising:  return "uptrend"
    if highs_falling and lows_falling: return "downtrend"
    return "sideways"


def is_pullback(close: pd.Series, lookback: int = SHORT_LOOKBACK) -> bool:
    """
    Detects a short-term pullback within a larger uptrend.
    True if price has declined >= PULLBACK_PCT from its recent high
    over the last `lookback` candles.
    """
    if len(close) < lookback + 1:
        return False
    recent = close.iloc[-(lookback+1):]
    recent_high = recent.max()
    current     = recent.iloc[-1]
    return (recent_high - current) / recent_high >= PULLBACK_PCT


def is_rally(close: pd.Series, lookback: int = SHORT_LOOKBACK) -> bool:
    """
    Detects a short-term rally within a larger downtrend.
    True if price has risen >= PULLBACK_PCT from its recent low.
    """
    if len(close) < lookback + 1:
        return False
    recent = close.iloc[-(lookback+1):]
    recent_low = recent.min()
    current    = recent.iloc[-1]
    return (current - recent_low) / recent_low >= PULLBACK_PCT


def classify_trend(close: pd.Series) -> str:
    """
    Full trend classification combining long-term and short-term context.

    Returns one of: uptrend, downtrend, pullback, rally, sideways
    """
    long_trend = classify_long_trend(close)

    if long_trend == "uptrend":
        if is_pullback(close):
            return "pullback"   # short dip in uptrend = valid BUY context
        return "uptrend"

    if long_trend == "downtrend":
        if is_rally(close):
            return "rally"      # short bounce in downtrend = valid SELL context
        return "downtrend"

    # sideways — check for short-term pullback/rally anyway
    if is_pullback(close):
        return "pullback"
    if is_rally(close):
        return "rally"

    return "sideways"


def add_prior_trend(df: pd.DataFrame) -> pd.DataFrame:
    """Adds 'prior_trend' column to dataframe."""
    trends = []
    for i in range(len(df)):
        if i < LONG_LOOKBACK + SWING_ORDER * 2:
            trends.append("sideways")
        else:
            window = df["close"].iloc[:i]
            trends.append(classify_trend(window))
    df["prior_trend"] = trends
    return df
