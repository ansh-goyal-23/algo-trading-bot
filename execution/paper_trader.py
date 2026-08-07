"""
Paper Trader — Positional Strategy.

Workflow:
  9:15 AM → 3:20 PM   Live feed: collect ticks, monitor stop losses
  3:20 PM             Build OHLC from ticks → run signals → log paper orders
  Positions carry overnight. Long-only (no shorting on cash equity).

Usage:
    source venv/bin/activate
    python -m execution.paper_trader
"""

import os
import sys
import time
import json
import pyotp
import subprocess
import pandas as pd
from datetime import datetime, time as dtime
from pathlib import Path
from dotenv import load_dotenv
from neo_api_client import NeoAPI
from execution.tick_aggregator import TickAggregator

load_dotenv(dotenv_path=os.path.expanduser("~/Documents/algo-trading-bot/.env"))

# ── config ─────────────────────────────────────────────────────────────────
PORTFOLIO = {
    "SBILIFE":    26460,
    "APOLLOHOSP": 24780,
    "ETERNAL":    21310,
    "INDUSINDBK": 17040,
    "GRASIM":     10420,
}

STOP_LOSS_PCT       = 0.02
RISK_PER_TRADE      = 0.015
LOG_DIR             = Path("reports/paper_trading")
LOG_DIR.mkdir(parents=True, exist_ok=True)
SESSION_DATE        = datetime.now().strftime("%Y%m%d")
LOG_FILE            = LOG_DIR / f"paper_trades_{SESSION_DATE}.csv"
POSITION_FILE       = LOG_DIR / "open_positions.csv"
TICK_FILE           = LOG_DIR / f"ticks_{SESSION_DATE}.csv"

MARKET_OPEN         = dtime(9, 15)
SIGNAL_WINDOW_START = dtime(15, 20)
MARKET_CLOSE        = dtime(15, 30)

# ── state ───────────────────────────────────────────────────────────────────
positions    = {}
paper_trades = []
OHLC_STATE_FILE = LOG_DIR / f"ohlc_state_{SESSION_DATE}.json"
aggregator   = TickAggregator(persist_path=str(OHLC_STATE_FILE))
from datetime import datetime as _dt, time as _dtime
signal_scan_done = False
_restart_after_window = _dt.now().time() >= _dtime(15, 20)

# load open positions from previous session
if POSITION_FILE.exists():
    pos_df = pd.read_csv(POSITION_FILE)
    for _, row in pos_df.iterrows():
        positions[row["symbol"]] = {
            "entry_price": row["entry_price"],
            "quantity":    row["quantity"],
            "stop_price":  row["stop_price"],
            "entry_date":  row["entry_date"],
        }
    if positions:
        print(f"📂 Loaded {len(positions)} open positions from previous session:")
        for sym, pos in positions.items():
            print(f"  {sym} @ ₹{pos['entry_price']} | stop ₹{pos['stop_price']} | qty {pos['quantity']}")

if LOG_FILE.exists():
    paper_trades = pd.read_csv(LOG_FILE).to_dict("records")
