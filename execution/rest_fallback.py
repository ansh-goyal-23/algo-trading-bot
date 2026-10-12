"""
REST fallback for the full-day monitor (execution/run_daily.py::run_full_day_monitor).

Why (2026-10-05..12): Kotak's `mlhsm` market-data websocket was down for six straight
trading days (Cloudflare 522). The monitor never got a tick, so open positions had NO
stop-loss monitoring and the 3:10 PM scan had nothing to scan ("No ticks collected
today"). Kotak's REST quote API kept working throughout, so when the websocket is not
delivering we poll REST LTP for the HELD positions and run the same stop/target rules,
and at 3:10 PM we build the scan from validated REST candles instead of ticks.

How "the websocket is not delivering" is judged: fewer than MIN_TICKS_IN_WINDOW
stock ticks in the trailing STALE_WINDOW_S seconds. Counting ticks in a window (rather
than "time since the last tick") matters because a dead feed that still emits one stale
snapshot tick per resubscribe (seen 2026-10-02) would otherwise look healthy forever.
Nothing is judged during the first window after observation starts.

This module is pure Python (no Kotak/yfinance/requests imports) so it can be tested with
a simulated clock. The Kotak call itself is injected by the caller.

Known limits (by design):
  * Polling every POLL_EVERY_S seconds can miss a dip that recovers between polls; the
    3:10 PM REST path runs the end-of-day stop check against the day's actual low as a
    backstop (note that backstop fills at the stop price, as it does on every EOD path).
  * A REST price on an unlisted market closure would be the previous session's close;
    execution/market_calendar.py is the primary holiday protection.
"""
from __future__ import annotations

import threading
from collections import deque

# --- tunables ---------------------------------------------------------------
STALE_WINDOW_S = 120          # trailing window used to judge websocket health
MIN_TICKS_IN_WINDOW = 5       # fewer stock ticks than this in the window => unhealthy
POLL_EVERY_S = 30             # REST poll cadence while the fallback is active
REST_SCAN_MIN_ACTIVE_S = 600  # >=10 min of cumulative fallback => scan from REST candles
MAX_PRICE_JUMP = 0.25         # reject a polled price >25% away from the last good one
CALL_TIMEOUT_S = 10           # hard timeout per REST call


def call_with_timeout(fn, timeout, *args, **kwargs):
    """
    Run fn(*args, **kwargs) with a hard wall-clock timeout, in a DAEMON thread.

    Deliberately not a ThreadPoolExecutor: its (non-daemon) workers are joined at
    interpreter exit, so one hung network call would keep the process alive after
    "Run ending" -- the exact failure mode behind the 8h-timeout shutdown hangs.
    A hung daemon thread is simply abandoned.
    """
    box: dict = {}

    def runner():
        try:
            box["value"] = fn(*args, **kwargs)
        except BaseException as e:  # noqa: BLE001 - re-raised in the caller
            box["error"] = e

    t = threading.Thread(target=runner, daemon=True, name="rest-call")
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(f"{getattr(fn, '__name__', fn)} did not return within {timeout}s")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def sane_price(new, last, max_jump: float = MAX_PRICE_JUMP) -> bool:
    """A polled price is usable if positive and not an implausible jump from the last good one."""
    try:
        new = float(new)
    except (TypeError, ValueError):
        return False
    if new <= 0:
        return False
    if last and last > 0 and abs(new / last - 1.0) > max_jump:
        return False
    return True


class RestFallback:
    """State machine: observe() every loop, due() -> poll() while the websocket is unhealthy."""

    def __init__(self, window_s: float = STALE_WINDOW_S, min_ticks: int = MIN_TICKS_IN_WINDOW,
                 poll_every_s: float = POLL_EVERY_S):
        self.window_s = window_s
        self.min_ticks = min_ticks
        self.poll_every_s = poll_every_s

        self._samples: deque = deque()      # (t, cumulative stock-tick count)
        self._last_obs_t = None
        self._last_poll_t = None
        self.active = False
        self.active_seconds_total = 0.0
        self.activations = 0
        self.polls = 0
        self.last_prices: dict = {}
        self.last_errors: list = []

    # -- health -------------------------------------------------------------
    def observe(self, t: float, tick_count: int):
        """
        Record (t, cumulative stock-tick count). Returns "activated" / "deactivated" when the
        fallback switches state, else None. Call about once per monitor-loop iteration.
        """
        if self.active and self._last_obs_t is not None:
            self.active_seconds_total += max(0.0, t - self._last_obs_t)
        self._last_obs_t = t

        self._samples.append((t, tick_count))
        # keep exactly one sample at/before the window start as the baseline
        while len(self._samples) > 1 and self._samples[1][0] <= t - self.window_s:
            self._samples.popleft()

        healthy = True  # nothing is judged until a full window of observation exists
        if t - self._samples[0][0] >= self.window_s:
            healthy = (tick_count - self._samples[0][1]) >= self.min_ticks

        if not healthy and not self.active:
            self.active = True
            self.activations += 1
            self._last_poll_t = None  # poll immediately
            return "activated"
        if healthy and self.active:
            self.active = False
            return "deactivated"
        return None

    # -- polling ------------------------------------------------------------
    def due(self, t: float) -> bool:
        return self.active and (self._last_poll_t is None or t - self._last_poll_t >= self.poll_every_s)

    def poll(self, t: float, symbols, fetch_ltp) -> dict:
        """
        Fetch an LTP for each symbol via ``fetch_ltp(symbol) -> float`` (0/None = no price).
        Returns {symbol: ltp} for prices that passed the sanity check. Errors never raise;
        they are collected in ``last_errors``.
        """
        self._last_poll_t = t
        self.polls += 1
        self.last_errors = []
        out = {}
        for sym in symbols:
            try:
                px = fetch_ltp(sym)
            except Exception as e:  # noqa: BLE001
                self.last_errors.append(f"{sym}: {type(e).__name__}: {e}")
                continue
            if not sane_price(px, self.last_prices.get(sym)):
                self.last_errors.append(f"{sym}: rejected price {px!r} (last good {self.last_prices.get(sym)})")
                continue
            px = float(px)
            self.last_prices[sym] = px
            out[sym] = px
        return out

    # -- 3:10 PM scan -------------------------------------------------------
    def needs_rest_scan(self, n_tick_candles: int) -> bool:
        """Build the 3:10 PM scan from REST candles if ticks gave nothing or coverage was poor."""
        return n_tick_candles == 0 or self.active_seconds_total >= REST_SCAN_MIN_ACTIVE_S

    def summary(self) -> str:
        return (f"fallback active {self.active_seconds_total / 60:.0f} min, "
                f"{self.polls} REST polls, {self.activations} activation(s)")
