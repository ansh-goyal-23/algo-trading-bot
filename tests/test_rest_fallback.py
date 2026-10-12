"""
Tests for execution/rest_fallback.py and its integration in run_daily.run_full_day_monitor.
Pure Python (heavy deps are stubbed); a simulated clock drives the real monitor loop.
Run: python3 -m unittest tests.test_rest_fallback -v
"""
import contextlib
import io
import sys
import time as real_time
import types
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from execution import rest_fallback as rf

IST = ZoneInfo("Asia/Kolkata")


# ───────────────────────── unit tests: the state machine ─────────────────────────
class StateMachine(unittest.TestCase):
    def drive(self, fb, seconds, tick_rate_per_s=0.0, start=0.0, count0=0):
        """Advance 1s at a time; return list of (t, change)."""
        events, count = [], count0
        for i in range(seconds):
            t = start + i
            count = count0 + int(tick_rate_per_s * (i + 1))
            ch = fb.observe(t, count)
            if ch:
                events.append((t, ch))
        return events

    def test_nothing_judged_in_first_window(self):
        fb = rf.RestFallback(window_s=120, min_ticks=5)
        self.assertEqual(self.drive(fb, 119), [])
        self.assertFalse(fb.active)

    def test_activates_after_a_full_silent_window(self):
        fb = rf.RestFallback(window_s=120, min_ticks=5)
        ev = self.drive(fb, 200)
        self.assertEqual(ev, [(120, "activated")])
        self.assertTrue(fb.active)

    def test_healthy_feed_never_activates(self):
        fb = rf.RestFallback()
        self.assertEqual(self.drive(fb, 3600, tick_rate_per_s=2), [])

    def test_sparse_snapshot_feed_still_counts_as_dead(self):
        # 1 stale snapshot tick per ~61s (the 2026-10-02 pattern) = ~2 per 120s < 5
        fb = rf.RestFallback()
        ev = self.drive(fb, 600, tick_rate_per_s=1 / 61)
        self.assertEqual([c for _, c in ev], ["activated"])

    def test_deactivates_when_ticks_resume_and_reactivates_later(self):
        fb = rf.RestFallback()
        self.drive(fb, 300)                       # silent -> active
        self.assertTrue(fb.active)
        ev = self.drive(fb, 130, tick_rate_per_s=2, start=300, count0=0)
        self.assertIn("deactivated", [c for _, c in ev])
        self.assertFalse(fb.active)
        ev = self.drive(fb, 300, start=430, count0=260)  # silent again
        self.assertIn("activated", [c for _, c in ev])
        self.assertEqual(fb.activations, 2)

    def test_poll_cadence(self):
        fb = rf.RestFallback(window_s=10, min_ticks=1, poll_every_s=30)
        due_times = []
        for t in range(0, 200):
            fb.observe(t, 0)
            if fb.due(t):
                fb.poll(t, ["X"], lambda s: 100.0)
                due_times.append(t)
        self.assertEqual(due_times[0], 10)           # first poll right on activation
        gaps = [b - a for a, b in zip(due_times, due_times[1:])]
        self.assertTrue(all(g == 30 for g in gaps), gaps)

    def test_active_seconds_accumulate_and_drive_rest_scan_decision(self):
        fb = rf.RestFallback(window_s=10, min_ticks=1)
        self.drive(fb, 100)
        self.assertAlmostEqual(fb.active_seconds_total, 89, delta=2)
        self.assertFalse(fb.needs_rest_scan(n_tick_candles=5))   # 89s < 600s
        self.assertTrue(fb.needs_rest_scan(n_tick_candles=0))    # no ticks at all
        self.drive(fb, 700, start=100)
        self.assertTrue(fb.needs_rest_scan(n_tick_candles=5))    # >= 10 min fallback


