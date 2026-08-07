"""
Technical indicators from Varsity Module 2:
- Moving averages (§13)
- RSI (§14)
- Bollinger Bands (§15)
"""
import pandas as pd
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands


def add_moving_averages(df, short=20, long=50):
    df[f"ema{short}"] = df["close"].ewm(span=short, adjust=False).mean()
    df[f"ema{long}"] = df["close"].ewm(span=long, adjust=False).mean()
    return df


def add_rsi(df, window=14):
    df["rsi"] = RSIIndicator(df["close"], window=window).rsi()
    return df


def add_bollinger_bands(df, window=20, window_dev=2):
    bb = BollingerBands(df["close"], window=window, window_dev=window_dev)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_mid"] = bb.bollinger_mavg()
    return df


def add_volume_avg(df, window=20):
    df["vol_avg"] = df["volume"].rolling(window).mean()
    df["above_avg_volume"] = df["volume"] > df["vol_avg"]
    return df


def add_all_indicators(df):
    df = add_moving_averages(df)
    df = add_rsi(df)
    df = add_bollinger_bands(df)
    df = add_volume_avg(df)
    return df
