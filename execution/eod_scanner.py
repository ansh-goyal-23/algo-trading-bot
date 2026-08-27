"""
End-of-Day Signal Scanner.

Run this at 3:10-3:15 PM daily instead of keeping the paper trader
running all day — before the CAS auction starts at 3:15 PM (SEBI
change Aug 3 2026). Fetches today's OHLC via Kotak Neo quotes API,
appends to historical data, runs signals, logs paper orders.

NOTE: this checks stop-loss AND the +4%/+6% partial-exit targets
against today's OHLC (via execution.portfolio.check_position_exit),
same rules paper_trader.py applies tick-by-tick. If positions are
open, prefer running paper_trader.py for continuous intraday
monitoring — this EOD-bar check can only catch a stop/target breach
once per day, using the day's low/high as a proxy for intraday price.

Usage:
    source venv/bin/activate
    python -m execution.eod_scanner

Stop loss monitoring: only needed once you have open positions.
"""

import os
import sys
import json
import subprocess
import pandas as pd
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from execution.portfolio import (
    PORTFOLIO, STOP_LOSS_PCT, RISK_PER_TRADE,
    get_position_size, login, check_position_exit,
)

load_dotenv(dotenv_path=os.path.expanduser("~/Documents/algo-trading-bot/.env"))

# ── config ─────────────────────────────────────────────────────────────────
LOG_DIR        = Path("reports/paper_trading")
LOG_DIR.mkdir(parents=True, exist_ok=True)
SESSION_DATE   = datetime.now().strftime("%Y%m%d")
LOG_FILE       = LOG_DIR / f"paper_trades_{SESSION_DATE}.csv"
POSITION_FILE  = LOG_DIR / "open_positions.csv"

# ── state ──────────────────────────────────────────────────────────────────
positions    = {}
paper_trades = []

if POSITION_FILE.exists():
    pos_df = pd.read_csv(POSITION_FILE)
    for _, row in pos_df.iterrows():
        positions[row["symbol"]] = {
            "entry_price":       row["entry_price"],
            "quantity":          row["quantity"],
            "stop_price":        row["stop_price"],
            "entry_date":        row["entry_date"],
            "partial_exit_done": bool(row.get("partial_exit_done", False)),
        }
    if positions:
        print(f"📂 Open positions loaded:")
        for sym, pos in positions.items():
            print(f"  {sym} @ ₹{pos['entry_price']} | stop ₹{pos['stop_price']}")

if LOG_FILE.exists():
    existing = pd.read_csv(LOG_FILE)
    if not existing.empty and "action" in existing.columns:
        paper_trades = existing.to_dict("records")
else:
    pd.DataFrame(columns=[
        "date","timestamp","action","symbol","price","quantity","reason"
    ]).to_csv(LOG_FILE, index=False)


def save_positions():
    if positions:
        pd.DataFrame([{"symbol": s, **p} for s, p in positions.items()]).to_csv(
            POSITION_FILE, index=False)
    elif POSITION_FILE.exists():
        POSITION_FILE.unlink()


def log_paper_order(action, symbol, price, quantity, reason=""):
    record = {
        "date":      datetime.now().strftime("%Y-%m-%d"),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action":    action,
        "symbol":    symbol,
        "price":     round(price, 2),
        "quantity":  quantity,
        "reason":    reason,
    }
    paper_trades.append(record)
    pd.DataFrame(paper_trades).to_csv(LOG_FILE, index=False)
    save_positions()
    emoji = "🟢" if action == "BUY" else "🔴"
    print(f"{emoji} PAPER {action} | {symbol} @ ₹{price:.2f} x {quantity} | {reason}")


