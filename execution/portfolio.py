"""
Shared portfolio config and position-management logic.

Used by both paper_trader.py (continuous tick monitoring) and
eod_scanner.py (EOD OHLC-based monitoring) so stop-loss/target rules
and position sizing can't drift between the two entry points.

Portfolio rebuilt 2026-09-22 (superseding the same-day 14-stock reset
below in git history): after raising RISK_PER_TRADE to 0.02, two bugs
were found and fixed:
  1. optimization/portfolio_builder.py's sharpe_weighted()/calmar_weighted()
     had no floor on negative Sharpe/Calmar, so a stock that qualified
     under one risk setting but went negative under another could get a
     nonsensical negative weight and distort every other stock's weight.
     Fixed by clipping negative values to 0 before weighting.
  2. backtest/run_backtest_v2.py's ChecklistStrategyV2 still defaulted
     risk_per_trade=0.015 even after the live value here became 0.02, so
     the "production" backtest pipeline was silently testing a stale risk
     level. Fixed the default to match live (0.02).
Re-ran the full 49-stock backtest with both fixes (RUN_20260922_130143_V2)
and re-ran portfolio_builder.py against it. TATASTEEL (Sharpe -0.339) and
TECHM (Sharpe -1.478) now correctly fail the MIN_SHARPE>=0.3 filter at the
live 2% risk setting and are excluded outright, rather than being kept in
the portfolio with a mis-weighted allocation.
Compared on these corrected, self-consistent numbers (2% risk-per-trade
AND fixed weighting) across candidate sizes over 2024-01-01 to 2026-09-22:
  - Top-5 Sharpe-weighted:   13.27% CAGR, 7.86% weighted max drawdown
  - 13-stock Calmar-weighted: 11.71% CAGR, 9.58% weighted max drawdown
  - 13-stock Sharpe-weighted: 10.89% CAGR, 10.09% weighted max drawdown
  - 13-stock Equal-weighted:   8.77% CAGR, 11.77% weighted max drawdown
Top-5 Sharpe-weighted wins on both CAGR and drawdown, so it's what's live:
APOLLOHOSP, HINDALCO, POWERGRID, EICHERMOT, NTPC (weights 27.60/24.55/
19.01/14.72/14.11%, from each stock's Sharpe ratio relative to the group).
"""
import os
import pyotp
from neo_api_client import NeoAPI

PORTFOLIO = {
    "APOLLOHOSP": 27600,
    "HINDALCO":   24550,
    "POWERGRID":  19010,
    "EICHERMOT":  14720,
    "NTPC":       14110,
}

STOP_LOSS_PCT  = 0.02
RISK_PER_TRADE = 0.02   # raised from 0.015 on 2026-09-22: exit-variant sweep
                        # (reports/EXITVAR_20260922_123423) identified this as the
                        # most robust improvement lever tested (exit/sizing only,
                        # no shorting). Corrected top-5 Sharpe-weighted portfolio
                        # backtest (RUN_20260922_130143_V2, self-consistent with
                        # this setting) shows 40.42% total return / 13.27% CAGR
                        # over 2024-01-01 to 2026-09-22, 7.86% weighted max
                        # drawdown. Same entries/exits/stop distance as before —
                        # this only scales position size, so it also scales
                        # losses proportionally if the edge doesn't hold OOS.


def get_position_size(symbol, price, portfolio=PORTFOLIO):
    """
    Risk-based position sizing: risk RISK_PER_TRADE of the symbol's allocated
    capital per trade, sized to the stop distance.

    Returns 0 if even a single share would cost more than the symbol's
    allocated capital — sizing can't be done sensibly, so skip the trade
    rather than force a 1-share position that blows the capital allocation.
    """
    capital = portfolio.get(symbol, 0)
    if capital <= 0 or price <= 0:
        return 0
    risk_amt  = capital * RISK_PER_TRADE
    stop_dist = price * STOP_LOSS_PCT
    size = int(risk_amt / stop_dist)
    if size < 1:
        if price > capital:
            return 0
        size = 1
    return size


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


def check_position_exit(pos, low, high, close):
    """
    Evaluate stop-loss / partial-exit(+4%) / full-exit(+6%) rules for one
    open position given the price range observed. For live tick monitoring
    pass low=high=close=ltp; for EOD bars pass the day's actual low/high/close.

    Mutates `pos` in place for the partial-exit case (reduces quantity,
    marks partial_exit_done, moves stop to breakeven) so callers don't
    have to duplicate that bookkeeping.

    Returns None if nothing triggered, otherwise:
      {"action": "STOP" | "TARGET1_PARTIAL" | "TARGET1_PROTECT" | "TARGET2",
       "quantity": <shares to log as sold — 0 for TARGET1_PROTECT>,
       "trigger_price": <price level that triggered this, for EOD fill assumptions>}

    Single-share positions never get a 0-quantity "partial" exit — a
    1-share position can't be split, so TARGET1_PROTECT just moves the
    stop to breakeven and leaves the full share open to run to target2.
    """
    entry   = pos["entry_price"]
    target1 = round(entry * 1.04, 2)
    target2 = round(entry * 1.06, 2)

    if low <= pos["stop_price"]:
        return {"action": "STOP", "quantity": pos["quantity"], "trigger_price": pos["stop_price"]}

    if high >= target1 and not pos.get("partial_exit_done"):
        qty = pos["quantity"]
        pos["partial_exit_done"] = True
        pos["stop_price"] = round(entry * 1.001, 2)
        if qty > 1:
            partial_qty = max(1, qty // 2)
            pos["quantity"] -= partial_qty
            return {"action": "TARGET1_PARTIAL", "quantity": partial_qty, "trigger_price": target1}
        return {"action": "TARGET1_PROTECT", "quantity": 0, "trigger_price": target1}

    if high >= target2 and pos.get("partial_exit_done"):
        return {"action": "TARGET2", "quantity": pos["quantity"], "trigger_price": target2}

    return None
