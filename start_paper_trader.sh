#!/bin/zsh
cd ~/Documents/algo-trading-bot
source venv/bin/activate

POSITION_FILE="reports/paper_trading/open_positions.csv"

if [ -f "$POSITION_FILE" ]; then
    echo "📂 Open positions found — starting full-day monitor (paper_trader.py)"
    echo "Start this at 9:10 AM and keep it running until 3:30 PM"
    python -m execution.paper_trader
else
    echo "📭 No open positions — running EOD scanner only"
    echo "Run this at 3:20 PM"
    python -m execution.eod_scanner
fi

deactivate
