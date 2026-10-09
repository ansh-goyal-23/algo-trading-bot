"""
Single daily entry point for unattended (Render Cron Job) execution.

Fires once each weekday morning (~9:00 AM IST, before market open). It
decides what to do based on whether there's an open position in Supabase:

  - Open position(s) exist  -> run a full-day tick monitor (same idea as
    paper_trader.py) from now until market close, so stop-loss and the
    +4%/+6% partial-exit targets are caught intraday, not just once at EOD.
  - Flat                    -> wait until the 3:10 PM signal window, then
    run the EOD scan once (same idea as eod_scanner.py), then exit.

This removes the "remember to run it at 3:10 PM" step by hand — see the
project doc's Daily Log for how many times that got missed.

DOES NOT MODIFY paper_trader.py or eod_scanner.py — those still work
exactly as before for running locally on your Mac. This script
reimplements the same flow against Supabase instead of local CSV/JSON
files, because Render's cron containers don't keep a filesystem between
runs. The trading-rule logic itself (stop-loss, partial exits, position
sizing) is NOT reimplemented here — it's imported unchanged from
execution/portfolio.py, the same module the local scripts use, so the
rules can't drift between local and cloud runs.

TWO VENVS, SAME AS LOCAL — NOT ONE. neo_api_client hard-pins
websockets==8.1 in its own package metadata; yfinance requires
websockets>=13.0. That's a real conflict between the two libraries'
declared dependencies, not just a pin choice, so it can't be resolved by
installing everything into one environment (this was tried and confirmed
broken — see project doc, Daily Log). This script runs directly in the
"live" venv (Kotak Neo, Supabase, no pandas/yfinance needed at all) and
shells out to a SEPARATE "data" venv for anything yfinance/pandas-based —
exactly the subprocess bridge paper_trader.py/eod_scanner.py already use
locally (`venv-data/bin/python`), just pointed at a second venv Render's
build step creates. See DEPLOY.md for the two-venv build/start commands.

IMPORTANT — test locally before trusting this on Render:
    source render-live-venv/bin/activate
    python -m execution.run_daily
(needs both render-live-venv/ and render-data-venv/ to exist locally,
per DEPLOY.md Step 1)

Usage:
    python -m execution.run_daily
"""

import time
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from pathlib import Path
from dotenv import load_dotenv

from execution.portfolio import (
    PORTFOLIO, STOP_LOSS_PCT, get_position_size, login, check_position_exit,
)
from execution.tick_aggregator import TickAggregator
from execution import state_store as store
from execution import quote_utils

load_dotenv()

IST = ZoneInfo("Asia/Kolkata")


def now_ist() -> datetime:
    """
    Timezone-aware current time in IST.

    The VM this runs on has its OS/Python clock set to UTC (confirmed
    2026-09-22: /etc/timezone -> Etc/UTC, time.tzname -> ('UTC','UTC')).
    MARKET_OPEN/MARKET_CLOSE below are IST wall-clock constants. Bare
    datetime.now() returns naive UTC on this VM, so comparing it directly
    against those constants was silently wrong for ~5 hours of every
    trading day (real market hours only "looked open" to the old code
    during UTC 09:15-15:30, i.e. IST 14:45-21:00 -- the last 45 minutes
    of the session was the only overlap). Use this helper everywhere
    instead of datetime.now() so the comparison is always correct
    regardless of what timezone the host OS happens to be set to.
    """
    return datetime.now(IST)


MARKET_OPEN         = dtime(9, 15)
SIGNAL_WINDOW_START = dtime(15, 10)
MARKET_CLOSE        = dtime(15, 30)

TODAY = now_ist().strftime("%Y-%m-%d")

# The "data" venv (yfinance/pandas/ta/scipy) — a sibling directory to
# whichever venv is currently running this script. Different environments
# have used different names for it (Render's build command created
# render-data-venv/; the Mac and the GCP VM both use venv-data/) — try
# each known name in order and fall back to whichever exists.
_DATA_VENV_CANDIDATES = [
    Path("venv-data/bin/python"),
    Path("render-data-venv/bin/python"),
]
DATA_VENV_PYTHON = next(
    (p for p in _DATA_VENV_CANDIDATES if p.exists()),
    _DATA_VENV_CANDIDATES[0],
)