def fetch_today_ohlc_kotak(client) -> dict:
    """Fetch today's OHLC via Kotak Neo quotes API."""
    ohlc = {}
    for stock in PORTFOLIO:
        try:
            results = client.search_scrip(exchange_segment="nse_cm", symbol=stock)
            if not results:
                continue
            match = next(
                (r for r in results if r.get("pGroup") == "EQ" and r.get("pSymbolName") == stock),
                None,
            )
            if match is None:
                raise ValueError(f"No exact EQ match found for symbol '{stock}'")
            token = str(match["pSymbol"])
            quote = client.quotes(
                instrument_tokens=[{"instrument_token": token, "exchange_segment": "nse_cm"}],
                quote_type="ohlc"
            )
            data = quote if isinstance(quote, list) else quote.get("data", [quote])
            if not data:
                continue
            q = data[0] if isinstance(data, list) else data
            # Kotak nests OHLC inside q['ohlc'], LTP at q['ltp']
            ohlc_data = q.get("ohlc", {})
            ltp        = float(q.get("ltp", 0))
            open_p     = float(ohlc_data.get("open",  0))
            high_p     = float(ohlc_data.get("high",  0))
            low_p      = float(ohlc_data.get("low",   0))
            # use LTP as close (real-time price), not ohlc['close'] which is open price
            close_p    = ltp if ltp > 0 else float(ohlc_data.get("close", 0))
            volume     = int(q.get("last_volume", q.get("volume", 0)))
            ohlc[stock] = {
                "date":   datetime.now().strftime("%Y-%m-%d"),
                "open":   open_p,
                "high":   high_p,
                "low":    low_p,
                "close":  close_p,
                "volume": volume,
            }
        except Exception as e:
            print(f"  ⚠️  {stock} (Kotak): {e}")
    return ohlc


def fetch_today_ohlc_yfinance() -> dict:
    """Fallback: fetch today's OHLC via yfinance."""
    import subprocess, json
    script = """
import sys, json
sys.path.insert(0, '.')
import yfinance as yf
from datetime import datetime
symbols = """ + str(list(PORTFOLIO.keys())) + """
result = {}
for sym in symbols:
    try:
        df = yf.download(sym + '.NS', period='2d', interval='1d', progress=False)
        if df.empty:
            continue
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        last = df.iloc[-1]
        result[sym] = {
            'date':   str(df.index[-1].date()),
            'open':   float(last['Open']),
            'high':   float(last['High']),
            'low':    float(last['Low']),
            'close':  float(last['Close']),
            'volume': int(last['Volume']),
        }
    except Exception as e:
        pass
print(json.dumps(result))
"""
    venv_python = Path("venv-data/bin/python")
    r = subprocess.run([str(venv_python), "-c", script],
                       capture_output=True, text=True, cwd=".")
    if r.returncode != 0:
        return {}
    try:
        return json.loads(r.stdout.strip())
    except:
        return {}


def fetch_today_ohlc(client) -> dict:
    """
    Fetch today's OHLC — tries Kotak Neo first, falls back to yfinance.
    Filters out any stocks with zero/invalid prices.
    """
    print("\n📡 Fetching today's OHLC from Kotak Neo...")
    ohlc = fetch_today_ohlc_kotak(client)

    # filter valid entries
    valid = {s: d for s, d in ohlc.items() if d["close"] > 0 and d["open"] > 0}
    invalid = set(PORTFOLIO.keys()) - set(valid.keys())

    if invalid:
        print(f"  ⚠️  Kotak returned zeros for {invalid} — falling back to yfinance...")
        yf_data = fetch_today_ohlc_yfinance()
        for sym in invalid:
            if sym in yf_data and yf_data[sym]["close"] > 0:
                valid[sym] = yf_data[sym]
                print(f"  ✅ {sym}: fetched from yfinance")

    # print summary
    print("\n  Today's OHLC:")
    for stock, c in valid.items():
        chg = round((c["close"] - c["open"]) / c["open"] * 100, 2) if c["open"] else 0
        direction = "🟢" if chg >= 0 else "🔴"
        print(f"  {stock:12s} | O={c['open']:.2f} H={c['high']:.2f} "
              f"L={c['low']:.2f} C={c['close']:.2f} | {direction} {chg:+.2f}%")

    return valid


