"""
Combines candlestick patterns + indicators into BUY/SELL/None signals,
following the book's "grand checklist" idea (Module 2, §18.6):
require multiple confirming conditions, not one indicator alone.

Requires at least one candlestick pattern AND enough supporting
indicator confirmations - patterns are the trigger, indicators are the filter.
"""
import pandas as pd
from strategy.indicators import add_all_indicators
from strategy.patterns import add_all_patterns


def build_features(df):
    df = add_all_indicators(df.copy())
    df = add_all_patterns(df)
    return df


def generate_signals(df, min_confirmations=3):
    df = build_features(df)

    bullish_pattern = (
        df["bullish_engulfing"] | df["bullish_marubozu"]
        | df["hammer"] | df["bullish_harami"]
    )
    bearish_pattern = (
        df["bearish_engulfing"] | df["bearish_marubozu"]
        | df["shooting_star"] | df["hanging_man"] | df["bearish_harami"]
    )

    long_score = (
        bullish_pattern.astype(int)
        + (df["close"] > df["ema20"]).astype(int)
        + (df["rsi"] < 60).astype(int)
        + df["above_avg_volume"].astype(int)
    )

    short_score = (
        bearish_pattern.astype(int)
        + (df["close"] < df["ema20"]).astype(int)
        + (df["rsi"] > 40).astype(int)
        + df["above_avg_volume"].astype(int)
    )

    df["signal"] = None
    df.loc[bullish_pattern & (long_score >= min_confirmations), "signal"] = "BUY"
    df.loc[bearish_pattern & (short_score >= min_confirmations), "signal"] = "SELL"
    return df
