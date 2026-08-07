"""
Signal generation — combines candlestick patterns + indicators.

Prior trend and S/R are computed and shown as context in the
signal interpreter but are NOT hard gates — backtesting showed
they reduce performance on trending Nifty 50 stocks.

Checklist (need 3/4, pattern is mandatory gate):
  [MANDATORY] Candlestick pattern
  [CONFIRM]   Price > EMA20
  [CONFIRM]   RSI filter
  [CONFIRM]   Volume above average

Context columns available (not scored):
  prior_trend   — uptrend/downtrend/pullback/rally/sideways
  near_support  — True if price within 1.5% of support zone
  near_resistance — True if price within 1.5% of resistance zone
  nearest_sr_zone — nearest S/R price level

Reference: Varsity Module 2
"""
import pandas as pd
from strategy.indicators import add_all_indicators
from strategy.patterns   import add_all_patterns
from strategy.trend      import add_prior_trend


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    df = add_all_indicators(df)
    df = add_all_patterns(df)
    df = add_prior_trend(df)
    return df


def generate_signals(df: pd.DataFrame, min_confirmations: int = 3) -> pd.DataFrame:
    df = build_features(df.copy())

    bullish_pattern = (
        df["bullish_engulfing"] | df["bullish_marubozu"]
        | df["hammer"]          | df["bullish_harami"]
    )
    bearish_pattern = (
        df["bearish_engulfing"] | df["bearish_marubozu"]
        | df["shooting_star"]   | df["hanging_man"]
        | df["bearish_harami"]
    )

    # trend context — downtrend/pullback favors BUY, uptrend/rally favors SELL
    bullish_trend = df["prior_trend"].isin(["downtrend", "pullback"])
    bearish_trend = df["prior_trend"].isin(["uptrend", "rally"])

    long_score = (
        bullish_pattern.astype(int)
        + (df["close"] > df["ema20"]).astype(int)
        + (df["rsi"] < 60).astype(int)
        + df["above_avg_volume"].astype(int)
        + bullish_trend.astype(int)        # trend as 5th scored condition
    )

    short_score = (
        bearish_pattern.astype(int)
        + (df["close"] < df["ema20"]).astype(int)
        + (df["rsi"] > 40).astype(int)
        + df["above_avg_volume"].astype(int)
        + bearish_trend.astype(int)        # trend as 5th scored condition
    )

    df["signal"] = None
    df.loc[bullish_pattern & (long_score >= min_confirmations), "signal"] = "BUY"
    df.loc[bearish_pattern & (short_score >= min_confirmations), "signal"] = "SELL"
    return df