def resolve_tokens(client):
    instrument_tokens, token_to_name = [], {}
    for stock in PORTFOLIO:
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
        instrument_tokens.append({"instrument_token": token, "exchange_segment": "nse_cm"})
        token_to_name[token] = stock
        print(f"Resolved {stock} -> {match['pTrdSymbol']} (token {token})")
    return instrument_tokens, token_to_name


# ── OHLC fetch (EOD path) — same approach as eod_scanner.py ────────────────
def fetch_today_ohlc_kotak(client) -> dict:
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
            inst = [{"instrument_token": token, "exchange_segment": "nse_cm"}]
            ohlc_resp = client.quotes(instrument_tokens=inst, quote_type="ohlc")
            # quote_type="ohlc" has NO ltp (and ohlc['close'] is the PREVIOUS
            # close) -- the real close must come from an LTP quote. Fixed
            # 2026-10-09; see execution/quote_utils.py.
            try:
                ltp_resp = client.quotes(instrument_tokens=inst, quote_type="ltp")
            except Exception as e:
                print(f"  ⚠️  {stock} (Kotak): ltp quote failed: {e}")
                ltp_resp = None
            candle, why = quote_utils.build_kotak_candle(ohlc_resp, ltp_resp, TODAY)
            if candle is None:
                print(f"  ⚠️  {stock} (Kotak): quote rejected — {why}")
                continue
            ohlc[stock] = candle
        except Exception as e:
            print(f"  ⚠️  {stock} (Kotak): {e}")
    return ohlc


def fetch_today_ohlc_yfinance() -> dict:
    """Fallback OHLC fetch, run in the separate data venv via subprocess —
    same bridge eod_scanner.py already uses locally."""
    script = """
import sys, json
sys.path.insert(0, '.')
import yfinance as yf
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
            'date': str(df.index[-1].date()),
            'open': float(last['Open']), 'high': float(last['High']),
            'low': float(last['Low']), 'close': float(last['Close']),
            'volume': int(last['Volume']),
        }
    except Exception:
        pass
print(json.dumps(result))
"""
    r = subprocess.run([str(DATA_VENV_PYTHON), "-c", script], capture_output=True, text=True, cwd=".")
    if r.returncode != 0:
        print("  ⚠️  yfinance subprocess failed:", r.stderr[-500:])
        return {}
    try:
        return json.loads(r.stdout.strip())
    except Exception as e:
        print(f"  ⚠️  Could not parse yfinance subprocess output: {e}")
        return {}


def fetch_today_ohlc(client) -> dict:
    """
    Today's validated daily candles. Kotak supplies open/high/low + a real LTP
    close (rejected if the LTP is missing or the candle is inconsistent);
    yfinance supplies volume (Kotak's ohlc quote has none) and is the fallback
    for any symbol Kotak couldn't give a valid candle for. A fallback candle is
    only accepted if it is dated TODAY and internally consistent. Symbols with no
    valid candle are skipped (logged loudly) -- we never scan/trade on bad data.
    """
    print("\n📡 Fetching today's OHLC from Kotak Neo...")
    ohlc = fetch_today_ohlc_kotak(client)

    valid = {s: d for s, d in ohlc.items() if quote_utils.candle_is_valid(d)}
    invalid = set(PORTFOLIO.keys()) - set(valid.keys())

    # yfinance: needed for volume on every valid candle, and as fallback for the rest
    yf_data = fetch_today_ohlc_yfinance()

    for sym in sorted(invalid):
        cand, why = quote_utils.accept_fallback_candle(yf_data.get(sym), TODAY)
        if cand is not None:
            valid[sym] = cand
            print(f"  ✅ {sym}: no valid Kotak candle — using yfinance")
        else:
            print(f"  🚫 {sym}: NO valid candle today (Kotak rejected; yfinance: {why}) — skipping this symbol")

    for sym, candle in valid.items():
        if candle.get("volume", 0) <= 0:
            if not quote_utils.fill_volume(candle, yf_data.get(sym), TODAY):
                print(f"  ⚠️  {sym}: volume unavailable for today — volume checklist point is unreliable")

    # print summary
    print("\n  Today's OHLC:")
    for stock, c in valid.items():
        chg = round((c["close"] - c["open"]) / c["open"] * 100, 2) if c["open"] else 0
        direction = "🟢" if chg >= 0 else "🔴"
        print(f"  {stock:12s} | O={c['open']:.2f} H={c['high']:.2f} "
              f"L={c['low']:.2f} C={c['close']:.2f} V={c.get('volume', 0)} | {direction} {chg:+.2f}%")

    return valid


