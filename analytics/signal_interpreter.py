"""
Signal Interpreter.

Explains in plain English why a signal fired — which conditions passed,
what candlestick pattern was detected, and what the book says about it.

Works on:
  - Historical backtest trade logs (trade_history.csv)
  - Live paper trading signals (generated at 3:20 PM)

Usage:
    python -m analytics.signal_interpreter reports/RUN_XXXXXXXX_XXXXXX/trade_history.csv
    python -m analytics.signal_interpreter reports/paper_trading/paper_trades_YYYYMMDD.csv
"""

import sys
import pandas as pd
import numpy as np
from pathlib import Path

# Book reference: Varsity Module 2 pattern descriptions
PATTERN_BOOK = {
    "bullish_engulfing": {
        "name":   "Bullish Engulfing",
        "chapter":"Chapter 6",
        "meaning":"A large bullish candle completely engulfs the previous bearish candle. "
                  "Signals strong reversal of downtrend. Bulls have overpowered bears.",
        "bias":   "Strongly Bullish",
    },
    "bullish_marubozu": {
        "name":   "Bullish Marubozu",
        "chapter":"Chapter 5",
        "meaning":"A long bullish candle with no wicks. Opens at low, closes at high. "
                  "Bulls in complete control throughout the session.",
        "bias":   "Strongly Bullish",
    },
    "hammer": {
        "name":   "Hammer",
        "chapter":"Chapter 6",
        "meaning":"Small body at top, long lower wick. Sellers pushed price down but "
                  "buyers recovered strongly. Bullish reversal at support.",
        "bias":   "Bullish Reversal",
    },
    "bullish_harami": {
        "name":   "Bullish Harami",
        "chapter":"Chapter 7",
        "meaning":"Small bullish candle inside a larger bearish candle. Downtrend losing "
                  "momentum. Early sign of reversal but needs confirmation.",
        "bias":   "Mildly Bullish",
    },
    "bearish_engulfing": {
        "name":   "Bearish Engulfing",
        "chapter":"Chapter 6",
        "meaning":"A large bearish candle completely engulfs the previous bullish candle. "
                  "Signals strong reversal of uptrend. Bears overpowering bulls.",
        "bias":   "Strongly Bearish — EXIT signal",
    },
    "bearish_marubozu": {
        "name":   "Bearish Marubozu",
        "chapter":"Chapter 5",
        "meaning":"Long bearish candle with no wicks. Bears in complete control. "
                  "Strong signal to exit long positions.",
        "bias":   "Strongly Bearish — EXIT signal",
    },
    "shooting_star": {
        "name":   "Shooting Star",
        "chapter":"Chapter 6",
        "meaning":"Small body at bottom, long upper wick. Buyers tried to push price up "
                  "but sellers crushed the rally. Bearish reversal at resistance.",
        "bias":   "Bearish Reversal — EXIT signal",
    },
    "hanging_man": {
        "name":   "Hanging Man",
        "chapter":"Chapter 6",
        "meaning":"Hammer shape appearing in an uptrend. Warning that bulls are losing "
                  "control. Potential top formation.",
        "bias":   "Bearish Warning — EXIT signal",
    },
    "bearish_harami": {
        "name":   "Bearish Harami",
        "chapter":"Chapter 7",
        "meaning":"Small bearish candle inside a larger bullish candle. Uptrend losing "
                  "momentum. Early reversal warning.",
        "bias":   "Mildly Bearish — EXIT signal",
    },
}

INDICATOR_EXPLANATIONS = {
    "ema_above": "Price is above the 20-day EMA → stock is in a short-term uptrend (Varsity Ch.13)",
    "ema_below": "Price is below the 20-day EMA → stock is in a short-term downtrend",
    "rsi_buy":   "RSI < 60 → momentum not yet overbought, room to run (Varsity Ch.14)",
    "rsi_sell":  "RSI > 40 → momentum not yet oversold enough to hold",
    "vol_above": "Volume above 20-day average → institutional participation confirms the move (Varsity Ch.12)",
    "vol_below": "Volume below average → weak conviction, treat signal with caution",
}