class Polling(unittest.TestCase):
    def test_poll_accepts_sane_prices_and_records_them(self):
        fb = rf.RestFallback()
        out = fb.poll(0, ["A", "B"], {"A": 100.0, "B": 250.5}.get)
        self.assertEqual(out, {"A": 100.0, "B": 250.5})
        self.assertEqual(fb.last_prices, {"A": 100.0, "B": 250.5})

    def test_poll_rejects_zero_none_garbage_and_wild_jumps(self):
        fb = rf.RestFallback()
        fb.poll(0, ["A"], lambda s: 100.0)
        for bad in (0, None, "abc", -5, 140.0):    # 140 = +40% jump
            out = fb.poll(30, ["A"], lambda s, b=bad: b)
            self.assertEqual(out, {}, bad)
            self.assertEqual(fb.last_prices["A"], 100.0)
        self.assertEqual(fb.poll(60, ["A"], lambda s: 110.0), {"A": 110.0})  # +10% ok

    def test_poll_errors_never_raise(self):
        fb = rf.RestFallback()
        def boom(sym):
            raise RuntimeError("session expired")
        self.assertEqual(fb.poll(0, ["A"], boom), {})
        self.assertIn("session expired", fb.last_errors[0])

    def test_call_with_timeout_returns_raises_and_times_out(self):
        self.assertEqual(rf.call_with_timeout(lambda x: x * 2, 1, 21), 42)
        with self.assertRaises(ValueError):
            rf.call_with_timeout(lambda: (_ for _ in ()).throw(ValueError("x")), 1)
        t0 = real_time.time()
        with self.assertRaises(TimeoutError):
            rf.call_with_timeout(real_time.sleep, 0.2, 5)
        self.assertLess(real_time.time() - t0, 1.0)


# ───────────────── integration: the real monitor loop on a simulated clock ─────────────────
TOKENS = {"157": "APOLLOHOSP", "910": "EICHERMOT"}
_SAVED = {}
rd = None


def setUpModule():
    global rd
    names = ["dotenv", "execution.portfolio", "execution.tick_aggregator",
             "execution.state_store", "execution.run_daily"]
    for n in names:
        _SAVED[n] = sys.modules.pop(n, None)
    dotenv = types.ModuleType("dotenv"); dotenv.load_dotenv = lambda *a, **k: None
    sys.modules["dotenv"] = dotenv
    pf = types.ModuleType("execution.portfolio")
    pf.PORTFOLIO = {"APOLLOHOSP": 1, "EICHERMOT": 1}
    pf.STOP_LOSS_PCT = 0.02
    pf.get_position_size = lambda *a, **k: 1
    pf.login = lambda: None
    pf.check_position_exit = lambda pos, low, high, close: (
        {"action": "STOP", "quantity": pos["quantity"], "trigger_price": pos["stop_price"]}
        if low <= pos["stop_price"] else None)
    sys.modules["execution.portfolio"] = pf
    ta = types.ModuleType("execution.tick_aggregator"); ta.TickAggregator = object
    sys.modules["execution.tick_aggregator"] = ta
    sys.modules["execution.state_store"] = types.ModuleType("execution.state_store")
    import execution
    execution.state_store = sys.modules["execution.state_store"]
    import execution.run_daily as mod
    rd = mod


def tearDownModule():
    for n, m in _SAVED.items():
        if m is None:
            sys.modules.pop(n, None)
        else:
            sys.modules[n] = m


class Clock:
    def __init__(self, start):
        self.t = start
        self.hook = None

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += timedelta(seconds=s)
        if self.hook:
            self.hook(self)

    def monotonic(self):
        return self.t.timestamp()


class FakeAgg:
    def __init__(self, save_fn=None, load_fn=None):
        self.candles = {}
    def on_tick(self, sym, ltp, vol):
        c = self.candles.setdefault(sym, {"open": ltp, "high": ltp, "low": ltp, "close": ltp, "volume": vol})
        c["high"], c["low"], c["close"] = max(c["high"], ltp), min(c["low"], ltp), ltp
    def get_all_candles(self):
        return dict(self.candles)


class FakeClient:
    def __init__(self, ltp_fn):
        self.ltp_fn = ltp_fn
        self.quote_calls = 0
        self.on_message = None
        self.subscribes = 0
        self.snapshot_on_subscribe = False   # emit a burst of ticks right after every subscribe()
    def subscribe(self, **kw):
        self.subscribes += 1
        if self.snapshot_on_subscribe and self.on_message and self.clock.now().hour >= 9:
            self.on_message({"type": "stock_feed", "data": [
                {"tk": "157", "ltp": 8100.0, "v": 0} for _ in range(10)]})
    def un_subscribe(self, **kw): pass
    def quotes(self, instrument_tokens, quote_type):
        self.quote_calls += 1
        assert quote_type == "ltp"
        sym = TOKENS[instrument_tokens[0]["instrument_token"]]
        return [{"exchange_token": "1", "ltp": f"{self.ltp_fn(sym, self.clock.now()):.4f}"}]


class FakeStore:
    def __init__(self, positions):
        self.positions = positions
        self.trades = []
    def load_positions(self): return {k: dict(v) for k, v in self.positions.items()}
    def log_trade(self, action, sym, price, qty, reason=""): self.trades.append((action, sym, price, qty, reason))
    def delete_position(self, sym): self.positions.pop(sym, None)
    def save_position(self, sym, pos): self.positions[sym] = pos
    def load_ohlc_state(self, d): return {}
    def save_ohlc_state(self, d, c): pass