# ── signal scan — strategy/signals.py rules, run in the DATA venv ─────────
def run_signal_scan(today_candles: dict):
    """
    Fetch 6mo history via yfinance, append today's candle, run
    generate_signals() — all inside the data-venv subprocess, since
    strategy/indicators.py needs `ta` and strategy/trend.py needs `scipy`,
    neither of which are (or should be) installed in the live venv.
    Gets back {symbol: {signal, close, rsi}} as JSON, then acts on
    BUY/SELL against Supabase-held positions back in THIS process (pure
    Python from here — no pandas needed).
    """
    script = f"""
import sys; sys.path.insert(0, '.')
import yfinance as yf
import pandas as pd
import json
from strategy.signals import generate_signals
from analytics.signal_interpreter import interpret_live_signal

today_candles = {json.dumps(today_candles)}
results = {{}}

for sym, today in today_candles.items():
    try:
        ticker = sym + '.NS'
        hist = yf.download(ticker, period='6mo', interval='1d', progress=False)
        if hist.empty:
            results[sym] = {{'signal': 'ERROR', 'error': 'No historical data'}}
            continue
        hist = hist.reset_index()
        hist.columns = [c[0] if isinstance(c, tuple) else c for c in hist.columns]
        hist.columns = [c.lower() for c in hist.columns]
        hist = hist[['date','open','high','low','close','volume']]
        hist['date'] = pd.to_datetime(hist['date']).dt.tz_localize(None)

        today_row = pd.DataFrame([{{
            'date': today['date'], 'open': today['open'], 'high': today['high'],
            'low': today['low'], 'close': today['close'], 'volume': today['volume'],
        }}])
        today_row['date'] = pd.to_datetime(today_row['date'])

        df = pd.concat([hist, today_row], ignore_index=True)
        df = df.drop_duplicates(subset='date', keep='last').sort_values('date').reset_index(drop=True)

        sig_df = generate_signals(df)
        last = sig_df.iloc[-1]

        pattern_cols = ['bullish_engulfing','bullish_marubozu','hammer','bullish_harami',
                        'bearish_engulfing','bearish_marubozu','shooting_star',
                        'hanging_man','bearish_harami']
        patterns = {{col: bool(last.get(col, False)) for col in pattern_cols}}

        # add trend context (fixed 2026-09-23 — was missing here, unlike the
        # matching lines in eod_scanner.py/paper_trader.py's subprocess
        # scripts, which is why every live log line showed "Prior Trend:
        # unknown" even though generate_signals() was computing and using
        # it correctly in the real BUY/SELL decision the whole time)
        patterns['prior_trend'] = str(last.get('prior_trend', 'unknown'))

        sig   = str(last.get('signal', 'None'))
        close = float(last['close'])
        rsi   = float(last['rsi'])   if 'rsi'   in last.index else 0
        ema20 = float(last['ema20']) if 'ema20' in last.index else 0
        vol   = bool(last.get('above_avg_volume', False))

        # human-readable interpretation goes to stderr — stdout is JSON-only
        print(interpret_live_signal(
            symbol=sym, signal=sig if sig != 'None' else 'HOLD',
            close=close, rsi=rsi, ema20=ema20,
            above_avg_volume=vol, pattern_flags=patterns,
        ), file=sys.stderr)

        results[sym] = {{'signal': sig, 'close': close, 'rsi': rsi}}
    except Exception as e:
        results[sym] = {{'signal': 'ERROR', 'error': str(e)}}

print(json.dumps(results))
"""
    result = subprocess.run(
        [str(DATA_VENV_PYTHON), "-c", script], capture_output=True, text=True, cwd="."
    )
    if result.stderr:
        print(result.stderr)  # the human-readable interpretations
    if result.returncode != 0:
        print("Signal scan subprocess error:", result.stderr[-800:])
        return
    try:
        signals = json.loads(result.stdout.strip())
    except Exception as e:
        print(f"Failed to parse signal scan output: {e}")
        return

    positions = store.load_positions()
    for sym, data in signals.items():
        sig = data.get("signal")
        if sig == "ERROR":
            print(f"  ⚠️  {sym}: {data.get('error')}")
            continue

        ltp = data.get("close", 0)
        rsi = data.get("rsi", 0)

        if sig == "BUY" and sym not in positions:
            qty = get_position_size(sym, ltp)
            if qty < 1:
                print(f"  ⚠️  {sym}: BUY signal but 1 share (₹{ltp:.2f}) exceeds allocated capital — skipping")
                continue
            stop_price = round(ltp * (1 - STOP_LOSS_PCT), 2)
            pos = {
                "entry_price": ltp, "quantity": qty, "stop_price": stop_price,
                "entry_date": TODAY, "partial_exit_done": False,
            }
            store.save_position(sym, pos)
            store.log_trade("BUY", sym, ltp, qty, f"SIGNAL | stop@{stop_price} | RSI={rsi:.1f}")
            positions[sym] = pos

        elif sig == "SELL" and sym in positions:
            pos = positions.pop(sym)
            pnl = round((ltp - pos["entry_price"]) * pos["quantity"], 2)
            store.log_trade("SELL", sym, ltp, pos["quantity"], f"SIGNAL_EXIT | PnL=₹{pnl}")
            store.delete_position(sym)

        elif sig == "SELL" and sym not in positions:
            print(f"  ℹ️  {sym}: SELL signal but no open position — no action (long-only)")