def run_signal_scan(today_ohlc: dict):
    """
    Fetch 6 months historical data, append today's OHLC,
    run generate_signals() via venv-data python.
    """
    print("\n🔍 Running signal scan...")

    script = f"""
import sys
sys.path.insert(0, '.')
import yfinance as yf
import pandas as pd
import json
from strategy.signals import generate_signals

today_candles = {json.dumps(today_ohlc)}
results = {{}}

for sym, today in today_candles.items():
    try:
        ticker = sym + '.NS'
        df = yf.download(ticker, period='6mo', interval='1d', progress=False)
        if df.empty:
            results[sym] = {{'signal': 'ERROR', 'error': 'No data'}}
            continue

        df = df.reset_index()
        df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
        df = df[['date','open','high','low','close','volume']]

        today_row = pd.DataFrame([{{
            'date':   today['date'],
            'open':   today['open'],
            'high':   today['high'],
            'low':    today['low'],
            'close':  today['close'],
            'volume': today['volume'],
        }}])
        today_row['date'] = pd.to_datetime(today_row['date'])
        df['date'] = pd.to_datetime(df['date'])
        df = pd.concat([df, today_row], ignore_index=True)
        df = df.drop_duplicates(subset='date', keep='last').sort_values('date').reset_index(drop=True)

        sig_df = generate_signals(df)
        last   = sig_df.iloc[-1]

        pattern_cols = ['bullish_engulfing','bullish_marubozu','hammer','bullish_harami',
                        'bearish_engulfing','bearish_marubozu','shooting_star',
                        'hanging_man','bearish_harami']
        patterns = {{col: bool(last.get(col, False)) for col in pattern_cols}}

        # add trend context
        patterns['prior_trend'] = str(last.get('prior_trend', 'unknown'))

        results[sym] = {{
            'signal':           str(last.get('signal', 'None')),
            'close':            float(last['close']),
            'rsi':              float(last['rsi'])   if 'rsi'   in last.index else 0,
            'ema20':            float(last['ema20']) if 'ema20' in last.index else 0,
            'above_avg_volume': bool(last.get('above_avg_volume', False)),
            'patterns':         patterns,
        }}
    except Exception as e:
        results[sym] = {{'signal': 'ERROR', 'error': str(e)}}

print(json.dumps(results))
"""

    venv_python = Path("venv-data/bin/python")
    result = subprocess.run(
        [str(venv_python), "-c", script],
        capture_output=True, text=True, cwd="."
    )

    if result.returncode != 0:
        print("Signal scan error:", result.stderr[-500:])
        return

    try:
        signals = json.loads(result.stdout.strip())
    except Exception as e:
        print(f"Failed to parse signal output: {e}")
        return

    print("\n📊 Signal scan results:")
    for sym, data in signals.items():
        sig   = data.get("signal", "None")
        close = data.get("close", 0)
        rsi   = data.get("rsi",   0)
        ema20 = data.get("ema20", 0)
        vol   = data.get("above_avg_volume", False)
        pats  = data.get("patterns", {})

        from analytics.signal_interpreter import interpret_live_signal
        interp = interpret_live_signal(
            symbol=sym, signal=sig if sig != "None" else "HOLD",
            close=close, rsi=rsi, ema20=ema20,
            above_avg_volume=vol, pattern_flags=pats,
        )
        print(interp)

        ltp = close

        if sig == "BUY" and sym not in positions:
            qty = get_position_size(sym, ltp)
            if qty < 1:
                print(f"  ⚠️  {sym}: BUY signal but 1 share (₹{ltp:.2f}) exceeds allocated capital — skipping")
                continue
            stop_price = round(ltp * (1 - STOP_LOSS_PCT), 2)
            positions[sym] = {
                "entry_price": ltp,
                "quantity":    qty,
                "stop_price":  stop_price,
                "entry_date":  datetime.now().strftime("%Y-%m-%d"),
            }
            log_paper_order("BUY", sym, ltp, qty,
                            f"SIGNAL | stop@{stop_price} | RSI={rsi:.1f}")

        elif sig == "SELL" and sym in positions:
            pos = positions.pop(sym)
            pnl = round((ltp - pos["entry_price"]) * pos["quantity"], 2)
            log_paper_order("SELL", sym, ltp, pos["quantity"],
                            f"SIGNAL_EXIT | PnL=₹{pnl}")

        elif sig == "SELL" and sym not in positions:
            print(f"  ℹ️  {sym}: SELL signal but no open position — no action (long-only)")


