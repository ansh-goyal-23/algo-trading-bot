"""
Supabase-backed state store — open positions, trade log, intraday
OHLC-building state.

Used by execution/run_daily.py (the Render cron entry point). The
existing local-only scripts (paper_trader.py, eod_scanner.py) are
UNTOUCHED and keep using CSV/JSON files exactly as before — this module
exists specifically because Render's cron job filesystem doesn't persist
between runs, so trading state has to live somewhere durable instead of
on disk.

Talks to Supabase's PostgREST API directly over HTTPS via `requests`,
rather than the `supabase` Python SDK — the SDK pulls in `realtime`,
which requires websockets>=11, conflicting with neo-api-client's hard
websockets==8.1 pin (the same class of conflict documented in
requirements-render-live.txt / run_daily.py's docstring, just via a
different package). Going straight to REST avoids adding any new
dependency at all — `requests` is already needed for Kotak.

Requires SUPABASE_URL and SUPABASE_KEY (the *secret* key — service role
equivalent, not the publishable one) in the environment. The secret key
is required because the `positions`, `trades`, and `ohlc_state` tables
have Row Level Security enabled with no public policies — PostgREST
grants the service-role key BYPASSRLS, so it's the only key that can
read/write these tables at all. Get it from the Supabase dashboard ->
Project Settings -> API — never paste it into chat; set it directly as a
Render environment variable.
"""
import os
from datetime import datetime, timezone
import requests

_TIMEOUT = 15


def _base_url() -> str:
    return os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1"


def _headers(extra: dict = None) -> dict:
    key = os.environ["SUPABASE_KEY"]
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if extra:
        headers.update(extra)
    return headers


def _get(table: str, params: dict) -> list:
    r = requests.get(f"{_base_url()}/{table}", headers=_headers(), params=params, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _upsert(table: str, rows: list, on_conflict: str):
    if not rows:
        return
    headers = _headers({"Prefer": "resolution=merge-duplicates,return=minimal"})
    params = {"on_conflict": on_conflict}
    r = requests.post(f"{_base_url()}/{table}", headers=headers, params=params, json=rows, timeout=_TIMEOUT)
    r.raise_for_status()


def _insert(table: str, row: dict):
    headers = _headers({"Prefer": "return=minimal"})
    r = requests.post(f"{_base_url()}/{table}", headers=headers, json=row, timeout=_TIMEOUT)
    r.raise_for_status()


def _delete(table: str, params: dict):
    r = requests.delete(f"{_base_url()}/{table}", headers=_headers(), params=params, timeout=_TIMEOUT)
    r.raise_for_status()


# ── positions ────────────────────────────────────────────────────────────
def load_positions() -> dict:
    """Returns {symbol: {entry_price, quantity, stop_price, entry_date, partial_exit_done}}"""
    rows = _get("positions", params={"select": "*"})
    return {
        r["symbol"]: {
            "entry_price":       r["entry_price"],
            "quantity":          r["quantity"],
            "stop_price":        r["stop_price"],
            "entry_date":        r["entry_date"],
            "partial_exit_done": bool(r.get("partial_exit_done", False)),
        }
        for r in rows
    }


def save_position(symbol: str, pos: dict):
    row = {
        "symbol":            symbol,
        "entry_price":       pos["entry_price"],
        "quantity":          pos["quantity"],
        "stop_price":        pos["stop_price"],
        "entry_date":        pos["entry_date"],
        "partial_exit_done": pos.get("partial_exit_done", False),
        "updated_at":        datetime.now(timezone.utc).isoformat(),
    }
    _upsert("positions", [row], on_conflict="symbol")


def delete_position(symbol: str):
    _delete("positions", params={"symbol": f"eq.{symbol}"})


# ── trade log ────────────────────────────────────────────────────────────
def log_trade(action: str, symbol: str, price: float, quantity: int, reason: str = ""):
    row = {
        "trade_date": datetime.now().strftime("%Y-%m-%d"),
        "action":     action,
        "symbol":     symbol,
        "price":      round(price, 2),
        "quantity":   quantity,
        "reason":     reason,
    }
    _insert("trades", row)
    emoji = "🟢" if action == "BUY" else "🔴"
    print(f"{emoji} PAPER {action} | {symbol} @ ₹{price:.2f} x {quantity} | {reason}")


def get_trades(trade_date: str = None) -> list:
    params = {"select": "*", "order": "ts"}
    if trade_date:
        params["trade_date"] = f"eq.{trade_date}"
    return _get("trades", params=params)


# ── intraday OHLC-building state ────────────────────────────────────────────
def load_ohlc_state(trade_date: str) -> dict:
    rows = _get("ohlc_state", params={"select": "*", "trade_date": f"eq.{trade_date}"})
    return {
        r["symbol"]: {
            "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"],
            "volume": r["volume"] or 0, "tick_count": r["tick_count"] or 0,
            "first_tick_time": r["first_tick_time"], "last_tick_time": r["last_tick_time"],
        }
        for r in rows
    }


def save_ohlc_state(trade_date: str, candles: dict):
    """candles: {symbol: {open, high, low, close, volume, tick_count,
    first_tick_time, last_tick_time}} — same shape TickAggregator holds
    internally, so it can be passed straight through."""
    if not candles:
        return
    rows = [
        {
            "symbol": sym, "trade_date": trade_date,
            "open": c.get("open"), "high": c.get("high"),
            "low": c.get("low"), "close": c.get("close"),
            "volume": c.get("volume", 0), "tick_count": c.get("tick_count", 0),
            "first_tick_time": c.get("first_tick_time"),
            "last_tick_time": c.get("last_tick_time"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        for sym, c in candles.items()
    ]
    _upsert("ohlc_state", rows, on_conflict="symbol,trade_date")
