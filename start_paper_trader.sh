#!/bin/zsh
cd ~/Documents/algo-trading-bot
source venv/bin/activate

POSITION_FILE="reports/paper_trading/open_positions.csv"

# keep Mac awake during market hours (prevents sleep killing connection)
caffeinate -i &
CAFFEINATE_PID=$!
echo "☕ Mac kept awake (caffeinate PID: $CAFFEINATE_PID)"

cleanup() {
    kill $CAFFEINATE_PID 2>/dev/null
    echo "☕ caffeinate stopped"
}
trap cleanup EXIT

if [ -f "$POSITION_FILE" ]; then
    echo "📂 Open positions found — starting full-day monitor"
    echo "Auto-restart enabled — will recover from crashes automatically"
    echo "Press Ctrl+C to stop manually\n"

    # auto-restart loop — restarts on crash, stops at market close
    while true; do
        python -m execution.paper_trader
        EXIT_CODE=$?

        NOW=$(date +%H%M)
        if [ $NOW -ge 1530 ]; then
            echo "✅ Market closed — stopping auto-restart"
            break
        fi

        if [ $EXIT_CODE -eq 0 ]; then
            # check if market is still open — if yes, restart anyway
            NOW=$(date +%H%M)
            if [ $NOW -lt 1530 ]; then
                echo "⚠️  Script exited cleanly but market still open — restarting..."
            else
                echo "✅ Script exited cleanly"
                break
            fi
        fi

        echo "⚠️  Script crashed (exit code $EXIT_CODE) — restarting in 10 seconds..."
        sleep 10
    done

else
    echo "📭 No open positions — running EOD scanner only"
    echo "Run this at 3:20 PM\n"
    python -m execution.eod_scanner
fi

deactivate