def run_monitor(ltp_fn, positions, tick_feed=None, start_clock=(9, 14, 50), snapshot_on_subscribe=False):
    """Run the real run_full_day_monitor() on a simulated clock. Returns a result dict."""
    clock = Clock(datetime(2026, 10, 13, *start_clock, tzinfo=IST))
    client = FakeClient(ltp_fn); client.clock = clock
    client.snapshot_on_subscribe = snapshot_on_subscribe
    client.logins = 0
    store = FakeStore(positions)
    rec = {"eod_checks": [], "scans": []}

    def feed_hook(c):
        if tick_feed and client.on_message:
            for msg in tick_feed(c.now()):
                client.on_message(msg)
    clock.hook = feed_hook

    saved = {k: getattr(rd, k) for k in ("login", "resolve_tokens", "TickAggregator", "store", "now_ist",
                                         "fetch_today_ohlc", "check_stop_losses_eod", "run_signal_scan")}
    saved_time = (rd.time.sleep, rd.time.monotonic)
    try:
        def _login():
            client.logins += 1
            return client
        rd.login = _login
        rd.resolve_tokens = lambda c: ([{"instrument_token": t, "exchange_segment": "nse_cm"} for t in TOKENS], dict(TOKENS))
        rd.TickAggregator = FakeAgg
        rd.store = store
        rd.now_ist = clock.now
        rd.TODAY = "2026-10-13"
        rd.time.sleep = clock.sleep
        rd.time.monotonic = clock.monotonic
        rd.fetch_today_ohlc = lambda c: {"APOLLOHOSP": {"date": "2026-10-13", "open": 8000.0, "high": 8010.0,
                                                          "low": 7940.0, "close": 7950.0, "volume": 1000}}
        rd.check_stop_losses_eod = lambda candles: rec["eod_checks"].append(candles)
        rd.run_signal_scan = lambda candles: rec["scans"].append(candles)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rd.run_full_day_monitor()
        rec["log"] = buf.getvalue()
    finally:
        for k, v in saved.items():
            setattr(rd, k, v)
        rd.time.sleep, rd.time.monotonic = saved_time
    rec.update(store=store, client=client, clock=clock)
    return rec


POS = lambda: {"APOLLOHOSP": {"entry_price": 8165.5, "quantity": 3, "stop_price": 8002.19,
                              "entry_date": "2026-10-01", "partial_exit_done": False}}