def interpret_live_signal(
    symbol: str,
    signal: str,
    close: float,
    rsi: float,
    ema20: float,
    above_avg_volume: bool,
    pattern_flags: dict,
    winning_trade: bool = None,
    pnl: float = None,
) -> str:
    lines = []
    lines.append(f"\n{'='*60}")
    lines.append(f"  SIGNAL INTERPRETATION: {symbol}")
    lines.append(f"{'='*60}")
    lines.append(f"  Signal   : {'🟢 BUY' if signal == 'BUY' else '🔴 SELL/EXIT'}")
    lines.append(f"  Price    : ₹{close:.2f}")
    lines.append(f"  RSI      : {rsi:.1f}")
    lines.append(f"  EMA20    : ₹{ema20:.2f}")
    lines.append(f"  Volume   : {'Above average ✓' if above_avg_volume else 'Below average ✗'}")

    if pnl is not None:
        outcome = "✅ Winner" if winning_trade else "❌ Loser"
        lines.append(f"  Outcome  : {outcome} | PnL ₹{pnl:,.2f}")

    # which pattern fired
    lines.append(f"\n  📖 Candlestick Pattern:")
    fired = [k for k, v in pattern_flags.items() if v and k in PATTERN_BOOK]
    if fired:
        for pat in fired:
            info = PATTERN_BOOK[pat]
            lines.append(f"    Pattern : {info['name']} ({info['chapter']})")
            lines.append(f"    Meaning : {info['meaning']}")
            lines.append(f"    Bias    : {info['bias']}")
    else:
        lines.append(f"    No named pattern detected — signal from indicators only")

    # indicator checklist
    lines.append(f"\n  📊 Indicator Checklist (need 3/4):")
    score = 0

    pat_pass = bool(fired)
    lines.append(f"    [{'✓' if pat_pass else '✗'}] Candlestick pattern")
    if pat_pass: score += 1

    ema_pass = close > ema20
    lines.append(f"    [{'✓' if ema_pass else '✗'}] Price > EMA20  — "
                 f"{INDICATOR_EXPLANATIONS['ema_above' if ema_pass else 'ema_below']}")
    if ema_pass: score += 1

    rsi_pass = rsi < 60 if signal == "BUY" else rsi > 40
    lines.append(f"    [{'✓' if rsi_pass else '✗'}] RSI filter     — "
                 f"{INDICATOR_EXPLANATIONS['rsi_buy' if signal == 'BUY' else 'rsi_sell']}")
    if rsi_pass: score += 1

    vol_pass = above_avg_volume
    lines.append(f"    [{'✓' if vol_pass else '✗'}] Volume filter  — "
                 f"{INDICATOR_EXPLANATIONS['vol_above' if vol_pass else 'vol_below']}")
    if vol_pass: score += 1

    lines.append(f"\n  Conditions met: {score}/4 "
                 f"({'✅ Signal valid' if score >= 3 else '⚠️  Weak signal'})")

    # trend context
    prior_trend = pattern_flags.get('prior_trend', 'unknown')
    trend_emoji = {
        'uptrend': '📈', 'downtrend': '📉',
        'pullback': '🔄', 'rally': '🔄', 'sideways': '➡️'
    }.get(prior_trend, '❓')
    lines.append(f"\n  📈 Trend Context:")
    lines.append(f"    Prior Trend  : {trend_emoji} {prior_trend}")
    trend_aligned = (
        (signal == 'BUY'  and prior_trend in ('downtrend', 'pullback')) or
        (signal == 'SELL' and prior_trend in ('uptrend', 'rally'))
    )
    lines.append(f"    Trend aligned: {'✅ Yes — higher conviction' if trend_aligned else '⚠️  No — trade against trend context'}")

    # risk parameters
    if signal == "BUY":
        stop = round(close * 0.98, 2)
        target_1r = round(close * 1.04, 2)   # 2:1 RRR
        target_2r = round(close * 1.06, 2)   # 3:1 RRR
        lines.append(f"\n  🎯 Trade Plan:")
        lines.append(f"    Entry      : ₹{close:.2f}")
        lines.append(f"    Stop Loss  : ₹{stop:.2f} (-2%)")
        lines.append(f"    Target 2:1 : ₹{target_1r:.2f} (+4%)")
        lines.append(f"    Target 3:1 : ₹{target_2r:.2f} (+6%)")
        lines.append(f"    Risk/Reward: Follow the 2:1 minimum rule (Varsity Ch.18)")

    lines.append("")
    return "\n".join(lines)


