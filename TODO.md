# Project TODO — Future Development

## Current Status
The swing trading research platform is complete and paper trading is active.
Live trading integration is the next step after paper trading validation.

---

## IMMEDIATE NEXT STEPS (before going live)

- [ ] Paper trade for minimum 2-3 months
- [ ] Validate real-time signals match backtest expectations
- [ ] Confirm stop loss monitoring works correctly on carried positions
- [ ] Build weekly paper trading summary script
- [ ] Go live on swing with small capital (₹50,000) after paper validation
- [ ] Confirm SEBI algo tagging requirement with Kotak Neo before placing real orders

---

## LIVE TRADING INTEGRATION (swing, next major feature)

- [ ] Connect Zerodha Kite or Kotak Neo order placement API
- [ ] Implement order placement in `execution/live_trader.py`
- [ ] Add bracket order support (entry + stop + target in one order)
- [ ] Add order status tracking (filled, rejected, partial)
- [ ] Add daily P&L tracking against paper trading baseline
- [ ] Implement daily re-auth token refresh (Kotak tokens expire daily)
- [ ] Add SMS/email alerts for fills, stop hits, errors
- [ ] Add circuit breaker — stop all trading if daily loss exceeds X%

---

## INTRADAY TRADING (future — do not start before swing is profitable)

### Prerequisites before starting intraday
- [ ] Swing strategy live and consistently profitable for 3+ months
- [ ] Intraday backtesting complete and validated
- [ ] Infrastructure upgraded (cloud VM or dedicated machine)

### Data Layer changes
- [ ] Replace `TickAggregator` with rolling N-minute candle builder
      - Closes a new OHLC bar every 5 minutes from live ticks
      - Immediately feeds completed bar to strategy pipeline
- [ ] Fetch 5-minute historical data from yfinance (last 60 days free)
      - Use for intraday backtesting
- [ ] Add candle alignment — ensure bars close at exact :00/:05/:10 etc.
- [ ] Add pre-market filter — ignore ticks before 9:30 AM (avoid opening volatility)

### Strategy Layer changes
- [ ] Retune indicators for 5-minute timeframe:
      - RSI period: 14 → 7 or 9
      - EMA period: 20 → 9 or 13
      - Volume filter: compare to 20-bar rolling avg instead of daily avg
- [ ] Raise min_confirmations: 3/4 → 4/4 (more noise on shorter timeframes)
- [ ] Add time-of-day filters:
      - No entries 9:15–9:30 AM (opening volatility)
      - No entries after 3:00 PM (erratic pre-close behavior)
- [ ] Re-run parameter optimization on 5-min data
- [ ] Re-run multi-stock runner on 5-min data to find intraday-compatible stocks

### Execution Layer changes
- [ ] Mandatory square off by 3:15 PM — no overnight carry
- [ ] Switch product type: CNC → MIS (intraday margin product)
- [ ] Implement bracket orders (entry + SL + target in single order)
- [ ] Signal → order latency target: under 1 second
- [ ] Add partial fill handling
- [ ] Add auto square-off fallback at 3:14 PM if signal exit hasn't triggered

### Risk Management changes
- [ ] Tighten stop loss: 2% → 0.3–0.5%
- [ ] Tighten target: 4–6% → 0.6–1%
- [ ] Add max trades per day per stock (cap at 3–5)
- [ ] Add max trades per day total across portfolio
- [ ] Add daily loss limit circuit breaker (e.g. stop if down ₹2,000 in a day)
- [ ] Recalculate position sizing for intraday margin (up to 5x leverage available)
- [ ] Account for higher brokerage impact:
      - At ₹20/order flat, 10 trades/day = ₹200/day minimum cost
      - Average trade profit must comfortably exceed ₹40 per trade

### Backtesting changes
- [ ] Switch backtest data feed to 5-minute interval
- [ ] Add intraday-specific commission model (brokerage + STT + exchange fees)
- [ ] Add market impact simulation for illiquid stocks
- [ ] Add time-of-day filter in backtrader strategy
- [ ] Validate backtest results on out-of-sample data (recent 2 months)

### Infrastructure changes
- [ ] Move to always-on machine (AWS t3.micro or dedicated mini-PC)
      - MacBook not suitable — may sleep, lose connection mid-session
- [ ] Add websocket auto-reconnect logic (reconnect within 5 seconds if dropped)
- [ ] Add heartbeat monitor — alert if no ticks received for 60+ seconds
- [ ] Add logging to database (SQLite or PostgreSQL) instead of CSV only
- [ ] Add real-time dashboard (simple Flask or Streamlit app)

### Regulatory
- [ ] Confirm SEBI intraday algo tagging requirements with Kotak Neo
- [ ] MIS product type has broker auto square-off at 3:15 PM — confirm timing
- [ ] Higher trade frequency may trigger additional exchange scrutiny

---

## ANALYTICS IMPROVEMENTS (any time)

- [ ] Weekly paper trading summary script
      - Reads all daily paper trade CSVs
      - Consolidated P&L, open positions, signals fired
      - Email/print friendly format
- [ ] Add Calmar ratio to HTML report
- [ ] Add equity curve chart to HTML report (matplotlib → embed as base64)
- [ ] Add Monte Carlo simulation for portfolio risk estimation
- [ ] Add correlation analysis between portfolio stocks
- [ ] Benchmark comparison — strategy return vs Nifty 50 buy-and-hold

---

## STRATEGY IMPROVEMENTS (research phase)

- [ ] Add Fibonacci retracement levels as a 5th filter (Varsity Module 2 Ch.15)
- [ ] Add Dow Theory trend confirmation (Varsity Module 2 Ch.4)
- [ ] Add support/resistance detection using swing highs/lows
- [ ] Test morning star / evening star patterns (3-candle patterns)
- [ ] Test strategy on Nifty 50 index options (requires F&O knowledge)
- [ ] Add sector rotation logic — rotate into strongest sectors quarterly

---

## KNOWN ISSUES / TECHNICAL DEBT

- [ ] `backtest/run_backtest.py` is frozen — future strategy changes need
      a new versioned strategy file, not edits to this file
- [ ] `scripts/run_all_stocks.py` rebuilds cerebro manually instead of
      calling `bt_run()` — consolidate once backtest API is stabilized
- [ ] Paper trader signal scan runs in subprocess calling venv-data python —
      consider a cleaner IPC mechanism for production
- [ ] Historical data in `data/historical/` will go stale — add a weekly
      auto-refresh script using yfinance
- [ ] TRENT had a ₹26,647 loss on a single gap-down — consider adding
      gap risk filter (skip trades where stock gapped >3% at open)

---

## NOTES

- Never modify `backtest/run_backtest.py` strategy logic directly.
  Build around it using analyzers and runners.
- Always paper trade any strategy change for minimum 4 weeks before
  committing real capital.
- The 2% stop loss causes most losses — consider wider stops (2.5–3%)
  with proportionally smaller position sizes in the next optimization round.
- Intraday is significantly harder than swing. Do not rush to it.
  Swing profitability for 3+ months is the prerequisite.