else:
    pd.DataFrame(columns=[
        "date","timestamp","action","symbol",
        "price","quantity","reason"
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


def get_position_size(symbol, price):
    capital   = PORTFOLIO.get(symbol, 0)
    risk_amt  = capital * RISK_PER_TRADE
    stop_dist = price  * STOP_LOSS_PCT
    size      = int(risk_amt / stop_dist)
    return max(size, 1)


def check_stop_loss(symbol, ltp):
    if symbol not in positions:
        return
    pos = positions[symbol]
    if ltp <= pos["stop_price"]:
        pnl = round((ltp - pos["entry_price"]) * pos["quantity"], 2)
        print(f"🚨 STOP LOSS HIT | {symbol} @ ₹{ltp:.2f} | PnL ₹{pnl}")
        positions.pop(symbol)
        log_paper_order("SELL", symbol, ltp, pos["quantity"],
                        f"STOP_LOSS | PnL=₹{pnl}")


def run_signal_scan():
    """
    At 3:20 PM:
    1. Get today's OHLC from tick aggregator (close = latest tick)
    2. Fetch historical data via yfinance in venv-data
    3. Append today's candle → run generate_signals()
    4. Log paper orders + print signal interpretation
    """
    print("\n⏰ 3:20 PM — Building OHLC from today's ticks...")
    aggregator.summary()

    today_candles = aggregator.get_all_candles()
    if not today_candles:
        print("⚠️  No ticks collected today — cannot generate signals.")
        return

    script = f"""
import sys
sys.path.insert(0, '.')
import yfinance as yf
import pandas as pd
import json
from strategy.signals import generate_signals
from strategy.indicators import add_all_indicators
from strategy.patterns import add_all_patterns

today_candles = {json.dumps(today_candles)}
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

        # append today's live candle
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
        df = df.drop_duplicates(subset='date').sort_values('date').reset_index(drop=True)

        sig_df = generate_signals(df)
        last   = sig_df.iloc[-1]

        # collect pattern flags
        pattern_cols = ['bullish_engulfing','bullish_marubozu','hammer','bullish_harami',
                        'bearish_engulfing','bearish_marubozu','shooting_star',
                        'hanging_man','bearish_harami']
        patterns = {{col: bool(last.get(col, False)) for col in pattern_cols}}

        results[sym] = {{
            'signal':          str(last.get('signal', 'None')),
            'close':           float(last['close']),
            'rsi':             float(last['rsi'])   if 'rsi'   in last.index else 0,
            'ema20':           float(last['ema20']) if 'ema20' in last.index else 0,
            'above_avg_volume':bool(last.get('above_avg_volume', False)),
            'patterns':        patterns,
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

    print("\n📊 Signal scan complete:")
    for sym, data in signals.items():
        sig   = data.get("signal", "None")
        close = data.get("close", 0)
        rsi   = data.get("rsi",   0)
        ema20 = data.get("ema20", 0)
        vol   = data.get("above_avg_volume", False)
        pats  = data.get("patterns", {})

        print(f"\n  {sym:12s} | ₹{close:.2f} | RSI={rsi:.1f} | "
              f"EMA20=₹{ema20:.2f} | vol_ok={vol} | signal={sig}")

        # print interpretation
        from analytics.signal_interpreter import interpret_live_signal
        interp = interpret_live_signal(
            symbol=sym, signal=sig if sig != "None" else "HOLD",
            close=close, rsi=rsi, ema20=ema20,
            above_avg_volume=vol, pattern_flags=pats,
        )
        print(interp)

        # LONG ONLY — only act on BUY signals (no shorting on cash equity)
        ltp = close

        if sig == "BUY" and sym not in positions:
            qty        = get_position_size(sym, ltp)
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
            # SELL signal = exit existing long position (not a short entry)
            pos = positions.pop(sym)
            pnl = round((ltp - pos["entry_price"]) * pos["quantity"], 2)
            log_paper_order("SELL", sym, ltp, pos["quantity"],
                            f"SIGNAL_EXIT | PnL=₹{pnl}")

        elif sig == "SELL" and sym not in positions:
            print(f"  ℹ️  {sym}: SELL signal but no open position — no action (long-only strategy)")


def on_tick(symbol, ltp, raw):
    now = datetime.now().time()
    if not (MARKET_OPEN <= now <= MARKET_CLOSE):
        return
    try:
        ltp = float(ltp)
    except (TypeError, ValueError):
        return

    # collect tick for OHLC building
    vol = int(raw.get("v", 0)) if raw else 0
    aggregator.on_tick(symbol, ltp, vol)

    # log raw tick
    with open(TICK_FILE, "a") as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')},{symbol},{ltp}\n")

    # monitor stop losses on open positions
    check_stop_loss(symbol, ltp)


def login():
    client = NeoAPI(
        environment  = "prod",
        consumer_key = os.getenv("NEO_CONSUMER_KEY"),
        access_token = None,
        neo_fin_key  = None,
    )
    totp = pyotp.TOTP(os.getenv("NEO_TOTP_SECRET")).now()
    client.totp_login(mobile_number=os.getenv("NEO_MOBILE"),
                      ucc=os.getenv("NEO_UCC"), totp=totp)
    client.totp_validate(mpin=os.getenv("NEO_MPIN"))
    print("Logged in successfully")
    return client


def resolve_tokens(client):
    instrument_tokens = []
    token_to_name     = {}
    for stock in PORTFOLIO:
        results = client.search_scrip(exchange_segment="nse_cm", symbol=stock)
        if not results:
            continue
        match = next((r for r in results if r.get("pGroup") == "EQ"), results[0])
        token = str(match["pSymbol"])
        instrument_tokens.append({"instrument_token": token, "exchange_segment": "nse_cm"})
        token_to_name[token] = stock
        print(f"Resolved {stock} → {match['pTrdSymbol']} (token {token})")
    return instrument_tokens, token_to_name


def main():
    global signal_scan_done
    print("=" * 55)
    print("  PAPER TRADER — Positional | Long Only | No real orders")
    print("=" * 55)
    print(f"Portfolio : {list(PORTFOLIO.keys())}")
    print(f"Log file  : {LOG_FILE}\n")

    client = login()
    instrument_tokens, token_to_name = resolve_tokens(client)

    def on_message(message):
        if not isinstance(message, dict) or message.get("type") != "stock_feed":
            return
        for tick in message.get("data", []):
            if "ltp" not in tick:
                continue
            token  = str(tick.get("tk"))
            symbol = token_to_name.get(token, token)
            ltp    = float(tick.get("ltp", 0))
            on_tick(symbol, ltp, tick)

    last_tick_time = [datetime.now()]

    def on_message_wrapper(message):
        last_tick_time[0] = datetime.now()
        on_message(message)

    client.on_message = on_message_wrapper
    client.on_error   = lambda e: print(f"⚠️  Feed error: {e}")
    client.on_open    = lambda m: print("WebSocket connected — paper trader running...\n")
    client.on_close   = lambda m: print(f"⚠️  WebSocket closed: {m}")

    client.subscribe(instrument_tokens=instrument_tokens,
                     isIndex=False, isDepth=False)
    print("Live feed started")

    if _restart_after_window and not signal_scan_done:
        print("⚠️  Restarted after 3:20 PM — running signal scan now...")
        signal_scan_done = True
        run_signal_scan()

    try:
        while True:
            now = datetime.now().time()

            if now >= SIGNAL_WINDOW_START and not signal_scan_done:
                signal_scan_done = True
                run_signal_scan()

            if now > MARKET_CLOSE:
                print("\n✅ Market closed. Session ended.")
                print(f"Open positions carried forward: {list(positions.keys()) or 'None'}")
                print(f"Trades today : {len(paper_trades)}")
                print(f"Log saved   → {LOG_FILE}")
                break

            # auto-reconnect if no tick for 60 seconds during market hours
            if (MARKET_OPEN <= now <= MARKET_CLOSE):
                seconds_since_tick = (datetime.now() - last_tick_time[0]).seconds
                if seconds_since_tick > 60:
                    print(f"⚠️  No ticks for {seconds_since_tick}s — reconnecting...")
                    try:
                        client.un_subscribe(instrument_tokens=instrument_tokens,
                                           isIndex=False, isDepth=False)
                    except:
                        pass
                    time.sleep(2)
                    client.subscribe(instrument_tokens=instrument_tokens,
                                    isIndex=False, isDepth=False)
                    last_tick_time[0] = datetime.now()
                    print("✅ Reconnected")

            time.sleep(1)

    except KeyboardInterrupt:
        print("\nStopped by user.")
        save_positions()
        print(f"Positions saved → {POSITION_FILE}")


if __name__ == "__main__":
    main()
