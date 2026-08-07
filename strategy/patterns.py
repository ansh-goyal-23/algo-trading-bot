"""
Candlestick pattern detection, from Varsity Module 2 chapters 5-10:
Marubozu, Hammer/Hanging Man, Shooting Star, Engulfing, Harami, Doji.

Each function returns a boolean Series aligned to df.index.
Patterns that need the prior candle (engulfing, harami) use .shift(1).
"""
import pandas as pd
import numpy as np


def _body(df):
    return (df["close"] - df["open"]).abs()


def _range(df):
    return df["high"] - df["low"]


def _upper_wick(df):
    return df["high"] - df[["open", "close"]].max(axis=1)


def _lower_wick(df):
    return df[["open", "close"]].min(axis=1) - df["low"]


def is_bullish_marubozu(df, wick_tolerance=0.05):
    rng = _range(df)
    body = _body(df)
    small_wicks = (_upper_wick(df) < wick_tolerance * rng) & (_lower_wick(df) < wick_tolerance * rng)
    return (df["close"] > df["open"]) & (body > 0.9 * rng) & small_wicks


def is_bearish_marubozu(df, wick_tolerance=0.05):
    rng = _range(df)
    body = _body(df)
    small_wicks = (_upper_wick(df) < wick_tolerance * rng) & (_lower_wick(df) < wick_tolerance * rng)
    return (df["close"] < df["open"]) & (body > 0.9 * rng) & small_wicks


def is_doji(df, body_tolerance=0.1):
    rng = _range(df)
    body = _body(df)
    return body < body_tolerance * rng


def is_hammer(df):
    # small body near top of range, long lower wick, little/no upper wick
    rng = _range(df)
    body = _body(df)
    return (
        (_lower_wick(df) > 2 * body)
        & (_upper_wick(df) < 0.2 * rng)
        & (body < 0.4 * rng)
    )


def is_hanging_man(df, prior_uptrend):
    # same shape as hammer, but appears after an uptrend -> bearish reversal
    return is_hammer(df) & prior_uptrend


def is_shooting_star(df):
    rng = _range(df)
    body = _body(df)
    return (
        (_upper_wick(df) > 2 * body)
        & (_lower_wick(df) < 0.2 * rng)
        & (body < 0.4 * rng)
    )


def is_bullish_engulfing(df):
    prev_open = df["open"].shift(1)
    prev_close = df["close"].shift(1)
    prev_bearish = prev_close < prev_open
    curr_bullish = df["close"] > df["open"]
    engulfs = (df["open"] <= prev_close) & (df["close"] >= prev_open)
    return prev_bearish & curr_bullish & engulfs


def is_bearish_engulfing(df):
    prev_open = df["open"].shift(1)
    prev_close = df["close"].shift(1)
    prev_bullish = prev_close > prev_open
    curr_bearish = df["close"] < df["open"]
    engulfs = (df["open"] >= prev_close) & (df["close"] <= prev_open)
    return prev_bullish & curr_bearish & engulfs


def is_bullish_harami(df):
    prev_open = df["open"].shift(1)
    prev_close = df["close"].shift(1)
    prev_bearish = prev_close < prev_open
    curr_bullish = df["close"] > df["open"]
    inside = (df["open"] >= prev_close) & (df["close"] <= prev_open)
    return prev_bearish & curr_bullish & inside


def is_bearish_harami(df):
    prev_open = df["open"].shift(1)
    prev_close = df["close"].shift(1)
    prev_bullish = prev_close > prev_open
    curr_bearish = df["close"] < df["open"]
    inside = (df["open"] <= prev_close) & (df["close"] >= prev_open)
    return prev_bullish & curr_bearish & inside


def add_all_patterns(df):
    uptrend = df["close"] > df["close"].shift(3)  # crude 3-bar trend proxy

    df["bullish_marubozu"] = is_bullish_marubozu(df)
    df["bearish_marubozu"] = is_bearish_marubozu(df)
    df["doji"] = is_doji(df)
    df["hammer"] = is_hammer(df)
    df["hanging_man"] = is_hanging_man(df, uptrend)
    df["shooting_star"] = is_shooting_star(df)
    df["bullish_engulfing"] = is_bullish_engulfing(df)
    df["bearish_engulfing"] = is_bearish_engulfing(df)
    df["bullish_harami"] = is_bullish_harami(df)
    df["bearish_harami"] = is_bearish_harami(df)
    return df
