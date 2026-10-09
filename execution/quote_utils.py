"""
Pure-Python helpers that turn Kotak Neo quote responses into *validated*
daily candles for the EOD scan (execution/run_daily.py, execution/eod_scanner.py).

Why this exists (2026-10-09): ``client.quotes(..., quote_type="ohlc")`` returns
only ``{"exchange_token", "display_symbol", "exchange", "ohlc": {open, high,
low, close}}`` -- there is NO ``ltp`` and NO volume in that response, and
``ohlc["close"]`` is the PREVIOUS session's close (open/high/low are today's).
The old code did ``close = ltp if ltp > 0 else ohlc["close"]``, so ltp was always
0 and every EOD candle silently became "today's O/H/L + yesterday's close, volume
0" -- which fed corrupted candlestick patterns/RSI/volume into the scan and
produced entry prices equal to the previous close. See
claude/eod-stale-entry-price-finding-2026-10-09.md in the project docs.

Rules enforced here:
  * ohlc["close"] is NEVER used as a close. A close must come from a real LTP.
  * A candle is only accepted if prices are positive and internally consistent
    (low <= open/close <= high).
  * Anything rejected is reported with a reason so callers can log it loudly and
    fall back to another source (yfinance) or skip the symbol -- never trade on
    a candle that failed validation.

No third-party imports, so it can be unit-tested anywhere.
"""
from __future__ import annotations

# Keys under which a last-traded price might appear in a quote dict.
_LTP_KEYS = ("ltp", "last_traded_price", "lastTradedPrice", "last_price", "lastPrice")

# Relative tolerance for "close is inside [low, high]" style checks (0.05%).
_TOL = 0.0005


def _num(value) -> float:
    """Best-effort float() for values like '7950.0000', '1,234.5', None."""
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def first_quote(resp) -> dict | None:
    """Normalise the various response shapes to a single quote dict."""
    if resp is None:
        return None
    if isinstance(resp, dict):
        if "data" in resp:
            resp = resp["data"]
        else:
            return resp
    if isinstance(resp, list):
        for item in resp:
            if isinstance(item, dict):
                return item
        return None
    return None


def parse_ltp(resp) -> float:
    """Last traded price from a quote response, or 0.0 if absent/invalid."""
    q = first_quote(resp)
    if not q:
        return 0.0
    for key in _LTP_KEYS:
        if key in q:
            v = _num(q[key])
            if v > 0:
                return v
    return 0.0


def parse_ohlc_fields(resp) -> dict | None:
    """
    Today's open/high/low plus the previous close from an ``ohlc`` quote.
    ``prev_close`` is returned for diagnostics only -- never use it as a close.
    """
    q = first_quote(resp)
    if not q:
        return None
    o = q.get("ohlc")
    if not isinstance(o, dict):
        return None
    return {
        "open": _num(o.get("open")),
        "high": _num(o.get("high")),
        "low": _num(o.get("low")),
        "prev_close": _num(o.get("close")),
    }


def candle_problem(c: dict | None) -> str | None:
    """Return a human-readable reason the candle is unusable, or None if OK."""
    if not c:
        return "no candle"
    try:
        o, h, l, cl = (float(c[k]) for k in ("open", "high", "low", "close"))
    except (KeyError, TypeError, ValueError):
        return "missing/non-numeric OHLC fields"
    if min(o, h, l, cl) <= 0:
        return f"non-positive price (O={o} H={h} L={l} C={cl})"
    if h < l * (1 - _TOL):
        return f"high < low (H={h} L={l})"
    top, bottom = h * (1 + _TOL), l * (1 - _TOL)
    if not (bottom <= cl <= top):
        return f"close outside day range (C={cl} L={l} H={h})"
    if not (bottom <= o <= top):
        return f"open outside day range (O={o} L={l} H={h})"
    return None


def candle_is_valid(c: dict | None) -> bool:
    return candle_problem(c) is None


def build_kotak_candle(ohlc_resp, ltp_resp, date: str) -> tuple[dict | None, str]:
    """
    Build a validated daily candle from Kotak responses.

    ``ohlc_resp``: response of quotes(quote_type="ohlc")  (today's O/H/L)
    ``ltp_resp``:  response of quotes(quote_type="ltp")   (real close source);
                   may be None. An ``ltp`` present in ``ohlc_resp`` is also used
                   if ``ltp_resp`` has none.

    Returns (candle, "") on success or (None, reason) on rejection. Volume is
    always 0 here -- Kotak's ohlc quote carries none; callers should fill it from
    another source (see fill_volume()).
    """
    fields = parse_ohlc_fields(ohlc_resp)
    if fields is None:
        return None, "no 'ohlc' block in quote response"
    ltp = parse_ltp(ltp_resp) or parse_ltp(ohlc_resp)
    if ltp <= 0:
        return None, ("no usable LTP in the quote response(s) -- refusing to fall "
                      "back to ohlc['close'] (that is the previous close)")
    candle = {
        "date": date,
        "open": fields["open"],
        "high": fields["high"],
        "low": fields["low"],
        "close": ltp,
        "volume": 0,
    }
    problem = candle_problem(candle)
    if problem:
        return None, problem
    return candle, ""


def accept_fallback_candle(row: dict | None, today: str) -> tuple[dict | None, str]:
    """
    Validate a candle from a fallback source (yfinance) for use as *today's*.
    Its date must equal ``today`` (a stale last row -- e.g. on a holiday -- would
    otherwise be silently mislabelled as today's) and it must pass candle checks.
    """
    if not row:
        return None, "no row"
    if str(row.get("date")) != today:
        return None, f"row dated {row.get('date')}, not {today} (stale / no session today)"
    problem = candle_problem(row)
    if problem:
        return None, problem
    return row, ""


def fill_volume(candle: dict, fallback_row: dict | None, today: str) -> bool:
    """
    Fill candle['volume'] from a same-day fallback row (yfinance volume units match
    the 6-month history the scan appends to). Returns True if volume was set.
    """
    if not fallback_row or str(fallback_row.get("date")) != today:
        return False
    try:
        vol = int(fallback_row.get("volume", 0))
    except (TypeError, ValueError):
        return False
    if vol <= 0:
        return False
    candle["volume"] = vol
    return True