def analyze_historical(trade_history_path: str):
    """Analyze best and worst historical signals from trade_history.csv"""
    path = Path(trade_history_path)
    if not path.exists():
        print(f"No trade file found at {path}")
        return
    df = pd.read_csv(path)
    if df.empty or "stock" not in df.columns:
        print(f"No trades recorded yet in {path.name} — no signals fired today.")
        return
    df["entry_date"] = pd.to_datetime(df["entry_date"])
    df["exit_date"]  = pd.to_datetime(df["exit_date"])

    print(f"\n{'='*60}")
    print("  HISTORICAL SIGNAL ANALYSIS")
    print(f"{'='*60}")
    print(f"  Source: {path.name}")
    print(f"  Trades: {len(df)} across {df['stock'].nunique()} stocks\n")

    # best 5 trades
    best = df.nlargest(5, "pnl")
    print("🏆 TOP 5 BEST SIGNALS:\n")
    for _, row in best.iterrows():
        held = (pd.to_datetime(row["exit_date"]) - pd.to_datetime(row["entry_date"])).days
        print(f"  {row['stock']:12s} | Entry {row['entry_date'].date()} @ ₹{row['entry_price']:.2f} "
              f"→ Exit @ ₹{row['exit_price']:.2f} | "
              f"Held {held}d | PnL ₹{row['pnl']:,.2f} | Exit: {row['exit_reason']}")

    # worst 5 trades
    worst = df.nsmallest(5, "pnl")
    print("\n💀 TOP 5 WORST SIGNALS:\n")
    for _, row in worst.iterrows():
        held = (pd.to_datetime(row["exit_date"]) - pd.to_datetime(row["entry_date"])).days
        print(f"  {row['stock']:12s} | Entry {row['entry_date'].date()} @ ₹{row['entry_price']:.2f} "
              f"→ Exit @ ₹{row['exit_price']:.2f} | "
              f"Held {held}d | PnL ₹{row['pnl']:,.2f} | Exit: {row['exit_reason']}")

    # per-stock signal quality
    print("\n📊 PER-STOCK SIGNAL QUALITY:\n")
    stats = df.groupby("stock").agg(
        trades     =("pnl", "count"),
        winners    =("pnl", lambda x: (x > 0).sum()),
        total_pnl  =("pnl", "sum"),
        avg_win    =("pnl", lambda x: x[x > 0].mean() if (x > 0).any() else 0),
        avg_loss   =("pnl", lambda x: x[x <= 0].mean() if (x <= 0).any() else 0),
        best_trade =("pnl", "max"),
        worst_trade=("pnl", "min"),
        avg_hold   =("holding_days", "mean"),
        stop_hits  =("exit_reason", lambda x: (x == "STOP_LOSS").sum()),
    ).reset_index()

    stats["win_rate"]   = round(stats["winners"] / stats["trades"] * 100, 1)
    stats["stop_rate"]  = round(stats["stop_hits"] / stats["trades"] * 100, 1)
    stats["total_pnl"]  = stats["total_pnl"].round(2)
    stats["avg_hold"]   = stats["avg_hold"].round(1)
    stats = stats.sort_values("total_pnl", ascending=False)

    print(stats[[
        "stock", "trades", "win_rate", "total_pnl",
        "best_trade", "worst_trade", "avg_hold", "stop_rate"
    ]].to_string(index=False))

    # exit reason breakdown
    print("\n📋 EXIT REASON BREAKDOWN:\n")
    exits = df.groupby(["stock","exit_reason"])["pnl"].agg(
        count="count", total_pnl="sum"
    ).reset_index()
    exits["total_pnl"] = exits["total_pnl"].round(2)
    print(exits.sort_values(["stock","exit_reason"]).to_string(index=False))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m analytics.signal_interpreter <trade_history.csv>")
        sys.exit(1)
    analyze_historical(sys.argv[1])