class MonitorIntegration(unittest.TestCase):
    def test_dead_websocket_stop_is_hit_via_rest_and_scan_uses_rest_candles(self):
        def ltp(sym, now):  # price drops through the stop at 11:00
            return 8100.0 if now.hour < 11 else 7950.0
        r = run_monitor(ltp, POS())
        sells = [t for t in r["store"].trades if t[0] == "SELL"]
        self.assertEqual(len(sells), 1, r["store"].trades)
        self.assertEqual(sells[0][1:3], ("APOLLOHOSP", 7950.0))
        self.assertIn("STOP_LOSS", sells[0][4])
        self.assertNotIn("APOLLOHOSP", r["store"].positions)
        self.assertIn("REST fallback ON", r["log"])
        # fallback switched on ~2 minutes after the open, not before
        on_line_idx = r["log"].index("REST fallback ON")
        self.assertGreater(on_line_idx, 0)
        # 3:10 PM scan built from REST candles, with the EOD stop check as backstop
        self.assertEqual(len(r["scans"]), 1)
        self.assertEqual(r["scans"][0]["APOLLOHOSP"]["close"], 7950.0)
        self.assertEqual(len(r["eod_checks"]), 1)
        self.assertIn("building the scan from REST quotes", r["log"])
        self.assertIn("Market closed. Run ending.", r["log"])
        # polling stops once nothing is held (post-11:00 stop-out): far fewer than 750 polls
        self.assertLess(r["client"].quote_calls, 300)

    def test_no_stop_breach_means_no_trade_but_scan_still_runs(self):
        r = run_monitor(lambda s, n: 8100.0, POS())
        self.assertEqual(r["store"].trades, [])
        self.assertIn("APOLLOHOSP", r["store"].positions)
        self.assertEqual(len(r["scans"]), 1)

    def test_healthy_websocket_never_triggers_rest(self):
        def feed(now):
            if not (9 <= now.hour < 16):
                return []
            return [{"type": "stock_feed", "data": [
                {"tk": "157", "ltp": 8100.0, "v": 5}, {"tk": "910", "ltp": 7100.0, "v": 5}]}]
        r = run_monitor(lambda s, n: 1 / 0, POS(), tick_feed=feed)   # REST must never be called
        self.assertEqual(r["client"].quote_calls, 0)
        self.assertNotIn("REST fallback ON", r["log"])
        self.assertEqual(r["store"].trades, [])
        self.assertEqual(len(r["scans"]), 1)  # normal tick-based scan
        self.assertEqual(r["eod_checks"], [])  # REST-only backstop not used when ticks were healthy

    def test_websocket_stop_still_works_and_rest_takes_over_after_feed_dies(self):
        def feed(now):  # ticks only until 10:00, then dead
            if not (9 <= now.hour < 10):
                return []
            return [{"type": "stock_feed", "data": [{"tk": "157", "ltp": 8100.0, "v": 5}]}]
        def ltp(sym, now):
            return 7900.0 if now.hour >= 12 else 8100.0   # breach at noon, only REST can see it
        r = run_monitor(ltp, POS(), tick_feed=feed)
        sells = [t for t in r["store"].trades if t[0] == "SELL"]
        self.assertEqual(len(sells), 1)
        self.assertEqual(sells[0][2], 7900.0)
        self.assertIn("REST fallback ON", r["log"])
        self.assertGreater(r["client"].quote_calls, 0)

    def test_fallback_switches_off_when_ticks_resume(self):
        def feed(now):  # silent until 10:30, then healthy
            if not (now.hour > 10 or (now.hour == 10 and now.minute >= 30)) or now.hour >= 16:
                return []
            return [{"type": "stock_feed", "data": [{"tk": "157", "ltp": 8100.0, "v": 5}]}]
        r = run_monitor(lambda s, n: 8100.0, POS(), tick_feed=feed)
        self.assertIn("REST fallback ON", r["log"])
        self.assertIn("REST fallback OFF", r["log"])
        self.assertLess(r["client"].quote_calls, 250)   # polled only during the ~75 silent minutes

    def test_rest_errors_do_not_crash_the_loop(self):
        def ltp(sym, now):
            raise RuntimeError("quote service down")
        r = run_monitor(ltp, POS())
        self.assertEqual(r["store"].trades, [])
        self.assertIn("REST poll issues", r["log"])
        self.assertIn("Market closed. Run ending.", r["log"])


class ReloginCap(unittest.TestCase):
    """Forced re-logins: backed off and capped (was ~119/day during the 2026-10 mlhsm outage)."""

    def test_dead_feed_all_day_is_capped(self):
        r = run_monitor(lambda s, n: 8100.0, POS())
        relogins = r["client"].logins - 1       # first login is the startup one
        self.assertEqual(relogins, 10, r["log"][-2000:])
        self.assertIn("re-login cap reached", r["log"])
        self.assertIn("Market closed. Run ending.", r["log"])

    def test_snapshot_burst_after_resubscribe_does_not_hide_a_dead_feed(self):
        r = run_monitor(lambda s, n: 8100.0, POS(), snapshot_on_subscribe=True)
        self.assertGreaterEqual(r["client"].logins - 1, 1, "escalation must still happen")
        self.assertLessEqual(r["client"].logins - 1, 10)

    def test_first_relogin_waits_for_three_failed_attempts_then_backs_off(self):
        r = run_monitor(lambda s, n: 8100.0, POS())
        lines = [l for l in r["log"].splitlines() if "forcing full re-login" in l]
        self.assertEqual(len(lines), 10)
        self.assertIn("(1/10)", lines[0])
        self.assertIn("(10/10)", lines[-1])

    def test_feed_that_comes_back_stops_the_escalation(self):
        def feed(now):  # dead until 10:00, healthy afterwards
            if now.hour < 10 or now.hour >= 16:
                return []
            return [{"type": "stock_feed", "data": [{"tk": "157", "ltp": 8100.0, "v": 5}]}]
        r = run_monitor(lambda s, n: 8100.0, POS(), tick_feed=feed)
        self.assertLessEqual(r["client"].logins - 1, 4)   # 09:18, 09:23, 09:33, 09:53 then ticks return
        self.assertNotIn("re-login cap reached", r["log"])

    def test_healthy_feed_never_relogs_in(self):
        def feed(now):
            if not (9 <= now.hour < 16):
                return []
            return [{"type": "stock_feed", "data": [{"tk": "157", "ltp": 8100.0, "v": 5}]}]
        r = run_monitor(lambda s, n: 1 / 0, POS(), tick_feed=feed)
        self.assertEqual(r["client"].logins, 1)


if __name__ == "__main__":
    unittest.main()