def check_stop_losses_eod(today_ohlc: dict):
    """EOD-bar stop/target check — same rule function as the intraday path,
    using today's low/high as a proxy (one check per day)."""
    positions = store.load_positions()
    if not positions:
        return
    print("\n🛡️  Checking stop losses and targets on open positions...")
    for sym, pos in positions.items():
        if sym not in today_ohlc:
            continue
        low, high, close = today_ohlc[sym]["low"], today_ohlc[sym]["high"], today_ohlc[sym]["close"]
        result = check_position_exit(pos, low=low, high=high, close=close)
        if result is None:
            print(f"  ✅ {sym} | low={low:.2f} > stop={pos['stop_price']:.2f} — position safe")
            continue

        action, qty, trigger = result["action"], result["quantity"], result["trigger_price"]
        entry = pos["entry_price"]

        if action == "STOP":
            pnl = round((trigger - entry) * qty, 2)
            print(f"🚨 STOP LOSS HIT | {sym} | low={low} <= stop={pos['stop_price']} | PnL ₹{pnl}")
            store.log_trade("SELL", sym, trigger, qty, f"STOP_LOSS | PnL=₹{pnl}")
            store.delete_position(sym)
        elif action == "TARGET1_PARTIAL":
            pnl = round((trigger - entry) * qty, 2)
            print(f"🎯 TARGET 1 HIT (+4%) | {sym} | Selling {qty} shares | PnL ₹{pnl}")
            store.log_trade("SELL", sym, trigger, qty, f"TARGET_1_PARTIAL | PnL=₹{pnl} | stop moved to breakeven")
            store.save_position(sym, pos)  # check_position_exit already mutated pos in place
        elif action == "TARGET1_PROTECT":
            print(f"🎯 TARGET 1 HIT (+4%) | {sym} | qty=1, holding full position | stop moved to breakeven")
            store.save_position(sym, pos)
        elif action == "TARGET2":
            pnl = round((trigger - entry) * qty, 2)
            print(f"🎯 TARGET 2 HIT (+6%) | {sym} | Full exit | PnL ₹{pnl}")
            store.log_trade("SELL", sym, trigger, qty, f"TARGET_2_FULL | PnL=₹{pnl}")
            store.delete_position(sym)


# ── path 1: flat — wait for the EOD window, scan once, exit ────────────────
def run_eod_only():
    now = now_ist().time()
    if now < SIGNAL_WINDOW_START:
        wait_s = (
            datetime.combine(now_ist().date(), SIGNAL_WINDOW_START)
            - datetime.combine(now_ist().date(), now)
        ).seconds
        print(f"No open positions — waiting {wait_s}s until the {SIGNAL_WINDOW_START} signal window...")
        time.sleep(wait_s)

    client = login()
    today_ohlc = fetch_today_ohlc(client)
    today_ohlc = {s: d for s, d in today_ohlc.items() if d["close"] > 0 and d["open"] > 0}
    if not today_ohlc:
        print("⚠️  No valid OHLC data — market may be closed or something's wrong upstream.")
        return

    check_stop_losses_eod(today_ohlc)
    run_signal_scan(today_ohlc)
    print(f"\n✅ Scan complete. Open positions: {list(store.load_positions().keys()) or 'None'}")


# ── path 2: position(s) open — monitor intraday until close ────────────────
_RECONNECT_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ws-reconnect")


