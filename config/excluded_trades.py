"""
Trades that must be EXCLUDED from any performance / win-rate / PnL numbers.

These rows stay in the Supabase ``trades`` table (nothing is deleted -- they are
the audit trail), but anything that computes live performance should read trades
through ``execution.state_store.get_trades()`` (which filters these out by
default) or call ``filter_valid_trades()`` directly.

2026-10-09 (Ansh's call): the 2026-10-01 EOD-path entries were priced and
signalled off a corrupted candle (the EOD quote parser used the PREVIOUS close as
"today's close" -- see claude/eod-stale-entry-price-finding-2026-10-09.md), and
the 2026-10-02 SELLs are phantom stop-outs triggered on an NSE holiday by stale
snapshot ticks. The still-open APOLLOHOSP position is trade 8's entry.

2026-10-09 (Ansh's call, later): ids 6 and 7 (APOLLOHOSP BUY 2026-09-29 @ 8860.0 =
the stale 09-28 close, and its 09-30 stop-out) excluded too -- same bug.

Candidates NOT yet excluded (pending Ansh's decision): ids 2 and 3 (2026-09-24
EOD-path entries, same buggy path but not verifiable; their exits, ids 4/5, were
tick-driven).
"""

EXCLUDED_TRADE_IDS = {
    6:  "2026-09-29 BUY APOLLOHOSP @8860.0 -- stale-quote entry (= 09-28 close; real 09-29 close 8659.0); 'Hammer' signal was an artifact",
    7:  "2026-09-30 SELL APOLLOHOSP @8610.0 -- stop-out of the stale-quote entry (id 6); opening gap",
    8:  "2026-10-01 BUY APOLLOHOSP @8165.5 -- stale-quote entry (real close 8133.5); also the open position",
    9:  "2026-10-01 BUY POWERGRID @260.5 -- stale-quote entry (real close ~254.55)",
    10: "2026-10-01 BUY EICHERMOT @7150.0 -- stale-quote entry (real close ~6920)",
    11: "2026-10-02 SELL EICHERMOT @6920.0 -- phantom stop-out on NSE holiday (stale snapshot tick)",
    12: "2026-10-02 SELL POWERGRID @254.55 -- phantom stop-out on NSE holiday (stale snapshot tick)",
}


def filter_valid_trades(trades):
    """Drop rows whose ``id`` is in EXCLUDED_TRADE_IDS. Input is left untouched."""
    return [t for t in trades if t.get("id") not in EXCLUDED_TRADE_IDS]