def check_stop_losses(today_ohlc: dict):
    """
    Check stop-loss and +4%/+6% partial-exit targets on open positions
    using today's low/high as a proxy for intraday price (only one check
    per day — paper_trader.py's tick monitoring is more accurate).
    Exit fills are assumed at the trigger level (stop/target price) since
    the exact intrabar fill isn't known from an OHLC bar.
    """
    if not positions:
        return
    print("\n🛡️  Checking stop losses and targets on open positions...")
    for sym, pos in list(positions.items()):
        if sym not in today_ohlc:
            continue
        entry = pos["entry_price"]
        low   = today_ohlc[sym]["low"]
        high  = today_ohlc[sym]["high"]
        close = today_ohlc[sym]["close"]

        result = check_position_exit(pos, low=low, high=high, close=close)
        if result is None:
            print(f"  ✅ {sym} | low={low:.2f} > stop={pos['stop_price']:.2f} — position safe")
            continue

        action, qty, trigger_price = result["action"], result["quantity"], result["trigger_price"]

        if action == "STOP":
            pnl = round((trigger_price - entry) * qty, 2)
            print(f"🚨 STOP LOSS HIT | {sym} | low={low} <= stop={pos['stop_price']} | PnL ₹{pnl}")
            positions.pop(sym)
            log_paper_order("SELL", sym, trigger_price, qty, f"STOP_LOSS | PnL=₹{pnl}")

        elif action == "TARGET1_PARTIAL":
            pnl = round((trigger_price - entry) * qty, 2)
            print(f"🎯 TARGET 1 HIT (+4%) | {sym} | high={high:.2f} >= {trigger_price} | Selling {qty} shares | PnL ₹{pnl}")
            log_paper_order("SELL", sym, trigger_price, qty,
                            f"TARGET_1_PARTIAL | PnL=₹{pnl} | stop moved to breakeven")

        elif action == "TARGET1_PROTECT":
            print(f"🎯 TARGET 1 HIT (+4%) | {sym} | qty=1, holding full position | stop moved to breakeven")
            save_positions()

        elif action == "TARGET2":
            pnl = round((trigger_price - entry) * qty, 2)
            print(f"🎯 TARGET 2 HIT (+6%) | {sym} | high={high:.2f} >= {trigger_price} | Full exit | PnL ₹{pnl}")
            positions.pop(sym)
            log_paper_order("SELL", sym, trigger_price, qty, f"TARGET_2_FULL | PnL=₹{pnl}")


def main():
    print("=" * 55)
    print("  EOD SIGNAL SCANNER — 3:10 PM")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    client     = login()
    today_ohlc = fetch_today_ohlc(client)

    # filter out stocks with zero/invalid OHLC (market closed or API error)
    today_ohlc = {
        sym: data for sym, data in today_ohlc.items()
        if data["close"] > 0 and data["open"] > 0
    }
    if not today_ohlc:
        print("⚠️  No valid OHLC data — market may be closed or run after 3:30 PM.")
        print("    EOD scanner should be run between 3:10–3:15 PM IST, before the CAS auction.")
        return

    # check stop losses first using today's low
    check_stop_losses(today_ohlc)

    # run signal scan
    run_signal_scan(today_ohlc)

    print(f"\n✅ Scan complete.")
    print(f"Open positions: {list(positions.keys()) or 'None'}")
    print(f"Log saved → {LOG_FILE}")


if __name__ == "__main__":
    main()