def _call_with_timeout(fn, *args, timeout=15, **kwargs):
    """
    Run fn(*args, **kwargs) with a hard wall-clock timeout.

    neo_api_client's subscribe()/un_subscribe() calls are synchronous and
    can block forever on a dead TCP connection the server never sends a
    clean close/RST for (observed 2026-09-21: process frozen for 1.5h+ at
    0% CPU immediately after "Session has been Closed!", never reaching
    the reconnect loop's own retry logic because the call itself never
    returned). Running the call in a worker thread with .result(timeout=)
    lets us treat a hang the same as any other reconnect failure instead
    of freezing the whole monitor until the 8h hard-kill wrapper fires.

    NOTE: on timeout the worker thread is NOT killed (Python has no clean
    way to do that) -- it's abandoned and may eventually complete or leak.
    That's an acceptable tradeoff here: the alternative is the entire
    monitor process hanging for hours, which is strictly worse.
    """
    future = _RECONNECT_EXECUTOR.submit(fn, *args, **kwargs)
    try:
        return future.result(timeout=timeout)
    except FutureTimeoutError:
        raise TimeoutError(f"{getattr(fn, '__name__', fn)} did not return within {timeout}s")


def run_full_day_monitor():
    print("Open position(s) found — running full-day monitor from now until market close...")
    client = login()
    instrument_tokens, token_to_name = resolve_tokens(client)

    aggregator = TickAggregator(
        save_fn=lambda candles: store.save_ohlc_state(TODAY, candles),
        load_fn=lambda: store.load_ohlc_state(TODAY),
    )
    signal_scan_done = [False]
    last_tick_time = [now_ist()]
    consecutive_failures = [0]
    tick_count_at_last_reconnect = [0]
    total_tick_count = [0]

    def check_stop_loss(symbol, ltp):
        positions = store.load_positions()
        if symbol not in positions:
            return
        pos = positions[symbol]
        result = check_position_exit(pos, low=ltp, high=ltp, close=ltp)
        if result is None:
            return
        action, qty = result["action"], result["quantity"]
        entry = pos["entry_price"]

        if action == "STOP":
            pnl = round((ltp - entry) * qty, 2)
            print(f"🚨 STOP LOSS HIT | {symbol} @ ₹{ltp:.2f} | PnL ₹{pnl}")
            store.log_trade("SELL", symbol, ltp, qty, f"STOP_LOSS | PnL=₹{pnl}")
            store.delete_position(symbol)
        elif action == "TARGET1_PARTIAL":
            pnl = round((ltp - entry) * qty, 2)
            print(f"🎯 TARGET 1 HIT (+4%) | {symbol} @ ₹{ltp:.2f} | Selling {qty} shares | PnL ₹{pnl}")
            store.log_trade("SELL", symbol, ltp, qty, f"TARGET_1_PARTIAL | PnL=₹{pnl} | stop moved to breakeven")
            store.save_position(symbol, pos)
        elif action == "TARGET1_PROTECT":
            print(f"🎯 TARGET 1 HIT (+4%) | {symbol} @ ₹{ltp:.2f} | qty=1, holding | stop moved to breakeven")
            store.save_position(symbol, pos)
        elif action == "TARGET2":
            pnl = round((ltp - entry) * qty, 2)
            print(f"🎯 TARGET 2 HIT (+6%) | {symbol} @ ₹{ltp:.2f} | Full exit | PnL ₹{pnl}")
            store.log_trade("SELL", symbol, ltp, qty, f"TARGET_2_FULL | PnL=₹{pnl}")
            store.delete_position(symbol)

    def on_message(message):
        if not isinstance(message, dict) or message.get("type") != "stock_feed":
            return
        for tick in message.get("data", []):
            if "ltp" not in tick:
                continue
            token = str(tick.get("tk"))
            symbol = token_to_name.get(token, token)
            try:
                ltp = float(tick.get("ltp", 0))
            except (TypeError, ValueError):
                continue
            now = now_ist().time()
            if not (MARKET_OPEN <= now <= MARKET_CLOSE):
                continue
            vol = int(tick.get("v", 0))
            aggregator.on_tick(symbol, ltp, vol)
            check_stop_loss(symbol, ltp)

    def on_message_wrapper(message):
        last_tick_time[0] = now_ist()
        total_tick_count[0] += 1
        on_message(message)

    client.on_message = on_message_wrapper
    client.on_error    = lambda e: print(f"⚠️  Feed error: {e}")
    client.on_open      = lambda m: print("WebSocket connected — monitoring...\n")
    client.on_close      = lambda m: print(f"⚠️  WebSocket closed: {m}")

    client.subscribe(instrument_tokens=instrument_tokens, isIndex=False, isDepth=False)
    print("Live feed started")

    while True:
        now = now_ist().time()

        if now >= SIGNAL_WINDOW_START and not signal_scan_done[0]:
            signal_scan_done[0] = True
            print("\n⏰ 3:10 PM — running signal scan from today's aggregated ticks...")
            today_candles = aggregator.get_all_candles()
            if today_candles:
                run_signal_scan(today_candles)
            else:
                print("⚠️  No ticks collected today — cannot generate signals.")

        if now > MARKET_CLOSE:
            print("\n✅ Market closed. Run ending.")
            print(f"Open positions carried forward: {list(store.load_positions().keys()) or 'None'}")
            break

        if MARKET_OPEN <= now <= MARKET_CLOSE:
            seconds_since_tick = (now_ist() - last_tick_time[0]).seconds
            if seconds_since_tick > 60:
                # Did the PREVIOUS reconnect attempt actually bring ticks back?
                # We only know this now, one 60s cycle later -- if
                # total_tick_count hasn't moved since we last tried
                # reconnecting, that attempt was a silent no-op (subscribe()
                # returned fine but delivered nothing), which is exactly
                # what happened repeatedly on 2026-09-21 while the old
                # exception-based check kept reporting "success". A true
                # first-ever staleness event (tick_count_at_last_reconnect
                # still at its initial 0 with ticks already flowing) is
                # handled the same way and just costs one extra check.
                previous_attempt_recovered_ticks = total_tick_count[0] > tick_count_at_last_reconnect[0]

                if previous_attempt_recovered_ticks:
                    consecutive_failures[0] = 0
                else:
                    consecutive_failures[0] += 1

                print(f"⚠️  No ticks for {seconds_since_tick}s — reconnecting (attempt {consecutive_failures[0]})...")

                if consecutive_failures[0] >= 3:
                    print("🔴 3 consecutive reconnect attempts produced zero new ticks — forcing full re-login + resubscribe...")
                    try:
                        client = login()
                        client.on_message = on_message_wrapper
                        client.on_error   = lambda e: print(f"⚠️  Feed error: {e}")
                        client.on_open    = lambda m: print("WebSocket connected — monitoring...\n")
                        client.on_close   = lambda m: print(f"⚠️  WebSocket closed: {m}")
                        _call_with_timeout(
                            client.subscribe,
                            instrument_tokens=instrument_tokens, isIndex=False, isDepth=False,
                            timeout=15,
                        )
                        consecutive_failures[0] = 0
                        print("✅ Re-logged in and resubscribed (will confirm ticks resume next cycle)")
                    except Exception as e:
                        print(f"  🔴 full re-login also failed: {e} — will retry next cycle")
                else:
                    try:
                        _call_with_timeout(
                            client.un_subscribe,
                            instrument_tokens=instrument_tokens, isIndex=False, isDepth=False,
                            timeout=15,
                        )
                    except Exception as e:
                        print(f"  ⚠️  un_subscribe failed/hung (continuing to resubscribe): {e}")

                    time.sleep(2)

                    try:
                        _call_with_timeout(
                            client.subscribe,
                            instrument_tokens=instrument_tokens, isIndex=False, isDepth=False,
                            timeout=15,
                        )
                        print("  subscribe() returned OK (will confirm ticks resume next cycle)")
                    except Exception as e:
                        print(f"  ⚠️  subscribe failed/hung: {e}")

                # Record where the tick count stood AT this reconnect attempt,
                # so next cycle's staleness check can tell whether it worked.
                tick_count_at_last_reconnect[0] = total_tick_count[0]
                # Push the staleness clock forward regardless of outcome --
                # otherwise we'd re-fire this block every second instead of
                # waiting a fresh 60s to judge the attempt fairly.
                last_tick_time[0] = now_ist()

        time.sleep(1)


def main():
    print("=" * 55)
    print("  RUN DAILY — unattended entry point (Render)")
    print(f"  {now_ist().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    positions = store.load_positions()
    print(f"Open positions in Supabase: {list(positions.keys()) or 'None'}")

    if positions:
        run_full_day_monitor()
    else:
        run_eod_only()


if __name__ == "__main__":
    main()
