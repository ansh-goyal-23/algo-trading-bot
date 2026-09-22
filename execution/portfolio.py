"""
Shared portfolio config and position-management logic.

Used by both paper_trader.py (continuous tick monitoring) and
eod_scanner.py (EOD OHLC-based monitoring) so stop-loss/target rules
and position sizing can't drift between the two entry points.

Portfolio rebuilt 2026-09-22: full re-sweep of strategy parameters
(min_confirmations/stop_loss_pct/risk_per_trade) confirmed the existing
3 / 2% / 1.5% set is still optimal (avg Sharpe across all 49 Nifty50
stocks, no better combo in the grid). Fresh V2 backtest run
(RUN_20260922_115213_V2) against data refreshed through 2026-09-22,
then portfolio_builder.py run WITHOUT the previous MAX_STOCKS=5 cap
(same filters: return>=5%, drawdown<=20%, win rate>=35%, Sharpe>=0.3) —
14 stocks qualified, Sharpe-weighted allocation chosen (highest simulated
return of the three weighting schemes: 24.8% vs 18.7% equal-weight vs
24.4% Calmar-weight).
"""
import os
import pyotp
from neo_api_client import NeoAPI

PORTFOLIO = {
    "NTPC":       17840,
    "APOLLOHOSP": 17270,
    "GRASIM":     13310,
    "EICHERMOT":  10760,
    "TATASTEEL":  6170,
    "ONGC":       4930,
    "SBILIFE":    4600,
    "TECHM":      4330,
    "CIPLA":      4310,
    "INFY":       4230,
    "NESTLEIND":  3740,
    "HINDALCO":   2980,
    "HCLTECH":    2800,
    "MARUTI":     2740,
}

STOP_LOSS_PCT  = 0.02
RISK_PER_TRADE = 0.015


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
