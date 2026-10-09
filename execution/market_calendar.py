"""
NSE trading-day guard (static layer).

Why (2026-10-02): the weekday-only cron fired on an NSE holiday (Gandhi Jayanti).
The websocket still delivered stale snapshot ticks (last close, volume 0) on every
resubscribe, and the bot booked two PHANTOM stop-outs and ran a 3:10 PM scan on
flat stale data. See claude/eod-stale-entry-price-finding-2026-10-09.md.

Layers:
  1. THIS module -- a maintained list of NSE equity-segment trading holidays.
     execution/run_daily.py::main() and execution/eod_scanner.py::main() call
     ``holiday_reason()`` first and skip the whole run on a non-trading day.
  2. Dynamic check in the EOD path (quote_utils.session_confirmed + fetch_today_ohlc):
     if yfinance returns rows but none is dated today, there was no session today
     (catches special/unlisted closures) and the scan is skipped.

MAINTENANCE: update NSE_HOLIDAYS each year from NSE's published holiday circular
(https://www.nseindia.com/resources/exchange-communication-holidays) and add the
year to MAINTAINED_YEARS. If a run happens in a year that is NOT listed there,
``calendar_covers()`` is False and callers log a loud warning (only the dynamic
layer protects those days).

Not covered: Muhurat trading (Sun 2026-11-08, evening special session) -- the
weekday cron never runs on Sundays, and this bot does not trade that session.

No third-party imports -- unit-testable anywhere.
"""
from __future__ import annotations

from datetime import date

# NSE equity-segment trading holidays falling on weekdays. 2026 list cross-checked
# against two published copies (cleartax.in, tatamutualfund.com) on 2026-10-09;
# 2026-10-02 (Gandhi Jayanti) is the day this bot traded by mistake. Verify against
# the NSE circular when updating.
NSE_HOLIDAYS: dict[str, str] = {
    # 2026-01-15 (Thu, Maharashtra municipal elections) is listed by one of the two
    # sources only; it is in the past and harmless to keep.
    "2026-01-15": "Maharashtra municipal elections",
    "2026-01-26": "Republic Day",
    "2026-03-03": "Holi",
    "2026-03-26": "Shri Ram Navami",
    "2026-03-31": "Shri Mahavir Jayanti",
    "2026-04-03": "Good Friday",
    "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2026-05-01": "Maharashtra Day",
    "2026-05-28": "Bakri Id",
    "2026-06-26": "Muharram",
    "2026-09-14": "Ganesh Chaturthi",
    "2026-10-02": "Mahatma Gandhi Jayanti",
    "2026-10-20": "Dussehra",
    "2026-11-10": "Diwali (Balipratipada)",
    "2026-11-24": "Prakash Gurpurb Sri Guru Nanak Dev",
    "2026-12-25": "Christmas",
}

MAINTAINED_YEARS = {2026}


def holiday_reason(d: date) -> str | None:
    """Reason ``d`` is NOT a trading day ("weekend" / "NSE holiday: ..."), else None."""
    if d.weekday() >= 5:
        return "weekend"
    name = NSE_HOLIDAYS.get(d.isoformat())
    if name:
        return f"NSE holiday: {name}"
    return None


def calendar_covers(d: date) -> bool:
    """True if the holiday list is maintained for ``d``'s year."""
    return d.year in MAINTAINED_YEARS
